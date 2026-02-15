#!/usr/bin/env python3
"""Steering Replay — backtest the full steering + signal system as a unit.

Replays each game day as if the system were live:
  1. Check model health (from model_performance_daily)
  2. Apply steering decision (champion vs challenger vs sit-out)
  3. Load graded predictions with supplemental data
  4. Override model health with historical value
  5. Run signal evaluation + BestBetsAggregator top-5 scoring
  6. Grade against actuals, track P&L

This tests the *complete* pipeline — signals, combos, health weighting —
unlike the existing replay engine which only sorts raw picks by edge.

Usage:
    # Full range
    PYTHONPATH=. python ml/analysis/steering_replay.py --start 2026-01-09 --end 2026-02-12

    # Single date debug
    PYTHONPATH=. python ml/analysis/steering_replay.py --start 2026-01-15 --end 2026-01-15 --verbose

    # Force a specific model (ignore steering)
    PYTHONPATH=. python ml/analysis/steering_replay.py --start 2026-01-09 --end 2026-02-12 --force-model catboost_v9

    # Re-enable health gate for A/B comparison
    PYTHONPATH=. python ml/analysis/steering_replay.py --start 2026-01-09 --end 2026-02-12 --with-health-gate

Created: 2026-02-15 (Session 269)
Updated: 2026-02-15 (Session 270) — health gate OFF by default
"""

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import bigquery

from ml.analysis.model_performance import BLOCK_THRESHOLD, WATCH_THRESHOLD
from ml.signals.aggregator import BestBetsAggregator
from ml.signals.combo_registry import load_combo_registry, match_combo
from ml.signals.registry import build_default_registry

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'

# Steering thresholds (matches model-steering-playbook.md)
CHALLENGER_MIN_HR = 56.0
CHALLENGER_MIN_N = 30

# P&L constants (-110 odds)
STAKE = 110
WIN_PAYOUT = 100

# Query template — adapted from signal_backfill.py with parameterized system_id
PREDICTION_QUERY = """
WITH preds AS (
  SELECT
    pa.player_lookup,
    pa.game_id,
    pa.game_date,
    pa.system_id,
    pa.team_abbr,
    pa.opponent_team_abbr,
    CAST(pa.predicted_points AS FLOAT64) AS predicted_points,
    CAST(pa.line_value AS FLOAT64) AS line_value,
    pa.recommendation,
    CAST(pa.predicted_points - pa.line_value AS FLOAT64) AS edge,
    CAST(pa.confidence_score AS FLOAT64) AS confidence_score,
    pa.actual_points,
    pa.prediction_correct
  FROM `{project}.nba_predictions.prediction_accuracy` pa
  WHERE pa.game_date = @target_date
    AND pa.system_id = @system_id
    AND pa.recommendation IN ('OVER', 'UNDER')
    AND pa.is_voided IS NOT TRUE
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY pa.player_lookup, pa.game_id ORDER BY pa.graded_at DESC
  ) = 1
),

game_stats AS (
  SELECT
    player_lookup,
    game_date,
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
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS minutes_avg_season
  FROM `{project}.nba_analytics.player_game_summary`
  WHERE game_date >= '2025-10-22'
    AND minutes_played > 0
),

latest_stats AS (
  SELECT gs.*
  FROM game_stats gs
  INNER JOIN preds p ON gs.player_lookup = p.player_lookup
  WHERE gs.game_date < @target_date
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY gs.player_lookup ORDER BY gs.game_date DESC
  ) = 1
),

streak_data AS (
  SELECT
    player_lookup,
    game_date,
    LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 1) OVER w AS prev_over_1,
    LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 2) OVER w AS prev_over_2,
    LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 3) OVER w AS prev_over_3,
    LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 4) OVER w AS prev_over_4,
    LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 5) OVER w AS prev_over_5
  FROM (
    SELECT *
    FROM `{project}.nba_predictions.prediction_accuracy`
    WHERE game_date >= '2025-10-22'
      AND system_id = @system_id
      AND prediction_correct IS NOT NULL
      AND is_voided IS NOT TRUE
      AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY player_lookup, game_id ORDER BY graded_at DESC
    ) = 1
  )
  WINDOW w AS (PARTITION BY player_lookup ORDER BY game_date)
),

latest_streak AS (
  SELECT sd.*
  FROM streak_data sd
  INNER JOIN preds p ON sd.player_lookup = p.player_lookup
  WHERE sd.game_date < @target_date
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY sd.player_lookup ORDER BY sd.game_date DESC
  ) = 1
)

SELECT
  p.*,
  ls.three_pct_last_3, ls.three_pct_season, ls.three_pct_std, ls.three_pa_per_game,
  ls.minutes_avg_last_3, ls.minutes_avg_season,
  ls.minutes_played AS prev_minutes,
  DATE_DIFF(@target_date, ls.game_date, DAY) AS rest_days,
  lsk.prev_over_1, lsk.prev_over_2, lsk.prev_over_3,
  lsk.prev_over_4, lsk.prev_over_5
FROM preds p
LEFT JOIN latest_stats ls ON ls.player_lookup = p.player_lookup
LEFT JOIN latest_streak lsk ON lsk.player_lookup = p.player_lookup
ORDER BY p.player_lookup
""".format(project=PROJECT_ID)


