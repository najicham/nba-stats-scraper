#!/usr/bin/env python3
"""
Cleanup scraper failures that have been successfully backfilled.

This script:
1. Finds failures marked as backfilled=FALSE
2. Verifies if data actually exists for those dates
3. Updates backfilled=TRUE if data is present
4. Handles postponed games appropriately
5. Supports dry-run mode for safe testing

Usage:
    python bin/monitoring/cleanup_scraper_failures.py --dry-run --days-back=7
    python bin/monitoring/cleanup_scraper_failures.py --scraper=nbac_play_by_play
    python bin/monitoring/cleanup_scraper_failures.py  # Production run

Examples:
    # Test what would be cleaned up
    python bin/monitoring/cleanup_scraper_failures.py --dry-run

    # Clean up only one scraper
    python bin/monitoring/cleanup_scraper_failures.py --scraper=bdb_pbp_scraper

    # Clean up last 14 days
    python bin/monitoring/cleanup_scraper_failures.py --days-back=14
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# GCP Configuration
PROJECT_ID = os.environ.get("GCP_PROJECT_ID") or os.environ.get("GCP_PROJECT", "nba-props-platform")

# Map scraper names to their data tables and verification queries
# This mapping allows us to check if data was successfully scraped
SCRAPER_TABLE_MAP = {
    'nbac_play_by_play': {
        'table': 'nba_raw.nbac_play_by_play',
        'date_field': 'game_date',
        'description': 'NBA.com play-by-play data'
    },
    'nbac_player_boxscore': {
        'table': 'nba_raw.nbac_player_boxscores',
        'date_field': 'game_date',
        'description': 'NBA.com player boxscores'
    },
    'nbac_team_boxscore': {
        'table': 'nba_raw.nbac_team_boxscore',
        'date_field': 'game_date',
        'description': 'NBA.com team boxscores'
    },
    'bdl_boxscores': {
        'table': 'nba_raw.bdl_player_boxscores',
        'date_field': 'game_date',
        'description': 'BallDontLie boxscores'
    },
    'bdb_pbp_scraper': {
        'table': 'nba_raw.bigdataball_play_by_play',
        'date_field': 'game_date',
        'description': 'BigDataBall play-by-play'
    },
    'nbac_scoreboard_v2': {
        'table': 'nba_raw.nbac_scoreboard_v2',
        'date_field': 'game_date',
        'description': 'NBA.com scoreboard v2'
    },
    'nbac_injury_report': {
        'table': 'nba_raw.nbac_injury_report',
        'date_field': 'report_date',
        'description': 'NBA.com injury report'
    },
    'nbac_gamebook': {
        'table': 'nba_raw.nbac_gamebook_player_stats',
        'date_field': 'game_date',
        'description': 'NBA.com gamebook PDFs'
    },
    'bdl_injuries': {
        'table': 'nba_raw.bdl_injuries',
        'date_field': 'scrape_date',
        'description': 'BallDontLie injuries'
    },
}


def get_unbackfilled_failures(
    client: bigquery.Client,
    days_back: int = 7,
    scraper_name: Optional[str] = None
) -> List[Dict]:
    """
    Query failures where backfilled=FALSE.

    Args:
        client: BigQuery client
        days_back: Number of days to look back
        scraper_name: Optional filter for specific scraper

    Returns:
        List of failure records with game_date and scraper_name
    """
    query = f"""
    SELECT
        game_date,
        scraper_name,
        error_type,
        error_message,
        first_failed_at,
        last_failed_at,
        retry_count
    FROM `{PROJECT_ID}.nba_orchestration.scraper_failures`
    WHERE backfilled = FALSE
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days_back DAY)
    """

    if scraper_name:
        query += " AND scraper_name = @scraper_name"

    query += " ORDER BY game_date DESC, scraper_name"

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("days_back", "INT64", days_back),
        ]
    )

    if scraper_name:
        job_config.query_parameters.append(
            bigquery.ScalarQueryParameter("scraper_name", "STRING", scraper_name)
        )

    try:
        result = client.query(query, job_config=job_config).result()
        failures = [dict(row) for row in result]
        logger.info(f"Found {len(failures)} unbackfilled failures")
        return failures
    except Exception as e:
        logger.error(f"Failed to query unbackfilled failures: {e}")
        return []


def check_if_data_exists(
    client: bigquery.Client,
    scraper_name: str,
    game_date: str
) -> tuple[bool, int]:
    """
    Check if data exists for this scraper/date combination.

    Args:
        client: BigQuery client
        scraper_name: Name of the scraper
        game_date: Date to check (YYYY-MM-DD format)

    Returns:
        Tuple of (data_exists: bool, record_count: int)
    """
    # Get table mapping for this scraper
    scraper_config = SCRAPER_TABLE_MAP.get(scraper_name)

    if not scraper_config:
        logger.warning(f"No table mapping for scraper: {scraper_name}")
        return False, 0

    table = scraper_config['table']
    date_field = scraper_config['date_field']

    # Query to count records for this date
    query = f"""
    SELECT COUNT(*) as record_count
    FROM `{PROJECT_ID}.{table}`
    WHERE {date_field} = @game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    )

    try:
        result = client.query(query, job_config=job_config).result()
        row = next(result, None)
        record_count = row.record_count if row else 0

        # Consider data to exist if there are any records
        data_exists = record_count > 0

        if data_exists:
            logger.info(f"✅ Found {record_count} records for {scraper_name} on {game_date}")
        else:
            logger.debug(f"❌ No data found for {scraper_name} on {game_date}")

        return data_exists, record_count

    except Exception as e:
        logger.error(f"Error checking data for {scraper_name}/{game_date}: {e}")
        return False, 0


