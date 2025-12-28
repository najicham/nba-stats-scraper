#!/usr/bin/env python3
"""
BDL Live Box Scores Processor

Processes live in-game box score snapshots from the BallDontLie API.
Each poll creates NEW rows (append-only) to enable time-series analysis.

Processing Strategy: APPEND_ONLY
- No updates or deletes during live games
- Each poll timestamp = new rows for all active players
- Enables historical queries like "when did player hit 20 points?"

Table: nba_raw.bdl_live_boxscores
Partitioned by: game_date
Clustered by: game_id, player_lookup, poll_timestamp
"""

import logging
import os
import re
from typing import Dict, List, Optional
from datetime import datetime, timezone

from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase

logger = logging.getLogger(__name__)


class BdlLiveBoxscoresProcessor(ProcessorBase):
    """
    Ball Don't Lie Live Box Scores Processor

    Processing Strategy: APPEND_ONLY
    - Each poll creates new rows (no updates)
    - Enables time-series analysis of in-game stats
    """

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.bdl_live_boxscores'
        self.processing_strategy = 'APPEND_ONLY'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

        # Team abbreviation mapping (same as bdl_boxscores_processor)
        self.team_mapping = {
            'atlanta hawks': 'ATL', 'boston celtics': 'BOS', 'brooklyn nets': 'BKN',
            'charlotte hornets': 'CHA', 'chicago bulls': 'CHI', 'cleveland cavaliers': 'CLE',
            'dallas mavericks': 'DAL', 'denver nuggets': 'DEN', 'detroit pistons': 'DET',
            'golden state warriors': 'GSW', 'houston rockets': 'HOU', 'indiana pacers': 'IND',
            'los angeles clippers': 'LAC', 'los angeles lakers': 'LAL', 'memphis grizzlies': 'MEM',
            'miami heat': 'MIA', 'milwaukee bucks': 'MIL', 'minnesota timberwolves': 'MIN',
            'new orleans pelicans': 'NOP', 'new york knicks': 'NYK', 'oklahoma city thunder': 'OKC',
            'orlando magic': 'ORL', 'philadelphia 76ers': 'PHI', 'phoenix suns': 'PHX',
            'portland trail blazers': 'POR', 'sacramento kings': 'SAC', 'san antonio spurs': 'SAS',
            'toronto raptors': 'TOR', 'utah jazz': 'UTA', 'washington wizards': 'WAS'
        }
        self.valid_team_abbrevs = set(self.team_mapping.values())

    def load_data(self) -> None:
        """Load live boxscores data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON structure from the live box scores scraper."""
        errors = []

        if 'liveBoxes' not in data:
            errors.append("Missing 'liveBoxes' field")
            return errors

        if not isinstance(data['liveBoxes'], list):
            errors.append("'liveBoxes' is not a list")

        # Empty liveBoxes is valid (no games in progress)
        return errors

    def normalize_team_name(self, team_name: str) -> str:
        """Normalize team name to standard abbreviation."""
        if not team_name:
            return ""

        normalized = team_name.lower().strip()

        # Handle common aliases
        aliases = {
            'la lakers': 'los angeles lakers',
            'la clippers': 'los angeles clippers'
        }

        if normalized in aliases:
            normalized = aliases[normalized]

        return self.team_mapping.get(normalized, "")

    def extract_team_abbreviation(self, team_data: Dict) -> str:
        """Extract team abbreviation with multiple fallback strategies."""
        if not team_data:
            return ""

        # Strategy 1: Use abbreviation field directly (most reliable for BDL)
        direct_abbrev = team_data.get('abbreviation', '')
        if direct_abbrev and direct_abbrev.upper() in self.valid_team_abbrevs:
            return direct_abbrev.upper()

        # Strategy 2: Use full_name mapping
        full_name = team_data.get('full_name', '')
        if full_name:
            abbrev = self.normalize_team_name(full_name)
            if abbrev:
                return abbrev

        # Strategy 3: Use city + name combination
        city = team_data.get('city', '')
        name = team_data.get('name', '')
        if city and name:
            combined_name = f"{city} {name}"
            abbrev = self.normalize_team_name(combined_name)
            if abbrev:
                return abbrev

        logger.warning(f"Failed to extract team abbreviation from: {team_data}")
        return ""

    def normalize_player_name(self, first_name: str, last_name: str) -> str:
        """Create normalized player lookup string."""
        full_name = f"{first_name} {last_name}".strip()
        # Remove spaces, punctuation, and convert to lowercase
        normalized = re.sub(r'[^a-z0-9]', '', full_name.lower())
        return normalized

    def parse_minutes_to_decimal(self, minutes_str: str) -> Optional[float]:
        """Convert "28:30" to 28.5 decimal format."""
        if not minutes_str:
            return None

        try:
            # Handle both "28:30" and "28" formats
            if ':' in minutes_str:
                parts = minutes_str.split(':')
                mins = int(parts[0])
                secs = int(parts[1]) if len(parts) > 1 else 0
                return round(mins + secs / 60.0, 2)
            else:
                return float(minutes_str)
        except (ValueError, TypeError):
            return None

    def determine_game_status(self, box: Dict) -> str:
        """Determine game status from BDL live response."""
        status_text = str(box.get('status', '')).lower()
        period = box.get('period', 0) or 0

        if 'final' in status_text:
            return 'final'
        elif period > 0 or 'progress' in status_text or 'live' in status_text:
            return 'in_progress'
        else:
            return 'scheduled'

    def transform_data(self) -> None:
        """Transform raw live boxscores data to BigQuery rows."""
        raw_data = self.raw_data
        file_path = raw_data.get('metadata', {}).get('source_file', 'unknown')

        rows = []

        # Extract poll metadata from scraper output
        poll_id = raw_data.get('pollId', datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        poll_timestamp = raw_data.get('timestamp', datetime.now(timezone.utc).isoformat())

        # Parse poll_timestamp to datetime
        try:
            if isinstance(poll_timestamp, str):
                poll_dt = datetime.fromisoformat(poll_timestamp.replace('Z', '+00:00'))
            else:
                poll_dt = datetime.now(timezone.utc)
        except ValueError:
            poll_dt = datetime.now(timezone.utc)

        live_boxes = raw_data.get('liveBoxes', [])

        if not live_boxes:
            logger.info(f"No live games in progress (poll: {poll_id})")
            self.transformed_data = []
            return

        for box in live_boxes:
            # Extract game-level data
            game_id = str(box.get('id', ''))

            # Determine game status
            game_status = self.determine_game_status(box)
            period = box.get('period', 0) or 0
            time_remaining = box.get('time', '')

            # Determine halftime (between Q2 and Q3)
            is_halftime = (period == 2 and time_remaining == '0:00')

            # Extract team information
            home_team = box.get('home_team', {})
            away_team = box.get('visitor_team', {})

            home_team_abbr = self.extract_team_abbreviation(home_team)
            away_team_abbr = self.extract_team_abbreviation(away_team)

            if not home_team_abbr or not away_team_abbr:
                logger.warning(f"Skipping game {game_id} - failed to extract team abbreviations")
                continue

            # Extract scores
            home_score = box.get('home_team_score', 0) or 0
            away_score = box.get('visitor_team_score', 0) or 0

            # Use the game's date from the API response (not poll timestamp)
            # This ensures games played past midnight UTC still use correct ET date
            game_date = box.get('date', poll_dt.date().isoformat())

            # Process home team players
            for player_stats in home_team.get('players', []):
                row = self._create_player_row(
                    poll_id=poll_id,
                    poll_timestamp=poll_dt,
                    game_id=game_id,
                    game_date=game_date,
                    game_status=game_status,
                    period=period,
                    time_remaining=time_remaining,
                    is_halftime=is_halftime,
                    home_team_abbr=home_team_abbr,
                    away_team_abbr=away_team_abbr,
                    home_score=home_score,
                    away_score=away_score,
                    team_abbr=home_team_abbr,
                    player_stats=player_stats,
                    file_path=file_path
                )
                if row:
                    rows.append(row)

            # Process away team players
            for player_stats in away_team.get('players', []):
                row = self._create_player_row(
                    poll_id=poll_id,
                    poll_timestamp=poll_dt,
                    game_id=game_id,
                    game_date=game_date,
                    game_status=game_status,
                    period=period,
                    time_remaining=time_remaining,
                    is_halftime=is_halftime,
                    home_team_abbr=home_team_abbr,
                    away_team_abbr=away_team_abbr,
                    home_score=home_score,
                    away_score=away_score,
                    team_abbr=away_team_abbr,
                    player_stats=player_stats,
                    file_path=file_path
                )
                if row:
                    rows.append(row)

        logger.info(f"Generated {len(rows)} player snapshot rows from {len(live_boxes)} games (poll: {poll_id})")
        self.transformed_data = rows

    def _create_player_row(self, **kwargs) -> Optional[Dict]:
        """Create a single player snapshot row."""
        try:
            player_stats = kwargs['player_stats']
            player_info = player_stats.get('player', {})

            first_name = player_info.get('first_name', '')
            last_name = player_info.get('last_name', '')

            if not first_name or not last_name:
                return None

            player_full_name = f"{first_name} {last_name}"
            player_lookup = self.normalize_player_name(first_name, last_name)

            minutes_str = player_stats.get('min', '')
            minutes_decimal = self.parse_minutes_to_decimal(minutes_str)

            def safe_int(value):
                return int(value) if value is not None else 0

            poll_timestamp = kwargs['poll_timestamp']

            row = {
                # Poll metadata
                'poll_timestamp': poll_timestamp.isoformat(),
                'poll_id': kwargs['poll_id'],

                # Game identification
                'game_id': kwargs['game_id'],
                'game_date': kwargs['game_date'],

                # Game state
                'game_status': kwargs['game_status'],
                'period': kwargs['period'],
                'time_remaining': kwargs['time_remaining'],
                'is_halftime': kwargs['is_halftime'],

                # Team context
                'home_team_abbr': kwargs['home_team_abbr'],
                'away_team_abbr': kwargs['away_team_abbr'],
                'home_score': kwargs['home_score'],
                'away_score': kwargs['away_score'],

                # Player identification
                'bdl_player_id': player_info.get('id'),
                'player_lookup': player_lookup,
                'player_full_name': player_full_name,
                'team_abbr': kwargs['team_abbr'],

                # Player stats
                'minutes': minutes_str,
                'minutes_decimal': minutes_decimal,
                'points': safe_int(player_stats.get('pts')),
                'rebounds': safe_int(player_stats.get('reb')),
                'offensive_rebounds': safe_int(player_stats.get('oreb')),
                'defensive_rebounds': safe_int(player_stats.get('dreb')),
                'assists': safe_int(player_stats.get('ast')),
                'steals': safe_int(player_stats.get('stl')),
                'blocks': safe_int(player_stats.get('blk')),
                'turnovers': safe_int(player_stats.get('turnover')),
                'personal_fouls': safe_int(player_stats.get('pf')),

                # Shooting stats
                'field_goals_made': safe_int(player_stats.get('fgm')),
                'field_goals_attempted': safe_int(player_stats.get('fga')),
                'three_pointers_made': safe_int(player_stats.get('fg3m')),
                'three_pointers_attempted': safe_int(player_stats.get('fg3a')),
                'free_throws_made': safe_int(player_stats.get('ftm')),
                'free_throws_attempted': safe_int(player_stats.get('fta')),

                # Processing metadata
                'source_file_path': kwargs['file_path'],
                'processed_at': datetime.now(timezone.utc).isoformat()
            }

            return row

        except Exception as e:
            logger.error(f"Error creating player row: {e}")
            return None

    def save_data(self) -> None:
        """Save transformed data to BigQuery (append-only)."""
        rows = self.transformed_data

        if not rows:
            logger.info("No rows to save (no games in progress)")
            return

        table_id = f"{self.project_id}.{self.table_name}"

        try:
            # Get table schema
            table = self.bq_client.get_table(table_id)

            # Configure batch load job (append only)
            job_config = bigquery.LoadJobConfig(
                schema=table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED
            )

            # Load using batch job
            load_job = self.bq_client.load_table_from_json(
                rows,
                table_id,
                job_config=job_config
            )

            # Wait for completion
            load_job.result()

            # Get unique game count
            game_ids = set(row['game_id'] for row in rows)
            poll_id = rows[0].get('poll_id', 'unknown') if rows else 'unknown'

            logger.info(f"Appended {len(rows)} player snapshots for {len(game_ids)} games (poll: {poll_id})")

        except Exception as e:
            logger.error(f"Error saving live boxscores: {e}")
            raise

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': len(self.transformed_data) if hasattr(self, 'transformed_data') else 0,
            'processing_strategy': self.processing_strategy
        }
