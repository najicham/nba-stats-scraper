#!/usr/bin/env python3
"""Signal System Comprehensive Audit — Session 295.

Answers 4 critical questions:
  1. Does the signal system beat pure edge-based filtering? (full season replay)
  2. Are UNDER signals needed for quantile models?
  3. Do specific models have directional biases that align with signals?
  4. Does the consensus bonus actually help?

Usage:
    PYTHONPATH=. python ml/experiments/signal_system_audit.py [--save] [--start 2025-11-04] [--end 2026-02-17]
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import bigquery

from ml.signals.registry import build_default_registry
from ml.signals.aggregator import BestBetsAggregator

# ── Configuration ────────────────────────────────────────────────────────────

ALL_MODEL_IDS = [
    'catboost_v9',
    'catboost_v12',
    'catboost_v9_q43',
    'catboost_v9_q45',
    'catboost_v12_noveg_q43',
    'catboost_v12_noveg_q45',
]

QUANTILE_MODEL_PREFIXES = ['q43', 'q45']
MAE_MODEL_PREFIXES = ['catboost_v9', 'catboost_v12']

# ── BigQuery data loader ─────────────────────────────────────────────────────

QUERY_ALL_MODELS = """
WITH all_preds AS (
  SELECT
    pa.player_lookup,
    pa.game_id,
    pa.game_date,
    pa.system_id,
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
  WHERE pa.game_date BETWEEN @start_date AND @end_date
    AND pa.recommendation IN ('OVER', 'UNDER')
    AND pa.is_voided IS NOT TRUE
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY pa.player_lookup, pa.game_id, pa.system_id
    ORDER BY pa.graded_at DESC
  ) = 1
)
SELECT * FROM all_preds
ORDER BY game_date, player_lookup, system_id
"""

QUERY_V9_WITH_SUPPLEMENTS = """
WITH v9_preds AS (
  SELECT
    pa.player_lookup,
    pa.game_id,
    pa.game_date,
    pa.system_id,
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
  WHERE pa.game_date BETWEEN @start_date AND @end_date
    AND pa.system_id = 'catboost_v9'
    AND pa.recommendation IN ('OVER', 'UNDER')
    AND pa.is_voided IS NOT TRUE
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY pa.player_lookup, pa.game_id ORDER BY pa.graded_at DESC
  ) = 1
),

v12_preds AS (
  SELECT
    pa.player_lookup,
    pa.game_id,
    pa.recommendation AS v12_recommendation,
    CAST(pa.predicted_points - pa.line_value AS FLOAT64) AS v12_edge,
    pa.prediction_correct AS v12_correct
  FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
  WHERE pa.game_date BETWEEN @start_date AND @end_date
    AND pa.system_id = 'catboost_v12'
    AND pa.recommendation IN ('OVER', 'UNDER')
    AND pa.is_voided IS NOT TRUE
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY pa.player_lookup, pa.game_id ORDER BY pa.graded_at DESC
  ) = 1
),

streak_data AS (
  SELECT
    player_lookup,
    game_date,
    LAG(CAST(prediction_correct AS INT64), 1) OVER w AS prev_correct_1,
    LAG(CAST(prediction_correct AS INT64), 2) OVER w AS prev_correct_2,
    LAG(CAST(prediction_correct AS INT64), 3) OVER w AS prev_correct_3,
    LAG(CAST(prediction_correct AS INT64), 4) OVER w AS prev_correct_4,
    LAG(CAST(prediction_correct AS INT64), 5) OVER w AS prev_correct_5,
    LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 1) OVER w AS prev_over_1,
    LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 2) OVER w AS prev_over_2,
    LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 3) OVER w AS prev_over_3,
    LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 4) OVER w AS prev_over_4,
    LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 5) OVER w AS prev_over_5
  FROM (
    SELECT *
    FROM `nba-props-platform.nba_predictions.prediction_accuracy`
    WHERE game_date >= '2025-10-22'
      AND system_id = 'catboost_v9'
      AND recommendation IN ('OVER', 'UNDER')
      AND prediction_correct IS NOT NULL
      AND is_voided IS NOT TRUE
      AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY player_lookup, game_id ORDER BY graded_at DESC
    ) = 1
  )
  WINDOW w AS (PARTITION BY player_lookup ORDER BY game_date)
),

