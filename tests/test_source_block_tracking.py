#!/usr/bin/env python3
"""
Test suite for source-block tracking system end-to-end.

Tests:
1. Record source block
2. Query source blocks
3. Validation script integration
4. Mark block resolved
"""

import sys
import os
from datetime import date

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_record_and_query():
    """Test recording and querying source blocks."""
    from shared.utils.source_block_tracker import record_source_block, get_source_blocked_resources

    print("Test 1: Record and Query Source Blocks")
    print("=" * 60)

    # Record a test block
    success = record_source_block(
        resource_id="TEST_E2E_001",
        resource_type="play_by_play",
        source_system="test_cdn",
        source_url="https://test.example.com/game/001",
        http_status_code=403,
        game_date="2026-01-26",
        notes="End-to-end test block",
        created_by="test_suite"
    )

    assert success, "Failed to record source block"
    print("✓ Recorded test block: TEST_E2E_001")

    # Query it back
    blocks = get_source_blocked_resources(
        game_date="2026-01-26",
        resource_type="play_by_play"
    )

    test_block = [b for b in blocks if b['resource_id'] == 'TEST_E2E_001']
    assert len(test_block) == 1, f"Expected 1 block, found {len(test_block)}"

    block = test_block[0]
    assert block['http_status_code'] == 403
    assert block['block_type'] == 'access_denied'
    assert block['source_system'] == 'test_cdn'
    assert block['is_resolved'] == False

    print(f"✓ Queried block back successfully")
    print(f"  - resource_id: {block['resource_id']}")
    print(f"  - block_type: {block['block_type']}")
    print(f"  - verification_count: {block['verification_count']}")
    print()

    return True


def test_validation_integration():
    """Test that validation script uses source blocks correctly."""
    from scripts.validate_tonight_data import TonightDataValidator

    print("Test 2: Validation Script Integration")
    print("=" * 60)

    # Test with 2026-01-25 (has 2 blocked games)
    validator = TonightDataValidator(date(2026, 1, 25))
    missing_teams = validator.check_game_context()

    # Should have 0 issues (blocked games not counted as failures)
    assert len(validator.issues) == 0, f"Expected 0 issues, got {len(validator.issues)}"

    # Should show blocked games in stats
    assert 'game_context_blocked' in validator.stats
    blocked_count = validator.stats['game_context_blocked']
    assert blocked_count == 2, f"Expected 2 blocked games, got {blocked_count}"

    print(f"✓ Validation correctly handles blocked games")
    print(f"  - Issues: {len(validator.issues)} (expected 0)")
    print(f"  - Blocked games: {blocked_count}")
    print(f"  - Total players: {validator.stats['game_context_players']}")
    print()

    return True


def test_historical_data():
    """Test that 2026-01-25 historical data is present."""
    from shared.utils.source_block_tracker import get_source_blocked_resources

    print("Test 3: Historical Data (2026-01-25)")
    print("=" * 60)

    blocks = get_source_blocked_resources(
        game_date="2026-01-25",
        resource_type="play_by_play"
    )

    assert len(blocks) >= 2, f"Expected at least 2 blocks for 2026-01-25, got {len(blocks)}"

    game_ids = {b['resource_id'] for b in blocks}
    expected_games = {'0022500651', '0022500652'}

    assert expected_games.issubset(game_ids), f"Missing expected games: {expected_games - game_ids}"

    print(f"✓ Historical data present")
    print(f"  - Blocked games: {len(blocks)}")
    print(f"  - Game IDs: {sorted(game_ids)}")

    for block in blocks:
        if block['resource_id'] in expected_games:
            print(f"  - {block['resource_id']}: {block['notes'][:50]}...")
    print()

    return True


def test_mark_resolved():
    """Test marking a block as resolved."""
    from shared.utils.source_block_tracker import mark_block_resolved, get_source_blocked_resources

    print("Test 4: Mark Block Resolved")
    print("=" * 60)

    # Mark test block as resolved
    success = mark_block_resolved(
        resource_id="TEST_E2E_001",
        resource_type="play_by_play",
        source_system="test_cdn",
        resolution_notes="Test complete - cleanup"
    )

    assert success, "Failed to mark block as resolved"
    print("✓ Marked test block as resolved")

    # Verify it's resolved (include_resolved=True to see it)
    blocks = get_source_blocked_resources(
        game_date="2026-01-26",
        resource_type="play_by_play",
        include_resolved=True
    )

    test_block = [b for b in blocks if b['resource_id'] == 'TEST_E2E_001']
    if test_block:
        assert test_block[0]['is_resolved'] == True, "Block should be marked as resolved"
        print(f"✓ Verified block marked as resolved")

    # Should NOT appear in active blocks
    active_blocks = get_source_blocked_resources(
        game_date="2026-01-26",
        resource_type="play_by_play",
        include_resolved=False
    )

    test_in_active = [b for b in active_blocks if b['resource_id'] == 'TEST_E2E_001']
    assert len(test_in_active) == 0, "Resolved block should not appear in active query"
    print(f"✓ Resolved block not in active list")
    print()

    return True


def test_classify_block_type():
    """Test block type classification."""
    from shared.utils.source_block_tracker import classify_block_type

    print("Test 5: Block Type Classification")
    print("=" * 60)

    tests = [
        (403, "access_denied"),
        (404, "not_found"),
        (410, "removed"),
        (500, "server_error"),
        (503, "server_error"),
        (400, "http_error"),
    ]

    for status_code, expected_type in tests:
        result = classify_block_type(status_code)
        assert result == expected_type, f"Expected {expected_type} for {status_code}, got {result}"
        print(f"✓ {status_code} → {result}")

    print()
    return True


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("SOURCE-BLOCK TRACKING - END-TO-END TESTS")
    print("=" * 60 + "\n")

    tests = [
        ("Block Type Classification", test_classify_block_type),
        ("Record and Query", test_record_and_query),
        ("Historical Data", test_historical_data),
        ("Validation Integration", test_validation_integration),
        ("Mark Resolved", test_mark_resolved),
    ]

    results = []

    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, "PASS", None))
        except Exception as e:
            results.append((name, "FAIL", str(e)))
            print(f"✗ Test failed: {e}\n")

    # Summary
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, status, _ in results if status == "PASS")
    failed = sum(1 for _, status, _ in results if status == "FAIL")

    for name, status, error in results:
        icon = "✓" if status == "PASS" else "✗"
        print(f"{icon} {name}: {status}")
        if error:
            print(f"  Error: {error}")

    print()
    print(f"Results: {passed} passed, {failed} failed out of {len(results)} tests")

    if failed == 0:
        print("\n✅ ALL TESTS PASSED")
        return 0
    else:
        print(f"\n❌ {failed} TEST(S) FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(main())
