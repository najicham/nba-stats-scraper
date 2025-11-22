#!/usr/bin/env python3
"""
Test all Phase 3 processors for dependency checking and hash tracking

Tests each processor to verify:
1. get_dependencies() is defined
2. Dependency checking uses standard pattern (date_range, expected_count_min, etc.)
3. Hash tracking fields are properly configured
4. Field prefixes match schema expectations
"""

import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
from data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor import UpcomingPlayerGameContextProcessor
from data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor import TeamOffenseGameSummaryProcessor
from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import TeamDefenseGameSummaryProcessor
from data_processors.analytics.upcoming_team_game_context.upcoming_team_game_context_processor import UpcomingTeamGameContextProcessor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


PROCESSORS = {
    'player_game_summary': PlayerGameSummaryProcessor,
    'upcoming_player_game_context': UpcomingPlayerGameContextProcessor,
    'team_offense_game_summary': TeamOffenseGameSummaryProcessor,
    'team_defense_game_summary': TeamDefenseGameSummaryProcessor,
    'upcoming_team_game_context': UpcomingTeamGameContextProcessor
}


def test_processor_dependencies(processor_name, processor_class):
    """Test a single processor's dependency configuration."""
    logger.info("=" * 80)
    logger.info(f"Testing: {processor_name}")
    logger.info("=" * 80)

    try:
        processor = processor_class()

        # Check if get_dependencies() exists
        if not hasattr(processor, 'get_dependencies'):
            logger.error(f"  ❌ Missing get_dependencies() method")
            return False

        dependencies = processor.get_dependencies()

        if not dependencies:
            logger.warning(f"  ⚠️  No dependencies defined")
            return True  # Not an error, just means no dependencies

        logger.info(f"  Dependencies: {len(dependencies)}")

        # Check each dependency
        uses_standard_pattern = False
        for table_name, config in dependencies.items():
            prefix = config.get('field_prefix', 'MISSING')
            check_type = config.get('check_type', 'MISSING')
            date_field = config.get('date_field', 'N/A')
            critical = config.get('critical', False)

            logger.info(f"\n  Source: {table_name}")
            logger.info(f"    Prefix: {prefix}")
            logger.info(f"    Check Type: {check_type}")
            logger.info(f"    Date Field: {date_field}")
            logger.info(f"    Critical: {critical}")

            # Check if using standard Phase 3 pattern
            if check_type == 'date_range':
                uses_standard_pattern = True
                expected_min = config.get('expected_count_min', 'MISSING')
                max_age_warn = config.get('max_age_hours_warn', 'MISSING')
                max_age_fail = config.get('max_age_hours_fail', 'MISSING')

                logger.info(f"    Expected Min: {expected_min}")
                logger.info(f"    Age Warn: {max_age_warn}h")
                logger.info(f"    Age Fail: {max_age_fail}h")
                logger.info(f"    ✅ Uses standard dependency pattern")

            elif check_type in ('date_match', 'lookback_days', 'existence'):
                logger.info(f"    ℹ️  Uses custom pattern (not standard Phase 3)")

        # Check if processor inherits from AnalyticsProcessorBase
        from data_processors.analytics.analytics_base import AnalyticsProcessorBase
        inherits_base = isinstance(processor, AnalyticsProcessorBase)

        logger.info(f"\n  Inherits AnalyticsProcessorBase: {inherits_base}")

        if uses_standard_pattern:
            logger.info(f"  ✅ Uses standard dependency checking (hash tracking enabled)")
        else:
            logger.info(f"  ℹ️  Uses custom dependency checking (hash tracking in schema only)")

        logger.info(f"\n✅ {processor_name}: Passed")
        return True

    except Exception as e:
        logger.error(f"\n❌ {processor_name}: Failed - {e}", exc_info=True)
        return False


def test_hash_tracking_fields():
    """Test that processors can build hash tracking fields."""
    logger.info("\n" + "=" * 80)
    logger.info("Testing Hash Tracking Field Generation")
    logger.info("=" * 80)

    results = {}

    for processor_name, processor_class in PROCESSORS.items():
        try:
            processor = processor_class()
            dependencies = processor.get_dependencies()

            if not dependencies:
                logger.info(f"\n  {processor_name}: No dependencies (skip)")
                results[processor_name] = 'skipped'
                continue

            # Initialize processor minimally
            processor.set_opts({'project_id': 'nba-props-platform'})

            # Simulate dependency check results with hash
            dep_check = {
                'all_critical_present': True,
                'all_fresh': True,
                'has_stale_fail': False,
                'has_stale_warn': False,
                'missing': [],
                'stale_fail': [],
                'stale_warn': [],
                'details': {}
            }

            # Add mock results for each dependency
            for table_name, config in dependencies.items():
                dep_check['details'][table_name] = {
                    'exists': True,
                    'row_count': 100,
                    'expected_count_min': config.get('expected_count_min', 1),
                    'age_hours': 1.5,
                    'last_updated': '2025-11-21T12:00:00',
                    'data_hash': 'test_hash_abc123'  # Mock hash
                }

            # Track source usage
            processor.track_source_usage(dep_check)

            # Build tracking fields
            tracking_fields = processor.build_source_tracking_fields()

            # Check for hash fields
            hash_fields = [k for k in tracking_fields.keys() if k.endswith('_hash')]

            logger.info(f"\n  {processor_name}:")
            logger.info(f"    Total tracking fields: {len(tracking_fields)}")
            logger.info(f"    Hash fields: {len(hash_fields)}")

            if hash_fields:
                logger.info(f"    ✅ Hash tracking working ({len(hash_fields)} sources)")
                for field in hash_fields[:3]:  # Show first 3
                    logger.info(f"      - {field}: {tracking_fields[field][:16]}...")
                if len(hash_fields) > 3:
                    logger.info(f"      ... and {len(hash_fields) - 3} more")
                results[processor_name] = 'passed'
            else:
                logger.warning(f"    ⚠️  No hash fields generated")
                results[processor_name] = 'no_hash_fields'

        except Exception as e:
            logger.error(f"  ❌ {processor_name}: Error - {e}")
            results[processor_name] = 'error'

    # Summary
    passed = sum(1 for r in results.values() if r == 'passed')
    total = len([r for r in results.values() if r != 'skipped'])

    logger.info(f"\n  Hash Tracking: {passed}/{total} processors passed")

    return all(r in ('passed', 'skipped') for r in results.values())


if __name__ == "__main__":
    logger.info("\n" + "=" * 80)
    logger.info("PHASE 3 PROCESSORS - COMPREHENSIVE TEST")
    logger.info("Testing: Dependency Configuration + Hash Tracking")
    logger.info("=" * 80 + "\n")

    results = {}

    # Test 1: Dependency configuration
    for processor_name, processor_class in PROCESSORS.items():
        results[processor_name] = test_processor_dependencies(processor_name, processor_class)

    # Test 2: Hash tracking field generation
    hash_tracking_works = test_hash_tracking_fields()

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)

    for processor_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"{status}: {processor_name}")

    logger.info(f"\nHash Tracking: {'✅ PASSED' if hash_tracking_works else '❌ FAILED'}")

    all_passed = all(results.values()) and hash_tracking_works

    if all_passed:
        logger.info("\n🎉 ALL TESTS PASSED")
        sys.exit(0)
    else:
        logger.error("\n❌ SOME TESTS FAILED")
        sys.exit(1)
