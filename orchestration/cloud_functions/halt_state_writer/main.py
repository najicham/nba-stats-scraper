"""halt_state_writer — single source of truth for "is the system halted today?".

Runs daily early in the morning ET (well before any Phase 6 export). For each
sport, determines whether picks should be produced today and writes one row to
`nba_orchestration.halt_state`. Every Phase 6 exporter reads from this row via
`BaseExporter.halt_envelope()`.

Replaces the ad-hoc halt detection that previously lived in:
  - regime_context.compute_regime() (computed but only consumed inside aggregator)
  - signal_best_bets_exporter (read regime_context, wrote halt JSON)
  - post_grading_export (gated history exports on graded_count, conflating halt
    with "no grading happened today" — caused best-bets/all.json to freeze
    21 days during NBA halt)
  - aggregator.py (had its own edge floor literal)

Halt reasons (canonical strings stored in halt_state.halt_reason):

    'off_season'    — outside the sport's regular-season + playoffs window
    'edge_collapse' — Session 515 edge-based auto-halt
    'fleet_blocked' — all enabled models in BLOCKED state per decay_detection
    'tight_market'  — vegas_mae_7d < 4.5 and operator-elevated
    'manual'        — operator-set via halt_overrides table

Published metrics (halt_metrics JSON column) are diagnostic only — readers
should treat unknown keys gracefully.

Triggered by Cloud Scheduler `halt-state-writer-daily` at 5 AM ET.

Created: 2026-05-09 (pipeline-state-redesign Phase B).
"""

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import functions_framework
from flask import Request
from google.cloud import bigquery


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
SLACK_WEBHOOK_URL_ALERTS = os.environ.get('SLACK_WEBHOOK_URL_ALERTS', '')

# Sport season windows. Anything outside these windows defaults to off_season.
# Windows are intentionally generous (preseason + playoffs included) — the
# schedule presence check inside the window is the precise signal.
SEASON_WINDOWS = {
    'nba': {'start_month': 10, 'start_day': 1, 'end_month': 6, 'end_day': 30},
    'mlb': {'start_month': 3, 'start_day': 1, 'end_month': 11, 'end_day': 15},
}

# Schedule tables for the schedule-presence check. We look ±21 days; if no
# games are present in that window, the sport is in off_season regardless of
# the calendar window above (covers e.g. lockouts, early playoffs end).
SCHEDULE_LOOKUP = {
    'nba': {
        'table': f'{PROJECT_ID}.nba_reference.nba_schedule',
        'date_col': 'game_date',
    },
    'mlb': {
        'table': f'{PROJECT_ID}.mlb_raw.mlb_schedule',
        'date_col': 'game_date',
    },
}

HALT_STATE_TABLE = f'{PROJECT_ID}.nba_orchestration.halt_state'

# Lazy BQ client
_bq_client = None


def _get_bq_client() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        try:
            from shared.clients.bigquery_pool import get_bigquery_client
            _bq_client = get_bigquery_client(project_id=PROJECT_ID)
        except Exception:
            _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


# --------------------------------------------------------------------------- #
# Halt evaluators
# --------------------------------------------------------------------------- #


def _is_in_season_window(today: date, sport: str) -> bool:
    """Calendar-window check. Loose — schedule-presence is the precise signal."""
    window = SEASON_WINDOWS[sport]
    start_md = (window['start_month'], window['start_day'])
    end_md = (window['end_month'], window['end_day'])
    today_md = (today.month, today.day)

    if start_md <= end_md:
        return start_md <= today_md <= end_md
    # Wraparound (NBA: Oct - Jun)
    return today_md >= start_md or today_md <= end_md


