#!/usr/bin/env python3
"""
Generate Historical MLB Pitcher Strikeout Predictions - V1.6 Model

Uses the V1.6 XGBoost CLASSIFIER model to generate predictions for the same
historical games as V1. This allows direct head-to-head comparison.

Key differences from V1:
- Uses 35 features (adds f15-f19c, f30-f32, f40-f44, f50-f53)
- Classifier model (outputs OVER probability)
- Converts probability to predicted strikeouts using line
- model_version: mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149

Usage:
    PYTHONPATH=. python scripts/mlb/generate_v16_predictions_mirror_v1.py \
        --start-date 2024-04-09 \
        --end-date 2025-09-28 \
        --model-path gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict, Any
import uuid

import numpy as np
import pandas as pd
import xgboost as xgb
from google.cloud import bigquery
from google.cloud import storage

# Configuration
PROJECT_ID = "nba-props-platform"
PREDICTIONS_TABLE = "mlb_predictions.pitcher_strikeouts"

# Feature columns in the order expected by V1.6 model (35 features)
FEATURE_COLUMNS = [
    # Recent K performance (5)
    "f00_k_avg_last_3",
    "f01_k_avg_last_5",
    "f02_k_avg_last_10",
    "f03_k_std_last_10",
    "f04_ip_avg_last_5",
    # Season baseline (5)
    "f05_season_k_per_9",
    "f06_season_era",
    "f07_season_whip",
    "f08_season_games",
    "f09_season_k_total",
    # Context (5)
    "f10_is_home",
    "f15_opponent_team_k_rate",
    "f16_ballpark_k_factor",
    "f17_month_of_season",
    "f18_days_into_season",
    # Season SwStr% (3)
    "f19_season_swstr_pct",
    "f19b_season_csw_pct",
    "f19c_season_chase_pct",
    # Workload (5)
    "f20_days_rest",
    "f21_games_last_30_days",
    "f22_pitch_count_avg",
    "f23_season_ip_total",
    "f24_is_postseason",
    # Line-relative (3)
    "f30_k_avg_vs_line",
    "f31_projected_vs_line",
    "f32_line_level",
    # BettingPros (5)
    "f40_bp_projection",
    "f41_projection_diff",
    "f42_perf_last_5_pct",
    "f43_perf_last_10_pct",
    "f44_over_implied_prob",
    # Rolling Statcast (4)
    "f50_swstr_pct_last_3",
    "f51_fb_velocity_last_3",
    "f52_swstr_trend",
    "f53_velocity_change",
]


def load_model(model_path: str) -> xgb.Booster:
    """Load the trained XGBoost model from GCS or local path."""
    print(f"Loading model from {model_path}")

    # If GCS path, download first
    if model_path.startswith('gs://'):
        bucket_name = model_path.split('/')[2]
        blob_path = '/'.join(model_path.split('/')[3:])

        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)

        local_path = Path('/tmp') / Path(blob_path).name
        blob.download_to_filename(str(local_path))
        model_path = str(local_path)
        print(f"Downloaded to {local_path}")

    model = xgb.Booster()
    model.load_model(model_path)
    return model


def get_historical_data(
    client: bigquery.Client,
    start_date: str = "2024-04-09",
    end_date: str = "2025-09-28",
    limit: int = None
) -> pd.DataFrame:
    """Query historical pitcher data with V1.6 features (35 features)."""

    limit_clause = f"LIMIT {limit}" if limit else ""

    # V1.6 requires BettingPros data and Statcast data
    query = f"""
    WITH statcast_rolling AS (
        SELECT DISTINCT
            player_lookup,
            game_date,
            swstr_pct_last_3,
            swstr_pct_season_prior,
            fb_velocity_last_3,
            fb_velocity_season_prior
        FROM `{PROJECT_ID}.mlb_analytics.pitcher_rolling_statcast`
        WHERE statcast_games_count >= 3
    ),
    bp_strikeouts AS (
        -- BettingPros strikeout props (market_id = 285)
        SELECT
            player_lookup,
            game_date,
            over_line,
            over_odds,
            under_odds,
            projection_value,
            actual_value,
            perf_last_5_over,
            perf_last_5_under,
            perf_last_10_over,
            perf_last_10_under
        FROM `{PROJECT_ID}.mlb_raw.bp_pitcher_props`
        WHERE market_id = 285
    ),
    pgs_normalized AS (
        -- Normalize player_lookup for BettingPros join
        SELECT
            player_lookup,
            LOWER(REGEXP_REPLACE(NORMALIZE(player_lookup, NFD), r'[\\W_]+', '')) as player_lookup_normalized,
            game_date,
            game_id,
            team_abbr,
            opponent_team_abbr,
            season_year,
            is_home,
            is_postseason,
            strikeouts,
            innings_pitched,
            player_full_name,
            -- Recent K performance
            k_avg_last_3,
            k_avg_last_5,
            k_avg_last_10,
            k_std_last_10,
            ip_avg_last_5,
            -- Season baseline
            season_k_per_9,
            era_rolling_10,
            whip_rolling_10,
            season_games_started,
            season_strikeouts,
            season_innings,
            -- Context
            opponent_team_k_rate,
            ballpark_k_factor,
            month_of_season,
            days_into_season,
            -- Season SwStr%
            season_swstr_pct,
            season_csw_pct,
            season_chase_pct,
            -- Workload
            days_rest,
            games_last_30_days,
            pitch_count_avg_last_5,
            -- Data quality
            data_completeness_score,
            rolling_stats_games
        FROM `{PROJECT_ID}.mlb_analytics.pitcher_game_summary`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND strikeouts IS NOT NULL
          AND innings_pitched >= 3.0
          AND rolling_stats_games >= 3
    )
    SELECT
        pgs.player_lookup,
        pgs.player_full_name as pitcher_name,
        pgs.game_date,
        pgs.game_id,
        pgs.team_abbr,
        pgs.opponent_team_abbr,
        pgs.season_year,
        pgs.is_home,

        -- Target (actual result for grading)
        pgs.strikeouts as actual_strikeouts,
        pgs.innings_pitched as actual_innings,

        -- Features: Recent K performance (f00-f04)
        COALESCE(pgs.k_avg_last_3, 5.0) as f00_k_avg_last_3,
        COALESCE(pgs.k_avg_last_5, 5.0) as f01_k_avg_last_5,
        COALESCE(pgs.k_avg_last_10, 5.0) as f02_k_avg_last_10,
        COALESCE(pgs.k_std_last_10, 2.0) as f03_k_std_last_10,
        COALESCE(pgs.ip_avg_last_5, 5.5) as f04_ip_avg_last_5,

        -- Features: Season baseline (f05-f09)
        COALESCE(pgs.season_k_per_9, 8.5) as f05_season_k_per_9,
        COALESCE(pgs.era_rolling_10, 4.0) as f06_season_era,
        COALESCE(pgs.whip_rolling_10, 1.3) as f07_season_whip,
        COALESCE(pgs.season_games_started, 5) as f08_season_games,
        COALESCE(pgs.season_strikeouts, 30) as f09_season_k_total,

        -- Features: Context (f10, f15-f18)
        IF(pgs.is_home, 1.0, 0.0) as f10_is_home,
        COALESCE(pgs.opponent_team_k_rate, 0.22) as f15_opponent_team_k_rate,
        COALESCE(pgs.ballpark_k_factor, 1.0) as f16_ballpark_k_factor,
        COALESCE(pgs.month_of_season, 6) as f17_month_of_season,
        COALESCE(pgs.days_into_season, 90) as f18_days_into_season,

        -- Features: Season SwStr% (f19, f19b, f19c)
        COALESCE(pgs.season_swstr_pct, 0.105) as f19_season_swstr_pct,
        COALESCE(pgs.season_csw_pct, 0.29) as f19b_season_csw_pct,
        COALESCE(pgs.season_chase_pct, 0.30) as f19c_season_chase_pct,

        -- Features: Workload (f20-f24)
        COALESCE(pgs.days_rest, 5) as f20_days_rest,
        COALESCE(pgs.games_last_30_days, 4) as f21_games_last_30_days,
        COALESCE(pgs.pitch_count_avg_last_5, 90.0) as f22_pitch_count_avg,
        COALESCE(pgs.season_innings, 50.0) as f23_season_ip_total,
        IF(pgs.is_postseason, 1.0, 0.0) as f24_is_postseason,

        -- Features: Line-relative (f30-f32) - requires bp data
        (COALESCE(pgs.k_avg_last_5, 5.0) - COALESCE(bp.over_line, 5.5)) as f30_k_avg_vs_line,
        ((COALESCE(pgs.season_k_per_9, 8.5) / 9.0) * COALESCE(pgs.ip_avg_last_5, 5.5) - COALESCE(bp.over_line, 5.5)) as f31_projected_vs_line,
        COALESCE(bp.over_line, 5.5) as f32_line_level,

        -- Features: BettingPros (f40-f44)
        COALESCE(bp.projection_value, 5.5) as f40_bp_projection,
        (COALESCE(bp.projection_value, 5.5) - COALESCE(bp.over_line, 5.5)) as f41_projection_diff,
        SAFE_DIVIDE(bp.perf_last_5_over, (bp.perf_last_5_over + bp.perf_last_5_under)) as f42_perf_last_5_pct,
        SAFE_DIVIDE(bp.perf_last_10_over, (bp.perf_last_10_over + bp.perf_last_10_under)) as f43_perf_last_10_pct,
        CASE
            WHEN bp.over_odds IS NOT NULL THEN
                CASE
                    WHEN bp.over_odds < 0 THEN ABS(bp.over_odds) / (ABS(bp.over_odds) + 100.0)
                    ELSE 100.0 / (bp.over_odds + 100.0)
                END
            ELSE 0.50
        END as f44_over_implied_prob,

        -- Features: Rolling Statcast (f50-f53)
        COALESCE(sc.swstr_pct_last_3, pgs.season_swstr_pct, 0.105) as f50_swstr_pct_last_3,
        COALESCE(sc.fb_velocity_last_3, 93.0) as f51_fb_velocity_last_3,
        COALESCE(sc.swstr_pct_last_3 - sc.swstr_pct_season_prior, 0.0) as f52_swstr_trend,
        COALESCE(sc.fb_velocity_season_prior - sc.fb_velocity_last_3, 0.0) as f53_velocity_change,

        -- Betting lines (for output)
        bp.over_line as strikeouts_line,
        bp.over_odds as strikeouts_over_odds,
        bp.under_odds as strikeouts_under_odds,

        -- Data quality indicators
        CASE WHEN bp.over_line IS NOT NULL THEN TRUE ELSE FALSE END as has_betting_line,
        CASE WHEN sc.swstr_pct_last_3 IS NOT NULL THEN TRUE ELSE FALSE END as has_statcast_data

    FROM pgs_normalized pgs
    LEFT JOIN bp_strikeouts bp
        ON bp.player_lookup = pgs.player_lookup_normalized
        AND bp.game_date = pgs.game_date
    LEFT JOIN statcast_rolling sc
        ON REPLACE(pgs.player_lookup, '_', '') = REPLACE(sc.player_lookup, '_', '')
        AND pgs.game_date = sc.game_date
    WHERE pgs.game_date >= '{start_date}'
      AND pgs.game_date <= '{end_date}'
    ORDER BY pgs.game_date, pgs.game_id
    {limit_clause}
    """

    print(f"Querying V1.6 data from {start_date} to {end_date}...")
    df = client.query(query).to_dataframe()
    print(f"Retrieved {len(df)} pitcher games")

    # Data quality check
    has_line = df['has_betting_line'].mean() * 100
    has_statcast = df['has_statcast_data'].mean() * 100
    print(f"  BettingPros data coverage: {has_line:.1f}%")
    print(f"  Statcast data coverage: {has_statcast:.1f}%")

    return df


def generate_predictions(model: xgb.Booster, df: pd.DataFrame) -> pd.DataFrame:
    """Generate predictions using the V1.6 classifier model."""
    print("Generating V1.6 predictions...")

    # Extract feature matrix
    X = df[FEATURE_COLUMNS].values
    dmatrix = xgb.DMatrix(X, feature_names=FEATURE_COLUMNS)

    # Generate predictions (V1.6 is a CLASSIFIER - outputs OVER probability)
    prob_over = model.predict(dmatrix)

    # Convert probability to predicted strikeouts
    # Logic: If prob > 0.5, predict line + 0.5, else predict line - 0.5
    # More nuanced: Use probability to adjust prediction around line
    df = df.copy()
    df['prob_over'] = prob_over

    # Convert classifier output to strikeout prediction
    # If we have a line, use it to anchor the prediction
    # If prob_over = 0.6, predict line + 0.5
    # If prob_over = 0.4, predict line - 0.5
    # Linear interpolation around the line
    df['predicted_strikeouts'] = np.where(
        df['strikeouts_line'].notna(),
        df['strikeouts_line'] + (df['prob_over'] - 0.5) * 2,  # Scale to ±1 around line
        df['f01_k_avg_last_5']  # Fallback if no line
    )
    df['predicted_strikeouts'] = df['predicted_strikeouts'].round(2)

    # Calculate confidence based on probability distance from 0.5
    # Higher confidence when probability is further from 0.5
    df['confidence'] = np.abs(prob_over - 0.5) * 2  # Scale to 0-1
    df['confidence'] = (df['confidence'] * 0.6 + 0.4).clip(0, 1)  # Scale to 0.4-1.0

    # Calculate edge vs betting line (if available)
    df['edge'] = np.where(
        df['strikeouts_line'].notna(),
        df['predicted_strikeouts'] - df['strikeouts_line'],
        None
    )

    # Recommendation based on probability (V1.6 uses classifier output directly)
    # Use prob_over to determine recommendation
    df['recommendation'] = np.where(
        df['strikeouts_line'].isna(), 'NO_LINE',
        np.where(df['prob_over'] > 0.55, 'OVER',  # More conservative than V1
        np.where(df['prob_over'] < 0.45, 'UNDER',
        'PASS'))
    )

    return df


def calculate_metrics(df: pd.DataFrame) -> Dict[str, float]:
    """Calculate prediction accuracy metrics."""
    mae = np.abs(df['predicted_strikeouts'] - df['actual_strikeouts']).mean()
    rmse = np.sqrt(((df['predicted_strikeouts'] - df['actual_strikeouts']) ** 2).mean())

    # Over/under accuracy (where we had lines)
    with_lines = df[df['strikeouts_line'].notna()].copy()
    if len(with_lines) > 0:
        with_lines['actual_over'] = with_lines['actual_strikeouts'] > with_lines['strikeouts_line']
        with_lines['pred_over'] = with_lines['predicted_strikeouts'] > with_lines['strikeouts_line']
        line_accuracy = (with_lines['actual_over'] == with_lines['pred_over']).mean()
    else:
        line_accuracy = None

    return {
        'mae': round(mae, 3),
        'rmse': round(rmse, 3),
        'total_predictions': len(df),
        'with_lines': len(with_lines) if len(with_lines) > 0 else 0,
        'line_accuracy': round(line_accuracy, 3) if line_accuracy else None,
        'avg_prob_over': round(df['prob_over'].mean(), 3)
    }


def save_predictions(client: bigquery.Client, df: pd.DataFrame, model_version: str, dry_run: bool = False):
    """Save predictions to BigQuery."""
    if dry_run:
        print(f"DRY RUN: Would save {len(df)} predictions")
        return

    print(f"Saving {len(df)} predictions to {PREDICTIONS_TABLE}...")

    # Prepare records for BigQuery
    now = datetime.utcnow().isoformat()

    records = []
    for _, row in df.iterrows():
        records.append({
            'prediction_id': str(uuid.uuid4()),
            'game_date': row['game_date'].strftime('%Y-%m-%d') if hasattr(row['game_date'], 'strftime') else str(row['game_date']),
            'game_id': row['game_id'],
            'pitcher_lookup': row['player_lookup'],
            'pitcher_name': row['pitcher_name'],
            'team_abbr': row['team_abbr'],
            'opponent_team_abbr': row['opponent_team_abbr'],
            'is_home': bool(row['is_home']),
            'predicted_strikeouts': float(row['predicted_strikeouts']),
            'confidence': float(row['confidence']),
            'model_version': model_version,
            'strikeouts_line': float(row['strikeouts_line']) if pd.notna(row['strikeouts_line']) else None,
            'over_odds': int(row['strikeouts_over_odds']) if pd.notna(row['strikeouts_over_odds']) else None,
            'under_odds': int(row['strikeouts_under_odds']) if pd.notna(row['strikeouts_under_odds']) else None,
            'recommendation': row['recommendation'],
            'edge': float(row['edge']) if pd.notna(row['edge']) else None,
            'actual_strikeouts': int(row['actual_strikeouts']),
            'is_correct': None,  # Will be filled by grading
            'graded_at': None,
            'created_at': now,
            'processed_at': now
        })

    # Write to BigQuery
    table_ref = client.dataset('mlb_predictions').table('pitcher_strikeouts')
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION]
    )

    job = client.load_table_from_json(records, table_ref, job_config=job_config)
    job.result()

    print(f"Successfully saved {len(records)} predictions")


def main():
    parser = argparse.ArgumentParser(description='Generate V1.6 MLB predictions')
    parser.add_argument('--start-date', default='2024-04-09', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', default='2025-09-28', help='End date (YYYY-MM-DD)')
    parser.add_argument('--model-path',
                       default='gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json',
                       help='Path to V1.6 model (GCS or local)')
    parser.add_argument('--model-version',
                       default='mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149',
                       help='Model version tag for predictions')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of records')
    parser.add_argument('--dry-run', action='store_true', help='Do not save to BigQuery')
    args = parser.parse_args()

    print("=" * 80)
    print(" MLB V1.6 HISTORICAL PREDICTION GENERATION")
    print("=" * 80)
    print(f"Date range: {args.start_date} to {args.end_date}")
    print(f"Model: {args.model_path}")
    print(f"Model version tag: {args.model_version}")
    print(f"Dry run: {args.dry_run}")
    print()

    # Load model
    model = load_model(args.model_path)

    # Get data
    client = bigquery.Client(project=PROJECT_ID)
    df = get_historical_data(client, args.start_date, args.end_date, args.limit)

    if len(df) == 0:
        print("No data found for the specified date range")
        return

    # Generate predictions
    df = generate_predictions(model, df)

    # Calculate metrics
    metrics = calculate_metrics(df)
    print()
    print("=" * 80)
    print(" PREDICTION METRICS")
    print("=" * 80)
    print(f"Total predictions: {metrics['total_predictions']}")
    print(f"MAE: {metrics['mae']}")
    print(f"RMSE: {metrics['rmse']}")
    print(f"Avg OVER probability: {metrics['avg_prob_over']:.3f}")
    if metrics['line_accuracy']:
        print(f"Line accuracy: {metrics['line_accuracy']:.1%} ({metrics['with_lines']} games with lines)")
    print()

    # Show sample predictions
    print("Sample predictions:")
    sample = df[['game_date', 'pitcher_name', 'team_abbr', 'opponent_team_abbr',
                  'predicted_strikeouts', 'actual_strikeouts', 'strikeouts_line',
                  'prob_over', 'recommendation']].head(10)
    print(sample.to_string(index=False))
    print()

    # Show recommendation breakdown
    print("Recommendation breakdown:")
    rec_counts = df['recommendation'].value_counts()
    for rec, count in rec_counts.items():
        pct = count / len(df) * 100
        print(f"  {rec}: {count} ({pct:.1f}%)")
    print()

    # Save predictions
    save_predictions(client, df, args.model_version, args.dry_run)

    print()
    print("=" * 80)
    print(" COMPLETE")
    print("=" * 80)
    print()
    print("Next steps:")
    print("  1. Verify V1 unchanged: PYTHONPATH=. python scripts/mlb/verify_v1_unchanged.py")
    print("  2. Grade V1.6 predictions: PYTHONPATH=. python scripts/mlb/grade_v16_predictions.py")
    print("  3. Compare V1 vs V1.6: PYTHONPATH=. python scripts/mlb/compare_v1_vs_v16_head_to_head.py")
    print()


if __name__ == '__main__':
    main()
