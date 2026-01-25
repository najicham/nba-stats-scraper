#!/usr/bin/env python3
"""
MLB Ball Don't Lie Pitcher Stats Processor

Processes output from mlb_pitcher_stats scraper to BigQuery.
Key field: p_k (strikeouts) - our target variable for predictions.

GCS Path: ball-dont-lie/mlb-pitcher-stats/{date}/{timestamp}.json
Target Table: mlb_raw.bdl_pitcher_stats

Data Format (input):
{
    "date": "2025-06-15",
    "timestamp": "2025-06-16T01:23:45Z",
    "rowCount": 45,
    "pitcherStats": [
        {
            "id": 12345,
            "p_k": 6,           # Strikeouts (TARGET!)
            "ip": 6.2,          # Innings pitched
            "pitch_count": 108, # Total pitches
            ...
            "player": {"id": 1, "first_name": "Gerrit", "last_name": "Cole", ...},
            "team": {"id": 10, "abbreviation": "NYY", "full_name": "New York Yankees"},
            "game": {"id": 123, "date": "2025-06-15", "status": "Final", ...}
        }
    ]
}

Created: 2026-01-06
"""

import json
import os
import logging
import re
from typing import Dict, List, Optional
from datetime import datetime, date, timezone
from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)
from shared.config.sport_config import get_raw_dataset, get_bucket

logger = logging.getLogger(__name__)


# MLB team abbreviations
MLB_TEAM_ABBREVS = {
    'ARI', 'ATL', 'BAL', 'BOS', 'CHC', 'CHW', 'CIN', 'CLE', 'COL', 'DET',
    'HOU', 'KC', 'LAA', 'LAD', 'MIA', 'MIL', 'MIN', 'NYM', 'NYY', 'OAK',
    'PHI', 'PIT', 'SD', 'SF', 'SEA', 'STL', 'TB', 'TEX', 'TOR', 'WSH'
}


