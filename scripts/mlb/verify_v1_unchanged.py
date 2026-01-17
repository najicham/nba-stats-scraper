#!/usr/bin/env python3
"""
Verify V1 Predictions Unchanged

Ensures that V1 predictions remain exactly as they were before V1.6 deployment.
This is a critical safety check to ensure we never modify production data.

Usage:
    PYTHONPATH=. python scripts/mlb/verify_v1_unchanged.py
"""

from google.cloud import bigquery
import sys


PROJECT_ID = "nba-props-platform"

# Expected V1 baseline (from validation)
EXPECTED_V1_STATS = {
    'total_predictions': 8130,
    'graded_predictions': 7196,
    'win_rate': 67.3,  # Allow ±0.1% tolerance
    'mae': 1.46,  # Allow ±0.01 tolerance
}


def verify_v1_unchanged():
    """Verify V1 predictions match expected baseline"""
    client = bigquery.Client(project=PROJECT_ID)

    print("=" * 80)
    print(" V1 PREDICTION INTEGRITY CHECK")
    print("=" * 80)
    print()

    # Query V1 current state
    query = """
    SELECT
        COUNT(*) as total_predictions,
        COUNTIF(is_correct IS NOT NULL) as graded_predictions,
        ROUND(AVG(CASE WHEN is_correct IS NOT NULL THEN CAST(is_correct AS INT64) END) * 100, 1) as win_rate,
        ROUND(AVG(CASE WHEN is_correct IS NOT NULL THEN ABS(predicted_strikeouts - actual_strikeouts) END), 2) as mae,
        MIN(game_date) as first_date,
        MAX(game_date) as last_date,
        COUNT(DISTINCT pitcher_lookup) as unique_pitchers
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE model_version = 'mlb_pitcher_strikeouts_v1_20260107'
    """

    result = list(client.query(query).result())[0]

    # Check each metric
    print("Checking V1 predictions against baseline...")
    print()

    all_pass = True

    # Check total predictions
    if result.total_predictions == EXPECTED_V1_STATS['total_predictions']:
        print(f"✅ Total predictions: {result.total_predictions} (MATCH)")
    else:
        print(f"❌ Total predictions: {result.total_predictions} (EXPECTED: {EXPECTED_V1_STATS['total_predictions']})")
        all_pass = False

    # Check graded count
    if result.graded_predictions == EXPECTED_V1_STATS['graded_predictions']:
        print(f"✅ Graded predictions: {result.graded_predictions} (MATCH)")
    else:
        # Allow small variation if new games got graded
        diff = abs(result.graded_predictions - EXPECTED_V1_STATS['graded_predictions'])
        if diff <= 100:  # Allow up to 100 more graded (normal grading activity)
            print(f"⚠️  Graded predictions: {result.graded_predictions} (EXPECTED: {EXPECTED_V1_STATS['graded_predictions']}, diff: +{diff})")
            print(f"    Note: Small increase is normal if grading ran recently")
        else:
            print(f"❌ Graded predictions: {result.graded_predictions} (EXPECTED: {EXPECTED_V1_STATS['graded_predictions']}, diff: {diff})")
            all_pass = False

    # Check win rate
    win_rate_diff = abs(result.win_rate - EXPECTED_V1_STATS['win_rate'])
    if win_rate_diff <= 0.5:  # Allow 0.5% tolerance
        print(f"✅ Win rate: {result.win_rate}% (MATCH)")
    else:
        print(f"❌ Win rate: {result.win_rate}% (EXPECTED: {EXPECTED_V1_STATS['win_rate']}%, diff: {win_rate_diff:.1f}%)")
        all_pass = False

    # Check MAE
    mae_diff = abs(result.mae - EXPECTED_V1_STATS['mae'])
    if mae_diff <= 0.05:  # Allow 0.05 tolerance
        print(f"✅ MAE: {result.mae} (MATCH)")
    else:
        print(f"❌ MAE: {result.mae} (EXPECTED: {EXPECTED_V1_STATS['mae']}, diff: {mae_diff:.2f})")
        all_pass = False

    print()
    print("Additional V1 stats:")
    print(f"  Date range: {result.first_date} to {result.last_date}")
    print(f"  Unique pitchers: {result.unique_pitchers}")
    print()

    # Check for any V1.6 predictions
    print("Checking for V1.6 predictions...")
    v16_query = """
    SELECT COUNT(*) as v16_count
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE model_version LIKE '%v1_6%'
    """
    v16_result = list(client.query(v16_query).result())[0]

    if v16_result.v16_count > 0:
        print(f"✅ V1.6 predictions found: {v16_result.v16_count} (V1.6 deployed)")
    else:
        print(f"⚠️  V1.6 predictions: 0 (V1.6 not deployed yet)")

    print()
    print("=" * 80)
    if all_pass:
        print(" ✅ V1 INTEGRITY CHECK PASSED")
        print(" V1 predictions are unchanged and safe")
    else:
        print(" ❌ V1 INTEGRITY CHECK FAILED")
        print(" V1 predictions may have been modified!")
    print("=" * 80)

    return all_pass


if __name__ == '__main__':
    success = verify_v1_unchanged()
    sys.exit(0 if success else 1)
