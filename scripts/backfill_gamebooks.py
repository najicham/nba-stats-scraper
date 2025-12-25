#!/usr/bin/env python3
"""
scripts/backfill_gamebooks.py

Backfill gamebook PDFs for missing dates.

This script was created after Session 165 discovered that gamebook data
was 4 days stale due to a bug in the parameter resolver.

IMPORTANT (Session 166 fix):
- This script now directly invokes Phase 2 processor after scraping
- This bypasses Pub/Sub which was dropping messages during bulk backfills
- Each game is: scraped → saved to GCS → processed directly to BigQuery

Usage:
    PYTHONPATH=. python scripts/backfill_gamebooks.py --start-date 2025-12-22 --end-date 2025-12-23
    PYTHONPATH=. python scripts/backfill_gamebooks.py --date 2025-12-22
    PYTHONPATH=. python scripts/backfill_gamebooks.py --date 2025-12-22 --dry-run
    PYTHONPATH=. python scripts/backfill_gamebooks.py --date 2025-12-22 --skip-scrape  # Only run Phase 2
"""

import argparse
import logging
import sys
import time
from datetime import datetime, date, timedelta
from typing import List, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_games_for_date(target_date: str) -> List[dict]:
    """Get final games for a specific date from BigQuery.

    game_status values:
    - 1 = Scheduled
    - 2 = In Progress
    - 3 = Final
    """
    from shared.utils.bigquery_utils import execute_bigquery

    query = f"""
        SELECT
            game_id,
            game_date,
            home_team_tricode as home_team,
            away_team_tricode as away_team,
            game_status
        FROM nba_reference.nba_schedule
        WHERE game_date = '{target_date}'
        AND game_status = 3  -- Final
        ORDER BY game_id
    """

    games = execute_bigquery(query)
    return games or []


def build_game_code(game: dict) -> str:
    """Build game_code in format YYYYMMDD/AWAYHOME."""
    game_date = game['game_date']
    if isinstance(game_date, str):
        date_str = game_date.replace('-', '')
    else:
        date_str = game_date.strftime('%Y%m%d')

    away_team = game['away_team'][:3].upper()
    home_team = game['home_team'][:3].upper()

    return f"{date_str}/{away_team}{home_team}"


def get_gcs_path_for_game(game_code: str) -> Optional[str]:
    """
    Get the GCS file path for a game's gamebook data.

    Args:
        game_code: Game code like "20251222/CHACLE"

    Returns:
        GCS path like "nba-com/gamebooks-data/2025-12-22/20251222-CHACLE/..." or None
    """
    from google.cloud import storage

    # Parse game_code to get date and teams
    # game_code format: "20251222/CHACLE" -> date=2025-12-22, teams=CHACLE
    parts = game_code.split('/')
    if len(parts) != 2:
        logger.error(f"Invalid game_code format: {game_code}")
        return None

    date_str = parts[0]  # "20251222"
    teams = parts[1]     # "CHACLE"

    # Convert to path format
    formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    game_folder = f"{date_str}-{teams}"

    # List files in the game folder
    bucket_name = "nba-scraped-data"
    prefix = f"nba-com/gamebooks-data/{formatted_date}/{game_folder}/"

    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix=prefix))

        # Find the JSON data file (not the PDF)
        for blob in blobs:
            if blob.name.endswith('.json') and 'data' not in blob.name.lower():
                # This is likely the parsed data file
                return blob.name
            elif blob.name.endswith('.json'):
                return blob.name

        # If no JSON found, check for any file
        if blobs:
            for blob in blobs:
                if blob.name.endswith('.json'):
                    return blob.name

        logger.warning(f"No JSON file found in {prefix}")
        return None

    except Exception as e:
        logger.error(f"Error listing GCS: {e}")
        return None