@dataclass
class DayResult:
    """Result for a single game day."""
    game_date: str
    model_id: Optional[str]
    state: str
    reason: str
    picks: int = 0
    wins: int = 0
    losses: int = 0
    daily_pnl: float = 0.0
    cumulative_pnl: float = 0.0
    pick_details: List[Dict] = field(default_factory=list)


# ── Data loading ─────────────────────────────────────────────────────────


def load_model_health_history(
    bq_client: bigquery.Client,
    start_date: str,
    end_date: str,
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Bulk-load historical model states from model_performance_daily.

    Returns:
        {date_str: {model_id: {state, rolling_hr_7d, rolling_n_7d}}}
    """
    query = """
    SELECT game_date, model_id, state, rolling_hr_7d, rolling_n_7d
    FROM `nba-props-platform.nba_predictions.model_performance_daily`
    WHERE game_date BETWEEN @start AND @end
    ORDER BY game_date, model_id
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter('start', 'DATE', start_date),
        bigquery.ScalarQueryParameter('end', 'DATE', end_date),
    ])
    rows = bq_client.query(query, job_config=job_config).result(timeout=60)

    result: Dict[str, Dict[str, Dict]] = {}
    for row in rows:
        d = str(row.game_date)
        if d not in result:
            result[d] = {}
        result[d][row.model_id] = {
            'state': row.state,
            'rolling_hr_7d': row.rolling_hr_7d,
            'rolling_n_7d': row.rolling_n_7d,
        }

    logger.info(f"Loaded model health for {len(result)} dates")
    return result


def load_signal_health_history(
    bq_client: bigquery.Client,
    start_date: str,
    end_date: str,
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Bulk-load signal health from signal_health_daily.

    Returns:
        {date_str: {signal_tag: {regime, hr_7d, is_model_dependent, ...}}}
    """
    query = """
    SELECT game_date, signal_tag, regime, hr_7d, hr_season, is_model_dependent
    FROM `nba-props-platform.nba_predictions.signal_health_daily`
    WHERE game_date BETWEEN @start AND @end
    ORDER BY game_date, signal_tag
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter('start', 'DATE', start_date),
        bigquery.ScalarQueryParameter('end', 'DATE', end_date),
    ])
    rows = bq_client.query(query, job_config=job_config).result(timeout=60)

    result: Dict[str, Dict[str, Dict]] = {}
    for row in rows:
        d = str(row.game_date)
        if d not in result:
            result[d] = {}
        result[d][row.signal_tag] = {
            'regime': row.regime,
            'hr_7d': row.hr_7d,
            'hr_season': row.hr_season,
            'is_model_dependent': row.is_model_dependent,
        }

    logger.info(f"Loaded signal health for {len(result)} dates")
    return result


