#!/usr/bin/env python3
"""
scripts/backfill_gamebooks.py

Backfill gamebook PDFs for missing dates.

This script was created after Session 165 discovered that gamebook data
was 4 days stale due to a bug in the parameter resolver.

Usage:
    PYTHONPATH=. python scripts/backfill_gamebooks.py --start-date 2025-12-22 --end-date 2025-12-23
    PYTHONPATH=. python scripts/backfill_gamebooks.py --date 2025-12-22
    PYTHONPATH=. python scripts/backfill_gamebooks.py --date 2025-12-22 --dry-run
"""

import argparse
import logging
import sys
from datetime import datetime, date, timedelta
from typing import List

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


def run_gamebook_scraper(game_code: str, dry_run: bool = False) -> bool:
    """Run gamebook scraper for a specific game."""
    from scrapers.nbacom.nbac_gamebook_pdf import GetNbaComGamebookPdf

    if dry_run:
        logger.info(f"[DRY RUN] Would scrape gamebook: {game_code}")
        return True

    try:
        logger.info(f"Scraping gamebook: {game_code}")
        scraper = GetNbaComGamebookPdf()
        result = scraper.run({
            'game_code': game_code,
            'group': 'prod',
            'debug': False
        })

        if result:
            logger.info(f"✅ Successfully scraped: {game_code}")
            return True
        else:
            logger.warning(f"⚠️  Scraper returned False for: {game_code}")
            return False

    except Exception as e:
        logger.error(f"❌ Failed to scrape {game_code}: {e}")
        return False


def backfill_date(target_date: str, dry_run: bool = False) -> dict:
    """Backfill all gamebooks for a specific date."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Processing date: {target_date}")
    logger.info(f"{'='*60}")

    games = get_games_for_date(target_date)

    if not games:
        logger.warning(f"No final games found for {target_date}")
        return {'date': target_date, 'total': 0, 'success': 0, 'failed': 0}

    logger.info(f"Found {len(games)} final games")

    results = {'date': target_date, 'total': len(games), 'success': 0, 'failed': 0}

    for game in games:
        game_code = build_game_code(game)
        matchup = f"{game['away_team']} @ {game['home_team']}"

        logger.info(f"\nGame: {matchup}")
        logger.info(f"Code: {game_code}")

        if run_gamebook_scraper(game_code, dry_run):
            results['success'] += 1
        else:
            results['failed'] += 1

    return results


def main():
    parser = argparse.ArgumentParser(description='Backfill gamebook PDFs')

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--date', type=str, help='Single date to backfill (YYYY-MM-DD)')
    group.add_argument('--start-date', type=str, help='Start date for range (YYYY-MM-DD)')

    parser.add_argument('--end-date', type=str, help='End date for range (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without executing')

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

    # Process each date
    all_results = []
    for target_date in dates:
        result = backfill_date(target_date, args.dry_run)
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