class MlbPitcherStatsProcessor(ProcessorBase):
    """
    MLB Ball Don't Lie Pitcher Stats Processor

    Processes pitcher game stats from GCS to BigQuery.
    Primary source for strikeout prediction target variable.

    Processing Strategy: MERGE_UPDATE
    - Deletes existing records for the game before inserting
    - Prevents duplicate pitcher records
    """

    def __init__(self):
        # Set dataset before calling super().__init__
        self.dataset_id = get_raw_dataset()  # Will be 'mlb_raw' when SPORT=mlb
        super().__init__()
        self.table_name = 'bdl_pitcher_stats'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        """Load pitcher stats data from GCS."""
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
        if abbr and abbr.upper() in MLB_TEAM_ABBREVS:
            return abbr.upper()

        # Fallback to first 3 chars of city
        city = team_data.get('city', '')
        if city:
            return city.upper()[:3]

        return ""

    def extract_season_year(self, game_date: str) -> int:
        """Extract season year from date."""
        # Handle dates with time component (e.g., '2024-10-30T00:08:00.000Z')
        if 'T' in game_date:
            game_date = game_date.split('T')[0]
        game_dt = datetime.strptime(game_date, '%Y-%m-%d').date()
        # MLB season is April-October, simple year extraction
        return game_dt.year

    def normalize_game_date(self, game_date: str) -> str:
        """Normalize date to YYYY-MM-DD format."""
        if not game_date:
            return ''
        # Handle dates with time component
        if 'T' in game_date:
            game_date = game_date.split('T')[0]
        return game_date

    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON structure."""
        errors = []

        if 'pitcherStats' not in data:
            errors.append("Missing 'pitcherStats' field")
            return errors

        if not isinstance(data['pitcherStats'], list):
            errors.append("'pitcherStats' is not a list")
            return errors

        if not data['pitcherStats']:
            # Empty stats is valid (no games on that date)
            logger.info("Empty pitcherStats array - no pitcher data for this date")

        return errors

    def transform_data(self) -> None:
        """Transform raw data into transformed data for BigQuery."""
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []
        skipped_count = 0

        pitcher_stats = raw_data.get('pitcherStats', [])
        logger.info(f"Processing {len(pitcher_stats)} pitcher stat rows from {file_path}")

        # Process all stats
        for stat in pitcher_stats:
            try:
                game = stat.get('game', {})
                player = stat.get('player', {})

                # Team info can be in 'team' dict or 'team_name' string
                team = stat.get('team', {})
                team_name = stat.get('team_name', '')

                if not game or not player:
                    logger.debug(f"Skipping stat - missing game or player")
                    skipped_count += 1
                    continue

                # Extract team abbreviations from game object
                home_team = game.get('home_team', {})
                away_team = game.get('away_team', {})
                home_abbr = home_team.get('abbreviation', 'UNK') if home_team else 'UNK'
                away_abbr = away_team.get('abbreviation', 'UNK') if away_team else 'UNK'

                # Get game scores from scoring summary if available
                # scoring_summary is a list of plays - get final scores from last item
                scoring = game.get('scoring_summary', [])
                if scoring and isinstance(scoring, list) and len(scoring) > 0:
                    last_play = scoring[-1]
                    home_score = last_play.get('home_score')
                    away_score = last_play.get('away_score')
                else:
                    home_score = None
                    away_score = None

                game_date = self.normalize_game_date(game.get('date', ''))
                bdl_game_id = game.get('id')

                # Build game_id: just use BDL ID for now (simpler than NBA format)
                game_id = str(bdl_game_id)

                # Player info
                first_name = player.get('first_name', '')
                last_name = player.get('last_name', '')
                if not first_name or not last_name:
                    logger.debug(f"Skipping stat - missing player name")
                    skipped_count += 1
                    continue

                player_full_name = f"{first_name} {last_name}"
                player_lookup = self.normalize_player_name(first_name, last_name)

                # Determine pitcher's team abbreviation
                # If we have a team dict, use it; otherwise infer from team_name
                if team and isinstance(team, dict):
                    team_abbr = self.extract_team_abbr(team)
                elif team_name:
                    # Match team_name to one of home/away team names
                    if team_name == home_team.get('name') or team_name == home_team.get('display_name'):
                        team_abbr = home_abbr
                    elif team_name == away_team.get('name') or team_name == away_team.get('display_name'):
                        team_abbr = away_abbr
                    else:
                        # Try partial match
                        if home_team.get('name', '') in team_name or team_name in home_team.get('display_name', ''):
                            team_abbr = home_abbr
                        elif away_team.get('name', '') in team_name or team_name in away_team.get('display_name', ''):
                            team_abbr = away_abbr
                        else:
                            team_abbr = 'UNK'
                else:
                    team_abbr = 'UNK'

                # Helper functions
                def safe_int(val):
                    return int(val) if val is not None else 0

                def safe_float(val):
                    if val is None:
                        return None
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        return None

                # Build row matching BigQuery schema
                row = {
                    # Core identifiers
                    'game_id': game_id,
                    'game_date': game_date,
                    'season_year': self.extract_season_year(game_date) if game_date else None,
                    'is_postseason': game.get('postseason', False),

                    # Game context
                    'home_team_abbr': home_abbr or '',
                    'away_team_abbr': away_abbr or '',
                    'home_team_score': home_score,
                    'away_team_score': away_score,
                    'venue': game.get('venue', ''),
                    'game_status': game.get('status', ''),

                    # Pitcher identification
                    'bdl_player_id': player.get('id'),
                    'player_full_name': player_full_name,
                    'player_lookup': player_lookup,
                    'team_abbr': team_abbr,
                    'position': player.get('position', ''),
                    'jersey_number': player.get('jersey_number'),

                    # Pitching stats - CORE (for predictions)
                    'strikeouts': safe_int(stat.get('p_k') or stat.get('strikeouts') or stat.get('_strikeouts')),
                    'innings_pitched': safe_float(stat.get('ip') or stat.get('innings_pitched') or stat.get('_innings_pitched')),
                    'pitch_count': safe_int(stat.get('pitch_count')),
                    'strikes': safe_int(stat.get('strikes')),

                    # Pitching stats - Extended
                    'walks_allowed': safe_int(stat.get('p_bb') or stat.get('walks')),
                    'hits_allowed': safe_int(stat.get('p_hits') or stat.get('hits_allowed')),
                    'runs_allowed': safe_int(stat.get('p_runs') or stat.get('runs_allowed')),
                    'earned_runs': safe_int(stat.get('er') or stat.get('earned_runs')),
                    'home_runs_allowed': safe_int(stat.get('p_hr') or stat.get('home_runs_allowed')),
                    'era': safe_float(stat.get('era')),

                    # Game result
                    'win': stat.get('win', False) or False,
                    'loss': stat.get('loss', False) or False,
                    'save': stat.get('save', False) or False,
                    'hold': stat.get('hold', False) or False,
                    'blown_save': stat.get('blown_save', False) or False,

                    # Processing metadata
                    'source_file_path': file_path,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }

                rows.append(row)

            except Exception as e:
                logger.error(f"Error processing pitcher stat row: {e}")
                skipped_count += 1
                continue

        # Log summary stats
        total_ks = sum(r.get('strikeouts', 0) or 0 for r in rows)
        avg_ks = total_ks / len(rows) if rows else 0

        logger.info(f"Transformed {len(rows)} rows, skipped {skipped_count}")
        logger.info(f"Total strikeouts: {total_ks}, Avg: {avg_ks:.2f}")
        self.transformed_data = rows

    def save_data(self) -> None:
        """Save transformed data to BigQuery."""
        rows = self.transformed_data

        if not rows:
            logger.info("No rows to save")
            self.stats["rows_inserted"] = 0
            return {'rows_processed': 0, 'errors': []}

        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
        errors = []

        try:
            # Get unique game IDs for logging
            game_ids = set(row['game_id'] for row in rows)
            logger.info(f"Loading {len(rows)} rows for {len(game_ids)} games using batch load")

            # Delete existing data for these games (MERGE_UPDATE strategy)
            for game_id in game_ids:
                game_date = next((row['game_date'] for row in rows if row['game_id'] == game_id), None)
                if game_date is None:
                    logger.warning(f"game_id {game_id} not found in rows, skipping delete")
                    continue
                try:
                    delete_query = f"""
                    DELETE FROM `{table_id}`
                    WHERE game_id = '{game_id}'
                      AND game_date = '{game_date}'
                    """
                    self.bq_client.query(delete_query).result(timeout=60)
                except Exception as e:
                    if 'streaming buffer' in str(e).lower():
                        logger.warning(f"Streaming buffer prevents delete for {game_id}")
                    elif 'not found' in str(e).lower():
                        # Table doesn't exist yet - will be created on insert
                        logger.info(f"Table doesn't exist yet, will create on first insert")
                    else:
                        raise

            # Get table schema for load job
            try:
                table = self.bq_client.get_table(table_id)
            except Exception as e:
                if 'not found' in str(e).lower():
                    logger.warning(f"Table {table_id} not found - run schema SQL first")
                    raise

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
            load_job.result(timeout=60)
            logger.info(f"Successfully loaded {len(rows)} rows for {len(game_ids)} games")

            # Update stats
            self.stats['rows_inserted'] = len(rows)

            # Calculate summary for notification
            total_ks = sum(r.get('strikeouts', 0) or 0 for r in rows)
            avg_ks = total_ks / len(rows) if rows else 0

            # Send success notification
            try:
                notify_info(
                    title="MLB Pitcher Stats Processing Complete",
                    message=f"Processed {len(rows)} pitcher stats from {len(game_ids)} games",
                    details={
                        'pitcher_records': len(rows),
                        'games_processed': len(game_ids),
                        'total_strikeouts': total_ks,
                        'avg_strikeouts': round(avg_ks, 2),
                        'table': f"{self.dataset_id}.{self.table_name}",
                        'processor': 'MlbPitcherStatsProcessor'
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")

        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logger.error(f"Error loading data: {error_msg}")
            self.stats["rows_inserted"] = 0

            try:
                notify_error(
                    title="MLB Pitcher Stats Processing Failed",
                    message=f"Error during processing: {str(e)[:200]}",
                    details={
                        'error': error_msg,
                        'error_type': type(e).__name__,
                        'rows_attempted': len(rows),
                        'processor': 'MlbPitcherStatsProcessor'
                    },
                    processor_name="MlbPitcherStatsProcessor"
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


# CLI entry point for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Process MLB pitcher stats from GCS')
    parser.add_argument('--bucket', default='mlb-scraped-data', help='GCS bucket')
    parser.add_argument('--file-path', required=True, help='Path to JSON file in GCS')
    parser.add_argument('--date', help='Game date (YYYY-MM-DD)')

    args = parser.parse_args()

    processor = MlbPitcherStatsProcessor()
    success = processor.run({
        'bucket': args.bucket,
        'file_path': args.file_path,
        'date': args.date
    })

    print(f"Processing {'succeeded' if success else 'failed'}")
    print(f"Stats: {processor.get_processor_stats()}")