def load_day_predictions(
    bq_client: bigquery.Client,
    target_date: str,
    system_id: str,
) -> List[Dict]:
    """Load graded predictions with supplemental data for a single date."""
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        bigquery.ScalarQueryParameter('system_id', 'STRING', system_id),
    ])
    rows = bq_client.query(PREDICTION_QUERY, job_config=job_config).result(timeout=120)
    return [dict(row) for row in rows]


# ── Steering logic ───────────────────────────────────────────────────────


def apply_steering(
    model_states: Dict[str, Dict[str, Any]],
    champion: str,
    challengers: List[str],
) -> Tuple[Optional[str], str, str]:
    """Apply steering decision based on pre-computed model states.

    Returns:
        (selected_model_id or None, state, reason)
    """
    champ_state = model_states.get(champion, {})
    state = champ_state.get('state', 'INSUFFICIENT_DATA')

    if state in ('HEALTHY', 'WATCH'):
        return champion, state, f'Champion {state}'

    if state == 'INSUFFICIENT_DATA':
        return champion, state, 'Insufficient data, using champion'

    # DEGRADING or BLOCKED — try challengers
    best_challenger = None
    best_hr = 0.0

    for cid in challengers:
        c_state = model_states.get(cid, {})
        c_hr = c_state.get('rolling_hr_7d') or 0.0
        c_n = c_state.get('rolling_n_7d') or 0
        if c_hr >= CHALLENGER_MIN_HR and c_n >= CHALLENGER_MIN_N and c_hr > best_hr:
            best_challenger = cid
            best_hr = c_hr

    if state == 'DEGRADING':
        if best_challenger:
            return best_challenger, state, f'Champion DEGRADING, switched to {best_challenger} ({best_hr:.1f}% HR)'
        return champion, state, 'Champion DEGRADING, no viable challenger — using champion'

    # BLOCKED
    if best_challenger:
        return best_challenger, state, f'Champion BLOCKED, switched to {best_challenger} ({best_hr:.1f}% HR)'
    return None, state, 'Champion BLOCKED, no viable challenger — sitting out'


# ── Signal evaluation (adapted from signal_backfill.evaluate_and_build) ──


def evaluate_day(
    rows: List[Dict],
    model_hr_7d: Optional[float],
    signal_health: Dict[str, Dict[str, Any]],
    registry,
    combo_reg: Dict,
    model_id: str,
    no_health_gate: bool = False,
) -> List[Dict]:
    """Run signal evaluation + aggregation for a single day.

    Returns top picks (up to 5) with actuals attached.
    """
    if not rows:
        return []

    # Override model health with historical value
    hr_7d = model_hr_7d

    # If health gate is disabled, pretend model is healthy
    effective_hr = 999.0 if no_health_gate else hr_7d

    predictions = []
    signal_results_map = {}

    for row in rows:
        pred = {
            'player_lookup': row['player_lookup'],
            'game_id': row['game_id'],
            'game_date': row['game_date'],
            'system_id': row.get('system_id', ''),
            'player_name': row.get('player_name', row.get('player_lookup', '')),
            'team_abbr': row.get('team_abbr', ''),
            'opponent_team_abbr': row.get('opponent_team_abbr', ''),
            'predicted_points': float(row['predicted_points'] or 0),
            'line_value': float(row['line_value'] or 0),
            'recommendation': row['recommendation'],
            'edge': float(row['edge'] or 0),
            'confidence_score': float(row['confidence_score'] or 0),
            'actual_points': row.get('actual_points'),
            'prediction_correct': row.get('prediction_correct'),
        }
        predictions.append(pred)

        # Build supplemental — use effective_hr so health gate override works
        supplemental = {'model_health': {'hit_rate_7d_edge3': effective_hr}}

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

        if row.get('prev_over_1') is not None:
            supplemental['streak_stats'] = {
                'prev_correct': [],
                'prev_over': [
                    row.get('prev_over_1'), row.get('prev_over_2'),
                    row.get('prev_over_3'), row.get('prev_over_4'),
                    row.get('prev_over_5'),
                ],
            }

        if row.get('prev_minutes') is not None and row.get('minutes_avg_season') is not None:
            supplemental['recovery_stats'] = {
                'prev_minutes': float(row['prev_minutes']),
                'minutes_avg_season': float(row['minutes_avg_season']),
            }

        if row.get('rest_days') is not None:
            supplemental['rest_stats'] = {'rest_days': int(row['rest_days'])}

        # Evaluate signals
        all_results = []
        for signal in registry.all():
            result = signal.evaluate(pred, features=None, supplemental=supplemental)
            all_results.append(result)

        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signal_results_map[key] = all_results

    # Aggregate with signal health weighting
    aggregator = BestBetsAggregator(
        combo_registry=combo_reg,
        signal_health=signal_health,
        model_id=model_id,
    )
    top_picks = aggregator.aggregate(predictions, signal_results_map)

    return top_picks


