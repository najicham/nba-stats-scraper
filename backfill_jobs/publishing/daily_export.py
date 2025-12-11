#!/usr/bin/env python3
"""
Phase 6 Daily Export Job

Exports prediction data to GCS as JSON for website consumption.
Can be run for a single date or backfill a range.

Usage:
    # Export single date (all exporters)
    python daily_export.py --date 2021-11-10

    # Export yesterday (default)
    python daily_export.py

    # Backfill all dates with graded predictions
    python daily_export.py --backfill-all

    # Export only specific types
    python daily_export.py --date 2021-11-10 --only results,best-bets

    # Export player profiles
    python daily_export.py --players

    # Export player profiles with minimum games threshold
    python daily_export.py --players --min-games 10
"""

import argparse
import logging
import sys
import os
from datetime import datetime, timedelta
from typing import List, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.cloud import bigquery
from data_processors.publishing.results_exporter import ResultsExporter
from data_processors.publishing.system_performance_exporter import SystemPerformanceExporter
from data_processors.publishing.best_bets_exporter import BestBetsExporter
from data_processors.publishing.predictions_exporter import PredictionsExporter
from data_processors.publishing.player_profile_exporter import PlayerProfileExporter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'

# Available export types
EXPORT_TYPES = ['results', 'performance', 'best-bets', 'predictions']


def get_dates_with_predictions() -> List[str]:
    """Get all dates that have graded predictions."""
    client = bigquery.Client(project=PROJECT_ID)
    query = """
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_predictions.prediction_accuracy`
    ORDER BY game_date
    """
    results = client.query(query).result()
    return [row['game_date'].strftime('%Y-%m-%d') for row in results]


def export_date(
    target_date: str,
    update_latest: bool = True,
    export_types: Optional[List[str]] = None
) -> dict:
    """
    Export data for a single date.

    Args:
        target_date: Date string in YYYY-MM-DD format
        update_latest: Whether to update latest.json files
        export_types: List of types to export (default: all)

    Returns:
        Dict with export status and paths
    """
    if export_types is None:
        export_types = EXPORT_TYPES

    result = {
        'date': target_date,
        'status': 'success',
        'paths': {},
        'errors': []
    }

    # Results exporter
    if 'results' in export_types:
        try:
            exporter = ResultsExporter()
            path = exporter.export(target_date, update_latest=update_latest)
            result['paths']['results'] = path
            logger.info(f"  Results: {path}")
        except Exception as e:
            result['errors'].append(f"results: {e}")
            logger.error(f"  Results error: {e}")

    # Performance exporter
    if 'performance' in export_types:
        try:
            exporter = SystemPerformanceExporter()
            path = exporter.export(target_date)
            result['paths']['performance'] = path
            logger.info(f"  Performance: {path}")
        except Exception as e:
            result['errors'].append(f"performance: {e}")
            logger.error(f"  Performance error: {e}")

    # Best bets exporter
    if 'best-bets' in export_types:
        try:
            exporter = BestBetsExporter()
            path = exporter.export(target_date, update_latest=update_latest)
            result['paths']['best_bets'] = path
            logger.info(f"  Best Bets: {path}")
        except Exception as e:
            result['errors'].append(f"best-bets: {e}")
            logger.error(f"  Best Bets error: {e}")

    # Predictions exporter
    if 'predictions' in export_types:
        try:
            exporter = PredictionsExporter()
            path = exporter.export(target_date, update_today=update_latest)
            result['paths']['predictions'] = path
            logger.info(f"  Predictions: {path}")
        except Exception as e:
            result['errors'].append(f"predictions: {e}")
            logger.error(f"  Predictions error: {e}")

    if result['errors']:
        result['status'] = 'partial' if result['paths'] else 'failed'

    return result


def export_players(min_games: int = 5) -> dict:
    """
    Export all player profiles.

    Args:
        min_games: Minimum games to include player

    Returns:
        Dict with export status
    """
    logger.info(f"Exporting player profiles (min_games={min_games})")

    exporter = PlayerProfileExporter()

    result = {
        'status': 'success',
        'paths': []
    }

    try:
        paths = exporter.export_all_players(min_games=min_games)
        result['paths'] = paths
        result['count'] = len(paths)
        logger.info(f"Exported {len(paths)} player profiles")
    except Exception as e:
        result['status'] = 'failed'
        result['error'] = str(e)
        logger.error(f"Player export error: {e}")

    return result


