#!/usr/bin/env python3
"""Signal Discovery Framework — Backtest Harness.

Loads prediction + supplemental data from BigQuery, evaluates all signals
across 4 eval windows, and reports per-signal hit rate, N, ROI,
overlap analysis, and aggregator simulation.

Usage:
    PYTHONPATH=. python ml/experiments/signal_backtest.py [--save]
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

from google.cloud import bigquery

from ml.signals.registry import build_default_registry
from ml.signals.aggregator import BestBetsAggregator

# ── Eval windows ──────────────────────────────────────────────────────────────
EVAL_WINDOWS = [
    ("W1", "2025-12-08", "2025-12-21"),
    ("W2", "2026-01-05", "2026-01-18"),
    ("W3", "2026-01-19", "2026-01-31"),
    ("W4", "2026-02-01", "2026-02-13"),
]

# ── BigQuery data loader ─────────────────────────────────────────────────────

QUERY = """
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

-- Streak data: prior prediction outcomes for hot_streak / cold_snap signals
streak_data AS (
  SELECT
    player_lookup,
    game_date,
    -- Prior model correctness (for hot_streak)
    LAG(CAST(prediction_correct AS INT64), 1) OVER w AS prev_correct_1,
    LAG(CAST(prediction_correct AS INT64), 2) OVER w AS prev_correct_2,
    LAG(CAST(prediction_correct AS INT64), 3) OVER w AS prev_correct_3,
    LAG(CAST(prediction_correct AS INT64), 4) OVER w AS prev_correct_4,
    LAG(CAST(prediction_correct AS INT64), 5) OVER w AS prev_correct_5,
    -- Prior actual over/under line (for cold_snap)
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
    fs.feature_2_value AS points_avg_season,  -- For player tier classification
    -- Player tier: elite (>25 ppg), stars (20-25), starters (15-20), role (10-15), bench (<10)
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

-- 3PT and minutes rolling stats via window functions (no fan-out joins)
game_stats AS (
  SELECT
    player_lookup,
    game_date,
    SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)) AS three_pct,
    three_pt_attempts,
    minutes_played,
    -- 3PT rolling (exclude current game: 1 PRECEDING)
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
    -- Minutes rolling (exclude current game)
    AVG(minutes_played)
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS minutes_avg_last_3,
    AVG(minutes_played)
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS minutes_avg_season,
    -- FG% rolling (exclude current game: 1 PRECEDING)
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
    -- Rest days and previous game minutes (for rest_advantage, blowout_recovery)
    DATE_DIFF(game_date,
      LAG(game_date, 1) OVER (PARTITION BY player_lookup ORDER BY game_date),
      DAY) AS rest_days,
    LAG(minutes_played, 1)
      OVER (PARTITION BY player_lookup ORDER BY game_date) AS prev_minutes,
    -- Player profile stats (for market-pattern UNDER signals, Session 274)
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
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS points_std_last_5
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2025-10-22'
    AND minutes_played > 0
),

-- Pace thresholds per eval window (top-5 and bottom-15 cutoffs)
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
  sd.prev_correct_1, sd.prev_correct_2, sd.prev_correct_3,
  sd.prev_correct_4, sd.prev_correct_5,
  sd.prev_over_1, sd.prev_over_2, sd.prev_over_3,
  sd.prev_over_4, sd.prev_over_5,
  pt.opp_pace_top5,
  pt.team_pace_bottom15
FROM v9_preds v9
LEFT JOIN v12_preds v12
  ON v12.player_lookup = v9.player_lookup AND v12.game_id = v9.game_id
LEFT JOIN feature_data fd
  ON fd.player_lookup = v9.player_lookup AND fd.game_date = v9.game_date
LEFT JOIN game_stats gs
  ON gs.player_lookup = v9.player_lookup AND gs.game_date = v9.game_date
LEFT JOIN streak_data sd
  ON sd.player_lookup = v9.player_lookup AND sd.game_date = v9.game_date
