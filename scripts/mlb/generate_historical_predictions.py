#!/usr/bin/env python3
"""
Generate Historical MLB Pitcher Strikeout Predictions

Uses the trained XGBoost model to generate predictions for all historical
games in pitcher_game_summary. This creates training/validation data for
the frontend and allows backtesting of model performance.

Usage:
    PYTHONPATH=. python scripts/mlb/generate_historical_predictions.py
    PYTHONPATH=. python scripts/mlb/generate_historical_predictions.py --start-date 2024-06-01 --end-date 2024-06-30
    PYTHONPATH=. python scripts/mlb/generate_historical_predictions.py --dry-run --limit 100
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

# Configuration
PROJECT_ID = "nba-props-platform"
MODEL_PATH = Path("models/mlb/mlb_pitcher_strikeouts_v2_20260108.json")
PREDICTIONS_TABLE = "mlb_predictions.pitcher_strikeouts"

# Feature columns in the order expected by the model
FEATURE_COLUMNS = [
    "f00_k_avg_last_3",
    "f01_k_avg_last_5",
    "f02_k_avg_last_10",
    "f03_k_std_last_10",
    "f04_ip_avg_last_5",
    "f05_season_k_per_9",
    "f06_season_era",
    "f07_season_whip",
    "f08_season_games",
    "f09_season_k_total",
    "f10_is_home",
    "f20_days_rest",
    "f21_games_last_30_days",
    "f22_pitch_count_avg",
    "f23_season_ip_total",
    "f24_is_postseason",
    "f25_bottom_up_k_expected",
    "f26_lineup_k_vs_hand",
    "f33_lineup_weak_spots",
]


def load_model() -> xgb.Booster:
    """Load the trained XGBoost model."""
    print(f"Loading model from {MODEL_PATH}")
    model = xgb.Booster()
    model.load_model(str(MODEL_PATH))
    return model


def get_historical_data(
    client: bigquery.Client,
    start_date: str = "2024-03-01",
    end_date: str = "2025-12-31",
    limit: int = None
) -> pd.DataFrame:
    """Query historical pitcher data with features."""

    limit_clause = f"LIMIT {limit}" if limit else ""

    # Calculate bottom-up features by joining lineup batters with batter analytics
    # Now that team_abbr is fixed, we can properly filter to opponent lineup only
    query = f"""
    WITH game_teams AS (
        -- Get distinct game_pk with home/away teams (dedupe mlb_game_lineups)
        SELECT DISTINCT
            game_pk,
            home_team_abbr,
            away_team_abbr
        FROM `{PROJECT_ID}.mlb_raw.mlb_game_lineups`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
    ),
    pitcher_games AS (
        -- Get pitcher game info including team_abbr from raw data (which is fixed)
        -- Dedupe using ROW_NUMBER since raw data may have duplicate rows per pitcher per game
        SELECT
            game_pk,
            game_date,
            player_lookup,
            pitcher_team,
            opponent_team
        FROM (
            SELECT
                ps.game_pk,
                ps.game_date,
                ps.player_lookup,
                ps.team_abbr as pitcher_team,
                -- Opponent is the OTHER team in the game
                CASE
                    WHEN ps.team_abbr = gt.home_team_abbr THEN gt.away_team_abbr
                    ELSE gt.home_team_abbr
                END as opponent_team,
                ROW_NUMBER() OVER (PARTITION BY ps.game_pk, ps.player_lookup ORDER BY ps.game_date) as rn
            FROM `{PROJECT_ID}.mlb_raw.mlb_pitcher_stats` ps
            JOIN game_teams gt
                ON ps.game_pk = gt.game_pk
            WHERE ps.is_starter = TRUE
              AND ps.game_date >= '{start_date}'
              AND ps.game_date <= '{end_date}'
        )
        WHERE rn = 1
    ),
    batter_latest_stats AS (
        -- Get each batter's most recent K rate before each date
        -- Use QUALIFY to get latest per batter per date range
        SELECT
            player_lookup,
            game_date as stats_date,
            k_rate_last_10,
            season_k_rate
        FROM `{PROJECT_ID}.mlb_analytics.batter_game_summary`
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY player_lookup
            ORDER BY game_date DESC
        ) = 1
    ),
    lineup_batters_deduped AS (
        -- Dedupe lineup batters (raw data has duplicates)
        SELECT
            game_pk,
            game_date,
            team_abbr,
            player_lookup,
            batting_order
        FROM (
            SELECT
                game_pk,
                game_date,
                team_abbr,
                player_lookup,
                batting_order,
                ROW_NUMBER() OVER (PARTITION BY game_pk, team_abbr, player_lookup ORDER BY batting_order) as rn
            FROM `{PROJECT_ID}.mlb_raw.mlb_lineup_batters`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
        )
        WHERE rn = 1
    ),
    lineup_batter_stats AS (
        -- Get batter K rates for each game's OPPONENT lineup only (filtered by pitcher's opponent)
        SELECT
            pg.game_pk,
            pg.game_date,
            pg.player_lookup as pitcher_lookup,
            lb.team_abbr as batter_team,
            lb.player_lookup as batter_lookup,
            lb.batting_order,
            -- Use batter's K rate (fallback to league average)
            COALESCE(bs.k_rate_last_10, bs.season_k_rate, 0.22) as batter_k_rate,
            -- Expected plate appearances by batting order
            CASE lb.batting_order
                WHEN 1 THEN 4.5 WHEN 2 THEN 4.3 WHEN 3 THEN 4.2 WHEN 4 THEN 4.0
                WHEN 5 THEN 3.9 WHEN 6 THEN 3.8 WHEN 7 THEN 3.7 WHEN 8 THEN 3.6
                ELSE 3.5
            END as expected_pa
        FROM pitcher_games pg
        JOIN lineup_batters_deduped lb
            ON pg.game_pk = lb.game_pk
            AND lb.team_abbr = pg.opponent_team  -- KEY FIX: Only opponent's batters
        LEFT JOIN batter_latest_stats bs
            ON lb.player_lookup = bs.player_lookup
    ),
    lineup_aggregates AS (
        -- Aggregate batter stats per pitcher per game (now opponent-specific!)
        SELECT
            game_pk,
            game_date,
            pitcher_lookup,
            -- Bottom-up expected K: sum of individual batter expected Ks
            SUM(batter_k_rate * expected_pa) as bottom_up_k,
            -- Average lineup K rate
            AVG(batter_k_rate) as lineup_avg_k_rate,
            -- Count of weak spots (K rate > 0.28)
            COUNTIF(batter_k_rate > 0.28) as weak_spots,
            COUNT(*) as batters_in_lineup
        FROM lineup_batter_stats
        GROUP BY game_pk, game_date, pitcher_lookup
    )
    SELECT
        p.player_lookup,
        p.player_full_name as pitcher_name,
        p.game_date,
        p.game_id,
        -- Pull team_abbr from raw data (which is fixed), not from analytics table (which has UNK)
        pg.pitcher_team as team_abbr,
        pg.opponent_team as opponent_team_abbr,
        p.season_year,
        p.is_home,

        -- Target (actual result for grading)
        p.strikeouts as actual_strikeouts,
        p.innings_pitched as actual_innings,

        -- Features (f00-f04: Recent performance)
        COALESCE(p.k_avg_last_3, 5.0) as f00_k_avg_last_3,
        COALESCE(p.k_avg_last_5, 5.0) as f01_k_avg_last_5,
        COALESCE(p.k_avg_last_10, 5.0) as f02_k_avg_last_10,
        COALESCE(p.k_std_last_10, 2.0) as f03_k_std_last_10,
        COALESCE(p.ip_avg_last_5, 5.5) as f04_ip_avg_last_5,

        -- Features (f05-f09: Season baseline)
        COALESCE(p.season_k_per_9, 8.5) as f05_season_k_per_9,
        COALESCE(SAFE_DIVIDE(p.earned_runs * 9, p.innings_pitched), 4.0) as f06_season_era,
        COALESCE(p.whip_rolling_10, 1.3) as f07_season_whip,
        COALESCE(p.season_games_started, 5) as f08_season_games,
        COALESCE(p.season_strikeouts, 30) as f09_season_k_total,

        -- Features (f10: Split)
        IF(p.is_home, 1.0, 0.0) as f10_is_home,

        -- Features (f20-f24: Workload)
        COALESCE(p.days_rest, 5) as f20_days_rest,
        COALESCE(p.games_last_30_days, 4) as f21_games_last_30_days,
        COALESCE(p.pitch_count_avg_last_5, 90.0) as f22_pitch_count_avg,
        COALESCE(p.season_innings, 50.0) as f23_season_ip_total,
        IF(p.is_postseason, 1.0, 0.0) as f24_is_postseason,

        -- Features (f25-f33: Bottom-up model from lineup data - now opponent-specific!)
        COALESCE(la.bottom_up_k, 5.0) as f25_bottom_up_k_expected,
        COALESCE(la.lineup_avg_k_rate, 0.22) as f26_lineup_k_vs_hand,
        COALESCE(la.weak_spots, 2) as f33_lineup_weak_spots,

        -- Betting lines (if available)
        p.strikeouts_line,
        p.strikeouts_over_odds,
        p.strikeouts_under_odds,

        -- Data quality indicators
        CASE WHEN la.game_pk IS NOT NULL THEN TRUE ELSE FALSE END as has_lineup_analysis,
        la.batters_in_lineup as lineup_data_quality

    FROM `{PROJECT_ID}.mlb_analytics.pitcher_game_summary` p
    -- Join with pitcher_games CTE to get fixed team_abbr and opponent
    JOIN pitcher_games pg
        ON p.player_lookup = pg.player_lookup AND p.game_date = pg.game_date
    -- Join lineup aggregates using game_pk and pitcher_lookup for opponent-specific data
    LEFT JOIN lineup_aggregates la
        ON pg.game_pk = la.game_pk AND pg.player_lookup = la.pitcher_lookup
    WHERE p.game_date >= '{start_date}'
      AND p.game_date <= '{end_date}'
      AND p.strikeouts IS NOT NULL
      AND p.innings_pitched >= 3.0  -- Starters only
      AND p.rolling_stats_games >= 3  -- Minimum history
    ORDER BY p.game_date, p.game_id
    {limit_clause}
    """

    print(f"Querying data from {start_date} to {end_date}...")
    df = client.query(query).to_dataframe()
    print(f"Retrieved {len(df)} pitcher games")
    return df


def generate_predictions(model: xgb.Booster, df: pd.DataFrame) -> pd.DataFrame:
    """Generate predictions using the model."""
    print("Generating predictions...")

    # Extract feature matrix
    X = df[FEATURE_COLUMNS].values
    dmatrix = xgb.DMatrix(X, feature_names=FEATURE_COLUMNS)

    # Generate predictions
    predictions = model.predict(dmatrix)

    # Add predictions to dataframe
    df = df.copy()
    df['predicted_strikeouts'] = predictions
    df['predicted_strikeouts'] = df['predicted_strikeouts'].round(2)

    # Calculate confidence based on feature completeness
    df['confidence'] = 0.8  # Base confidence

    # Calculate edge vs betting line (if available)
    df['edge'] = np.where(
        df['strikeouts_line'].notna(),
        df['predicted_strikeouts'] - df['strikeouts_line'],
        None
    )

    # Recommendation based on edge
    df['recommendation'] = np.where(
        df['edge'].isna(), 'NO_LINE',
        np.where(df['edge'] > 0.5, 'OVER',
        np.where(df['edge'] < -0.5, 'UNDER', 'PASS'))
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
        'line_accuracy': round(line_accuracy, 3) if line_accuracy else None
    }


def save_predictions(client: bigquery.Client, df: pd.DataFrame, dry_run: bool = False):
    """Save predictions to BigQuery."""
    if dry_run:
        print(f"DRY RUN: Would save {len(df)} predictions")
        return

    print(f"Saving {len(df)} predictions to {PREDICTIONS_TABLE}...")

    # Prepare records for BigQuery
    now = datetime.utcnow().isoformat()
    model_version = "mlb_pitcher_strikeouts_v1_20260107"

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
    parser = argparse.ArgumentParser(description='Generate historical MLB predictions')
    parser.add_argument('--start-date', default='2024-03-01', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', default='2025-09-30', help='End date (YYYY-MM-DD)')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of records')
    parser.add_argument('--dry-run', action='store_true', help='Do not save to BigQuery')
    args = parser.parse_args()

    print("=" * 80)
    print(" MLB HISTORICAL PREDICTION GENERATION")
    print("=" * 80)
    print(f"Date range: {args.start_date} to {args.end_date}")
    print(f"Dry run: {args.dry_run}")
    print()

    # Load model
    model = load_model()

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
    if metrics['line_accuracy']:
        print(f"Line accuracy: {metrics['line_accuracy']:.1%} ({metrics['with_lines']} games with lines)")
    print()

    # Show sample predictions
    print("Sample predictions:")
    sample = df[['game_date', 'pitcher_name', 'team_abbr', 'opponent_team_abbr',
                  'predicted_strikeouts', 'actual_strikeouts', 'strikeouts_line']].head(10)
    print(sample.to_string(index=False))
    print()

    # Save predictions
    save_predictions(client, df, args.dry_run)

    print()
    print("=" * 80)
    print(" COMPLETE")
    print("=" * 80)


if __name__ == '__main__':
    main()
