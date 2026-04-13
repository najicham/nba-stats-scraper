#!/usr/bin/env python3
"""
MLB Statcast Daily Pitcher Summary Processor

Processes output from mlb_statcast_daily scraper to BigQuery.
Key fields: swstr_pct, csw_pct, whiff_rate - most predictive of K outcomes.

GCS Path: mlb-statcast/daily-pitcher-summary/{date}/{timestamp}.json
Target Table: mlb_raw.statcast_pitcher_daily

Data Format (input):
{
    "date": "2025-06-15",
    "timestamp": "2025-06-16T01:23:45Z",
    "pitchers_found": 48,
    "total_pitches": 4200,
    "pitcher_summaries": [
        {
            "pitcher_id": 543037,
            "pitcher_name": "Cole, Gerrit",
            "game_date": "2025-06-15",
            "game_pk": 745263,
            "total_pitches": 108,
            "avg_velocity": 96.3,
            "max_velocity": 99.1,
            "avg_spin_rate": 2410.0,
            "swinging_strikes": 18,
            "called_strikes": 12,
            "fouls": 14,
            "balls": 35,
            "in_play": 15,
            "swstr_pct": 16.7,
            "csw_pct": 27.8,
            "whiff_rate": 38.3,
            "zone_pct": 48.1,
            "chase_rate": 32.5,
            "pitch_types": {"FF": 42, "SL": 28, "KC": 20, "CH": 18}
        }
    ]
}

Processing Strategy: APPEND with deduplication
- Checks if game_date + pitcher_id already exists before inserting
- Prevents duplicate records on re-processing

Created: 2026-03-06
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import notify_error, notify_info
from shared.config.sport_config import get_raw_dataset

logger = logging.getLogger(__name__)


class MlbStatcastDailyProcessor(ProcessorBase):
    """
    MLB Statcast Daily Pitcher Summary Processor

    Processes per-pitcher Statcast metrics from GCS to BigQuery.
    Primary source for swinging strike rate, whiff rate, and CSW%
    which are the most predictive features for strikeout modeling.

    Processing Strategy: APPEND with deduplication
    - Deletes existing records for the game_date before inserting
    - Prevents duplicate pitcher records on re-processing
    """

    def __init__(self):
        self.dataset_id = get_raw_dataset()  # mlb_raw
        super().__init__()
        self.table_name = 'statcast_pitcher_daily'
        self.processing_strategy = 'APPEND'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        """Load Statcast daily data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def normalize_player_name(self, name: str) -> str:
        """Create normalized player lookup string.

        Handles both 'Last, First' and 'First Last' formats from pybaseball.
        """
        if not name:
            return ""

        # pybaseball returns "Last, First" format — normalize to "First Last"
        if ',' in name:
            parts = name.split(',', 1)
            name = f"{parts[1].strip()} {parts[0].strip()}"

        # Remove spaces, punctuation, convert to lowercase
        normalized = re.sub(r'[^a-z0-9]', '', name.lower())
        return normalized

    def compute_data_hash(self, row: Dict) -> str:
        """Compute a hash of the data fields for deduplication/change detection."""
        # Hash the key metric fields to detect if data has changed
        hash_fields = [
            str(row.get('pitcher_id', '')),
            str(row.get('game_date', '')),
            str(row.get('total_pitches', '')),
            str(row.get('swstr_pct', '')),
            str(row.get('csw_pct', '')),
            str(row.get('whiff_rate', '')),
            str(row.get('avg_velocity', '')),
        ]
        hash_input = '|'.join(hash_fields)
        return hashlib.md5(hash_input.encode()).hexdigest()

    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON structure."""
        errors = []

        if 'pitcher_summaries' not in data:
            errors.append("Missing 'pitcher_summaries' field")
            return errors

        if not isinstance(data['pitcher_summaries'], list):
            errors.append("'pitcher_summaries' is not a list")
            return errors

        if not data['pitcher_summaries']:
            # Empty summaries is valid (no games on that date)
            logger.info("Empty pitcher_summaries array - no Statcast data for this date")

        return errors

    def transform_data(self) -> None:
        """Transform raw Statcast pitcher summaries into BigQuery rows."""
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []
        skipped_count = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        summaries = raw_data.get('pitcher_summaries', [])
        logger.info(f"Processing {len(summaries)} pitcher summaries from {file_path}")

        for summary in summaries:
            try:
                pitcher_id = summary.get('pitcher_id')
                game_date = summary.get('game_date')

                if not pitcher_id:
                    logger.debug("Skipping summary - missing pitcher_id")
                    skipped_count += 1
                    continue

                if not game_date:
                    # Fall back to file-level date
                    game_date = raw_data.get('date')
                    if not game_date:
                        logger.debug("Skipping summary - missing game_date")
                        skipped_count += 1
                        continue

                # Normalize game_date (strip time component if present)
                if 'T' in str(game_date):
                    game_date = str(game_date).split('T')[0]

                # Pitcher name and lookup
                pitcher_name = summary.get('pitcher_name', '')
                player_lookup = self.normalize_player_name(pitcher_name)

                # Serialize pitch_types dict to JSON string
                pitch_types_raw = summary.get('pitch_types', {})
                if isinstance(pitch_types_raw, dict):
                    pitch_types_json = json.dumps(pitch_types_raw) if pitch_types_raw else None
                elif isinstance(pitch_types_raw, str):
                    pitch_types_json = pitch_types_raw
                else:
                    pitch_types_json = None

                row = {
                    # Core identifiers
                    'game_date': game_date,
                    'game_pk': summary.get('game_pk'),
                    'pitcher_id': int(pitcher_id),
                    'pitcher_name': pitcher_name,
                    'player_lookup': player_lookup,

                    # Pitch counts
                    'total_pitches': summary.get('total_pitches'),
                    'swinging_strikes': summary.get('swinging_strikes'),
                    'called_strikes': summary.get('called_strikes'),
                    'fouls': summary.get('fouls'),
                    'balls': summary.get('balls'),
                    'in_play': summary.get('in_play'),

                    # Velocity
                    'avg_velocity': summary.get('avg_velocity'),
                    'max_velocity': summary.get('max_velocity'),
                    'avg_spin_rate': summary.get('avg_spin_rate'),

                    # Rates (most predictive of K outcomes)
                    'swstr_pct': summary.get('swstr_pct'),
                    'csw_pct': summary.get('csw_pct'),
                    'whiff_rate': summary.get('whiff_rate'),
                    'zone_pct': summary.get('zone_pct'),
                    'chase_rate': summary.get('chase_rate'),

                    # Pitch mix (JSON string)
                    'pitch_types': pitch_types_json,

                    # Processing metadata
                    'source_file_path': file_path,
                    'created_at': now_iso,
                    'processed_at': now_iso,
                }

                # Compute data hash for change detection
                row['data_hash'] = self.compute_data_hash(row)

                rows.append(row)

            except Exception as e:
                logger.error(f"Error processing pitcher summary: {e}")
                skipped_count += 1
                continue

        # Log summary stats
        if rows:
            avg_swstr = sum(
                r.get('swstr_pct', 0) or 0 for r in rows
            ) / len(rows)
            avg_pitches = sum(
                r.get('total_pitches', 0) or 0 for r in rows
            ) / len(rows)
            logger.info(
                f"Transformed {len(rows)} pitcher rows, skipped {skipped_count}. "
                f"Avg SwStr%: {avg_swstr:.1f}, Avg pitches: {avg_pitches:.0f}"
            )
        else:
            logger.info(f"No rows transformed, skipped {skipped_count}")

        self.transformed_data = rows

    def save_data(self) -> None:
        """Save transformed data to BigQuery with deduplication."""
        rows = self.transformed_data

        if not rows:
            logger.info("No rows to save")
            self.stats["rows_inserted"] = 0
            return {'rows_processed': 0, 'errors': []}

        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
        errors = []

        try:
            # Get unique game dates for deduplication delete
            game_dates = set(row['game_date'] for row in rows)

            for game_date in game_dates:
                # Get pitcher_ids for this date to scope the delete
                pitcher_ids = [
                    row['pitcher_id'] for row in rows
                    if row['game_date'] == game_date
                ]

                try:
                    # Delete existing records for this date + these pitchers
                    pitcher_ids_str = ', '.join(str(pid) for pid in pitcher_ids)
                    delete_query = f"""
                    DELETE FROM `{table_id}`
                    WHERE game_date = '{game_date}'
                      AND pitcher_id IN ({pitcher_ids_str})
                    """
                    self.bq_client.query(delete_query).result(timeout=60)
                    logger.info(
                        f"Deleted existing records for {game_date} "
                        f"({len(pitcher_ids)} pitchers)"
                    )
                except Exception as e:
                    if 'not found' in str(e).lower():
                        logger.info("Table doesn't exist yet, will be created")
                    elif 'streaming buffer' in str(e).lower():
                        logger.warning(
                            f"Streaming buffer prevents delete for {game_date}"
                        )
                    else:
                        logger.warning(f"Delete failed for {game_date}: {e}")

            # Load data via batch job
            try:
                table = self.bq_client.get_table(table_id)
            except Exception as e:
                if 'not found' in str(e).lower():
                    logger.warning(
                        f"Table {table_id} not found - "
                        f"run statcast_pitcher_daily_tables.sql first"
                    )
                raise

            job_config = bigquery.LoadJobConfig(
                schema=table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
            )

            load_job = self.bq_client.load_table_from_json(
                rows,
                table_id,
                job_config=job_config,
            )
            load_job.result(timeout=120)

            logger.info(
                f"Saved {len(rows)} Statcast pitcher rows "
                f"for {len(game_dates)} date(s) to {table_id}"
            )
            self.stats['rows_inserted'] = len(rows)

            # Summary stats for notification
            total_pitches = sum(r.get('total_pitches', 0) or 0 for r in rows)
            avg_swstr = (
                sum(r.get('swstr_pct', 0) or 0 for r in rows) / len(rows)
                if rows else 0
            )

            try:
                notify_info(
                    title="MLB Statcast Daily Processing Complete",
                    message=(
                        f"Processed {len(rows)} pitcher summaries "
                        f"for {len(game_dates)} date(s)"
                    ),
                    details={
                        'pitcher_records': len(rows),
                        'dates': sorted(game_dates),
                        'total_pitches': total_pitches,
                        'avg_swstr_pct': round(avg_swstr, 1),
                        'table': f"{self.dataset_id}.{self.table_name}",
                        'processor': 'MlbStatcastDailyProcessor',
                    },
                    processor_name=self.__class__.__name__,
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")

        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logger.error(f"Error loading Statcast data: {error_msg}")
            self.stats["rows_inserted"] = 0

            try:
                notify_error(
                    title="MLB Statcast Daily Processing Failed",
                    message=f"Error: {str(e)[:200]}",
                    details={
                        'error': error_msg,
                        'error_type': type(e).__name__,
                        'rows_attempted': len(rows),
                        'processor': 'MlbStatcastDailyProcessor',
                    },
                    processor_name="MlbStatcastDailyProcessor",
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
            'total_runtime': self.stats.get('total_runtime', 0),
        }


# CLI entry point for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description='Process MLB Statcast daily pitcher summaries from GCS'
    )
    parser.add_argument(
        '--bucket', default='nba-scraped-data', help='GCS bucket'
    )
    parser.add_argument(
        '--file-path', required=True, help='Path to JSON file in GCS'
    )
    parser.add_argument(
        '--date', help='Game date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--force', action='store_true', help='Skip deduplication check (for backfills)'
    )

    args = parser.parse_args()

    processor = MlbStatcastDailyProcessor()
    if args.force:
        processor.SKIP_DEDUPLICATION = True
    success = processor.run({
        'bucket': args.bucket,
        'file_path': args.file_path,
        'date': args.date,
    })

    print(f"Processing {'succeeded' if success else 'failed'}")
    print(f"Stats: {processor.get_processor_stats()}")