CROSS JOIN pace_thresholds pt
ORDER BY v9.game_date, v9.player_lookup
"""


def load_window_data(client: bigquery.Client,
                     start_date: str, end_date: str) -> List[Dict]:
    """Load all data for one eval window."""
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )
    rows = client.query(QUERY, job_config=job_config).result()
    return [dict(row) for row in rows]


# ── Evaluation logic ─────────────────────────────────────────────────────────

def evaluate_signals(rows: List[Dict], registry) -> Tuple[
    Dict[str, List[Dict]],       # per-signal qualifying picks
    Dict[str, List],              # signal_results keyed by player::game
    List[Dict],                   # all predictions
]:
    """Run all signals against loaded rows."""
    per_signal: Dict[str, List[Dict]] = defaultdict(list)
    signal_results: Dict[str, List] = defaultdict(list)
    predictions = []

    for row in rows:
        # Build prediction dict
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
            'rest_days': row.get('rest_days'),  # For context-aware signals
            'player_tier': row.get('player_tier', 'unknown'),  # For context-aware signals
            'points_avg_season': float(row.get('points_avg_season') or 0),
            'starter_flag': row.get('starter_flag'),
            'usage_avg_season': float(row.get('usage_avg_season') or 0),
            'fta_season': float(row.get('fta_season') or 0),
            'unassisted_fg_season': float(row.get('unassisted_fg_season') or 0),
            'points_std_last_5': float(row.get('points_std_last_5') or 0),
        }
        predictions.append(pred)

        # Build features dict (pace data from feature store)
        features = {}
        if row.get('opponent_pace') is not None:
            features['opponent_pace'] = float(row['opponent_pace'])
        if row.get('team_pace') is not None:
            features['team_pace'] = float(row['team_pace'])

        # Build supplemental dict
        supplemental = {}

        # V12 prediction
        if row.get('v12_recommendation'):
            supplemental['v12_prediction'] = {
                'recommendation': row['v12_recommendation'],
                'edge': float(row['v12_edge'] or 0),
            }

        # 3PT stats
        if row.get('three_pct_last_3') is not None:
            supplemental['three_pt_stats'] = {
                'three_pct_last_3': float(row['three_pct_last_3']),
                'three_pct_season': float(row['three_pct_season'] or 0),
                'three_pct_std': float(row['three_pct_std'] or 0),
                'three_pa_per_game': float(row['three_pa_per_game'] or 0),
            }

        # Minutes stats
        if row.get('minutes_avg_last_3') is not None:
            supplemental['minutes_stats'] = {
                'minutes_avg_last_3': float(row['minutes_avg_last_3']),
                'minutes_avg_season': float(row['minutes_avg_season'] or 0),
            }

        # Pace thresholds
        if row.get('opp_pace_top5') is not None:
            supplemental['pace_thresholds'] = {
                'opp_pace_top5': float(row['opp_pace_top5']),
                'team_pace_bottom15': float(row['team_pace_bottom15']),
            }

        # FG% stats (for fg_cold_continuation)
        if row.get('fg_pct_last_3') is not None:
            supplemental['fg_stats'] = {
                'fg_pct_last_3': float(row['fg_pct_last_3']),
                'fg_pct_season': float(row['fg_pct_season'] or 0),
                'fg_pct_std': float(row['fg_pct_std'] or 0),
            }

        # Streak stats (for hot_streak, cold_snap, cold_continuation)
        if row.get('prev_correct_1') is not None:
            prev_correct = [
                row.get('prev_correct_1'),
                row.get('prev_correct_2'),
                row.get('prev_correct_3'),
                row.get('prev_correct_4'),
                row.get('prev_correct_5'),
            ]
            prev_over = [
                row.get('prev_over_1'),
                row.get('prev_over_2'),
                row.get('prev_over_3'),
                row.get('prev_over_4'),
                row.get('prev_over_5'),
            ]

            # Calculate consecutive line beats (from most recent backwards)
            consecutive_beats = 0
            for val in prev_correct:
                if val == 1:
                    consecutive_beats += 1
                else:
                    break

            # Calculate consecutive line misses (from most recent backwards)
            consecutive_misses = 0
            last_miss_direction = None
            for i, val in enumerate(prev_correct):
                if val == 0:
                    consecutive_misses += 1
                    # Determine if last miss was OVER or UNDER
                    if i < len(prev_over) and prev_over[i] is not None:
                        last_miss_direction = 'OVER' if prev_over[i] == 1 else 'UNDER'
                else:
                    break

            # Store both formats for backwards compatibility
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

        # Rest stats (for rest_advantage)
        if row.get('rest_days') is not None:
            supplemental['rest_stats'] = {
                'rest_days': int(row['rest_days']),
            }

        # Player profile stats (for market-pattern UNDER signals, Session 274)
        supplemental['player_profile'] = {
            'starter_flag': row.get('starter_flag'),
            'points_avg_season': float(row.get('points_avg_season') or 0),
            'usage_avg_season': float(row.get('usage_avg_season') or 0),
            'fta_season': float(row.get('fta_season') or 0),
            'unassisted_fg_season': float(row.get('unassisted_fg_season') or 0),
            'points_std_last_5': float(row.get('points_std_last_5') or 0),
        }

        # Recovery stats (for blowout_recovery)
        if (row.get('prev_minutes') is not None
                and row.get('minutes_avg_season') is not None):
            supplemental['recovery_stats'] = {
                'prev_minutes': float(row['prev_minutes']),
                'minutes_avg_season': float(row['minutes_avg_season']),
            }

        # Evaluate each signal
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        for signal in registry.all():
            result = signal.evaluate(pred, features, supplemental)
            signal_results[key].append(result)
            if result.qualifies:
                per_signal[signal.tag].append({**pred, 'signal_meta': result.metadata})

    return per_signal, signal_results, predictions


def compute_metrics(picks: List[Dict]) -> Dict:
    """Compute hit rate, N, and ROI for a list of qualifying picks."""
    if not picks:
        return {'hit_rate': None, 'n': 0, 'roi': None}

    correct = sum(1 for p in picks if p.get('prediction_correct'))
    total = len(picks)
    hit_rate = round(100.0 * correct / total, 1) if total else None

    # ROI: assume -110 odds (bet $110 to win $100)
    wins = correct
    losses = total - correct
    profit = wins * 100 - losses * 110
    roi = round(100.0 * profit / (total * 110), 1) if total else None

    return {'hit_rate': hit_rate, 'n': total, 'roi': roi}


def print_header(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def print_signal_table(results: Dict[str, Dict[str, Dict]]) -> None:
    """Print per-signal x per-window table."""
    signals = sorted(results.keys())
    windows = [w[0] for w in EVAL_WINDOWS]

    # Header
    print(f"\n{'Signal':<16}", end="")
    for w in windows:
        print(f"{'|':>2} {w:>14}", end="")
    print(f"{'|':>2} {'AVG':>14}")
    print("-" * (16 + 17 * (len(windows) + 1)))

    for sig in signals:
        print(f"{sig:<16}", end="")
        hrs = []
        for w in windows:
            m = results[sig].get(w, {})
            if m.get('hit_rate') is not None:
                hrs.append(m['hit_rate'])
                print(f"| {m['hit_rate']:5.1f}% (N={m['n']:<3})", end="")
            else:
                print(f"|     -- (N=0  )", end="")
        # Average
        avg_hr = round(sum(hrs) / len(hrs), 1) if hrs else None
        if avg_hr is not None:
            print(f"| {avg_hr:5.1f}%")
        else:
            print("|     --")


def overlap_analysis(signal_results: Dict, predictions: List[Dict]) -> None:
    """Analyze picks that qualify for multiple signals."""
    print_header("SIGNAL OVERLAP ANALYSIS")

    multi_signal = []
    for pred in predictions:
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        qualifying = [r for r in signal_results.get(key, []) if r.qualifies]
        if len(qualifying) >= 2:
            multi_signal.append({
                **pred,
                'signal_tags': [r.source_tag for r in qualifying],
                'signal_count': len(qualifying),
            })

    if not multi_signal:
        print("\nNo picks qualified for 2+ signals.")
        return

    metrics = compute_metrics(multi_signal)
    print(f"\nPicks with 2+ signals: N={metrics['n']}, "
          f"HR={metrics['hit_rate']}%, ROI={metrics['roi']}%")

    # Breakdown by signal combo
    combos = defaultdict(list)
    for p in multi_signal:
        combo_key = "+".join(sorted(p['signal_tags']))
        combos[combo_key].append(p)

    print(f"\n{'Combo':<35} {'N':>4} {'HR':>7} {'ROI':>7}")
    print("-" * 55)
    for combo, picks in sorted(combos.items(), key=lambda x: -len(x[1])):
        m = compute_metrics(picks)
        hr_str = f"{m['hit_rate']:.1f}%" if m['hit_rate'] is not None else "--"
        roi_str = f"{m['roi']:.1f}%" if m['roi'] is not None else "--"
        print(f"{combo:<35} {m['n']:>4} {hr_str:>7} {roi_str:>7}")


def aggregator_simulation(signal_results: Dict, predictions: List[Dict],
                          window_name: str) -> Dict:
    """Simulate daily aggregator picks for a window."""
    aggregator = BestBetsAggregator()

    # Group predictions by date
    by_date = defaultdict(list)
    for pred in predictions:
        by_date[str(pred['game_date'])].append(pred)

    all_picks = []
    for date_str in sorted(by_date.keys()):
        day_preds = by_date[date_str]
        # Filter signal_results to this day's predictions
        day_sr = {}
        for pred in day_preds:
            key = f"{pred['player_lookup']}::{pred['game_id']}"
            if key in signal_results:
                day_sr[key] = signal_results[key]

        picks, _ = aggregator.aggregate(day_preds, day_sr)
        all_picks.extend(picks)

    metrics = compute_metrics(all_picks)
    n_days = len(by_date)
    avg_picks = round(len(all_picks) / n_days, 1) if n_days else 0

    print(f"\n  {window_name}: {len(all_picks)} picks over {n_days} days "
          f"(avg {avg_picks}/day) — HR={metrics['hit_rate']}%, "
          f"ROI={metrics['roi']}%")

    return {
        'window': window_name,
        'total_picks': len(all_picks),
        'days': n_days,
        'avg_picks_per_day': avg_picks,
        **metrics,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Signal Discovery Backtest")
    parser.add_argument('--save', action='store_true',
                        help="Save results to ml/experiments/results/")
    args = parser.parse_args()

    client = bigquery.Client(project='nba-props-platform')
    registry = build_default_registry()

    print_header("SIGNAL DISCOVERY FRAMEWORK — BACKTEST")
    print(f"Signals: {', '.join(registry.tags())}")
    print(f"Eval windows: {len(EVAL_WINDOWS)}")

    all_results = {}
    all_signal_results = {}
    all_predictions = []

    for window_name, start, end in EVAL_WINDOWS:
        print(f"\n--- Loading {window_name}: {start} to {end} ---")
        rows = load_window_data(client, start, end)
        print(f"  Loaded {len(rows)} V9 predictions")

        per_signal, signal_results, predictions = evaluate_signals(rows, registry)
        all_predictions.extend(predictions)

        for tag, picks in per_signal.items():
            metrics = compute_metrics(picks)
            if tag not in all_results:
                all_results[tag] = {}
            all_results[tag][window_name] = metrics

        # Merge signal results (keyed globally)
        for k, v in signal_results.items():
            all_signal_results[k] = v

        # Print per-signal summary for this window
        for tag in registry.tags():
            picks = per_signal.get(tag, [])
            m = compute_metrics(picks)
            if m['n'] > 0:
                print(f"  {tag:<16}: N={m['n']:<4} HR={m['hit_rate']:.1f}% "
                      f"ROI={m['roi']:.1f}%")
            else:
                print(f"  {tag:<16}: N=0")

    # ── Summary table ─────────────────────────────────────────────────────
    print_header("SIGNAL PERFORMANCE SUMMARY")
    print_signal_table(all_results)

    # Deduplicate predictions across windows (in case of date overlap)
    seen_keys = set()
    deduped_predictions = []
    for pred in all_predictions:
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        if key not in seen_keys:
            seen_keys.add(key)
            deduped_predictions.append(pred)
    all_predictions = deduped_predictions

    # ── Baseline comparison ───────────────────────────────────────────────
    print_header("BASELINE COMPARISON (V9 edge >= 3)")
    baseline_picks = [p for p in all_predictions if abs(p['edge']) >= 3.0]
    baseline_m = compute_metrics(baseline_picks)
    print(f"  All V9 edge 3+: N={baseline_m['n']}, HR={baseline_m['hit_rate']}%, "
          f"ROI={baseline_m['roi']}%")

    # ── Overlap analysis ──────────────────────────────────────────────────
    overlap_analysis(all_signal_results, all_predictions)

    # ── Aggregator simulation ─────────────────────────────────────────────
    print_header("AGGREGATOR SIMULATION (Top 5 picks/day)")

    agg_results = []
    for window_name, start, end in EVAL_WINDOWS:
        window_preds = [p for p in all_predictions
                        if start <= str(p['game_date']) <= end]
        window_sr = {}
        for pred in window_preds:
            key = f"{pred['player_lookup']}::{pred['game_id']}"
            if key in all_signal_results:
                window_sr[key] = all_signal_results[key]

        agg_m = aggregator_simulation(window_sr, window_preds, window_name)
        agg_results.append(agg_m)

    # Overall aggregator stats
    all_agg_hrs = [a['hit_rate'] for a in agg_results if a['hit_rate'] is not None]
    if all_agg_hrs:
        print(f"\n  Aggregator AVG HR: {sum(all_agg_hrs)/len(all_agg_hrs):.1f}%")

    # ── Save results ──────────────────────────────────────────────────────
    if args.save:
        results_dir = os.path.join(os.path.dirname(__file__), 'results')
        os.makedirs(results_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = os.path.join(results_dir, f'signal_backtest_{ts}.json')

        output = {
            'timestamp': ts,
            'eval_windows': [{'name': w, 'start': s, 'end': e}
                             for w, s, e in EVAL_WINDOWS],
            'signal_performance': all_results,
            'baseline': baseline_m,
            'aggregator': agg_results,
        }

        # Convert non-serializable types
        def default_serializer(obj):
            if hasattr(obj, 'isoformat'):
                return obj.isoformat()
            return str(obj)

        with open(path, 'w') as f:
            json.dump(output, f, indent=2, default=default_serializer)
        print(f"\nResults saved to {path}")


if __name__ == '__main__':
    main()
