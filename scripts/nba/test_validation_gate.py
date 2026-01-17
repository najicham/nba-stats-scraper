#!/usr/bin/env python3
"""
Test script for Phase 1 validation gate
Tests that the validate_line_quality function correctly blocks placeholder lines
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

# Import the validation function
from predictions.worker.worker import validate_line_quality


def test_valid_predictions():
    """Test that valid predictions pass validation"""
    print("\n=== Test 1: Valid Predictions ===")

    predictions = [
        {
            'system_id': 'similarity_v3',
            'current_points_line': 18.5,
            'line_source': 'ACTUAL_PROP',
            'has_prop_line': True
        },
        {
            'system_id': 'moving_average_v2',
            'current_points_line': 22.0,
            'line_source': 'ACTUAL_PROP',
            'has_prop_line': True
        }
    ]

    is_valid, error = validate_line_quality(predictions, 'lebron-james', '2026-01-16')

    if is_valid:
        print("✅ PASS: Valid predictions accepted")
    else:
        print(f"❌ FAIL: Valid predictions rejected - {error}")

    return is_valid


def test_placeholder_20_blocked():
    """Test that line_value = 20.0 is blocked"""
    print("\n=== Test 2: Placeholder 20.0 Blocked ===")

    predictions = [
        {
            'system_id': 'xgboost_v1',
            'current_points_line': 20.0,  # PLACEHOLDER
            'line_source': 'ESTIMATED_AVG',
            'has_prop_line': False
        }
    ]

    is_valid, error = validate_line_quality(predictions, 'test-player', '2026-01-16')

    if not is_valid and '20.0 (PLACEHOLDER)' in error:
        print("✅ PASS: Placeholder 20.0 correctly blocked")
        print(f"   Error message: {error[:100]}...")
    else:
        print(f"❌ FAIL: Placeholder 20.0 not blocked - {error}")

    return not is_valid


def test_invalid_line_source_blocked():
    """Test that invalid line sources are blocked"""
    print("\n=== Test 3: Invalid Line Source Blocked ===")

    predictions = [
        {
            'system_id': 'similarity_v3',
            'current_points_line': 18.5,
            'line_source': None,  # INVALID
            'has_prop_line': True
        }
    ]

    is_valid, error = validate_line_quality(predictions, 'test-player', '2026-01-16')

    if not is_valid and 'invalid line_source=None' in error:
        print("✅ PASS: Invalid line_source=None correctly blocked")
    else:
        print(f"❌ FAIL: Invalid line_source not blocked - {error}")

    return not is_valid


def test_needs_bootstrap_blocked():
    """Test that NEEDS_BOOTSTRAP line source is blocked"""
    print("\n=== Test 4: NEEDS_BOOTSTRAP Blocked ===")

    predictions = [
        {
            'system_id': 'zone_matchup_v1',
            'current_points_line': 15.0,
            'line_source': 'NEEDS_BOOTSTRAP',  # INVALID
            'has_prop_line': False
        }
    ]

    is_valid, error = validate_line_quality(predictions, 'test-player', '2026-01-16')

    if not is_valid and 'invalid line_source=NEEDS_BOOTSTRAP' in error:
        print("✅ PASS: NEEDS_BOOTSTRAP correctly blocked")
    else:
        print(f"❌ FAIL: NEEDS_BOOTSTRAP not blocked - {error}")

    return not is_valid


def test_null_line_with_has_prop_blocked():
    """Test that NULL line with has_prop_line=True is blocked"""
    print("\n=== Test 5: NULL Line with has_prop_line=TRUE Blocked ===")

    predictions = [
        {
            'system_id': 'ensemble_v4',
            'current_points_line': None,  # NULL
            'line_source': 'ACTUAL_PROP',
            'has_prop_line': True  # Inconsistent!
        }
    ]

    is_valid, error = validate_line_quality(predictions, 'test-player', '2026-01-16')

    if not is_valid and 'NULL line but has_prop_line=TRUE' in error:
        print("✅ PASS: NULL line with has_prop_line=TRUE correctly blocked")
    else:
        print(f"❌ FAIL: Inconsistent data not blocked - {error}")

    return not is_valid


def test_mixed_predictions():
    """Test batch with both valid and invalid predictions"""
    print("\n=== Test 6: Mixed Valid/Invalid Batch ===")

    predictions = [
        {
            'system_id': 'similarity_v3',
            'current_points_line': 18.5,
            'line_source': 'ACTUAL_PROP',
            'has_prop_line': True
        },
        {
            'system_id': 'xgboost_v1',
            'current_points_line': 20.0,  # PLACEHOLDER
            'line_source': 'ESTIMATED_AVG',
            'has_prop_line': False
        },
        {
            'system_id': 'moving_average_v2',
            'current_points_line': None,  # NULL
            'line_source': 'ACTUAL_PROP',
            'has_prop_line': True  # Inconsistent!
        }
    ]

    is_valid, error = validate_line_quality(predictions, 'test-player', '2026-01-16')

    if not is_valid and 'Failed: 2/3 predictions' in error:
        print("✅ PASS: Mixed batch correctly rejected (2/3 invalid)")
        print(f"   Error details: {error}")
    else:
        print(f"❌ FAIL: Mixed batch handling incorrect - {error}")

    return not is_valid


def main():
    print("=" * 70)
    print("PHASE 1 VALIDATION GATE TEST SUITE")
    print("=" * 70)

    results = []

    # Run all tests
    results.append(("Valid predictions pass", test_valid_predictions()))
    results.append(("Placeholder 20.0 blocked", test_placeholder_20_blocked()))
    results.append(("Invalid line_source blocked", test_invalid_line_source_blocked()))
    results.append(("NEEDS_BOOTSTRAP blocked", test_needs_bootstrap_blocked()))
    results.append(("NULL line inconsistency blocked", test_null_line_with_has_prop_blocked()))
    results.append(("Mixed batch handled", test_mixed_predictions()))

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    print(f"\nResults: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed! Validation gate is working correctly.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Review validation logic.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
