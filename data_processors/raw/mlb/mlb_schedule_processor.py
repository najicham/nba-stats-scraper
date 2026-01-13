#!/usr/bin/env python3
"""
MLB Schedule Processor

Processes output from mlb_schedule scraper to BigQuery.
CRITICAL for predictions - provides probable pitchers.

GCS Path: mlb-stats-api/schedule/{date}/{timestamp}.json
Target Table: mlb_raw.mlb_schedule

Data Format (input):
{
    "scrape_date": "2025-06-15",
    "timestamp": "2025-06-15T10:30:00Z",
    "total_games": 15,
    "games_with_probable_pitchers": 12,
    "games": [
        {
            "game_pk": 745263,
            "game_date": "2025-06-15",
            "away_team_abbr": "NYY",
            "home_team_abbr": "BOS",
            "away_probable_pitcher_id": 543037,
            "away_probable_pitcher_name": "Gerrit Cole",
            "home_probable_pitcher_id": 519242,
            "home_probable_pitcher_name": "Chris Sale",
            ...
        }
    ]
}

Processing Strategy: MERGE_UPDATE per game_date
- Replaces schedule for the date with fresh data
- Handles pitcher announcements/changes

Created: 2026-01-06
"""

import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import notify_error, notify_warning, notify_info
from shared.config.sport_config import get_raw_dataset

logger = logging.getLogger(__name__)


