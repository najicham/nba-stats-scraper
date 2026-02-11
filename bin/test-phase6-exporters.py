#!/usr/bin/env python3
"""
Test script for Phase 6 exporters.

Runs all 5 exporters locally and validates output structure.
Session 191: Added SeasonSubsetPicksExporter v2 tests.
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
from data_processors.publishing.season_subset_picks_exporter import SeasonSubsetPicksExporter


def test_subset_definitions():
    """Test SubsetDefinitionsExporter."""
    print("\n=== Testing SubsetDefinitionsExporter ===")
    exporter = SubsetDefinitionsExporter()
    result = exporter.generate_json()

    model_groups = result.get('model_groups', [])
    total_subsets = sum(len(mg.get('subsets', [])) for mg in model_groups)
    print(f"  Generated JSON with {len(model_groups)} model groups, {total_subsets} subsets")
    print(f"  Version: {result.get('version')}")

    # Validate structure
    assert 'generated_at' in result
    assert 'version' in result
    assert 'model_groups' in result
    assert len(model_groups) > 0

    # Check no technical details leaked
    json_str = json.dumps(result)
    forbidden_terms = ['system_id', 'subset_id', 'confidence_score', 'edge', 'catboost']
    for term in forbidden_terms:
        if term in json_str:
            print(f"  LEAKED: Found '{term}' in output!")
            return False

    print("  No technical details leaked")
    print(f"  Sample model group: {model_groups[0]['model_name']} with {len(model_groups[0].get('subsets', []))} subsets")
    return True


def test_daily_signals():
    """Test DailySignalsExporter."""
    print("\n=== Testing DailySignalsExporter ===")
    exporter = DailySignalsExporter()

    # Test with a recent date
    test_date = (date.today() - timedelta(days=1)).isoformat()
    result = exporter.generate_json(test_date)

    print(f"  Generated signal for {test_date}")
    print(f"  Signal: {result.get('signal')}")
    print(f"  Conditions: {result.get('metrics', {}).get('conditions')}")
    print(f"  Picks: {result.get('metrics', {}).get('picks')}")

    # Validate structure
    assert result['date'] == test_date
    assert result['signal'] in ['favorable', 'neutral', 'challenging']
    assert 'metrics' in result

    # Check no technical details leaked
    json_str = json.dumps(result)
    forbidden_terms = ['system_id', 'GREEN', 'RED', 'YELLOW']
    for term in forbidden_terms:
        if term in json_str:
            print(f"  LEAKED: Found '{term}' in output!")
            return False

    print("  No technical details leaked")
    return True


def test_subset_performance():
    """Test SubsetPerformanceExporter."""
    print("\n=== Testing SubsetPerformanceExporter ===")
    exporter = SubsetPerformanceExporter()
    result = exporter.generate_json()

    model_groups = result.get('model_groups', [])
    print(f"  Generated performance for {len(model_groups)} model groups")
    print(f"  Version: {result.get('version')}")

    # Validate structure
    assert 'generated_at' in result
    assert 'version' in result
    assert 'model_groups' in result
    assert len(model_groups) > 0

    # Check first model's windows
    first_model = model_groups[0]
    windows = first_model.get('windows', {})
    assert 'last_1_day' in windows
    assert 'last_3_days' in windows
    assert 'last_7_days' in windows
    assert 'last_14_days' in windows
    assert 'last_30_days' in windows
    assert 'season' in windows

    window_7d = windows['last_7_days']
    print(f"  7-day window: {window_7d['start_date']} to {window_7d['end_date']}")
    print(f"  Groups in 7-day window: {len(window_7d.get('groups', []))}")

    if window_7d.get('groups'):
        sample = window_7d['groups'][0]
        print(f"  Sample group: {sample}")

    # Check no technical details leaked
    json_str = json.dumps(result)
    forbidden_terms = ['system_id', 'subset_id', 'confidence_score', 'edge']
    for term in forbidden_terms:
        if term in json_str:
            print(f"  LEAKED: Found '{term}' in output!")
            return False

    print("  No technical details leaked")
    return True


def test_all_subsets_picks():
    """Test AllSubsetsPicksExporter."""
    print("\n=== Testing AllSubsetsPicksExporter ===")
    exporter = AllSubsetsPicksExporter()

    # Test with a recent date that has predictions
    test_date = (date.today() - timedelta(days=1)).isoformat()
    result = exporter.generate_json(test_date)

    model_groups = result.get('model_groups', [])
    total_picks = sum(
        len(p) for mg in model_groups
        for s in mg.get('subsets', [])
        for p in [s.get('picks', [])]
    )
    print(f"  Generated picks for {test_date}")
    print(f"  Model groups: {len(model_groups)}")
    print(f"  Total picks across all groups: {total_picks}")

    # Validate structure
    assert result['date'] == test_date
    assert 'generated_at' in result
    assert 'version' in result
    assert 'model_groups' in result

    # Check pick structure from first model group with picks
    for mg in model_groups:
        for subset in mg.get('subsets', []):
            if subset.get('picks'):
                sample_pick = subset['picks'][0]
                print(f"  Sample pick from {mg['model_name']}: {sample_pick}")

                # Validate pick has required fields only
                required_fields = {'player', 'team', 'opponent', 'prediction', 'line', 'direction'}
                actual_fields = set(sample_pick.keys())
                assert actual_fields == required_fields, f"Pick fields mismatch: {actual_fields}"
                break
        else:
            continue
        break

    # Check no technical details leaked
    json_str = json.dumps(result)
    forbidden_terms = [
        'system_id', 'subset_id', 'confidence_score', 'edge',
        'composite_score', 'catboost', 'prediction_id'
    ]
    for term in forbidden_terms:
        if term in json_str:
            print(f"  LEAKED: Found '{term}' in output!")
            return False

    print("  No technical details leaked")
    print("  Clean API structure verified")
    return True


def test_season_subset_picks():
    """Test SeasonSubsetPicksExporter (v2 multi-model)."""
    print("\n=== Testing SeasonSubsetPicksExporter (v2) ===")
    exporter = SeasonSubsetPicksExporter()
    result = exporter.generate_json()

    model_groups = result.get('model_groups', [])
    total_dates = sum(len(mg.get('dates', [])) for mg in model_groups)
    total_picks = sum(
        len(p)
        for mg in model_groups
        for d in mg.get('dates', [])
        for p in [d.get('picks', [])]
    )
    print(f"  Version: {result.get('version')}")
    print(f"  Season: {result.get('season')}")
    print(f"  Model groups: {len(model_groups)}")
    print(f"  Total date entries: {total_dates}")
    print(f"  Total picks: {total_picks}")

    # Validate top-level structure
    assert 'generated_at' in result, "Missing generated_at"
    assert result.get('version') == 2, f"Expected version 2, got {result.get('version')}"
    assert 'season' in result, "Missing season"
    assert 'model_groups' in result, "Missing model_groups"
    assert len(model_groups) > 0, "No model groups"

    # Validate model_group structure
    first_model = model_groups[0]
    assert 'model_id' in first_model, "Missing model_id"
    assert 'model_name' in first_model, "Missing model_name"
    assert 'model_type' in first_model, "Missing model_type"
    assert 'record' in first_model, "Missing record"
    assert 'dates' in first_model, "Missing dates"

    # Champion should be first
    print(f"  First model (champion): {first_model['model_id']} ({first_model['model_name']})")
    assert first_model['model_id'] == 'phoenix', f"Champion should be first, got {first_model['model_id']}"

    # Validate record structure (if has data)
    record = first_model.get('record')
    if record is not None:
        for window in ['season', 'month', 'week']:
            assert window in record, f"Missing {window} in record"
            assert 'wins' in record[window], f"Missing wins in record.{window}"
            assert 'losses' in record[window], f"Missing losses in record.{window}"
            assert 'pct' in record[window], f"Missing pct in record.{window}"
        print(f"  Record: {record['season']['wins']}W-{record['season']['losses']}L ({record['season']['pct']}%)")

    # Check pick structure (includes actual/result — unique to season exporter)
    for mg in model_groups:
        for day in mg.get('dates', []):
            if day.get('picks'):
                sample_pick = day['picks'][0]
                print(f"  Sample pick: {sample_pick}")

                # Season picks include actual/result fields
                required_fields = {'player', 'team', 'opponent', 'prediction', 'line', 'direction', 'actual', 'result'}
                actual_fields = set(sample_pick.keys())
                assert actual_fields == required_fields, f"Pick fields mismatch: expected {required_fields}, got {actual_fields}"

                # Validate result values
                if sample_pick['result'] is not None:
                    assert sample_pick['result'] in ('hit', 'miss', 'push'), f"Bad result: {sample_pick['result']}"
                break
            break
        break

    # Check date structure
    if first_model.get('dates'):
        first_date = first_model['dates'][0]
        assert 'date' in first_date, "Missing date"
        assert 'signal' in first_date, "Missing signal"
        assert 'picks' in first_date, "Missing picks"
        assert first_date['signal'] in ('favorable', 'neutral', 'challenging'), f"Bad signal: {first_date['signal']}"

    # Check no technical details leaked
    json_str = json.dumps(result)
    forbidden_terms = [
        'system_id', 'subset_id', 'confidence_score',
        'composite_score', 'catboost', 'prediction_id'
    ]
    for term in forbidden_terms:
        if term in json_str:
            print(f"  LEAKED: Found '{term}' in output!")
            return False

    print("  No technical details leaked")
    print("  v2 multi-model structure verified")
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
        ("Season Subset Picks (v2)", test_season_subset_picks),
    ]

    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"\n  {name} FAILED with exception: {e}")
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
        status = "PASS" if passed else "FAIL"
        print(f"  {status}: {name}")

    print(f"\nPassed: {passed_count}/{total_count}")

    if passed_count == total_count:
        print("\nAll tests passed!")
        return 0
    else:
        print("\nSome tests failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
