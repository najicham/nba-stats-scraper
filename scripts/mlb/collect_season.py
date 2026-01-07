#!/usr/bin/env python3
"""
MLB Season Data Collection

Collects MLB season data and stores in BigQuery:
- Game lineups (mlb_game_lineups, mlb_lineup_batters)
- Pitcher game stats (for validation/target variable)
- Batter K rates with platoon splits

Usage:
    # Collect 2025 season (most recent - RECOMMENDED)
    python scripts/mlb/collect_season.py --season 2025

    # Collect 2024 season (for additional training data)
    python scripts/mlb/collect_season.py --season 2024

    # Collect specific month
    python scripts/mlb/collect_season.py --season 2025 --month 8

    # Resume from checkpoint
    python scripts/mlb/collect_season.py --season 2025 --resume

    # Dry run (no BigQuery writes)
    python scripts/mlb/collect_season.py --season 2025 --dry-run --limit 10
"""

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MLB Stats API endpoints
MLB_SCHEDULE_API = "https://statsapi.mlb.com/api/v1/schedule"
MLB_GAME_API = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

# MLB Season dates by year
SEASON_DATES = {
    2024: (date(2024, 3, 28), date(2024, 9, 29)),  # 2024 Opening Day to end
    2025: (date(2025, 3, 27), date(2025, 9, 28)),  # 2025 Opening Day to end
}

# Checkpoint directory
CHECKPOINT_DIR = "/tmp/mlb_backfill_checkpoints"
CHECKPOINT_FILE = f"{CHECKPOINT_DIR}/checkpoint.json"  # Default checkpoint file


@dataclass
class GameData:
    """Complete game data for storage."""
    game_pk: int
    game_date: str
    game_time_utc: Optional[str]
    away_team_id: int
    away_team_abbr: str
    away_team_name: str
    home_team_id: int
    home_team_abbr: str
    home_team_name: str
    venue_name: str
    status_code: str
    away_lineup: List[Dict]
    home_lineup: List[Dict]
    away_pitchers: List[Dict]
    home_pitchers: List[Dict]


@dataclass
class CollectionProgress:
    """Track collection progress."""
    total_dates: int = 0
    processed_dates: int = 0
    total_games: int = 0
    games_with_lineups: int = 0
    total_pitcher_starts: int = 0
    errors: List[str] = field(default_factory=list)
    last_date_processed: Optional[str] = None


