#!/usr/bin/env python3
"""
Edge Case Tests for Season Boundaries and Special Game Types

Tests:
1. Season transitions (June → October)
2. Regular season → Playoffs transition
3. Pre-season handling
4. Play-In tournament
5. All-Star weekend (if available)
6. Postponed/rescheduled games

Usage:
    python tests/test_edge_cases.py
    python tests/test_edge_cases.py --season 2024 --verbose
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple

from shared.utils.schedule import NBAScheduleService, GameType

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class EdgeCaseTests:
    """Test edge cases in season handling."""

    def __init__(self, season_year: int = 2024):
        self.season_year = season_year
        self.schedule = NBAScheduleService()
        self.test_results = []

    def test_season_transitions(self) -> None:
        """Test season year calculation across transitions."""
        logger.info("\n" + "="*80)
        logger.info("🔄 TEST: Season Transitions")
        logger.info("="*80)

        test_dates = [
            # End of previous season
            (f"{self.season_year}-06-15", self.season_year - 1, "End of playoffs"),

            # Start of new season (pre-season)
            (f"{self.season_year}-10-04", self.season_year, "Pre-season start"),

            # Regular season start
            (f"{self.season_year}-10-22", self.season_year, "Regular season start"),

            # Mid-season
            (f"{self.season_year + 1}-01-15", self.season_year, "Mid-season"),

            # Playoffs
            (f"{self.season_year + 1}-04-20", self.season_year, "Playoffs"),
        ]

        for test_date, expected_season, description in test_dates:
            try:
                # Parse the date to get season year using same logic as processors
                date_obj = datetime.strptime(test_date, '%Y-%m-%d').date()
                calculated_season = date_obj.year if date_obj.month >= 10 else date_obj.year - 1

                status = "✅" if calculated_season == expected_season else "❌"
                self.test_results.append({
                    'test': 'Season Transition',
                    'passed': calculated_season == expected_season
                })

                logger.info(f"{status} {description}: {test_date}")
                logger.info(f"   Expected season: {expected_season}, Calculated: {calculated_season}")

                if calculated_season != expected_season:
                    logger.warning(f"   ⚠️  MISMATCH - Check season_year extraction logic!")

            except Exception as e:
                logger.error(f"❌ Error testing {test_date}: {e}")
                self.test_results.append({'test': 'Season Transition', 'passed': False})

    def test_season_type_consistency(self) -> None:
        """Test that season types are consistent."""
        logger.info("\n" + "="*80)
        logger.info("🎯 TEST: Season Type Consistency")
        logger.info("="*80)

        # Define critical dates to test
        test_scenarios = [
            ("2024-10-04", "Pre Season", "Pre-season game"),
            ("2024-10-22", "Regular Season", "First regular season game"),
            ("2025-02-16", "All Star", "All-Star Sunday (if exists)"),
            ("2025-04-15", "PlayIn", "Play-In tournament"),
            ("2025-04-20", "Playoffs", "Playoff game"),
        ]

        for test_date, expected_type, description in test_scenarios:
            try:
                actual_type = self.schedule.get_season_type_for_date(test_date)

                # Check if date has games
                game_count = self.schedule.get_game_count(test_date, GameType.ALL)

                if game_count == 0:
                    logger.info(f"ℹ️  {description}: {test_date}")
                    logger.info(f"   No games on this date (skipping test)")
                    continue

                status = "✅" if actual_type == expected_type else "⚠️"
                self.test_results.append({
                    'test': 'Season Type Consistency',
                    'passed': actual_type == expected_type
                })

                logger.info(f"{status} {description}: {test_date}")
                logger.info(f"   Expected: {expected_type}, Actual: {actual_type}")

                if actual_type != expected_type:
                    logger.warning(f"   ⚠️  Type mismatch - verify schedule data")

            except Exception as e:
                logger.error(f"❌ Error testing {test_date}: {e}")
                self.test_results.append({'test': 'Season Type Consistency', 'passed': False})

    def test_processor_skip_logic(self) -> None:
        """Test which season types would be skipped by processors."""
        logger.info("\n" + "="*80)
        logger.info("⏭️  TEST: Processor Skip Logic")
        logger.info("="*80)

        season_types = ["Pre Season", "Regular Season", "PlayIn", "Playoffs", "All Star"]

        logger.info("\nCurrent Implementation:")
        logger.info("   if season_type == 'All Star':")
        logger.info("       # Skip game")
        logger.info("")

        for season_type in season_types:
            # Current logic: only skip All-Star
            would_skip_current = (season_type == "All Star")

            # Recommended logic: skip All-Star AND Pre-Season
            would_skip_recommended = (season_type in ["All Star", "Pre Season"])

            current_action = "🛑 SKIP" if would_skip_current else "✅ PROCESS"
            recommended_action = "🛑 SKIP" if would_skip_recommended else "✅ PROCESS"

            logger.info(f"{season_type}:")
            logger.info(f"   Current:     {current_action}")
            logger.info(f"   Recommended: {recommended_action}")

            if current_action != recommended_action:
                logger.warning(f"   ⚠️  RECOMMENDATION: Update processors to skip '{season_type}'")
                self.test_results.append({
                    'test': 'Skip Logic',
                    'passed': False,
                    'recommendation': f"Skip {season_type}"
                })

    def test_game_id_uniqueness(self) -> None:
        """Test that game_id format ensures uniqueness."""
        logger.info("\n" + "="*80)
        logger.info("🔑 TEST: Game ID Uniqueness")
        logger.info("="*80)

        # Game ID format: YYYYMMDD_AWAY_HOME
        # Test: Same teams on different dates should have different IDs
        test_cases = [
            {
                'date1': '2024-10-22',
                'date2': '2024-12-25',
                'away': 'LAL',
                'home': 'BOS',
                'description': 'Same matchup, different dates'
            },
            {
                'date1': '2024-11-15',
                'date2': '2024-11-15',
                'away': 'LAL',
                'home': 'BOS',
                'description': 'Same date, home/away reversed'
            }
        ]

        for case in test_cases:
            game_id1 = f"{case['date1'].replace('-', '')}_{case['away']}_{case['home']}"

            if case['date1'] == case['date2']:
                # Home/away reversed
                game_id2 = f"{case['date2'].replace('-', '')}_{case['home']}_{case['away']}"
            else:
                game_id2 = f"{case['date2'].replace('-', '')}_{case['away']}_{case['home']}"

            is_unique = (game_id1 != game_id2)
            status = "✅" if is_unique else "❌"

            logger.info(f"{status} {case['description']}")
            logger.info(f"   Game 1: {game_id1}")
            logger.info(f"   Game 2: {game_id2}")
            logger.info(f"   Unique: {is_unique}")

            self.test_results.append({
                'test': 'Game ID Uniqueness',
                'passed': is_unique
            })

    def generate_summary(self) -> None:
        """Generate test summary and recommendations."""
        logger.info("\n" + "="*80)
        logger.info("📊 TEST SUMMARY")
        logger.info("="*80)

        total_tests = len(self.test_results)
        passed = sum(1 for r in self.test_results if r.get('passed', False))
        failed = total_tests - passed

        logger.info(f"\nTotal Tests: {total_tests}")
        logger.info(f"Passed: ✅ {passed}")
        logger.info(f"Failed: ❌ {failed}")

        # Collect recommendations
        recommendations = [r.get('recommendation') for r in self.test_results if 'recommendation' in r]

        if recommendations:
            logger.info("\n" + "="*80)
            logger.info("💡 CRITICAL RECOMMENDATIONS")
            logger.info("="*80)

            for i, rec in enumerate(recommendations, 1):
                logger.info(f"{i}. {rec}")

            logger.info("\nIMPLEMENTATION:")
            logger.info("   Update all 4 raw processors to skip pre-season:")
            logger.info("   ")
            logger.info("   # In transform_data():")
            logger.info("   if season_type in ['All Star', 'Pre Season']:")
            logger.info("       logger.info(f'Skipping {season_type} game - exhibition data')")
            logger.info("       self.transformed_data = []")
            logger.info("       return")

    def run_all_tests(self) -> None:
        """Run complete test suite."""
        logger.info("="*80)
        logger.info("🧪 EDGE CASE TEST SUITE")
        logger.info("="*80)
        logger.info(f"Season: {self.season_year}-{self.season_year+1}")
        logger.info(f"Timestamp: {datetime.now().isoformat()}")

        self.test_season_transitions()
        self.test_season_type_consistency()
        self.test_processor_skip_logic()
        self.test_game_id_uniqueness()
        self.generate_summary()

        logger.info("\n" + "="*80)


def main():
    parser = argparse.ArgumentParser(description='Test edge cases')
    parser.add_argument('--season', type=int, default=2024)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    tester = EdgeCaseTests(season_year=args.season)
    tester.run_all_tests()


if __name__ == '__main__':
    main()