def _has_recent_games(bq: bigquery.Client, today: date, sport: str) -> Tuple[bool, int]:
    """Are there scheduled games within ±21 days? Returns (has_games, num_today)."""
    lookup = SCHEDULE_LOOKUP[sport]
    query = f"""
        SELECT
          COUNTIF({lookup['date_col']} = @today) AS games_today,
          COUNT(*) AS games_window
        FROM `{lookup['table']}`
        WHERE {lookup['date_col']} BETWEEN @start AND @end
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('today', 'DATE', today),
            bigquery.ScalarQueryParameter('start', 'DATE', today - timedelta(days=21)),
            bigquery.ScalarQueryParameter('end', 'DATE', today + timedelta(days=21)),
        ]
    )
    try:
        rows = list(bq.query(query, job_config=job_config).result(timeout=60))
        if not rows:
            return False, 0
        games_window = int(rows[0].games_window or 0)
        games_today = int(rows[0].games_today or 0)
        return games_window > 0, games_today
    except Exception as e:
        # If the schedule table isn't reachable, assume in-season to fail safe
        # (don't accidentally publish off_season during a transient BQ error).
        logger.warning(f"Schedule lookup failed for {sport}: {e}; assuming in-season.")
        return True, 0


def _nba_edge_collapse(bq: bigquery.Client, today: date) -> Optional[Dict[str, Any]]:
    """Mirrors the Session 515 edge-based auto-halt logic from regime_context.

    Inlined here so this CF doesn't import the full ml/signals stack.
    Returns dict with halt context if collapse detected, else None.
    """
    query = f"""
        WITH daily_edges AS (
          SELECT
            game_date,
            AVG(ABS(predicted_points - current_points_line)) AS avg_edge,
            COUNTIF(ABS(predicted_points - current_points_line) >= 5.0) AS edge_5plus,
            COUNT(*) AS total
          FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
          WHERE game_date >= DATE_SUB(@today, INTERVAL 7 DAY)
            AND game_date < @today
          GROUP BY game_date
        )
        SELECT
          ROUND(AVG(avg_edge), 2) AS rolling_7d_avg_edge,
          ROUND(100.0 * SUM(edge_5plus) / NULLIF(SUM(total), 0), 1) AS rolling_7d_pct_edge_5plus,
          COUNT(*) AS days_sampled
        FROM daily_edges
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter('today', 'DATE', today)]
    )
    try:
        rows = list(bq.query(query, job_config=job_config).result(timeout=60))
    except Exception as e:
        logger.warning(f"Edge collapse query failed: {e}")
        return None

    if not rows or rows[0].rolling_7d_avg_edge is None:
        return None

    row = rows[0]
    avg_edge = float(row.rolling_7d_avg_edge)
    pct_5plus = float(row.rolling_7d_pct_edge_5plus or 0.0)
    days_sampled = int(row.days_sampled)

    metrics = {
        'rolling_7d_avg_edge': avg_edge,
        'rolling_7d_pct_edge_5plus': pct_5plus,
        'edge_halt_days_sampled': days_sampled,
    }

    if avg_edge < 5.0 and pct_5plus < 50.0 and days_sampled >= 3:
        metrics['halt_threshold'] = 'avg_edge<5.0 AND pct_5plus<50.0 AND days>=3'
        return metrics
    return None