feature_data AS (
  SELECT
    fs.player_lookup,
    fs.game_date,
    fs.feature_14_value AS opponent_pace,
    fs.feature_22_value AS team_pace,
    fs.feature_2_value AS points_avg_season,
    CASE
      WHEN fs.feature_2_value > 25 THEN 'elite'
      WHEN fs.feature_2_value >= 20 THEN 'stars'
      WHEN fs.feature_2_value >= 15 THEN 'starters'
      WHEN fs.feature_2_value >= 10 THEN 'role'
      ELSE 'bench'
    END as player_tier
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` fs
  WHERE fs.game_date BETWEEN @start_date AND @end_date
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY fs.player_lookup, fs.game_date ORDER BY fs.updated_at DESC
  ) = 1
),

game_stats AS (
  SELECT
    player_lookup,
    game_date,
    SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)) AS three_pct,
    three_pt_attempts,
    minutes_played,
    AVG(SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS three_pct_last_3,
    AVG(SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS three_pct_season,
    STDDEV(SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS three_pct_std,
    AVG(CAST(three_pt_attempts AS FLOAT64))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS three_pa_per_game,
    AVG(minutes_played)
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS minutes_avg_last_3,
    AVG(minutes_played)
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS minutes_avg_season,
    SAFE_DIVIDE(fg_makes, NULLIF(fg_attempts, 0)) AS fg_pct,
    AVG(SAFE_DIVIDE(fg_makes, NULLIF(fg_attempts, 0)))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS fg_pct_last_3,
    AVG(SAFE_DIVIDE(fg_makes, NULLIF(fg_attempts, 0)))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS fg_pct_season,
    STDDEV(SAFE_DIVIDE(fg_makes, NULLIF(fg_attempts, 0)))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS fg_pct_std,
    DATE_DIFF(game_date,
      LAG(game_date, 1) OVER (PARTITION BY player_lookup ORDER BY game_date),
      DAY) AS rest_days,
    LAG(minutes_played, 1)
      OVER (PARTITION BY player_lookup ORDER BY game_date) AS prev_minutes,
    starter_flag,
    AVG(usage_rate)
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS usage_avg_season,
    AVG(CAST(ft_attempts AS FLOAT64))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS fta_season,
    AVG(CAST(unassisted_fg_makes AS FLOAT64))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS unassisted_fg_season,
    STDDEV(CAST(points AS FLOAT64))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS points_std_last_5,
    -- Plus/minus streak (Session 294)
    plus_minus,
    LAG(CASE WHEN plus_minus < 0 THEN 1 ELSE 0 END, 1)
      OVER (PARTITION BY player_lookup ORDER BY game_date) AS neg_pm_1,
    LAG(CASE WHEN plus_minus < 0 THEN 1 ELSE 0 END, 2)
      OVER (PARTITION BY player_lookup ORDER BY game_date) AS neg_pm_2,
    LAG(CASE WHEN plus_minus < 0 THEN 1 ELSE 0 END, 3)
      OVER (PARTITION BY player_lookup ORDER BY game_date) AS neg_pm_3
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2025-10-22'
    AND minutes_played > 0
),

-- Prop line delta (Session 294 — previous game's line for each player)
prev_lines AS (
  SELECT
    pa.player_lookup,
    pa.game_date,
    pa.line_value AS current_line,
    LAG(pa.line_value, 1) OVER (
      PARTITION BY pa.player_lookup ORDER BY pa.game_date
    ) AS prev_line_value
  FROM (
    SELECT player_lookup, game_date, line_value
    FROM `nba-props-platform.nba_predictions.prediction_accuracy`
    WHERE game_date >= '2025-10-22'
      AND system_id = 'catboost_v9'
      AND recommendation IN ('OVER', 'UNDER')
      AND is_voided IS NOT TRUE
      AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY player_lookup, game_id ORDER BY graded_at DESC
    ) = 1
  ) pa
),

pace_thresholds AS (
  SELECT
    APPROX_QUANTILES(feature_14_value, 100)[OFFSET(83)] AS opp_pace_top5,
    APPROX_QUANTILES(feature_22_value, 100)[OFFSET(50)] AS team_pace_bottom15
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE game_date BETWEEN @start_date AND @end_date
    AND feature_14_value IS NOT NULL
    AND feature_22_value IS NOT NULL
)

SELECT
  v9.*,
  v12.v12_recommendation,
  v12.v12_edge,
  v12.v12_correct,
  fd.opponent_pace,
  fd.team_pace,
  fd.points_avg_season,
  fd.player_tier,
  gs.three_pct_last_3,
  gs.three_pct_season,
  gs.three_pct_std,
  gs.three_pa_per_game,
  gs.minutes_avg_last_3,
  gs.minutes_avg_season,
  gs.fg_pct_last_3,
  gs.fg_pct_season,
  gs.fg_pct_std,
  gs.rest_days,
  gs.prev_minutes,
  gs.starter_flag,
  gs.usage_avg_season,
  gs.fta_season,
  gs.unassisted_fg_season,
  gs.points_std_last_5,
  gs.neg_pm_1,
  gs.neg_pm_2,
  gs.neg_pm_3,
  sd.prev_correct_1, sd.prev_correct_2, sd.prev_correct_3,
  sd.prev_correct_4, sd.prev_correct_5,
  sd.prev_over_1, sd.prev_over_2, sd.prev_over_3,
  sd.prev_over_4, sd.prev_over_5,
  pt.opp_pace_top5,
  pt.team_pace_bottom15,
  pl.prev_line_value,
  ROUND(CAST(v9.line_value AS FLOAT64) - pl.prev_line_value, 1) AS prop_line_delta
FROM v9_preds v9
LEFT JOIN v12_preds v12
  ON v12.player_lookup = v9.player_lookup AND v12.game_id = v9.game_id
LEFT JOIN feature_data fd
  ON fd.player_lookup = v9.player_lookup AND fd.game_date = v9.game_date
LEFT JOIN game_stats gs
  ON gs.player_lookup = v9.player_lookup AND gs.game_date = v9.game_date
LEFT JOIN streak_data sd
  ON sd.player_lookup = v9.player_lookup AND sd.game_date = v9.game_date
LEFT JOIN prev_lines pl
  ON pl.player_lookup = v9.player_lookup AND pl.game_date = v9.game_date
CROSS JOIN pace_thresholds pt
ORDER BY v9.game_date, v9.player_lookup
"""


def load_data(client: bigquery.Client, start: str, end: str, query: str) -> List[Dict]:
    """Load data for a date range."""
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start),
            bigquery.ScalarQueryParameter("end_date", "DATE", end),
        ]
    )
    rows = client.query(query, job_config=job_config).result(timeout=300)
    return [dict(row) for row in rows]


# ── Evaluation logic ─────────────────────────────────────────────────────────

def build_pred_and_supplemental(row: Dict) -> Tuple[Dict, Dict, Dict]:
    """Build prediction dict, features dict, and supplemental dict from a row."""
    pred = {
        'player_lookup': row['player_lookup'],
        'game_id': row['game_id'],
        'game_date': row['game_date'],
        'predicted_points': float(row['predicted_points'] or 0),
        'line_value': float(row['line_value'] or 0),
        'recommendation': row['recommendation'],
        'edge': float(row['edge'] or 0),
        'actual_points': row['actual_points'],
        'prediction_correct': row['prediction_correct'],
        'confidence_score': float(row['confidence_score'] or 0),
        'rest_days': row.get('rest_days'),
        'player_tier': row.get('player_tier', 'unknown'),
        'points_avg_season': float(row.get('points_avg_season') or 0),
        'starter_flag': row.get('starter_flag'),
        'usage_avg_season': float(row.get('usage_avg_season') or 0),
        'fta_season': float(row.get('fta_season') or 0),
        'unassisted_fg_season': float(row.get('unassisted_fg_season') or 0),
        'points_std_last_5': float(row.get('points_std_last_5') or 0),
    }

    # Prop line delta for aggregator pre-filter
    if row.get('prop_line_delta') is not None:
        pred['prop_line_delta'] = float(row['prop_line_delta'])

    # Neg +/- streak for aggregator pre-filter
    neg_pm_streak = 0
    for lag_val in [row.get('neg_pm_1'), row.get('neg_pm_2'), row.get('neg_pm_3')]:
        if lag_val == 1:
            neg_pm_streak += 1
        else:
            break
    if neg_pm_streak > 0:
        pred['neg_pm_streak'] = neg_pm_streak

    features = {}
    if row.get('opponent_pace') is not None:
        features['opponent_pace'] = float(row['opponent_pace'])
    if row.get('team_pace') is not None:
        features['team_pace'] = float(row['team_pace'])

    supplemental: Dict[str, Any] = {}

    if row.get('v12_recommendation'):
        supplemental['v12_prediction'] = {
            'recommendation': row['v12_recommendation'],
            'edge': float(row['v12_edge'] or 0),
        }

    if row.get('three_pct_last_3') is not None:
        supplemental['three_pt_stats'] = {
            'three_pct_last_3': float(row['three_pct_last_3']),
            'three_pct_season': float(row.get('three_pct_season') or 0),
            'three_pct_std': float(row.get('three_pct_std') or 0),
            'three_pa_per_game': float(row.get('three_pa_per_game') or 0),
        }

    if row.get('minutes_avg_last_3') is not None:
        supplemental['minutes_stats'] = {
            'minutes_avg_last_3': float(row['minutes_avg_last_3']),
            'minutes_avg_season': float(row.get('minutes_avg_season') or 0),
        }

    if row.get('opp_pace_top5') is not None:
        supplemental['pace_thresholds'] = {
            'opp_pace_top5': float(row['opp_pace_top5']),
            'team_pace_bottom15': float(row['team_pace_bottom15']),
        }

    if row.get('fg_pct_last_3') is not None:
        supplemental['fg_stats'] = {
            'fg_pct_last_3': float(row['fg_pct_last_3']),
            'fg_pct_season': float(row.get('fg_pct_season') or 0),
            'fg_pct_std': float(row.get('fg_pct_std') or 0),
        }

    if row.get('prev_correct_1') is not None:
        prev_correct = [row.get(f'prev_correct_{i}') for i in range(1, 6)]
        prev_over = [row.get(f'prev_over_{i}') for i in range(1, 6)]

        consecutive_beats = 0
        for val in prev_correct:
            if val == 1:
                consecutive_beats += 1
            else:
                break

        consecutive_misses = 0
        last_miss_direction = None
        for i, val in enumerate(prev_correct):
            if val == 0:
                consecutive_misses += 1
                if i < len(prev_over) and prev_over[i] is not None:
                    last_miss_direction = 'OVER' if prev_over[i] == 1 else 'UNDER'
            else:
                break

        player_game_key = f"{pred['player_lookup']}::{pred['game_date']}"
        supplemental['streak_data'] = {
            player_game_key: {
                'consecutive_line_beats': consecutive_beats,
                'consecutive_line_misses': consecutive_misses,
                'last_miss_direction': last_miss_direction,
            }
        }
        supplemental['streak_stats'] = {
            'prev_correct': prev_correct,
            'prev_over': prev_over,
            'consecutive_line_beats': consecutive_beats,
            'consecutive_line_misses': consecutive_misses,
        }

    if row.get('rest_days') is not None:
        supplemental['rest_stats'] = {
            'rest_days': int(row['rest_days']),
        }

    supplemental['player_profile'] = {
        'starter_flag': row.get('starter_flag'),
        'points_avg_season': float(row.get('points_avg_season') or 0),
        'usage_avg_season': float(row.get('usage_avg_season') or 0),
        'fta_season': float(row.get('fta_season') or 0),
        'unassisted_fg_season': float(row.get('unassisted_fg_season') or 0),
        'points_std_last_5': float(row.get('points_std_last_5') or 0),
    }

    if (row.get('prev_minutes') is not None
            and row.get('minutes_avg_season') is not None):
        supplemental['recovery_stats'] = {
            'prev_minutes': float(row['prev_minutes']),
            'minutes_avg_season': float(row['minutes_avg_season']),
        }

    # Prop line stats for prop_line_drop_over signal
    if row.get('prev_line_value') is not None:
        current_line = float(row.get('line_value') or 0)
        prev_line = float(row['prev_line_value'])
        supplemental['prop_line_stats'] = {
            'prev_line_value': prev_line,
            'current_line_value': current_line,
            'line_delta': round(current_line - prev_line, 1),
        }

    return pred, features, supplemental


def evaluate_signals(rows: List[Dict], registry) -> Tuple[
    Dict[str, List[Dict]], Dict[str, List], List[Dict]
]:
    """Run all signals against loaded rows. Returns per_signal, signal_results, predictions."""
    per_signal: Dict[str, List[Dict]] = defaultdict(list)
    signal_results: Dict[str, List] = defaultdict(list)
    predictions = []

    for row in rows:
        pred, features, supplemental = build_pred_and_supplemental(row)
        predictions.append(pred)

        key = f"{pred['player_lookup']}::{pred['game_id']}"
        for signal in registry.all():
            result = signal.evaluate(pred, features, supplemental)
            signal_results[key].append(result)
            if result.qualifies:
                per_signal[signal.tag].append({**pred, 'signal_meta': result.metadata})

    return per_signal, signal_results, predictions


# ── Metrics ──────────────────────────────────────────────────────────────────

def compute_metrics(picks: List[Dict]) -> Dict:
    """Compute hit rate, N, ROI, and P&L."""
    if not picks:
        return {'hit_rate': None, 'n': 0, 'roi': None, 'pnl': 0}

    correct = sum(1 for p in picks if p.get('prediction_correct'))
    total = len(picks)
    hit_rate = round(100.0 * correct / total, 1) if total else None
    wins = correct
    losses = total - correct
    profit = wins * 100 - losses * 110
    roi = round(100.0 * profit / (total * 110), 1) if total else None

    return {'hit_rate': hit_rate, 'n': total, 'roi': roi, 'pnl': profit}


def compute_daily_picks(predictions: List[Dict],
                        signal_results: Dict[str, List],
                        aggregator: BestBetsAggregator) -> List[Dict]:
    """Run aggregator daily and collect all top picks."""
    by_date = defaultdict(list)
    for pred in predictions:
        by_date[str(pred['game_date'])].append(pred)

    all_picks = []
    for date_str in sorted(by_date.keys()):
        day_preds = by_date[date_str]
        day_sr = {}
        for pred in day_preds:
            key = f"{pred['player_lookup']}::{pred['game_id']}"
            if key in signal_results:
                day_sr[key] = signal_results[key]
        picks = aggregator.aggregate(day_preds, day_sr)
        all_picks.extend(picks)

    return all_picks


def pure_edge_top5(predictions: List[Dict]) -> List[Dict]:
    """Baseline: top 5 by absolute edge per day, edge >= 3."""
    by_date = defaultdict(list)
    for pred in predictions:
        if abs(pred.get('edge', 0)) >= 3.0:
            by_date[str(pred['game_date'])].append(pred)

    all_picks = []
    for date_str in sorted(by_date.keys()):
        day_preds = by_date[date_str]
        day_preds.sort(key=lambda x: abs(x.get('edge', 0)), reverse=True)
        all_picks.extend(day_preds[:5])

    return all_picks


# ── Printing ─────────────────────────────────────────────────────────────────

def print_header(title: str) -> None:
    print(f"\n{'=' * 74}")
    print(f"  {title}")
    print(f"{'=' * 74}")


def print_metrics_row(label: str, m: Dict, indent: int = 2) -> None:
    pad = ' ' * indent
    hr = f"{m['hit_rate']:.1f}%" if m['hit_rate'] is not None else "--"
    roi = f"{m['roi']:.1f}%" if m['roi'] is not None else "--"
    pnl = f"${m['pnl']:+,}" if m.get('pnl') is not None else "--"
    print(f"{pad}{label:<42} N={m['n']:<5} HR={hr:<7} ROI={roi:<7} P&L={pnl}")


# ── AUDIT 1: Signal system vs pure edge ──────────────────────────────────────

def audit_signal_vs_edge(predictions, signal_results, registry):
    """Compare signal aggregator picks vs pure edge-based filtering."""
    print_header("AUDIT 1: SIGNAL SYSTEM vs PURE EDGE BASELINE")

    # Scenario A: Pure edge top 5 per day
    edge_picks = pure_edge_top5(predictions)
    edge_m = compute_metrics(edge_picks)
    print_metrics_row("A) Pure edge top-5/day (edge >= 3)", edge_m)

    # Scenario B: Current signal aggregator (v294)
    agg = BestBetsAggregator()
    signal_picks = compute_daily_picks(predictions, signal_results, agg)
    signal_m = compute_metrics(signal_picks)
    print_metrics_row("B) Signal aggregator top-5/day (v294)", signal_m)

    # Scenario C: Signal aggregator WITHOUT Session 294 pre-filters
    # (same aggregator but with prop_line_delta and neg_pm_streak removed from preds)
    clean_preds = []
    for pred in predictions:
        p = dict(pred)
        p.pop('prop_line_delta', None)
        p.pop('neg_pm_streak', None)
        clean_preds.append(p)
    agg_no294 = BestBetsAggregator()
    no294_picks = compute_daily_picks(clean_preds, signal_results, agg_no294)
    no294_m = compute_metrics(no294_picks)
    print_metrics_row("C) Signal aggregator WITHOUT s294 filters", no294_m)

    # Scenario D: All V9 edge 3+ (no top-5 limit)
    all_edge3 = [p for p in predictions if abs(p.get('edge', 0)) >= 3.0]
    all_edge3_m = compute_metrics(all_edge3)
    print_metrics_row("D) All V9 edge 3+ (no limit, reference)", all_edge3_m)

    # Monthly breakdown
    print(f"\n  Monthly breakdown (Signal aggregator B):")
    monthly = defaultdict(list)
    for p in signal_picks:
        month = str(p['game_date'])[:7]
        monthly[month].append(p)
    for month in sorted(monthly.keys()):
        m = compute_metrics(monthly[month])
        print_metrics_row(f"  {month}", m, indent=4)

    return {
        'pure_edge_top5': edge_m,
        'signal_aggregator_v294': signal_m,
        'signal_aggregator_no_s294': no294_m,
        'all_v9_edge3': all_edge3_m,
    }


# ── AUDIT 2: Model directional bias + UNDER signal need ─────────────────────

def audit_model_bias(all_model_data: List[Dict]):
    """Analyze per-model directional performance and UNDER signal gap."""
    print_header("AUDIT 2: MODEL DIRECTIONAL BIAS & UNDER SIGNAL NEED")

    # Group by model
    by_model: Dict[str, List[Dict]] = defaultdict(list)
    for row in all_model_data:
        # Normalize system_id to short form
        sid = row['system_id']
        if abs(float(row['edge'] or 0)) >= 3.0:
            by_model[sid].append(row)

    print(f"\n  Per-model performance (edge >= 3 only):")
    print(f"  {'Model':<45} {'N':>5} {'HR':>7} {'OVER_N':>7} {'OVER_HR':>8} {'UNDER_N':>8} {'UNDER_HR':>9}")
    print(f"  {'-' * 95}")

    model_stats = {}
    for sid in sorted(by_model.keys()):
        picks = by_model[sid]
        m_all = compute_metrics(picks)
        over_picks = [p for p in picks if p['recommendation'] == 'OVER']
        under_picks = [p for p in picks if p['recommendation'] == 'UNDER']
        m_over = compute_metrics(over_picks)
        m_under = compute_metrics(under_picks)

        over_hr = f"{m_over['hit_rate']:.1f}%" if m_over['hit_rate'] is not None else "--"
        under_hr = f"{m_under['hit_rate']:.1f}%" if m_under['hit_rate'] is not None else "--"
        all_hr = f"{m_all['hit_rate']:.1f}%" if m_all['hit_rate'] is not None else "--"
        print(f"  {sid:<45} {m_all['n']:>5} {all_hr:>7} {m_over['n']:>7} {over_hr:>8} {m_under['n']:>8} {under_hr:>9}")

        model_stats[sid] = {
            'all': m_all,
            'over': m_over,
            'under': m_under,
        }

    # Identify UNDER specialists
    print(f"\n  UNDER specialists (HR > 55% on UNDER, edge 3+):")
    for sid, stats in sorted(model_stats.items()):
        if (stats['under']['hit_rate'] is not None
                and stats['under']['hit_rate'] > 55.0
                and stats['under']['n'] >= 10):
            print(f"    {sid}: {stats['under']['hit_rate']:.1f}% HR on {stats['under']['n']} UNDER picks")

    # Identify OVER specialists
    print(f"\n  OVER specialists (HR > 55% on OVER, edge 3+):")
    for sid, stats in sorted(model_stats.items()):
        if (stats['over']['hit_rate'] is not None
                and stats['over']['hit_rate'] > 55.0
                and stats['over']['n'] >= 10):
            print(f"    {sid}: {stats['over']['hit_rate']:.1f}% HR on {stats['over']['n']} OVER picks")

    return model_stats


# ── AUDIT 3: Signal-model alignment ─────────────────────────────────────────

def audit_signal_model_alignment(predictions, signal_results, per_signal, registry):
    """Test whether signals help or hurt for different directions."""
    print_header("AUDIT 3: SIGNAL-MODEL ALIGNMENT")

    # For each signal, break down HR by direction
    print(f"\n  Per-signal performance by direction (edge 3+):")
    print(f"  {'Signal':<28} {'OVER_N':>7} {'OVER_HR':>8} {'UNDER_N':>8} {'UNDER_HR':>9} {'Combined_HR':>12}")
    print(f"  {'-' * 78}")

    signal_dir_stats = {}
    for tag in sorted(per_signal.keys()):
        picks = per_signal[tag]
        edge_picks = [p for p in picks if abs(p.get('edge', 0)) >= 3.0]
        over = [p for p in edge_picks if p['recommendation'] == 'OVER']
        under = [p for p in edge_picks if p['recommendation'] == 'UNDER']
        m_over = compute_metrics(over)
        m_under = compute_metrics(under)
        m_all = compute_metrics(edge_picks)

        over_hr = f"{m_over['hit_rate']:.1f}%" if m_over['hit_rate'] else "--"
        under_hr = f"{m_under['hit_rate']:.1f}%" if m_under['hit_rate'] else "--"
        all_hr = f"{m_all['hit_rate']:.1f}%" if m_all['hit_rate'] else "--"
        print(f"  {tag:<28} {m_over['n']:>7} {over_hr:>8} {m_under['n']:>8} {under_hr:>9} {all_hr:>12}")

        signal_dir_stats[tag] = {
            'over': m_over, 'under': m_under, 'combined': m_all,
        }

    # Identify signals that actually help UNDER
    print(f"\n  Signals that HELP UNDER picks (HR > 55%, N >= 5):")
    for tag, stats in sorted(signal_dir_stats.items()):
        if (stats['under']['hit_rate'] is not None
                and stats['under']['hit_rate'] > 55.0
                and stats['under']['n'] >= 5):
            print(f"    {tag}: {stats['under']['hit_rate']:.1f}% HR on {stats['under']['n']} UNDER picks")

    # Which signals are OVER-only by outcome (even if BOTH direction)
    print(f"\n  Signals where OVER outperforms UNDER by 10+ pp:")
    for tag, stats in sorted(signal_dir_stats.items()):
        oh = stats['over']['hit_rate']
        uh = stats['under']['hit_rate']
        if oh is not None and uh is not None and (oh - uh) > 10:
            print(f"    {tag}: OVER={oh:.1f}% vs UNDER={uh:.1f}% (gap={oh-uh:.1f}pp)")

    return signal_dir_stats


# ── AUDIT 4: Consensus bonus validation ──────────────────────────────────────

def audit_consensus_bonus(predictions, signal_results, all_model_data):
    """Compare aggregator WITH vs WITHOUT consensus bonus."""
    print_header("AUDIT 4: CONSENSUS BONUS VALIDATION")

    # Build cross-model factors from all_model_data
    # Group by player_lookup::game_id
    model_by_player: Dict[str, Dict[str, Dict]] = defaultdict(dict)
    for row in all_model_data:
        key = f"{row['player_lookup']}::{row['game_id']}"
        model_by_player[key][row['system_id']] = {
            'recommendation': row['recommendation'],
            'edge': float(row['edge'] or 0),
        }

    from shared.config.cross_model_subsets import V9_FEATURE_SET, V12_FEATURE_SET, QUANTILE_MODELS as QM_LIST

    factors = {}
    for key, models in model_by_player.items():
        over_models = []
        under_models = []
        for mid, pred in models.items():
            if abs(pred['edge']) < 3.0:
                continue
            if pred['recommendation'] == 'OVER':
                over_models.append(mid)
            else:
                under_models.append(mid)

        if not over_models and not under_models:
            continue

        if len(over_models) >= len(under_models):
            majority_dir = 'OVER'
            agreeing = over_models
        else:
            majority_dir = 'UNDER'
            agreeing = under_models

        n_agreeing = len(agreeing)
        has_v9 = any(m in V9_FEATURE_SET for m in agreeing)
        has_v12 = any(m in V12_FEATURE_SET for m in agreeing)
        feature_diversity = (1 if has_v9 else 0) + (1 if has_v12 else 0)

        quantile_under = (
            majority_dir == 'UNDER'
            and all(m in agreeing for m in QM_LIST)
        )

        agreeing_edges = [abs(models[m]['edge']) for m in agreeing if m in models]
        avg_edge = sum(agreeing_edges) / len(agreeing_edges) if agreeing_edges else 0

        agreement_base = 0.05 * (n_agreeing - 2) if n_agreeing >= 3 else 0
        diversity_mult = 1.3 if (has_v9 and has_v12) else 1.0
        quantile_bonus = 0.10 if quantile_under else 0
        consensus_bonus = round(agreement_base * diversity_mult + quantile_bonus, 4)

        factors[key] = {
            'model_agreement_count': n_agreeing,
            'majority_direction': majority_dir,
            'feature_set_diversity': feature_diversity,
            'quantile_consensus_under': quantile_under,
            'avg_edge_agreeing': round(avg_edge, 2),
            'consensus_bonus': consensus_bonus,
            'agreeing_model_ids': agreeing,
        }

    with_bonus_count = sum(1 for f in factors.values() if f['consensus_bonus'] > 0)
    print(f"  Cross-model factors computed: {len(factors)} player-games, "
          f"{with_bonus_count} with bonus > 0")

    # A: Aggregator WITH consensus bonus
    agg_with = BestBetsAggregator(cross_model_factors=factors)
    picks_with = compute_daily_picks(predictions, signal_results, agg_with)
    m_with = compute_metrics(picks_with)
    print_metrics_row("A) Aggregator WITH consensus bonus", m_with)

    # B: Aggregator WITHOUT consensus bonus (empty factors)
    agg_without = BestBetsAggregator(cross_model_factors={})
    picks_without = compute_daily_picks(predictions, signal_results, agg_without)
    m_without = compute_metrics(picks_without)
    print_metrics_row("B) Aggregator WITHOUT consensus bonus", m_without)

    # Overlap analysis: how many picks change?
    with_keys = set(f"{p['player_lookup']}::{p['game_id']}" for p in picks_with)
    without_keys = set(f"{p['player_lookup']}::{p['game_id']}" for p in picks_without)
    overlap = with_keys & without_keys
    only_with = with_keys - without_keys
    only_without = without_keys - with_keys
    print(f"\n  Pick overlap: {len(overlap)} same, "
          f"{len(only_with)} only-with-bonus, {len(only_without)} only-without-bonus")

    # Analyze picks unique to WITH bonus — are they better?
    if only_with:
        with_unique = [p for p in picks_with
                       if f"{p['player_lookup']}::{p['game_id']}" in only_with]
        m_wu = compute_metrics(with_unique)
        print_metrics_row("  Picks ADDED by consensus bonus", m_wu, indent=4)

    if only_without:
        without_unique = [p for p in picks_without
                          if f"{p['player_lookup']}::{p['game_id']}" in only_without]
        m_wou = compute_metrics(without_unique)
        print_metrics_row("  Picks REMOVED by consensus bonus", m_wou, indent=4)

    # Consensus bonus distribution for winning vs losing picks
    bonus_dist = {'winners': [], 'losers': []}
    for p in picks_with:
        cb = p.get('consensus_bonus', 0)
        if p.get('prediction_correct'):
            bonus_dist['winners'].append(cb)
        else:
            bonus_dist['losers'].append(cb)

    if bonus_dist['winners']:
        avg_w = sum(bonus_dist['winners']) / len(bonus_dist['winners'])
        avg_l = sum(bonus_dist['losers']) / len(bonus_dist['losers']) if bonus_dist['losers'] else 0
        print(f"\n  Avg consensus bonus: winners={avg_w:.4f}, losers={avg_l:.4f}")

    return {
        'with_bonus': m_with,
        'without_bonus': m_without,
        'overlap': len(overlap),
        'only_with_bonus': len(only_with),
        'only_without_bonus': len(only_without),
    }


# ── AUDIT 5: Quantile model integration test ────────────────────────────────

def audit_quantile_integration(all_model_data: List[Dict], predictions: List[Dict]):
    """Test what happens if we include quantile model UNDER picks in best bets."""
    print_header("AUDIT 5: QUANTILE MODEL UNDER PICKS (MISSED OPPORTUNITY)")

    # Get quantile model UNDER picks with edge >= 3
    q_under = [
        row for row in all_model_data
        if 'q4' in row['system_id']
        and row['recommendation'] == 'UNDER'
        and abs(float(row['edge'] or 0)) >= 3.0
    ]

    # Cross-reference with V9 picks for the same player-game
    v9_keys = set(f"{p['player_lookup']}::{p['game_id']}" for p in predictions)
    q_in_v9 = [r for r in q_under if f"{r['player_lookup']}::{r['game_id']}" in v9_keys]
    q_not_in_v9 = [r for r in q_under if f"{r['player_lookup']}::{r['game_id']}" not in v9_keys]

    m_all_q = compute_metrics(q_under)
    m_in_v9 = compute_metrics(q_in_v9)
    m_not_in_v9 = compute_metrics(q_not_in_v9)

    print_metrics_row("All quantile UNDER picks (edge 3+)", m_all_q)
    print_metrics_row("  Overlap with V9 predictions", m_in_v9)
    print_metrics_row("  Unique to quantile models", m_not_in_v9)

    # By quantile model family
    print(f"\n  Per quantile model UNDER performance:")
    q_models = defaultdict(list)
    for row in q_under:
        q_models[row['system_id']].append(row)
    for mid in sorted(q_models.keys()):
        m = compute_metrics(q_models[mid])
        print_metrics_row(f"  {mid}", m, indent=4)

    # Simulate: what if we added top-2 quantile UNDER picks to daily best bets?
    by_date: Dict[str, List[Dict]] = defaultdict(list)
    for row in q_under:
        by_date[str(row['game_date'])].append(row)

    q_top2_daily = []
    for date_str in sorted(by_date.keys()):
        day_q = by_date[date_str]
        day_q.sort(key=lambda x: abs(float(x['edge'] or 0)), reverse=True)
        q_top2_daily.extend(day_q[:2])

    m_q_top2 = compute_metrics(q_top2_daily)
    print(f"\n  Simulated: top-2 quantile UNDER picks per day:")
    print_metrics_row("Top-2 quantile UNDER daily", m_q_top2)

    return {
        'all_quantile_under': m_all_q,
        'overlap_with_v9': m_in_v9,
        'unique_to_quantile': m_not_in_v9,
        'top2_daily': m_q_top2,
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Signal System Comprehensive Audit")
    parser.add_argument('--save', action='store_true',
                        help="Save results to ml/experiments/results/")
    parser.add_argument('--start', default='2025-11-04',
                        help="Start date (default: 2025-11-04)")
    parser.add_argument('--end', default='2026-02-17',
                        help="End date (default: 2026-02-17)")
    args = parser.parse_args()

    client = bigquery.Client(project='nba-props-platform')
    registry = build_default_registry()

    print_header(f"SIGNAL SYSTEM COMPREHENSIVE AUDIT — {args.start} to {args.end}")
    print(f"  Signals: {len(registry.tags())} active")
    print(f"  Date range: {args.start} to {args.end}")

    # ── Load data ────────────────────────────────────────────────────────────
    print(f"\n  Loading all model predictions from prediction_accuracy...")
    all_model_data = load_data(client, args.start, args.end, QUERY_ALL_MODELS)
    print(f"  Loaded {len(all_model_data)} total predictions across all models")

    model_counts = defaultdict(int)
    for row in all_model_data:
        model_counts[row['system_id']] += 1
    for mid in sorted(model_counts.keys()):
        print(f"    {mid}: {model_counts[mid]:,}")

    print(f"\n  Loading V9 predictions with supplemental data...")
    v9_rows = load_data(client, args.start, args.end, QUERY_V9_WITH_SUPPLEMENTS)
    print(f"  Loaded {len(v9_rows)} V9 rows with supplements")

    # ── Evaluate signals ─────────────────────────────────────────────────────
    print(f"\n  Evaluating {len(registry.tags())} signals against {len(v9_rows)} predictions...")
    per_signal, signal_results, predictions = evaluate_signals(v9_rows, registry)
    for tag in sorted(per_signal.keys()):
        n = len(per_signal[tag])
        if n > 0:
            print(f"    {tag}: {n} qualifying picks")

    # ── Run audits ───────────────────────────────────────────────────────────
    results = {}

    results['audit1_signal_vs_edge'] = audit_signal_vs_edge(
        predictions, signal_results, registry)

    results['audit2_model_bias'] = audit_model_bias(all_model_data)

    results['audit3_signal_alignment'] = audit_signal_model_alignment(
        predictions, signal_results, per_signal, registry)

    results['audit4_consensus_bonus'] = audit_consensus_bonus(
        predictions, signal_results, all_model_data)

    results['audit5_quantile_integration'] = audit_quantile_integration(
        all_model_data, predictions)

    # ── Summary ──────────────────────────────────────────────────────────────
    print_header("EXECUTIVE SUMMARY")
    a1 = results['audit1_signal_vs_edge']
    print(f"  Q1: Does signal system beat pure edge?")
    if a1['signal_aggregator_v294']['hit_rate'] and a1['pure_edge_top5']['hit_rate']:
        delta = a1['signal_aggregator_v294']['hit_rate'] - a1['pure_edge_top5']['hit_rate']
        print(f"      Signal: {a1['signal_aggregator_v294']['hit_rate']:.1f}% HR "
              f"vs Edge: {a1['pure_edge_top5']['hit_rate']:.1f}% HR "
              f"(delta: {delta:+.1f}pp)")
        pnl_delta = a1['signal_aggregator_v294']['pnl'] - a1['pure_edge_top5']['pnl']
        print(f"      P&L: Signal ${a1['signal_aggregator_v294']['pnl']:+,} "
              f"vs Edge ${a1['pure_edge_top5']['pnl']:+,} "
              f"(delta: ${pnl_delta:+,})")

    a4 = results['audit4_consensus_bonus']
    print(f"\n  Q4: Does consensus bonus help?")
    if a4['with_bonus']['hit_rate'] and a4['without_bonus']['hit_rate']:
        delta = a4['with_bonus']['hit_rate'] - a4['without_bonus']['hit_rate']
        print(f"      With: {a4['with_bonus']['hit_rate']:.1f}% HR "
              f"vs Without: {a4['without_bonus']['hit_rate']:.1f}% HR "
              f"(delta: {delta:+.1f}pp)")

    # ── Save ─────────────────────────────────────────────────────────────────
    if args.save:
        results_dir = os.path.join(os.path.dirname(__file__), 'results')
        os.makedirs(results_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = os.path.join(results_dir, f'signal_system_audit_{ts}.json')

        def default_serializer(obj):
            if hasattr(obj, 'isoformat'):
                return obj.isoformat()
            return str(obj)

        with open(path, 'w') as f:
            json.dump(results, f, indent=2, default=default_serializer)
        print(f"\n  Results saved to {path}")


if __name__ == '__main__':
    main()
