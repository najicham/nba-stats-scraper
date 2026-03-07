#!/usr/bin/env python3
"""
MLB Stats API Batter Stats Processor

Processes batter stats from the MLB Stats API box scores scraper to BigQuery.
Key field: strikeouts - critical for bottom-up strikeout prediction model.

GCS Path: mlb-stats-api/box-scores/{date}/{timestamp}.json
Target Table: mlb_raw.mlbapi_batter_stats

Data Format (input from mlb_box_scores scraper):
{
    "date": "2025-06-15",
    "timestamp": "2025-06-16T01:23:45Z",
    "games_found": 15,
    "games_final": 15,
    "pitcher_stats": [...],
    "batter_stats": [
        {
            "game_pk": 717501,
            "game_date": "2025-06-15",
            "player_id": 592450,
            "player_name": "Aaron Judge",
            "team_abbr": "NYY",
            "opponent_abbr": "BOS",
            "home_away": "home",
            "batting_order": 2,
            "strikeouts": 2,
            "at_bats": 4,
            "hits": 1,
            "walks": 0,
            "home_runs": 0,
            "rbis": 0,
            "runs": 1
        }
    ]
}

Bottom-Up Model:
    Pitcher K's ~ Sum of individual batter K probabilities
    If batter K lines don't sum to pitcher K line -> market inefficiency

Created: 2026-03-06
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List

from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import notify_error, notify_info
from shared.config.sport_config import get_raw_dataset

logger = logging.getLogger(__name__)


def normalize_name(name: str) -> str:
    """Convert 'Aaron Judge' to 'aaron_judge'.

    Follows the NBA player_lookup normalization pattern:
    - Lowercase
    - Remove suffixes (Jr., Sr., III, II, IV)
    - Replace non-alphanumeric chars with underscores
    - Collapse multiple underscores
    """
    if not name:
        return ''
    # Remove suffixes like Jr., Sr., III
    name = re.sub(r'\s+(Jr\.|Sr\.|III|II|IV)$', '', name.strip())
    # Replace spaces and special chars with underscores
    name = re.sub(r'[^a-zA-Z0-9]', '_', name.lower())
    # Collapse multiple underscores
    name = re.sub(r'_+', '_', name).strip('_')
    return name


def compute_data_hash(record: Dict) -> str:
    """Compute a SHA-256 hash of the record for deduplication.

    Uses the core stat fields (not metadata) to detect true duplicates.
    """
    hash_fields = [
        str(record.get('game_pk', '')),
        str(record.get('player_id', '')),
        str(record.get('strikeouts', '')),
        str(record.get('at_bats', '')),
        str(record.get('hits', '')),
        str(record.get('walks', '')),
        str(record.get('home_runs', '')),
        str(record.get('rbis', '')),
    ]
    hash_input = '|'.join(hash_fields)
    return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()


class MlbApiBatterStatsProcessor(ProcessorBase):
    """
    MLB Stats API Batter Stats Processor

    Processes batter game stats from the MLB Stats API box scores scraper.
    Reads GCS JSON output and writes to mlb_raw.mlbapi_batter_stats.
    Critical source for bottom-up strikeout prediction model.

    Processing Strategy: MERGE_UPDATE
    - Deletes existing records for the game_date before inserting
    - Prevents duplicate batter records on re-processing
    """

    def __init__(self):
        self.dataset_id = get_raw_dataset()  # 'mlb_raw' when SPORT=mlb
        super().__init__()
        self.table_name = 'mlbapi_batter_stats'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        """Load box scores data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON structure from the box scores scraper."""
        errors = []

        if not data:
            errors.append("Empty data")
            return errors

        if 'batter_stats' not in data:
            errors.append("Missing 'batter_stats' field")
            return errors

        if not isinstance(data['batter_stats'], list):
            errors.append("'batter_stats' is not a list")
            return errors

        if not data['batter_stats']:
            # Empty stats is valid (no games on that date)
            logger.info("Empty batter_stats array - no batter data for this date")

        return errors

    def extract_season_year(self, game_date: str) -> int:
        """Extract season year from date string."""
        if not game_date:
            return 0
        if 'T' in game_date:
            game_date = game_date.split('T')[0]
        try:
            return datetime.strptime(game_date, '%Y-%m-%d').year
        except ValueError:
            return 0

    def transform_data(self) -> None:
        """Transform raw batter stats into BigQuery rows.

        Reads the 'batter_stats' array from the box scores JSON and adds:
        - player_lookup: normalized batter name for joins
        - k_rate: strikeouts / at_bats (handles division by zero)
        - data_hash: SHA-256 hash for deduplication
        - source_file_path, created_at, processed_at: metadata
        """
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []
        skipped_count = 0

        errors = self.validate_data(raw_data)
        if errors:
            logger.warning(f"Validation issues for {file_path}: {errors}")
            self.transformed_data = rows
            return

        batter_stats = raw_data.get('batter_stats', [])
        scrape_date = raw_data.get('date', '')
        logger.info(f"Processing {len(batter_stats)} batter stat rows from {file_path}")

        now_iso = datetime.now(timezone.utc).isoformat()

        for stat in batter_stats:
            try:
                player_name = stat.get('player_name', '')
                if not player_name:
                    logger.debug("Skipping stat - missing player_name")
                    skipped_count += 1
                    continue

                game_date = stat.get('game_date', scrape_date)
                game_pk = stat.get('game_pk')

                if not game_pk:
                    logger.debug("Skipping stat - missing game_pk")
                    skipped_count += 1
                    continue

                # Core stats
                strikeouts = stat.get('strikeouts', 0) or 0
                at_bats = stat.get('at_bats', 0) or 0

                # Computed field: K rate (strikeouts / at_bats)
                if at_bats > 0:
                    k_rate = round(strikeouts / at_bats, 4)
                else:
                    k_rate = None

                row = {
                    # Core identifiers
                    'game_pk': game_pk,
                    'game_date': game_date,
                    'season_year': self.extract_season_year(game_date),

                    # Player identification
                    'player_id': stat.get('player_id'),
                    'player_name': player_name,
                    'player_lookup': normalize_name(player_name),
                    'team_abbr': stat.get('team_abbr', ''),
                    'opponent_abbr': stat.get('opponent_abbr', ''),
                    'home_away': stat.get('home_away', ''),
                    'batting_order': stat.get('batting_order', 0) or 0,

                    # Batting stats - core (for bottom-up model)
                    'strikeouts': strikeouts,
                    'at_bats': at_bats,
                    'hits': stat.get('hits', 0) or 0,
                    'walks': stat.get('walks', 0) or 0,

                    # Batting stats - extended
                    'home_runs': stat.get('home_runs', 0) or 0,
                    'rbis': stat.get('rbis', 0) or 0,
                    'runs': stat.get('runs', 0) or 0,

                    # Computed fields
                    'k_rate': k_rate,

                    # Processing metadata
                    'source_file_path': file_path,
                    'data_hash': compute_data_hash(stat),
                    'created_at': now_iso,
                    'processed_at': now_iso,
                }

                rows.append(row)

            except Exception as e:
                logger.error(f"Error processing batter stat row: {e}")
                skipped_count += 1
                continue

        # Log summary for bottom-up model validation
        total_ks = sum(r.get('strikeouts', 0) or 0 for r in rows)
        total_abs = sum(r.get('at_bats', 0) or 0 for r in rows)
        k_rate = total_ks / total_abs if total_abs > 0 else 0

        logger.info(f"Transformed {len(rows)} rows, skipped {skipped_count}")
        logger.info(f"Total strikeouts: {total_ks}, Total ABs: {total_abs}, K rate: {k_rate:.3f}")
        self.transformed_data = rows

    def save_data(self) -> None:
        """Save transformed data to BigQuery using MERGE_UPDATE strategy.

        Deletes existing records for the game_pk, then batch inserts.
        """
        rows = self.transformed_data

        if not rows:
            logger.info("No rows to save")
            self.stats['rows_inserted'] = 0
            return

        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"

        try:
            # Get unique game PKs for delete (MERGE_UPDATE)
            game_dates = set(row['game_date'] for row in rows if row.get('game_date'))
            game_pks = set(row['game_pk'] for row in rows if row.get('game_pk'))
            logger.info(
                f"Loading {len(rows)} rows for {len(game_pks)} games "
                f"({len(game_dates)} dates) using batch load"
            )

            # Delete existing data for these game_pks (MERGE_UPDATE strategy)
            for game_pk in game_pks:
                game_date = next(
                    (row['game_date'] for row in rows if row['game_pk'] == game_pk),
                    None
                )
                if game_date is None:
                    logger.warning(f"game_pk {game_pk} not found in rows, skipping delete")
                    continue
                try:
                    delete_query = f"""
                    DELETE FROM `{table_id}`
                    WHERE game_pk = {game_pk}
                      AND game_date = '{game_date}'
                    """
                    self.bq_client.query(delete_query).result(timeout=60)
                except Exception as e:
                    if 'streaming buffer' in str(e).lower():
                        logger.warning(f"Streaming buffer prevents delete for {game_pk}")
                    elif 'not found' in str(e).lower():
                        logger.info("Table doesn't exist yet, will create on first insert")
                    else:
                        raise

            # Get table schema for load job
            try:
                table = self.bq_client.get_table(table_id)
            except Exception as e:
                if 'not found' in str(e).lower():
                    logger.warning(f"Table {table_id} not found - run schema SQL first")
                    raise
                raise

            # Configure batch load job
            job_config = bigquery.LoadJobConfig(
                schema=table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
            )

            # Load using batch job
            load_job = self.bq_client.load_table_from_json(
                rows,
                table_id,
                job_config=job_config,
            )
            load_job.result(timeout=60)

            if load_job.errors:
                logger.error(f"BigQuery load had errors: {load_job.errors[:3]}")
                return

            self.stats['rows_inserted'] = len(rows)
            logger.info(
                f"Successfully loaded {len(rows)} rows for "
                f"{len(game_pks)} games to {table_id}"
            )

            # Summary for notification
            total_ks = sum(r.get('strikeouts', 0) or 0 for r in rows)
            total_abs = sum(r.get('at_bats', 0) or 0 for r in rows)
            k_rate = total_ks / total_abs if total_abs > 0 else 0

            try:
                notify_info(
                    title="MLB API Batter Stats Processing Complete",
                    message=f"Processed {len(rows)} batter stats from {len(game_pks)} games",
                    details={
                        'batter_records': len(rows),
                        'games_processed': len(game_pks),
                        'total_strikeouts': total_ks,
                        'total_at_bats': total_abs,
                        'k_rate': round(k_rate, 3),
                        'table': f"{self.dataset_id}.{self.table_name}",
                        'processor': 'MlbApiBatterStatsProcessor',
                    },
                    processor_name=self.__class__.__name__,
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error loading data: {error_msg}")
            self.stats['rows_inserted'] = 0

            try:
                notify_error(
                    title="MLB API Batter Stats Processing Failed",
                    message=f"Error during processing: {str(e)[:200]}",
                    details={
                        'error': error_msg,
                        'error_type': type(e).__name__,
                        'rows_attempted': len(rows),
                        'processor': 'MlbApiBatterStatsProcessor',
                    },
                    processor_name="MlbApiBatterStatsProcessor",
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            raise

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
        description='Process MLB Stats API batter stats from GCS'
    )
    parser.add_argument('--bucket', default='mlb-scraped-data', help='GCS bucket')
    parser.add_argument('--file-path', required=True, help='Path to JSON file in GCS')
    parser.add_argument('--date', help='Game date (YYYY-MM-DD)')

    args = parser.parse_args()

    processor = MlbApiBatterStatsProcessor()
    success = processor.run({
        'bucket': args.bucket,
        'file_path': args.file_path,
        'date': args.date,
    })

    print(f"Processing {'succeeded' if success else 'failed'}")
    print(f"Stats: {processor.get_processor_stats()}")