def run_phase2_processor(gcs_path: str, dry_run: bool = False) -> bool:
    """
    Directly run Phase 2 processor to load GCS data into BigQuery.

    This bypasses Pub/Sub to ensure reliable backfill processing.
    """
    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor

    if dry_run:
        logger.info(f"[DRY RUN] Would process: {gcs_path}")
        return True

    try:
        logger.info(f"  → Phase 2: Processing {gcs_path}")
        processor = NbacGamebookProcessor()

        # Set up the processor with the GCS file path
        processor.opts = {
            'file_path': gcs_path,
            'bucket': 'nba-scraped-data',
            'backfill_mode': True,  # Skip freshness checks
            'project_id': 'nba-props-platform'
        }

        # Initialize GCS and BigQuery clients
        processor.init_clients()

        # Run the processor pipeline
        processor.load_data()
        processor.transform_data()
        processor.save_data()

        logger.info(f"  ✅ Phase 2 complete: {gcs_path}")
        return True

    except Exception as e:
        logger.error(f"  ❌ Phase 2 failed for {gcs_path}: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_gamebook_scraper(game_code: str, dry_run: bool = False, skip_scrape: bool = False) -> bool:
    """
    Run gamebook scraper for a specific game, then directly process to BigQuery.

    Args:
        game_code: Game code like "20251222/CHACLE"
        dry_run: If True, just log what would be done
        skip_scrape: If True, skip Phase 1 and only run Phase 2 (for re-processing)

    Returns:
        True if both scraping and processing succeeded
    """
    from scrapers.nbacom.nbac_gamebook_pdf import GetNbaComGamebookPdf

    if dry_run:
        logger.info(f"[DRY RUN] Would scrape and process gamebook: {game_code}")
        return True

    # Phase 1: Scrape (unless skipped)
    if not skip_scrape:
        try:
            logger.info(f"  → Phase 1: Scraping {game_code}")
            scraper = GetNbaComGamebookPdf()
            result = scraper.run({
                'game_code': game_code,
                'group': 'prod',
                'debug': False
            })

            if not result:
                logger.warning(f"  ⚠️ Scraper returned False for: {game_code}")
                return False

            logger.info(f"  ✅ Phase 1 complete: {game_code}")

            # Small delay to ensure GCS write is visible
            time.sleep(0.5)

        except Exception as e:
            logger.error(f"  ❌ Phase 1 failed for {game_code}: {e}")
            return False

    # Phase 2: Direct processing to BigQuery
    gcs_path = get_gcs_path_for_game(game_code)
    if not gcs_path:
        logger.error(f"  ❌ Could not find GCS path for: {game_code}")
        return False

    return run_phase2_processor(gcs_path, dry_run)


def backfill_date(target_date: str, dry_run: bool = False, skip_scrape: bool = False) -> dict:
    """
    Backfill all gamebooks for a specific date.

    Args:
        target_date: Date in YYYY-MM-DD format
        dry_run: If True, just log what would be done
        skip_scrape: If True, skip Phase 1 and only run Phase 2 (data already in GCS)

    Returns:
        Dict with date, total, success, failed counts
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"Processing date: {target_date}")
    if skip_scrape:
        logger.info(f"Mode: PHASE 2 ONLY (skipping scrape, processing existing GCS data)")
    else:
        logger.info(f"Mode: FULL (scrape + process)")
    logger.info(f"{'='*60}")

    games = get_games_for_date(target_date)

    if not games:
        logger.warning(f"No final games found for {target_date}")
        return {'date': target_date, 'total': 0, 'success': 0, 'failed': 0}

    logger.info(f"Found {len(games)} final games")

    results = {'date': target_date, 'total': len(games), 'success': 0, 'failed': 0}

    for i, game in enumerate(games, 1):
        game_code = build_game_code(game)
        matchup = f"{game['away_team']} @ {game['home_team']}"

        logger.info(f"\n[{i}/{len(games)}] {matchup}")
        logger.info(f"Code: {game_code}")

        if run_gamebook_scraper(game_code, dry_run, skip_scrape):
            results['success'] += 1
        else:
            results['failed'] += 1

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Backfill gamebook PDFs with direct BigQuery processing',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full backfill (scrape + process to BigQuery):
  PYTHONPATH=. python scripts/backfill_gamebooks.py --start-date 2025-12-22 --end-date 2025-12-23

  # Re-process existing GCS data (skip scraping, just run Phase 2):
  PYTHONPATH=. python scripts/backfill_gamebooks.py --date 2025-12-22 --skip-scrape

  # Dry run to see what would be processed:
  PYTHONPATH=. python scripts/backfill_gamebooks.py --date 2025-12-22 --dry-run
        """
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--date', type=str, help='Single date to backfill (YYYY-MM-DD)')
    group.add_argument('--start-date', type=str, help='Start date for range (YYYY-MM-DD)')

    parser.add_argument('--end-date', type=str, help='End date for range (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without executing')
    parser.add_argument('--skip-scrape', action='store_true',
                        help='Skip Phase 1 scraping, only run Phase 2 processing (for re-processing existing GCS data)')

    args = parser.parse_args()

    # Determine dates to process
    if args.date:
        dates = [args.date]
    else:
        if not args.end_date:
            parser.error("--end-date is required when using --start-date")

        start = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end = datetime.strptime(args.end_date, '%Y-%m-%d').date()

        dates = []
        current = start
        while current <= end:
            dates.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)

    logger.info(f"Gamebook Backfill")
    logger.info(f"================")
    logger.info(f"Dates: {dates}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Skip scrape (Phase 2 only): {args.skip_scrape}")

    # Process each date
    all_results = []
    for target_date in dates:
        result = backfill_date(target_date, args.dry_run, args.skip_scrape)
        all_results.append(result)

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY")
    logger.info(f"{'='*60}")

    total_games = sum(r['total'] for r in all_results)
    total_success = sum(r['success'] for r in all_results)
    total_failed = sum(r['failed'] for r in all_results)

    for r in all_results:
        status = "✅" if r['failed'] == 0 and r['success'] > 0 else "⚠️" if r['success'] > 0 else "❌"
        logger.info(f"  {r['date']}: {status} {r['success']}/{r['total']} succeeded")

    logger.info(f"\nTotal: {total_success}/{total_games} succeeded, {total_failed} failed")

    if total_failed > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