class CheckpointManager:
    """Manages checkpoint state for resumable collection."""

    def __init__(self, checkpoint_file: str = CHECKPOINT_FILE):
        self.checkpoint_file = checkpoint_file
        os.makedirs(os.path.dirname(checkpoint_file), exist_ok=True)

    def save(self, progress: CollectionProgress, completed_dates: List[str]):
        """Save checkpoint to disk."""
        data = {
            'progress': asdict(progress),
            'completed_dates': completed_dates,
            'saved_at': datetime.utcnow().isoformat()
        }
        with open(self.checkpoint_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Checkpoint saved: {len(completed_dates)} dates complete")

    def load(self) -> Tuple[Optional[CollectionProgress], List[str]]:
        """Load checkpoint from disk."""
        if not os.path.exists(self.checkpoint_file):
            return None, []

        try:
            with open(self.checkpoint_file, 'r') as f:
                data = json.load(f)

            progress = CollectionProgress(**data['progress'])
            completed_dates = data['completed_dates']
            logger.info(f"Loaded checkpoint: {len(completed_dates)} dates already complete")
            return progress, completed_dates
        except Exception as e:
            logger.warning(f"Error loading checkpoint: {e}")
            return None, []

    def clear(self):
        """Clear checkpoint file."""
        if os.path.exists(self.checkpoint_file):
            os.remove(self.checkpoint_file)


class MLBDataCollector:
    """Collects game data from MLB Stats API."""

    def __init__(self, rate_limit_delay: float = 0.3):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'mlb-season-collector/1.0'
        })
        self.rate_limit_delay = rate_limit_delay

    def get_season_schedule(self, start_date: date, end_date: date) -> List[Dict]:
        """Get all games for a date range."""
        all_games = []
        current = start_date

        while current <= end_date:
            # Fetch in monthly chunks for efficiency
            month_end = min(
                date(current.year, current.month + 1, 1) - timedelta(days=1)
                if current.month < 12 else date(current.year, 12, 31),
                end_date
            )

            url = (f"{MLB_SCHEDULE_API}?sportId=1"
                   f"&startDate={current.isoformat()}"
                   f"&endDate={month_end.isoformat()}"
                   f"&gameTypes=R,P")  # Regular + Postseason

            try:
                resp = self.session.get(url, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                for date_entry in data.get('dates', []):
                    for game in date_entry.get('games', []):
                        if game.get('status', {}).get('abstractGameCode') == 'F':
                            all_games.append({
                                'game_pk': game['gamePk'],
                                'game_date': date_entry['date'],
                                'away_team': game.get('teams', {}).get('away', {}).get('team', {}).get('name'),
                                'home_team': game.get('teams', {}).get('home', {}).get('team', {}).get('name'),
                            })

                time.sleep(self.rate_limit_delay)
            except Exception as e:
                logger.error(f"Error fetching schedule for {current}: {e}")

            # Move to next month
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)

        logger.info(f"Found {len(all_games)} completed games in date range")
        return all_games

    def get_games_for_date(self, game_date: str) -> List[int]:
        """Get all completed game IDs for a specific date."""
        url = f"{MLB_SCHEDULE_API}?sportId=1&date={game_date}&gameTypes=R,P"

        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            game_pks = []
            for date_entry in data.get('dates', []):
                for game in date_entry.get('games', []):
                    if game.get('status', {}).get('abstractGameCode') == 'F':
                        game_pks.append(game['gamePk'])

            return game_pks
        except Exception as e:
            logger.error(f"Error fetching games for {game_date}: {e}")
            return []

    def get_game_data(self, game_pk: int) -> Optional[GameData]:
        """Get full game data including lineups and pitcher stats."""
        url = MLB_GAME_API.format(game_pk=game_pk)

        try:
            time.sleep(self.rate_limit_delay)
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            return self._parse_game_data(data)
        except Exception as e:
            logger.error(f"Error fetching game {game_pk}: {e}")
            return None

    def _parse_game_data(self, data: Dict) -> Optional[GameData]:
        """Parse game data from API response."""
        try:
            game_data = data.get('gameData', {})
            live_data = data.get('liveData', {})
            boxscore = live_data.get('boxscore', {})

            game_pk = game_data.get('game', {}).get('pk')
            if not game_pk:
                return None

            datetime_info = game_data.get('datetime', {})
            venue = game_data.get('venue', {})
            status = game_data.get('status', {})
            teams = boxscore.get('teams', {})

            away = teams.get('away', {})
            home = teams.get('home', {})

            return GameData(
                game_pk=game_pk,
                game_date=datetime_info.get('originalDate'),
                game_time_utc=datetime_info.get('dateTime'),
                away_team_id=away.get('team', {}).get('id'),
                away_team_abbr=away.get('team', {}).get('abbreviation', 'UNK'),
                away_team_name=away.get('team', {}).get('name', 'Unknown'),
                home_team_id=home.get('team', {}).get('id'),
                home_team_abbr=home.get('team', {}).get('abbreviation', 'UNK'),
                home_team_name=home.get('team', {}).get('name', 'Unknown'),
                venue_name=venue.get('name', 'Unknown'),
                status_code=status.get('statusCode', 'F'),
                away_lineup=self._extract_lineup(away, game_data),
                home_lineup=self._extract_lineup(home, game_data),
                away_pitchers=self._extract_pitchers(away, game_data),
                home_pitchers=self._extract_pitchers(home, game_data),
            )
        except Exception as e:
            logger.error(f"Error parsing game data: {e}")
            return None

    def _extract_lineup(self, team_data: Dict, game_data: Dict) -> List[Dict]:
        """Extract starting lineup with player details."""
        lineup = []
        batters = team_data.get('batters', [])
        players = team_data.get('players', {})
        all_players = game_data.get('players', {})

        for player_id in batters:
            player_key = f'ID{player_id}'
            player_data = players.get(player_key, {})
            batting_order_raw = player_data.get('battingOrder')

            if not batting_order_raw:
                continue

            order = int(batting_order_raw) // 100
            if order < 1 or order > 9:
                continue

            person = player_data.get('person', {})
            position = player_data.get('position', {})

            # Get batter handedness from game data
            bats = 'R'  # Default
            full_player_key = f'ID{player_id}'
            if full_player_key in all_players:
                bats = all_players[full_player_key].get('batSide', {}).get('code', 'R')

            lineup.append({
                'player_id': person.get('id'),
                'player_name': person.get('fullName', 'Unknown'),
                'batting_order': order,
                'position': position.get('abbreviation', 'UNK'),
                'bats': bats,
            })

        # Sort and dedupe by batting order
        lineup.sort(key=lambda x: x['batting_order'])
        seen = set()
        unique = []
        for b in lineup:
            if b['batting_order'] not in seen:
                seen.add(b['batting_order'])
                unique.append(b)

        return unique[:9]

    def _extract_pitchers(self, team_data: Dict, game_data: Dict) -> List[Dict]:
        """Extract pitchers with their stats."""
        pitchers_list = []
        pitchers = team_data.get('pitchers', [])
        players = team_data.get('players', {})
        all_players = game_data.get('players', {})

        for i, player_id in enumerate(pitchers):
            player_key = f'ID{player_id}'
            player_data = players.get(player_key, {})
            person = player_data.get('person', {})
            stats = player_data.get('stats', {}).get('pitching', {})

            # Get pitcher handedness
            throws = 'R'  # Default
            full_player_key = f'ID{player_id}'
            if full_player_key in all_players:
                throws = all_players[full_player_key].get('pitchHand', {}).get('code', 'R')

            # Parse innings pitched
            ip_str = stats.get('inningsPitched', '0')
            try:
                if '.' in str(ip_str):
                    whole, frac = str(ip_str).split('.')
                    ip = float(whole) + float(frac) / 3
                else:
                    ip = float(ip_str)
            except:
                ip = 0.0

            pitchers_list.append({
                'player_id': person.get('id'),
                'player_name': person.get('fullName', 'Unknown'),
                'throws': throws,
                'is_starter': i == 0,
                'innings_pitched': ip,
                'strikeouts': stats.get('strikeOuts', 0),
                'hits': stats.get('hits', 0),
                'walks': stats.get('baseOnBalls', 0),  # Walks allowed
                'earned_runs': stats.get('earnedRuns', 0),
                'pitch_count': stats.get('pitchesThrown', 0),
            })

        return pitchers_list


