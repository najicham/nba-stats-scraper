#!/usr/bin/env python3
"""
scripts/check_data_completeness.py

Check data completeness for overnight collection.
Compares scheduled games vs actual data collected.

Run after post_game_window_3 (4 AM ET) to verify overnight collection.

Usage:
    PYTHONPATH=. python scripts/check_data_completeness.py
    PYTHONPATH=. python scripts/check_data_completeness.py --date 2025-12-27
    PYTHONPATH=. python scripts/check_data_completeness.py --days 7

Created after Session 180 incident where only 1/9 gamebooks were collected.
"""

import argparse
import logging
import sys
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
import pytz

from shared.utils.bigquery_utils import execute_bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ET = pytz.timezone('America/New_York')


def get_scheduled_games(target_date: str) -> List[Dict]:
    """Get all final games for a date from schedule."""
    query = f"""
        SELECT
            game_id,
            home_team_tricode,
            away_team_tricode,
            game_status
        FROM nba_raw.nbac_schedule
        WHERE game_date = '{target_date}'
        AND game_status = 3  -- Final
        ORDER BY game_id
    """
    return execute_bigquery(query) or []


def get_gamebook_count(target_date: str) -> int:
    """Get count of games with gamebook data."""
    query = f"""
        SELECT COUNT(DISTINCT game_id) as count
        FROM nba_raw.nbac_gamebook_player_stats
        WHERE game_date = '{target_date}'
    """
    results = execute_bigquery(query) or []
    return results[0]['count'] if results else 0


def get_boxscore_count(target_date: str) -> int:
    """Get count of games with box score data."""
    query = f"""
        SELECT COUNT(DISTINCT game_id) as count
        FROM nba_raw.bdl_player_boxscores
        WHERE game_date = '{target_date}'
    """
    results = execute_bigquery(query) or []
    return results[0]['count'] if results else 0


def get_bettingpros_props_count(target_date: str) -> int:
    """Get count of BettingPros player props for a date."""
    query = f"""
        SELECT COUNT(*) as count
        FROM nba_raw.bettingpros_player_points_props
        WHERE game_date = '{target_date}'
    """
    results = execute_bigquery(query) or []
    return results[0]['count'] if results else 0


def check_completeness(target_date: str) -> Dict:
    """
    Check data completeness for a specific date.

    Note: Game IDs differ between tables (schedule uses NBA API format,
    gamebooks use date_team_team format), so we compare by count only.

    Returns dict with:
        - scheduled_count: number of final games scheduled
        - gamebook_count: number of games with gamebook data
        - boxscore_count: number of games with box score data
        - is_complete: True if all data present
    """
    logger.info(f"Checking completeness for {target_date}")

    # Get scheduled final games
    scheduled = get_scheduled_games(target_date)
    scheduled_count = len(scheduled)

    if scheduled_count == 0:
        logger.info(f"  No final games found for {target_date}")
        return {
            'date': target_date,
            'scheduled_count': 0,
            'scheduled_games': [],
            'gamebook_count': 0,
            'boxscore_count': 0,
            'bettingpros_count': 0,
            'is_complete': True,  # No games = complete
            'gamebook_pct': 100.0,
            'boxscore_pct': 100.0,
            'bettingpros_ok': True,
        }

    # Get collected data counts
    gamebook_count = get_gamebook_count(target_date)
    boxscore_count = get_boxscore_count(target_date)
    bettingpros_count = get_bettingpros_props_count(target_date)

    # Calculate percentages
    gamebook_pct = 100.0 * gamebook_count / scheduled_count
    boxscore_pct = 100.0 * boxscore_count / scheduled_count

    # BettingPros: expect at least 150 props per game (rough heuristic)
    min_expected_props = scheduled_count * 150
    bettingpros_ok = bettingpros_count >= min_expected_props

    is_complete = (gamebook_count >= scheduled_count and
                   boxscore_count >= scheduled_count)

    return {
        'date': target_date,
        'scheduled_count': scheduled_count,
        'scheduled_games': scheduled,
        'gamebook_count': gamebook_count,
        'boxscore_count': boxscore_count,
        'bettingpros_count': bettingpros_count,
        'bettingpros_expected': min_expected_props,
        'bettingpros_ok': bettingpros_ok,
        'is_complete': is_complete,
        'gamebook_pct': gamebook_pct,
        'boxscore_pct': boxscore_pct,
    }


