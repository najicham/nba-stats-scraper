#!/usr/bin/env python3
"""
Test Smart Reprocessing Pattern

Tests the Phase 3 smart reprocessing pattern where processors skip
processing when Phase 2 source data hashes are unchanged.

This is the Phase 3 equivalent of Phase 2's smart idempotency pattern.

Expected behavior:
- First run: Process data (no previous hashes)
- Second run (same date): Skip processing (hashes unchanged)
- After Phase 2 update: Process data (hash changed)

Expected impact: 30-50% reduction in Phase 3 processing
"""

import sys
import os
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor


def test_smart_reprocessing():
    """Test smart reprocessing with player_game_summary processor."""

    print("=" * 80)
    print("SMART REPROCESSING TEST")
    print("=" * 80)

    # Use recent date with existing data
    test_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

    print(f"\nTest Date: {test_date}")
    print(f"Processor: PlayerGameSummaryProcessor")

    # Initialize processor
    processor = PlayerGameSummaryProcessor()
    processor.set_opts({
        'project_id': 'nba-props-platform',
        'start_date': test_date,
        'end_date': test_date
    })
    processor.init_clients()

    print("\n" + "=" * 80)
    print("RUN 1: Initial Processing")
    print("=" * 80)

    # First run - should process data
    success1 = processor.run({
        'start_date': test_date,
        'end_date': test_date
    })

    print(f"\nRun 1 Result: {'✅ Success' if success1 else '❌ Failed'}")

    # Check if data was written
    query = f"""
    SELECT COUNT(*) as row_count,
           COUNT(DISTINCT game_id) as game_count,
           MAX(source_gamebook_hash) as sample_hash
    FROM nba_analytics.player_game_summary
    WHERE game_date = '{test_date}'
    """

    result = list(processor.bq_client.query(query).result())[0]
    print(f"Data Written: {result['row_count']} rows, {result['game_count']} games")
    print(f"Sample Hash: {result['sample_hash'][:16]}..." if result['sample_hash'] else "No hash")

    print("\n" + "=" * 80)
    print("RUN 2: Reprocessing Same Date (Should Skip)")
    print("=" * 80)

    # Second run - should skip if Phase 2 data unchanged
    # Reinitialize processor to simulate new run
    processor2 = PlayerGameSummaryProcessor()
    processor2.set_opts({
        'project_id': 'nba-props-platform',
        'start_date': test_date,
        'end_date': test_date
    })
    processor2.init_clients()

    # Check dependencies (this will populate source hashes)
    dep_check = processor2.check_dependencies(test_date, test_date)

    if dep_check['success']:
        # Track sources (populates hash attributes)
        processor2.track_source_usage(dep_check)

        # Now test should_skip_processing
        print("\nChecking if processing can be skipped...")
        skip, reason = processor2.should_skip_processing(test_date)

        print(f"\nSkip Decision: {skip}")
        print(f"Reason: {reason}")

        if skip:
            print("\n✅ SMART REPROCESSING WORKING!")
            print("   Processor correctly detected unchanged source data")
            print("   Processing skipped - saving compute resources")
        else:
            print(f"\n⚠️  Processing not skipped: {reason}")
            print("   This is expected if:")
            print("   - First time running on this date")
            print("   - Phase 2 data was updated recently")
            print("   - Previous data doesn't exist")
    else:
        print(f"\n❌ Dependency check failed: {dep_check['message']}")

    print("\n" + "=" * 80)
    print("HASH COMPARISON DETAILS")
    print("=" * 80)

    # Get previous hashes
    previous_hashes = processor2.get_previous_source_hashes(test_date)
    print(f"\nPrevious Hashes ({len(previous_hashes)} sources):")
    for source, hash_val in previous_hashes.items():
        if hash_val:
            print(f"  {source}: {hash_val[:16]}...")
        else:
            print(f"  {source}: None")

    # Get current hashes
    print(f"\nCurrent Hashes (from Phase 2):")
    dependencies = processor2.get_dependencies()
    for table_name, config in dependencies.items():
        prefix = config['field_prefix']
        hash_attr = f'{prefix}_hash'
        current_hash = getattr(processor2, hash_attr, None)
        if current_hash:
            print(f"  {hash_attr}: {current_hash[:16]}...")
        else:
            print(f"  {hash_attr}: None")

    # Compare
    print(f"\nComparison:")
    for table_name, config in dependencies.items():
        prefix = config['field_prefix']
        hash_field = f'{prefix}_hash'

        prev = previous_hashes.get(hash_field)
        curr = getattr(processor2, hash_field, None)

        if prev and curr:
            if prev == curr:
                print(f"  ✅ {table_name}: UNCHANGED")
            else:
                print(f"  🔄 {table_name}: CHANGED")
                print(f"     Previous: {prev[:16]}...")
                print(f"     Current:  {curr[:16]}...")
        elif prev:
            print(f"  ⚠️  {table_name}: Current hash missing")
        elif curr:
            print(f"  ⚠️  {table_name}: Previous hash missing (first run)")
        else:
            print(f"  ❌ {table_name}: Both hashes missing")

    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)

    return skip if dep_check['success'] else None


def test_check_all_sources():
    """Test smart reprocessing checking all sources (stricter mode)."""

    print("\n" + "=" * 80)
    print("TEST: Check All Sources Mode")
    print("=" * 80)

    test_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

    processor = PlayerGameSummaryProcessor()
    processor.set_opts({
        'project_id': 'nba-props-platform',
        'start_date': test_date,
        'end_date': test_date
    })
    processor.init_clients()

    # Check dependencies
    dep_check = processor.check_dependencies(test_date, test_date)

    if dep_check['success']:
        processor.track_source_usage(dep_check)

        # Check with all sources (stricter)
        skip_all, reason_all = processor.should_skip_processing(
            test_date,
            check_all_sources=True
        )

        # Check with primary source only (default)
        skip_primary, reason_primary = processor.should_skip_processing(
            test_date,
            check_all_sources=False
        )

        print(f"\nCheck All Sources: {skip_all}")
        print(f"Reason: {reason_all}")

        print(f"\nCheck Primary Only: {skip_primary}")
        print(f"Reason: {reason_primary}")

        if skip_all != skip_primary:
            print("\n⚠️  Different results between check modes!")
            print("    This means some sources changed but not all")
            print("    Primary source mode is more lenient (recommended)")
    else:
        print(f"❌ Dependency check failed: {dep_check['message']}")


if __name__ == "__main__":
    print("\nSMART REPROCESSING PATTERN TEST")
    print("Testing Phase 3 equivalent of Phase 2 smart idempotency\n")

    try:
        # Test 1: Basic smart reprocessing
        skip_result = test_smart_reprocessing()

        # Test 2: Check all sources mode
        test_check_all_sources()

        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)

        if skip_result is True:
            print("\n✅ Smart reprocessing is WORKING!")
            print("   Phase 3 processors can now skip unchanged source data")
            print("   Expected impact: 30-50% reduction in processing")
        elif skip_result is False:
            print("\n⚠️  Processing not skipped (expected on first run or after updates)")
        else:
            print("\n❌ Could not complete test (check errors above)")

        print("\nNext Steps:")
        print("1. Update processors to use should_skip_processing() in extract_raw_data()")
        print("2. Track skip rate metrics")
        print("3. Monitor savings over time")

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