class BatterKRateProvider:
    """Provides batter K rates with platoon splits from pybaseball."""

    def __init__(self, season: int = 2024):
        self.season = season
        self.overall_k_rates: Dict[str, float] = {}
        self.vs_lhp_k_rates: Dict[str, float] = {}
        self.vs_rhp_k_rates: Dict[str, float] = {}
        self.league_avg = 0.23
        self._loaded = False

    def load_k_rates(self) -> None:
        """Load K rates from pybaseball (FanGraphs + Statcast)."""
        if self._loaded:
            return

        try:
            from pybaseball import batting_stats

            logger.info(f"Loading {self.season} batter K rates from FanGraphs...")
            batters = batting_stats(self.season, qual=1)

            for _, row in batters.iterrows():
                name = str(row.get('Name', '')).lower().strip()
                k_pct = row.get('K%', 0)

                if isinstance(k_pct, str):
                    k_pct = float(k_pct.replace('%', '')) / 100

                if name and k_pct > 0:
                    self.overall_k_rates[name] = k_pct

            logger.info(f"Loaded overall K rates for {len(self.overall_k_rates)} batters")

            # Now load platoon splits from Statcast
            self._load_platoon_splits()
            self._loaded = True

        except Exception as e:
            logger.error(f"Error loading K rates: {e}")
            logger.warning("Falling back to league average for all batters")

    def _load_platoon_splits(self) -> None:
        """Load platoon splits (K% vs LHP and RHP) from Statcast."""
        try:
            from pybaseball import statcast

            logger.info("Loading platoon splits from Statcast (this takes a few minutes)...")

            # Get full season of Statcast data
            # We'll sample a few months to keep it reasonable
            sample_periods = [
                ('2024-04-01', '2024-04-30'),  # April
                ('2024-06-01', '2024-06-30'),  # June
                ('2024-08-01', '2024-08-31'),  # August
            ]

            all_data = []
            for start, end in sample_periods:
                logger.info(f"  Fetching {start} to {end}...")
                try:
                    data = statcast(start, end)
                    all_data.append(data)
                except Exception as e:
                    logger.warning(f"  Error fetching {start}-{end}: {e}")

            if not all_data:
                logger.warning("No Statcast data loaded, using overall K rates only")
                return

            import pandas as pd
            combined = pd.concat(all_data, ignore_index=True)
            logger.info(f"  Combined {len(combined)} pitch records")

            # Calculate K rates by batter vs pitcher hand
            # An at-bat ends with an event (strikeout, hit, out, etc.)
            at_bats = combined[combined['events'].notna()].copy()

            # Group by batter and pitcher hand
            for (batter_id, p_throws), group in at_bats.groupby(['batter', 'p_throws']):
                total_abs = len(group)
                strikeouts = len(group[group['events'] == 'strikeout'])

                if total_abs >= 20:  # Minimum sample size
                    k_rate = strikeouts / total_abs

                    # Get batter name (use first occurrence)
                    batter_name = str(group['player_name'].iloc[0]).lower().strip() if 'player_name' in group.columns else None

                    if batter_name:
                        if p_throws == 'L':
                            self.vs_lhp_k_rates[batter_name] = k_rate
                        else:
                            self.vs_rhp_k_rates[batter_name] = k_rate

            logger.info(f"Loaded platoon splits: {len(self.vs_lhp_k_rates)} vs LHP, {len(self.vs_rhp_k_rates)} vs RHP")

        except ImportError:
            logger.warning("pybaseball not available for platoon splits")
        except Exception as e:
            logger.error(f"Error loading platoon splits: {e}")

    def get_k_rate(self, player_name: str, vs_pitcher_hand: str = None) -> float:
        """Get K rate for a batter, optionally adjusted for pitcher hand."""
        if not self._loaded:
            self.load_k_rates()

        name_lower = player_name.lower().strip()

        # Try platoon-specific rate first
        if vs_pitcher_hand == 'L' and name_lower in self.vs_lhp_k_rates:
            return self.vs_lhp_k_rates[name_lower]
        elif vs_pitcher_hand == 'R' and name_lower in self.vs_rhp_k_rates:
            return self.vs_rhp_k_rates[name_lower]

        # Fall back to overall rate
        if name_lower in self.overall_k_rates:
            return self.overall_k_rates[name_lower]

        # Try partial match
        for stored_name, k_rate in self.overall_k_rates.items():
            if name_lower.split()[-1] in stored_name:  # Match last name
                return k_rate

        return self.league_avg

    def get_stats(self) -> Dict:
        """Get loading statistics."""
        return {
            'overall_batters': len(self.overall_k_rates),
            'vs_lhp_batters': len(self.vs_lhp_k_rates),
            'vs_rhp_batters': len(self.vs_rhp_k_rates),
        }


