"""
MLB Umpire Stats Processor

Processes umpire accuracy/tendency data from UmpScorecards to BigQuery.
Seasonal data — refreshed periodically to track umpire K tendencies.

GCS Path: mlb-external/umpire-stats/{season}/{timestamp}.json
Target Table: mlb_raw.mlb_umpire_stats

Processing Strategy: MERGE_UPDATE per season
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List

from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.config.sport_config import get_raw_dataset

logger = logging.getLogger(__name__)


class MlbUmpireStatsProcessor(ProcessorBase):
    """Processes umpire stats from UmpScorecards to BigQuery."""

    def __init__(self):
        self.dataset_id = get_raw_dataset()  # mlb_raw
        super().__init__()
        self.table_name = 'mlb_umpire_stats'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        self.raw_data = self.load_json_from_gcs()

    def validate_data(self, data: Dict) -> List[str]:
        errors = []
        if 'umpires' not in data:
            errors.append("Missing 'umpires' field")
        elif not isinstance(data['umpires'], list):
            errors.append("'umpires' is not a list")
        return errors

    def transform_data(self) -> None:
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []
        skipped = 0
        now = datetime.now(timezone.utc).isoformat()
        season = raw_data.get('season', str(datetime.now().year))
        scrape_date = raw_data.get('date', datetime.now(timezone.utc).date().isoformat())

        umpires = raw_data.get('umpires', [])
        logger.info(f"Processing {len(umpires)} umpire stats for season {season}")

        for ump in umpires:
            try:
                name = ump.get('name')
                if not name:
                    skipped += 1
                    continue

                rows.append({
                    'umpire_name': name,
                    'season': int(season),
                    'scrape_date': scrape_date,
                    'games': ump.get('games', 0),
                    'accuracy': ump.get('accuracy'),
                    'consistency': ump.get('consistency'),
                    'favor': ump.get('favor'),
                    'k_zone_tendency': ump.get('k_zone_tendency', 'average'),
                    'source_file_path': file_path,
                    'created_at': now,
                    'processed_at': now,
                })
            except Exception as e:
                logger.error(f"Error processing umpire: {e}")
                skipped += 1

        logger.info(f"Transformed {len(rows)} umpire stats, skipped {skipped}")
        self.transformed_data = rows
        self._season = season

    def save_data(self) -> None:
        rows = self.transformed_data
        if not rows:
            logger.info("No rows to save")
            self.stats["rows_inserted"] = 0
            return {'rows_processed': 0, 'errors': []}

        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
        errors = []

        try:
            # Delete existing season data before re-insert
            try:
                delete_query = f"""
                DELETE FROM `{table_id}`
                WHERE season = {self._season}
                """
                self.bq_client.query(delete_query).result(timeout=60)
            except Exception as e:
                if 'not found' not in str(e).lower():
                    logger.warning(f"Delete failed for season {self._season}: {e}")

            table = self.bq_client.get_table(table_id)
            job_config = bigquery.LoadJobConfig(
                schema=table.schema,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            )
            load_job = self.bq_client.load_table_from_json(rows, table_id, job_config=job_config)
            load_job.result(timeout=120)

            logger.info(f"Saved {len(rows)} umpire stats to {table_id}")
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
