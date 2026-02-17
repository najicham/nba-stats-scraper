#!/usr/bin/env python3
"""Model Performance by Player Type — Where does V9 excel vs struggle?

Analyzes V9 prediction accuracy by player/game dimensions with edge filters.
Answers: "For edge 3+ picks in each bucket, what's the hit rate?"
Also looks at MAE and directional accuracy.

Usage:
    PYTHONPATH=. python ml/experiments/model_performance_by_type.py [--save]
"""

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

from google.cloud import bigquery

BREAKEVEN = 52.4
MIN_N = 15

# Reuse the same query from dimensional_analysis but add MAE-relevant fields
QUERY = """
WITH graded AS (
  SELECT
    pa.player_lookup,
    pa.game_id,
    pa.game_date,
    pa.predicted_points,
    pa.line_value,
    pa.recommendation,
    CAST(pa.predicted_points - pa.line_value AS FLOAT64) AS edge,
    pa.actual_points,
    pa.prediction_correct,
    pa.confidence_score,
    pa.team_abbr,
    pa.system_id,
    ABS(pa.predicted_points - pa.actual_points) AS abs_error,
    (pa.actual_points - pa.line_value) AS actual_margin
  FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
  WHERE pa.game_date BETWEEN '2025-11-15' AND '2026-02-13'
    AND pa.system_id = 'catboost_v9'
    AND pa.recommendation IN ('OVER', 'UNDER')
    AND pa.is_voided IS NOT TRUE
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY pa.player_lookup, pa.game_id ORDER BY pa.graded_at DESC
  ) = 1
),

player_rolling AS (
  SELECT
    player_lookup,
    game_date,
    AVG(CAST(points AS FLOAT64))
      OVER w_season AS points_avg_season,
    AVG(CAST(three_pt_attempts AS FLOAT64))
      OVER w_season AS three_pa_season,
    AVG(CAST(ft_attempts AS FLOAT64))
      OVER w_season AS fta_season,
    AVG(minutes_played)
      OVER w_season AS minutes_avg_season,
    AVG(usage_rate)
      OVER w_season AS usage_avg_season,
    AVG(CAST(assists AS FLOAT64))
      OVER w_season AS assists_avg_season,
    AVG(CAST(unassisted_fg_makes AS FLOAT64))
      OVER w_season AS unassisted_fg_season,
    AVG(CAST(paint_attempts AS FLOAT64))
      OVER w_season AS paint_attempts_season,
    starter_flag,
    DATE_DIFF(game_date,
      LAG(game_date, 1) OVER (PARTITION BY player_lookup ORDER BY game_date),
      DAY) AS rest_days,
    AVG(CAST(points AS FLOAT64))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS points_avg_last_3,
    STDDEV(CAST(points AS FLOAT64))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS points_std_last_5
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2025-10-22'
    AND minutes_played > 0
  WINDOW w_season AS (
    PARTITION BY player_lookup ORDER BY game_date
    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
  )
)

SELECT
  g.*,
  pr.points_avg_season,
  pr.three_pa_season,
  pr.fta_season,
  pr.minutes_avg_season,
  pr.usage_avg_season,
  pr.assists_avg_season,
  pr.unassisted_fg_season,
  pr.paint_attempts_season,
  pr.starter_flag,
  pr.rest_days,
  pr.points_avg_last_3,
  pr.points_std_last_5
FROM graded g
LEFT JOIN player_rolling pr
  ON pr.player_lookup = g.player_lookup AND pr.game_date = g.game_date
ORDER BY g.game_date
"""


def load_data(client):
    rows = client.query(QUERY).result(timeout=120)
    return [dict(row) for row in rows]


def compute_metrics(picks):
    if not picks:
        return {'hr': None, 'n': 0, 'roi': None, 'mae': None}
    correct = sum(1 for p in picks if p.get('prediction_correct'))
    total = len(picks)
    hr = round(100.0 * correct / total, 1)
    profit = correct * 100 - (total - correct) * 110
    roi = round(100.0 * profit / (total * 110), 1)
    errors = [float(p['abs_error']) for p in picks if p.get('abs_error') is not None]
    mae = round(sum(errors) / len(errors), 2) if errors else None
    return {'hr': hr, 'n': total, 'roi': roi, 'mae': mae}