# ── Grading ──────────────────────────────────────────────────────────────


def grade_picks(picks: List[Dict]) -> Tuple[int, int, float]:
    """Grade picks against actuals.

    Returns:
        (wins, losses, pnl_dollars)
    """
    wins = 0
    losses = 0
    for pick in picks:
        if pick.get('prediction_correct') is True:
            wins += 1
        elif pick.get('prediction_correct') is False:
            losses += 1
        # Skip if prediction_correct is None (ungradable)

    pnl = (wins * WIN_PAYOUT) - (losses * STAKE)
    return wins, losses, round(pnl, 2)


# ── Main replay loop ─────────────────────────────────────────────────────


def run_replay(
    bq_client: bigquery.Client,
    start_date: str,
    end_date: str,
    champion: str,
    challengers: List[str],
    force_model: Optional[str] = None,
    no_health_gate: bool = False,
    verbose: bool = False,
) -> List[DayResult]:
    """Run full steering replay over a date range.

    Returns list of DayResult, one per game day.
    """
    # 1. Bulk-load historical data
    model_health = load_model_health_history(bq_client, start_date, end_date)
    signal_health = load_signal_health_history(bq_client, start_date, end_date)
    registry = build_default_registry()
    combo_reg = load_combo_registry(bq_client=bq_client)

    # 2. Get game dates with graded predictions
    all_models = [champion] + challengers
    model_ids_str = ', '.join(f"'{m}'" for m in all_models)
    dates_q = f"""
    SELECT DISTINCT game_date
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date BETWEEN @start AND @end
      AND system_id IN ({model_ids_str})
      AND prediction_correct IS NOT NULL
    ORDER BY game_date
    """
    dates_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter('start', 'DATE', start_date),
        bigquery.ScalarQueryParameter('end', 'DATE', end_date),
    ])
    game_dates = [str(row.game_date) for row in
                  bq_client.query(dates_q, job_config=dates_config).result()]

    if not game_dates:
        logger.warning(f"No graded predictions found between {start_date} and {end_date}")
        return []

    logger.info(f"Replaying {len(game_dates)} game days: {game_dates[0]} to {game_dates[-1]}")

    # 3. Iterate
    results: List[DayResult] = []
    cumulative_pnl = 0.0

    for i, date_str in enumerate(game_dates):
        day_model_states = model_health.get(date_str, {})
        day_signal_health = signal_health.get(date_str, {})

        # Steering decision
        if force_model:
            selected_model = force_model
            state = day_model_states.get(force_model, {}).get('state', 'FORCED')
            reason = f'Forced: {force_model}'
        else:
            selected_model, state, reason = apply_steering(
                day_model_states, champion, challengers)

        # Sit out if no model selected (and health gate not bypassed)
        if selected_model is None and not no_health_gate:
            day_result = DayResult(
                game_date=date_str,
                model_id=None,
                state=state,
                reason=reason,
                cumulative_pnl=cumulative_pnl,
            )
            results.append(day_result)
            if verbose:
                logger.info(f"[{i+1}/{len(game_dates)}] {date_str}: SIT OUT — {reason}")
            continue

        # If health gate bypassed but model was None, use champion
        effective_model = selected_model or champion

        # Get model's HR for health override
        model_hr_7d = day_model_states.get(effective_model, {}).get('rolling_hr_7d')

        # Load predictions for this model + date
        rows = load_day_predictions(bq_client, date_str, effective_model)

        if not rows:
            day_result = DayResult(
                game_date=date_str,
                model_id=effective_model,
                state=state,
                reason=f'{reason} (0 predictions)',
                cumulative_pnl=cumulative_pnl,
            )
            results.append(day_result)
            if verbose:
                logger.info(f"[{i+1}/{len(game_dates)}] {date_str}: {effective_model} — 0 predictions")
            continue

        # Evaluate signals + aggregate top picks
        top_picks = evaluate_day(
            rows, model_hr_7d, day_signal_health, registry, combo_reg,
            model_id=effective_model, no_health_gate=no_health_gate,
        )

        # Grade
        wins, losses, day_pnl = grade_picks(top_picks)
        cumulative_pnl += day_pnl

        day_result = DayResult(
            game_date=date_str,
            model_id=effective_model,
            state=state,
            reason=reason,
            picks=len(top_picks),
            wins=wins,
            losses=losses,
            daily_pnl=day_pnl,
            cumulative_pnl=round(cumulative_pnl, 2),
        )

        if verbose:
            day_result.pick_details = [
                {
                    'player': p.get('player_lookup', ''),
                    'team': p.get('team_abbr', ''),
                    'rec': p.get('recommendation', ''),
                    'edge': round(p.get('edge', 0), 1),
                    'signals': p.get('signal_tags', []),
                    'score': p.get('composite_score', 0),
                    'actual': p.get('actual_points'),
                    'correct': p.get('prediction_correct'),
                }
                for p in top_picks
            ]

        results.append(day_result)

        if verbose:
            hr = round(100.0 * wins / len(top_picks), 1) if top_picks else 0.0
            logger.info(
                f"[{i+1}/{len(game_dates)}] {date_str}: {effective_model} "
                f"{state} | {len(top_picks)} picks, {wins}W/{losses}L "
                f"({hr}%) | ${day_pnl:+.0f} | Cum: ${cumulative_pnl:+,.0f}"
            )

    return results


