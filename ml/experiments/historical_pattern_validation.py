#!/usr/bin/env python3
"""Historical Pattern Validation — Test signal patterns against raw market O/U data.

Validates whether dimensional patterns (bench UNDER, high FT UNDER, etc.) exist
in the underlying market data across seasons, independent of any model.

Uses player_game_summary over_under_result to check: "In this bucket, what % of
games actually went UNDER the prop line?" If patterns hold across seasons,
they're real market inefficiencies, not model artifacts.

Usage:
    PYTHONPATH=. python ml/experiments/historical_pattern_validation.py [--save]
"""

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from google.cloud import bigquery

MIN_N = 20

QUERY = """
WITH raw_games AS (
  SELECT
    player_lookup,
    game_date,
    season_year,
    points,
    CAST(points_line AS FLOAT64) AS points_line,
    over_under_result,
    CAST(margin AS FLOAT64) AS margin,
    starter_flag,
    minutes_played,
    three_pt_attempts,
    ft_attempts,
    fg_makes,
    fg_attempts,
    assists,
    turnovers,
    unassisted_fg_makes,
    paint_attempts,
    usage_rate,
    offensive_rebounds,
    defensive_rebounds,
    -- Rolling stats (season-level, exclude current game)
    AVG(CAST(points AS FLOAT64))
      OVER (PARTITION BY player_lookup, season_year ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS points_avg_season,
    AVG(CAST(three_pt_attempts AS FLOAT64))
      OVER (PARTITION BY player_lookup, season_year ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS three_pa_season,
    AVG(CAST(ft_attempts AS FLOAT64))
      OVER (PARTITION BY player_lookup, season_year ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS fta_season,
    AVG(minutes_played)
      OVER (PARTITION BY player_lookup, season_year ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS minutes_avg_season,
    AVG(usage_rate)
      OVER (PARTITION BY player_lookup, season_year ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS usage_avg_season,
    AVG(CAST(assists AS FLOAT64))
      OVER (PARTITION BY player_lookup, season_year ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS assists_avg_season,
    AVG(CAST(unassisted_fg_makes AS FLOAT64))
      OVER (PARTITION BY player_lookup, season_year ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS unassisted_fg_season,
    AVG(CAST(paint_attempts AS FLOAT64))
      OVER (PARTITION BY player_lookup, season_year ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS paint_attempts_season,
    DATE_DIFF(game_date,
      LAG(game_date, 1) OVER (PARTITION BY player_lookup ORDER BY game_date),
      DAY) AS rest_days,
    AVG(CAST(points AS FLOAT64))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS points_avg_last_3,
    STDDEV(CAST(points AS FLOAT64))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS points_std_last_5,
    -- Game count for player (only use after 10+ games for stable stats)
    COUNT(*) OVER (PARTITION BY player_lookup, season_year ORDER BY game_date
                   ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS games_played
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE minutes_played > 0
    AND points_line IS NOT NULL
    AND over_under_result IN ('OVER', 'UNDER')
)
SELECT *
FROM raw_games
WHERE points_avg_season IS NOT NULL
  AND games_played >= 10  -- Need stable rolling averages
ORDER BY game_date, player_lookup
"""


def load_data(client: bigquery.Client) -> List[Dict]:
    rows = client.query(QUERY).result(timeout=180)
    return [dict(row) for row in rows]


