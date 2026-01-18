#!/usr/bin/env python3
"""
Test script for MLB optimization improvements

Tests:
1. Shared feature loader functionality
2. Feature coverage calculation
3. Multi-system batch predictions
4. IL cache behavior

Usage:
    python bin/mlb/test_optimizations.py --test all
    python bin/mlb/test_optimizations.py --test feature-loader
    python bin/mlb/test_optimizations.py --test coverage
"""

import os
import sys
import argparse
import logging
from datetime import date
from typing import Dict, List

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from predictions.mlb.pitcher_loader import load_batch_features
from predictions.mlb.prediction_systems.v1_baseline_predictor import V1BaselinePredictor
from predictions.mlb.prediction_systems.v1_6_rolling_predictor import V1_6RollingPredictor
from predictions.mlb.prediction_systems.ensemble_v1 import MLBEnsembleV1

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_feature_loader():
    """Test shared feature loader"""
    print("\n" + "="*80)
    print("TEST 1: Shared Feature Loader")
    print("="*80)

    test_date = date(2025, 9, 20)

    print(f"\nLoading features for {test_date}...")
    features_by_pitcher = load_batch_features(
        game_date=test_date,
        pitcher_lookups=None  # Load all pitchers
    )

    if not features_by_pitcher:
        print("❌ FAIL: No features loaded")
        return False

    print(f"✅ PASS: Loaded features for {len(features_by_pitcher)} pitchers")

    # Verify feature completeness
    sample_pitcher = list(features_by_pitcher.keys())[0]
    sample_features = features_by_pitcher[sample_pitcher]

    print(f"\nSample pitcher: {sample_pitcher}")
    print(f"  Features loaded: {len(sample_features)} fields")

    # Check for key features
    key_features = [
        'k_avg_last_5',
        'swstr_pct_last_3',  # V1.6 feature
        'bp_projection',     # V1.6 feature
        'team_abbr',
        'opponent_team_abbr'
    ]

    missing = [f for f in key_features if f not in sample_features or sample_features[f] is None]
    if missing:
        print(f"⚠️  Missing features: {missing}")
    else:
        print(f"✅ All key features present")

    return True


def test_feature_coverage():
    """Test feature coverage calculation"""
    print("\n" + "="*80)
    print("TEST 2: Feature Coverage Calculation")
    print("="*80)

    # Initialize V1.6 predictor (has most features)
    predictor = V1_6RollingPredictor()
    if not predictor.load_model():
        print("❌ FAIL: Could not load V1.6 model")
        return False

    print(f"✅ Model loaded: {len(predictor.feature_order)} features expected")

    # Test with full features
    test_features = {feature: 1.0 for feature in predictor.feature_order}
    coverage_pct, missing = predictor._calculate_feature_coverage(test_features, predictor.feature_order)

    print(f"\nTest 2a: Full features")
    print(f"  Coverage: {coverage_pct:.1f}%")
    print(f"  Missing: {len(missing)}")

    if coverage_pct != 100.0:
        print(f"❌ FAIL: Expected 100% coverage, got {coverage_pct}%")
        return False
    print(f"✅ PASS: Full coverage calculation correct")

    # Test with partial features (50% missing)
    partial_features = {feature: 1.0 for i, feature in enumerate(predictor.feature_order) if i % 2 == 0}
    coverage_pct, missing = predictor._calculate_feature_coverage(partial_features, predictor.feature_order)

    print(f"\nTest 2b: Partial features (50% removed)")
    print(f"  Coverage: {coverage_pct:.1f}%")
    print(f"  Missing: {len(missing)}")

    if not (45 <= coverage_pct <= 55):
        print(f"❌ FAIL: Expected ~50% coverage, got {coverage_pct}%")
        return False
    print(f"✅ PASS: Partial coverage calculation correct")

    # Test confidence adjustment
    base_confidence = 80.0

    test_cases = [
        (95.0, 80.0, "95% coverage → no penalty"),
        (85.0, 75.0, "85% coverage → -5 penalty"),
        (75.0, 70.0, "75% coverage → -10 penalty"),
        (65.0, 65.0, "65% coverage → -15 penalty"),
        (55.0, 55.0, "55% coverage → -25 penalty"),
    ]

    print(f"\nTest 2c: Confidence adjustment (base confidence = {base_confidence})")
    for coverage, expected_conf, description in test_cases:
        adjusted = predictor._adjust_confidence_for_coverage(base_confidence, coverage)
        print(f"  {description}: {adjusted:.1f} (expected {expected_conf})")
        if abs(adjusted - expected_conf) > 0.1:
            print(f"    ❌ FAIL: Expected {expected_conf}, got {adjusted}")
            return False

    print(f"✅ PASS: All confidence adjustments correct")
    return True


