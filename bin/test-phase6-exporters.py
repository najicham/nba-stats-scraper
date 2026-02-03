#!/usr/bin/env python3
"""
Test script for Phase 6 exporters.

Runs all 4 exporters locally and validates output structure.
"""

import sys
import json
from datetime import date, timedelta

# Add parent directory to path
sys.path.insert(0, '/home/naji/code/nba-stats-scraper')

from data_processors.publishing.subset_definitions_exporter import SubsetDefinitionsExporter
from data_processors.publishing.daily_signals_exporter import DailySignalsExporter
from data_processors.publishing.subset_performance_exporter import SubsetPerformanceExporter
from data_processors.publishing.all_subsets_picks_exporter import AllSubsetsPicksExporter


def test_subset_definitions():
    """Test SubsetDefinitionsExporter."""
    print("\n=== Testing SubsetDefinitionsExporter ===")
    exporter = SubsetDefinitionsExporter()
    result = exporter.generate_json()

    print(f"✓ Generated JSON with {len(result.get('groups', []))} groups")
    print(f"✓ Model: {result.get('model')}")

    # Validate structure
    assert 'generated_at' in result
    assert 'model' in result
    assert 'groups' in result
    assert len(result['groups']) > 0

    # Check no technical details leaked
    json_str = json.dumps(result)
    forbidden_terms = ['system_id', 'subset_id', 'confidence_score', 'edge', 'catboost']
    for term in forbidden_terms:
        if term in json_str:
            print(f"❌ LEAKED: Found '{term}' in output!")
            return False

    print("✓ No technical details leaked")
    print(f"Sample group: {result['groups'][0]}")
    return True


def test_daily_signals():
    """Test DailySignalsExporter."""
    print("\n=== Testing DailySignalsExporter ===")
    exporter = DailySignalsExporter()

    # Test with a recent date
    test_date = (date.today() - timedelta(days=1)).isoformat()
    result = exporter.generate_json(test_date)

    print(f"✓ Generated signal for {test_date}")
    print(f"✓ Signal: {result.get('signal')}")
    print(f"✓ Conditions: {result.get('metrics', {}).get('conditions')}")
    print(f"✓ Picks: {result.get('metrics', {}).get('picks')}")

    # Validate structure
    assert result['date'] == test_date
    assert result['signal'] in ['favorable', 'neutral', 'challenging']
    assert 'metrics' in result

    # Check no technical details leaked
    json_str = json.dumps(result)
    forbidden_terms = ['system_id', 'GREEN', 'RED', 'YELLOW']
    for term in forbidden_terms:
        if term in json_str:
            print(f"❌ LEAKED: Found '{term}' in output!")
            return False

    print("✓ No technical details leaked")
    return True


def test_subset_performance():
    """Test SubsetPerformanceExporter."""
    print("\n=== Testing SubsetPerformanceExporter ===")
    exporter = SubsetPerformanceExporter()
    result = exporter.generate_json()

    print(f"✓ Generated performance with {len(result.get('windows', {}))} windows")

    # Validate structure
    assert 'generated_at' in result
    assert 'model' in result
    assert 'windows' in result
    assert 'last_7_days' in result['windows']
    assert 'last_30_days' in result['windows']
    assert 'season' in result['windows']

    # Check a window
    window_7d = result['windows']['last_7_days']
    print(f"✓ 7-day window: {window_7d['start_date']} to {window_7d['end_date']}")
    print(f"✓ Groups in 7-day window: {len(window_7d.get('groups', []))}")

    if window_7d.get('groups'):
        sample = window_7d['groups'][0]
        print(f"Sample group: {sample}")

    # Check no technical details leaked
    json_str = json.dumps(result)
    forbidden_terms = ['system_id', 'subset_id', 'confidence_score', 'edge']
    for term in forbidden_terms:
        if term in json_str:
            print(f"❌ LEAKED: Found '{term}' in output!")
            return False

    print("✓ No technical details leaked")
    return True


def test_all_subsets_picks():
    """Test AllSubsetsPicksExporter."""
    print("\n=== Testing AllSubsetsPicksExporter ===")
    exporter = AllSubsetsPicksExporter()

    # Test with a recent date that has predictions
    test_date = (date.today() - timedelta(days=1)).isoformat()
    result = exporter.generate_json(test_date)

    print(f"✓ Generated picks for {test_date}")
    print(f"✓ Groups: {len(result.get('groups', []))}")

    total_picks = sum(len(g.get('picks', [])) for g in result.get('groups', []))
    print(f"✓ Total picks across all groups: {total_picks}")

    # Validate structure
    assert result['date'] == test_date
    assert 'generated_at' in result
    assert 'model' in result
    assert 'groups' in result

    # Check pick structure
    if result['groups'] and result['groups'][0].get('picks'):
        sample_pick = result['groups'][0]['picks'][0]
        print(f"Sample pick: {sample_pick}")

        # Validate pick has required fields only
        required_fields = {'player', 'team', 'opponent', 'prediction', 'line', 'direction'}
        actual_fields = set(sample_pick.keys())
        assert actual_fields == required_fields, f"Pick fields mismatch: {actual_fields}"

    # Check no technical details leaked
    json_str = json.dumps(result)
    forbidden_terms = [
        'system_id', 'subset_id', 'confidence_score', 'edge',
        'composite_score', 'catboost', 'prediction_id'
    ]
    for term in forbidden_terms:
        if term in json_str:
            print(f"❌ LEAKED: Found '{term}' in output!")
            return False

    print("✓ No technical details leaked")
    print("✓ Clean API structure verified")
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("Phase 6 Exporter Tests")
    print("=" * 60)

    tests = [
        ("Subset Definitions", test_subset_definitions),
        ("Daily Signals", test_daily_signals),
        ("Subset Performance", test_subset_performance),
        ("All Subsets Picks", test_all_subsets_picks),
    ]

    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"\n❌ {name} FAILED with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    for name, passed in results:
        status = "✓ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")

    print(f"\nPassed: {passed_count}/{total_count}")

    if passed_count == total_count:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print("\n⚠️  Some tests failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
