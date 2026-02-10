#!/usr/bin/env python3
"""
Compare Model Performance — Backtest vs Production

Session 177: Compares a challenger model's production graded results against
its backtest metrics from MONTHLY_MODELS config and the champion's performance.

Session 187: Added --all (landscape view) and --segments (segment breakdowns)
for monitoring model strengths across direction, tier, and line range.

Usage:
    python bin/compare-model-performance.py catboost_v9_train1102_0108
    python bin/compare-model-performance.py catboost_v9_train1102_0108 --days 14
    python bin/compare-model-performance.py --list  # Show all challengers with strengths
    python bin/compare-model-performance.py --all --days 7  # Landscape view
    python bin/compare-model-performance.py catboost_v9 --segments --days 7  # Segment breakdowns
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
    parser.add_argument('--list', action='store_true', help='List all challenger models with strength profiles')
    parser.add_argument('--all', action='store_true', help='Landscape view: compare all models in one table')
    parser.add_argument('--segments', action='store_true', help='Show segment breakdowns (direction, tier, line range)')
    return parser.parse_args()


def list_models():
    """List all challenger models with their backtest metrics and strength profiles."""
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
        strengths = config.get('strengths')
        if strengths:
            print(f"    Strengths: {strengths.get('summary', 'N/A')}")
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
            predicted_margin
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
        COUNTIF(ABS(predicted_margin) >= 3) as n_edge_3plus,
        ROUND(100.0 * COUNTIF(prediction_correct AND ABS(predicted_margin) >= 3)
            / NULLIF(COUNTIF(ABS(predicted_margin) >= 3), 0), 1) as hit_rate_edge_3plus,
        -- Edge 5+
        COUNTIF(ABS(predicted_margin) >= 5) as n_edge_5plus,
        ROUND(100.0 * COUNTIF(prediction_correct AND ABS(predicted_margin) >= 5)
            / NULLIF(COUNTIF(ABS(predicted_margin) >= 5), 0), 1) as hit_rate_edge_5plus,
        -- Vegas bias
        ROUND(AVG(predicted_points - line_value), 2) as vegas_bias,
        -- Directional
        ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'OVER' AND ABS(predicted_margin) >= 3)
            / NULLIF(COUNTIF(recommendation = 'OVER' AND ABS(predicted_margin) >= 3), 0), 1) as over_hr_3plus,
        COUNTIF(recommendation = 'OVER' AND ABS(predicted_margin) >= 3) as over_n_3plus,
        ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'UNDER' AND ABS(predicted_margin) >= 3)
            / NULLIF(COUNTIF(recommendation = 'UNDER' AND ABS(predicted_margin) >= 3), 0), 1) as under_hr_3plus,
        COUNTIF(recommendation = 'UNDER' AND ABS(predicted_margin) >= 3) as under_n_3plus,
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
    # Convert Decimal types to float for clean display
    v = float(val) if hasattr(val, 'as_tuple') else val
    if isinstance(v, float):
        # Use appropriate precision
        return f"{v:.1f}{suffix}" if abs(v) >= 1 else f"{v:.3f}{suffix}"
    return f"{v}{suffix}"


def query_all_models(client, days):
    """Query production performance for all enabled models + champion in one shot."""
    enabled_ids = [mid for mid, cfg in MONTHLY_MODELS.items() if cfg.get("enabled")]
    all_ids = [CHAMPION_SYSTEM_ID] + enabled_ids
    id_list = ", ".join(f"'{sid}'" for sid in all_ids)

    query = f"""
    WITH graded AS (
        SELECT
            system_id,
            predicted_points,
            actual_points,
            line_value,
            prediction_correct,
            recommendation,
            predicted_margin
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE system_id IN ({id_list})
          AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          AND prediction_correct IS NOT NULL
          AND line_value IS NOT NULL
          AND recommendation IN ('OVER', 'UNDER')
    )
    SELECT
        system_id,
        COUNT(*) as total_graded,
        ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate_all,
        COUNTIF(ABS(predicted_margin) >= 3) as n_edge_3plus,
        ROUND(100.0 * COUNTIF(prediction_correct AND ABS(predicted_margin) >= 3)
            / NULLIF(COUNTIF(ABS(predicted_margin) >= 3), 0), 1) as hit_rate_edge_3plus,
        ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'UNDER')
            / NULLIF(COUNTIF(recommendation = 'UNDER'), 0), 1) as under_hr,
        ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'OVER')
            / NULLIF(COUNTIF(recommendation = 'OVER'), 0), 1) as over_hr,
        ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae,
        ROUND(AVG(predicted_points - line_value), 2) as vegas_bias,
    FROM graded
    GROUP BY system_id
    ORDER BY hit_rate_all DESC
    """
    df = client.query(query).to_dataframe()

    # Build results dict keyed by system_id
    results = {}
    for _, row in df.iterrows():
        results[row['system_id']] = row.to_dict()

    return results, all_ids


def query_segment_performance(client, system_id, days):
    """Query segment breakdowns for a model: direction, tier, line range."""
    query = f"""
    WITH graded AS (
        SELECT
            prediction_correct,
            recommendation,
            predicted_margin,
            line_value,
            actual_points,
            predicted_points,
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE system_id = '{system_id}'
          AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          AND prediction_correct IS NOT NULL
          AND line_value IS NOT NULL
          AND recommendation IN ('OVER', 'UNDER')
    )
    SELECT
        -- Direction segments
        COUNTIF(recommendation = 'OVER') as over_n,
        ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'OVER')
            / NULLIF(COUNTIF(recommendation = 'OVER'), 0), 1) as over_hr,
        COUNTIF(recommendation = 'UNDER') as under_n,
        ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'UNDER')
            / NULLIF(COUNTIF(recommendation = 'UNDER'), 0), 1) as under_hr,

        -- Tier segments (by line_value as proxy for player tier)
        COUNTIF(line_value >= 25) as stars_n,
        ROUND(100.0 * COUNTIF(prediction_correct AND line_value >= 25)
            / NULLIF(COUNTIF(line_value >= 25), 0), 1) as stars_hr,
        COUNTIF(line_value >= 15 AND line_value < 25) as starters_n,
        ROUND(100.0 * COUNTIF(prediction_correct AND line_value >= 15 AND line_value < 25)
            / NULLIF(COUNTIF(line_value >= 15 AND line_value < 25), 0), 1) as starters_hr,
        COUNTIF(line_value >= 5 AND line_value < 15) as role_n,
        ROUND(100.0 * COUNTIF(prediction_correct AND line_value >= 5 AND line_value < 15)
            / NULLIF(COUNTIF(line_value >= 5 AND line_value < 15), 0), 1) as role_hr,
        COUNTIF(line_value < 5) as bench_n,
        ROUND(100.0 * COUNTIF(prediction_correct AND line_value < 5)
            / NULLIF(COUNTIF(line_value < 5), 0), 1) as bench_hr,

        -- Line range segments
        COUNTIF(line_value < 12.5) as low_line_n,
        ROUND(100.0 * COUNTIF(prediction_correct AND line_value < 12.5)
            / NULLIF(COUNTIF(line_value < 12.5), 0), 1) as low_line_hr,
        COUNTIF(line_value >= 12.5 AND line_value <= 20.5) as mid_line_n,
        ROUND(100.0 * COUNTIF(prediction_correct AND line_value >= 12.5 AND line_value <= 20.5)
            / NULLIF(COUNTIF(line_value >= 12.5 AND line_value <= 20.5), 0), 1) as mid_line_hr,
        COUNTIF(line_value > 20.5) as high_line_n,
        ROUND(100.0 * COUNTIF(prediction_correct AND line_value > 20.5)
            / NULLIF(COUNTIF(line_value > 20.5), 0), 1) as high_line_hr,

        -- Direction x Tier cross-segments
        COUNTIF(recommendation = 'UNDER' AND line_value >= 25) as stars_under_n,
        ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'UNDER' AND line_value >= 25)
            / NULLIF(COUNTIF(recommendation = 'UNDER' AND line_value >= 25), 0), 1) as stars_under_hr,
        COUNTIF(recommendation = 'UNDER' AND line_value >= 15 AND line_value < 25) as starters_under_n,
        ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'UNDER' AND line_value >= 15 AND line_value < 25)
            / NULLIF(COUNTIF(recommendation = 'UNDER' AND line_value >= 15 AND line_value < 25), 0), 1) as starters_under_hr,
        COUNTIF(recommendation = 'UNDER' AND line_value >= 5 AND line_value < 15) as role_under_n,
        ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'UNDER' AND line_value >= 5 AND line_value < 15)
            / NULLIF(COUNTIF(recommendation = 'UNDER' AND line_value >= 5 AND line_value < 15), 0), 1) as role_under_hr,

    FROM graded
    """
    result = client.query(query).to_dataframe()
    if len(result) == 0:
        return None
    return result.iloc[0].to_dict()


STRENGTH_THRESHOLD_HR = 58.0
STRENGTH_THRESHOLD_N = 5


def detect_strengths(segments):
    """Auto-detect strength segments (HR >= 58% and N >= 5)."""
    if not segments:
        return []

    checks = [
        ("OVER", segments.get('over_hr'), segments.get('over_n')),
        ("UNDER", segments.get('under_hr'), segments.get('under_n')),
        ("Stars (25+)", segments.get('stars_hr'), segments.get('stars_n')),
        ("Starters (15-24)", segments.get('starters_hr'), segments.get('starters_n')),
        ("Role (5-14)", segments.get('role_hr'), segments.get('role_n')),
        ("Bench (<5)", segments.get('bench_hr'), segments.get('bench_n')),
        ("Low Line (<12.5)", segments.get('low_line_hr'), segments.get('low_line_n')),
        ("Mid Line (12.5-20.5)", segments.get('mid_line_hr'), segments.get('mid_line_n')),
        ("High Line (>20.5)", segments.get('high_line_hr'), segments.get('high_line_n')),
        ("Stars UNDER", segments.get('stars_under_hr'), segments.get('stars_under_n')),
        ("Starters UNDER", segments.get('starters_under_hr'), segments.get('starters_under_n')),
        ("Role UNDER", segments.get('role_under_hr'), segments.get('role_under_n')),
    ]

    strengths = []
    for label, hr, n in checks:
        if hr is not None and n is not None:
            hr_f = float(hr) if hr == hr else 0  # NaN check
            n_i = int(n) if n == n else 0
            if hr_f >= STRENGTH_THRESHOLD_HR and n_i >= STRENGTH_THRESHOLD_N:
                strengths.append((label, hr_f, n_i))

    return sorted(strengths, key=lambda x: -x[1])


def print_landscape(results, all_ids, days):
    """Print landscape view comparing all models."""
    print(f"\nMODEL LANDSCAPE (last {days} days)")
    print("=" * 100)
    print(f"{'System ID':<42s} {'HR All':>7s} {'HR 3+ (N)':>12s} {'UNDER HR':>9s} {'OVER HR':>8s} {'MAE':>6s} {'Bias':>6s}")
    print("-" * 100)

    for sid in all_ids:
        label = sid
        if sid == CHAMPION_SYSTEM_ID:
            label += " (CHAMPION)"

        if sid not in results:
            print(f"  {label:<40s} {'(no graded data)':>50s}")
            continue

        r = results[sid]
        hr_all = format_val(r.get('hit_rate_all'), '%')
        hr_3 = format_val(r.get('hit_rate_edge_3plus'), '%')
        n_3 = format_val(r.get('n_edge_3plus'))
        under_hr = format_val(r.get('under_hr'), '%')
        over_hr = format_val(r.get('over_hr'), '%')
        mae = format_val(r.get('mae'))
        bias = format_val(r.get('vegas_bias'))

        hr3_col = f"{hr_3} ({n_3})" if hr_3 != 'N/A' else 'N/A'
        print(f"  {label:<40s} {hr_all:>7s} {hr3_col:>12s} {under_hr:>9s} {over_hr:>8s} {mae:>6s} {bias:>6s}")

    print()


def print_segments(segments, system_id):
    """Print segment breakdown for a model."""
    if not segments:
        print(f"No segment data for {system_id}.")
        return

    def seg_row(label, hr, n, indent=4):
        hr_str = format_val(hr, '%')
        n_str = format_val(n)
        marker = " ***" if hr is not None and n is not None and float(hr if hr == hr else 0) >= STRENGTH_THRESHOLD_HR and int(n if n == n else 0) >= STRENGTH_THRESHOLD_N else ""
        print(f"{' ' * indent}{label:<25s} {hr_str:>7s}  (n={n_str}){marker}")

    print(f"\nSEGMENT BREAKDOWN: {system_id}")
    print("=" * 60)

    print("\n  Direction:")
    seg_row("OVER", segments.get('over_hr'), segments.get('over_n'))
    seg_row("UNDER", segments.get('under_hr'), segments.get('under_n'))

    print("\n  Player Tier (by line):")
    seg_row("Stars (25+)", segments.get('stars_hr'), segments.get('stars_n'))
    seg_row("Starters (15-24)", segments.get('starters_hr'), segments.get('starters_n'))
    seg_row("Role (5-14)", segments.get('role_hr'), segments.get('role_n'))
    seg_row("Bench (<5)", segments.get('bench_hr'), segments.get('bench_n'))

    print("\n  Line Range:")
    seg_row("Low (<12.5)", segments.get('low_line_hr'), segments.get('low_line_n'))
    seg_row("Mid (12.5-20.5)", segments.get('mid_line_hr'), segments.get('mid_line_n'))
    seg_row("High (>20.5)", segments.get('high_line_hr'), segments.get('high_line_n'))

    print("\n  Direction x Tier (UNDER):")
    seg_row("Stars UNDER", segments.get('stars_under_hr'), segments.get('stars_under_n'))
    seg_row("Starters UNDER", segments.get('starters_under_hr'), segments.get('starters_under_n'))
    seg_row("Role UNDER", segments.get('role_under_hr'), segments.get('role_under_n'))

    # Auto-detect and highlight strengths
    strengths = detect_strengths(segments)
    if strengths:
        print(f"\n  Detected Strengths (>= {STRENGTH_THRESHOLD_HR}% HR, N >= {STRENGTH_THRESHOLD_N}):")
        for label, hr, n in strengths:
            print(f"    *** {label}: {hr:.1f}% (n={n})")
    else:
        print("\n  No segments meet strength threshold yet.")
    print()


def main():
    args = parse_args()

    if args.list:
        list_models()
        return

    if args.all:
        client = bigquery.Client(project=PROJECT_ID)
        print(f"Querying all models (last {args.days} days)...\n")
        results, all_ids = query_all_models(client, args.days)
        print_landscape(results, all_ids, args.days)

        if args.segments:
            for sid in all_ids:
                if sid in results:
                    segments = query_segment_performance(client, sid, args.days)
                    print_segments(segments, sid)
        return

    if not args.system_id:
        print("ERROR: Provide a system_id, use --list, or use --all")
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
            gap = float(prod_val) - float(backtest_val)
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

    # Segment breakdowns
    if args.segments:
        segments = query_segment_performance(client, system_id, args.days)
        print_segments(segments, system_id)
    else:
        print()


if __name__ == "__main__":
    main()
