"""
MLB Umpire Assignments Processor

Processes output from mlb_umpire_assignments scraper to BigQuery.
Links home plate umpires to games for K-prediction signals.

GCS Path: mlb-stats-api/umpire-assignments/{date}/{timestamp}.json
Target Table: mlb_raw.mlb_umpire_assignments

Processing Strategy: MERGE_UPDATE per game_date
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List

from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.config.sport_config import get_raw_dataset

logger = logging.getLogger(__name__)


class MlbUmpireAssignmentsProcessor(ProcessorBase):
    """Processes umpire assignment data from MLB Stats API to BigQuery."""

    def __init__(self):
        self.dataset_id = get_raw_dataset()  # mlb_raw
        super().__init__()
        self.table_name = 'mlb_umpire_assignments'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        self.raw_data = self.load_json_from_gcs()

    def validate_data(self, data: Dict) -> List[str]:
        errors = []
        if 'assignments' not in data:
            errors.append("Missing 'assignments' field")
        elif not isinstance(data['assignments'], list):
            errors.append("'assignments' is not a list")
        return errors

    def transform_data(self) -> None:
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []
        skipped = 0
        now = datetime.now(timezone.utc).isoformat()

        assignments = raw_data.get('assignments', [])
        logger.info(f"Processing {len(assignments)} umpire assignments from {file_path}")

        for item in assignments:
            try:
                game_pk = item.get('game_pk')
                game_date = item.get('game_date')
                umpire_name = item.get('umpire_name')

                if not game_pk or not game_date or not umpire_name:
                    skipped += 1
                    continue

                rows.append({
                    'game_pk': game_pk,
                    'game_date': game_date,
                    'umpire_name': umpire_name,
                    'umpire_id': item.get('umpire_id'),
                    'umpire_link': item.get('umpire_link', ''),
                    'home_team_abbr': item.get('home_team', ''),
                    'away_team_abbr': item.get('away_team', ''),
                    'game_status': item.get('game_status', ''),
                    'source_file_path': file_path,
                    'created_at': now,
                    'processed_at': now,
                })
            except Exception as e:
                logger.error(f"Error processing assignment: {e}")
                skipped += 1

        logger.info(f"Transformed {len(rows)} assignments, skipped {skipped}")
        self.transformed_data = rows

    def save_data(self) -> None:
        rows = self.transformed_data
        if not rows:
            logger.info("No rows to save")
            self.stats["rows_inserted"] = 0
            return {'rows_processed': 0, 'errors': []}

        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
        errors = []

        try:
            game_dates = set(row['game_date'] for row in rows)
            for game_date in game_dates:
                try:
                    delete_query = f"""
                    DELETE FROM `{table_id}`
                    WHERE game_date = '{game_date}'
                    """
                    self.bq_client.query(delete_query).result(timeout=60)
                except Exception as e:
                    if 'not found' not in str(e).lower():
                        logger.warning(f"Delete failed for {game_date}: {e}")

            table = self.bq_client.get_table(table_id)
            job_config = bigquery.LoadJobConfig(
                schema=table.schema,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            )
            load_job = self.bq_client.load_table_from_json(rows, table_id, job_config=job_config)
            load_job.result(timeout=120)

            logger.info(f"Saved {len(rows)} umpire assignments to {table_id}")
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
