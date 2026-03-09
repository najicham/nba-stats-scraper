"""
MLB Weather Processor

Processes stadium weather data from OpenWeatherMap to BigQuery.
Daily snapshots — one row per stadium per scrape.

GCS Path: mlb-external/weather/{date}/{timestamp}.json
Target Table: mlb_raw.mlb_weather

Processing Strategy: MERGE_UPDATE per scrape_date
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List

from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.config.sport_config import get_raw_dataset

logger = logging.getLogger(__name__)


class MlbWeatherProcessor(ProcessorBase):
    """Processes MLB stadium weather data to BigQuery."""

    def __init__(self):
        self.dataset_id = get_raw_dataset()  # mlb_raw
        super().__init__()
        self.table_name = 'mlb_weather'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        self.raw_data = self.load_json_from_gcs()

    def validate_data(self, data: Dict) -> List[str]:
        errors = []
        if 'weather' not in data:
            errors.append("Missing 'weather' field")
        elif not isinstance(data['weather'], list):
            errors.append("'weather' is not a list")
        return errors

    def transform_data(self) -> None:
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []
        skipped = 0
        now = datetime.now(timezone.utc).isoformat()
        scrape_date = raw_data.get('date', datetime.now(timezone.utc).date().isoformat())

        weather_list = raw_data.get('weather', [])
        logger.info(f"Processing weather for {len(weather_list)} stadiums on {scrape_date}")

        for w in weather_list:
            try:
                team_abbr = w.get('team_abbr')
                if not team_abbr:
                    skipped += 1
                    continue

                # Skip error entries
                if w.get('error'):
                    skipped += 1
                    continue

                rows.append({
                    'scrape_date': scrape_date,
                    'team_abbr': team_abbr,
                    'stadium_name': w.get('stadium_name', ''),
                    'is_dome': w.get('is_dome', False),
                    'temperature_f': w.get('temperature_f'),
                    'feels_like_f': w.get('feels_like_f'),
                    'humidity_pct': w.get('humidity_pct'),
                    'wind_speed_mph': w.get('wind_speed_mph'),
                    'wind_direction_deg': w.get('wind_direction_deg'),
                    'wind_gust_mph': w.get('wind_gust_mph'),
                    'conditions': w.get('conditions', ''),
                    'description': w.get('description', ''),
                    'clouds_pct': w.get('clouds_pct'),
                    'pressure_hpa': w.get('pressure_hpa'),
                    'visibility_m': w.get('visibility_m'),
                    'k_weather_factor': w.get('k_weather_factor', 1.0),
                    'source_file_path': file_path,
                    'created_at': now,
                    'processed_at': now,
                })
            except Exception as e:
                logger.error(f"Error processing weather for {w.get('team_abbr', '?')}: {e}")
                skipped += 1

        logger.info(f"Transformed {len(rows)} weather records, skipped {skipped}")
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
            # Delete existing data for this date before re-insert
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

            logger.info(f"Saved {len(rows)} weather records to {table_id}")
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