def _predictions_inactive(bq: bigquery.Client, sport: str, today: date) -> Optional[Dict[str, Any]]:
    """Have NBA predictions been silent for 3+ days while games are scheduled?

    Catches halts that don't fall into the off_season / edge_collapse /
    fleet_blocked buckets — e.g. operator-paused schedulers, prediction
    worker crashes, or the late-season dormancy that left the system
    silent for ~6 weeks of 2026-04 → 2026-05-09.

    Returns a dict if predictions are inactive while games are scheduled.
    """
    if sport != 'nba':
        return None  # MLB has its own prediction pipeline; not modeled here.

    query = f"""
        WITH recent_preds AS (
          SELECT COUNT(*) AS n_preds
          FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
          WHERE game_date BETWEEN DATE_SUB(@today, INTERVAL 3 DAY) AND @today
        ),
        upcoming_games AS (
          SELECT COUNT(*) AS n_games
          FROM `{PROJECT_ID}.nba_reference.nba_schedule`
          WHERE game_date BETWEEN @today AND DATE_ADD(@today, INTERVAL 7 DAY)
        )
        SELECT
          (SELECT n_preds FROM recent_preds) AS recent_preds,
          (SELECT n_games FROM upcoming_games) AS upcoming_games
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter('today', 'DATE', today)]
    )
    try:
        rows = list(bq.query(query, job_config=job_config).result(timeout=30))
    except Exception as e:
        logger.warning(f"Predictions-inactive query failed: {e}")
        return None

    if not rows:
        return None
    row = rows[0]
    recent_preds = int(row.recent_preds or 0)
    upcoming_games = int(row.upcoming_games or 0)

    if recent_preds == 0 and upcoming_games > 0:
        return {
            'recent_preds_3d': recent_preds,
            'upcoming_games_7d': upcoming_games,
        }
    return None


def _fleet_blocked(bq: bigquery.Client, sport: str, today: date) -> Optional[Dict[str, Any]]:
    """Are all enabled NBA models in BLOCKED state?

    Uses model_performance_daily as written by decay_detection. Returns dict
    with halt context if all-blocked, else None.
    """
    if sport != 'nba':
        return None  # MLB fleet blocking semantics differ; not modeled yet.

    query = f"""
        WITH latest AS (
          SELECT model_id, state, rolling_hr_7d, rolling_n_7d
          FROM `{PROJECT_ID}.nba_predictions.model_performance_daily` p
          WHERE game_date = (
            SELECT MAX(game_date) FROM `{PROJECT_ID}.nba_predictions.model_performance_daily`
            WHERE game_date <= @today
          )
        )
        SELECT
          COUNT(*) AS n_total,
          COUNTIF(state = 'BLOCKED') AS n_blocked,
          ARRAY_AGG(model_id ORDER BY model_id) AS model_ids,
          ARRAY_AGG(state ORDER BY model_id) AS states
        FROM latest
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter('today', 'DATE', today)]
    )
    try:
        rows = list(bq.query(query, job_config=job_config).result(timeout=60))
    except Exception as e:
        logger.warning(f"Fleet block query failed: {e}")
        return None

    if not rows or rows[0].n_total == 0:
        return None

    row = rows[0]
    if row.n_total > 0 and row.n_blocked == row.n_total:
        return {
            'fleet_total': int(row.n_total),
            'fleet_blocked': int(row.n_blocked),
            'model_ids': list(row.model_ids),
            'states': list(row.states),
        }
    return None


# --------------------------------------------------------------------------- #
# Compose the halt decision
# --------------------------------------------------------------------------- #


def evaluate_halt_state(
    bq: bigquery.Client,
    today: date,
    sport: str,
) -> Dict[str, Any]:
    """Pure function: given (today, sport), return the canonical halt-state row."""

    # Defaults
    halt_active = False
    halt_reason: Optional[str] = None
    halt_metrics: Dict[str, Any] = {}

    # 1. Schedule-presence check — strongest signal for off_season.
    has_games, games_today = _has_recent_games(bq, today, sport)
    in_window = _is_in_season_window(today, sport)
    halt_metrics['games_today'] = games_today
    halt_metrics['has_games_in_21d_window'] = has_games
    halt_metrics['in_season_window'] = in_window

    if not has_games or not in_window:
        halt_active = True
        halt_reason = 'off_season'

    # 2. Edge collapse (NBA only) — only consult when not already off_season.
    if not halt_active and sport == 'nba':
        edge_metrics = _nba_edge_collapse(bq, today)
        if edge_metrics is not None:
            halt_active = True
            halt_reason = 'edge_collapse'
            halt_metrics.update(edge_metrics)

    # 3. Fleet blocked (NBA only).
    if not halt_active and sport == 'nba':
        fleet_metrics = _fleet_blocked(bq, sport, today)
        if fleet_metrics is not None:
            halt_active = True
            halt_reason = 'fleet_blocked'
            halt_metrics.update(fleet_metrics)

    # 4. Predictions inactive (NBA only) — catches operator-paused / late-season
    #    dormancy where edge_collapse and fleet_blocked checks need recent data
    #    they don't have. Last-resort signal: games scheduled but no predictions.
    if not halt_active and sport == 'nba':
        pred_metrics = _predictions_inactive(bq, sport, today)
        if pred_metrics is not None:
            halt_active = True
            halt_reason = 'predictions_inactive'
            halt_metrics.update(pred_metrics)

    return {
        'halt_active': halt_active,
        'halt_reason': halt_reason,
        'halt_metrics': halt_metrics,
    }