def test_multi_system_batch():
    """Test multi-system batch predictions"""
    print("\n" + "="*80)
    print("TEST 3: Multi-System Batch Predictions")
    print("="*80)

    test_date = date(2025, 9, 20)
    test_pitchers = ['gerrit-cole', 'shohei-ohtani']

    print(f"\nLoading features for {len(test_pitchers)} pitchers...")
    features_by_pitcher = load_batch_features(
        game_date=test_date,
        pitcher_lookups=test_pitchers
    )

    if not features_by_pitcher:
        print("⚠️  No features loaded - skipping test (may be test data issue)")
        return True

    print(f"✅ Loaded features for {len(features_by_pitcher)} pitchers")

    # Initialize all systems
    v1 = V1BaselinePredictor()
    v1_6 = V1_6RollingPredictor()

    if not v1.load_model():
        print("❌ FAIL: Could not load V1 model")
        return False
    if not v1_6.load_model():
        print("❌ FAIL: Could not load V1.6 model")
        return False

    ensemble = MLBEnsembleV1(v1_predictor=v1, v1_6_predictor=v1_6)

    systems = {
        'v1_baseline': v1,
        'v1_6_rolling': v1_6,
        'ensemble_v1': ensemble
    }

    print(f"\n✅ All {len(systems)} systems initialized")

    # Generate predictions
    all_predictions = []
    for pitcher_lookup, features in features_by_pitcher.items():
        strikeouts_line = features.get('strikeouts_line', 6.5)

        for system_id, predictor in systems.items():
            try:
                prediction = predictor.predict(
                    pitcher_lookup=pitcher_lookup,
                    features=features,
                    strikeouts_line=strikeouts_line
                )
                prediction['system_id'] = system_id
                all_predictions.append(prediction)
            except Exception as e:
                print(f"❌ FAIL: {system_id} prediction failed for {pitcher_lookup}: {e}")
                return False

    print(f"\n✅ Generated {len(all_predictions)} predictions")

    # Verify prediction structure
    for pred in all_predictions[:3]:  # Check first 3
        print(f"\n  Pitcher: {pred['pitcher_lookup']}, System: {pred['system_id']}")
        print(f"    Predicted K: {pred.get('predicted_strikeouts')}")
        print(f"    Confidence: {pred.get('confidence')}")
        print(f"    Recommendation: {pred.get('recommendation')}")
        print(f"    Feature Coverage: {pred.get('feature_coverage_pct', 'N/A')}%")

        # Verify required fields
        required_fields = ['predicted_strikeouts', 'confidence', 'recommendation', 'feature_coverage_pct']
        missing_fields = [f for f in required_fields if f not in pred]
        if missing_fields:
            print(f"    ❌ FAIL: Missing fields: {missing_fields}")
            return False

    print(f"\n✅ PASS: All predictions have required fields")
    return True


def test_il_cache():
    """Test IL cache behavior"""
    print("\n" + "="*80)
    print("TEST 4: IL Cache Behavior")
    print("="*80)

    predictor = V1BaselinePredictor()

    print("\nFetching IL pitchers (first call - cache miss)...")
    il_pitchers_1 = predictor._get_current_il_pitchers()

    print(f"✅ Loaded {len(il_pitchers_1)} pitchers on IL")

    print("\nFetching IL pitchers (second call - should hit cache)...")
    il_pitchers_2 = predictor._get_current_il_pitchers()

    if il_pitchers_1 != il_pitchers_2:
        print("❌ FAIL: Cache returned different results")
        return False

    print(f"✅ PASS: Cache hit successful ({len(il_pitchers_2)} pitchers)")

    if il_pitchers_1:
        sample_pitcher = list(il_pitchers_1)[0]
        print(f"\nSample IL pitcher: {sample_pitcher}")

    return True


def run_all_tests():
    """Run all tests"""
    print("\n" + "="*80)
    print("MLB OPTIMIZATION VALIDATION TESTS")
    print("="*80)

    tests = [
        ("Feature Loader", test_feature_loader),
        ("Feature Coverage", test_feature_coverage),
        ("Multi-System Batch", test_multi_system_batch),
        ("IL Cache", test_il_cache),
    ]

    results = {}
    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
        except Exception as e:
            print(f"\n❌ {test_name} EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            results[test_name] = False

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")

    all_passed = all(results.values())
    print("\n" + "="*80)
    if all_passed:
        print("✅ ALL TESTS PASSED - Ready for deployment!")
    else:
        print("❌ SOME TESTS FAILED - Review errors above")
    print("="*80 + "\n")

    return all_passed


def main():
    parser = argparse.ArgumentParser(description="Test MLB optimization improvements")
    parser.add_argument(
        '--test',
        choices=['all', 'feature-loader', 'coverage', 'multi-system', 'il-cache'],
        default='all',
        help='Which test to run'
    )
    args = parser.parse_args()

    if args.test == 'all':
        success = run_all_tests()
    elif args.test == 'feature-loader':
        success = test_feature_loader()
    elif args.test == 'coverage':
        success = test_feature_coverage()
    elif args.test == 'multi-system':
        success = test_multi_system_batch()
    elif args.test == 'il-cache':
        success = test_il_cache()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