def run_backfill(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    backfill_all: bool = False,
    export_types: Optional[List[str]] = None
):
    """
    Backfill exports for a date range.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        backfill_all: If True, export all dates with predictions
        export_types: List of types to export (default: all)
    """
    # Get dates to process
    if backfill_all:
        dates = get_dates_with_predictions()
        logger.info(f"Backfilling all {len(dates)} dates with predictions")
    else:
        # Generate date range
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        dates = []
        current = start
        while current <= end:
            dates.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
        logger.info(f"Backfilling {len(dates)} dates from {start_date} to {end_date}")

    if export_types:
        logger.info(f"Export types: {export_types}")

    # Process each date
    successful = 0
    partial = 0
    failed = 0

    for i, target_date in enumerate(dates):
        logger.info(f"[{i+1}/{len(dates)}] Exporting {target_date}")

        # Only update latest.json for the most recent date
        update_latest = (target_date == dates[-1])
        result = export_date(target_date, update_latest=update_latest, export_types=export_types)

        if result['status'] == 'success':
            successful += 1
        elif result['status'] == 'partial':
            partial += 1
        else:
            failed += 1

    # Summary
    logger.info("=" * 60)
    logger.info("BACKFILL COMPLETE")
    logger.info(f"  Successful: {successful}")
    logger.info(f"  Partial: {partial}")
    logger.info(f"  Failed: {failed}")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description='Phase 6 Daily Export - Export predictions to GCS JSON'
    )
    parser.add_argument(
        '--date',
        type=str,
        help='Single date to export (YYYY-MM-DD). Default: yesterday'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        help='Start date for backfill (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        help='End date for backfill (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--backfill-all',
        action='store_true',
        help='Backfill all dates with graded predictions'
    )
    parser.add_argument(
        '--only',
        type=str,
        help=f'Comma-separated list of export types: {",".join(EXPORT_TYPES)}'
    )
    parser.add_argument(
        '--players',
        action='store_true',
        help='Export player profiles instead of daily data'
    )
    parser.add_argument(
        '--min-games',
        type=int,
        default=5,
        help='Minimum games for player profiles (default: 5)'
    )

    args = parser.parse_args()

    # Parse export types
    export_types = None
    if args.only:
        export_types = [t.strip() for t in args.only.split(',')]
        invalid = [t for t in export_types if t not in EXPORT_TYPES]
        if invalid:
            logger.error(f"Invalid export types: {invalid}. Valid: {EXPORT_TYPES}")
            sys.exit(1)

    # Handle player profiles separately
    if args.players:
        result = export_players(min_games=args.min_games)
        if result['status'] == 'success':
            logger.info(f"Player export complete: {result['count']} profiles")
        else:
            logger.error(f"Player export failed: {result.get('error')}")
            sys.exit(1)
        return

    # Determine mode
    if args.backfill_all:
        run_backfill(backfill_all=True, export_types=export_types)
    elif args.start_date and args.end_date:
        run_backfill(start_date=args.start_date, end_date=args.end_date, export_types=export_types)
    elif args.date:
        result = export_date(args.date, export_types=export_types)
        if result['status'] == 'success':
            logger.info(f"Export complete: {result['paths']}")
        elif result['status'] == 'partial':
            logger.warning(f"Export partial: {result['paths']}, errors: {result['errors']}")
        else:
            logger.error(f"Export failed: {result.get('errors')}")
            sys.exit(1)
    else:
        # Default: yesterday
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        logger.info(f"No date specified, exporting yesterday: {yesterday}")
        result = export_date(yesterday, export_types=export_types)
        if result['status'] == 'success':
            logger.info(f"Export complete: {result['paths']}")
        elif result['status'] == 'partial':
            logger.warning(f"Export partial: {result['paths']}, errors: {result['errors']}")
        else:
            logger.error(f"Export failed: {result.get('errors')}")
            sys.exit(1)


if __name__ == '__main__':
    main()
