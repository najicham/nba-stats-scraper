#!/usr/bin/env python3
"""
Compare Model Performance — Backtest vs Production

Session 177: Compares a challenger model's production graded results against
its backtest metrics from MONTHLY_MODELS config and the champion's performance.

Usage:
    python bin/compare-model-performance.py catboost_v9_train1102_0108
    python bin/compare-model-performance.py catboost_v9_train1102_0108 --days 14
    python bin/compare-model-performance.py --list  # Show all challengers
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from google.cloud import bigquery

from predictions.worker.prediction_systems.catboost_monthly import MONTHLY_MODELS

PROJECT_ID = "nba-props-platform"
CHAMPION_SYSTEM_ID = "catboost_v9"


def parse_args():
    parser = argparse.ArgumentParser(description='Compare model backtest vs production performance')
    parser.add_argument('system_id', nargs='?', help='Challenger system_id from MONTHLY_MODELS')
    parser.add_argument('--days', type=int, default=7, help='Days of production data to compare (default: 7)')
    parser.add_argument('--list', action='store_true', help='List all challenger models')
    return parser.parse_args()


def list_models():
    """List all challenger models with their backtest metrics."""
    print("=== Challenger Models (MONTHLY_MODELS) ===\n")
    for model_id, config in MONTHLY_MODELS.items():
        status = "ENABLED" if config.get("enabled") else "DISABLED"
        print(f"  {model_id} [{status}]")
        print(f"    Train: {config.get('train_start')} to {config.get('train_end')}")
        if config.get('backtest_mae'):
            print(f"    Backtest MAE: {config['backtest_mae']}")
        if config.get('backtest_hit_rate_all'):
            print(f"    Backtest HR All: {config['backtest_hit_rate_all']}%")
        if config.get('backtest_hit_rate_edge_3plus'):
            print(f"    Backtest HR 3+: {config['backtest_hit_rate_edge_3plus']}% (n={config.get('backtest_n_edge_3plus', '?')})")
        print(f"    Description: {config.get('description', 'N/A')}")
        print()


def query_production_performance(client, system_id, days):
    """Query graded production performance for a system_id."""
    query = f"""
    WITH graded AS (
        SELECT
            game_date,
            predicted_points,
            actual_points,
            line_value,
            prediction_correct,
            recommendation,
            edge
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE system_id = '{system_id}'
          AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          AND prediction_correct IS NOT NULL
          AND line_value IS NOT NULL
          AND recommendation IN ('OVER', 'UNDER')
    )
    SELECT
        MIN(game_date) as first_date,
        MAX(game_date) as last_date,
        COUNT(DISTINCT game_date) as game_days,
        COUNT(*) as total_graded,
        ROUND(AVG(ABS(predicted_points - actual_points)), 3) as mae,
        ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate_all,
        -- Edge 3+
        COUNTIF(ABS(edge) >= 3) as n_edge_3plus,
        ROUND(100.0 * COUNTIF(prediction_correct AND ABS(edge) >= 3)
            / NULLIF(COUNTIF(ABS(edge) >= 3), 0), 1) as hit_rate_edge_3plus,
        -- Edge 5+
        COUNTIF(ABS(edge) >= 5) as n_edge_5plus,
        ROUND(100.0 * COUNTIF(prediction_correct AND ABS(edge) >= 5)
            / NULLIF(COUNTIF(ABS(edge) >= 5), 0), 1) as hit_rate_edge_5plus,
        -- Vegas bias
        ROUND(AVG(predicted_points - line_value), 2) as vegas_bias,
        -- Directional
        ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'OVER' AND ABS(edge) >= 3)
            / NULLIF(COUNTIF(recommendation = 'OVER' AND ABS(edge) >= 3), 0), 1) as over_hr_3plus,
        COUNTIF(recommendation = 'OVER' AND ABS(edge) >= 3) as over_n_3plus,
        ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'UNDER' AND ABS(edge) >= 3)
            / NULLIF(COUNTIF(recommendation = 'UNDER' AND ABS(edge) >= 3), 0), 1) as under_hr_3plus,
        COUNTIF(recommendation = 'UNDER' AND ABS(edge) >= 3) as under_n_3plus,
    FROM graded
    """
    result = client.query(query).to_dataframe()
    if len(result) == 0 or result['total_graded'].iloc[0] == 0:
        return None
    return result.iloc[0].to_dict()


def format_val(val, suffix='', na='N/A'):
    """Format a value with suffix, handling None/NaN."""
    if val is None or (isinstance(val, float) and val != val):  # NaN check
        return na
    return f"{val}{suffix}"


def main():
    args = parse_args()

    if args.list:
        list_models()
        return

    if not args.system_id:
        print("ERROR: Provide a system_id or use --list")
        print("Usage: python bin/compare-model-performance.py <system_id>")
        return

    system_id = args.system_id

    # Get config if it exists in MONTHLY_MODELS
    config = MONTHLY_MODELS.get(system_id)

    client = bigquery.Client(project=PROJECT_ID)

    # Query production performance for challenger and champion
    print(f"Querying production performance (last {args.days} days)...\n")
    challenger = query_production_performance(client, system_id, args.days)
    champion = query_production_performance(client, CHAMPION_SYSTEM_ID, args.days)

    # Header
    print("=" * 70)
    print(f" MODEL COMPARISON: {system_id}")
    print("=" * 70)

    if config:
        print(f"Training: {config.get('train_start')} to {config.get('train_end')}")
        print(f"Description: {config.get('description', 'N/A')}")
    print()

    if not challenger:
        print(f"No graded production data found for {system_id} in last {args.days} days.")
        print("The model may not have been deployed yet, or games haven't been graded.")
        if config:
            print("\nBacktest metrics (from training):")
            print(f"  MAE:        {format_val(config.get('backtest_mae'))}")
            print(f"  HR All:     {format_val(config.get('backtest_hit_rate_all'), '%')}")
            print(f"  HR Edge 3+: {format_val(config.get('backtest_hit_rate_edge_3plus'), '%')} "
                  f"(n={config.get('backtest_n_edge_3plus', '?')})")
        return

    # Production period info
    print(f"Production period: {challenger['first_date']} to {challenger['last_date']} "
          f"({challenger['game_days']} game days, {challenger['total_graded']} graded)")
    print()

    # Comparison table
    print(f"{'Metric':<25s} {'Backtest':<12s} {'Production':<12s} {'Gap':<12s}")
    print("-" * 61)

    def compare_row(name, backtest_val, prod_val, suffix='', higher_better=True):
        bt = format_val(backtest_val, suffix)
        pr = format_val(prod_val, suffix)
        if backtest_val is not None and prod_val is not None:
            gap = prod_val - backtest_val
            direction = "+" if gap > 0 else ""
            gap_str = f"{direction}{gap:.1f}{suffix}"
        else:
            gap_str = "—"
        print(f"  {name:<23s} {bt:<12s} {pr:<12s} {gap_str:<12s}")

    if config:
        compare_row("MAE", config.get('backtest_mae'), challenger['mae'], higher_better=False)
        compare_row("HR All", config.get('backtest_hit_rate_all'), challenger['hit_rate_all'], '%')
        compare_row("HR Edge 3+",
                     config.get('backtest_hit_rate_edge_3plus'), challenger['hit_rate_edge_3plus'],
                     '%')
    else:
        compare_row("MAE", None, challenger['mae'], higher_better=False)
        compare_row("HR All", None, challenger['hit_rate_all'], '%')
        compare_row("HR Edge 3+", None, challenger['hit_rate_edge_3plus'], '%')

    print(f"  {'Vegas Bias':<23s} {'—':<12s} {format_val(challenger['vegas_bias']):<12s}")
    print(f"  {'N Edge 3+':<23s} "
          f"{format_val(config.get('backtest_n_edge_3plus') if config else None):<12s} "
          f"{format_val(challenger['n_edge_3plus']):<12s}")

    # Directional balance
    print()
    print(f"  {'OVER HR (3+)':<23s} {'—':<12s} "
          f"{format_val(challenger['over_hr_3plus'], '%'):<12s} "
          f"(n={format_val(challenger['over_n_3plus'])})")
    print(f"  {'UNDER HR (3+)':<23s} {'—':<12s} "
          f"{format_val(challenger['under_hr_3plus'], '%'):<12s} "
          f"(n={format_val(challenger['under_n_3plus'])})")

    # Champion comparison
    if champion:
        print()
        print("-" * 61)
        print(f"  Champion ({CHAMPION_SYSTEM_ID}) same period:")
        print(f"  {'Champion HR All':<23s} {format_val(champion['hit_rate_all'], '%'):<12s} "
              f"vs challenger {format_val(challenger['hit_rate_all'], '%')}")

        if champion['hit_rate_all'] is not None and challenger['hit_rate_all'] is not None:
            diff = challenger['hit_rate_all'] - champion['hit_rate_all']
            direction = "+" if diff > 0 else ""
            verdict = "CHALLENGER BETTER" if diff > 0 else "CHAMPION BETTER" if diff < 0 else "TIE"
            print(f"  {'Difference':<23s} {direction}{diff:.1f}pp ({verdict})")

        if champion['hit_rate_edge_3plus'] is not None and challenger['hit_rate_edge_3plus'] is not None:
            diff3 = challenger['hit_rate_edge_3plus'] - champion['hit_rate_edge_3plus']
            dir3 = "+" if diff3 > 0 else ""
            print(f"  {'HR 3+ Diff':<23s} {dir3}{diff3:.1f}pp "
                  f"(champ={format_val(champion['hit_rate_edge_3plus'], '%')} n={champion['n_edge_3plus']}, "
                  f"chall={format_val(challenger['hit_rate_edge_3plus'], '%')} n={challenger['n_edge_3plus']})")

        print(f"  {'Champion MAE':<23s} {format_val(champion['mae']):<12s} "
              f"vs challenger {format_val(challenger['mae'])}")
    else:
        print(f"\nNo champion ({CHAMPION_SYSTEM_ID}) data for comparison period.")

    print()


if __name__ == "__main__":
    main()