class MlbScheduleProcessor(ProcessorBase):
    """
    MLB Schedule Processor

    Processes schedule data from MLB Stats API to BigQuery.
    Critical for knowing which pitchers are starting (prediction target).

    Processing Strategy: MERGE_UPDATE
    - Deletes existing records for the date before inserting
    - Allows schedule updates as pitchers are announced
    """

    def __init__(self):
        self.dataset_id = get_raw_dataset()  # mlb_raw
        super().__init__()
        self.table_name = 'mlb_schedule'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        """Load schedule data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def normalize_player_name(self, name: str) -> str:
        """Create normalized player lookup string."""
        if not name:
            return ""
        # Remove spaces, punctuation, and convert to lowercase
        normalized = re.sub(r'[^a-z0-9]', '', name.lower())
        return normalized

    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON structure."""
        errors = []

        if 'games' not in data:
            errors.append("Missing 'games' field")
            return errors

        if not isinstance(data['games'], list):
            errors.append("'games' is not a list")
            return errors

        return errors

    def transform_data(self) -> None:
        """Transform raw schedule data for BigQuery."""
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []
        skipped_count = 0

        games = raw_data.get('games', [])
        logger.info(f"Processing {len(games)} games from {file_path}")

        for game in games:
            try:
                game_pk = game.get('game_pk')
                game_date = game.get('game_date')

                if not game_pk or not game_date:
                    skipped_count += 1
                    continue

                # Parse game time
                game_time_utc = None
                if game.get('game_time_utc'):
                    try:
                        game_time_utc = game['game_time_utc']
                    except Exception:
                        pass

                row = {
                    # Core identifiers
                    'game_pk': game_pk,
                    'game_date': game_date,
                    'game_time_utc': game_time_utc,
                    'season': game.get('season') or int(game_date[:4]),
                    'game_type': game.get('game_type', 'R'),

                    # Teams
                    'away_team_id': game.get('away_team_id'),
                    'away_team_name': game.get('away_team_name', ''),
                    'away_team_abbr': game.get('away_team_abbr', ''),
                    'home_team_id': game.get('home_team_id'),
                    'home_team_name': game.get('home_team_name', ''),
                    'home_team_abbr': game.get('home_team_abbr', ''),

                    # Probable pitchers (THE KEY DATA!)
                    'away_probable_pitcher_id': game.get('away_probable_pitcher_id'),
                    'away_probable_pitcher_name': game.get('away_probable_pitcher_name'),
                    'away_probable_pitcher_number': game.get('away_probable_pitcher_number'),
                    'home_probable_pitcher_id': game.get('home_probable_pitcher_id'),
                    'home_probable_pitcher_name': game.get('home_probable_pitcher_name'),
                    'home_probable_pitcher_number': game.get('home_probable_pitcher_number'),

                    # Venue & context
                    'venue_id': game.get('venue_id'),
                    'venue_name': game.get('venue_name'),
                    'day_night': game.get('day_night'),
                    'series_description': game.get('series_description'),
                    'games_in_series': game.get('games_in_series'),
                    'series_game_number': game.get('series_game_number'),

                    # Status
                    'status_code': game.get('status_code'),
                    'status_detailed': game.get('status_detailed'),
                    'is_final': game.get('is_final', False),

                    # Scores
                    'away_score': game.get('away_score'),
                    'home_score': game.get('home_score'),
                    'away_hits': game.get('away_hits'),
                    'home_hits': game.get('home_hits'),

                    # Metadata
                    'source_file_path': file_path,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat(),
                }

                rows.append(row)

            except Exception as e:
                logger.error(f"Error processing game: {e}")
                skipped_count += 1
                continue

        # Log summary
        games_with_pitchers = sum(
            1 for r in rows
            if r.get('away_probable_pitcher_id') or r.get('home_probable_pitcher_id')
        )

        logger.info(
            f"Transformed {len(rows)} games ({games_with_pitchers} with probable pitchers), "
            f"skipped {skipped_count}"
        )
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
            # Get unique game dates for delete
            game_dates = set(row['game_date'] for row in rows)

            for game_date in game_dates:
                try:
                    delete_query = f"""
                    DELETE FROM `{table_id}`
                    WHERE game_date = '{game_date}'
                    """
                    self.bq_client.query(delete_query).result(timeout=60)
                except Exception as e:
                    if 'not found' in str(e).lower():
                        logger.info(f"Table doesn't exist yet, will be created")
                    else:
                        logger.warning(f"Delete failed for {game_date}: {e}")

            # Load data
            try:
                table = self.bq_client.get_table(table_id)

                job_config = bigquery.LoadJobConfig(
                    schema=table.schema,
                    write_disposition=bigquery.WriteDisposition.WRITE_APPEND
                )

                load_job = self.bq_client.load_table_from_json(
                    rows,
                    table_id,
                    job_config=job_config
                )
                load_job.result(timeout=120)

                logger.info(f"Saved {len(rows)} schedule rows to {table_id}")
                self.stats['rows_inserted'] = len(rows)

            except Exception as e:
                if 'not found' in str(e).lower():
                    logger.warning(f"Table {table_id} not found - run schema SQL first")
                raise

            # Calculate stats for notification
            games_with_both_pitchers = sum(
                1 for r in rows
                if r.get('away_probable_pitcher_id') and r.get('home_probable_pitcher_id')
            )

            notify_info(
                title="MLB Schedule Processing Complete",
                message=f"Processed {len(rows)} games",
                details={
                    'games': len(rows),
                    'games_with_both_starters': games_with_both_pitchers,
                    'dates': list(game_dates),
                    'processor': 'MlbScheduleProcessor'
                }
            )

        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logger.error(f"Error loading data: {error_msg}")
            self.stats["rows_inserted"] = 0

            notify_error(
                title="MLB Schedule Processing Failed",
                message=f"Error: {str(e)[:200]}",
                details={
                    'error': error_msg,
                    'rows_attempted': len(rows),
                    'processor': 'MlbScheduleProcessor'
                },
                processor_name="MlbScheduleProcessor"
            )
            raise

        return {'rows_processed': len(rows), 'errors': errors}

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'run_id': self.stats.get('run_id'),
        }


# CLI entry point
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Process MLB schedule from GCS')
    parser.add_argument('--bucket', default='mlb-scraped-data', help='GCS bucket')
    parser.add_argument('--file-path', required=True, help='Path to JSON file in GCS')

    args = parser.parse_args()

    processor = MlbScheduleProcessor()
    success = processor.run({
        'bucket': args.bucket,
        'file_path': args.file_path,
    })

    print(f"Processing {'succeeded' if success else 'failed'}")
    print(f"Stats: {processor.get_processor_stats()}")
