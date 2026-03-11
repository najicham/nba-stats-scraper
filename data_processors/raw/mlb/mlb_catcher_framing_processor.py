"""
MLB Catcher Framing Processor

Processes catcher framing data from Baseball Savant to BigQuery.
Weekly refresh — framing runs stable within season.

GCS Path: mlb-external/catcher-framing/{season}/{timestamp}.json
Target Table: mlb_raw.catcher_framing

Processing Strategy: MERGE_UPDATE per scrape_date
Session 465: Initial implementation.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List

from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.config.sport_config import get_raw_dataset

logger = logging.getLogger(__name__)


class MlbCatcherFramingProcessor(ProcessorBase):
    """Processes MLB catcher framing data to BigQuery."""

    def __init__(self):
        self.dataset_id = get_raw_dataset()  # mlb_raw
        super().__init__()
        self.table_name = 'catcher_framing'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        self.raw_data = self.load_json_from_gcs()

    def validate_data(self, data: Dict) -> List[str]:
        errors = []
        if 'catchers' not in data:
            errors.append("Missing 'catchers' field")
        elif not isinstance(data['catchers'], list):
            errors.append("'catchers' is not a list")
        return errors

    def transform_data(self) -> None:
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []
        skipped = 0
        now = datetime.now(timezone.utc).isoformat()
        scrape_date = raw_data.get('scrape_date', datetime.now(timezone.utc).date().isoformat())

        catchers = raw_data.get('catchers', [])
        logger.info(f"Processing {len(catchers)} catcher framing records for {scrape_date}")

        for c in catchers:
            try:
                player_lookup = c.get('player_lookup')
                if not player_lookup:
                    skipped += 1
                    continue

                rows.append({
                    'player_name': c.get('player_name', ''),
                    'player_lookup': player_lookup,
                    'player_id': c.get('player_id'),
                    'team_abbr': c.get('team_abbr', ''),
                    'season': c.get('season'),
                    'games': c.get('games'),
                    'pitches_received': c.get('pitches_received'),
                    'framing_runs': c.get('framing_runs'),
                    'framing_runs_per_game': c.get('framing_runs_per_game'),
                    'strike_rate': c.get('strike_rate'),
                    'shadow_zone_strike_rate': c.get('shadow_zone_strike_rate'),
                    'scrape_date': scrape_date,
                    'created_at': now,
                })
            except Exception as e:
                logger.error(f"Error processing catcher {c.get('player_lookup', '?')}: {e}")
                skipped += 1

        logger.info(f"Transformed {len(rows)} catcher framing records, skipped {skipped}")
        self.transformed_data = rows
        self._scrape_date = scrape_date

    def save_data(self) -> None:
        rows = self.transformed_data
        if not rows:
            logger.info("No rows to save")
            self.stats["rows_inserted"] = 0
            return {'rows_processed': 0, 'errors': []}

        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
        errors = []

        try:
            # Delete existing data for this scrape date before re-insert
            try:
                delete_query = f"""
                DELETE FROM `{table_id}`
                WHERE scrape_date = '{self._scrape_date}'
                """
                self.bq_client.query(delete_query).result(timeout=60)
            except Exception as e:
                if 'not found' not in str(e).lower():
                    logger.warning(f"Delete failed for {self._scrape_date}: {e}")

            table = self.bq_client.get_table(table_id)
            job_config = bigquery.LoadJobConfig(
                schema=table.schema,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            )
            load_job = self.bq_client.load_table_from_json(rows, table_id, job_config=job_config)
            load_job.result(timeout=120)

            logger.info(f"Saved {len(rows)} catcher framing records to {table_id}")
            self.stats['rows_inserted'] = len(rows)

        except Exception as e:
            errors.append(str(e))
            logger.error(f"Error loading data: {e}")
            self.stats["rows_inserted"] = 0
            raise

        return {'rows_processed': len(rows), 'errors': errors}

    def get_processor_stats(self) -> Dict:
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'run_id': self.stats.get('run_id'),
        }