def check_game_status(client: bigquery.Client, game_date: str) -> Dict:
    """
    Check if games were postponed on this date.

    Args:
        client: BigQuery client
        game_date: Date to check (YYYY-MM-DD format)

    Returns:
        Dict with game status information
    """
    query = f"""
    SELECT
        COUNT(*) as total_games,
        COUNTIF(game_status = 4) as postponed_games,
        COUNTIF(game_status = 3) as finished_games,
        COUNTIF(game_status IN (1, 2)) as scheduled_or_live
    FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
    WHERE game_date = @game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    )

    try:
        result = client.query(query, job_config=job_config).result()
        row = next(result, None)
        if row is None:
            return {'total_games': 0, 'postponed_games': 0, 'finished_games': 0, 'scheduled_or_live': 0, 'all_postponed': False}

        status = {
            'total_games': row.total_games,
            'postponed_games': row.postponed_games,
            'finished_games': row.finished_games,
            'scheduled_or_live': row.scheduled_or_live,
            'all_postponed': row.total_games > 0 and row.postponed_games == row.total_games
        }

        if status['all_postponed']:
            logger.info(f"📅 All {status['total_games']} games on {game_date} were postponed")
        elif status['postponed_games'] > 0:
            logger.info(f"📅 {status['postponed_games']}/{status['total_games']} games on {game_date} were postponed")

        return status

    except Exception as e:
        logger.error(f"Error checking game status for {game_date}: {e}")
        return {
            'total_games': 0,
            'postponed_games': 0,
            'finished_games': 0,
            'scheduled_or_live': 0,
            'all_postponed': False
        }


def mark_as_backfilled(
    client: bigquery.Client,
    scraper_name: str,
    game_date: str,
    dry_run: bool = False
) -> bool:
    """
    Update backfilled=TRUE for this failure.

    Args:
        client: BigQuery client
        scraper_name: Name of the scraper
        game_date: Date to mark as backfilled
        dry_run: If True, don't actually update

    Returns:
        True if update succeeded (or would have in dry-run)
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would mark as backfilled: {scraper_name} / {game_date}")
        return True

    query = f"""
    UPDATE `{PROJECT_ID}.nba_orchestration.scraper_failures`
    SET
        backfilled = TRUE,
        backfilled_at = CURRENT_TIMESTAMP()
    WHERE scraper_name = @scraper_name
      AND game_date = @game_date
      AND backfilled = FALSE
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("scraper_name", "STRING", scraper_name),
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    try:
        result = client.query(query, job_config=job_config).result()
        logger.info(f"✅ Marked as backfilled: {scraper_name} / {game_date}")
        return True

    except Exception as e:
        logger.error(f"Failed to mark as backfilled {scraper_name}/{game_date}: {e}")
        return False


def cleanup_failures(
    client: bigquery.Client,
    days_back: int = 7,
    scraper_name: Optional[str] = None,
    dry_run: bool = False
) -> Dict:
    """
    Main cleanup logic - find and clean up successfully backfilled failures.

    Args:
        client: BigQuery client
        days_back: Number of days to look back
        scraper_name: Optional filter for specific scraper
        dry_run: If True, don't actually update records

    Returns:
        Dict with cleanup statistics
    """
    stats = {
        'total_failures': 0,
        'data_exists': 0,
        'all_postponed': 0,
        'still_missing': 0,
        'marked_backfilled': 0,
        'errors': 0
    }

    # Get all unbackfilled failures
    failures = get_unbackfilled_failures(client, days_back, scraper_name)
    stats['total_failures'] = len(failures)

    if not failures:
        logger.info("No unbackfilled failures to process")
        return stats

    logger.info(f"\nProcessing {len(failures)} unbackfilled failures...")
    logger.info("=" * 80)

    # Process each failure
    for failure in failures:
        scraper = failure['scraper_name']
        date = str(failure['game_date'])

        logger.info(f"\nChecking {scraper} / {date}:")
        logger.info(f"  Error: {failure['error_type']}")
        logger.info(f"  Retries: {failure['retry_count']}")
        logger.info(f"  Last failed: {failure['last_failed_at']}")

        # Check if data exists
        data_exists, record_count = check_if_data_exists(client, scraper, date)

        if data_exists:
            stats['data_exists'] += 1
            logger.info(f"  ✅ Data exists ({record_count} records) - marking as backfilled")

            if mark_as_backfilled(client, scraper, date, dry_run):
                stats['marked_backfilled'] += 1
            else:
                stats['errors'] += 1

        else:
            # No data - check if games were postponed
            game_status = check_game_status(client, date)

            if game_status['all_postponed']:
                stats['all_postponed'] += 1
                logger.info(f"  📅 All games postponed - marking as backfilled")

                if mark_as_backfilled(client, scraper, date, dry_run):
                    stats['marked_backfilled'] += 1
                else:
                    stats['errors'] += 1

            else:
                stats['still_missing'] += 1
                logger.info(f"  ❌ Data still missing ({game_status['finished_games']} games finished)")

    return stats


def print_summary(stats: Dict, dry_run: bool):
    """Print cleanup summary."""
    logger.info("\n" + "=" * 80)
    logger.info("CLEANUP SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total failures checked:       {stats['total_failures']}")
    logger.info(f"  ✅ Data exists:             {stats['data_exists']}")
    logger.info(f"  📅 All games postponed:     {stats['all_postponed']}")
    logger.info(f"  ❌ Still missing data:      {stats['still_missing']}")
    logger.info(f"  ⚠️  Errors:                  {stats['errors']}")
    logger.info("")

    if dry_run:
        logger.info(f"[DRY RUN] Would mark {stats['marked_backfilled']} failures as backfilled")
    else:
        logger.info(f"✅ Marked {stats['marked_backfilled']} failures as backfilled")

    logger.info("=" * 80)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Cleanup scraper failures that have been successfully backfilled',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be cleaned up without making changes'
    )
    parser.add_argument(
        '--days-back',
        type=int,
        default=7,
        help='Number of days to look back (default: 7)'
    )
    parser.add_argument(
        '--scraper',
        type=str,
        help='Only process failures for this scraper'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Print configuration
    logger.info("=" * 80)
    logger.info("SCRAPER FAILURE CLEANUP")
    logger.info("=" * 80)
    logger.info(f"Project:    {PROJECT_ID}")
    logger.info(f"Days back:  {args.days_back}")
    logger.info(f"Scraper:    {args.scraper or 'ALL'}")
    logger.info(f"Mode:       {'DRY RUN' if args.dry_run else 'PRODUCTION'}")
    logger.info("=" * 80)

    if args.dry_run:
        logger.info("\n⚠️  DRY RUN MODE - No changes will be made\n")

    try:
        # Initialize BigQuery client
        client = bigquery.Client(project=PROJECT_ID)

        # Run cleanup
        stats = cleanup_failures(
            client,
            days_back=args.days_back,
            scraper_name=args.scraper,
            dry_run=args.dry_run
        )

        # Print summary
        print_summary(stats, args.dry_run)

        # Exit with appropriate code
        if stats['errors'] > 0:
            logger.warning(f"Completed with {stats['errors']} errors")
            sys.exit(1)
        else:
            logger.info("✅ Cleanup completed successfully")
            sys.exit(0)

    except KeyboardInterrupt:
        logger.info("\n\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