class BigQueryLoader:
    """Loads collected data to BigQuery."""

    def __init__(self, project_id: str = 'nba-props-platform', dry_run: bool = False):
        self.project_id = project_id
        self.dry_run = dry_run
        self._client = None

    @property
    def client(self):
        if self._client is None and not self.dry_run:
            from google.cloud import bigquery
            self._client = bigquery.Client(project=self.project_id)
        return self._client

    def load_game_lineups(self, games: List[GameData]) -> int:
        """Load game lineup data to BigQuery."""
        if not games:
            return 0

        if self.dry_run:
            logger.info(f"[DRY RUN] Would load {len(games)} games to mlb_game_lineups")
            return len(games)

        from google.cloud import bigquery

        rows = []
        for game in games:
            rows.append({
                'game_pk': game.game_pk,
                'game_date': game.game_date,
                'game_time_utc': game.game_time_utc,
                'away_team_id': game.away_team_id,
                'away_team_name': game.away_team_name,
                'away_team_abbr': game.away_team_abbr,
                'home_team_id': game.home_team_id,
                'home_team_name': game.home_team_name,
                'home_team_abbr': game.home_team_abbr,
                'venue_name': game.venue_name,
                'status_code': game.status_code,
                'lineups_available': len(game.away_lineup) > 0 or len(game.home_lineup) > 0,
                'away_lineup_count': len(game.away_lineup),
                'home_lineup_count': len(game.home_lineup),
                'source_file_path': f'mlb-stats-api/boxscores/{game.game_date}/{game.game_pk}',
                'scraped_at': datetime.utcnow().isoformat(),
                'created_at': datetime.utcnow().isoformat(),
                'processed_at': datetime.utcnow().isoformat(),
            })

        table_id = f"{self.project_id}.mlb_raw.mlb_game_lineups"

        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
        )

        try:
            job = self.client.load_table_from_json(rows, table_id, job_config=job_config)
            job.result()
            logger.info(f"Loaded {len(rows)} rows to mlb_game_lineups")
            return len(rows)
        except Exception as e:
            logger.error(f"Error loading to mlb_game_lineups: {e}")
            return 0

    def load_lineup_batters(self, games: List[GameData]) -> int:
        """Load individual batter lineup data to BigQuery."""
        if not games:
            return 0

        rows = []
        for game in games:
            # Away lineup
            away_starter = game.home_pitchers[0] if game.home_pitchers else {}
            for batter in game.away_lineup:
                rows.append(self._batter_row(game, batter, is_home=False,
                                            opponent_abbr=game.home_team_abbr,
                                            opponent_pitcher=away_starter))

            # Home lineup
            home_starter = game.away_pitchers[0] if game.away_pitchers else {}
            for batter in game.home_lineup:
                rows.append(self._batter_row(game, batter, is_home=True,
                                            opponent_abbr=game.away_team_abbr,
                                            opponent_pitcher=home_starter))

        if self.dry_run:
            logger.info(f"[DRY RUN] Would load {len(rows)} batters to mlb_lineup_batters")
            return len(rows)

        from google.cloud import bigquery

        table_id = f"{self.project_id}.mlb_raw.mlb_lineup_batters"

        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )

        try:
            job = self.client.load_table_from_json(rows, table_id, job_config=job_config)
            job.result()
            logger.info(f"Loaded {len(rows)} rows to mlb_lineup_batters")
            return len(rows)
        except Exception as e:
            logger.error(f"Error loading to mlb_lineup_batters: {e}")
            return 0

    def _batter_row(self, game: GameData, batter: Dict, is_home: bool,
                    opponent_abbr: str, opponent_pitcher: Dict) -> Dict:
        """Create a batter row for BigQuery."""
        player_name = batter.get('player_name', 'Unknown')
        return {
            'game_pk': game.game_pk,
            'game_date': game.game_date,
            'team_abbr': game.home_team_abbr if is_home else game.away_team_abbr,
            'is_home': is_home,
            'player_id': batter.get('player_id'),
            'player_name': player_name,
            'player_lookup': player_name.lower().replace(' ', '_').replace('.', '').replace("'", ''),
            'batting_order': batter.get('batting_order'),
            'position': batter.get('position'),
            'position_name': batter.get('position'),
            'opponent_team_abbr': opponent_abbr,
            'opponent_pitcher_id': opponent_pitcher.get('player_id'),
            'opponent_pitcher_name': opponent_pitcher.get('player_name'),
            'source_file_path': f'mlb-stats-api/boxscores/{game.game_date}/{game.game_pk}',
            'created_at': datetime.utcnow().isoformat(),
            'processed_at': datetime.utcnow().isoformat(),
        }

    def load_pitcher_stats(self, games: List[GameData]) -> int:
        """Load pitcher game stats to BigQuery - CRITICAL for ML training."""
        if not games:
            return 0

        rows = []
        for game in games:
            # Away pitchers (facing home lineup)
            for pitcher in game.away_pitchers:
                rows.append(self._pitcher_row(game, pitcher, is_home=False,
                                              team_abbr=game.away_team_abbr,
                                              opponent_abbr=game.home_team_abbr))

            # Home pitchers (facing away lineup)
            for pitcher in game.home_pitchers:
                rows.append(self._pitcher_row(game, pitcher, is_home=True,
                                              team_abbr=game.home_team_abbr,
                                              opponent_abbr=game.away_team_abbr))

        if self.dry_run:
            logger.info(f"[DRY RUN] Would load {len(rows)} pitchers to mlb_pitcher_stats")
            return len(rows)

        from google.cloud import bigquery

        table_id = f"{self.project_id}.mlb_raw.mlb_pitcher_stats"

        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
        )

        try:
            job = self.client.load_table_from_json(rows, table_id, job_config=job_config)
            job.result()
            logger.info(f"Loaded {len(rows)} rows to mlb_pitcher_stats")
            return len(rows)
        except Exception as e:
            logger.error(f"Error loading to mlb_pitcher_stats: {e}")
            return 0

    def _pitcher_row(self, game: GameData, pitcher: Dict, is_home: bool,
                     team_abbr: str, opponent_abbr: str) -> Dict:
        """Create a pitcher stats row for BigQuery."""
        player_name = pitcher.get('player_name', 'Unknown')
        return {
            'game_pk': game.game_pk,
            'game_date': game.game_date,
            'game_id': f"{game.game_date}_{game.away_team_abbr}_{game.home_team_abbr}",
            'season_year': int(game.game_date[:4]) if game.game_date else 2025,
            'player_id': pitcher.get('player_id'),
            'player_name': player_name,
            'player_lookup': player_name.lower().replace(' ', '_').replace('.', '').replace("'", ''),
            'team_abbr': team_abbr,
            'opponent_team_abbr': opponent_abbr,
            'is_home': is_home,
            'is_starter': pitcher.get('is_starter', False),
            'throws': pitcher.get('throws', 'R'),
            # Key stats for ML
            'strikeouts': pitcher.get('strikeouts', 0),
            'innings_pitched': pitcher.get('innings_pitched', 0.0),
            'hits_allowed': pitcher.get('hits', 0),
            'walks_allowed': pitcher.get('walks', 0),
            'earned_runs': pitcher.get('earned_runs', 0),
            'pitch_count': pitcher.get('pitch_count', 0),
            # Computed fields
            'k_per_9': round(pitcher.get('strikeouts', 0) * 9 / max(pitcher.get('innings_pitched', 1), 0.1), 2),
            # Metadata
            'venue': game.venue_name,
            'game_status': game.status_code,
            'source': 'mlb_stats_api',
            'created_at': datetime.utcnow().isoformat(),
            'processed_at': datetime.utcnow().isoformat(),
        }


