#!/usr/bin/env python3
"""
MLB Historical BATTER Props Batch Loader

Loads historical batter props from GCS to BigQuery.
Adapted from pitcher props batch loader.

Markets loaded:
- batter_strikeouts (CRITICAL for bottom-up K model)
- batter_hits
- batter_walks
- batter_total_bases
- batter_home_runs
- batter_rbis

Usage:
    # Process all available dates
    python scripts/mlb/historical_odds_backfill/batch_load_batter_props_to_bigquery.py

    # Process specific date range
    python scripts/mlb/historical_odds_backfill/batch_load_batter_props_to_bigquery.py \
        --start-date 2024-06-01 --end-date 2024-06-30

    # Dry-run to see what would be processed
    python scripts/mlb/historical_odds_backfill/batch_load_batter_props_to_bigquery.py --dry-run
"""

import argparse
import io
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from google.cloud import storage, bigquery

# Import transform helpers from processor
from shared.utils.player_name_normalizer import normalize_name_for_lookup

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration - BATTER PROPS
PROJECT_ID = 'nba-props-platform'
BUCKET_NAME = 'nba-scraped-data'
GCS_PREFIX = 'mlb-odds-api/batter-props-history'  # Changed from pitcher
TABLE_ID = f'{PROJECT_ID}.mlb_raw.oddsa_batter_props'  # Changed from pitcher
BATCH_SIZE = 1000  # Rows per BigQuery batch insert

# Team mappings (from processor)
MLB_TEAM_MAP = {
    'arizona diamondbacks': 'ARI', 'atlanta braves': 'ATL', 'baltimore orioles': 'BAL',
    'boston red sox': 'BOS', 'chicago cubs': 'CHC', 'chicago white sox': 'CHW',
    'cincinnati reds': 'CIN', 'cleveland guardians': 'CLE', 'colorado rockies': 'COL',
    'detroit tigers': 'DET', 'houston astros': 'HOU', 'kansas city royals': 'KC',
    'los angeles angels': 'LAA', 'los angeles dodgers': 'LAD', 'miami marlins': 'MIA',
    'milwaukee brewers': 'MIL', 'minnesota twins': 'MIN', 'new york mets': 'NYM',
    'new york yankees': 'NYY', 'oakland athletics': 'OAK', 'philadelphia phillies': 'PHI',
    'pittsburgh pirates': 'PIT', 'san diego padres': 'SD', 'san francisco giants': 'SF',
    'seattle mariners': 'SEA', 'st. louis cardinals': 'STL', 'st louis cardinals': 'STL',
    'tampa bay rays': 'TB', 'texas rangers': 'TEX', 'toronto blue jays': 'TOR',
    'washington nationals': 'WSH',
}


def get_team_abbr(team_name: str) -> str:
    """Get MLB team abbreviation from full name."""
    if not team_name:
        return ''
    team_lower = team_name.lower().strip()
    if team_lower in MLB_TEAM_MAP:
        return MLB_TEAM_MAP[team_lower]
    # Try partial match
    for full_name, abbr in MLB_TEAM_MAP.items():
        if full_name in team_lower or team_lower in full_name:
            return abbr
    return team_name[:3].upper() if team_name else ''


def decimal_to_american(decimal_odds: float) -> Optional[int]:
    """Convert decimal odds to American odds."""
    if decimal_odds is None:
        return None
    try:
        decimal_odds = float(decimal_odds)
    except (ValueError, TypeError):
        return None
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1) * 100))
    elif decimal_odds > 1.0:
        return int(round(-100 / (decimal_odds - 1)))
    return None


def normalize_odds(price) -> Optional[int]:
    """Normalize odds to American format."""
    if price is None:
        return None
    try:
        price = float(price)
    except (ValueError, TypeError):
        return None
    if 1.01 <= price <= 15.0:
        return decimal_to_american(price)
    return int(round(price))


def american_to_implied_prob(american_odds: int) -> Optional[float]:
    """Convert American odds to implied probability."""
    if american_odds is None:
        return None
    if american_odds < 0:
        return abs(american_odds) / (abs(american_odds) + 100)
    return 100 / (american_odds + 100)


