#!/usr/bin/env python3
"""Dimensional Analysis — Slice V9 prediction performance by player/game characteristics.

Discovers which player types, game contexts, and stat profiles produce
the best (and worst) OVER/UNDER hit rates. Use findings to design new signals.

Usage:
    PYTHONPATH=. python ml/experiments/dimensional_analysis.py [--save]
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from google.cloud import bigquery

# ── Configuration ──────────────────────────────────────────────────────────────

BREAKEVEN_HR = 52.4  # At -110 odds
MIN_N = 20           # Minimum sample size to report

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
    pa.opponent_team_abbr
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

-- Player rolling stats (season averages EXCLUDING current game)
player_rolling AS (
  SELECT
    player_lookup,
    game_date,
    -- Scoring
    AVG(CAST(points AS FLOAT64))
      OVER w_season AS points_avg_season,
    STDDEV(CAST(points AS FLOAT64))
      OVER w_season AS points_std_season,
    AVG(CAST(points AS FLOAT64))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS points_avg_last_5,
    -- 3PT volume
    AVG(CAST(three_pt_attempts AS FLOAT64))
      OVER w_season AS three_pa_season,
    AVG(SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)))
      OVER w_season AS three_pct_season,
    -- FT volume
    AVG(CAST(ft_attempts AS FLOAT64))
      OVER w_season AS fta_season,
    AVG(SAFE_DIVIDE(ft_makes, NULLIF(ft_attempts, 0)))
      OVER w_season AS ft_pct_season,
    -- Minutes
    AVG(minutes_played)
      OVER w_season AS minutes_avg_season,
    -- Usage rate
    AVG(usage_rate)
      OVER w_season AS usage_avg_season,
    -- Assists
    AVG(CAST(assists AS FLOAT64))
      OVER w_season AS assists_avg_season,
    -- Rebounds
    AVG(CAST(offensive_rebounds + defensive_rebounds AS FLOAT64))
      OVER w_season AS rebounds_avg_season,
    -- Turnovers
    AVG(CAST(turnovers AS FLOAT64))
      OVER w_season AS turnovers_avg_season,
    -- FG%
    AVG(SAFE_DIVIDE(fg_makes, NULLIF(fg_attempts, 0)))
      OVER w_season AS fg_pct_season,
    -- TS%
    AVG(ts_pct)
      OVER w_season AS ts_pct_season,
    -- Paint scoring
    AVG(SAFE_DIVIDE(paint_makes, NULLIF(paint_attempts, 0)))
      OVER w_season AS paint_pct_season,
    AVG(CAST(paint_attempts AS FLOAT64))
      OVER w_season AS paint_attempts_season,
    -- Shot creation (unassisted FGs)
    AVG(CAST(unassisted_fg_makes AS FLOAT64))
      OVER w_season AS unassisted_fg_season,
    -- Starter flag (most recent)
    starter_flag,
    -- Rest days
    DATE_DIFF(game_date,
      LAG(game_date, 1) OVER (PARTITION BY player_lookup ORDER BY game_date),
      DAY) AS rest_days,
    -- Recent form: last 3 games scoring vs season
    AVG(CAST(points AS FLOAT64))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS points_avg_last_3,
    -- Volatility: last 5 game std
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
),

-- Feature store data for game-level context
features AS (
  SELECT
    player_lookup,
    game_date,
    feature_5_value AS fatigue_score,
    feature_7_value AS pace_score,
    feature_8_value AS usage_spike,
    feature_9_value AS rest_advantage,
    feature_11_value AS recent_trend,
    feature_13_value AS opponent_def_rating,
    feature_14_value AS opponent_pace,
    feature_15_value AS home_away,
    feature_16_value AS back_to_back,
    feature_22_value AS team_pace,
    feature_23_value AS team_off_rating,
    feature_24_value AS team_win_pct
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE game_date BETWEEN '2025-11-15' AND '2026-02-13'
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY player_lookup, game_date ORDER BY updated_at DESC
  ) = 1
)

SELECT
  g.*,
  -- Player rolling stats
  pr.points_avg_season,
  pr.points_std_season,
  pr.points_avg_last_5,
  pr.points_avg_last_3,
  pr.points_std_last_5,
  pr.three_pa_season,
  pr.three_pct_season,
  pr.fta_season,
  pr.ft_pct_season,
  pr.minutes_avg_season,
  pr.usage_avg_season,
  pr.assists_avg_season,
  pr.rebounds_avg_season,
  pr.turnovers_avg_season,
  pr.fg_pct_season,
  pr.ts_pct_season,
  pr.paint_pct_season,
  pr.paint_attempts_season,
  pr.unassisted_fg_season,
  pr.starter_flag,
  pr.rest_days,
  -- Feature store
  f.fatigue_score,
  f.pace_score,
  f.usage_spike,
  f.rest_advantage,
  f.recent_trend,
  f.opponent_def_rating,
  f.opponent_pace,
  f.home_away,
  f.back_to_back,
  f.team_pace,
  f.team_off_rating,
  f.team_win_pct
FROM graded g
LEFT JOIN player_rolling pr
  ON pr.player_lookup = g.player_lookup AND pr.game_date = g.game_date
LEFT JOIN features f
  ON f.player_lookup = g.player_lookup AND f.game_date = g.game_date
ORDER BY g.game_date, g.player_lookup
"""