# ── Output formatting ────────────────────────────────────────────────────


def print_daily_table(results: List[DayResult], verbose: bool = False) -> None:
    """Print daily results table."""
    header = (
        f"{'Date':<12} {'Model':<22} {'State':<12} "
        f"{'Picks':>5} {'W/L':>7} {'HR%':>7} "
        f"{'Day P&L':>10} {'Cum P&L':>10}"
    )
    print(header)
    print('-' * len(header))

    for r in results:
        if r.model_id is None:
            model_str = '-- SIT OUT --'
            wl = '-'
            hr = '-'
            day_pnl_str = '$0'
        else:
            model_str = r.model_id[:22]
            if r.picks > 0:
                wl = f'{r.wins}/{r.losses}'
                hr = f'{100.0 * r.wins / r.picks:.1f}%'
            else:
                wl = '-'
                hr = '-'
            day_pnl_str = f'${r.daily_pnl:+,.0f}'

        cum_pnl_str = f'${r.cumulative_pnl:+,.0f}'

        print(
            f"{r.game_date:<12} {model_str:<22} {r.state:<12} "
            f"{r.picks:>5} {wl:>7} {hr:>7} "
            f"{day_pnl_str:>10} {cum_pnl_str:>10}"
        )

        if verbose and r.pick_details:
            for p in r.pick_details:
                correct_str = 'W' if p['correct'] else 'L' if p['correct'] is False else '?'
                signals_str = ', '.join(p['signals'][:3])
                if len(p['signals']) > 3:
                    signals_str += f' +{len(p["signals"]) - 3}'
                print(
                    f"  {correct_str} {p['player'][:25]:<25} {p['team']:>3} "
                    f"{p['rec']:>5} edge={p['edge']:>5.1f} "
                    f"actual={p['actual'] or '?':>5} [{signals_str}]"
                )