def calculate_expected_ks(market_key: str, point: float, over_prob: float) -> Optional[float]:
    """
    Calculate expected strikeouts for batter strikeout props.

    For batter_strikeouts market:
    - If point is 0.5: expected_ks = over_probability (probability of 1+ K)
    - If point is 1.5: expected_ks = over_prob * 2 + (1 - over_prob) * 0.5
    - Generic: point * over_probability
    """
    if market_key != 'batter_strikeouts':
        return None
    if point is None or over_prob is None:
        return None

    try:
        point = float(point)
        over_prob = float(over_prob)

        if point == 0.5:
            # Over 0.5 means 1+ strikeouts, probability is directly the expected value
            return over_prob
        elif point == 1.5:
            # Weighted average assuming over means ~2, under means ~0.5
            return over_prob * 2.0 + (1 - over_prob) * 0.5
        else:
            # Generic approximation
            return point * over_prob
    except (ValueError, TypeError):
        return None


def transform_file_data(raw_data: Dict, file_path: str) -> List[Dict]:
    """Transform a single file's raw data into BigQuery rows."""
    rows = []

    try:
        # Detect historical vs current format
        if 'data' in raw_data and 'timestamp' in raw_data:
            odds_data = raw_data.get('data', {})
            snapshot_timestamp_str = raw_data.get('timestamp')
        elif 'odds' in raw_data:
            odds_data = raw_data.get('odds', {})
            snapshot_timestamp_str = raw_data.get('snapshot_timestamp')
        else:
            odds_data = raw_data
            snapshot_timestamp_str = None

        # Extract date from path
        path_parts = file_path.split('/')
        game_date = path_parts[-3] if len(path_parts) >= 3 else None

        # Get event_id from path
        event_folder = path_parts[-2] if len(path_parts) >= 2 else ''
        parts = event_folder.rsplit('-', 1)
        event_id = parts[0] if parts else event_folder

        if isinstance(odds_data, list):
            odds_data = odds_data[0] if odds_data else {}

        # Get team info
        home_team_full = odds_data.get('home_team', '')
        away_team_full = odds_data.get('away_team', '')
        home_team_abbr = get_team_abbr(home_team_full)
        away_team_abbr = get_team_abbr(away_team_full)

        # Generate game_id
        if event_id:
            game_id = event_id
        elif game_date and away_team_abbr and home_team_abbr:
            game_id = f"{game_date.replace('-', '')}_{away_team_abbr}_{home_team_abbr}"
        else:
            game_id = None

        snapshot_time = datetime.now(timezone.utc)

        # Process bookmakers
        for bookmaker in odds_data.get('bookmakers', []):
            bookmaker_key = bookmaker.get('key', '')
            last_update = bookmaker.get('last_update')

            if last_update:
                try:
                    last_update_dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    last_update_dt = None
            else:
                last_update_dt = None

            # Process markets
            for market in bookmaker.get('markets', []):
                market_key = market.get('key', '')

                # Group outcomes by player
                player_props = {}
                for outcome in market.get('outcomes', []):
                    player_name = outcome.get('description', '')
                    outcome_type = outcome.get('name', '')
                    price = outcome.get('price')
                    point = outcome.get('point')

                    if not player_name:
                        continue

                    if player_name not in player_props:
                        player_props[player_name] = {
                            'point': point,
                            'over_price': None,
                            'under_price': None,
                        }

                    if outcome_type == 'Over':
                        player_props[player_name]['over_price'] = normalize_odds(price)
                        player_props[player_name]['point'] = point
                    elif outcome_type == 'Under':
                        player_props[player_name]['under_price'] = normalize_odds(price)

                # Create rows
                for player_name, props in player_props.items():
                    over_implied = american_to_implied_prob(props['over_price'])
                    under_implied = american_to_implied_prob(props['under_price'])

                    # Calculate expected K's for batter strikeout props
                    expected_ks = calculate_expected_ks(market_key, props['point'], over_implied)

                    row = {
                        'game_id': game_id,
                        'game_date': game_date,
                        'event_id': event_id,
                        'player_name': player_name,
                        'player_lookup': normalize_name_for_lookup(player_name),
                        'team_abbr': None,  # Not in ODDS API response
                        'home_team_abbr': home_team_abbr,
                        'away_team_abbr': away_team_abbr,
                        'opposing_team_abbr': None,  # Would need lineup data to determine
                        'market_key': market_key,
                        'bookmaker': bookmaker_key,
                        'point': props['point'],
                        'over_price': props['over_price'],
                        'under_price': props['under_price'],
                        'over_implied_prob': over_implied,
                        'under_implied_prob': under_implied,
                        'expected_ks': expected_ks,
                        'last_update': last_update_dt.isoformat() if last_update_dt else None,
                        'snapshot_time': snapshot_time.isoformat(),
                        'source_file_path': file_path,
                        'created_at': snapshot_time.isoformat(),
                    }
                    rows.append(row)

    except Exception as e:
        logger.warning(f"Transform error for {file_path}: {e}")

    return rows