class SeasonCollector:
    """Main orchestrator for MLB season collection."""

    def __init__(self, season: int = 2025, dry_run: bool = False, resume: bool = False):
        self.season = season
        self.dry_run = dry_run
        self.resume = resume
        self.collector = MLBDataCollector()
        self.k_rate_provider = BatterKRateProvider(season=season)
        self.bq_loader = BigQueryLoader(dry_run=dry_run)
        self.checkpoint = CheckpointManager(
            checkpoint_file=os.path.join(CHECKPOINT_DIR, f"collect_{season}_checkpoint.json")
        )
        self.progress = CollectionProgress()
        self.completed_dates: List[str] = []
        self.collected_games: List[GameData] = []

    def run(self, start_date: date = None, end_date: date = None,
            month: int = None, limit: int = None) -> CollectionProgress:
        """Run the full collection pipeline."""

        # Get default season dates
        season_start, season_end = SEASON_DATES.get(self.season, SEASON_DATES[2025])

        # Determine date range
        if month:
            start_date = date(self.season, month, 1)
            if month == 12:
                end_date = date(self.season, 12, 31)
            else:
                end_date = date(self.season, month + 1, 1) - timedelta(days=1)
        else:
            start_date = start_date or season_start
            end_date = end_date or season_end

        logger.info(f"Collecting MLB data from {start_date} to {end_date}")
        logger.info(f"Dry run: {self.dry_run}")

        # Load checkpoint if resuming
        if self.resume:
            saved_progress, self.completed_dates = self.checkpoint.load()
            if saved_progress:
                self.progress = saved_progress
                logger.info(f"Resuming from checkpoint: {len(self.completed_dates)} dates already done")

        # Load K rates first
        logger.info("Loading batter K rates...")
        self.k_rate_provider.load_k_rates()
        k_stats = self.k_rate_provider.get_stats()
        logger.info(f"K rate stats: {k_stats}")

        # Generate date list
        all_dates = []
        current = start_date
        while current <= end_date:
            date_str = current.isoformat()
            if date_str not in self.completed_dates:
                all_dates.append(date_str)
            current += timedelta(days=1)

        if limit:
            all_dates = all_dates[:limit]

        self.progress.total_dates = len(all_dates) + len(self.completed_dates)
        logger.info(f"Processing {len(all_dates)} dates ({len(self.completed_dates)} already complete)")

        # Process each date
        for i, date_str in enumerate(all_dates):
            try:
                games_collected = self._process_date(date_str)
                self.completed_dates.append(date_str)
                self.progress.processed_dates = len(self.completed_dates)
                self.progress.last_date_processed = date_str

                # Save checkpoint every 10 dates
                if (i + 1) % 10 == 0:
                    self.checkpoint.save(self.progress, self.completed_dates)
                    logger.info(f"Progress: {self.progress.processed_dates}/{self.progress.total_dates} dates, "
                               f"{self.progress.total_games} games, {self.progress.total_pitcher_starts} starts")

            except Exception as e:
                error_msg = f"Error processing {date_str}: {e}"
                logger.error(error_msg)
                self.progress.errors.append(error_msg)

        # Final checkpoint
        self.checkpoint.save(self.progress, self.completed_dates)

        # Print summary
        self._print_summary()

        return self.progress

    def _process_date(self, date_str: str) -> int:
        """Process a single date."""
        game_pks = self.collector.get_games_for_date(date_str)

        if not game_pks:
            return 0

        games_for_date = []
        for game_pk in game_pks:
            game_data = self.collector.get_game_data(game_pk)
            if game_data:
                games_for_date.append(game_data)
                self.progress.total_games += 1

                if game_data.away_lineup or game_data.home_lineup:
                    self.progress.games_with_lineups += 1

                # Count pitcher starts
                if game_data.away_pitchers:
                    self.progress.total_pitcher_starts += 1
                if game_data.home_pitchers:
                    self.progress.total_pitcher_starts += 1

        # Load to BigQuery
        if games_for_date:
            self.bq_loader.load_game_lineups(games_for_date)
            self.bq_loader.load_lineup_batters(games_for_date)
            self.bq_loader.load_pitcher_stats(games_for_date)  # NEW: Store pitcher stats for ML

        return len(games_for_date)

    def _print_summary(self):
        """Print collection summary."""
        print("\n" + "=" * 60)
        print("MLB 2024 SEASON COLLECTION SUMMARY")
        print("=" * 60)
        print(f"\nDates processed:    {self.progress.processed_dates}/{self.progress.total_dates}")
        print(f"Total games:        {self.progress.total_games}")
        print(f"Games with lineups: {self.progress.games_with_lineups}")
        print(f"Pitcher starts:     {self.progress.total_pitcher_starts}")
        print(f"Errors:             {len(self.progress.errors)}")

        if self.progress.errors:
            print("\nErrors encountered:")
            for err in self.progress.errors[:10]:
                print(f"  - {err}")

        k_stats = self.k_rate_provider.get_stats()
        print(f"\nK rate coverage:")
        print(f"  Overall K rates:  {k_stats['overall_batters']} batters")
        print(f"  vs LHP splits:    {k_stats['vs_lhp_batters']} batters")
        print(f"  vs RHP splits:    {k_stats['vs_rhp_batters']} batters")

        if self.dry_run:
            print("\n[DRY RUN] No data was written to BigQuery")


def main():
    parser = argparse.ArgumentParser(description='Collect MLB Season Data')
    parser.add_argument('--season', type=int, choices=[2024, 2025], default=2025,
                        help='Season to collect (default: 2025 - most recent)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be collected without writing')
    parser.add_argument('--resume', action='store_true', help='Resume from checkpoint')
    parser.add_argument('--month', type=int, choices=range(1, 13), help='Collect specific month only')
    parser.add_argument('--limit', type=int, help='Limit number of dates to process')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')

    args = parser.parse_args()

    # Get season dates
    season_start, season_end = SEASON_DATES.get(args.season, SEASON_DATES[2025])

    # Parse dates if provided, otherwise use season defaults
    start_date = date.fromisoformat(args.start_date) if args.start_date else season_start
    end_date = date.fromisoformat(args.end_date) if args.end_date else season_end

    logger.info(f"=== Collecting MLB {args.season} Season ===")

    collector = SeasonCollector(
        season=args.season,
        dry_run=args.dry_run,
        resume=args.resume
    )

    collector.run(
        start_date=start_date,
        end_date=end_date,
        month=args.month,
        limit=args.limit
    )


if __name__ == '__main__':
    main()
