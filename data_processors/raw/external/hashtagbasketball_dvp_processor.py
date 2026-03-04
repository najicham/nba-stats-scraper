"""
Hashtag Basketball Defense vs Position Processor

GCS Path: gs://nba-scraped-data/external/hashtagbasketball/dvp/{date}/{timestamp}.json
BigQuery Table: nba_raw.hashtagbasketball_dvp

Processing Strategy: APPEND_ALWAYS (daily DvP snapshots)
Nested Structure: teams[] -> positions{} -> stats per position
Flattened to one row per team-position combination.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List

from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.utils.notification_system import notify_error

logger = logging.getLogger(__name__)


class HashtagBasketballDvpProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Hashtag Basketball DvP Processor

    Processing Strategy: APPEND_ALWAYS
    Smart Idempotency: Enabled
        Hash Fields: team, position, game_date, points_allowed
    """

    HASH_FIELDS = [
        'team',
        'position',
        'game_date',
        'points_allowed',
    ]

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.hashtagbasketball_dvp'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        """Load data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def transform_data(self) -> None:
        """Transform DvP JSON into flat BQ rows (one per team-position)."""
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []

        try:
            game_date = raw_data.get('date')
            if not game_date:
                raise ValueError(f"Missing date in DvP data: {file_path}")

            scraped_at = raw_data.get('timestamp')
            current_time = datetime.now(timezone.utc).isoformat()

            for team_data in raw_data.get('teams', []):
                team = team_data.get('team')
                if not team:
                    continue

                positions = team_data.get('positions', {})
                for position, stats in positions.items():
                    row = {
                        'game_date': game_date,
                        'team': team,
                        'position': position,
                        'points_allowed': stats.get('points_allowed'),
                        'rebounds_allowed': stats.get('rebounds_allowed'),
                        'assists_allowed': stats.get('assists_allowed'),
                        'rank': stats.get('rank'),
                        'source_file_path': file_path,
                        'scraped_at': scraped_at,
                        'processed_at': current_time,
                    }
                    rows.append(row)

            logger.info(f"Transformed {len(rows)} DvP rows from {file_path}")

        except Exception as e:
            logger.error(f"Transform failed for {file_path}: {e}", exc_info=True)
            try:
                notify_error(
                    title="DvP Transform Failed",
                    message=str(e),
                    details={'file_path': file_path, 'error_type': type(e).__name__},
                    processor_name=self.__class__.__name__
                )
            except Exception:
                pass
            raise

        self.transformed_data = rows
        self.add_data_hash()

    def save_data(self) -> None:
        """Save to BigQuery using batch loading."""
        rows = self.transformed_data
        if not rows:
            self.stats['rows_inserted'] = 0
            return

        table_id = f"{self.project_id}.{self.table_name}"

        try:
            table_ref = self.bq_client.get_table(table_id)
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True,
            )
            load_job = self.bq_client.load_table_from_json(rows, table_id, job_config=job_config)
            load_job.result(timeout=60)

            if load_job.errors:
                logger.error(f"BQ batch load errors: {load_job.errors}")
            else:
                self.stats['rows_inserted'] = len(rows)
                logger.info(f"Loaded {len(rows)} DvP rows to BQ")

        except Exception as e:
            logger.error(f"Failed to load to BigQuery: {e}", exc_info=True)
            self.stats['rows_inserted'] = 0
            self.stats['rows_failed'] = len(rows)
            try:
                notify_error(
                    title="DvP BQ Load Failed",
                    message=str(e),
                    details={'table': self.table_name, 'rows': len(rows)},
                    processor_name=self.__class__.__name__
                )
            except Exception:
                pass
