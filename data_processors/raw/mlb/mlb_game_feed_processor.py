#!/usr/bin/env python3
"""
MLB Game Feed Per-Pitch Processor

Processes output from mlb_game_feed_daily scraper to BigQuery.
Emits one row per pitch with full physics + result classification.

GCS Path: mlb-stats-api/game-feed-daily/{date}/{timestamp}.json
Target Table: mlb_raw.mlb_game_feed_pitches

Processing Strategy: APPEND with deduplication by (game_pk, at_bat_index, pitch_number).
- Scopes DELETE to the game_pks present in the input file
- Prevents duplicate pitches on re-processing

Created: 2026-04-13 (Session 530)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List

from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import notify_error, notify_info
from shared.config.sport_config import get_raw_dataset

logger = logging.getLogger(__name__)


class MlbGameFeedPitchesProcessor(ProcessorBase):
    """
    Processes per-pitch rows from MLB Stats API game feed into BigQuery.

    Dedup key: (game_pk, at_bat_index, pitch_number).
    """

    def __init__(self):
        self.dataset_id = get_raw_dataset()  # mlb_raw
        super().__init__()
        self.table_name = 'mlb_game_feed_pitches'
        self.processing_strategy = 'APPEND'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        self.raw_data = self.load_json_from_gcs()

    def validate_data(self, data: Dict) -> List[str]:
        errors = []
        if 'pitches' not in data:
            errors.append("Missing 'pitches' field")
            return errors
        if not isinstance(data['pitches'], list):
            errors.append("'pitches' is not a list")
            return errors
        if not data['pitches']:
            logger.info("Empty pitches array — no games on this date")
        return errors

    def transform_data(self) -> None:
        raw = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        pitches = raw.get('pitches', [])
        now_iso = datetime.now(timezone.utc).isoformat()
        logger.info(f"Processing {len(pitches)} pitches from {file_path}")

        rows = []
        skipped = 0
        for p in pitches:
            try:
                game_pk = p.get('game_pk')
                pitcher_id = p.get('pitcher_id')
                at_bat_index = p.get('at_bat_index')
                pitch_number = p.get('pitch_number')

                if game_pk is None or pitcher_id is None or at_bat_index is None or pitch_number is None:
                    skipped += 1
                    continue

                row = {
                    'game_date': p.get('game_date'),
                    'game_pk': int(game_pk),
                    'pitcher_id': int(pitcher_id),
                    'pitcher_name': p.get('pitcher_name'),
                    'pitcher_lookup': p.get('pitcher_lookup'),
                    'batter_id': int(p['batter_id']) if p.get('batter_id') is not None else None,
                    'batter_name': p.get('batter_name'),
                    'batter_side': p.get('batter_side'),
                    'pitch_type_code': p.get('pitch_type_code'),
                    'pitch_type_desc': p.get('pitch_type_desc'),
                    'velocity': p.get('velocity'),
                    'spin_rate': p.get('spin_rate'),
                    'extension': p.get('extension'),
                    'zone': p.get('zone'),
                    'result_description': p.get('result_description'),
                    'is_swinging_strike': p.get('is_swinging_strike'),
                    'is_called_strike': p.get('is_called_strike'),
                    'is_foul': p.get('is_foul'),
                    'is_ball': p.get('is_ball'),
                    'is_in_play': p.get('is_in_play'),
                    'is_swing': p.get('is_swing'),
                    'is_in_zone': p.get('is_in_zone'),
                    'is_chase': p.get('is_chase'),
                    'is_whiff': p.get('is_whiff'),
                    'count_balls': p.get('count_balls'),
                    'count_strikes': p.get('count_strikes'),
                    'inning': p.get('inning'),
                    'half_inning': p.get('half_inning'),
                    'at_bat_index': int(at_bat_index),
                    'pitch_number': int(pitch_number),
                    'at_bat_event': p.get('at_bat_event'),
                    'is_at_bat_end': p.get('is_at_bat_end'),
                    'source_file_path': file_path,
                    'processed_at': now_iso,
                }
                # BigQuery rejects explicit None on some INT fields even when NULLABLE
                row = {k: v for k, v in row.items() if v is not None}
                rows.append(row)
            except Exception as exc:
                logger.error(f"Error transforming pitch row: {exc}")
                skipped += 1

        logger.info(f"Transformed {len(rows)} rows, skipped {skipped}")
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
            # Dedup: scope DELETE to (game_date, game_pk) — small partition, fast.
            # Cross-product of dates × game_pks in input.
            date_pk_pairs = set()
            for r in rows:
                date_pk_pairs.add((r['game_date'], r['game_pk']))

            dates = sorted({d for d, _ in date_pk_pairs})
            pks = sorted({pk for _, pk in date_pk_pairs})

            try:
                date_list = ", ".join(f"'{d}'" for d in dates)
                pk_list = ", ".join(str(pk) for pk in pks)
                delete_query = f"""
                DELETE FROM `{table_id}`
                WHERE game_date IN ({date_list})
                  AND game_pk IN ({pk_list})
                """
                self.bq_client.query(delete_query).result(timeout=60)
                logger.info(f"Deleted existing rows for {len(pks)} game_pks across {len(dates)} date(s)")
            except Exception as exc:
                msg = str(exc).lower()
                if 'not found' in msg:
                    logger.info("Table doesn't exist yet, will be created on load")
                elif 'streaming buffer' in msg:
                    logger.warning(f"Streaming buffer prevents delete; proceeding (may duplicate)")
                else:
                    logger.warning(f"Delete failed: {exc}")

            # Load via batch job
            try:
                table = self.bq_client.get_table(table_id)
                schema = table.schema
            except Exception as exc:
                if 'not found' in str(exc).lower():
                    raise RuntimeError(
                        f"Table {table_id} not found — "
                        f"run mlb_game_feed_pitches_tables.sql first"
                    )
                raise

            job_config = bigquery.LoadJobConfig(
                schema=schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
            )
            load_job = self.bq_client.load_table_from_json(rows, table_id, job_config=job_config)
            load_job.result(timeout=180)

            logger.info(f"Saved {len(rows)} pitch rows to {table_id}")
            self.stats['rows_inserted'] = len(rows)

            try:
                notify_info(
                    title="MLB Game Feed Pitches Processing Complete",
                    message=f"Processed {len(rows)} pitches across {len(pks)} game(s)",
                    details={
                        'pitch_rows': len(rows),
                        'games': len(pks),
                        'dates': dates,
                        'table': f"{self.dataset_id}.{self.table_name}",
                        'processor': 'MlbGameFeedPitchesProcessor',
                    },
                    processor_name=self.__class__.__name__,
                )
            except Exception as exc:
                logger.warning(f"Failed to send notification: {exc}")

        except Exception as exc:
            error_msg = str(exc)
            errors.append(error_msg)
            logger.error(f"Error loading pitch data: {error_msg}")
            self.stats['rows_inserted'] = 0
            try:
                notify_error(
                    title="MLB Game Feed Pitches Processing Failed",
                    message=f"Error: {str(exc)[:200]}",
                    details={
                        'error': error_msg,
                        'error_type': type(exc).__name__,
                        'rows_attempted': len(rows),
                        'processor': 'MlbGameFeedPitchesProcessor',
                    },
                    processor_name="MlbGameFeedPitchesProcessor",
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

        return {'rows_processed': len(rows), 'errors': errors}

    def get_processor_stats(self) -> Dict:
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'rows_failed': self.stats.get('rows_failed', 0),
            'run_id': self.stats.get('run_id'),
            'total_runtime': self.stats.get('total_runtime', 0),
        }


# CLI entry point
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Process MLB game feed per-pitch data from GCS')
    parser.add_argument('--bucket', default='nba-scraped-data', help='GCS bucket')
    parser.add_argument('--file-path', required=True, help='Path to JSON file in GCS')
    parser.add_argument('--date', help='Game date (YYYY-MM-DD)')
    parser.add_argument('--force', action='store_true', help='Skip dedup check (for backfills)')

    args = parser.parse_args()

    processor = MlbGameFeedPitchesProcessor()
    if args.force:
        processor.SKIP_DEDUPLICATION = True
    success = processor.run({
        'bucket': args.bucket,
        'file_path': args.file_path,
        'date': args.date,
    })

    print(f"Processing {'succeeded' if success else 'failed'}")
    print(f"Stats: {processor.get_processor_stats()}")
