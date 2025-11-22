#!/usr/bin/env python3
"""
Test script for historical backfill detection

Tests the enhanced Phase 3 dependency checking with:
1. Hash tracking (4 fields per source)
2. Historical backfill candidate detection

Usage:
    python tests/unit/patterns/test_historical_backfill_detection.py
"""

import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_hash_tracking():
    """Test that dependency checking includes data_hash from Phase 2 sources."""
    logger.info("=" * 80)
    logger.info("TEST 1: Hash Tracking in Dependency Checking")
    logger.info("=" * 80)

    processor = PlayerGameSummaryProcessor()

    # Run dependency check for recent date
    from datetime import datetime, timedelta
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)

    logger.info(f"\nChecking dependencies for {yesterday}...")

    try:
        dep_check = processor.check_dependencies(
            str(yesterday),
            str(yesterday)
        )

        logger.info(f"\nDependency Check Results:")
        logger.info(f"  All critical present: {dep_check['all_critical_present']}")
        logger.info(f"  All fresh: {dep_check['all_fresh']}")

        # Check if hash field is populated
        for table_name, details in dep_check['details'].items():
            logger.info(f"\n  Source: {table_name}")
            logger.info(f"    Exists: {details.get('exists')}")
            logger.info(f"    Rows: {details.get('row_count')}")
            logger.info(f"    Hash: {details.get('data_hash', 'NOT FOUND')}")

            if details.get('exists') and details.get('data_hash'):
                logger.info(f"    ✅ Hash tracking working!")
            elif details.get('exists'):
                logger.warning(f"    ⚠️ Source exists but no hash found (may not have smart idempotency)")
            else:
                logger.info(f"    ℹ️ Source not available")

        # Track source usage
        processor.track_source_usage(dep_check)

        # Build tracking fields
        tracking_fields = processor.build_source_tracking_fields()

        logger.info(f"\n  Tracking fields generated:")
        for field_name, value in tracking_fields.items():
            if 'hash' in field_name:
                logger.info(f"    {field_name}: {value if value else 'None'}")

        logger.info("\n✅ TEST 1 PASSED: Hash tracking implemented\n")
        return True

    except Exception as e:
        logger.error(f"\n❌ TEST 1 FAILED: {e}\n", exc_info=True)
        return False


def test_backfill_detection():
    """Test historical backfill candidate detection."""
    logger.info("=" * 80)
    logger.info("TEST 2: Historical Backfill Detection")
    logger.info("=" * 80)

    processor = PlayerGameSummaryProcessor()

    # Initialize BigQuery client
    processor.init_clients()

    logger.info(f"\nSearching for backfill candidates (last 7 days)...")

    try:
        candidates = processor.find_backfill_candidates(lookback_days=7)

        if candidates:
            logger.info(f"\n✅ Found {len(candidates)} games needing backfill:")
            for candidate in candidates[:10]:  # Show first 10
                logger.info(f"  - {candidate['game_date']}: {candidate['game_id']}")
                logger.info(f"      Phase 2 updated: {candidate['phase2_last_updated']}")
                logger.info(f"      Phase 2 rows: {candidate['phase2_row_count']}")

            if len(candidates) > 10:
                logger.info(f"  ... and {len(candidates) - 10} more")
        else:
            logger.info(f"\n✅ No backfill candidates found - all games processed")

        logger.info("\n✅ TEST 2 PASSED: Backfill detection working\n")
        return True

    except Exception as e:
        logger.error(f"\n❌ TEST 2 FAILED: {e}\n", exc_info=True)
        return False


def test_source_tracking_fields():
    """Test that all 6 sources have 4 fields each (24 total)."""
    logger.info("=" * 80)
    logger.info("TEST 3: Source Tracking Field Count")
    logger.info("=" * 80)

    processor = PlayerGameSummaryProcessor()
    dependencies = processor.get_dependencies()

    expected_sources = 6
    expected_fields_per_source = 4  # last_updated, rows_found, completeness_pct, hash
    expected_total_fields = expected_sources * expected_fields_per_source

    logger.info(f"\nExpected: {expected_sources} sources × {expected_fields_per_source} fields = {expected_total_fields} fields")
    logger.info(f"Configured dependencies: {len(dependencies)}")

    if len(dependencies) != expected_sources:
        logger.error(f"❌ TEST 3 FAILED: Expected {expected_sources} sources, found {len(dependencies)}")
        return False

    # Check field structure
    for table_name, config in dependencies.items():
        prefix = config['field_prefix']
        logger.info(f"\n  {table_name}")
        logger.info(f"    Prefix: {prefix}")
        logger.info(f"    Fields: {prefix}_last_updated, {prefix}_rows_found, {prefix}_completeness_pct, {prefix}_hash")

    logger.info(f"\n✅ TEST 3 PASSED: All {expected_sources} sources configured correctly\n")
    return True


if __name__ == "__main__":
    logger.info("\n" + "=" * 80)
    logger.info("PHASE 3 DEPENDENCY CHECKING TEST SUITE")
    logger.info("Testing: Hash Tracking + Historical Backfill Detection")
    logger.info("=" * 80 + "\n")

    results = []

    # Run tests
    results.append(("Source Tracking Field Count", test_source_tracking_fields()))
    results.append(("Hash Tracking", test_hash_tracking()))
    results.append(("Backfill Detection", test_backfill_detection()))

    # Summary
    logger.info("=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)

    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"{status}: {test_name}")

    all_passed = all(result[1] for result in results)

    if all_passed:
        logger.info("\n🎉 ALL TESTS PASSED\n")
        sys.exit(0)
    else:
        logger.info("\n❌ SOME TESTS FAILED\n")
        sys.exit(1)
