#!/usr/bin/env python3
"""
MLB BettingPros Historical Props Backfill
=========================================

Orchestrates the complete backfill of MLB player prop historical data from
BettingPros API. Collects 4 seasons (2022-2025) of data with actual outcomes.

Features:
- All 11 MLB prop markets (2 pitcher, 9 batter)
- Parallel execution with configurable workers
- Resume capability (skip existing GCS files)
- Progress tracking with ETA
- Rate limiting to respect API

Usage:
    # Full backfill (all markets, all seasons)
    python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py

    # Pitcher props only
    python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --markets pitcher

    # Batter props only
    python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --markets batter

    # Specific market
    python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --market_id 285

    # Date range
    python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py \\
        --start-date 2024-06-01 --end-date 2024-06-30

    # Dry run
    python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --dry-run

    # Resume (skip existing)
    python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --resume

    # Force re-scrape
    python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --no-resume

    # Single worker (debugging)
    python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --workers 1

Created: 2026-01-14
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests
from google.cloud import storage

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scrapers.utils.proxy_utils import get_proxy_urls

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

PROJECT_ID = 'nba-props-platform'
BUCKET_NAME = 'nba-scraped-data'
GCS_PREFIX = 'bettingpros-mlb/historical'

# API Configuration
API_BASE_URL = "https://api.bettingpros.com/v3/props"
API_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json',
    'Origin': 'https://www.fantasypros.com',
    'Referer': 'https://www.fantasypros.com/',
}

# Rate limiting
DEFAULT_DELAY = 0.3  # seconds between requests
DEFAULT_WORKERS = 4

# Market definitions
MLB_MARKETS = {
    # Pitcher Props (2)
    285: 'pitcher-strikeouts',
    290: 'pitcher-earned-runs-allowed',
    # Batter Props (9)
    287: 'batter-hits',
    288: 'batter-runs',
    289: 'batter-rbis',
    291: 'batter-doubles',
    292: 'batter-triples',
    293: 'batter-total-bases',
    294: 'batter-stolen-bases',
    295: 'batter-singles',
    299: 'batter-home-runs',
}

PITCHER_MARKETS = [285, 290]
BATTER_MARKETS = [287, 288, 289, 291, 292, 293, 294, 295, 299]

# Season date ranges
MLB_SEASONS = {
    2022: ('2022-04-07', '2022-10-05'),
    2023: ('2023-03-30', '2023-10-01'),
    2024: ('2024-03-28', '2024-09-29'),
    2025: ('2025-03-27', '2025-09-28'),
}


# Retryable HTTP status codes (transient server errors)
RETRYABLE_STATUS_CODES = {502, 503, 504}


@dataclass
class BackfillStats:
    """Track backfill progress and statistics."""
    start_time: float = field(default_factory=time.time)
    dates_processed: int = 0
    dates_skipped: int = 0
    api_calls: int = 0
    props_collected: int = 0
    files_created: int = 0
    errors: int = 0
    partial_failures: List[Tuple[int, str, str]] = field(default_factory=list)  # (market_id, date, reason)

    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    def elapsed_str(self) -> str:
        elapsed = self.elapsed_seconds()
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def rate_per_minute(self) -> float:
        elapsed = self.elapsed_seconds()
        if elapsed > 0:
            return self.api_calls / (elapsed / 60)
        return 0


class MLBBettingProsBackfill:
    """
    Master orchestrator for BettingPros historical backfill.

    Fetches all MLB prop data from the BettingPros API and stores
    results to Google Cloud Storage for downstream processing.
    """

    def __init__(
        self,
        markets: Optional[List[int]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        workers: int = DEFAULT_WORKERS,
        delay: float = DEFAULT_DELAY,
        resume: bool = True,
        dry_run: bool = False,
        use_proxy: bool = False,
    ):
        self.markets = markets or list(MLB_MARKETS.keys())
        self.start_date = start_date
        self.end_date = end_date
        self.workers = workers
        self.delay = delay
        self.resume = resume
        self.dry_run = dry_run
        self.use_proxy = use_proxy

        self.stats = BackfillStats()
        self.existing_files: Set[str] = set()

        # Initialize GCS client
        if not dry_run:
            self.storage_client = storage.Client(project=PROJECT_ID)
            self.bucket = self.storage_client.bucket(BUCKET_NAME)
        else:
            self.storage_client = None
            self.bucket = None

        # HTTP session for API calls
        self.session = requests.Session()
        self.session.headers.update(API_HEADERS)

        # Configure proxy if enabled
        if use_proxy:
            proxy_urls = get_proxy_urls()
            if proxy_urls:
                proxy_url = proxy_urls[0]  # Use first proxy
                self.session.proxies = {
                    'http': proxy_url,
                    'https': proxy_url
                }
                # SSL verification enabled for security
                # If proxy has SSL issues, configure proxy to use valid certificates
                logger.info(f"Proxy enabled: {proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url}")

    def get_date_range(self) -> List[str]:
        """Generate list of dates to process."""
        dates = []

        # Use provided dates or default to all seasons
        if self.start_date and self.end_date:
            start = datetime.strptime(self.start_date, '%Y-%m-%d')
            end = datetime.strptime(self.end_date, '%Y-%m-%d')
        else:
            # All seasons: 2022-2025
            start = datetime.strptime(MLB_SEASONS[2022][0], '%Y-%m-%d')
            end = datetime.strptime(MLB_SEASONS[2025][1], '%Y-%m-%d')

        current = start
        while current <= end:
            date_str = current.strftime('%Y-%m-%d')

            # Check if date is within any season
            for season, (season_start, season_end) in MLB_SEASONS.items():
                if season_start <= date_str <= season_end:
                    dates.append(date_str)
                    break

            current += timedelta(days=1)

        return dates

    def scan_existing_files(self) -> None:
        """Scan GCS for existing files to enable resume."""
        if not self.resume or self.dry_run:
            return

        logger.info("Scanning GCS for existing files...")

        for market_id in self.markets:
            market_name = MLB_MARKETS[market_id]
            prefix = f"{GCS_PREFIX}/{market_name}/"

            try:
                blobs = self.bucket.list_blobs(prefix=prefix)
                for blob in blobs:
                    # Extract date from path: bettingpros-mlb/historical/pitcher-strikeouts/2024-06-15/props.json
                    parts = blob.name.split('/')
                    if len(parts) >= 4 and parts[-1] == 'props.json':
                        date = parts[-2]
                        key = f"{market_id}:{date}"
                        self.existing_files.add(key)
            except Exception as e:
                logger.warning(f"Error scanning GCS for market {market_name}: {e}")

        logger.info(f"Found {len(self.existing_files)} existing files")

    def file_exists(self, market_id: int, date: str) -> bool:
        """Check if file already exists in GCS."""
        return f"{market_id}:{date}" in self.existing_files

    def fetch_props(self, market_id: int, date: str) -> Tuple[List[Dict], int, Optional[str]]:
        """
        Fetch all props for a market/date with pagination and retry logic.

        Returns:
            Tuple of (props list, total API calls, failure_reason or None)
        """
        all_props = []
        page = 1
        api_calls = 0
        max_retries = 3
        failure_reason = None

        while True:
            url = f"{API_BASE_URL}?sport=MLB&market_id={market_id}&date={date}&limit=50&page={page}"

            for attempt in range(max_retries):
                try:
                    response = self.session.get(url, timeout=60)  # Increased timeout
                    api_calls += 1

                    if response.status_code != 200:
                        # Retry on transient server errors (502, 503, 504)
                        if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 5
                            logger.warning(f"API returned {response.status_code} for {market_id}/{date} page {page}, retrying in {wait_time}s...")
                            time.sleep(wait_time)
                            continue
                        failure_reason = f"HTTP {response.status_code} on page {page}"
                        logger.warning(f"API returned {response.status_code} for {market_id}/{date} (after {attempt + 1} attempts)")
                        return all_props, api_calls, failure_reason  # Return what we have

                    data = response.json()

                    # Check for API timeout response
                    if data.get('message') == 'Endpoint request timed out':
                        if attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 5
                            logger.warning(f"API timeout for {market_id}/{date}, retrying in {wait_time}s...")
                            time.sleep(wait_time)
                            continue
                        else:
                            failure_reason = f"API timeout on page {page}"
                            logger.error(f"API timeout after {max_retries} retries for {market_id}/{date}")
                            return all_props, api_calls, failure_reason

                    props = data.get('props', [])
                    pagination = data.get('_pagination', {})

                    all_props.extend(props)

                    total_pages = pagination.get('total_pages', 1)
                    if page >= total_pages:
                        return all_props, api_calls, None  # Success, no failure

                    page += 1
                    time.sleep(self.delay)  # Rate limiting between pages
                    break  # Success, exit retry loop

                except Exception as e:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 5
                        logger.warning(f"Error fetching {market_id}/{date} page {page} (attempt {attempt + 1}): {e}, retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        failure_reason = f"Exception on page {page}: {type(e).__name__}"
                        logger.error(f"Error fetching {market_id}/{date} page {page} after {max_retries} retries: {e}")
                        return all_props, api_calls, failure_reason

        return all_props, api_calls, None  # Should not reach here, but just in case

    def process_props(self, props: List[Dict]) -> List[Dict]:
        """Transform raw props into standardized format."""
        processed = []

        for prop in props:
            try:
                participant = prop.get('participant', {})
                player = participant.get('player', {})
                over = prop.get('over', {})
                under = prop.get('under', {})
                projection = prop.get('projection', {})
                scoring = prop.get('scoring', {})
                performance = prop.get('performance', {})
                extra = prop.get('extra', {})

                processed.append({
                    # Identifiers
                    'event_id': prop.get('event_id'),
                    'player_id': participant.get('id'),
                    'player_name': participant.get('name'),
                    'team': player.get('team'),
                    'position': player.get('position'),

                    # Over line
                    'over_line': over.get('line'),
                    'over_odds': over.get('odds'),
                    'over_book_id': over.get('book'),
                    'over_consensus_line': over.get('consensus_line'),

                    # Under line
                    'under_line': under.get('line'),
                    'under_odds': under.get('odds'),
                    'under_book_id': under.get('book'),
                    'under_consensus_line': under.get('consensus_line'),

                    # Projection
                    'projection_value': projection.get('value'),
                    'projection_side': projection.get('recommended_side'),
                    'projection_ev': projection.get('expected_value'),
                    'projection_rating': projection.get('bet_rating'),

                    # ACTUAL OUTCOME
                    'actual_value': scoring.get('actual'),
                    'is_scored': scoring.get('is_scored', False),
                    'is_push': scoring.get('is_push', False),

                    # Performance trends
                    'perf_last_5_over': self._safe_perf(performance, 'last_5', 'over'),
                    'perf_last_5_under': self._safe_perf(performance, 'last_5', 'under'),
                    'perf_last_10_over': self._safe_perf(performance, 'last_10', 'over'),
                    'perf_last_10_under': self._safe_perf(performance, 'last_10', 'under'),
                    'perf_season_over': self._safe_perf(performance, 'season', 'over'),
                    'perf_season_under': self._safe_perf(performance, 'season', 'under'),

                    # Context
                    'opposing_pitcher': extra.get('opposing_pitcher'),
                    'opposition_rank': extra.get('opposition_rank', {}).get('rank'),
                })
            except Exception as e:
                logger.debug(f"Error processing prop: {e}")
                continue

        return processed

    def _safe_perf(self, performance: Dict, period: str, side: str) -> Optional[int]:
        """Safely extract performance value."""
        try:
            return performance.get(period, {}).get(side)
        except (AttributeError, TypeError, KeyError):
            return None

    def save_to_gcs(self, market_id: int, date: str, props: List[Dict]) -> bool:
        """Save props to GCS."""
        if self.dry_run:
            return True

        market_name = MLB_MARKETS[market_id]
        gcs_path = f"{GCS_PREFIX}/{market_name}/{date}/props.json"

        data = {
            'meta': {
                'sport': 'MLB',
                'market_id': market_id,
                'market_name': market_name,
                'date': date,
                'total_props': len(props),
                'scraped_at': datetime.now(timezone.utc).isoformat(),
            },
            'props': props,
        }

        try:
            blob = self.bucket.blob(gcs_path)
            blob.upload_from_string(
                json.dumps(data, indent=2),
                content_type='application/json'
            )
            return True
        except Exception as e:
            logger.error(f"Error saving to GCS: {gcs_path}: {e}")
            return False

    def process_market_date(self, market_id: int, date: str) -> Dict:
        """Process a single market/date combination."""
        market_name = MLB_MARKETS[market_id]

        # Check if already exists
        if self.resume and self.file_exists(market_id, date):
            return {
                'market_id': market_id,
                'date': date,
                'status': 'skipped',
                'props': 0,
                'api_calls': 0,
            }

        if self.dry_run:
            return {
                'market_id': market_id,
                'date': date,
                'status': 'dry_run',
                'props': 0,
                'api_calls': 0,
            }

        # Fetch props
        raw_props, api_calls, failure_reason = self.fetch_props(market_id, date)

        # Process props
        processed_props = self.process_props(raw_props)

        # Save to GCS
        if processed_props or True:  # Save even if empty to mark as processed
            success = self.save_to_gcs(market_id, date, processed_props)
            status = 'success' if success else 'error'
        else:
            status = 'empty'

        return {
            'market_id': market_id,
            'date': date,
            'status': status,
            'props': len(processed_props),
            'api_calls': api_calls,
            'failure_reason': failure_reason,
        }

    def run(self) -> None:
        """Execute the backfill."""
        print("=" * 70)
        print("MLB BETTINGPROS HISTORICAL PROPS BACKFILL")
        print("=" * 70)
        print()

        # Get dates to process
        dates = self.get_date_range()
        total_tasks = len(dates) * len(self.markets)

        # Configuration summary
        pitcher_markets = [m for m in self.markets if m in PITCHER_MARKETS]
        batter_markets = [m for m in self.markets if m in BATTER_MARKETS]

        print("Configuration:")
        print(f"  Markets: {len(self.markets)} ({len(pitcher_markets)} pitcher, {len(batter_markets)} batter)")
        print(f"  Date range: {dates[0] if dates else 'N/A'} to {dates[-1] if dates else 'N/A'}")
        print(f"  Total days: {len(dates)}")
        print(f"  Total tasks: {total_tasks}")
        print(f"  Workers: {self.workers}")
        print(f"  Delay: {self.delay}s")
        print(f"  Resume: {self.resume}")
        print(f"  Dry run: {self.dry_run}")
        print()

        if not dates:
            print("No dates to process!")
            return

        # Scan for existing files
        self.scan_existing_files()
        print()

        # Build task list
        tasks = []
        for date in dates:
            for market_id in self.markets:
                tasks.append((market_id, date))

        # Process tasks
        print("Starting backfill...")
        print()

        completed = 0
        last_progress = time.time()

        if self.workers == 1:
            # Single-threaded for debugging
            for market_id, date in tasks:
                result = self.process_market_date(market_id, date)
                self._update_stats(result)
                completed += 1

                if result['status'] != 'skipped':
                    market_name = MLB_MARKETS[market_id]
                    logger.info(f"[{completed}/{total_tasks}] {market_name} {date}: {result['props']} props")

                # Progress update every 30 seconds
                if time.time() - last_progress > 30:
                    self._print_progress(completed, total_tasks)
                    last_progress = time.time()

                time.sleep(self.delay)
        else:
            # Multi-threaded
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                future_to_task = {
                    executor.submit(self.process_market_date, m, d): (m, d)
                    for m, d in tasks
                }

                for future in as_completed(future_to_task):
                    market_id, date = future_to_task[future]
                    try:
                        result = future.result()
                        self._update_stats(result)
                    except Exception as e:
                        logger.error(f"Task failed for {market_id}/{date}: {e}")
                        self.stats.errors += 1

                    completed += 1

                    # Progress update every 30 seconds
                    if time.time() - last_progress > 30:
                        self._print_progress(completed, total_tasks)
                        last_progress = time.time()

        # Final summary
        self._print_summary(total_tasks)

    def _update_stats(self, result: Dict) -> None:
        """Update statistics from task result."""
        if result['status'] == 'skipped':
            self.stats.dates_skipped += 1
        elif result['status'] == 'success':
            self.stats.dates_processed += 1
            self.stats.files_created += 1
        elif result['status'] == 'error':
            self.stats.errors += 1
        elif result['status'] == 'dry_run':
            self.stats.dates_processed += 1

        self.stats.api_calls += result['api_calls']
        self.stats.props_collected += result['props']

        # Track partial failures (got some data but hit an error)
        if result.get('failure_reason'):
            self.stats.partial_failures.append((
                result['market_id'],
                result['date'],
                result['failure_reason']
            ))

    def _print_progress(self, completed: int, total: int) -> None:
        """Print progress update."""
        pct = (completed / total * 100) if total > 0 else 0
        rate = self.stats.rate_per_minute()
        remaining = total - completed
        eta_minutes = remaining / rate if rate > 0 else 0

        print(
            f"Progress: {completed}/{total} ({pct:.1f}%) | "
            f"Props: {self.stats.props_collected:,} | "
            f"Rate: {rate:.1f}/min | "
            f"ETA: {eta_minutes:.0f} min"
        )

    def _print_summary(self, total_tasks: int) -> None:
        """Print final summary."""
        print()
        print("=" * 70)
        print("BACKFILL COMPLETE")
        print("=" * 70)
        print(f"  Total time: {self.stats.elapsed_str()}")
        print(f"  Tasks completed: {self.stats.dates_processed + self.stats.dates_skipped}/{total_tasks}")
        print(f"  Tasks processed: {self.stats.dates_processed}")
        print(f"  Tasks skipped (existing): {self.stats.dates_skipped}")
        print(f"  Files created: {self.stats.files_created}")
        print(f"  Props collected: {self.stats.props_collected:,}")
        print(f"  API calls: {self.stats.api_calls:,}")
        print(f"  Errors: {self.stats.errors}")
        print(f"  Partial failures: {len(self.stats.partial_failures)}")
        print(f"  Rate: {self.stats.rate_per_minute():.1f} calls/min")
        print()

        # Print and save partial failures for retry
        if self.stats.partial_failures:
            print("=" * 70)
            print("PARTIAL FAILURES (may have incomplete data)")
            print("=" * 70)
            for market_id, date, reason in self.stats.partial_failures:
                market_name = MLB_MARKETS.get(market_id, f"unknown-{market_id}")
                print(f"  {market_name} ({market_id}) {date}: {reason}")
            print()

            # Save to file for easy retry
            retry_file = Path(__file__).parent / "retry_failures.json"
            retry_data = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "failures": [
                    {
                        "market_id": m,
                        "market_name": MLB_MARKETS.get(m, f"unknown-{m}"),
                        "date": d,
                        "reason": r
                    }
                    for m, d, r in self.stats.partial_failures
                ],
                "retry_commands": [
                    f"python {Path(__file__).name} --market_id {m} --start-date {d} --end-date {d} --no-resume"
                    for m, d, _ in self.stats.partial_failures
                ]
            }
            with open(retry_file, 'w') as f:
                json.dump(retry_data, f, indent=2)
            print(f"Retry commands saved to: {retry_file}")
            print()


def main():
    parser = argparse.ArgumentParser(
        description='Backfill MLB historical props from BettingPros API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Market selection
    market_group = parser.add_mutually_exclusive_group()
    market_group.add_argument(
        '--markets',
        choices=['all', 'pitcher', 'batter'],
        default='all',
        help='Market category to backfill (default: all)'
    )
    market_group.add_argument(
        '--market_id',
        type=int,
        help='Specific market ID to backfill'
    )

    # Date range
    parser.add_argument(
        '--start-date',
        help='Start date (YYYY-MM-DD). Default: 2022-04-07'
    )
    parser.add_argument(
        '--end-date',
        help='End date (YYYY-MM-DD). Default: 2025-09-28'
    )
    parser.add_argument(
        '--season',
        type=int,
        choices=[2022, 2023, 2024, 2025],
        help='Backfill specific season only'
    )

    # Execution options
    parser.add_argument(
        '--workers',
        type=int,
        default=DEFAULT_WORKERS,
        help=f'Number of parallel workers (default: {DEFAULT_WORKERS})'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=DEFAULT_DELAY,
        help=f'Delay between API calls in seconds (default: {DEFAULT_DELAY})'
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        default=True,
        help='Skip existing files (default: True)'
    )
    parser.add_argument(
        '--no-resume',
        action='store_true',
        help='Force re-scrape all files'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be processed without making API calls'
    )
    parser.add_argument(
        '--proxy',
        action='store_true',
        help='Use proxy for API requests'
    )

    args = parser.parse_args()

    # Resolve markets
    if args.market_id:
        markets = [args.market_id]
    elif args.markets == 'pitcher':
        markets = PITCHER_MARKETS
    elif args.markets == 'batter':
        markets = BATTER_MARKETS
    else:
        markets = list(MLB_MARKETS.keys())

    # Resolve dates
    start_date = args.start_date
    end_date = args.end_date

    if args.season:
        start_date, end_date = MLB_SEASONS[args.season]

    # Resolve resume
    resume = not args.no_resume

    # Run backfill
    backfill = MLBBettingProsBackfill(
        markets=markets,
        start_date=start_date,
        end_date=end_date,
        workers=args.workers,
        delay=args.delay,
        resume=resume,
        dry_run=args.dry_run,
        use_proxy=args.proxy,
    )

    try:
        backfill.run()
    except KeyboardInterrupt:
        print("\n\nBackfill interrupted by user")
        print("Resume with: python backfill_all_props.py --resume")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Backfill failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