def load_data(client: bigquery.Client) -> List[Dict]:
    """Load all graded V9 predictions with supplemental data."""
    rows = client.query(QUERY).result(timeout=120)
    return [dict(row) for row in rows]


def compute_metrics(picks: List[Dict]) -> Dict:
    """Compute hit rate, N, ROI."""
    if not picks:
        return {'hit_rate': None, 'n': 0, 'roi': None, 'correct': 0}
    correct = sum(1 for p in picks if p.get('prediction_correct'))
    total = len(picks)
    hit_rate = round(100.0 * correct / total, 1) if total else None
    profit = correct * 100 - (total - correct) * 110
    roi = round(100.0 * profit / (total * 110), 1) if total else None
    return {'hit_rate': hit_rate, 'n': total, 'roi': roi, 'correct': correct}


def bucket_value(val, thresholds: List[Tuple], labels: List[str]) -> Optional[str]:
    """Bucket a numeric value using thresholds."""
    if val is None:
        return None
    for (lo, hi), label in zip(thresholds, labels):
        if lo <= val < hi:
            return label
    return None


# ── Dimension definitions ──────────────────────────────────────────────────────

def define_dimensions() -> List[Dict]:
    """Define all slicing dimensions with their bucketing logic."""
    return [
        # === PLAYER TYPE ===
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
            'name': 'Direction',
            'field': 'recommendation',
            'categorical': True,
        },
        {
            'name': 'Direction x Player Tier',
            'composite': True,
            'func': lambda r: (
                f"{r.get('recommendation', '?')}_"
                f"{'Elite' if (r.get('points_avg_season') or 0) > 25 else 'Stars' if (r.get('points_avg_season') or 0) >= 20 else 'Starters' if (r.get('points_avg_season') or 0) >= 15 else 'Role' if (r.get('points_avg_season') or 0) >= 10 else 'Bench'}"
            ) if r.get('points_avg_season') is not None else None,
        },
        # === SHOOTING PROFILE ===
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
            'name': 'Direction x 3PT Volume',
            'composite': True,
            'func': lambda r: (
                f"{r.get('recommendation', '?')}_"
                f"{'HiVol3' if (r.get('three_pa_season') or 0) >= 6 else 'Reg3' if (r.get('three_pa_season') or 0) >= 3 else 'Lo3' if (r.get('three_pa_season') or 0) >= 1 else 'Non3'}"
            ) if r.get('three_pa_season') is not None else None,
        },
        {
            'name': '3PT Accuracy (Season %)',
            'field': 'three_pct_season',
            'buckets': [
                ((0.40, 1.0), 'Elite (40%+)'),
                ((0.36, 0.40), 'Good (36-40%)'),
                ((0.33, 0.36), 'Average (33-36%)'),
                ((0, 0.33), 'Below Avg (<33%)'),
            ],
        },
        # === FREE THROWS ===
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
            'name': 'Direction x FT Volume',
            'composite': True,
            'func': lambda r: (
                f"{r.get('recommendation', '?')}_"
                f"{'HiFT' if (r.get('fta_season') or 0) >= 7 else 'MedFT' if (r.get('fta_season') or 0) >= 4 else 'LoFT' if (r.get('fta_season') or 0) >= 2 else 'MinFT'}"
            ) if r.get('fta_season') is not None else None,
        },
        # === MINUTES / ROLE ===
        {
            'name': 'Minutes Tier (Season Avg)',
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
            'label_map': {True: 'Starter', False: 'Bench', None: 'Unknown'},
        },
        # === REST / FATIGUE ===
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
            'name': 'Direction x Rest Days',
            'composite': True,
            'func': lambda r: (
                f"{r.get('recommendation', '?')}_"
                f"{'B2B' if (r.get('rest_days') or 99) == 1 else 'Normal' if (r.get('rest_days') or 99) <= 3 else 'Rested'}"
            ) if r.get('rest_days') is not None else None,
        },
        {
            'name': 'Fatigue Score',
            'field': 'fatigue_score',
            'buckets': [
                ((0.7, 999), 'High Fatigue (0.7+)'),
                ((0.4, 0.7), 'Medium Fatigue'),
                ((0.0, 0.4), 'Low Fatigue (<0.4)'),
                ((-999, 0.0), 'Negative (rested)'),
            ],
        },
        {
            'name': 'Back-to-Back Flag',
            'field': 'back_to_back',
            'buckets': [
                ((0.5, 999), 'B2B Game'),
                ((-999, 0.5), 'Not B2B'),
            ],
        },
        # === GAME CONTEXT ===
        {
            'name': 'Home vs Away',
            'field': 'home_away',
            'buckets': [
                ((0.5, 999), 'Home'),
                ((-999, 0.5), 'Away'),
            ],
        },
        {
            'name': 'Direction x Home/Away',
            'composite': True,
            'func': lambda r: (
                f"{r.get('recommendation', '?')}_"
                f"{'Home' if (r.get('home_away') or 0) > 0.5 else 'Away'}"
            ) if r.get('home_away') is not None else None,
        },
        {
            'name': 'Opponent Pace',
            'field': 'opponent_pace',
            'quantile_buckets': 4,
            'labels': ['Slow (Q1)', 'Below Avg (Q2)', 'Above Avg (Q3)', 'Fast (Q4)'],
        },
        {
            'name': 'Opponent Def Rating',
            'field': 'opponent_def_rating',
            'quantile_buckets': 4,
            'labels': ['Elite D (Q1)', 'Good D (Q2)', 'Avg D (Q3)', 'Bad D (Q4)'],
        },
        {
            'name': 'Team Offensive Rating',
            'field': 'team_off_rating',
            'quantile_buckets': 4,
            'labels': ['Low OFF (Q1)', 'Below Avg (Q2)', 'Above Avg (Q3)', 'High OFF (Q4)'],
        },
        {
            'name': 'Team Win %',
            'field': 'team_win_pct',
            'quantile_buckets': 4,
            'labels': ['Lottery (Q1)', 'Below .500 (Q2)', 'Playoff (Q3)', 'Contender (Q4)'],
        },
        # === EDGE / CONFIDENCE ===
        {
            'name': 'Edge Magnitude',
            'composite': True,
            'func': lambda r: (
                'High Edge (5+)' if abs(r.get('edge') or 0) >= 5
                else 'Medium Edge (3-5)' if abs(r.get('edge') or 0) >= 3
                else 'Low Edge (1-3)' if abs(r.get('edge') or 0) >= 1
                else 'Tiny Edge (<1)'
            ),
        },
        {
            'name': 'Direction x Edge',
            'composite': True,
            'func': lambda r: (
                f"{r.get('recommendation', '?')}_"
                f"{'Hi' if abs(r.get('edge') or 0) >= 5 else 'Med' if abs(r.get('edge') or 0) >= 3 else 'Lo'}"
            ),
        },
        # === SCORING FORM / VOLATILITY ===
        {
            'name': 'Recent Form (Last 3 vs Season)',
            'composite': True,
            'func': lambda r: (
                _form_bucket(r.get('points_avg_last_3'), r.get('points_avg_season'))
            ),
        },
        {
            'name': 'Direction x Recent Form',
            'composite': True,
            'func': lambda r: (
                f"{r.get('recommendation', '?')}_"
                f"{_form_bucket(r.get('points_avg_last_3'), r.get('points_avg_season')) or '?'}"
            ) if _form_bucket(r.get('points_avg_last_3'), r.get('points_avg_season')) else None,
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
            'name': 'Recent Trend (Feature)',
            'field': 'recent_trend',
            'buckets': [
                ((0.5, 999), 'Strong Up'),
                ((0.1, 0.5), 'Slight Up'),
                ((-0.1, 0.1), 'Flat'),
                ((-0.5, -0.1), 'Slight Down'),
                ((-999, -0.5), 'Strong Down'),
            ],
        },
        # === PLAY STYLE ===
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
            'name': 'Usage Spike',
            'field': 'usage_spike',
            'buckets': [
                ((0.5, 999), 'High Spike (0.5+)'),
                ((0.1, 0.5), 'Moderate Spike'),
                ((-0.1, 0.1), 'Normal'),
                ((-999, -0.1), 'Usage Dip'),
            ],
        },
        # === MONTH ===
        {
            'name': 'Month',
            'composite': True,
            'func': lambda r: (
                r['game_date'].strftime('%Y-%m') if hasattr(r.get('game_date'), 'strftime') else str(r.get('game_date', ''))[:7]
            ),
        },
        # === DAY OF WEEK ===
        {
            'name': 'Day of Week',
            'composite': True,
            'func': lambda r: (
                ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][r['game_date'].weekday()]
                if hasattr(r.get('game_date'), 'weekday') else None
            ),
        },
    ]