def compute_ou_metrics(picks: List[Dict]) -> Dict:
    """Compute UNDER rate, OVER rate, and average margin."""
    if not picks:
        return {'under_rate': None, 'over_rate': None, 'n': 0, 'avg_margin': None}
    under = sum(1 for p in picks if p.get('over_under_result') == 'UNDER')
    over = sum(1 for p in picks if p.get('over_under_result') == 'OVER')
    total = len(picks)
    margins = [float(p['margin']) for p in picks if p.get('margin') is not None]
    avg_margin = round(sum(margins) / len(margins), 2) if margins else None
    return {
        'under_rate': round(100.0 * under / total, 1),
        'over_rate': round(100.0 * over / total, 1),
        'n': total,
        'avg_margin': avg_margin,
    }


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
    """Same dimensions as dimensional_analysis.py for direct comparison."""
    return [
        {
            'name': 'Player Tier (Season PPG)',
            'field': 'points_avg_season',
            'buckets': [
                ((25, 999), 'Elite (25+)'),
                ((20, 25), 'Stars (20-25)'),
                ((15, 20), 'Starters (15-20)'),
                ((10, 15), 'Role (10-15)'),
                ((0, 10), 'Bench (<10)'),
            ],
        },
        {
            'name': '3PT Volume (Attempts/Game)',
            'field': 'three_pa_season',
            'buckets': [
                ((6, 999), 'High Volume (6+)'),
                ((3, 6), 'Regular (3-6)'),
                ((1, 3), 'Low (1-3)'),
                ((0, 1), 'Non-shooter (<1)'),
            ],
        },
        {
            'name': 'FT Volume (Attempts/Game)',
            'field': 'fta_season',
            'buckets': [
                ((7, 999), 'High FTA (7+)'),
                ((4, 7), 'Medium FTA (4-7)'),
                ((2, 4), 'Low FTA (2-4)'),
                ((0, 2), 'Minimal FTA (<2)'),
            ],
        },
        {
            'name': 'Minutes Tier',
            'field': 'minutes_avg_season',
            'buckets': [
                ((35, 999), 'Heavy (35+)'),
                ((30, 35), 'Starter (30-35)'),
                ((24, 30), 'Regular (24-30)'),
                ((15, 24), 'Rotation (15-24)'),
                ((0, 15), 'Bench (<15)'),
            ],
        },
        {
            'name': 'Usage Rate Tier',
            'field': 'usage_avg_season',
            'buckets': [
                ((30, 999), 'High Usage (30%+)'),
                ((25, 30), 'Above Avg (25-30%)'),
                ((20, 25), 'Average (20-25%)'),
                ((15, 20), 'Below Avg (15-20%)'),
                ((0, 15), 'Low Usage (<15%)'),
            ],
        },
        {
            'name': 'Starter vs Bench',
            'field': 'starter_flag',
            'categorical': True,
            'label_map': {True: 'Starter', False: 'Bench'},
        },
        {
            'name': 'Rest Days',
            'field': 'rest_days',
            'buckets': [
                ((1, 2), 'B2B (1 day)'),
                ((2, 3), 'Normal (2 days)'),
                ((3, 5), 'Rested (3-4 days)'),
                ((5, 999), 'Well Rested (5+)'),
            ],
        },
        {
            'name': 'Recent Form (Last 3 vs Season)',
            'composite': True,
            'func': lambda r: _form_bucket(r.get('points_avg_last_3'), r.get('points_avg_season')),
        },
        {
            'name': 'Scoring Volatility (Std Last 5)',
            'field': 'points_std_last_5',
            'buckets': [
                ((10, 999), 'Very Volatile (10+)'),
                ((7, 10), 'High (7-10)'),
                ((4, 7), 'Medium (4-7)'),
                ((0, 4), 'Consistent (<4)'),
            ],
        },
        {
            'name': 'Paint Reliance',
            'field': 'paint_attempts_season',
            'buckets': [
                ((8, 999), 'Paint Heavy (8+)'),
                ((5, 8), 'Mixed (5-8)'),
                ((2, 5), 'Perimeter (2-5)'),
                ((0, 2), 'Pure Perimeter (<2)'),
            ],
        },
        {
            'name': 'Self-Creation (Unassisted FG/Game)',
            'field': 'unassisted_fg_season',
            'buckets': [
                ((5, 999), 'High Self-Creator (5+)'),
                ((3, 5), 'Medium (3-5)'),
                ((1, 3), 'Low (1-3)'),
                ((0, 1), 'Assisted (<1)'),
            ],
        },
        {
            'name': 'Assist Rate (Assists/Game)',
            'field': 'assists_avg_season',
            'buckets': [
                ((8, 999), 'Playmaker (8+)'),
                ((5, 8), 'Ball-Handler (5-8)'),
                ((3, 5), 'Secondary (3-5)'),
                ((0, 3), 'Off-Ball (<3)'),
            ],
        },
        {
            'name': 'Day of Week',
            'composite': True,
            'func': lambda r: (
                ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][r['game_date'].weekday()]
                if hasattr(r.get('game_date'), 'weekday') else None
            ),
        },
    ]