def print_summary(results: List[DayResult], champion: str,
                   challengers: List[str]) -> None:
    """Print aggregate summary."""
    game_days = len(results)
    played = sum(1 for r in results if r.picks > 0)
    sat_out = sum(1 for r in results if r.model_id is None)
    total_picks = sum(r.picks for r in results)
    total_wins = sum(r.wins for r in results)
    total_losses = sum(r.losses for r in results)
    final_pnl = results[-1].cumulative_pnl if results else 0

    hr = round(100.0 * total_wins / total_picks, 1) if total_picks > 0 else 0.0
    roi = round(100.0 * final_pnl / (total_picks * STAKE), 1) if total_picks > 0 else 0.0

    # Count model switches
    switches = 0
    prev_model = None
    models_used = set()
    for r in results:
        if r.model_id is not None:
            models_used.add(r.model_id)
            if prev_model is not None and r.model_id != prev_model:
                switches += 1
            prev_model = r.model_id

    # State distribution
    state_counts: Dict[str, int] = {}
    for r in results:
        state_counts[r.state] = state_counts.get(r.state, 0) + 1

    print(f"\n{'=' * 60}")
    print(f"SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Game Days:     {game_days} | Played: {played} | Sat Out: {sat_out}")
    print(f"  Picks:         {total_picks} | W-L: {total_wins}-{total_losses} | HR: {hr}%")
    print(f"  P&L:           ${final_pnl:+,.0f} | ROI: {roi:+.1f}%")
    print(f"  Model Switches: {switches}")
    print(f"  Models Used:   {', '.join(sorted(models_used)) or 'none'}")

    if state_counts:
        print(f"\n  State Distribution:")
        for state, count in sorted(state_counts.items()):
            print(f"    {state:<20} {count:>3} days")

    # Streak analysis
    if results:
        best_streak = 0
        worst_streak = 0
        current_w = 0
        current_l = 0
        for r in results:
            if r.picks == 0:
                continue
            if r.wins > r.losses:
                current_w += 1
                current_l = 0
                best_streak = max(best_streak, current_w)
            elif r.losses > r.wins:
                current_l += 1
                current_w = 0
                worst_streak = max(worst_streak, current_l)
            else:
                current_w = 0
                current_l = 0

        print(f"\n  Best Winning Streak:  {best_streak} days")
        print(f"  Worst Losing Streak:  {worst_streak} days")


# ── CLI ──────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description='Steering Replay — backtest the full steering + signal system')
    parser.add_argument('--start', default='2026-01-09',
                        help='Start date inclusive (default: 2026-01-09)')
    parser.add_argument('--end', default='2026-02-12',
                        help='End date inclusive (default: 2026-02-12)')
    parser.add_argument('--champion', default='catboost_v9',
                        help='Champion model ID (default: catboost_v9)')
    parser.add_argument('--challengers', default='catboost_v12',
                        help='Comma-separated challenger model IDs')
    parser.add_argument('--force-model',
                        help='Force a specific model, ignoring steering')
    parser.add_argument('--no-health-gate', action='store_true', default=True,
                        help='(Default) Bypass health gate — picks on all days')
    parser.add_argument('--with-health-gate', action='store_true',
                        help='Re-enable health gate for A/B comparison')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show individual pick details per day')
    args = parser.parse_args()

    challengers = [c.strip() for c in args.challengers.split(',') if c.strip()]

    # Health gate is OFF by default (Session 270); --with-health-gate re-enables
    no_health_gate = not args.with_health_gate

    bq_client = bigquery.Client(project=PROJECT_ID)

    # Header
    print(f"=== Steering Replay: {args.start} to {args.end} ===")
    print(f"Champion: {args.champion} | Challengers: {', '.join(challengers)}")
    if args.force_model:
        print(f"FORCED MODEL: {args.force_model}")
    if args.with_health_gate:
        print("HEALTH GATE ENABLED (for comparison)")
    else:
        print("HEALTH GATE OFF (default since Session 270)")
    print()

    results = run_replay(
        bq_client,
        start_date=args.start,
        end_date=args.end,
        champion=args.champion,
        challengers=challengers,
        force_model=args.force_model,
        no_health_gate=no_health_gate,
        verbose=args.verbose,
    )

    if not results:
        print("No results — check date range and model IDs.")
        sys.exit(1)

    print_daily_table(results, verbose=args.verbose)
    print_summary(results, args.champion, challengers)


if __name__ == '__main__':
    main()