def _form_bucket(last_3, season):
    """Bucket recent form relative to season average."""
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


def compute_quantile_thresholds(rows, field, n_buckets):
    """Compute quantile thresholds for a field."""
    values = sorted([float(r[field]) for r in rows if r.get(field) is not None])
    if not values:
        return []
    thresholds = []
    for i in range(n_buckets):
        idx = int(len(values) * i / n_buckets)
        thresholds.append(values[idx])
    thresholds.append(values[-1] + 1)  # upper bound
    return thresholds


def analyze_dimension(rows: List[Dict], dim: Dict) -> List[Dict]:
    """Analyze one dimension, returning per-bucket metrics."""
    buckets = defaultdict(list)

    if dim.get('composite'):
        func = dim['func']
        for r in rows:
            label = func(r)
            if label is not None:
                buckets[label].append(r)
    elif dim.get('categorical'):
        field = dim['field']
        label_map = dim.get('label_map', {})
        for r in rows:
            val = r.get(field)
            label = label_map.get(val, str(val)) if label_map else str(val)
            if val is not None:
                buckets[label].append(r)
    elif dim.get('quantile_buckets'):
        field = dim['field']
        n = dim['quantile_buckets']
        labels = dim['labels']
        thresholds = compute_quantile_thresholds(rows, field, n)
        if len(thresholds) >= 2:
            for r in rows:
                val = r.get(field)
                if val is None:
                    continue
                val = float(val)
                for i in range(len(thresholds) - 1):
                    if thresholds[i] <= val < thresholds[i + 1]:
                        buckets[labels[i]].append(r)
                        break
    else:
        field = dim['field']
        bucket_defs = dim['buckets']
        for r in rows:
            val = r.get(field)
            if val is None:
                continue
            val = float(val)
            for (lo, hi), label in bucket_defs:
                if lo <= val < hi:
                    buckets[label].append(r)
                    break

    results = []
    for label, picks in sorted(buckets.items(), key=lambda x: -len(x[1])):
        m = compute_metrics(picks)
        if m['n'] >= MIN_N:
            # Also compute OVER vs UNDER breakdown
            over_picks = [p for p in picks if p.get('recommendation') == 'OVER']
            under_picks = [p for p in picks if p.get('recommendation') == 'UNDER']
            over_m = compute_metrics(over_picks)
            under_m = compute_metrics(under_picks)
            results.append({
                'label': label,
                **m,
                'over_n': over_m['n'],
                'over_hr': over_m['hit_rate'],
                'under_n': under_m['n'],
                'under_hr': under_m['hit_rate'],
            })

    return results


