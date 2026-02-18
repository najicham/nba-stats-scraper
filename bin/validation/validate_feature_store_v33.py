#!/usr/bin/env python3
"""
Validate ML Feature Store has all 33 features for daily predictions.

Run as part of daily validation before Phase 5 predictions.

Usage:
    python bin/validation/validate_feature_store_v33.py
    python bin/validation/validate_feature_store_v33.py --date 2026-01-09
"""

import argparse
import sys
from datetime import datetime, timedelta
import os

from google.cloud import bigquery

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

# All 33 features required for CatBoost v8
REQUIRED_FEATURES = [
    # Base 25 features
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct",
    # Extra 8 features (v33)
    "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line",
    "avg_points_vs_opponent", "games_vs_opponent",
    "minutes_avg_last_10", "ppm_avg_last_10"
]

# Features that are allowed to be NULL/0 (fallbacks are acceptable)
ALLOWED_MISSING = {
    "vegas_opening_line",  # May use current line as fallback
    "vegas_line_move",     # Will be 0 if no line movement
    "games_vs_opponent",   # 0 for first matchup
}


def validate_features(client: bigquery.Client, game_date: str) -> dict:
    """
    Validate feature store has all 33 features for a date.

    Returns dict with validation results.
    """
    query = f"""
    SELECT
        COUNT(*) as total_players,
        COUNTIF(feature_count = 33) as players_with_33_features,
        COUNTIF(feature_count = 25) as players_with_25_features,
        COUNTIF(feature_count != 33 AND feature_count != 25) as players_with_other,
        MAX(feature_version) as feature_version,

        -- Check for NULL values in extra features using individual columns
        COUNTIF(feature_25_value IS NOT NULL) as has_vegas_line,
        COUNTIF(feature_29_value IS NOT NULL) as has_opponent_avg,
        COUNTIF(feature_31_value IS NOT NULL) as has_minutes_avg
    FROM `nba_predictions.ml_feature_store_v2`
    WHERE game_date = @game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    )

    result = list(client.query(query, job_config=job_config).result(timeout=60))[0]

    total = result.total_players

    return {
        'game_date': game_date,
        'total_players': total,
        'players_with_33_features': result.players_with_33_features,
        'players_with_25_features': result.players_with_25_features,
        'feature_version': result.feature_version,
        'pct_complete': round(result.players_with_33_features / total * 100, 1) if total > 0 else 0,
        'has_vegas_line_pct': round(result.has_vegas_line / total * 100, 1) if total > 0 else 0,
        'has_opponent_avg_pct': round(result.has_opponent_avg / total * 100, 1) if total > 0 else 0,
        'has_minutes_avg_pct': round(result.has_minutes_avg / total * 100, 1) if total > 0 else 0,
        'is_valid': result.players_with_33_features == total
    }


def main():
    parser = argparse.ArgumentParser(description='Validate feature store v33')
    parser.add_argument('--date', type=str, help='Date to validate (YYYY-MM-DD)',
                        default=(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'))
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    print(f"\n{'='*60}")
    print(f"Feature Store V33 Validation - {args.date}")
    print(f"{'='*60}\n")

    result = validate_features(client, args.date)

    print(f"Total players:           {result['total_players']}")
    print(f"With 33 features:        {result['players_with_33_features']} ({result['pct_complete']}%)")
    print(f"With 25 features (old):  {result['players_with_25_features']}")
    print(f"Feature version:         {result['feature_version']}")
    print()
    print(f"Vegas line coverage:     {result['has_vegas_line_pct']}%")
    print(f"Opponent avg coverage:   {result['has_opponent_avg_pct']}%")
    print(f"Minutes avg coverage:    {result['has_minutes_avg_pct']}%")
    print()

    if result['is_valid']:
        print("✅ PASS: All players have 33 features")
        sys.exit(0)
    else:
        print("❌ FAIL: Some players missing v33 features")
        sys.exit(1)


if __name__ == '__main__':
    main()