def analyze_dimension(rows, dim):
    """Bucket rows by dimension and compute O/U metrics."""
    buckets = defaultdict(list)

    if dim.get('composite'):
        for r in rows:
            label = dim['func'](r)
            if label is not None:
                buckets[label].append(r)
    elif dim.get('categorical'):
        field = dim['field']
        label_map = dim.get('label_map', {})
        for r in rows:
            val = r.get(field)
            if val is not None:
                label = label_map.get(val, str(val))
                buckets[label].append(r)
    else:
        field = dim['field']
        for r in rows:
            val = r.get(field)
            if val is None:
                continue
            val = float(val)
            for (lo, hi), label in dim['buckets']:
                if lo <= val < hi:
                    buckets[label].append(r)
                    break

    results = []
    for label, picks in sorted(buckets.items(), key=lambda x: -len(x[1])):
        m = compute_ou_metrics(picks)
        if m['n'] >= MIN_N:
            results.append({'label': label, **m})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--save', action='store_true')
    args = parser.parse_args()

    client = bigquery.Client(project='nba-props-platform')

    print("=" * 120)
    print("  HISTORICAL PATTERN VALIDATION — Raw Market O/U Rates by Player/Game Dimension")
    print("=" * 120)

    print("\nLoading all player_game_summary data with prop lines...")
    rows = load_data(client)
    print(f"Loaded {len(rows)} player-games with prop lines")

    # Split by season
    seasons = defaultdict(list)
    for r in rows:
        sy = r.get('season_year')
        if sy:
            seasons[sy].append(r)

    print(f"Seasons found: {sorted(seasons.keys())}")
    for sy in sorted(seasons.keys()):
        m = compute_ou_metrics(seasons[sy])
        print(f"  {sy}: N={m['n']}, UNDER rate={m['under_rate']}%, OVER rate={m['over_rate']}%, Avg Margin={m['avg_margin']}")

    # Analyze each season + combined
    all_season_keys = sorted(seasons.keys())
    analysis_sets = [(f"Season {sy}", seasons[sy]) for sy in all_season_keys]
    analysis_sets.append(("ALL SEASONS", rows))

    # If we have current season (2026), also split it into months
    current_season = [r for r in rows if str(r.get('game_date', ''))[:4] == '2026' or str(r.get('game_date', ''))[:7] == '2025-11' or str(r.get('game_date', ''))[:7] == '2025-12']
    if current_season:
        analysis_sets.append(("Current 2025-26", current_season))

    dimensions = define_dimensions()
    all_results = {}

    for set_name, set_rows in analysis_sets:
        print(f"\n{'=' * 120}")
        print(f"  {set_name} — N={len(set_rows)}")
        print(f"{'=' * 120}")

        set_results = {}
        for dim in dimensions:
            results = analyze_dimension(set_rows, dim)
            set_results[dim['name']] = results

            if not results:
                continue

            print(f"\n  {dim['name']}")
            print(f"  {'Bucket':<28} {'N':>6} {'UNDER%':>8} {'OVER%':>8} {'Avg Margin':>11}")
            print(f"  {'-'*65}")
            for r in results:
                u_str = f"{r['under_rate']:.1f}%" if r['under_rate'] is not None else "--"
                o_str = f"{r['over_rate']:.1f}%" if r['over_rate'] is not None else "--"
                m_str = f"{r['avg_margin']:+.2f}" if r['avg_margin'] is not None else "--"

                # Highlight strong biases (>55% one way)
                marker = ''
                if r['under_rate'] is not None:
                    if r['under_rate'] >= 55:
                        marker = ' ↓↓'
                    elif r['under_rate'] >= 52:
                        marker = ' ↓'
                    elif r['over_rate'] >= 55:
                        marker = ' ↑↑'
                    elif r['over_rate'] >= 52:
                        marker = ' ↑'

                print(f"  {r['label']:<28} {r['n']:>6} {u_str:>8} {o_str:>8} {m_str:>11}{marker}")

        all_results[set_name] = set_results

    # === CROSS-SEASON COMPARISON for key findings ===
    print(f"\n{'=' * 120}")
    print("  CROSS-SEASON COMPARISON — Key Patterns")
    print(f"{'=' * 120}")

    key_patterns = [
        ('Player Tier (Season PPG)', 'Bench (<10)', 'under_rate', 'Bench players UNDER'),
        ('Player Tier (Season PPG)', 'Elite (25+)', 'under_rate', 'Elite players UNDER'),
        ('Player Tier (Season PPG)', 'Stars (20-25)', 'under_rate', 'Stars UNDER'),
        ('FT Volume (Attempts/Game)', 'High FTA (7+)', 'under_rate', 'High FTA UNDER'),
        ('FT Volume (Attempts/Game)', 'Medium FTA (4-7)', 'under_rate', 'Medium FTA UNDER'),
        ('Self-Creation (Unassisted FG/Game)', 'High Self-Creator (5+)', 'under_rate', 'Self-creators UNDER'),
        ('Paint Reliance', 'Paint Heavy (8+)', 'under_rate', 'Paint scorers UNDER'),
        ('Starter vs Bench', 'Bench', 'under_rate', 'Non-starters UNDER'),
        ('Starter vs Bench', 'Starter', 'over_rate', 'Starters OVER'),
        ('Rest Days', 'B2B (1 day)', 'under_rate', 'B2B games UNDER'),
        ('Recent Form (Last 3 vs Season)', 'Warm (5-15% above)', 'under_rate', 'Warm form UNDER (reversion)'),
        ('Recent Form (Last 3 vs Season)', 'Cold (>15% below)', 'over_rate', 'Cold form OVER (reversion)'),
        ('Usage Rate Tier', 'High Usage (30%+)', 'under_rate', 'High usage UNDER'),
        ('Assist Rate (Assists/Game)', 'Ball-Handler (5-8)', 'under_rate', 'Ball-handler UNDER'),
        ('Day of Week', 'Mon', 'over_rate', 'Monday OVER'),
        ('Day of Week', 'Sat', 'under_rate', 'Saturday UNDER'),
        ('Scoring Volatility (Std Last 5)', 'Very Volatile (10+)', 'under_rate', 'Volatile UNDER'),
        ('3PT Volume (Attempts/Game)', 'Low (1-3)', 'under_rate', 'Low 3PT UNDER'),
    ]

    print(f"\n  {'Pattern':<30}", end="")
    for set_name, _ in analysis_sets:
        short = set_name.replace("Season ", "").replace("Current ", "")[:12]
        print(f" {'|':>2} {short:>12}", end="")
    print(f" {'|':>2} {'Consistent?':>12}")
    print(f"  {'-' * (30 + 15 * (len(analysis_sets) + 1))}")

    for dim_name, bucket_label, metric, pattern_name in key_patterns:
        print(f"  {pattern_name:<30}", end="")
        values = []
        for set_name, _ in analysis_sets:
            results = all_results.get(set_name, {}).get(dim_name, [])
            found = next((r for r in results if r['label'] == bucket_label), None)
            if found and found[metric] is not None:
                val = found[metric]
                n = found['n']
                values.append(val)
                marker = '★' if val >= 53 else '✗' if val < 48 else ' '
                print(f" | {val:5.1f}% {marker} n={n:<4}", end="")
            else:
                print(f" |     --       ", end="")

        # Consistency check
        if len(values) >= 2:
            all_above_50 = all(v > 50 for v in values)
            all_above_52 = all(v > 52 for v in values)
            consistent = "YES ★★" if all_above_52 else "yes ★" if all_above_50 else "mixed"
        else:
            consistent = "N/A"
        print(f" | {consistent:>12}")

    if args.save:
        results_dir = os.path.join(os.path.dirname(__file__), 'results')
        os.makedirs(results_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = os.path.join(results_dir, f'historical_validation_{ts}.json')

        def default_serializer(obj):
            if hasattr(obj, 'isoformat'):
                return obj.isoformat()
            return str(obj)

        with open(path, 'w') as f:
            json.dump(all_results, f, indent=2, default=default_serializer)
        print(f"\nResults saved to {path}")


if __name__ == '__main__':
    main()
