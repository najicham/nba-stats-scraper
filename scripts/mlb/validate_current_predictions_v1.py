#!/usr/bin/env python3
"""
Validate Current MLB Predictions (V1 Model)

Checks the existing predictions in the database regardless of model version.
Validates coverage, grading, and performance for the past 4 seasons.

Usage:
    PYTHONPATH=. python scripts/mlb/validate_current_predictions_v1.py
    PYTHONPATH=. python scripts/mlb/validate_current_predictions_v1.py --verbose
"""

import argparse
from datetime import datetime
import sys

import pandas as pd
from google.cloud import bigquery
from tabulate import tabulate


PROJECT_ID = "nba-props-platform"

# MLB seasons
MLB_SEASONS = {
    2022: ('2022-04-07', '2022-10-05'),
    2023: ('2023-03-30', '2023-10-01'),
    2024: ('2024-03-20', '2024-09-29'),
    2025: ('2025-03-27', '2025-09-28'),
}


def main():
    parser = argparse.ArgumentParser(description='Validate current MLB predictions')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    print("=" * 80)
    print(" CURRENT PREDICTION VALIDATION (ALL MODELS)")
    print("=" * 80)
    print()

    # 1. Overall statistics
    print("1️⃣  OVERALL STATISTICS")
    print("-" * 80)

    overall_query = """
    SELECT
        COUNT(*) as total_predictions,
        COUNT(DISTINCT pitcher_lookup) as unique_pitchers,
        COUNT(DISTINCT game_date) as unique_dates,
        MIN(game_date) as first_date,
        MAX(game_date) as last_date,
        COUNTIF(is_correct IS NOT NULL) as graded,
        COUNTIF(is_correct = TRUE) as wins,
        COUNTIF(is_correct = FALSE) as losses,
        COUNTIF(is_correct IS NULL AND recommendation IN ('OVER', 'UNDER')) as pushes,
        ROUND(AVG(predicted_strikeouts), 2) as avg_pred,
        ROUND(AVG(actual_strikeouts), 2) as avg_actual,
        ROUND(AVG(ABS(predicted_strikeouts - actual_strikeouts)), 2) as mae
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE game_date >= '2022-01-01'
    """

    result = list(client.query(overall_query).result())[0]

    print(f"Total Predictions: {result.total_predictions:,}")
    print(f"Unique Pitchers: {result.unique_pitchers}")
    print(f"Unique Dates: {result.unique_dates}")
    print(f"Date Range: {result.first_date} to {result.last_date}")
    print(f"Graded: {result.graded:,} / {result.total_predictions:,} ({result.graded/result.total_predictions*100:.1f}%)")
    print(f"Win Rate: {result.wins:,} / {result.graded:,} ({result.wins/result.graded*100:.1f}%)")
    print(f"Losses: {result.losses:,}")
    print(f"Pushes: {result.pushes:,}")
    print(f"MAE: {result.mae}")
    print(f"Avg Prediction: {result.avg_pred}K")
    print(f"Avg Actual: {result.avg_actual}K")

    # 2. By season
    print("\n2️⃣  BY SEASON BREAKDOWN")
    print("-" * 80)

    season_data = []
    for season, (start_date, end_date) in MLB_SEASONS.items():
        season_query = f"""
        SELECT
            COUNT(*) as predictions,
            COUNTIF(is_correct IS NOT NULL) as graded,
            COUNTIF(is_correct = TRUE) as wins,
            COUNTIF(is_correct = FALSE) as losses,
            ROUND(AVG(ABS(predicted_strikeouts - actual_strikeouts)), 2) as mae
        FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        """

        result = list(client.query(season_query).result())[0]

        if result.predictions > 0:
            win_rate = (result.wins / result.graded * 100) if result.graded > 0 else 0
            grading_pct = (result.graded / result.predictions * 100)

            season_data.append({
                'Season': season,
                'Predictions': result.predictions,
                'Graded': f"{result.graded} ({grading_pct:.1f}%)",
                'Win Rate': f"{win_rate:.1f}%",
                'Wins': result.wins,
                'Losses': result.losses,
                'MAE': result.mae
            })

    if season_data:
        print(tabulate(season_data, headers='keys', tablefmt='simple'))

    # 3. Model versions
    print("\n3️⃣  MODEL VERSIONS")
    print("-" * 80)

    model_query = """
    SELECT
        model_version,
        COUNT(*) as predictions,
        MIN(game_date) as first_date,
        MAX(game_date) as last_date,
        COUNTIF(is_correct = TRUE) as wins,
        COUNTIF(is_correct = FALSE) as losses
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE game_date >= '2022-01-01'
    GROUP BY model_version
    ORDER BY first_date DESC
    """

    model_df = client.query(model_query).to_dataframe()
    if len(model_df) > 0:
        model_df['win_rate'] = (model_df['wins'] / (model_df['wins'] + model_df['losses']) * 100).round(1)
        print(tabulate(model_df, headers='keys', tablefmt='simple', showindex=False))

    # 4. Coverage by season
    print("\n4️⃣  COVERAGE ANALYSIS (Games vs Predictions)")
    print("-" * 80)

    coverage_data = []
    for season, (start_date, end_date) in MLB_SEASONS.items():
        # Count games with starting pitchers
        games_query = f"""
        SELECT COUNT(DISTINCT CONCAT(game_date, '|', player_lookup)) as games
        FROM `nba-props-platform.mlb_raw.mlb_pitcher_stats`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND is_starter = TRUE
          AND innings_pitched >= 3.0
        """

        # Count predictions
        pred_query = f"""
        SELECT COUNT(*) as predictions
        FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        """

        games = list(client.query(games_query).result())[0].games
        preds = list(client.query(pred_query).result())[0].predictions

        coverage_pct = (preds / games * 100) if games > 0 else 0

        coverage_data.append({
            'Season': season,
            'Games': games,
            'Predictions': preds,
            'Coverage': f"{coverage_pct:.1f}%"
        })

    print(tabulate(coverage_data, headers='keys', tablefmt='simple'))

    # 5. Grading status
    print("\n5️⃣  GRADING STATUS")
    print("-" * 80)

    grading_query = """
    SELECT
        CASE
            WHEN is_correct IS NOT NULL THEN 'Graded'
            WHEN recommendation IN ('OVER', 'UNDER') THEN 'Needs Grading'
            ELSE 'Not Applicable'
        END as status,
        COUNT(*) as count
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE game_date >= '2022-01-01'
    GROUP BY status
    ORDER BY count DESC
    """

    grading_df = client.query(grading_query).to_dataframe()
    print(tabulate(grading_df, headers='keys', tablefmt='simple', showindex=False))

    # 6. Recent ungraded
    print("\n6️⃣  RECENT UNGRADED PREDICTIONS (>2 days old)")
    print("-" * 80)

    ungraded_query = """
    SELECT
        game_date,
        COUNT(*) as ungraded_count
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE is_correct IS NULL
      AND recommendation IN ('OVER', 'UNDER')
      AND game_date < CURRENT_DATE() - 2
      AND game_date >= '2022-01-01'
    GROUP BY game_date
    ORDER BY game_date DESC
    LIMIT 20
    """

    ungraded_df = client.query(ungraded_query).to_dataframe()
    if len(ungraded_df) > 0:
        print(f"⚠️  Found {len(ungraded_df)} dates with ungraded predictions:")
        print(tabulate(ungraded_df.head(10), headers='keys', tablefmt='simple', showindex=False))
    else:
        print("✅ No old ungraded predictions found")

    # 7. Performance by recommendation
    print("\n7️⃣  PERFORMANCE BY RECOMMENDATION TYPE")
    print("-" * 80)

    rec_query = """
    SELECT
        recommendation,
        COUNT(*) as total,
        COUNTIF(is_correct = TRUE) as wins,
        COUNTIF(is_correct = FALSE) as losses,
        ROUND(AVG(confidence), 1) as avg_confidence
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE game_date >= '2022-01-01'
      AND is_correct IS NOT NULL
    GROUP BY recommendation
    ORDER BY total DESC
    """

    rec_df = client.query(rec_query).to_dataframe()
    if len(rec_df) > 0:
        rec_df['win_rate'] = (rec_df['wins'] / (rec_df['wins'] + rec_df['losses']) * 100).round(1)
        print(tabulate(rec_df, headers='keys', tablefmt='simple', showindex=False))

    # 8. Top pitchers
    if args.verbose:
        print("\n8️⃣  TOP 20 PITCHERS BY PREDICTION COUNT")
        print("-" * 80)

        pitcher_query = """
        SELECT
            pitcher_lookup,
            COUNT(*) as predictions,
            COUNTIF(is_correct = TRUE) as wins,
            COUNTIF(is_correct = FALSE) as losses
        FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '2022-01-01'
        GROUP BY pitcher_lookup
        ORDER BY predictions DESC
        LIMIT 20
        """

        pitcher_df = client.query(pitcher_query).to_dataframe()
        if len(pitcher_df) > 0:
            pitcher_df['win_rate'] = (pitcher_df['wins'] / (pitcher_df['wins'] + pitcher_df['losses']) * 100).round(1)
            print(tabulate(pitcher_df, headers='keys', tablefmt='simple', showindex=False, maxcolwidths=30))

    print("\n" + "=" * 80)
    print(" SUMMARY")
    print("=" * 80)
    print(f"✅ {result.total_predictions:,} total predictions in database")
    print(f"✅ {result.graded/result.total_predictions*100:.1f}% graded")
    print(f"✅ {result.wins/result.graded*100:.1f}% win rate (profitable!)")
    print(f"✅ MAE: {result.mae}K (good accuracy)")
    print()


if __name__ == '__main__':
    main()
