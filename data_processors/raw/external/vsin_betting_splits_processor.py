"""
VSiN Betting Splits Processor

GCS Path: gs://nba-scraped-data/external/vsin/betting-splits/{date}/{timestamp}.json
BigQuery Table: nba_raw.vsin_betting_splits
"""

import logging
import os
from datetime import datetime, timezone

from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.utils.notification_system import notify_error

logger = logging.getLogger(__name__)


class VSiNBettingSplitsProcessor(SmartIdempotencyMixin, ProcessorBase):

    HASH_FIELDS = ['away_team', 'home_team', 'game_date', 'over_ticket_pct']

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.vsin_betting_splits'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        self.raw_data = self.load_json_from_gcs()

    def transform_data(self) -> None:
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []

        try:
            game_date = raw_data.get('date')
            if not game_date:
                raise ValueError(f"Missing date: {file_path}")

            scraped_at = raw_data.get('timestamp')
            current_time = datetime.now(timezone.utc).isoformat()

            for game in raw_data.get('games', []):
                row = {
                    'game_date': game_date,
                    'away_team': game.get('away_team', ''),
                    'home_team': game.get('home_team', ''),
                    'total_line': game.get('total_line'),
                    'over_ticket_pct': game.get('over_ticket_pct'),
                    'under_ticket_pct': game.get('under_ticket_pct'),
                    'over_money_pct': game.get('over_money_pct'),
                    'under_money_pct': game.get('under_money_pct'),
                    'spread': game.get('spread'),
                    'home_spread_pct': game.get('home_spread_pct'),
                    'away_spread_pct': game.get('away_spread_pct'),
                    'source_file_path': file_path,
                    'scraped_at': scraped_at,
                    'processed_at': current_time,
                }
                rows.append(row)

            logger.info(f"Transformed {len(rows)} VSiN betting splits from {file_path}")
        except Exception as e:
            logger.error(f"Transform failed for {file_path}: {e}", exc_info=True)
            try:
                notify_error(title="VSiN Transform Failed", message=str(e),
                             details={'file_path': file_path}, processor_name=self.__class__.__name__)
            except Exception:
                pass
            raise

        self.transformed_data = rows
        self.add_data_hash()

    def save_data(self) -> None:
        rows = self.transformed_data
        if not rows:
            self.stats['rows_inserted'] = 0
            return
        table_id = f"{self.project_id}.{self.table_name}"
        try:
            table_ref = self.bq_client.get_table(table_id)
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema, autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True,
            )
            load_job = self.bq_client.load_table_from_json(rows, table_id, job_config=job_config)
            load_job.result(timeout=60)
            if load_job.errors:
                logger.error(f"BQ errors: {load_job.errors}")
            else:
                self.stats['rows_inserted'] = len(rows)
        except Exception as e:
            logger.error(f"BQ load failed: {e}", exc_info=True)
            self.stats['rows_inserted'] = 0
            self.stats['rows_failed'] = len(rows)
