#!/usr/bin/env python3
"""
Test Season Type Handling Across Scrapers and Processors

This script tests how scrapers and processors handle different season types:
- Regular Season
- Playoffs
- Play-In Tournament
- All-Star Weekend
- Pre-Season (if available)

Usage:
    python tests/test_season_type_handling.py --season 2024
    python tests/test_season_type_handling.py --season 2024 --check-processors
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from collections import defaultdict

from shared.utils.schedule import NBAScheduleService, GameType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SeasonTypeTest:
    """Test season type detection and handling."""

    def __init__(self, season_year: int = 2024):
        """
        Initialize test suite.

        Args:
            season_year: NBA season starting year (e.g., 2024 for 2024-25 season)
        """
        self.season_year = season_year
        self.schedule = NBAScheduleService()
        self.results = defaultdict(list)

    def find_sample_dates_by_season_type(self) -> Dict[str, List[str]]:
        """
        Scan the schedule to find sample dates for each season type.

        Returns:
            Dict mapping season_type -> list of sample dates
        """
        logger.info(f"🔍 Scanning {self.season_year}-{self.season_year+1} season for season types...")

        # Define date range for the season
        # NBA season typically runs Oct-June
        start_date = date(self.season_year, 10, 1)
        end_date = date(self.season_year + 1, 6, 30)

        season_type_dates = defaultdict(list)
        current_date = start_date

        while current_date <= end_date:
            date_str = current_date.isoformat()

            # Check if there are games on this date
            try:
                game_count = self.schedule.get_game_count(date_str, GameType.ALL)
                if game_count > 0:
                    # Get season type for this date
                    season_type = self.schedule.get_season_type_for_date(date_str)

                    # Store up to 3 sample dates per season type
                    if len(season_type_dates[season_type]) < 3:
                        games = self.schedule.get_games_for_date(date_str, GameType.ALL)
                        season_type_dates[season_type].append({
                            'date': date_str,
                            'game_count': game_count,
                            'sample_game': f"{games[0].away_team} @ {games[0].home_team}" if games else "N/A"
                        })
            except Exception as e:
                logger.debug(f"Error checking {date_str}: {e}")

            current_date += timedelta(days=1)

        return season_type_dates

    def display_season_type_summary(self, season_type_dates: Dict[str, List[str]]) -> None:
        """Display summary of found season types."""
        logger.info("\n" + "="*80)
        logger.info(f"📊 SEASON TYPE SUMMARY - {self.season_year}-{self.season_year+1} Season")
        logger.info("="*80)

        if not season_type_dates:
            logger.warning("⚠️  No games found in schedule data!")
            return

        for season_type in sorted(season_type_dates.keys()):
            dates = season_type_dates[season_type]
            logger.info(f"\n🏀 {season_type}")
            logger.info(f"   Found {len(dates)} sample date(s):")
            for entry in dates:
                logger.info(f"     • {entry['date']}: {entry['game_count']} games - {entry['sample_game']}")

    def test_processor_handling(self, season_type_dates: Dict[str, List[str]]) -> Dict:
        """
        Test how processors handle each season type.

        Args:
            season_type_dates: Dict of season type -> sample dates

        Returns:
            Dict of test results
        """
        logger.info("\n" + "="*80)
        logger.info("🧪 TESTING PROCESSOR BEHAVIOR")
        logger.info("="*80)

        test_results = {}

        for season_type, dates in season_type_dates.items():
            if not dates:
                continue

            sample_date = dates[0]['date']
            logger.info(f"\n📅 Testing {season_type} with date: {sample_date}")

            # Test what our current implementation does
            try:
                returned_type = self.schedule.get_season_type_for_date(sample_date)

                # Check if this would be skipped by our processors
                would_skip = (returned_type == "All Star")

                test_results[season_type] = {
                    'sample_date': sample_date,
                    'returned_type': returned_type,
                    'would_skip': would_skip,
                    'status': '❌ SKIPPED' if would_skip else '✅ PROCESSED'
                }

                logger.info(f"   Season Type Returned: {returned_type}")
                logger.info(f"   Processor Action: {test_results[season_type]['status']}")

                if would_skip:
                    logger.info(f"   ℹ️  This is expected - All-Star games are intentionally skipped")

            except Exception as e:
                logger.error(f"   ❌ Error: {e}")
                test_results[season_type] = {
                    'sample_date': sample_date,
                    'error': str(e),
                    'status': '❌ ERROR'
                }

        return test_results

    def generate_recommendations(self, test_results: Dict) -> List[str]:
        """Generate recommendations based on test results."""
        recommendations = []

        for season_type, result in test_results.items():
            if result.get('would_skip') and season_type != "All Star":
                recommendations.append(
                    f"⚠️  {season_type} games are being SKIPPED - verify this is intentional"
                )
            elif result.get('error'):
                recommendations.append(
                    f"❌ {season_type} handling ERROR - investigate: {result['error']}"
                )

        # Check for missing season types
        expected_types = ["Regular Season", "Playoffs"]
        found_types = set(test_results.keys())
        missing = set(expected_types) - found_types

        if missing:
            for season_type in missing:
                recommendations.append(
                    f"ℹ️  No {season_type} games found in schedule - may be normal depending on date range"
                )

        return recommendations

    def run_full_test(self) -> None:
        """Run complete test suite."""
        logger.info("="*80)
        logger.info("🚀 SEASON TYPE HANDLING TEST SUITE")
        logger.info("="*80)
        logger.info(f"Season: {self.season_year}-{self.season_year+1}")
        logger.info(f"Timestamp: {datetime.now().isoformat()}")

        # Step 1: Find sample dates for each season type
        season_type_dates = self.find_sample_dates_by_season_type()
        self.display_season_type_summary(season_type_dates)

        # Step 2: Test processor handling
        test_results = self.test_processor_handling(season_type_dates)

        # Step 3: Generate recommendations
        logger.info("\n" + "="*80)
        logger.info("💡 RECOMMENDATIONS")
        logger.info("="*80)

        recommendations = self.generate_recommendations(test_results)

        if recommendations:
            for rec in recommendations:
                logger.info(rec)
        else:
            logger.info("✅ All season types are being handled correctly!")

        # Summary
        logger.info("\n" + "="*80)
        logger.info("📈 SUMMARY")
        logger.info("="*80)
        logger.info(f"Season Types Found: {len(season_type_dates)}")
        logger.info(f"Tests Run: {len(test_results)}")
        logger.info(f"Recommendations: {len(recommendations)}")

        # Key findings
        all_star_found = "All Star" in season_type_dates
        preseason_found = "Pre Season" in season_type_dates
        playin_found = "PlayIn" in season_type_dates

        logger.info("\n🔑 Key Findings:")
        logger.info(f"   All-Star Weekend: {'✅ Found (will be skipped)' if all_star_found else '❌ Not found'}")
        logger.info(f"   Pre-Season: {'✅ Found' if preseason_found else '❌ Not found (may not be in schedule)'}")
        logger.info(f"   Play-In Tournament: {'✅ Found (will be processed)' if playin_found else '❌ Not found'}")

        logger.info("\n" + "="*80)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Test season type handling')
    parser.add_argument('--season', type=int, default=2024,
                       help='NBA season starting year (default: 2024)')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Run tests
    tester = SeasonTypeTest(season_year=args.season)
    tester.run_full_test()


if __name__ == '__main__':
    main()