def _form_bucket(last_3, season):
    if last_3 is None or season is None or season == 0:
        return None
    diff_pct = (last_3 - season) / season * 100
    if diff_pct > 15:
        return 'Hot (>15% above)'
    elif diff_pct > 5:
        return 'Warm (5-15% above)'
    elif diff_pct >= -5:
        return 'Normal (+/-5%)'
    elif diff_pct >= -15:
        return 'Cool (5-15% below)'
    else:
        return 'Cold (>15% below)'


def define_dimensions():
    return [
        {
            'name': 'Player Tier',
            'func': lambda r: (
                'Elite (25+)' if (r.get('points_avg_season') or 0) > 25
                else 'Stars (20-25)' if (r.get('points_avg_season') or 0) >= 20
                else 'Starters (15-20)' if (r.get('points_avg_season') or 0) >= 15
                else 'Role (10-15)' if (r.get('points_avg_season') or 0) >= 10
                else 'Bench (<10)'
            ) if r.get('points_avg_season') is not None else None,
        },
        {
            'name': '3PT Volume',
            'func': lambda r: (
                'High Volume (6+)' if (r.get('three_pa_season') or 0) >= 6
                else 'Regular (3-6)' if (r.get('three_pa_season') or 0) >= 3
                else 'Low (1-3)' if (r.get('three_pa_season') or 0) >= 1
                else 'Non-shooter (<1)'
            ) if r.get('three_pa_season') is not None else None,
        },
        {
            'name': 'FT Volume',
            'func': lambda r: (
                'High FTA (7+)' if (r.get('fta_season') or 0) >= 7
                else 'Medium FTA (4-7)' if (r.get('fta_season') or 0) >= 4
                else 'Low FTA (2-4)' if (r.get('fta_season') or 0) >= 2
                else 'Minimal FTA (<2)'
            ) if r.get('fta_season') is not None else None,
        },
        {
            'name': 'Usage Rate',
            'func': lambda r: (
                'High Usage (30%+)' if (r.get('usage_avg_season') or 0) >= 30
                else 'Above Avg (25-30%)' if (r.get('usage_avg_season') or 0) >= 25
                else 'Average (20-25%)' if (r.get('usage_avg_season') or 0) >= 20
                else 'Below Avg (15-20%)' if (r.get('usage_avg_season') or 0) >= 15
                else 'Low Usage (<15%)'
            ) if r.get('usage_avg_season') is not None else None,
        },
        {
            'name': 'Starter/Bench',
            'func': lambda r: 'Starter' if r.get('starter_flag') else 'Bench' if r.get('starter_flag') is not None else None,
        },
        {
            'name': 'Rest Days',
            'func': lambda r: (
                'B2B (1 day)' if (r.get('rest_days') or 99) == 1
                else 'Normal (2 days)' if (r.get('rest_days') or 99) == 2
                else 'Rested (3-4)' if (r.get('rest_days') or 99) <= 4
                else 'Well Rested (5+)'
            ) if r.get('rest_days') is not None else None,
        },
        {
            'name': 'Recent Form',
            'func': lambda r: _form_bucket(r.get('points_avg_last_3'), r.get('points_avg_season')),
        },
        {
            'name': 'Volatility',
            'func': lambda r: (
                'Very Volatile (10+)' if (r.get('points_std_last_5') or 0) >= 10
                else 'High (7-10)' if (r.get('points_std_last_5') or 0) >= 7
                else 'Medium (4-7)' if (r.get('points_std_last_5') or 0) >= 4
                else 'Consistent (<4)'
            ) if r.get('points_std_last_5') is not None else None,
        },
        {
            'name': 'Paint Reliance',
            'func': lambda r: (
                'Paint Heavy (8+)' if (r.get('paint_attempts_season') or 0) >= 8
                else 'Mixed (5-8)' if (r.get('paint_attempts_season') or 0) >= 5
                else 'Perimeter (2-5)' if (r.get('paint_attempts_season') or 0) >= 2
                else 'Pure Perimeter (<2)'
            ) if r.get('paint_attempts_season') is not None else None,
        },
        {
            'name': 'Self-Creation',
            'func': lambda r: (
                'High Self-Creator (5+)' if (r.get('unassisted_fg_season') or 0) >= 5
                else 'Medium (3-5)' if (r.get('unassisted_fg_season') or 0) >= 3
                else 'Low (1-3)' if (r.get('unassisted_fg_season') or 0) >= 1
                else 'Assisted (<1)'
            ) if r.get('unassisted_fg_season') is not None else None,
        },
        {
            'name': 'Assist Rate',
            'func': lambda r: (
                'Playmaker (8+)' if (r.get('assists_avg_season') or 0) >= 8
                else 'Ball-Handler (5-8)' if (r.get('assists_avg_season') or 0) >= 5
                else 'Secondary (3-5)' if (r.get('assists_avg_season') or 0) >= 3
                else 'Off-Ball (<3)'
            ) if r.get('assists_avg_season') is not None else None,
        },
        {
            'name': 'Day of Week',
            'func': lambda r: (
                ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][r['game_date'].weekday()]
                if hasattr(r.get('game_date'), 'weekday') else None
            ),
        },
    ]


