#!/usr/bin/env python3
"""
MLB Stats API Pitcher Stats Processor

Processes pitcher stats from the MLB Stats API box scores scraper to BigQuery.
Key field: strikeouts - our target variable for predictions.

GCS Path: mlb-stats-api/box-scores/{date}/{timestamp}.json
Target Table: mlb_raw.mlbapi_pitcher_stats

Data Format (input from mlb_box_scores scraper):
{
    "date": "2025-06-15",
    "timestamp": "2025-06-16T01:23:45Z",
    "games_found": 15,
    "games_final": 15,
    "pitcher_stats": [
        {
            "game_pk": 717501,
            "game_date": "2025-06-15",
            "player_id": 543037,
            "player_name": "Gerrit Cole",
            "team_abbr": "NYY",
            "opponent_abbr": "BOS",
            "home_away": "home",
            "is_starter": true,
            "strikeouts": 8,
            "innings_pitched": "6.2",
            "pitches_thrown": 108,
            "strikes": 72,
            "balls": 36,
            "hits_allowed": 4,
            "walks": 2,
            "earned_runs": 2,
            "runs": 2,
            "home_runs_allowed": 1,
            "batters_faced": 26,
            "win": true,
            "loss": false,
            "save": false
        }
    ],
    "batter_stats": [...]
}

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
    """Convert 'Gerrit Cole' to 'gerrit_cole'.

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
        str(record.get('innings_pitched', '')),
        str(record.get('pitches_thrown', '')),
        str(record.get('hits_allowed', '')),
        str(record.get('walks', '')),
        str(record.get('earned_runs', '')),
    ]
    hash_input = '|'.join(hash_fields)
    return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()


def parse_innings_pitched(ip_str) -> float:
    """Parse innings pitched string (e.g. '6.2') to float.

    MLB encodes partial innings as decimals: 6.1 = 6 1/3, 6.2 = 6 2/3.
    We store as-is (string from API) but parse to float for computed fields.
    """
    if ip_str is None:
        return 0.0
    try:
        return float(ip_str)
    except (ValueError, TypeError):
        return 0.0


