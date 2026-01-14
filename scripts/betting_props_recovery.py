#!/usr/bin/env python3
"""
scripts/betting_props_recovery.py

BettingPros Props Recovery - Auto-recovery for missing player props

This script checks if BettingPros player props exist for today's games.
If games are scheduled but props are missing, it triggers the bp_player_props
scraper for all market types.

Run this via Cloud Scheduler at 3 PM, 6 PM, 9 PM ET to ensure props are captured.

Usage:
    PYTHONPATH=. python scripts/betting_props_recovery.py
    PYTHONPATH=. python scripts/betting_props_recovery.py --date 2026-01-12
    PYTHONPATH=. python scripts/betting_props_recovery.py --dry-run
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional

import pytz
import requests

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.utils.bigquery_utils import execute_bigquery
from shared.utils.notification_system import notify_info, notify_warning, notify_error

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
SCRAPER_SERVICE_URL = os.environ.get(
    'SCRAPER_SERVICE_URL',
    'https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app'
)
MARKET_TYPES = ['points', 'rebounds', 'assists', 'threes', 'steals', 'blocks']
MIN_EXPECTED_PROPS = 1000  # Minimum props expected per game date with games


class BettingPropsRecovery:
    """
    Checks for and recovers missing BettingPros player props data.
    """

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.ET = pytz.timezone('America/New_York')

    def get_today_date(self) -> str:
        """Get today's date in ET timezone."""
        return datetime.now(self.ET).strftime('%Y-%m-%d')

    def check_games_scheduled(self, date: str) -> int:
        """
        Check how many games are scheduled for the given date.

        Returns:
            Number of games scheduled
        """
        query = f"""
        SELECT COUNT(DISTINCT game_id) as game_count
        FROM `nba-props-platform.nba_raw.nbac_schedule`
        WHERE game_date = '{date}'
        """
        try:
            result = execute_bigquery(query)
            if result and len(result) > 0:
                return result[0].get('game_count', 0)
        except Exception as e:
            logger.warning(f"Failed to check schedule: {e}")
        return 0

    def check_props_exist(self, date: str) -> int:
        """
        Check how many BettingPros props exist for the given date.

        Returns:
            Number of props records
        """
        query = f"""
        SELECT COUNT(*) as prop_count
        FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
        WHERE game_date = '{date}'
        """
        try:
            result = execute_bigquery(query)
            if result and len(result) > 0:
                return result[0].get('prop_count', 0)
        except Exception as e:
            logger.warning(f"Failed to check props: {e}")
        return 0

    def trigger_scraper(self, date: str, market_type: str) -> Dict[str, Any]:
        """
        Trigger the bp_player_props scraper for a specific market type.

        Returns:
            Scraper response dict
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would trigger bp_player_props for {date}, market={market_type}")
            return {'status': 'dry_run', 'market_type': market_type}

        url = f"{SCRAPER_SERVICE_URL}/scrape"
        payload = {
            'scraper': 'bp_player_props',
            'date': date,
            'sport': 'NBA',
            'market_type': market_type,
            'group': 'prod'
        }

        try:
            response = requests.post(url, json=payload, timeout=180)
            response.raise_for_status()
            result = response.json()
            logger.info(f"✅ Triggered {market_type}: status={result.get('status')}, "
                       f"props={result.get('data_summary', {}).get('props_count', 'N/A')}")
            return result
        except Exception as e:
            logger.error(f"❌ Failed to trigger {market_type}: {e}")
            return {'status': 'error', 'error': str(e), 'market_type': market_type}

    def run(self, date: Optional[str] = None) -> Dict[str, Any]:
        """
        Main recovery check.

        Args:
            date: Date to check (defaults to today in ET)

        Returns:
            Summary dict with check results and any recovery actions taken
        """
        target_date = date or self.get_today_date()

        logger.info("=" * 60)
        logger.info("🔍 BettingPros Props Recovery Check")
        logger.info(f"   Date: {target_date}")
        logger.info(f"   Dry Run: {self.dry_run}")
        logger.info("=" * 60)

        # Check games scheduled
        games_count = self.check_games_scheduled(target_date)
        logger.info(f"📅 Games scheduled for {target_date}: {games_count}")

        if games_count == 0:
            logger.info("✅ No games scheduled, nothing to recover")
            return {
                'date': target_date,
                'games_scheduled': 0,
                'props_count': 0,
                'action': 'none',
                'reason': 'no_games_scheduled'
            }

        # Check props exist
        props_count = self.check_props_exist(target_date)
        logger.info(f"📊 BettingPros props for {target_date}: {props_count}")

        # Determine if recovery needed
        # Expect at least 1000 props per game date (rough heuristic)
        min_expected = games_count * 150  # ~150 props per game minimum

        if props_count >= min_expected:
            logger.info(f"✅ Props count ({props_count}) meets minimum expected ({min_expected})")
            return {
                'date': target_date,
                'games_scheduled': games_count,
                'props_count': props_count,
                'action': 'none',
                'reason': 'sufficient_props'
            }

        # Props missing or insufficient - trigger recovery
        logger.warning(f"⚠️ Props count ({props_count}) below expected ({min_expected}) - triggering recovery")

        # Notify about recovery
        try:
            notify_warning(
                title="BettingPros Props Recovery Triggered",
                message=f"Auto-recovering missing props for {target_date}",
                details={
                    'date': target_date,
                    'games_scheduled': games_count,
                    'props_found': props_count,
                    'min_expected': min_expected,
                    'market_types': MARKET_TYPES
                }
            )
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

        # Trigger all market types
        results = []
        for market_type in MARKET_TYPES:
            result = self.trigger_scraper(target_date, market_type)
            results.append(result)

        # Summary
        successes = sum(1 for r in results if r.get('status') == 'success')
        failures = sum(1 for r in results if r.get('status') == 'error')

        logger.info("=" * 60)
        logger.info(f"📊 Recovery Summary: {successes}/{len(MARKET_TYPES)} succeeded, {failures} failed")
        logger.info("=" * 60)

        # Send summary notification
        try:
            if failures > 0:
                notify_error(
                    title="BettingPros Recovery Partial Failure",
                    message=f"Recovery for {target_date}: {successes}/{len(MARKET_TYPES)} succeeded",
                    details={'date': target_date, 'results': results}
                )
            else:
                notify_info(
                    title="BettingPros Recovery Complete",
                    message=f"Successfully recovered all {len(MARKET_TYPES)} market types for {target_date}",
                    details={'date': target_date, 'successes': successes}
                )
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

        return {
            'date': target_date,
            'games_scheduled': games_count,
            'props_count': props_count,
            'action': 'recovery_triggered',
            'market_types': MARKET_TYPES,
            'results': results,
            'successes': successes,
            'failures': failures
        }


def main():
    parser = argparse.ArgumentParser(description='BettingPros Props Recovery')
    parser.add_argument('--date', type=str, help='Date to check (YYYY-MM-DD), defaults to today')
    parser.add_argument('--dry-run', action='store_true', help='Check only, do not trigger scrapers')
    args = parser.parse_args()

    recovery = BettingPropsRecovery(dry_run=args.dry_run)
    result = recovery.run(date=args.date)

    # Exit with error code if recovery failed
    if result.get('failures', 0) > 0:
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()
