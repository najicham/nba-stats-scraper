#!/usr/bin/env python3
"""
Load BettingPros Historical Props from GCS to BigQuery

Processes all GCS files from the BettingPros backfill and loads them to BigQuery.
Supports resume capability via source_file_path checking.

Usage:
    # Load all pitcher props
    python scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py --prop-type pitcher

    # Load all batter props
    python scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py --prop-type batter

    # Load specific market
    python scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py --market pitcher-strikeouts

    # Dry run
    python scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py --prop-type pitcher --dry-run

Created: 2026-01-15
"""

import argparse
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

from google.cloud import bigquery, storage

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shared.utils.player_name_normalizer import normalize_name_for_lookup

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = 'nba-props-platform'
BUCKET_NAME = 'nba-scraped-data'
GCS_PREFIX = 'bettingpros-mlb/historical'
DATASET_ID = 'mlb_raw'

# Market definitions
PITCHER_MARKETS = ['pitcher-strikeouts', 'pitcher-earned-runs-allowed']
BATTER_MARKETS = [
    'batter-hits', 'batter-runs', 'batter-rbis', 'batter-doubles',
    'batter-triples', 'batter-total-bases', 'batter-stolen-bases',
    'batter-singles', 'batter-home-runs'
]


@dataclass
class LoadStats:
    """Track loading statistics."""
    files_processed: int = 0
    files_skipped: int = 0
    rows_loaded: int = 0
    errors: int = 0
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def elapsed_str(self) -> str:
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        hours, remainder = divmod(int(elapsed), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"


class BettingProsLoader:
    """Load BettingPros historical props from GCS to BigQuery."""

    def __init__(
        self,
        prop_type: str = 'pitcher',
        markets: Optional[List[str]] = None,
        batch_size: int = 1000,
        workers: int = 4,
        dry_run: bool = False,
    ):
        self.prop_type = prop_type
        self.batch_size = batch_size
        self.workers = workers
        self.dry_run = dry_run
        self.stats = LoadStats()

        # Set target table
        if prop_type == 'pitcher':
            self.table_name = 'bp_pitcher_props'
            self.markets = markets or PITCHER_MARKETS
        else:
            self.table_name = 'bp_batter_props'
            self.markets = markets or BATTER_MARKETS

        # Initialize clients
        self.storage_client = storage.Client(project=PROJECT_ID)
        self.bucket = self.storage_client.bucket(BUCKET_NAME)
        self.bq_client = bigquery.Client(project=PROJECT_ID)
        self.table_id = f"{PROJECT_ID}.{DATASET_ID}.{self.table_name}"

        # Track processed files for resume
        self.processed_files: Set[str] = set()

    def get_processed_files(self) -> Set[str]:
        """Get set of already processed file paths from BigQuery."""
        if self.dry_run:
            return set()

        query = f"""
        SELECT DISTINCT source_file_path
        FROM `{self.table_id}`
        """

        try:
            logger.info("Querying BigQuery for already processed files...")
            query_job = self.bq_client.query(query)
            results = query_job.result(timeout=120)
            processed = {row.source_file_path for row in results}
            logger.info(f"Found {len(processed)} already processed files")
            return processed
        except Exception as e:
            logger.warning(f"Could not query processed files: {e}")
            return set()

    def list_gcs_files(self) -> List[str]:
        """List all GCS files for the configured markets."""
        all_files = []

        for market in self.markets:
            prefix = f"{GCS_PREFIX}/{market}/"
            logger.info(f"Listing files for {market}...")

            try:
                blobs = self.bucket.list_blobs(prefix=prefix)
                market_files = [
                    blob.name for blob in blobs
                    if blob.name.endswith('props.json')
                ]
                all_files.extend(market_files)
                logger.info(f"  Found {len(market_files)} files for {market}")
            except Exception as e:
                logger.error(f"Error listing files for {market}: {e}")

        return sorted(all_files)

    def download_and_transform(self, file_path: str) -> List[Dict]:
        """Download a GCS file and transform to BigQuery rows."""
        try:
            blob = self.bucket.blob(file_path)
            content = blob.download_as_string()
            data = json.loads(content)

            meta = data.get('meta', {})
            game_date = meta.get('date')
            market_id = meta.get('market_id')
            market_name = meta.get('market_name', '')
            scraped_at = meta.get('scraped_at')

            processed_at = datetime.now(timezone.utc).isoformat()
            rows = []

            for prop in data.get('props', []):
                player_name = prop.get('player_name', '')
                player_lookup = normalize_name_for_lookup(player_name) if player_name else None

                if not player_lookup:
                    continue

                row = {
                    'game_date': game_date,
                    'market_id': market_id,
                    'market_name': market_name,
                    'event_id': prop.get('event_id'),
                    'player_id': str(prop.get('player_id')) if prop.get('player_id') else None,
                    'player_name': player_name,
                    'player_lookup': player_lookup,
                    'team': prop.get('team'),
                    'position': prop.get('position'),
                    'over_line': prop.get('over_line'),
                    'over_odds': prop.get('over_odds'),
                    'over_book_id': prop.get('over_book_id'),
                    'over_consensus_line': prop.get('over_consensus_line'),
                    'under_line': prop.get('under_line'),
                    'under_odds': prop.get('under_odds'),
                    'under_book_id': prop.get('under_book_id'),
                    'under_consensus_line': prop.get('under_consensus_line'),
                    'projection_value': prop.get('projection_value'),
                    'projection_side': prop.get('projection_side'),
                    'projection_ev': prop.get('projection_ev'),
                    'projection_rating': prop.get('projection_rating'),
                    'actual_value': prop.get('actual_value'),
                    'is_scored': prop.get('is_scored'),
                    'is_push': prop.get('is_push'),
                    'perf_last_5_over': prop.get('perf_last_5_over'),
                    'perf_last_5_under': prop.get('perf_last_5_under'),
                    'perf_last_10_over': prop.get('perf_last_10_over'),
                    'perf_last_10_under': prop.get('perf_last_10_under'),
                    'perf_season_over': prop.get('perf_season_over'),
                    'perf_season_under': prop.get('perf_season_under'),
                    'opposing_pitcher': prop.get('opposing_pitcher'),
                    'opposition_rank': prop.get('opposition_rank'),
                    'source_file_path': file_path,
                    'scraped_at': scraped_at,
                    'processed_at': processed_at,
                }
                rows.append(row)

            return rows

        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            return []

    def load_batch_to_bigquery(self, rows: List[Dict]) -> int:
        """Load a batch of rows to BigQuery."""
        if not rows or self.dry_run:
            return len(rows) if self.dry_run else 0

        try:
            target_table = self.bq_client.get_table(self.table_id)

            job_config = bigquery.LoadJobConfig(
                schema=target_table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(
                rows,
                self.table_id,
                job_config=job_config
            )
            load_job.result(timeout=120)

            if load_job.errors:
                logger.warning(f"Load had errors: {load_job.errors[:2]}")
                return 0

            return len(rows)

        except Exception as e:
            logger.error(f"Batch load failed: {e}")
            return 0

    def run(self):
        """Run the loader."""
        print("=" * 70)
        print("BETTINGPROS HISTORICAL PROPS LOADER")
        print("=" * 70)
        print(f"\nConfiguration:")
        print(f"  Prop type: {self.prop_type}")
        print(f"  Markets: {len(self.markets)}")
        print(f"  Table: {self.table_id}")
        print(f"  Batch size: {self.batch_size}")
        print(f"  Workers: {self.workers}")
        print(f"  Dry run: {self.dry_run}")
        print()

        # Get already processed files
        self.processed_files = self.get_processed_files()

        # List all GCS files
        all_files = self.list_gcs_files()
        logger.info(f"\nTotal GCS files: {len(all_files)}")

        # Filter out already processed
        files_to_process = [
            f for f in all_files
            if f not in self.processed_files
        ]
        logger.info(f"Files to process: {len(files_to_process)}")
        logger.info(f"Files already processed: {len(all_files) - len(files_to_process)}")

        if not files_to_process:
            print("\nNo new files to process!")
            return

        print(f"\nProcessing {len(files_to_process)} files...")

        # Process files in parallel, batch load
        all_rows = []
        processed_count = 0

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self.download_and_transform, f): f
                for f in files_to_process
            }

            for future in as_completed(futures):
                file_path = futures[future]
                processed_count += 1

                try:
                    rows = future.result()
                    all_rows.extend(rows)
                    self.stats.files_processed += 1

                    # Batch load when we have enough rows
                    if len(all_rows) >= self.batch_size:
                        loaded = self.load_batch_to_bigquery(all_rows)
                        self.stats.rows_loaded += loaded
                        all_rows = []

                        # Progress update
                        if processed_count % 100 == 0:
                            logger.info(
                                f"Progress: {processed_count}/{len(files_to_process)} files | "
                                f"{self.stats.rows_loaded} rows loaded | "
                                f"{self.stats.elapsed_str()}"
                            )

                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
                    self.stats.errors += 1

        # Load remaining rows
        if all_rows:
            loaded = self.load_batch_to_bigquery(all_rows)
            self.stats.rows_loaded += loaded

        # Summary
        print("\n" + "=" * 70)
        print("LOADING COMPLETE")
        print("=" * 70)
        print(f"  Total time: {self.stats.elapsed_str()}")
        print(f"  Files processed: {self.stats.files_processed}")
        print(f"  Files skipped: {len(self.processed_files)}")
        print(f"  Rows loaded: {self.stats.rows_loaded}")
        print(f"  Errors: {self.stats.errors}")


def main():
    parser = argparse.ArgumentParser(
        description='Load BettingPros historical props to BigQuery'
    )
    parser.add_argument(
        '--prop-type',
        choices=['pitcher', 'batter'],
        default='pitcher',
        help='Type of props to load'
    )
    parser.add_argument(
        '--market',
        help='Specific market to load (e.g., pitcher-strikeouts)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Rows per BigQuery batch (default: 1000)'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=4,
        help='Parallel workers for GCS downloads (default: 4)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be processed without loading'
    )

    args = parser.parse_args()

    # Handle specific market
    markets = None
    if args.market:
        markets = [args.market]
        # Determine prop type from market
        if args.market in PITCHER_MARKETS:
            args.prop_type = 'pitcher'
        else:
            args.prop_type = 'batter'

    loader = BettingProsLoader(
        prop_type=args.prop_type,
        markets=markets,
        batch_size=args.batch_size,
        workers=args.workers,
        dry_run=args.dry_run,
    )

    try:
        loader.run()
    except KeyboardInterrupt:
        print("\n\nLoading interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Loading failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
