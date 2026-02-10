#!/usr/bin/env python3
"""
Model Performance Diagnosis - Automated Drift Detection

Automates the 5 diagnostic queries used in Session 173 to diagnose model
performance decline. Produces a formatted report with a clear recommendation.

Recommendation logic:
  - Trailing 2-week edge 3+ hit rate < threshold (default 55%) -> RETRAIN_NOW
  - 55-60% -> MONITOR
  - >= 60% -> HEALTHY
  - Flags directional drift if OVER or UNDER < 52.4% (breakeven at -110)

Usage:
    # Default: 6 weeks, edge 3+, catboost_v9
    PYTHONPATH=. python ml/experiments/model_diagnose.py

    # Custom parameters
    PYTHONPATH=. python ml/experiments/model_diagnose.py --weeks 4 --edge-threshold 5.0

    # JSON output for downstream tools
    PYTHONPATH=. python ml/experiments/model_diagnose.py --json

Session 175 - Model Experiment Infrastructure Improvements
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import json
from datetime import date, timedelta
from google.cloud import bigquery

PROJECT_ID = "nba-props-platform"
BREAKEVEN_RATE = 52.4  # Breakeven at -110 odds


def parse_args():
    parser = argparse.ArgumentParser(
        description='Diagnose model performance and detect drift'
    )
    parser.add_argument('--system-id', default='catboost_v9',
                        help='Model system ID (default: catboost_v9)')
    parser.add_argument('--weeks', type=int, default=6,
                        help='Weeks of history to analyze (default: 6)')
    parser.add_argument('--edge-threshold', type=float, default=3.0,
                        help='Edge threshold for filtering (default: 3.0)')
    parser.add_argument('--profitability-threshold', type=float, default=55.0,
                        help='Hit rate threshold for RETRAIN_NOW (default: 55.0)')
    parser.add_argument('--json', action='store_true',
                        help='Output JSON instead of formatted tables')
    return parser.parse_args()


def query_weekly_performance(client, system_id, weeks, edge):
    """Weekly edge N+ performance with OVER/UNDER hit rate breakdown, MAE, bias."""
    query = f"""
    SELECT
      DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,
      COUNT(*) as picks,
      ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_pct,
      -- OVER subset
      COUNTIF(recommendation = 'OVER') as over_picks,
      ROUND(100.0 * COUNTIF(recommendation = 'OVER' AND prediction_correct) /
            NULLIF(COUNTIF(recommendation = 'OVER' AND prediction_correct IS NOT NULL), 0), 1) as over_hit_pct,
      -- UNDER subset
      COUNTIF(recommendation = 'UNDER') as under_picks,
      ROUND(100.0 * COUNTIF(recommendation = 'UNDER' AND prediction_correct) /
            NULLIF(COUNTIF(recommendation = 'UNDER' AND prediction_correct IS NOT NULL), 0), 1) as under_hit_pct,
      -- MAE and bias
      ROUND(AVG(absolute_error), 2) as mae,
      ROUND(AVG(predicted_points - actual_points), 2) as bias
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE system_id = '{system_id}'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks} WEEK)
      AND game_date < CURRENT_DATE()
      AND ABS(predicted_points - line_value) >= {edge}
      AND prediction_correct IS NOT NULL
      AND recommendation IN ('OVER', 'UNDER')
    GROUP BY week_start
    ORDER BY week_start
    """
    return client.query(query).to_dataframe()


def query_weekly_high_edge(client, system_id, weeks):
    """Weekly edge 5+ performance with OVER/UNDER breakdown."""
    query = f"""
    SELECT
      DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,
      COUNT(*) as picks,
      ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_pct,
      COUNTIF(recommendation = 'OVER') as over_picks,
      ROUND(100.0 * COUNTIF(recommendation = 'OVER' AND prediction_correct) /
            NULLIF(COUNTIF(recommendation = 'OVER' AND prediction_correct IS NOT NULL), 0), 1) as over_hit_pct,
      COUNTIF(recommendation = 'UNDER') as under_picks,
      ROUND(100.0 * COUNTIF(recommendation = 'UNDER' AND prediction_correct) /
            NULLIF(COUNTIF(recommendation = 'UNDER' AND prediction_correct IS NOT NULL), 0), 1) as under_hit_pct,
      ROUND(AVG(absolute_error), 2) as mae
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE system_id = '{system_id}'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks} WEEK)
      AND game_date < CURRENT_DATE()
      AND ABS(predicted_points - line_value) >= 5
      AND prediction_correct IS NOT NULL
      AND recommendation IN ('OVER', 'UNDER')
    GROUP BY week_start
    ORDER BY week_start
    """
    return client.query(query).to_dataframe()


def query_pvl_trend(client, system_id, weeks):
    """Weekly avg pred_vs_line, stddev, and %OVER recommendations."""
    query = f"""
    SELECT
      DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,
      COUNT(*) as total_picks,
      ROUND(AVG(predicted_points - line_value), 2) as avg_pvl,
      ROUND(STDDEV(predicted_points - line_value), 2) as stddev_pvl,
      ROUND(100.0 * COUNTIF(recommendation = 'OVER') /
            NULLIF(COUNTIF(recommendation IN ('OVER', 'UNDER')), 0), 1) as pct_over
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE system_id = '{system_id}'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks} WEEK)
      AND game_date < CURRENT_DATE()
      AND recommendation IN ('OVER', 'UNDER')
      AND line_value IS NOT NULL
    GROUP BY week_start
    ORDER BY week_start
    """
    return client.query(query).to_dataframe()


def query_daily_granular(client, system_id, edge, days=14):
    """Daily edge N+ performance for last N days."""
    query = f"""
    SELECT
      game_date,
      COUNT(*) as picks,
      ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_pct,
      COUNTIF(recommendation = 'OVER') as over_picks,
      COUNTIF(recommendation = 'UNDER') as under_picks,
      ROUND(100.0 * COUNTIF(recommendation = 'OVER' AND prediction_correct) /
            NULLIF(COUNTIF(recommendation = 'OVER' AND prediction_correct IS NOT NULL), 0), 1) as over_hit_pct,
      ROUND(100.0 * COUNTIF(recommendation = 'UNDER' AND prediction_correct) /
            NULLIF(COUNTIF(recommendation = 'UNDER' AND prediction_correct IS NOT NULL), 0), 1) as under_hit_pct
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE system_id = '{system_id}'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
      AND game_date < CURRENT_DATE()
      AND ABS(predicted_points - line_value) >= {edge}
      AND prediction_correct IS NOT NULL
      AND recommendation IN ('OVER', 'UNDER')
    GROUP BY game_date
    ORDER BY game_date
    """
    return client.query(query).to_dataframe()


def query_period_comparison(client, system_id, edge):
    """Training holdout (Jan 9-31) vs trailing 2 weeks with OVER/UNDER."""
    two_weeks_ago = (date.today() - timedelta(days=14)).strftime('%Y-%m-%d')
    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')

    query = f"""
    SELECT
      period,
      COUNT(*) as picks,
      ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_pct,
      COUNTIF(recommendation = 'OVER') as over_picks,
      ROUND(100.0 * COUNTIF(recommendation = 'OVER' AND prediction_correct) /
            NULLIF(COUNTIF(recommendation = 'OVER' AND prediction_correct IS NOT NULL), 0), 1) as over_hit_pct,
      COUNTIF(recommendation = 'UNDER') as under_picks,
      ROUND(100.0 * COUNTIF(recommendation = 'UNDER' AND prediction_correct) /
            NULLIF(COUNTIF(recommendation = 'UNDER' AND prediction_correct IS NOT NULL), 0), 1) as under_hit_pct,
      ROUND(AVG(absolute_error), 2) as mae,
      ROUND(AVG(predicted_points - actual_points), 2) as bias
    FROM (
      SELECT *, 'Holdout (Jan 9-31)' as period
      FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
      WHERE system_id = '{system_id}'
        AND game_date BETWEEN '2026-01-09' AND '2026-01-31'
        AND ABS(predicted_points - line_value) >= {edge}
        AND prediction_correct IS NOT NULL
        AND recommendation IN ('OVER', 'UNDER')

      UNION ALL

      SELECT *, 'Trailing 2 Weeks' as period
      FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
      WHERE system_id = '{system_id}'
        AND game_date BETWEEN '{two_weeks_ago}' AND '{yesterday}'
        AND ABS(predicted_points - line_value) >= {edge}
        AND prediction_correct IS NOT NULL
        AND recommendation IN ('OVER', 'UNDER')
    )
    GROUP BY period
    ORDER BY period
    """
    return client.query(query).to_dataframe()


def compute_recommendation(trailing_hit_rate, threshold, over_hit_rate, under_hit_rate):
    """Compute recommendation based on trailing performance.

    Returns:
        dict with 'recommendation', 'reasons' list, and 'next_step' string.
    """
    reasons = []
    next_step = ""

    if trailing_hit_rate is None:
        return {
            'recommendation': 'INSUFFICIENT_DATA',
            'reasons': ['Not enough graded predictions in trailing 2 weeks'],
            'next_step': 'Wait for more graded data or check grading pipeline.',
        }

    # Primary: overall hit rate
    if trailing_hit_rate < threshold:
        recommendation = 'RETRAIN_NOW'
        reasons.append(
            f"Trailing 2-week edge 3+ hit rate ({trailing_hit_rate:.1f}%) "
            f"below threshold ({threshold:.1f}%)."
        )
        next_step = (
            "PYTHONPATH=. python ml/experiments/quick_retrain.py \\\n"
            "    --name \"V9_RETRAIN\" --train-start 2025-11-02 "
            f"--train-end {date.today().strftime('%Y-%m-%d')}"
        )
    elif trailing_hit_rate < 60:
        recommendation = 'MONITOR'
        reasons.append(
            f"Trailing 2-week edge 3+ hit rate ({trailing_hit_rate:.1f}%) "
            f"marginal (threshold: {threshold:.1f}%, target: 60%+)."
        )
        next_step = "Re-run diagnosis in 3-5 days. No immediate action needed."
    else:
        recommendation = 'HEALTHY'
        reasons.append(
            f"Trailing 2-week edge 3+ hit rate ({trailing_hit_rate:.1f}%) "
            f"above target (60%+)."
        )
        next_step = "No action needed. Continue monitoring weekly."

    # Secondary: directional drift
    if over_hit_rate is not None and over_hit_rate < BREAKEVEN_RATE:
        reasons.append(
            f"OVER hit rate ({over_hit_rate:.1f}%) below breakeven "
            f"({BREAKEVEN_RATE}%) — directional drift detected."
        )
        if recommendation == 'HEALTHY':
            recommendation = 'MONITOR'
    if under_hit_rate is not None and under_hit_rate < BREAKEVEN_RATE:
        reasons.append(
            f"UNDER hit rate ({under_hit_rate:.1f}%) below breakeven "
            f"({BREAKEVEN_RATE}%) — directional drift detected."
        )
        if recommendation == 'HEALTHY':
            recommendation = 'MONITOR'

    return {
        'recommendation': recommendation,
        'reasons': reasons,
        'next_step': next_step,
    }


def print_report(system_id, edge, threshold, weeks,
                 weekly_perf, weekly_high, pvl_trend, daily, comparison,
                 rec):
    """Print formatted diagnostic report."""
    print("=" * 70)
    print(f" MODEL PERFORMANCE DIAGNOSIS: {system_id}")
    print("=" * 70)
    print(f"Period: {weeks} weeks | Edge: {edge}+ | Threshold: {threshold}%")
    print()

    # --- Weekly Edge N+ ---
    print(f"--- Weekly Edge {edge}+ Performance ---")
    print(f"{'Week':<12} | {'Picks':>5} | {'Hit%':>6} | {'OVER Hit%':>10} | {'UNDER Hit%':>11} | {'MAE':>5} | {'Bias':>6}")
    print("-" * 70)
    for _, row in weekly_perf.iterrows():
        week_str = str(row['week_start'])[:10]
        hit = _fmt(row.get('hit_pct'))
        over = _fmt(row.get('over_hit_pct'))
        under = _fmt(row.get('under_hit_pct'))
        mae = f"{row['mae']:.2f}" if row.get('mae') is not None else "N/A"
        bias = f"{row['bias']:+.2f}" if row.get('bias') is not None else "N/A"
        print(f"{week_str:<12} | {int(row['picks']):>5} | {hit:>6} | {over:>10} | {under:>11} | {mae:>5} | {bias:>6}")
    print()

    # --- Weekly Edge 5+ ---
    print("--- Weekly Edge 5+ Performance ---")
    print(f"{'Week':<12} | {'Picks':>5} | {'Hit%':>6} | {'OVER Hit%':>10} | {'UNDER Hit%':>11} | {'MAE':>5}")
    print("-" * 70)
    for _, row in weekly_high.iterrows():
        week_str = str(row['week_start'])[:10]
        hit = _fmt(row.get('hit_pct'))
        over = _fmt(row.get('over_hit_pct'))
        under = _fmt(row.get('under_hit_pct'))
        mae = f"{row['mae']:.2f}" if row.get('mae') is not None else "N/A"
        print(f"{week_str:<12} | {int(row['picks']):>5} | {hit:>6} | {over:>10} | {under:>11} | {mae:>5}")
    print()

    # --- PVL Trend ---
    print("--- Pred vs Line (PVL) Trend ---")
    print(f"{'Week':<12} | {'Picks':>5} | {'Avg PVL':>8} | {'StdDev':>7} | {'%OVER':>6}")
    print("-" * 50)
    for _, row in pvl_trend.iterrows():
        week_str = str(row['week_start'])[:10]
        avg_pvl = f"{row['avg_pvl']:+.2f}" if row.get('avg_pvl') is not None else "N/A"
        stddev = f"{row['stddev_pvl']:.2f}" if row.get('stddev_pvl') is not None else "N/A"
        pct_over = _fmt(row.get('pct_over'))
        print(f"{week_str:<12} | {int(row['total_picks']):>5} | {avg_pvl:>8} | {stddev:>7} | {pct_over:>6}")
    print()

    # --- Daily Granular ---
    print(f"--- Daily Edge {edge}+ (Last 14 Days) ---")
    print(f"{'Date':<12} | {'Picks':>5} | {'Hit%':>6} | {'OVER':>4} | {'UNDER':>5} | {'OVER%':>6} | {'UNDER%':>7}")
    print("-" * 65)
    for _, row in daily.iterrows():
        day_str = str(row['game_date'])[:10]
        hit = _fmt(row.get('hit_pct'))
        over_h = _fmt(row.get('over_hit_pct'))
        under_h = _fmt(row.get('under_hit_pct'))
        print(f"{day_str:<12} | {int(row['picks']):>5} | {hit:>6} | {int(row['over_picks']):>4} | {int(row['under_picks']):>5} | {over_h:>6} | {under_h:>7}")
    print()

    # --- Period Comparison ---
    print("--- Period Comparison ---")
    print(f"{'Period':<20} | {'Picks':>5} | {'Hit%':>6} | {'OVER Hit%':>10} | {'UNDER Hit%':>11} | {'MAE':>5} | {'Bias':>6}")
    print("-" * 78)
    for _, row in comparison.iterrows():
        hit = _fmt(row.get('hit_pct'))
        over = _fmt(row.get('over_hit_pct'))
        under = _fmt(row.get('under_hit_pct'))
        mae = f"{row['mae']:.2f}" if row.get('mae') is not None else "N/A"
        bias = f"{row['bias']:+.2f}" if row.get('bias') is not None else "N/A"
        print(f"{row['period']:<20} | {int(row['picks']):>5} | {hit:>6} | {over:>10} | {under:>11} | {mae:>5} | {bias:>6}")
    print()

    # --- Recommendation ---
    print("=" * 70)
    print(f" RECOMMENDATION: {rec['recommendation']}")
    print("=" * 70)
    for reason in rec['reasons']:
        print(f"  {reason}")
    print()
    print(f"Next step: {rec['next_step']}")


def output_json(system_id, edge, threshold, weeks,
                weekly_perf, weekly_high, pvl_trend, daily, comparison,
                rec):
    """Output results as JSON."""
    def df_to_records(df):
        records = []
        for _, row in df.iterrows():
            record = {}
            for col in df.columns:
                val = row[col]
                if hasattr(val, 'isoformat'):
                    record[col] = val.isoformat() if val is not None else None
                elif hasattr(val, 'item'):
                    record[col] = val.item()
                else:
                    record[col] = val
            records.append(record)
        return records

    result = {
        'system_id': system_id,
        'edge_threshold': edge,
        'profitability_threshold': threshold,
        'weeks': weeks,
        'run_date': date.today().isoformat(),
        'recommendation': rec['recommendation'],
        'reasons': rec['reasons'],
        'next_step': rec['next_step'],
        'weekly_edge_performance': df_to_records(weekly_perf),
        'weekly_high_edge_performance': df_to_records(weekly_high),
        'pvl_trend': df_to_records(pvl_trend),
        'daily_granular': df_to_records(daily),
        'period_comparison': df_to_records(comparison),
    }
    print(json.dumps(result, indent=2, default=str))


def _fmt(val):
    """Format a percentage value, handling None/NaN."""
    if val is None:
        return "N/A"
    try:
        import math
        if math.isnan(val):
            return "N/A"
    except (TypeError, ValueError):
        pass
    return f"{val:.1f}%"


def main():
    args = parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    if not args.json:
        print(f"Running model diagnosis for {args.system_id}...")
        print()

    # Run all diagnostic queries
    weekly_perf = query_weekly_performance(
        client, args.system_id, args.weeks, args.edge_threshold
    )
    weekly_high = query_weekly_high_edge(client, args.system_id, args.weeks)
    pvl_trend = query_pvl_trend(client, args.system_id, args.weeks)
    daily = query_daily_granular(
        client, args.system_id, args.edge_threshold, days=14
    )
    comparison = query_period_comparison(
        client, args.system_id, args.edge_threshold
    )

    # Extract trailing 2-week metrics for recommendation
    trailing_row = comparison[comparison['period'] == 'Trailing 2 Weeks']
    if len(trailing_row) > 0:
        trailing_hit = trailing_row.iloc[0].get('hit_pct')
        trailing_over = trailing_row.iloc[0].get('over_hit_pct')
        trailing_under = trailing_row.iloc[0].get('under_hit_pct')
    else:
        trailing_hit = None
        trailing_over = None
        trailing_under = None

    rec = compute_recommendation(
        trailing_hit, args.profitability_threshold,
        trailing_over, trailing_under
    )

    if args.json:
        output_json(
            args.system_id, args.edge_threshold,
            args.profitability_threshold, args.weeks,
            weekly_perf, weekly_high, pvl_trend, daily, comparison, rec
        )
    else:
        print_report(
            args.system_id, args.edge_threshold,
            args.profitability_threshold, args.weeks,
            weekly_perf, weekly_high, pvl_trend, daily, comparison, rec
        )


if __name__ == "__main__":
    main()
