#!/usr/bin/env python3
"""
V1 vs V1.6 Head-to-Head Comparison

Comprehensive comparison of V1 and V1.6 models on identical games.
Analyzes where models agree/disagree and which performs better.

Usage:
    PYTHONPATH=. python scripts/mlb/compare_v1_vs_v16_head_to_head.py
    PYTHONPATH=. python scripts/mlb/compare_v1_vs_v16_head_to_head.py --export-csv
"""

import argparse
from datetime import datetime
import pandas as pd
from google.cloud import bigquery
from tabulate import tabulate


PROJECT_ID = "nba-props-platform"


def main():
    parser = argparse.ArgumentParser(description='Compare V1 vs V1.6 head-to-head')
    parser.add_argument('--export-csv', action='store_true', help='Export results to CSV')
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    print("=" * 80)
    print(" V1 vs V1.6 HEAD-TO-HEAD COMPARISON")
    print("=" * 80)
    print()

    # 1. Overall Performance
    print("1️⃣  OVERALL PERFORMANCE")
    print("-" * 80)

    overall_query = """
    SELECT
      CASE
        WHEN model_version LIKE '%v1_6%' THEN 'V1.6'
        ELSE 'V1'
      END as model,
      COUNT(*) as predictions,
      COUNTIF(is_correct IS NOT NULL) as graded,
      COUNTIF(is_correct = TRUE) as wins,
      COUNTIF(is_correct = FALSE) as losses,
      ROUND(AVG(CASE WHEN is_correct IS NOT NULL THEN CAST(is_correct AS INT64) END) * 100, 1) as win_rate,
      ROUND(AVG(CASE WHEN is_correct IS NOT NULL THEN ABS(predicted_strikeouts - actual_strikeouts) END), 2) as mae,
      ROUND(AVG(CASE WHEN is_correct IS NOT NULL THEN predicted_strikeouts - actual_strikeouts END), 2) as bias
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    GROUP BY model
    ORDER BY model
    """

    overall_df = client.query(overall_query).to_dataframe()
    print(tabulate(overall_df, headers='keys', tablefmt='simple', showindex=False))
    print()

    # Winner
    if len(overall_df) == 2:
        v1_wr = overall_df[overall_df['model'] == 'V1']['win_rate'].values[0]
        v16_wr = overall_df[overall_df['model'] == 'V1.6']['win_rate'].values[0]

        if v16_wr > v1_wr + 1:
            print(f"🏆 V1.6 WINS: {v16_wr}% vs {v1_wr}% (+{v16_wr - v1_wr:.1f}%)")
        elif v1_wr > v16_wr + 1:
            print(f"🏆 V1 WINS: {v1_wr}% vs {v16_wr}% (+{v1_wr - v16_wr:.1f}%)")
        else:
            print(f"🤝 TIE: V1 {v1_wr}% vs V1.6 {v16_wr}% (within 1%)")

    # 2. By Recommendation Type
    print("\n2️⃣  PERFORMANCE BY RECOMMENDATION TYPE")
    print("-" * 80)

    by_rec_query = """
    SELECT
      CASE WHEN model_version LIKE '%v1_6%' THEN 'V1.6' ELSE 'V1' END as model,
      recommendation,
      COUNT(*) as bets,
      COUNTIF(is_correct = TRUE) as wins,
      COUNTIF(is_correct = FALSE) as losses,
      ROUND(AVG(CAST(is_correct AS INT64)) * 100, 1) as win_rate
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE is_correct IS NOT NULL
      AND recommendation IN ('OVER', 'UNDER')
    GROUP BY model, recommendation
    ORDER BY model, recommendation
    """

    by_rec_df = client.query(by_rec_query).to_dataframe()
    print(tabulate(by_rec_df, headers='keys', tablefmt='simple', showindex=False))
    print()

    # 3. Head-to-Head (Same Games)
    print("3️⃣  HEAD-TO-HEAD COMPARISON (Same Games)")
    print("-" * 80)

    h2h_query = """
    WITH v1_preds AS (
      SELECT
        game_date,
        pitcher_lookup,
        predicted_strikeouts as v1_pred,
        recommendation as v1_rec,
        is_correct as v1_correct,
        actual_strikeouts
      FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
      WHERE model_version = 'mlb_pitcher_strikeouts_v1_20260107'
    ),
    v16_preds AS (
      SELECT
        game_date,
        pitcher_lookup,
        predicted_strikeouts as v16_pred,
        recommendation as v16_rec,
        is_correct as v16_correct
      FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
      WHERE model_version LIKE '%v1_6%'
    )
    SELECT
      COUNT(*) as head_to_head_games,
      COUNTIF(v1_correct = TRUE AND v16_correct = FALSE) as v1_only_correct,
      COUNTIF(v1_correct = FALSE AND v16_correct = TRUE) as v16_only_correct,
      COUNTIF(v1_correct = TRUE AND v16_correct = TRUE) as both_correct,
      COUNTIF(v1_correct = FALSE AND v16_correct = FALSE) as both_wrong,
      COUNTIF(v1_correct IS NULL OR v16_correct IS NULL) as incomplete,
      ROUND(AVG(ABS(v1_pred - actual_strikeouts)), 2) as v1_mae,
      ROUND(AVG(ABS(v16_pred - actual_strikeouts)), 2) as v16_mae,
      ROUND(AVG(v1_pred - actual_strikeouts), 2) as v1_bias,
      ROUND(AVG(v16_pred - actual_strikeouts), 2) as v16_bias
    FROM v1_preds
    INNER JOIN v16_preds USING (game_date, pitcher_lookup)
    """

    h2h_result = list(client.query(h2h_query).result())[0]

    print(f"Total head-to-head games: {h2h_result.head_to_head_games}")
    print(f"  V1 only correct: {h2h_result.v1_only_correct}")
    print(f"  V1.6 only correct: {h2h_result.v16_only_correct}")
    print(f"  Both correct: {h2h_result.both_correct}")
    print(f"  Both wrong: {h2h_result.both_wrong}")
    print(f"  Incomplete (not graded): {h2h_result.incomplete}")
    print()
    print(f"MAE comparison:")
    print(f"  V1 MAE: {h2h_result.v1_mae}")
    print(f"  V1.6 MAE: {h2h_result.v16_mae}")
    print(f"  Difference: {h2h_result.v1_mae - h2h_result.v16_mae:+.2f} (negative = V1.6 better)")
    print()
    print(f"Bias comparison:")
    print(f"  V1 bias: {h2h_result.v1_bias:+.2f}")
    print(f"  V1.6 bias: {h2h_result.v16_bias:+.2f}")
    print()

    # 4. Agreement Analysis
    print("4️⃣  AGREEMENT ANALYSIS")
    print("-" * 80)

    agreement_query = """
    WITH both_models AS (
      SELECT
        v1.game_date,
        v1.pitcher_lookup,
        v1.recommendation as v1_rec,
        v16.recommendation as v16_rec,
        v1.is_correct as v1_correct,
        v16.is_correct as v16_correct
      FROM (
        SELECT * FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
        WHERE model_version = 'mlb_pitcher_strikeouts_v1_20260107'
      ) v1
      INNER JOIN (
        SELECT * FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
        WHERE model_version LIKE '%v1_6%'
      ) v16
      USING (game_date, pitcher_lookup)
    )
    SELECT
      CASE
        WHEN v1_rec = v16_rec THEN 'AGREE'
        ELSE 'DISAGREE'
      END as agreement,
      v1_rec,
      v16_rec,
      COUNT(*) as cases,
      COUNTIF(v1_correct = TRUE) as v1_wins,
      COUNTIF(v16_correct = TRUE) as v16_wins,
      ROUND(AVG(CAST(v1_correct AS INT64)) * 100, 1) as v1_win_rate,
      ROUND(AVG(CAST(v16_correct AS INT64)) * 100, 1) as v16_win_rate
    FROM both_models
    WHERE v1_rec IN ('OVER', 'UNDER', 'PASS')
      AND v16_rec IN ('OVER', 'UNDER', 'PASS')
      AND v1_correct IS NOT NULL
      AND v16_correct IS NOT NULL
    GROUP BY agreement, v1_rec, v16_rec
    ORDER BY cases DESC
    """

    agreement_df = client.query(agreement_query).to_dataframe()
    print(tabulate(agreement_df, headers='keys', tablefmt='simple', showindex=False))
    print()

    # Calculate agreement rate
    if len(agreement_df) > 0:
        total_compared = agreement_df['cases'].sum()
        agreed = agreement_df[agreement_df['agreement'] == 'AGREE']['cases'].sum()
        agreement_rate = (agreed / total_compared * 100) if total_compared > 0 else 0
        print(f"Agreement rate: {agreement_rate:.1f}% ({agreed:,}/{total_compared:,} games)")
        print()

    # 5. By Confidence Level
    print("5️⃣  PERFORMANCE BY CONFIDENCE LEVEL")
    print("-" * 80)

    confidence_query = """
    SELECT
      CASE WHEN model_version LIKE '%v1_6%' THEN 'V1.6' ELSE 'V1' END as model,
      CASE
        WHEN confidence < 60 THEN 'Low (0-60)'
        WHEN confidence < 75 THEN 'Medium (60-75)'
        WHEN confidence < 90 THEN 'High (75-90)'
        ELSE 'Very High (90+)'
      END as confidence_bucket,
      COUNT(*) as bets,
      COUNTIF(is_correct = TRUE) as wins,
      ROUND(AVG(CAST(is_correct AS INT64)) * 100, 1) as win_rate
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE is_correct IS NOT NULL
      AND recommendation IN ('OVER', 'UNDER')
    GROUP BY model, confidence_bucket
    ORDER BY model,
      CASE confidence_bucket
        WHEN 'Low (0-60)' THEN 1
        WHEN 'Medium (60-75)' THEN 2
        WHEN 'High (75-90)' THEN 3
        ELSE 4
      END
    """

    confidence_df = client.query(confidence_query).to_dataframe()
    print(tabulate(confidence_df, headers='keys', tablefmt='simple', showindex=False))
    print()

    # 6. Export to CSV if requested
    if args.export_csv:
        print("6️⃣  EXPORTING TO CSV")
        print("-" * 80)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        overall_df.to_csv(f'v1_vs_v16_overall_{timestamp}.csv', index=False)
        print(f"✅ Exported: v1_vs_v16_overall_{timestamp}.csv")

        by_rec_df.to_csv(f'v1_vs_v16_by_recommendation_{timestamp}.csv', index=False)
        print(f"✅ Exported: v1_vs_v16_by_recommendation_{timestamp}.csv")

        agreement_df.to_csv(f'v1_vs_v16_agreement_{timestamp}.csv', index=False)
        print(f"✅ Exported: v1_vs_v16_agreement_{timestamp}.csv")

        confidence_df.to_csv(f'v1_vs_v16_confidence_{timestamp}.csv', index=False)
        print(f"✅ Exported: v1_vs_v16_confidence_{timestamp}.csv")
        print()

    # Summary
    print("=" * 80)
    print(" SUMMARY")
    print("=" * 80)

    if len(overall_df) == 2:
        v1_stats = overall_df[overall_df['model'] == 'V1'].iloc[0]
        v16_stats = overall_df[overall_df['model'] == 'V1.6'].iloc[0]

        print(f"V1:  {v1_stats['win_rate']}% win rate, {v1_stats['mae']} MAE")
        print(f"V1.6: {v16_stats['win_rate']}% win rate, {v16_stats['mae']} MAE")
        print()

        # Recommendation
        if v16_stats['win_rate'] >= v1_stats['win_rate'] + 1:
            print("✅ RECOMMENDATION: Consider switching to V1.6 (better performance)")
        elif v16_stats['win_rate'] >= v1_stats['win_rate'] - 1:
            print("⚠️  RECOMMENDATION: A/B test V1.6 (comparable performance)")
        else:
            print("❌ RECOMMENDATION: Keep V1 (V1.6 underperforms)")
    else:
        print("⚠️  Only one model found - cannot compare")

    print()


if __name__ == '__main__':
    main()