def print_dimension(name: str, results: List[Dict]) -> None:
    """Print results for one dimension."""
    if not results:
        print(f"\n  {name}: No buckets with N >= {MIN_N}")
        return

    print(f"\n  {name}")
    print(f"  {'Bucket':<28} {'N':>5} {'HR':>7} {'ROI':>7}  |  {'OVER N':>6} {'OVER HR':>8}  {'UNDER N':>7} {'UNDER HR':>9}")
    print(f"  {'-'*100}")

    for r in results:
        hr_str = f"{r['hit_rate']:.1f}%" if r['hit_rate'] is not None else "--"
        roi_str = f"{r['roi']:.1f}%" if r['roi'] is not None else "--"
        over_hr = f"{r['over_hr']:.1f}%" if r['over_hr'] is not None else "--"
        under_hr = f"{r['under_hr']:.1f}%" if r['under_hr'] is not None else "--"

        # Highlight profitable buckets
        marker = ''
        if r['hit_rate'] is not None:
            if r['hit_rate'] >= 60:
                marker = ' ★★'
            elif r['hit_rate'] >= BREAKEVEN_HR:
                marker = ' ★'
            elif r['hit_rate'] < 48:
                marker = ' ✗'

        print(f"  {r['label']:<28} {r['n']:>5} {hr_str:>7} {roi_str:>7}  |  {r['over_n']:>6} {over_hr:>8}  {r['under_n']:>7} {under_hr:>9}{marker}")


