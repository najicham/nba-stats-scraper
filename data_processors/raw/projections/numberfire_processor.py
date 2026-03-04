"""
NumberFire Projections Processor

GCS Path: gs://nba-scraped-data/projections/numberfire/{date}/{timestamp}.json
BigQuery Table: nba_raw.numberfire_projections

Processing Strategy: APPEND_ALWAYS (daily projections, each scrape is unique)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List

from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.utils.notification_system import notify_error, notify_info

logger = logging.getLogger(__name__)


class NumberFireProjectionsProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    NumberFire Projections Processor

    Processing Strategy: APPEND_ALWAYS
    Smart Idempotency: Enabled
        Hash Fields: player_lookup, game_date, projected_points
    """

    HASH_FIELDS = [
        'player_lookup',
        'game_date',
        'projected_points',
    ]

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.numberfire_projections'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        """Load data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def transform_data(self) -> None:
        """Transform NumberFire JSON into BQ rows."""
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []

        try:
            game_date = raw_data.get('date')
            if not game_date:
                raise ValueError(f"Missing date in NumberFire data: {file_path}")

            scraped_at = raw_data.get('timestamp')
            current_time = datetime.now(timezone.utc).isoformat()

            for player in raw_data.get('players', []):
                player_lookup = player.get('player_lookup')
                if not player_lookup:
                    continue

                row = {
                    'game_date': game_date,
                    'player_name': player.get('player_name', ''),
                    'player_lookup': player_lookup,
                    'team': player.get('team', ''),
                    'position': player.get('position', ''),
                    'projected_points': player.get('projected_points'),
                    'projected_minutes': player.get('projected_minutes'),
                    'projected_rebounds': player.get('projected_rebounds'),
                    'projected_assists': player.get('projected_assists'),
                    'source_file_path': file_path,
                    'scraped_at': scraped_at,
                    'processed_at': current_time,
                }
                rows.append(row)

            logger.info(f"Transformed {len(rows)} NumberFire projections from {file_path}")

        except Exception as e:
            logger.error(f"Transform failed for {file_path}: {e}", exc_info=True)
            try:
                notify_error(
                    title="NumberFire Projections Transform Failed",
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
                logger.info(f"Loaded {len(rows)} NumberFire projection rows to BQ")

        except Exception as e:
            logger.error(f"Failed to load to BigQuery: {e}", exc_info=True)
            self.stats['rows_inserted'] = 0
            self.stats['rows_failed'] = len(rows)
            try:
                notify_error(
                    title="NumberFire BQ Load Failed",
                    message=str(e),
                    details={'table': self.table_name, 'rows': len(rows)},
                    processor_name=self.__class__.__name__
                )
            except Exception:
                pass
