#!/usr/bin/env python3
"""
MLB Odds API Events Processor

Processes event IDs from The Odds API to BigQuery.
Event IDs are needed to fetch player props and are used as join keys.

GCS Path: mlb-odds-api/events/{date}/{timestamp}.json
Target Table: mlb_raw.oddsa_events

Data Format (input from scraper):
{
    "sport": "baseball_mlb",
    "game_date": "2025-06-15",
    "rowCount": 15,
    "events": [
        {
            "id": "abc123def456...",
            "sport_key": "baseball_mlb",
            "sport_title": "MLB",
            "commence_time": "2025-06-15T23:10:00Z",
            "home_team": "New York Yankees",
            "away_team": "Boston Red Sox",
            "_home_team": "New York Yankees",
            "_away_team": "Boston Red Sox"
        }
    ]
}

Created: 2026-01-06
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List

from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import notify_error, notify_warning, notify_info
from shared.config.sport_config import get_raw_dataset

logger = logging.getLogger(__name__)


# MLB team mappings
MLB_TEAM_MAP = {
    'arizona diamondbacks': 'ARI', 'atlanta braves': 'ATL',
    'baltimore orioles': 'BAL', 'boston red sox': 'BOS',
    'chicago cubs': 'CHC', 'chicago white sox': 'CHW',
    'cincinnati reds': 'CIN', 'cleveland guardians': 'CLE',
    'colorado rockies': 'COL', 'detroit tigers': 'DET',
    'houston astros': 'HOU', 'kansas city royals': 'KC',
    'los angeles angels': 'LAA', 'los angeles dodgers': 'LAD',
    'miami marlins': 'MIA', 'milwaukee brewers': 'MIL',
    'minnesota twins': 'MIN', 'new york mets': 'NYM',
    'new york yankees': 'NYY', 'oakland athletics': 'OAK',
    'philadelphia phillies': 'PHI', 'pittsburgh pirates': 'PIT',
    'san diego padres': 'SD', 'san francisco giants': 'SF',
    'seattle mariners': 'SEA', 'st. louis cardinals': 'STL',
    'st louis cardinals': 'STL', 'tampa bay rays': 'TB',
    'texas rangers': 'TEX', 'toronto blue jays': 'TOR',
    'washington nationals': 'WSH',
}


class MlbEventsProcessor(ProcessorBase):
    """
    MLB Odds API Events Processor

    Maps game dates to Odds API event IDs.
    Event IDs are used as join keys for props and game lines.

    Processing Strategy: APPEND_ALWAYS
    - Multiple snapshots per day are stored
    - Enables tracking of event availability over time
    """

    def __init__(self):
        self.dataset_id = get_raw_dataset()
        super().__init__()
        self.table_name = 'oddsa_events'
        self.processing_strategy = 'APPEND_ALWAYS'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        """Load events data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def get_team_abbr(self, team_name: str) -> str:
        """Get MLB team abbreviation from full name."""
        if not team_name:
            return ''

        team_lower = team_name.lower().strip()
        if team_lower in MLB_TEAM_MAP:
            return MLB_TEAM_MAP[team_lower]

        for full_name, abbr in MLB_TEAM_MAP.items():
            if full_name in team_lower or team_lower in full_name:
                return abbr

        return team_name[:3].upper() if team_name else ''

    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON structure."""
        errors = []

        if not data:
            errors.append("Empty data")
            return errors

        if 'events' not in data:
            errors.append("Missing 'events' field")
            return errors

        if not isinstance(data['events'], list):
            errors.append("'events' is not a list")

        return errors

    def transform_data(self) -> None:
        """Transform raw data into rows for BigQuery."""
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []

        try:
            errors = self.validate_data(raw_data)
            if errors:
                logger.warning(f"Validation issues for {file_path}: {errors}")
                self.transformed_data = rows
                return

            game_date = raw_data.get('game_date')
            events = raw_data.get('events', [])
            snapshot_time = datetime.now(timezone.utc)

            for event in events:
                event_id = event.get('id')
                if not event_id:
                    continue

                home_team = event.get('home_team', '')
                away_team = event.get('away_team', '')

                # Parse commence time
                commence_time = event.get('commence_time')
                if commence_time:
                    try:
                        commence_dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                    except (ValueError, TypeError):
                        commence_dt = None
                else:
                    commence_dt = None

                row = {
                    'event_id': event_id,
                    'game_date': game_date,
                    'commence_time': commence_dt.isoformat() if commence_dt else None,
                    'home_team': home_team,
                    'away_team': away_team,
                    'home_team_abbr': self.get_team_abbr(home_team),
                    'away_team_abbr': self.get_team_abbr(away_team),
                    'sport_key': event.get('sport_key', 'baseball_mlb'),
                    'snapshot_time': snapshot_time.isoformat(),
                    'source_file_path': file_path,
                    'created_at': snapshot_time.isoformat(),
                }

                rows.append(row)

            logger.info(f"Transformed {len(rows)} events from {file_path}")
            self.transformed_data = rows

        except Exception as e:
            logger.error(f"Transform failed for {file_path}: {e}", exc_info=True)
            notify_error(
                title="MLB Events Transform Failed",
                message=f"Error transforming events: {str(e)[:200]}",
                details={'file_path': file_path, 'error': str(e)},
                processor_name="MlbEventsProcessor"
            )
            raise

    def save_data(self) -> None:
        """Save transformed data to BigQuery."""
        rows = self.transformed_data

        if not rows:
            logger.info("No rows to save")
            self.stats['rows_inserted'] = 0
            return

        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"

        try:
            try:
                target_table = self.bq_client.get_table(table_id)
            except Exception as e:
                if 'not found' in str(e).lower():
                    logger.error(f"Table {table_id} not found - run schema SQL first")
                    raise
                raise

            job_config = bigquery.LoadJobConfig(
                schema=target_table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(
                rows,
                table_id,
                job_config=job_config
            )
            load_job.result(timeout=60)

            if load_job.errors:
                logger.error(f"BigQuery load had errors: {load_job.errors[:3]}")
                return

            self.stats['rows_inserted'] = len(rows)
            logger.info(f"Successfully loaded {len(rows)} events to {table_id}")

            notify_info(
                title="MLB Events Processing Complete",
                message=f"Loaded {len(rows)} events",
                details={
                    'events_loaded': len(rows),
                    'table': f"{self.dataset_id}.{self.table_name}",
                },
                processor_name=self.__class__.__name__
            )

        except Exception as e:
            logger.error(f"Failed to save data: {e}", exc_info=True)
            self.stats["rows_inserted"] = 0
            notify_error(
                title="MLB Events Save Failed",
                message=f"Error saving to BigQuery: {str(e)[:200]}",
                details={'table': self.table_name, 'error': str(e)},
                processor_name="MlbEventsProcessor"
            )
            raise

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'rows_failed': self.stats.get('rows_failed', 0),
            'run_id': self.stats.get('run_id'),
            'total_runtime': self.stats.get('total_runtime', 0)
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Process MLB events from GCS')
    parser.add_argument('--bucket', default='mlb-scraped-data', help='GCS bucket')
    parser.add_argument('--file-path', required=True, help='Path to JSON file in GCS')

    args = parser.parse_args()

    processor = MlbEventsProcessor()
    success = processor.run({
        'bucket': args.bucket,
        'file_path': args.file_path,
    })

    print(f"Processing {'succeeded' if success else 'failed'}")
    print(f"Stats: {processor.get_processor_stats()}")
