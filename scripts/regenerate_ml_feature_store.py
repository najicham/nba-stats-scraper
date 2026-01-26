#!/usr/bin/env python3
"""
Regenerate ML Feature Store after player_daily_cache fix.

This script runs the ML Feature Store processor for each date to regenerate
features using the corrected player_daily_cache values.

Usage:
    python scripts/regenerate_ml_feature_store.py --start-date 2024-10-01 --end-date 2025-01-26
    python scripts/regenerate_ml_feature_store.py --date 2025-01-26  # Single date
"""

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from typing import List

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor
from shared.config.gcp_config import get_project_id

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_date_range(start_date: date, end_date: date) -> List[date]:
    """Generate list of dates between start and end (inclusive)."""
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def regenerate_for_date(analysis_date: date) -> dict:
    """
    Regenerate ML feature store for a single date.

    Returns: dict with status and stats
    """
    logger.info(f"Regenerating ML feature store for {analysis_date}")

    try:
        # Instantiate processor (same way as production service)
        processor = MLFeatureStoreProcessor()

        # Build options (same as production service)
        opts = {
            'analysis_date': analysis_date,
            'project_id': get_project_id(),
            'backfill_mode': True,  # Use backfill mode to get actual played data
            'skip_downstream_trigger': True,  # Don't trigger downstream systems
            'strict_mode': False  # Allow processing even if some dependencies are soft-missing
        }

        # Run processor
        success = processor.run(opts)

        if success:
            # Get stats from processor
            stats = getattr(processor, 'stats', {})
            players_processed = stats.get('features_generated', 0)

            logger.info(f"✅ {analysis_date}: Generated features for {players_processed} players")

            return {
                'date': analysis_date,
                'status': 'success',
                'players_processed': players_processed,
                'stats': stats
            }
        else:
            logger.error(f"❌ {analysis_date}: Processor returned False")
            return {
                'date': analysis_date,
                'status': 'failed',
                'error': 'Processor returned False'
            }

    except Exception as e:
        logger.error(f"❌ {analysis_date}: Exception - {str(e)}")
        return {
            'date': analysis_date,
            'status': 'error',
            'error': str(e)
        }


def main():
    parser = argparse.ArgumentParser(description='Regenerate ML Feature Store')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--date', type=str, help='Single date to regenerate (YYYY-MM-DD)')

    args = parser.parse_args()

    # Determine date range
    if args.date:
        # Single date
        target_date = date.fromisoformat(args.date)
        dates = [target_date]
    elif args.start_date and args.end_date:
        # Date range
        start = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date)
        dates = get_date_range(start, end)
    else:
        parser.error("Must provide either --date or both --start-date and --end-date")

    # Process dates
    logger.info(f"Regenerating ML feature store for {len(dates)} dates ({dates[0]} to {dates[-1]})")

    results = []
    successful = 0
    failed = 0

    for analysis_date in dates:
        result = regenerate_for_date(analysis_date)
        results.append(result)

        if result['status'] == 'success':
            successful += 1
        else:
            failed += 1

    # Summary
    logger.info("=" * 70)
    logger.info("REGENERATION COMPLETE")
    logger.info("=" * 70)
    logger.info(f"Total dates processed: {len(dates)}")
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")

    # Total players processed
    total_players = sum(r.get('players_processed', 0) for r in results if r['status'] == 'success')
    logger.info(f"Total features generated: {total_players}")

    if failed > 0:
        logger.warning(f"\n⚠️ {failed} dates failed:")
        for r in results:
            if r['status'] != 'success':
                logger.warning(f"  - {r['date']}: {r.get('error', 'Unknown error')}")

    if successful == len(dates):
        logger.info("✅ All dates regenerated successfully")
    else:
        logger.warning(f"⚠️ {failed}/{len(dates)} dates failed")
        sys.exit(1)


if __name__ == '__main__':
    main()