def _last_halt_state(bq: bigquery.Client, sport: str, today: date) -> Optional[Dict[str, Any]]:
    """Most recent halt_state row for this sport before today (for halt_since
    continuity and state-change detection)."""
    query = f"""
        SELECT effective_date, halt_active, halt_reason, halt_since
        FROM `{HALT_STATE_TABLE}`
        WHERE sport = @sport AND effective_date < @today
        ORDER BY effective_date DESC
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('sport', 'STRING', sport),
            bigquery.ScalarQueryParameter('today', 'DATE', today),
        ]
    )
    try:
        rows = list(bq.query(query, job_config=job_config).result(timeout=30))
    except Exception as e:
        logger.warning(f"Last halt_state lookup failed for {sport}: {e}")
        return None
    if not rows:
        return None
    r = rows[0]
    return {
        'effective_date': r.effective_date,
        'halt_active': bool(r.halt_active),
        'halt_reason': r.halt_reason,
        'halt_since': r.halt_since,
    }


def _resolve_halt_since(
    today: date,
    decision: Dict[str, Any],
    last: Optional[Dict[str, Any]],
) -> Optional[date]:
    """When did the current halt begin?

    - Not halted today → None.
    - Halted today, last was NOT halted (or no last) → today.
    - Halted today, last halted → preserve last.halt_since.
    """
    if not decision['halt_active']:
        return None
    if last is None or not last['halt_active'] or last['halt_since'] is None:
        return today
    return last['halt_since']


# --------------------------------------------------------------------------- #
# Persistence — replace today's row idempotently
# --------------------------------------------------------------------------- #


def write_halt_state(
    bq: bigquery.Client,
    effective_date: date,
    sport: str,
    decision: Dict[str, Any],
    halt_since: Optional[date],
    actor: Optional[str] = None,
) -> None:
    """MERGE one row into halt_state. Idempotent — re-runs replace today's row."""
    merge_sql = f"""
        MERGE `{HALT_STATE_TABLE}` T
        USING (
          SELECT
            @effective_date AS effective_date,
            @sport AS sport,
            @halt_active AS halt_active,
            @halt_reason AS halt_reason,
            @halt_since AS halt_since,
            PARSE_JSON(@halt_metrics) AS halt_metrics,
            @source AS source,
            CURRENT_TIMESTAMP() AS written_at,
            @actor AS actor
        ) S
        ON T.effective_date = S.effective_date AND T.sport = S.sport
        WHEN MATCHED THEN UPDATE SET
          halt_active = S.halt_active,
          halt_reason = S.halt_reason,
          halt_since = S.halt_since,
          halt_metrics = S.halt_metrics,
          source = S.source,
          written_at = S.written_at,
          actor = S.actor
        WHEN NOT MATCHED THEN INSERT (
          effective_date, sport, halt_active, halt_reason, halt_since,
          halt_metrics, source, written_at, actor
        ) VALUES (
          S.effective_date, S.sport, S.halt_active, S.halt_reason, S.halt_since,
          S.halt_metrics, S.source, S.written_at, S.actor
        )
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('effective_date', 'DATE', effective_date),
            bigquery.ScalarQueryParameter('sport', 'STRING', sport),
            bigquery.ScalarQueryParameter('halt_active', 'BOOL', decision['halt_active']),
            bigquery.ScalarQueryParameter('halt_reason', 'STRING', decision['halt_reason']),
            bigquery.ScalarQueryParameter('halt_since', 'DATE', halt_since),
            bigquery.ScalarQueryParameter(
                'halt_metrics', 'STRING', json.dumps(decision['halt_metrics'], default=str)
            ),
            bigquery.ScalarQueryParameter('source', 'STRING', 'halt_state_writer_cf'),
            bigquery.ScalarQueryParameter('actor', 'STRING', actor),
        ]
    )
    bq.query(merge_sql, job_config=job_config).result()


# --------------------------------------------------------------------------- #
# Slack alert on state change (nice-to-have; failures are non-fatal)
# --------------------------------------------------------------------------- #


def _post_slack(message: str) -> None:
    if not SLACK_WEBHOOK_URL_ALERTS:
        return
    try:
        import requests
        requests.post(SLACK_WEBHOOK_URL_ALERTS, json={'text': message}, timeout=5)
    except Exception as e:
        logger.warning(f"Slack post failed (non-fatal): {e}")


def maybe_alert_on_change(
    sport: str,
    today: date,
    decision: Dict[str, Any],
    last: Optional[Dict[str, Any]],
) -> None:
    if last is None:
        return  # First write for this sport — don't spam.
    if last['halt_active'] == decision['halt_active'] and last['halt_reason'] == decision['halt_reason']:
        return
    direction = 'HALTED' if decision['halt_active'] else 'RESUMED'
    reason = decision['halt_reason'] or '(none)'
    last_reason = last['halt_reason'] or '(none)'
    message = (
        f":rotating_light: *{sport.upper()} {direction}* on {today.isoformat()}\n"
        f"From: halt_active={last['halt_active']} reason={last_reason}\n"
        f"To:   halt_active={decision['halt_active']} reason={reason}"
    )
    _post_slack(message)


# --------------------------------------------------------------------------- #
# HTTP entry point
# --------------------------------------------------------------------------- #


@functions_framework.http
def halt_state_writer(request: Request):
    """HTTP entry point — Cloud Scheduler-triggered.

    Optional query params:
      - target_date: ISO date (default: today)
      - sport: one of ['nba', 'mlb', 'all']  (default: 'all')
      - actor: free-form string for audit

    Returns 200 with summary JSON on success, 500 on unrecoverable error.
    """
    target_date_str = request.args.get('target_date') if request.args else None
    sport_arg = (request.args.get('sport') if request.args else None) or 'all'
    actor = (request.args.get('actor') if request.args else None) or None

    today = (
        date.fromisoformat(target_date_str) if target_date_str else date.today()
    )
    sports = ['nba', 'mlb'] if sport_arg == 'all' else [sport_arg]

    bq = _get_bq_client()
    summary: Dict[str, Any] = {'effective_date': today.isoformat(), 'results': {}}

    for sport in sports:
        try:
            decision = evaluate_halt_state(bq, today, sport)
            last = _last_halt_state(bq, sport, today)
            halt_since = _resolve_halt_since(today, decision, last)
            write_halt_state(bq, today, sport, decision, halt_since, actor=actor)
            maybe_alert_on_change(sport, today, decision, last)
            summary['results'][sport] = {
                'halt_active': decision['halt_active'],
                'halt_reason': decision['halt_reason'],
                'halt_since': halt_since.isoformat() if halt_since else None,
                'metrics': decision['halt_metrics'],
            }
            logger.info(
                f"halt_state[{sport}] effective={today} "
                f"halt_active={decision['halt_active']} reason={decision['halt_reason']}"
            )
        except Exception as e:
            logger.error(f"halt_state_writer failed for {sport}: {e}", exc_info=True)
            summary['results'][sport] = {'error': str(e)}

    summary['written_at'] = datetime.now(timezone.utc).isoformat()
    return summary, 200


# Gen2 entrypoint alias (CLAUDE.md note: Gen2 entry point is immutable)
main = halt_state_writer
