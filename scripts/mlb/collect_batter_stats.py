#!/usr/bin/env python3
"""
MLB Batter Stats Collection (from MLB Stats API)

Collects individual batter game stats and loads to bdl_batter_stats.
Uses the MLB Stats API boxscore endpoint which includes detailed batting stats.

Usage:
    # Collect all batter stats for games already in mlb_game_lineups
    PYTHONPATH=. python scripts/mlb/collect_batter_stats.py

    # Collect for specific date range
    PYTHONPATH=. python scripts/mlb/collect_batter_stats.py --start-date 2024-08-01 --end-date 2024-08-31

    # Dry run
    PYTHONPATH=. python scripts/mlb/collect_batter_stats.py --dry-run --limit 10

    # Resume from checkpoint
    PYTHONPATH=. python scripts/mlb/collect_batter_stats.py --resume
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
import requests

from google.cloud import bigquery

# Import MLB team config for ID to abbreviation fallback
try:
    from shared.config.sports.mlb.teams import TEAM_ID_TO_ABBR
except ImportError:
    TEAM_ID_TO_ABBR = {}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MLB Stats API endpoint
MLB_GAME_API = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

# Checkpoint management
CHECKPOINT_DIR = "/tmp/mlb_batter_backfill"
CHECKPOINT_FILE = f"{CHECKPOINT_DIR}/checkpoint.json"


@dataclass
class CollectionProgress:
    """Track collection progress."""
    total_games: int = 0
    processed_games: int = 0
    total_batters: int = 0
    errors: List[str] = field(default_factory=list)
    last_game_processed: Optional[int] = None


class CheckpointManager:
    """Manages checkpoint state for resumable collection."""

    def __init__(self, checkpoint_file: str = CHECKPOINT_FILE):
        self.checkpoint_file = checkpoint_file
        os.makedirs(os.path.dirname(checkpoint_file), exist_ok=True)

    def save(self, progress: CollectionProgress, completed_game_pks: List[int]):
        """Save checkpoint to disk."""
        data = {
            'progress': {
                'total_games': progress.total_games,
                'processed_games': progress.processed_games,
                'total_batters': progress.total_batters,
                'errors': progress.errors[-100:],  # Keep last 100 errors
                'last_game_processed': progress.last_game_processed,
            },
            'completed_game_pks': completed_game_pks,
            'saved_at': datetime.utcnow().isoformat()
        }
        with open(self.checkpoint_file, 'w') as f:
            json.dump(data, f)
        logger.debug(f"Checkpoint saved: {len(completed_game_pks)} games complete")

    def load(self) -> Tuple[Optional[CollectionProgress], List[int]]:
        """Load checkpoint from disk."""
        if not os.path.exists(self.checkpoint_file):
            return None, []

        try:
            with open(self.checkpoint_file, 'r') as f:
                data = json.load(f)

            progress = CollectionProgress(
                total_games=data['progress']['total_games'],
                processed_games=data['progress']['processed_games'],
                total_batters=data['progress']['total_batters'],
                errors=data['progress']['errors'],
                last_game_processed=data['progress']['last_game_processed'],
            )
            completed = data['completed_game_pks']
            logger.info(f"Loaded checkpoint: {len(completed)} games already complete")
            return progress, completed
        except Exception as e:
            logger.warning(f"Error loading checkpoint: {e}")
            return None, []

    def clear(self):
        """Clear checkpoint file."""
        if os.path.exists(self.checkpoint_file):
            os.remove(self.checkpoint_file)


class MLBBatterCollector:
    """Collects batter stats from MLB Stats API."""

    def __init__(self, rate_limit_delay: float = 0.25):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'mlb-batter-collector/1.0'
        })
        self.rate_limit_delay = rate_limit_delay

    def get_batter_stats(self, game_pk: int) -> Optional[List[Dict]]:
        """Get batter stats for a specific game."""
        url = MLB_GAME_API.format(game_pk=game_pk)

        try:
            time.sleep(self.rate_limit_delay)
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            return self._parse_batter_stats(data, game_pk)

        except Exception as e:
            logger.error(f"Error fetching game {game_pk}: {e}")
            return None

    def _parse_batter_stats(self, data: Dict, game_pk: int) -> List[Dict]:
        """Parse batter stats from API response."""
        batter_stats = []

        try:
            game_data = data.get('gameData', {})
            live_data = data.get('liveData', {})
            boxscore = live_data.get('boxscore', {})

            # Game info
            datetime_info = game_data.get('datetime', {})
            venue = game_data.get('venue', {})
            status = game_data.get('status', {})
            game_info = game_data.get('game', {})

            game_date = datetime_info.get('originalDate')
            if not game_date:
                return []

            season_year = int(game_date[:4])
            game_type = game_info.get('type', 'R')
            is_postseason = game_type in ['P', 'F', 'D', 'L', 'W']

            boxscore_teams = boxscore.get('teams', {})
            all_players = game_data.get('players', {})

            # Get team abbreviations from gameData.teams (has abbreviation)
            # NOT from boxscore.teams (which lacks abbreviation)
            game_teams = game_data.get('teams', {})
            home_team_id = game_teams.get('home', {}).get('id')
            away_team_id = game_teams.get('away', {}).get('id')
            # Use API value with fallback to config
            home_team_abbr = game_teams.get('home', {}).get('abbreviation') or TEAM_ID_TO_ABBR.get(str(home_team_id), 'UNK')
            away_team_abbr = game_teams.get('away', {}).get('abbreviation') or TEAM_ID_TO_ABBR.get(str(away_team_id), 'UNK')

            # Process both teams
            for team_side in ['away', 'home']:
                team_data = boxscore_teams.get(team_side, {})
                team_id = game_teams.get(team_side, {}).get('id')
                team_abbr = game_teams.get(team_side, {}).get('abbreviation') or TEAM_ID_TO_ABBR.get(str(team_id), 'UNK')
                team_name = game_teams.get(team_side, {}).get('name', 'Unknown')

                opponent_side = 'home' if team_side == 'away' else 'away'
                opponent_id = game_teams.get(opponent_side, {}).get('id')
                opponent_abbr = game_teams.get(opponent_side, {}).get('abbreviation') or TEAM_ID_TO_ABBR.get(str(opponent_id), 'UNK')

                # Scores from linescore
                linescore = live_data.get('linescore', {}).get('teams', {})
                home_score = linescore.get('home', {}).get('runs', 0)
                away_score = linescore.get('away', {}).get('runs', 0)

                batters = team_data.get('batters', [])
                players = team_data.get('players', {})

                for player_id in batters:
                    player_key = f'ID{player_id}'
                    player_data = players.get(player_key, {})

                    if not player_data:
                        continue

                    person = player_data.get('person', {})
                    stats = player_data.get('stats', {}).get('batting', {})
                    position = player_data.get('position', {})
                    batting_order_raw = player_data.get('battingOrder')

                    # Only include batters with at-bats
                    at_bats = stats.get('atBats', 0)
                    if at_bats == 0:
                        continue

                    # Get batting order
                    batting_order = None
                    if batting_order_raw:
                        try:
                            batting_order = int(batting_order_raw) // 100
                        except (ValueError, TypeError):
                            pass

                    player_name = person.get('fullName', 'Unknown')
                    player_lookup = player_name.lower().replace(' ', '_').replace('.', '').replace("'", '')

                    # Generate game_id
                    game_id = f"{game_date}_{away_team_abbr}_{home_team_abbr}"

                    # Create data hash for deduplication
                    hash_str = f"{game_id}_{player_id}_{at_bats}_{stats.get('strikeOuts', 0)}"
                    data_hash = hashlib.md5(hash_str.encode()).hexdigest()[:16]

                    batter_stat = {
                        'game_id': game_id,
                        'game_date': game_date,
                        'season_year': season_year,
                        'is_postseason': is_postseason,
                        'home_team_abbr': home_team_abbr,
                        'away_team_abbr': away_team_abbr,
                        'home_team_score': home_score,
                        'away_team_score': away_score,
                        'venue': venue.get('name', 'Unknown'),
                        'game_status': f"STATUS_{status.get('abstractGameCode', 'F')}",
                        'bdl_player_id': player_id,
                        'player_full_name': player_name,
                        'player_lookup': player_lookup,
                        'team_abbr': team_abbr,
                        'position': position.get('abbreviation', 'UNK'),
                        'jersey_number': person.get('jerseyNumber'),
                        'batting_order': batting_order,
                        'strikeouts': stats.get('strikeOuts', 0),
                        'at_bats': at_bats,
                        'hits': stats.get('hits', 0),
                        'walks': stats.get('baseOnBalls', 0),
                        'runs': stats.get('runs', 0),
                        'rbi': stats.get('rbi', 0),
                        'home_runs': stats.get('homeRuns', 0),
                        'doubles': stats.get('doubles', 0),
                        'triples': stats.get('triples', 0),
                        'stolen_bases': stats.get('stolenBases', 0),
                        'caught_stealing': stats.get('caughtStealing', 0),
                        'hit_by_pitch': stats.get('hitByPitch', 0),
                        'sacrifice_hits': stats.get('sacBunts', 0),
                        'sacrifice_flies': stats.get('sacFlies', 0),
                        'batting_average': self._safe_decimal(stats.get('avg')),
                        'on_base_pct': self._safe_decimal(stats.get('obp')),
                        'slugging_pct': self._safe_decimal(stats.get('slg')),
                        'ops': self._safe_decimal(stats.get('ops')),
                        'source_file_path': f'mlb-stats-api/boxscores/{game_date}/{game_pk}',
                        'data_hash': data_hash,
                        'created_at': datetime.utcnow().isoformat(),
                        'processed_at': datetime.utcnow().isoformat(),
                    }

                    batter_stats.append(batter_stat)

            return batter_stats

        except Exception as e:
            logger.error(f"Error parsing game {game_pk}: {e}")
            return []

    def _safe_decimal(self, value) -> Optional[float]:
        """Safely convert stat to decimal."""
        if value is None:
            return None
        try:
            if isinstance(value, str):
                return float(value) if value not in ('', '.---', '---') else None
            return float(value)
        except (ValueError, TypeError):
            return None


class BigQueryLoader:
    """Loads batter stats to BigQuery."""

    def __init__(self, project_id: str = 'nba-props-platform', dry_run: bool = False):
        self.project_id = project_id
        self.dry_run = dry_run
        self._client = None

    @property
    def client(self):
        if self._client is None and not self.dry_run:
            self._client = bigquery.Client(project=self.project_id)
        return self._client

    def load_batter_stats(self, rows: List[Dict]) -> int:
        """Load batter stats to BigQuery."""
        if not rows:
            return 0

        if self.dry_run:
            logger.info(f"[DRY RUN] Would load {len(rows)} batter stats")
            return len(rows)

        table_id = f"{self.project_id}.mlb_raw.bdl_batter_stats"

        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )

        try:
            job = self.client.load_table_from_json(rows, table_id, job_config=job_config)
            job.result(timeout=120)
            logger.debug(f"Loaded {len(rows)} rows to bdl_batter_stats")
            return len(rows)
        except Exception as e:
            logger.error(f"Error loading to bdl_batter_stats: {e}")
            return 0

    def get_game_pks_to_process(self, start_date: str = None, end_date: str = None) -> List[Tuple[int, str]]:
        """Get game PKs that need batter stats collected."""
        if self.dry_run:
            # In dry run, just return some sample games
            return [(746839, '2024-08-15'), (746840, '2024-08-15')]

        # Get games from mlb_game_lineups that don't have batter stats yet
        date_filter = ""
        if start_date and end_date:
            date_filter = f"AND g.game_date BETWEEN '{start_date}' AND '{end_date}'"
        elif start_date:
            date_filter = f"AND g.game_date >= '{start_date}'"
        elif end_date:
            date_filter = f"AND g.game_date <= '{end_date}'"

        query = f"""
        SELECT DISTINCT
            g.game_pk,
            g.game_date
        FROM `{self.project_id}.mlb_raw.mlb_game_lineups` g
        LEFT JOIN (
            SELECT DISTINCT
                CAST(SPLIT(source_file_path, '/')[SAFE_OFFSET(3)] AS INT64) as game_pk
            FROM `{self.project_id}.mlb_raw.bdl_batter_stats`
        ) b ON g.game_pk = b.game_pk
        WHERE b.game_pk IS NULL
          AND g.status_code = 'F'
          {date_filter}
        ORDER BY g.game_date, g.game_pk
        """

        try:
            results = self.client.query(query).result()
            games = [(int(row.game_pk), str(row.game_date)) for row in results]
            logger.info(f"Found {len(games)} games needing batter stats")
            return games
        except Exception as e:
            logger.error(f"Error querying games: {e}")
            return []


class BatterStatsCollector:
    """Main orchestrator for batter stats collection."""

    def __init__(self, dry_run: bool = False, resume: bool = False):
        self.dry_run = dry_run
        self.resume = resume
        self.collector = MLBBatterCollector()
        self.bq_loader = BigQueryLoader(dry_run=dry_run)
        self.checkpoint = CheckpointManager()
        self.progress = CollectionProgress()
        self.completed_game_pks: List[int] = []

    def run(self, start_date: str = None, end_date: str = None, limit: int = None) -> CollectionProgress:
        """Run the batter stats collection."""
        logger.info(f"Starting batter stats collection (dry_run={self.dry_run})")

        # Load checkpoint if resuming
        if self.resume:
            saved_progress, self.completed_game_pks = self.checkpoint.load()
            if saved_progress:
                self.progress = saved_progress

        # Get games to process
        all_games = self.bq_loader.get_game_pks_to_process(start_date, end_date)

        # Filter out already completed games
        games_to_process = [
            (pk, dt) for pk, dt in all_games
            if pk not in self.completed_game_pks
        ]

        if limit:
            games_to_process = games_to_process[:limit]

        self.progress.total_games = len(games_to_process) + len(self.completed_game_pks)
        logger.info(f"Processing {len(games_to_process)} games ({len(self.completed_game_pks)} already done)")

        # Process games in batches
        batch_size = 50
        batch_rows = []

        for i, (game_pk, game_date) in enumerate(games_to_process):
            try:
                batter_stats = self.collector.get_batter_stats(game_pk)

                if batter_stats:
                    batch_rows.extend(batter_stats)
                    self.progress.total_batters += len(batter_stats)
                    logger.debug(f"Game {game_pk} ({game_date}): {len(batter_stats)} batters")

                self.completed_game_pks.append(game_pk)
                self.progress.processed_games = len(self.completed_game_pks)
                self.progress.last_game_processed = game_pk

                # Write batch to BigQuery
                if len(batch_rows) >= batch_size:
                    self.bq_loader.load_batter_stats(batch_rows)
                    batch_rows = []

                # Save checkpoint every 100 games
                if (i + 1) % 100 == 0:
                    self.checkpoint.save(self.progress, self.completed_game_pks)
                    logger.info(f"Progress: {self.progress.processed_games}/{self.progress.total_games} games, "
                               f"{self.progress.total_batters} batters")

            except Exception as e:
                error_msg = f"Error processing game {game_pk}: {e}"
                logger.error(error_msg)
                self.progress.errors.append(error_msg)

        # Write remaining batch
        if batch_rows:
            self.bq_loader.load_batter_stats(batch_rows)

        # Final checkpoint
        self.checkpoint.save(self.progress, self.completed_game_pks)

        # Print summary
        self._print_summary()

        return self.progress

    def _print_summary(self):
        """Print collection summary."""
        print("\n" + "=" * 60)
        print("MLB BATTER STATS COLLECTION SUMMARY")
        print("=" * 60)
        print(f"\nGames processed:   {self.progress.processed_games}/{self.progress.total_games}")
        print(f"Total batters:     {self.progress.total_batters}")
        print(f"Errors:            {len(self.progress.errors)}")

        if self.progress.errors:
            print("\nRecent errors:")
            for err in self.progress.errors[-5:]:
                print(f"  - {err}")

        if self.dry_run:
            print("\n[DRY RUN] No data was written to BigQuery")


def main():
    parser = argparse.ArgumentParser(description='Collect MLB Batter Stats')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be collected')
    parser.add_argument('--resume', action='store_true', help='Resume from checkpoint')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--limit', type=int, help='Limit number of games')

    args = parser.parse_args()

    collector = BatterStatsCollector(
        dry_run=args.dry_run,
        resume=args.resume
    )

    collector.run(
        start_date=args.start_date,
        end_date=args.end_date,
        limit=args.limit
    )


if __name__ == '__main__':
    main()