class MlbApiPitcherStatsProcessor(ProcessorBase):
    """
    MLB Stats API Pitcher Stats Processor

    Processes pitcher game stats from the MLB Stats API box scores scraper.
    Reads GCS JSON output and writes to mlb_raw.mlbapi_pitcher_stats.

    Processing Strategy: MERGE_UPDATE
    - Deletes existing records for the game_date before inserting
    - Prevents duplicate pitcher records on re-processing
    """

    def __init__(self):
        self.dataset_id = get_raw_dataset()  # 'mlb_raw' when SPORT=mlb
        super().__init__()
        self.table_name = 'mlbapi_pitcher_stats'
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

        if 'pitcher_stats' not in data:
            errors.append("Missing 'pitcher_stats' field")
            return errors

        if not isinstance(data['pitcher_stats'], list):
            errors.append("'pitcher_stats' is not a list")
            return errors

        if not data['pitcher_stats']:
            # Empty stats is valid (no games on that date)
            logger.info("Empty pitcher_stats array - no pitcher data for this date")

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
        """Transform raw pitcher stats into BigQuery rows.

        Reads the 'pitcher_stats' array from the box scores JSON and adds:
        - player_lookup: normalized pitcher name for joins
        - k_per_9: (strikeouts / innings_pitched) * 9
        - pitch_efficiency: strikeouts / pitches_thrown
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

        pitcher_stats = raw_data.get('pitcher_stats', [])
        scrape_date = raw_data.get('date', '')
        logger.info(f"Processing {len(pitcher_stats)} pitcher stat rows from {file_path}")

        now_iso = datetime.now(timezone.utc).isoformat()

        for stat in pitcher_stats:
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

                # Parse innings pitched for computed fields
                ip_raw = stat.get('innings_pitched', '0.0')
                ip_float = parse_innings_pitched(ip_raw)

                # Computed fields
                strikeouts = stat.get('strikeouts', 0) or 0
                pitches_thrown = stat.get('pitches_thrown', 0) or 0

                # K/9: (strikeouts / innings_pitched) * 9
                if ip_float > 0:
                    k_per_9 = round((strikeouts / ip_float) * 9, 2)
                else:
                    k_per_9 = None

                # Pitch efficiency: strikeouts / pitches_thrown
                if pitches_thrown > 0:
                    pitch_efficiency = round(strikeouts / pitches_thrown, 4)
                else:
                    pitch_efficiency = None

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
                    'is_starter': stat.get('is_starter', False),

                    # Pitching stats - core
                    'strikeouts': strikeouts,
                    'innings_pitched': ip_raw,
                    'pitches_thrown': pitches_thrown,
                    'strikes': stat.get('strikes', 0) or 0,
                    'balls': stat.get('balls', 0) or 0,

                    # Pitching stats - extended
                    'hits_allowed': stat.get('hits_allowed', 0) or 0,
                    'walks': stat.get('walks', 0) or 0,
                    'earned_runs': stat.get('earned_runs', 0) or 0,
                    'runs': stat.get('runs', 0) or 0,
                    'home_runs_allowed': stat.get('home_runs_allowed', 0) or 0,
                    'batters_faced': stat.get('batters_faced', 0) or 0,

                    # Game result
                    'win': stat.get('win', False) or False,
                    'loss': stat.get('loss', False) or False,
                    'save': stat.get('save', False) or False,

                    # Computed fields
                    'k_per_9': k_per_9,
                    'pitch_efficiency': pitch_efficiency,

                    # Processing metadata
                    'source_file_path': file_path,
                    'data_hash': compute_data_hash(stat),
                    'created_at': now_iso,
                    'processed_at': now_iso,
                }

                rows.append(row)

            except Exception as e:
                logger.error(f"Error processing pitcher stat row: {e}")
                skipped_count += 1
                continue

        # Log summary
        total_ks = sum(r.get('strikeouts', 0) or 0 for r in rows)
        avg_ks = total_ks / len(rows) if rows else 0

        logger.info(f"Transformed {len(rows)} rows, skipped {skipped_count}")
        logger.info(f"Total strikeouts: {total_ks}, Avg: {avg_ks:.2f}")
        self.transformed_data = rows

    def save_data(self) -> None:
        """Save transformed data to BigQuery using MERGE_UPDATE strategy.

        Deletes existing records for the game_date, then batch inserts.
        """
        rows = self.transformed_data

        if not rows:
            logger.info("No rows to save")
            self.stats['rows_inserted'] = 0
            return

        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"

        try:
            # Get unique game dates for delete (MERGE_UPDATE)
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
            avg_ks = total_ks / len(rows) if rows else 0

            try:
                notify_info(
                    title="MLB API Pitcher Stats Processing Complete",
                    message=f"Processed {len(rows)} pitcher stats from {len(game_pks)} games",
                    details={
                        'pitcher_records': len(rows),
                        'games_processed': len(game_pks),
                        'total_strikeouts': total_ks,
                        'avg_strikeouts': round(avg_ks, 2),
                        'table': f"{self.dataset_id}.{self.table_name}",
                        'processor': 'MlbApiPitcherStatsProcessor',
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
                    title="MLB API Pitcher Stats Processing Failed",
                    message=f"Error during processing: {str(e)[:200]}",
                    details={
                        'error': error_msg,
                        'error_type': type(e).__name__,
                        'rows_attempted': len(rows),
                        'processor': 'MlbApiPitcherStatsProcessor',
                    },
                    processor_name="MlbApiPitcherStatsProcessor",
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
        description='Process MLB Stats API pitcher stats from GCS'
    )
    parser.add_argument('--bucket', default='mlb-scraped-data', help='GCS bucket')
    parser.add_argument('--file-path', required=True, help='Path to JSON file in GCS')
    parser.add_argument('--date', help='Game date (YYYY-MM-DD)')

    args = parser.parse_args()

    processor = MlbApiPitcherStatsProcessor()
    success = processor.run({
        'bucket': args.bucket,
        'file_path': args.file_path,
        'date': args.date,
    })

    print(f"Processing {'succeeded' if success else 'failed'}")
    print(f"Stats: {processor.get_processor_stats()}")