def find_highlights(all_dim_results: Dict[str, List[Dict]]) -> Tuple[List, List]:
    """Find the best and worst performing buckets across all dimensions."""
    best = []
    worst = []

    for dim_name, results in all_dim_results.items():
        for r in results:
            if r['n'] < 30:  # Slightly higher bar for highlights
                continue
            entry = {
                'dimension': dim_name,
                'bucket': r['label'],
                'n': r['n'],
                'hit_rate': r['hit_rate'],
                'roi': r['roi'],
                'over_n': r['over_n'],
                'over_hr': r['over_hr'],
                'under_n': r['under_n'],
                'under_hr': r['under_hr'],
            }
            if r['hit_rate'] is not None:
                if r['hit_rate'] >= 58:
                    best.append(entry)
                elif r['hit_rate'] <= 47:
                    worst.append(entry)

    best.sort(key=lambda x: -(x['hit_rate'] or 0))
    worst.sort(key=lambda x: x['hit_rate'] or 100)
    return best[:25], worst[:25]


def main():
    parser = argparse.ArgumentParser(description="Dimensional Analysis")
    parser.add_argument('--save', action='store_true')
    args = parser.parse_args()

    client = bigquery.Client(project='nba-props-platform')

    print("=" * 110)
    print("  DIMENSIONAL ANALYSIS — V9 Prediction Performance by Player/Game Characteristics")
    print("  Season: 2025-11-15 to 2026-02-13")
    print("=" * 110)

    print("\nLoading data from BigQuery...")
    rows = load_data(client)
    print(f"Loaded {len(rows)} graded V9 predictions")

    # Baseline
    baseline = compute_metrics(rows)
    edge3 = compute_metrics([r for r in rows if abs(r.get('edge') or 0) >= 3])
    print(f"\nBASELINE: All V9 — N={baseline['n']}, HR={baseline['hit_rate']}%, ROI={baseline['roi']}%")
    print(f"BASELINE: V9 edge 3+ — N={edge3['n']}, HR={edge3['hit_rate']}%, ROI={edge3['roi']}%")

    dimensions = define_dimensions()
    all_dim_results = {}

    for dim in dimensions:
        results = analyze_dimension(rows, dim)
        all_dim_results[dim['name']] = results
        print_dimension(dim['name'], results)

    # === HIGHLIGHTS ===
    best, worst = find_highlights(all_dim_results)

    print(f"\n{'=' * 110}")
    print("  TOP PERFORMING BUCKETS (HR >= 58%, N >= 30)")
    print(f"{'=' * 110}")
    print(f"  {'Dimension':<30} {'Bucket':<28} {'N':>5} {'HR':>7} {'ROI':>7}  {'O_HR':>6} {'U_HR':>6}")
    print(f"  {'-'*95}")
    for e in best:
        over_hr = f"{e['over_hr']:.0f}%" if e['over_hr'] is not None else "--"
        under_hr = f"{e['under_hr']:.0f}%" if e['under_hr'] is not None else "--"
        print(f"  {e['dimension']:<30} {e['bucket']:<28} {e['n']:>5} {e['hit_rate']:.1f}% {e['roi']:.1f}%  {over_hr:>6} {under_hr:>6}")

    print(f"\n{'=' * 110}")
    print("  WORST PERFORMING BUCKETS (HR <= 47%, N >= 30)")
    print(f"{'=' * 110}")
    print(f"  {'Dimension':<30} {'Bucket':<28} {'N':>5} {'HR':>7} {'ROI':>7}  {'O_HR':>6} {'U_HR':>6}")
    print(f"  {'-'*95}")
    for e in worst:
        over_hr = f"{e['over_hr']:.0f}%" if e['over_hr'] is not None else "--"
        under_hr = f"{e['under_hr']:.0f}%" if e['under_hr'] is not None else "--"
        print(f"  {e['dimension']:<30} {e['bucket']:<28} {e['n']:>5} {e['hit_rate']:.1f}% {e['roi']:.1f}%  {over_hr:>6} {under_hr:>6}")

    # === SIGNAL OPPORTUNITIES ===
    print(f"\n{'=' * 110}")
    print("  SIGNAL OPPORTUNITIES — Buckets that could become new signals")
    print(f"{'=' * 110}")

    opportunities = []
    for dim_name, results in all_dim_results.items():
        for r in results:
            if r['n'] < 30:
                continue
            # Check if OVER or UNDER direction within a bucket is esp strong
            if r['over_hr'] is not None and r['over_n'] >= 20 and r['over_hr'] >= 60:
                opportunities.append({
                    'dimension': dim_name,
                    'bucket': r['label'],
                    'direction': 'OVER',
                    'n': r['over_n'],
                    'hr': r['over_hr'],
                })
            if r['under_hr'] is not None and r['under_n'] >= 20 and r['under_hr'] >= 60:
                opportunities.append({
                    'dimension': dim_name,
                    'bucket': r['label'],
                    'direction': 'UNDER',
                    'n': r['under_n'],
                    'hr': r['under_hr'],
                })

    opportunities.sort(key=lambda x: -(x['hr'] or 0))
    print(f"\n  Direction-specific opportunities (HR >= 60%, N >= 20):")
    print(f"  {'Dimension':<30} {'Bucket':<28} {'Dir':>5} {'N':>5} {'HR':>7}")
    print(f"  {'-'*80}")
    for o in opportunities[:30]:
        print(f"  {o['dimension']:<30} {o['bucket']:<28} {o['direction']:>5} {o['n']:>5} {o['hr']:.1f}%")

    # Save
    if args.save:
        results_dir = os.path.join(os.path.dirname(__file__), 'results')
        os.makedirs(results_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = os.path.join(results_dir, f'dimensional_analysis_{ts}.json')

        def default_serializer(obj):
            if hasattr(obj, 'isoformat'):
                return obj.isoformat()
            return str(obj)

        output = {
            'timestamp': ts,
            'total_predictions': len(rows),
            'baseline': baseline,
            'baseline_edge3': edge3,
            'dimensions': {
                name: results for name, results in all_dim_results.items()
            },
            'highlights': {'best': best, 'worst': worst},
            'opportunities': opportunities[:30],
        }

        with open(path, 'w') as f:
            json.dump(output, f, indent=2, default=default_serializer)
        print(f"\nResults saved to {path}")


if __name__ == '__main__':
    main()