def analyze_dim(rows, dim, edge_filters=[0, 3, 5]):
    """Analyze one dimension across multiple edge filters."""
    # Bucket all rows
    buckets = defaultdict(list)
    for r in rows:
        label = dim['func'](r)
        if label is not None:
            buckets[label].append(r)

    results = {}
    for label, picks in sorted(buckets.items(), key=lambda x: -len(x[1])):
        if len(picks) < MIN_N:
            continue
        bucket_results = {}
        for min_edge in edge_filters:
            filtered = [p for p in picks if abs(p.get('edge') or 0) >= min_edge]
            m = compute_metrics(filtered)
            if m['n'] >= MIN_N:
                # Also split by direction
                over = compute_metrics([p for p in filtered if p.get('recommendation') == 'OVER'])
                under = compute_metrics([p for p in filtered if p.get('recommendation') == 'UNDER'])
                bucket_results[f'edge_{min_edge}+'] = {
                    'all': m,
                    'OVER': over,
                    'UNDER': under,
                }
        if bucket_results:
            results[label] = bucket_results
    return results


def print_dim_results(name, results):
    """Print results for one dimension."""
    if not results:
        return

    print(f"\n  {name}")
    print(f"  {'Bucket':<24} | {'--- All Edges ---':^24} | {'--- Edge 3+ ---':^24} | {'--- Edge 5+ ---':^24}")
    print(f"  {'':24} | {'N':>5} {'HR':>6} {'MAE':>5} {'ROI':>6} | {'N':>5} {'HR':>6} {'MAE':>5} {'ROI':>6} | {'N':>5} {'HR':>6} {'MAE':>5} {'ROI':>6}")
    print(f"  {'-'*100}")

    for label in sorted(results.keys()):
        bucket = results[label]
        print(f"  {label:<24}", end="")
        for edge_key in ['edge_0+', 'edge_3+', 'edge_5+']:
            if edge_key in bucket:
                m = bucket[edge_key]['all']
                hr = f"{m['hr']:.1f}" if m['hr'] is not None else "--"
                mae = f"{m['mae']:.1f}" if m['mae'] is not None else "--"
                roi = f"{m['roi']:.1f}" if m['roi'] is not None else "--"
                marker = '★' if m['hr'] and m['hr'] >= 58 else '✗' if m['hr'] and m['hr'] < 48 else ' '
                print(f" | {m['n']:>5} {hr:>5}% {mae:>5} {roi:>5}%{marker}", end="")
            else:
                print(f" | {'':>5} {'--':>5}  {'--':>5} {'--':>5}  ", end="")
        print()

    # Print direction breakdown for edge 3+
    print(f"\n  {name} — DIRECTION BREAKDOWN (Edge 3+ only)")
    print(f"  {'Bucket':<24} | {'OVER N':>6} {'OVER HR':>8} {'OVER ROI':>9} | {'UNDER N':>7} {'UNDER HR':>9} {'UNDER ROI':>10}")
    print(f"  {'-'*85}")

    for label in sorted(results.keys()):
        bucket = results[label]
        if 'edge_3+' not in bucket:
            continue
        over = bucket['edge_3+']['OVER']
        under = bucket['edge_3+']['UNDER']
        o_hr = f"{over['hr']:.1f}%" if over['hr'] is not None else "--"
        o_roi = f"{over['roi']:.1f}%" if over['roi'] is not None else "--"
        u_hr = f"{under['hr']:.1f}%" if under['hr'] is not None else "--"
        u_roi = f"{under['roi']:.1f}%" if under['roi'] is not None else "--"

        o_mark = ' ★' if over['hr'] and over['hr'] >= 60 else ' ✗' if over['hr'] and over['hr'] < 48 else ''
        u_mark = ' ★' if under['hr'] and under['hr'] >= 60 else ' ✗' if under['hr'] and under['hr'] < 48 else ''

        print(f"  {label:<24} | {over['n']:>6} {o_hr:>8} {o_roi:>9}{o_mark} | {under['n']:>7} {u_hr:>9} {u_roi:>10}{u_mark}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--save', action='store_true')
    args = parser.parse_args()

    client = bigquery.Client(project='nba-props-platform')

    print("=" * 110)
    print("  V9 MODEL PERFORMANCE BY PLAYER TYPE — Where does the model excel vs struggle?")
    print("  Season: 2025-11-15 to 2026-02-13")
    print("=" * 110)

    print("\nLoading graded V9 predictions...")
    rows = load_data(client)
    print(f"Loaded {len(rows)} graded predictions")

    # Baselines
    for min_edge in [0, 3, 5]:
        filtered = [r for r in rows if abs(r.get('edge') or 0) >= min_edge]
        m = compute_metrics(filtered)
        over = compute_metrics([r for r in filtered if r.get('recommendation') == 'OVER'])
        under = compute_metrics([r for r in filtered if r.get('recommendation') == 'UNDER'])
        print(f"  Edge {min_edge}+: N={m['n']}, HR={m['hr']}%, MAE={m['mae']}, ROI={m['roi']}%"
              f"  |  OVER: N={over['n']} HR={over['hr']}%  UNDER: N={under['n']} HR={under['hr']}%")

    dimensions = define_dimensions()
    all_results = {}

    for dim in dimensions:
        results = analyze_dim(rows, dim)
        all_results[dim['name']] = results
        print_dim_results(dim['name'], results)

    # === SUMMARY: Best model performance buckets ===
    print(f"\n{'=' * 110}")
    print("  BEST EDGE 3+ BUCKETS (HR >= 60%, N >= 15)")
    print(f"{'=' * 110}")
    print(f"  {'Dimension':<20} {'Bucket':<24} {'Dir':>5} {'N':>5} {'HR':>7} {'ROI':>7} {'MAE':>5}")
    print(f"  {'-'*80}")

    highlights = []
    for dim_name, dim_results in all_results.items():
        for label, bucket in dim_results.items():
            if 'edge_3+' not in bucket:
                continue
            for direction in ['all', 'OVER', 'UNDER']:
                m = bucket['edge_3+'][direction]
                if m['n'] >= 15 and m['hr'] and m['hr'] >= 60:
                    highlights.append({
                        'dim': dim_name, 'bucket': label, 'dir': direction,
                        'n': m['n'], 'hr': m['hr'], 'roi': m['roi'], 'mae': m['mae'],
                    })

    highlights.sort(key=lambda x: -(x['hr'] or 0))
    for h in highlights[:35]:
        mae_str = f"{h['mae']:.1f}" if h['mae'] else "--"
        print(f"  {h['dim']:<20} {h['bucket']:<24} {h['dir']:>5} {h['n']:>5} {h['hr']:.1f}% {h['roi']:.1f}% {mae_str:>5}")

    # === WORST ===
    print(f"\n{'=' * 110}")
    print("  WORST EDGE 3+ BUCKETS (HR < 48%, N >= 15)")
    print(f"{'=' * 110}")
    print(f"  {'Dimension':<20} {'Bucket':<24} {'Dir':>5} {'N':>5} {'HR':>7} {'ROI':>7}")
    print(f"  {'-'*70}")

    lowlights = []
    for dim_name, dim_results in all_results.items():
        for label, bucket in dim_results.items():
            if 'edge_3+' not in bucket:
                continue
            for direction in ['all', 'OVER', 'UNDER']:
                m = bucket['edge_3+'][direction]
                if m['n'] >= 15 and m['hr'] and m['hr'] < 48:
                    lowlights.append({
                        'dim': dim_name, 'bucket': label, 'dir': direction,
                        'n': m['n'], 'hr': m['hr'], 'roi': m['roi'],
                    })

    lowlights.sort(key=lambda x: x['hr'] or 100)
    for h in lowlights[:20]:
        print(f"  {h['dim']:<20} {h['bucket']:<24} {h['dir']:>5} {h['n']:>5} {h['hr']:.1f}% {h['roi']:.1f}%")

    if args.save:
        results_dir = os.path.join(os.path.dirname(__file__), 'results')
        os.makedirs(results_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = os.path.join(results_dir, f'model_performance_by_type_{ts}.json')

        def default_serializer(obj):
            if hasattr(obj, 'isoformat'):
                return obj.isoformat()
            return str(obj)

        with open(path, 'w') as f:
            json.dump({'dimensions': all_results, 'highlights': highlights, 'lowlights': lowlights},
                      f, indent=2, default=default_serializer)
        print(f"\nResults saved to {path}")


if __name__ == '__main__':
    main()