def format_game(game: Dict) -> str:
    """Format game for display."""
    away = game.get('away_team_tricode', '???')
    home = game.get('home_team_tricode', '???')
    game_id = game.get('game_id', '???')
    return f"{away}@{home} ({game_id})"


def print_report(result: Dict) -> None:
    """Print completeness report."""
    date_str = result['date']
    scheduled_count = result['scheduled_count']
    gamebook_count = result['gamebook_count']
    boxscore_count = result['boxscore_count']
    gb_pct = result['gamebook_pct']
    bs_pct = result['boxscore_pct']

    print(f"\n{'='*60}")
    print(f"Data Completeness Report: {date_str}")
    print(f"{'='*60}")

    print(f"\nScheduled final games: {scheduled_count}")

    # Gamebooks
    gb_status = "✅" if gb_pct >= 100 else "❌"
    print(f"\nGamebooks: {gamebook_count}/{scheduled_count} ({gb_pct:.0f}%) {gb_status}")
    if gamebook_count < scheduled_count:
        print(f"  ⚠️  Missing {scheduled_count - gamebook_count} gamebook(s)")

    # Box scores
    bs_status = "✅" if bs_pct >= 100 else "❌"
    print(f"\nBox Scores: {boxscore_count}/{scheduled_count} ({bs_pct:.0f}%) {bs_status}")
    if boxscore_count < scheduled_count:
        print(f"  ⚠️  Missing {scheduled_count - boxscore_count} box score(s)")

    # BettingPros props
    bp_count = result.get('bettingpros_count', 0)
    bp_expected = result.get('bettingpros_expected', 0)
    bp_ok = result.get('bettingpros_ok', True)
    bp_status = "✅" if bp_ok else "⚠️"
    print(f"\nBettingPros Props: {bp_count:,} (expected ≥{bp_expected:,}) {bp_status}")
    if not bp_ok:
        print(f"  ⚠️  Props count below expected - may need recovery")
        print(f"  Run: PYTHONPATH=. python scripts/betting_props_recovery.py --date {date_str}")

    # Overall
    if result['is_complete']:
        print(f"\n✅ ALL DATA COMPLETE for {date_str}")
    else:
        print(f"\n❌ DATA INCOMPLETE for {date_str}")
        if gamebook_count < scheduled_count:
            print("\nTo backfill gamebooks:")
            print(f"  PYTHONPATH=. python scripts/backfill_gamebooks.py --date {date_str}")


def main():
    parser = argparse.ArgumentParser(description='Check data completeness')
    parser.add_argument('--date', type=str, help='Specific date (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, default=1, help='Number of days to check (default: 1 = yesterday)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    # Determine dates to check
    if args.date:
        dates = [args.date]
    else:
        # Default: check yesterday (for overnight collection)
        today = datetime.now(ET).date()
        dates = [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(1, args.days + 1)]

    print("\n" + "="*60)
    print("DATA COMPLETENESS CHECK")
    print("="*60)
    print(f"Dates to check: {dates}")

    all_complete = True
    results = []

    for target_date in dates:
        result = check_completeness(target_date)
        results.append(result)
        print_report(result)

        if not result['is_complete']:
            all_complete = False

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    for r in results:
        status = "✅" if r['is_complete'] else "❌"
        print(f"  {r['date']}: Gamebooks {r['gamebook_pct']:.0f}%, Box Scores {r['boxscore_pct']:.0f}% {status}")

    if all_complete:
        print("\n✅ All dates have complete data")
        sys.exit(0)
    else:
        print("\n❌ Some dates have incomplete data - see above for details")
        sys.exit(1)


if __name__ == '__main__':
    main()
