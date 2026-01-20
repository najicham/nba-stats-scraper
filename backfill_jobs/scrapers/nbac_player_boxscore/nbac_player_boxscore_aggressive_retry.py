#!/usr/bin/env python3
"""
NBA.com Player Boxscore Aggressive Retry Script
================================================

Retry script for stubborn dates that failed in previous backfill attempts.
Uses very conservative settings to maximize success rate:
- Fewer workers (reduces API load)
- Longer timeouts (gives API more time)
- Retry logic with exponential backoff
- Rate limiting between requests

Usage:
    python backfill_jobs/scrapers/nbac_player_boxscore/nbac_player_boxscore_aggressive_retry.py \
        --service-url https://nba-phase1-scrapers-756957797294.us-west2.run.app \
        --dates-file /tmp/failed_dates_from_nbac.txt \
        --workers 3 \
        --timeout 300 \
        --max-retries 3
"""

import argparse
import concurrent.futures
import json
import logging
import os
import requests
from shared.clients.http_pool import get_http_session
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class AggressiveRetryRunner:
    """Retry runner with aggressive retry logic and rate limiting"""

    def __init__(
        self,
        service_url: str,
        dates_file: str,
        workers: int = 3,
        timeout: int = 300,
        max_retries: int = 3,
        retry_delay: int = 30,
        rate_limit_delay: float = 2.0
    ):
        self.service_url = service_url.rstrip('/')
        self.dates_file = dates_file
        self.workers = workers
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay  # Base delay for exponential backoff
        self.rate_limit_delay = rate_limit_delay  # Delay between each request

        # Load GCS client for checking existing data
        try:
            from google.cloud import storage
            self.gcs_client = storage.Client()
            self.bucket = self.gcs_client.bucket('nba-scraped-data')
            self.gcs_available = True
        except Exception as e:
            logger.warning(f"GCS client not available: {e}")
            self.gcs_available = False

        # Stats
        self.total_dates = 0
        self.succeeded = []
        self.failed = []
        self.skipped = []
        self.start_time = None

    def _load_dates(self) -> List[str]:
        """Load dates from file"""
        with open(self.dates_file, 'r') as f:
            dates = [line.strip() for line in f if line.strip()]

        # Validate and sort
        dates = sorted(set(dates))
        self.total_dates = len(dates)
        logger.info(f"Loaded {self.total_dates} unique dates from {self.dates_file}")
        return dates

    def _check_gcs_exists(self, game_date: str) -> bool:
        """Check if data already exists in GCS"""
        if not self.gcs_available:
            return False

        try:
            # Path pattern: nba-com/player-boxscores/YYYY-MM-DD/
            blob_prefix = f"nba-com/player-boxscores/{game_date}/"
            blobs = list(self.bucket.list_blobs(prefix=blob_prefix, max_results=1))
            return len(blobs) > 0
        except Exception as e:
            logger.debug(f"GCS check failed for {game_date}: {e}")
            return False

    def _scrape_date_with_retries(self, game_date: str, attempt: int = 1) -> Dict:
        """Scrape a single date with retry logic"""

        # Add rate limiting delay
        if self.rate_limit_delay > 0:
            time.sleep(self.rate_limit_delay)

        try:
            payload = {
                "scraper": "nbac_player_boxscore",
                "game_date": game_date,
                "export_groups": "prod"
            }

            logger.debug(f"[Attempt {attempt}/{self.max_retries}] Scraping {game_date}")

            response = get_http_session().post(
                f"{self.service_url}/scrape",
                json=payload,
                timeout=self.timeout
            )

            # Check response
            if response.status_code == 200:
                result = response.json()
                if result.get('status') == 'success':
                    return {
                        'status': 'success',
                        'game_date': game_date,
                        'attempt': attempt
                    }
                else:
                    # API returned error
                    error_msg = result.get('message', 'Unknown error')
                    if 'HTTP 500' in error_msg or 'timeout' in error_msg.lower():
                        # Retryable error
                        if attempt < self.max_retries:
                            delay = self.retry_delay * (2 ** (attempt - 1))  # Exponential backoff
                            logger.debug(f"  Retryable error, waiting {delay}s before retry...")
                            time.sleep(delay)
                            return self._scrape_date_with_retries(game_date, attempt + 1)

                    return {
                        'status': 'failed',
                        'game_date': game_date,
                        'error': error_msg,
                        'attempts': attempt
                    }
            else:
                # HTTP error
                error_msg = f"HTTP {response.status_code}"
                if attempt < self.max_retries and response.status_code >= 500:
                    delay = self.retry_delay * (2 ** (attempt - 1))
                    logger.debug(f"  HTTP {response.status_code}, waiting {delay}s before retry...")
                    time.sleep(delay)
                    return self._scrape_date_with_retries(game_date, attempt + 1)

                return {
                    'status': 'failed',
                    'game_date': game_date,
                    'error': error_msg,
                    'attempts': attempt
                }

        except requests.exceptions.Timeout:
            if attempt < self.max_retries:
                delay = self.retry_delay * (2 ** (attempt - 1))
                logger.debug(f"  Timeout, waiting {delay}s before retry...")
                time.sleep(delay)
                return self._scrape_date_with_retries(game_date, attempt + 1)

            return {
                'status': 'failed',
                'game_date': game_date,
                'error': f'Timeout after {self.timeout}s',
                'attempts': attempt
            }

        except Exception as e:
            return {
                'status': 'failed',
                'game_date': game_date,
                'error': str(e),
                'attempts': attempt
            }

    def _scrape_date(self, game_date: str, date_num: int) -> Dict:
        """Scrape a single date (main entry point)"""
        logger.info(f"[{date_num}/{self.total_dates}] Processing {game_date}")

        # Check if already in GCS
        if self._check_gcs_exists(game_date):
            logger.info(f"  ⏭️  Skipped (already in GCS)")
            return {
                'status': 'skipped',
                'game_date': game_date,
                'reason': 'Already in GCS'
            }

        # Scrape with retries
        result = self._scrape_date_with_retries(game_date)

        # Log result
        if result['status'] == 'success':
            logger.info(f"  ✅ Scraped successfully (attempt {result['attempt']})")
        else:
            error = result.get('error', 'Unknown')
            attempts = result.get('attempts', 1)
            logger.warning(f"  ❌ Failed after {attempts} attempts: {error}")

        return result

    def run(self):
        """Execute aggressive retry backfill"""
        logger.info("=" * 70)
        logger.info("NBA.com Player Boxscore Aggressive Retry")
        logger.info(f"  Service URL: {self.service_url}")
        logger.info(f"  Dates file: {self.dates_file}")
        logger.info(f"  Workers: {self.workers}")
        logger.info(f"  Timeout: {self.timeout}s")
        logger.info(f"  Max retries: {self.max_retries}")
        logger.info(f"  Retry delay (base): {self.retry_delay}s")
        logger.info(f"  Rate limit delay: {self.rate_limit_delay}s")
        logger.info("=" * 70)

        # Load dates
        dates = self._load_dates()

        # Start processing
        self.start_time = time.time()
        completed = 0

        # Process with limited parallelism
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self._scrape_date, date, i + 1): (date, i + 1)
                for i, date in enumerate(dates)
            }

            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                completed += 1

                if result['status'] == 'success':
                    self.succeeded.append(result)
                elif result['status'] == 'skipped':
                    self.skipped.append(result)
                elif result['status'] == 'failed':
                    self.failed.append(result)

                # Progress updates every 25 dates
                if completed % 25 == 0:
                    elapsed = time.time() - self.start_time
                    rate = completed / (elapsed / 60) if elapsed > 0 else 0
                    success_rate = (len(self.succeeded) / completed * 100) if completed > 0 else 0
                    eta_minutes = (self.total_dates - completed) / rate if rate > 0 else 0

                    logger.info(f"📊 Progress: {completed}/{self.total_dates} ({completed/self.total_dates*100:.1f}%) | "
                              f"✅ {len(self.succeeded)} | ⏭️ {len(self.skipped)} | ❌ {len(self.failed)} | "
                              f"{success_rate:.1f}% success | ETA: {eta_minutes:.0f}min")

        # Final summary
        self._print_summary()
        self._save_results()

    def _print_summary(self):
        """Print final summary"""
        duration = time.time() - self.start_time

        logger.info("=" * 70)
        logger.info("AGGRESSIVE RETRY COMPLETE")
        logger.info(f"Total dates: {self.total_dates}")
        logger.info(f"✅ Succeeded: {len(self.succeeded)}")
        logger.info(f"⏭️  Skipped: {len(self.skipped)}")
        logger.info(f"❌ Failed: {len(self.failed)}")
        logger.info(f"Time: {duration / 60:.1f} minutes")
        logger.info(f"Rate: {self.total_dates / (duration / 60):.1f} dates/min")

        if self.total_dates > 0:
            success_rate = (len(self.succeeded) + len(self.skipped)) / self.total_dates * 100
            logger.info(f"Success rate: {success_rate:.1f}%")

        logger.info("=" * 70)

    def _save_results(self):
        """Save results to files"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = Path(self.dates_file).parent

        # Save summary
        summary = {
            'timestamp': datetime.now().isoformat(),
            'total_dates': self.total_dates,
            'succeeded': len(self.succeeded),
            'skipped': len(self.skipped),
            'failed': len(self.failed),
            'duration_seconds': time.time() - self.start_time,
            'settings': {
                'workers': self.workers,
                'timeout': self.timeout,
                'max_retries': self.max_retries,
                'retry_delay': self.retry_delay,
                'rate_limit_delay': self.rate_limit_delay
            }
        }

        summary_file = output_dir / f"retry_summary_{timestamp}.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        logger.info(f"📊 Summary saved to: {summary_file}")

        # Save failed dates if any
        if self.failed:
            failed_output = {
                'timestamp': datetime.now().isoformat(),
                'total_failed': len(self.failed),
                'failed_dates': self.failed
            }

            failed_file = output_dir / f"retry_failed_dates_{timestamp}.json"
            with open(failed_file, 'w') as f:
                json.dump(failed_output, f, indent=2)
            logger.info(f"💾 Failed dates saved to: {failed_file}")

            # Also save as simple text list
            failed_txt = output_dir / f"retry_failed_dates_{timestamp}.txt"
            with open(failed_txt, 'w') as f:
                for item in self.failed:
                    f.write(f"{item['game_date']}\n")
            logger.info(f"💾 Failed dates list saved to: {failed_txt}")


def main():
    parser = argparse.ArgumentParser(description='Aggressive retry for NBA.com player boxscore backfill')
    parser.add_argument('--service-url', required=True, help='Scraper service URL')
    parser.add_argument('--dates-file', required=True, help='File with dates to retry')
    parser.add_argument('--workers', type=int, default=3, help='Number of parallel workers (default: 3)')
    parser.add_argument('--timeout', type=int, default=300, help='Timeout per request (default: 300s)')
    parser.add_argument('--max-retries', type=int, default=3, help='Max retries per date (default: 3)')
    parser.add_argument('--retry-delay', type=int, default=30, help='Base retry delay in seconds (default: 30s)')
    parser.add_argument('--rate-limit-delay', type=float, default=2.0, help='Delay between requests (default: 2.0s)')

    args = parser.parse_args()

    # Validate inputs
    if not Path(args.dates_file).exists():
        logger.error(f"❌ Dates file not found: {args.dates_file}")
        return 1

    # Run aggressive retry
    runner = AggressiveRetryRunner(
        service_url=args.service_url,
        dates_file=args.dates_file,
        workers=args.workers,
        timeout=args.timeout,
        max_retries=args.max_retries,
        retry_delay=args.retry_delay,
        rate_limit_delay=args.rate_limit_delay
    )

    runner.run()
    return 0


if __name__ == '__main__':
    exit(main())
