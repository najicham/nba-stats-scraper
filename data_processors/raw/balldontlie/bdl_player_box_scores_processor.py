#!/usr/bin/env python3
"""
Ball Don't Lie Player Box Scores Processor

Processes output from bdl_player_box_scores scraper (/stats endpoint).
Handles the flat stats array format and loads to bdl_player_boxscores table.

GCS Path: ball-dont-lie/player-box-scores/{date}/{timestamp}.json
Target Table: nba_raw.bdl_player_boxscores

Data Format (input):
{
    "startDate": "2025-12-28",
    "endDate": "2025-12-28",
    "rowCount": 150,
    "stats": [
        {
            "id": 12345,
            "min": "32:15",
            "pts": 25,
            ...
            "player": {"id": 1, "first_name": "LeBron", "last_name": "James", ...},
            "team": {"id": 14, "abbreviation": "LAL", "full_name": "Los Angeles Lakers"},
            "game": {"id": 123, "date": "2025-12-28", "status": "Final", ...}
        }
    ]
}

This processor is separate from BdlBoxscoresProcessor which handles /boxscores endpoint
with a different nested structure.

Created: 2025-12-28 (Session 183)
"""

import json
import os
import logging
import re
from typing import Dict, List, Optional
from datetime import datetime, date, timezone
from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)


class BdlPlayerBoxScoresProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Ball Don't Lie Player Box Scores Processor

    Processes the flat stats array from /stats endpoint.
    Writes to same table as BdlBoxscoresProcessor (nba_raw.bdl_player_boxscores).

    Processing Strategy: MERGE_UPDATE
    Smart Idempotency: Enabled
        Hash Fields: game_id, player_lookup, points, rebounds, assists
    """

    # Smart Idempotency configuration
    HASH_FIELDS = [
        'game_id',
        'player_lookup',
        'points',
        'rebounds',
        'assists',
        'field_goals_made',
        'field_goals_attempted'
    ]

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.bdl_player_boxscores'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

        # Standard NBA team abbreviations
        self.valid_team_abbrevs = {
            'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET',
            'GSW', 'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN',
            'NOP', 'NYK', 'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS',
            'TOR', 'UTA', 'WAS'
        }

    def load_data(self) -> None:
        """Load player box scores data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def normalize_player_name(self, first_name: str, last_name: str) -> str:
        """Create normalized player lookup string."""
        full_name = f"{first_name} {last_name}".strip()
        # Remove spaces, punctuation, and convert to lowercase
        normalized = re.sub(r'[^a-z0-9]', '', full_name.lower())
        return normalized

    def extract_team_abbr(self, team_data: Dict) -> str:
        """Extract team abbreviation from team object."""
        if not team_data:
            return ""

        # Try abbreviation field first
        abbr = team_data.get('abbreviation', '')
        if abbr and abbr.upper() in self.valid_team_abbrevs:
            return abbr.upper()

        # Fallback to first 3 chars of city
        city = team_data.get('city', '')
        if city:
            return city.upper()[:3]

        return ""

    def build_game_id(self, game_data: Dict) -> str:
        """
        Build game_id in standard format: YYYYMMDD_AWAY_HOME

        Note: BDL /stats response has game.home_team_id and game.visitor_team_id
        but not the team abbreviations directly. We need to infer from context.
        """
        game_date = game_data.get('date', '')
        if not game_date:
            return ""

        # Parse date
        try:
            date_obj = datetime.strptime(game_date, '%Y-%m-%d').date()
            date_str = date_obj.strftime('%Y%m%d')
        except ValueError:
            logger.warning(f"Could not parse game date: {game_date}")
            return ""

        # For now, use BDL game ID as suffix since we don't have team abbrs in game object
        # The actual home/away teams will be added when we have that context
        bdl_game_id = game_data.get('id', '')
        return f"{date_str}_BDL{bdl_game_id}"

    def extract_season_year(self, game_date: str, season_field: Optional[int] = None) -> int:
        """Extract season year from date or season field."""
        if season_field:
            return season_field

        # Fall back to date-based calculation
        game_dt = datetime.strptime(game_date, '%Y-%m-%d').date()
        if game_dt.month >= 10:  # October or later = start of season
            return game_dt.year
        else:  # Before October = second year of season
            return game_dt.year - 1

    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON structure."""
        errors = []

        if 'stats' not in data:
            errors.append("Missing 'stats' field")
            return errors

        if not isinstance(data['stats'], list):
            errors.append("'stats' is not a list")
            return errors

        if not data['stats']:
            # Empty stats is valid (no games on that date)
            logger.info("Empty stats array - no player data for this date")

        return errors

    def transform_data(self) -> None:
        """Transform raw data into transformed data for BigQuery."""
        raw_data = self.raw_data
        file_path = raw_data.get('metadata', {}).get('source_file', 'unknown')
        rows = []
        skipped_count = 0

        stats = raw_data.get('stats', [])
        logger.info(f"Processing {len(stats)} stat rows from {file_path}")

        # Group stats by game to build proper game_id with team abbrs
        games_data = {}  # bdl_game_id -> {home_abbr, away_abbr, ...}

        for stat in stats:
            game = stat.get('game', {})
            team = stat.get('team', {})
            player = stat.get('player', {})

            if not game or not team or not player:
                skipped_count += 1
                continue

            bdl_game_id = game.get('id')
            team_abbr = self.extract_team_abbr(team)
            team_id = team.get('id')

            # Track which team is home vs away
            if bdl_game_id not in games_data:
                games_data[bdl_game_id] = {
                    'date': game.get('date'),
                    'home_team_id': game.get('home_team_id'),
                    'visitor_team_id': game.get('visitor_team_id'),
                    'home_team_abbr': None,
                    'away_team_abbr': None,
                    'home_team_score': game.get('home_team_score'),
                    'away_team_score': game.get('visitor_team_score'),
                    'status': game.get('status'),
                    'period': game.get('period'),
                    'postseason': game.get('postseason', False),
                    'season': game.get('season')
                }

            # Assign team abbr based on team_id match
            game_info = games_data[bdl_game_id]
            if team_id == game.get('home_team_id'):
                game_info['home_team_abbr'] = team_abbr
            elif team_id == game.get('visitor_team_id'):
                game_info['away_team_abbr'] = team_abbr

        # Now process all stats with complete game info
        for stat in stats:
            try:
                game = stat.get('game', {})
                team = stat.get('team', {})
                player = stat.get('player', {})

                if not game or not team or not player:
                    continue

                bdl_game_id = game.get('id')
                game_info = games_data.get(bdl_game_id, {})

                game_date = game.get('date', '')
                home_abbr = game_info.get('home_team_abbr', 'UNK')
                away_abbr = game_info.get('away_team_abbr', 'UNK')

                # Build proper game_id
                if game_date and home_abbr and away_abbr:
                    date_str = datetime.strptime(game_date, '%Y-%m-%d').strftime('%Y%m%d')
                    game_id = f"{date_str}_{away_abbr}_{home_abbr}"
                else:
                    # Fallback
                    game_id = self.build_game_id(game)

                # Player info
                first_name = player.get('first_name', '')
                last_name = player.get('last_name', '')
                if not first_name or not last_name:
                    skipped_count += 1
                    continue

                player_full_name = f"{first_name} {last_name}"
                player_lookup = self.normalize_player_name(first_name, last_name)
                team_abbr = self.extract_team_abbr(team)

                # Helper functions
                def safe_int(val):
                    return int(val) if val is not None else 0

                def safe_float(val):
                    return float(val) if val is not None else None

                # Build row
                row = {
                    # Core identifiers
                    'game_id': game_id,
                    'game_date': game_date,
                    'season_year': self.extract_season_year(game_date, game.get('season')),
                    'game_status': game_info.get('status', ''),
                    'period': game_info.get('period'),
                    'is_postseason': game_info.get('postseason', False),

                    # Team context
                    'home_team_abbr': home_abbr,
                    'away_team_abbr': away_abbr,
                    'home_team_score': game_info.get('home_team_score'),
                    'away_team_score': game_info.get('away_team_score'),
                    'team_abbr': team_abbr,

                    # Player identification
                    'player_full_name': player_full_name,
                    'player_lookup': player_lookup,
                    'bdl_player_id': player.get('id'),
                    'jersey_number': player.get('jersey_number'),
                    'position': player.get('position'),

                    # Performance stats
                    'minutes': stat.get('min'),
                    'points': safe_int(stat.get('pts')),
                    'assists': safe_int(stat.get('ast')),
                    'rebounds': safe_int(stat.get('reb')),
                    'offensive_rebounds': safe_int(stat.get('oreb')),
                    'defensive_rebounds': safe_int(stat.get('dreb')),
                    'steals': safe_int(stat.get('stl')),
                    'blocks': safe_int(stat.get('blk')),
                    'turnovers': safe_int(stat.get('turnover')),
                    'personal_fouls': safe_int(stat.get('pf')),

                    # Shooting stats
                    'field_goals_made': safe_int(stat.get('fgm')),
                    'field_goals_attempted': safe_int(stat.get('fga')),
                    'field_goal_pct': safe_float(stat.get('fg_pct')),
                    'three_pointers_made': safe_int(stat.get('fg3m')),
                    'three_pointers_attempted': safe_int(stat.get('fg3a')),
                    'three_point_pct': safe_float(stat.get('fg3_pct')),
                    'free_throws_made': safe_int(stat.get('ftm')),
                    'free_throws_attempted': safe_int(stat.get('fta')),
                    'free_throw_pct': safe_float(stat.get('ft_pct')),

                    # Processing metadata
                    'source_file_path': file_path,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }

                rows.append(row)

            except Exception as e:
                logger.error(f"Error processing stat row: {e}")
                skipped_count += 1
                continue

        logger.info(f"Transformed {len(rows)} rows, skipped {skipped_count}")
        self.transformed_data = rows

        # Add data hash for smart idempotency
        self.add_data_hash()

    def save_data(self) -> None:
        """Save transformed data to BigQuery."""
        rows = self.transformed_data

        if not rows:
            logger.info("No rows to save")
            return {'rows_processed': 0, 'errors': []}

        table_id = f"{self.project_id}.{self.table_name}"
        errors = []

        try:
            # Get unique game IDs for logging
            game_ids = set(row['game_id'] for row in rows)
            logger.info(f"Loading {len(rows)} rows for {len(game_ids)} games using batch load")

            # Delete existing data for these games (MERGE_UPDATE strategy)
            for game_id in game_ids:
                game_date = next(row['game_date'] for row in rows if row['game_id'] == game_id)
                try:
                    delete_query = f"""
                    DELETE FROM `{table_id}`
                    WHERE game_id = '{game_id}'
                      AND game_date = '{game_date}'
                      AND DATETIME_DIFF(CURRENT_DATETIME(), DATETIME(processed_at), MINUTE) >= 90
                    """
                    self.bq_client.query(delete_query).result()
                except Exception as e:
                    if 'streaming buffer' in str(e).lower():
                        logger.warning(f"Streaming buffer prevents delete for {game_id}")
                    else:
                        raise

            # Get table schema for load job
            table = self.bq_client.get_table(table_id)

            # Configure batch load job
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
            logger.info(f"Successfully loaded {len(rows)} rows for {len(game_ids)} games")

            # Update stats
            self.stats['rows_inserted'] = len(rows)

            # Send success notification
            try:
                notify_info(
                    title="BDL Player Box Scores Processing Complete",
                    message=f"Processed {len(rows)} player box scores from {len(game_ids)} games",
                    details={
                        'player_records': len(rows),
                        'games_processed': len(game_ids),
                        'sample_game_ids': list(game_ids)[:3],
                        'table': self.table_name,
                        'processor': 'BdlPlayerBoxScoresProcessor'
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")

        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logger.error(f"Error loading data: {error_msg}")

            try:
                notify_error(
                    title="BDL Player Box Scores Processing Failed",
                    message=f"Error during processing: {str(e)[:200]}",
                    details={
                        'error': error_msg,
                        'error_type': type(e).__name__,
                        'rows_attempted': len(rows),
                        'processor': 'BdlPlayerBoxScoresProcessor'
                    },
                    processor_name="BdlPlayerBoxScoresProcessor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            raise

        return {'rows_processed': len(rows), 'errors': errors}

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'rows_failed': self.stats.get('rows_failed', 0),
            'run_id': self.stats.get('run_id'),
            'total_runtime': self.stats.get('total_runtime', 0)
        }