class BatchLoader:
    """Optimized batch loader for historical MLB batter props."""

    def __init__(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        dry_run: bool = False,
        parallel_downloads: int = 10,
    ):
        self.start_date = start_date
        self.end_date = end_date
        self.dry_run = dry_run
        self.parallel_downloads = parallel_downloads

        self.storage_client = storage.Client(project=PROJECT_ID)
        self.bucket = self.storage_client.bucket(BUCKET_NAME)
        self.bq_client = bigquery.Client(project=PROJECT_ID)

        self.stats = {
            'dates_processed': 0,
            'files_processed': 0,
            'rows_loaded': 0,
            'batches_written': 0,
            'errors': 0,
            'start_time': None,
        }

    def get_dates_from_gcs(self) -> List[str]:
        """Get all available dates from GCS."""
        logger.info("Scanning GCS for available dates...")

        dates = set()
        for blob in self.bucket.list_blobs(prefix=f"{GCS_PREFIX}/"):
            parts = blob.name.split('/')
            if len(parts) >= 3:
                date_str = parts[2]
                try:
                    datetime.strptime(date_str, '%Y-%m-%d')
                    dates.add(date_str)
                except ValueError:
                    continue

        sorted_dates = sorted(dates)

        # Apply filters
        if self.start_date:
            sorted_dates = [d for d in sorted_dates if d >= self.start_date]
        if self.end_date:
            sorted_dates = [d for d in sorted_dates if d <= self.end_date]

        logger.info(f"Found {len(sorted_dates)} dates to process")
        return sorted_dates

    def get_already_loaded_dates(self) -> Set[str]:
        """Check which dates already have data in BigQuery."""
        query = f"""
        SELECT DISTINCT CAST(game_date AS STRING) as game_date
        FROM `{TABLE_ID}`
        WHERE source_file_path LIKE '%batter-props-history%'
        """
        try:
            result = self.bq_client.query(query).result()
            return {row.game_date for row in result}
        except Exception as e:
            logger.warning(f"Could not check existing dates: {e}")
            return set()

    def download_file(self, blob_name: str) -> Tuple[str, Optional[Dict]]:
        """Download a single file from GCS."""
        try:
            blob = self.bucket.blob(blob_name)
            content = blob.download_as_text()
            return blob_name, json.loads(content)
        except Exception as e:
            logger.debug(f"Failed to download {blob_name}: {e}")
            return blob_name, None

    def get_files_for_date(self, game_date: str) -> List[str]:
        """Get all JSON files for a date."""
        prefix = f"{GCS_PREFIX}/{game_date}/"
        blobs = list(self.bucket.list_blobs(prefix=prefix))
        return [b.name for b in blobs if b.name.endswith('.json')]

    def load_batch_to_bigquery(self, rows: List[Dict]) -> int:
        """Load a batch of rows to BigQuery using NDJSON."""
        if not rows:
            return 0

        try:
            # Get schema
            target_table = self.bq_client.get_table(TABLE_ID)

            # Convert to NDJSON
            ndjson_data = "\n".join(json.dumps(row) for row in rows)
            ndjson_bytes = ndjson_data.encode('utf-8')

            # Configure batch load
            job_config = bigquery.LoadJobConfig(
                schema=target_table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                ignore_unknown_values=True
            )

            # Execute batch load
            load_job = self.bq_client.load_table_from_file(
                io.BytesIO(ndjson_bytes),
                TABLE_ID,
                job_config=job_config
            )
            load_job.result(timeout=120)

            if load_job.errors:
                logger.warning(f"Load had {len(load_job.errors)} errors")
                return 0

            return len(rows)

        except Exception as e:
            logger.error(f"Batch load failed: {e}")
            self.stats['errors'] += 1
            return 0

    def process_date(self, game_date: str) -> Tuple[int, int]:
        """Process all files for a single date. Returns (files, rows)."""
        files = self.get_files_for_date(game_date)
        if not files:
            return 0, 0

        all_rows = []

        # Download and transform files in parallel
        with ThreadPoolExecutor(max_workers=self.parallel_downloads) as executor:
            futures = {executor.submit(self.download_file, f): f for f in files}

            for future in as_completed(futures):
                file_path, data = future.result()
                if data:
                    rows = transform_file_data(data, file_path)
                    all_rows.extend(rows)

        return len(files), len(all_rows)

    def run(self) -> Dict:
        """Execute batch loading."""
        self.stats['start_time'] = time.time()

        logger.info("=" * 70)
        logger.info("MLB HISTORICAL BATTER PROPS BATCH LOADER")
        logger.info("=" * 70)
        logger.info(f"GCS Source: {GCS_PREFIX}")
        logger.info(f"BigQuery Target: {TABLE_ID}")

        # Get dates
        all_dates = self.get_dates_from_gcs()
        if not all_dates:
            logger.warning("No dates found in GCS")
            return self.stats

        # Check what's already loaded
        loaded_dates = self.get_already_loaded_dates()
        dates_to_process = [d for d in all_dates if d not in loaded_dates]

        logger.info(f"Total dates in GCS: {len(all_dates)}")
        logger.info(f"Already loaded: {len(loaded_dates)}")
        logger.info(f"To process: {len(dates_to_process)}")

        if self.dry_run:
            logger.info("\nDRY RUN - would process these dates:")
            for d in dates_to_process[:10]:
                files = self.get_files_for_date(d)
                logger.info(f"  {d}: {len(files)} files")
            if len(dates_to_process) > 10:
                logger.info(f"  ... and {len(dates_to_process) - 10} more dates")
            return self.stats

        # Process dates in batches
        all_rows = []

        for i, game_date in enumerate(dates_to_process, 1):
            logger.info(f"[{i}/{len(dates_to_process)}] Processing {game_date}...")

            # Download and transform files
            files = self.get_files_for_date(game_date)
            with ThreadPoolExecutor(max_workers=self.parallel_downloads) as executor:
                futures = {executor.submit(self.download_file, f): f for f in files}
                for future in as_completed(futures):
                    file_path, data = future.result()
                    if data:
                        rows = transform_file_data(data, file_path)
                        all_rows.extend(rows)
                        self.stats['files_processed'] += 1

            self.stats['dates_processed'] += 1

            # Flush batch when it gets large enough
            if len(all_rows) >= BATCH_SIZE:
                loaded = self.load_batch_to_bigquery(all_rows)
                self.stats['rows_loaded'] += loaded
                self.stats['batches_written'] += 1
                strikeouts = sum(1 for r in all_rows if r.get('market_key') == 'batter_strikeouts')
                logger.info(f"  Batch written: {loaded} rows ({strikeouts} batter strikeouts)")
                all_rows = []

            # Progress update every 10 dates
            if i % 10 == 0:
                elapsed = time.time() - self.stats['start_time']
                rate = self.stats['dates_processed'] / (elapsed / 60)
                logger.info(f"  Progress: {self.stats['dates_processed']} dates, "
                           f"{self.stats['rows_loaded']} rows, {rate:.1f} dates/min")

        # Final batch
        if all_rows:
            loaded = self.load_batch_to_bigquery(all_rows)
            self.stats['rows_loaded'] += loaded
            self.stats['batches_written'] += 1
            logger.info(f"  Final batch: {loaded} rows")

        # Summary
        elapsed = time.time() - self.stats['start_time']

        logger.info("\n" + "=" * 70)
        logger.info("BATTER PROPS BATCH LOADING COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Time: {elapsed/60:.1f} minutes")
        logger.info(f"Dates processed: {self.stats['dates_processed']}")
        logger.info(f"Files processed: {self.stats['files_processed']}")
        logger.info(f"Rows loaded: {self.stats['rows_loaded']}")
        logger.info(f"Batches written: {self.stats['batches_written']}")
        logger.info(f"Errors: {self.stats['errors']}")

        if self.stats['dates_processed'] > 0:
            logger.info(f"Rate: {self.stats['dates_processed'] / (elapsed / 60):.1f} dates/min")
            logger.info(f"Rate: {self.stats['rows_loaded'] / elapsed:.0f} rows/sec")

        return self.stats


def main():
    parser = argparse.ArgumentParser(
        description='Batch load MLB historical BATTER props to BigQuery',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be processed')
    parser.add_argument('--parallel', type=int, default=10, help='Parallel downloads (default: 10)')

    args = parser.parse_args()

    loader = BatchLoader(
        start_date=args.start_date,
        end_date=args.end_date,
        dry_run=args.dry_run,
        parallel_downloads=args.parallel,
    )

    try:
        loader.run()
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Batch loading failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
