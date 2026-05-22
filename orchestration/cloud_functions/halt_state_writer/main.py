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

    'off_season'           — outside the sport's regular-season + playoffs window
    'between_rounds'       — in-window but no future games in next 14d
    'edge_collapse'        — Session 515 edge-based auto-halt (NBA only)
    'fleet_blocked'        — all enabled models in BLOCKED state per decay_detection
    'predictions_inactive' — predictions silent 3+ days while games scheduled
    'pick_drought'         — MLB: predictions flowing but 2+ days of zero picks
                             (filter squeeze / floor-cap collision class)
    'tight_market'         — vegas_mae_7d < 4.5 and operator-elevated
    'manual'               — operator-set via halt_overrides table

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

# Per-sport predictions tables — used by _predictions_inactive and (MLB) _pick_drought.
PREDICTIONS_LOOKUP = {
    'nba': {
        'table': f'{PROJECT_ID}.nba_predictions.player_prop_predictions',
        'date_col': 'game_date',
    },
    'mlb': {
        'table': f'{PROJECT_ID}.mlb_predictions.pitcher_strikeouts',
        'date_col': 'game_date',
    },
}

# Per-sport model_performance_daily — schemas drift between sports.
# NBA writes `state`/`rolling_hr_7d`/`rolling_n_7d`; MLB writes `decay_state`/`hr_7d`/`n_7d`.
MODEL_PERF_LOOKUP = {
    'nba': {
        'table': f'{PROJECT_ID}.nba_predictions.model_performance_daily',
        'state_col': 'state',
        'hr_col': 'rolling_hr_7d',
        'n_col': 'rolling_n_7d',
    },
    'mlb': {
        'table': f'{PROJECT_ID}.mlb_predictions.model_performance_daily',
        'state_col': 'decay_state',
        'hr_col': 'hr_7d',
        'n_col': 'n_7d',
    },
}

# Per-sport model_registry — used by _fleet_blocked transition grace check.
MODEL_REGISTRY_LOOKUP = {
    'nba': f'{PROJECT_ID}.nba_predictions.model_registry',
    'mlb': f'{PROJECT_ID}.mlb_predictions.model_registry',
}

# Days after model registration during which fleet_blocked is suspended if the
# model lacks model_performance_daily rows. Tuned to grading lag: a model
# registered Monday gets its first MPD row Tuesday morning at earliest; 5 days
# gives a week of slack before fleet_blocked re-engages if MPD is still empty.
FLEET_TRANSITION_GRACE_DAYS = 5

# Per-sport best-bets picks table — used by MLB _pick_drought.
PICKS_LOOKUP = {
    'mlb': {
        'table': f'{PROJECT_ID}.mlb_predictions.signal_best_bets_picks',
        'date_col': 'game_date',
    },
}

HALT_STATE_TABLE = f'{PROJECT_ID}.nba_orchestration.halt_state'
HALT_OVERRIDES_TABLE = f'{PROJECT_ID}.nba_orchestration.halt_overrides'

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


def _has_recent_games(bq: bigquery.Client, today: date, sport: str) -> Tuple[bool, int, bool]:
    """Schedule presence diagnostics. Returns (has_games_in_window, games_today, has_future_games_14d).

    has_games_in_window: any games scheduled in ±21 days. Distinguishes
        true off-season (no games in window) from "between rounds" / dormant.
    games_today: count of games on `today`.
    has_future_games_14d: any games scheduled today through today+14d. When
        this is False but has_games_in_window is True, the sport is in
        a between-rounds dormancy (e.g. NBA between playoff rounds in May).
    """
    lookup = SCHEDULE_LOOKUP[sport]
    query = f"""
        SELECT
          COUNTIF({lookup['date_col']} = @today) AS games_today,
          COUNT(*) AS games_window,
          COUNTIF({lookup['date_col']} BETWEEN @today AND @end_14d) AS games_future_14d
        FROM `{lookup['table']}`
        WHERE {lookup['date_col']} BETWEEN @start AND @end
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('today', 'DATE', today),
            bigquery.ScalarQueryParameter('start', 'DATE', today - timedelta(days=21)),
            bigquery.ScalarQueryParameter('end', 'DATE', today + timedelta(days=21)),
            bigquery.ScalarQueryParameter('end_14d', 'DATE', today + timedelta(days=14)),
        ]
    )
    try:
        rows = list(bq.query(query, job_config=job_config).result(timeout=60))
        if not rows:
            return False, 0, False
        games_window = int(rows[0].games_window or 0)
        games_today = int(rows[0].games_today or 0)
        games_future_14d = int(rows[0].games_future_14d or 0)
        return games_window > 0, games_today, games_future_14d > 0
    except Exception as e:
        # If the schedule table isn't reachable, assume in-season to fail safe.
        logger.warning(f"Schedule lookup failed for {sport}: {e}; assuming in-season.")
        return True, 0, True


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
    """Have predictions been silent for 3+ days while games are scheduled?

    Catches halts that don't fall into the off_season / edge_collapse /
    fleet_blocked buckets — e.g. operator-paused schedulers, prediction
    worker crashes, or the late-season dormancy that left the system
    silent for ~6 weeks of 2026-04 → 2026-05-09.

    Returns a dict if predictions are inactive while games are scheduled.
    """
    pred_cfg = PREDICTIONS_LOOKUP.get(sport)
    sched_cfg = SCHEDULE_LOOKUP.get(sport)
    if pred_cfg is None or sched_cfg is None:
        return None

    query = f"""
        WITH recent_preds AS (
          SELECT COUNT(*) AS n_preds
          FROM `{pred_cfg['table']}`
          WHERE {pred_cfg['date_col']} BETWEEN DATE_SUB(@today, INTERVAL 3 DAY) AND @today
        ),
        upcoming_games AS (
          SELECT COUNT(*) AS n_games
          FROM `{sched_cfg['table']}`
          WHERE {sched_cfg['date_col']} BETWEEN @today AND DATE_ADD(@today, INTERVAL 7 DAY)
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
        logger.warning(f"Predictions-inactive query failed for {sport}: {e}")
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


def _fleet_in_transition(
    bq: bigquery.Client, sport: str, today: date
) -> Optional[Dict[str, Any]]:
    """Is the production fleet mid-swap?

    Returns context dict (non-None) when EVERY production-enabled model in the
    registry is "fresh" (registered within FLEET_TRANSITION_GRACE_DAYS) AND has
    no model_performance_daily rows yet. In that state, `_fleet_blocked` has
    only stale data from older models to read from, so its BLOCKED result is a
    false positive — we suspend it.

    Why ALL must be fresh (not ANY): for a multi-model fleet (NBA), one
    week's retrain producing one fresh model doesn't invalidate the BLOCKED
    state inferred from the other 6. Suspending only fires when the entire
    fleet is in transition (single-model retrain or a coordinated NBA swap).

    Returns None on any query failure (fail-open — don't suppress halts when
    the transition check itself is broken).
    """
    registry_table = MODEL_REGISTRY_LOOKUP.get(sport)
    mpd_cfg = MODEL_PERF_LOOKUP.get(sport)
    if registry_table is None or mpd_cfg is None:
        return None

    query = f"""
        WITH prod_models AS (
          SELECT
            model_id,
            DATE(created_at) AS registered_date,
            DATE_DIFF(@today, DATE(created_at), DAY) AS age_days
          FROM `{registry_table}`
          WHERE is_production = TRUE AND enabled = TRUE
        ),
        mpd_recent AS (
          -- Has each model produced any decay row in the last 14 days?
          -- 14d window is generous; MPD is written daily after grading.
          SELECT model_id, COUNT(*) AS mpd_rows
          FROM `{mpd_cfg['table']}`
          WHERE game_date BETWEEN DATE_SUB(@today, INTERVAL 14 DAY) AND @today
          GROUP BY model_id
        ),
        joined AS (
          SELECT
            p.model_id, p.registered_date, p.age_days,
            COALESCE(m.mpd_rows, 0) AS mpd_rows
          FROM prod_models p
          LEFT JOIN mpd_recent m USING (model_id)
        )
        SELECT
          COUNT(*) AS n_prod,
          COUNTIF(age_days < @grace_days AND mpd_rows = 0) AS n_in_transition,
          ARRAY_AGG(model_id ORDER BY model_id) AS model_ids,
          ARRAY_AGG(age_days ORDER BY model_id) AS ages,
          ARRAY_AGG(mpd_rows ORDER BY model_id) AS mpd_rows_per_model
        FROM joined
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('today', 'DATE', today),
            bigquery.ScalarQueryParameter('grace_days', 'INT64', FLEET_TRANSITION_GRACE_DAYS),
        ]
    )
    try:
        rows = list(bq.query(query, job_config=job_config).result(timeout=60))
    except Exception as e:
        logger.warning(f"Fleet-in-transition query failed for {sport}: {e}")
        return None

    if not rows or rows[0].n_prod == 0:
        return None

    row = rows[0]
    n_prod = int(row.n_prod)
    n_in_transition = int(row.n_in_transition)

    # Only suspend fleet_blocked when the ENTIRE production fleet is in transition.
    # Partial fleet swaps still allow fleet_blocked to consult the established models.
    if n_in_transition == n_prod and n_prod > 0:
        return {
            'fleet_in_transition': True,
            'fleet_in_transition_models': list(row.model_ids),
            'fleet_in_transition_ages': [int(a) for a in row.ages],
            'fleet_in_transition_mpd_rows': [int(m) for m in row.mpd_rows_per_model],
            'fleet_transition_grace_days': FLEET_TRANSITION_GRACE_DAYS,
        }
    return None


def _fleet_blocked(bq: bigquery.Client, sport: str, today: date) -> Optional[Dict[str, Any]]:
    """Are all enabled models in BLOCKED state?

    Uses model_performance_daily as written by decay_detection. Returns dict
    with halt context if all-blocked, else None.

    Schema note: NBA writes `state`/`rolling_hr_7d`; MLB writes `decay_state`/`hr_7d`.
    MLB has historically been a single-model fleet (`catboost_v2_regressor`), so the
    "all blocked" check fires whenever that one model is BLOCKED — which is the
    correct gating signal for MLB given there's no fallback to fail over to.

    NOTE: callers must check `_fleet_in_transition` first. When the fleet is
    mid-swap (fresh production model with no MPD rows yet), the BLOCKED signal
    is a false positive from the prior model's stale decay state. The caller
    is responsible for that gate — this function will happily return BLOCKED
    in transition because the underlying MPD query knows nothing about model
    registration recency.
    """
    cfg = MODEL_PERF_LOOKUP.get(sport)
    if cfg is None:
        return None

    # Both subquery and outer query need explicit partition predicates —
    # MLB's model_performance_daily is partitioned by game_date with
    # require_partition_filter=TRUE. The 7-day lookback is generous; we just
    # need a finite window to pick the most recent state row per model.
    query = f"""
        WITH latest AS (
          SELECT model_id, {cfg['state_col']} AS state, {cfg['hr_col']} AS hr_7d, {cfg['n_col']} AS n_7d
          FROM `{cfg['table']}` p
          WHERE game_date BETWEEN DATE_SUB(@today, INTERVAL 7 DAY) AND @today
            AND game_date = (
              SELECT MAX(game_date) FROM `{cfg['table']}`
              WHERE game_date BETWEEN DATE_SUB(@today, INTERVAL 7 DAY) AND @today
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
        logger.warning(f"Fleet block query failed for {sport}: {e}")
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


def _mlb_pick_drought(bq: bigquery.Client, today: date) -> Optional[Dict[str, Any]]:
    """MLB-only: have 2+ recent game days shipped zero picks despite predictions?

    Mirrors `check_mlb_pick_drought` in pipeline_canary_queries.py — the same
    multi-day signal that flagged the 5/14-5/16 drought caused by the
    `MAX_EDGE == effective_edge_floor` collision in the regressor pipeline.

    Fires when both: (a) predictions are flowing (>= 5/day) so the issue is
    downstream of the model, and (b) zero best-bet picks landed for 2+
    consecutive game days. Excludes off-days (0 scheduled games) and
    upstream-issue days (preds < 5).

    Why this complements `_predictions_inactive`: that check catches the
    "worker is dead" failure mode (zero preds). `_pick_drought` catches the
    "worker is live but the funnel collapsed" mode (preds normal, picks zero) —
    which is what actually happened 5/14-5/16.
    """
    pred_cfg = PREDICTIONS_LOOKUP['mlb']
    sched_cfg = SCHEDULE_LOOKUP['mlb']
    picks_cfg = PICKS_LOOKUP['mlb']

    query = f"""
        WITH game_days AS (
          SELECT DISTINCT {sched_cfg['date_col']} AS game_date
          FROM `{sched_cfg['table']}`
          WHERE {sched_cfg['date_col']} BETWEEN DATE_SUB(@today, INTERVAL 3 DAY) AND DATE_SUB(@today, INTERVAL 1 DAY)
        ),
        preds AS (
          SELECT {pred_cfg['date_col']} AS game_date, COUNT(*) AS n_preds
          FROM `{pred_cfg['table']}`
          WHERE {pred_cfg['date_col']} BETWEEN DATE_SUB(@today, INTERVAL 3 DAY) AND DATE_SUB(@today, INTERVAL 1 DAY)
          GROUP BY 1
        ),
        picks AS (
          SELECT {picks_cfg['date_col']} AS game_date, COUNT(*) AS n_picks
          FROM `{picks_cfg['table']}`
          WHERE {picks_cfg['date_col']} BETWEEN DATE_SUB(@today, INTERVAL 3 DAY) AND DATE_SUB(@today, INTERVAL 1 DAY)
          GROUP BY 1
        )
        SELECT
          g.game_date,
          COALESCE(p.n_preds, 0) AS n_preds,
          COALESCE(b.n_picks, 0) AS n_picks
        FROM game_days g
        LEFT JOIN preds p USING (game_date)
        LEFT JOIN picks b USING (game_date)
        ORDER BY g.game_date DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter('today', 'DATE', today)]
    )
    try:
        rows = list(bq.query(query, job_config=job_config).result(timeout=60))
    except Exception as e:
        logger.warning(f"MLB pick-drought query failed: {e}")
        return None

    if not rows:
        return None

    # Rows are ORDER BY game_date DESC — most recent first.
    drought_days: List[str] = []
    per_day: Dict[str, Dict[str, int]] = {}
    most_recent_is_drought = False
    for idx, r in enumerate(rows):
        n_preds = int(r.n_preds or 0)
        n_picks = int(r.n_picks or 0)
        is_drought = n_preds >= 5 and n_picks == 0
        per_day[r.game_date.isoformat()] = {'preds': n_preds, 'picks': n_picks}
        if is_drought:
            drought_days.append(r.game_date.isoformat())
        if idx == 0:
            most_recent_is_drought = is_drought

    # Two gates:
    #   - drought must be ONGOING: the most recent game day in the lookback
    #     must itself be a drought day. Otherwise the halt would persist
    #     after the system started producing picks again — exactly the
    #     opposite of what we want.
    #   - 2+ drought days total: differentiates from a single-day blip
    #     (late lines, scheduler hiccup) that self-heals.
    if not most_recent_is_drought or len(drought_days) < 2:
        return None

    return {
        'drought_days': drought_days,
        'drought_days_count': len(drought_days),
        'per_day': per_day,
    }


def _get_active_override(
    bq: bigquery.Client, sport: str, today: date
) -> Optional[Dict[str, Any]]:
    """Operator-set manual halt override from `nba_orchestration.halt_overrides`.

    Returns context dict if an active override covers `today`, else None.

    An override can ONLY force a halt — never resume the system. Applied last
    in the decision tree (see evaluate_halt_state step 6). A forgotten/stale
    override is therefore harmless: it can only keep the system more
    conservative, never publish picks during a real off-season.

    Fail-open: any query error returns None, so a broken/missing overrides
    table never suppresses the natural halt decision.
    """
    query = f"""
        SELECT halt_reason, start_date, end_date, note, created_by
        FROM `{HALT_OVERRIDES_TABLE}`
        WHERE sport = @sport
          AND active = TRUE
          AND start_date <= @today
          AND (end_date IS NULL OR end_date >= @today)
        ORDER BY created_at DESC
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
        logger.warning(
            f"halt_overrides lookup failed for {sport}: {e}; ignoring override."
        )
        return None
    if not rows:
        return None
    r = rows[0]
    return {
        'halt_reason': r.halt_reason or 'manual',
        'override_start_date': r.start_date.isoformat() if r.start_date else None,
        'override_end_date': r.end_date.isoformat() if r.end_date else None,
        'override_note': r.note,
        'override_created_by': r.created_by,
    }


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

    # 1. Schedule-presence check — strongest signal for off_season / dormant.
    has_games, games_today, has_future_games_14d = _has_recent_games(bq, today, sport)
    in_window = _is_in_season_window(today, sport)
    halt_metrics['games_today'] = games_today
    halt_metrics['has_games_in_21d_window'] = has_games
    halt_metrics['has_future_games_14d'] = has_future_games_14d
    halt_metrics['in_season_window'] = in_window

    if not has_games or not in_window:
        halt_active = True
        halt_reason = 'off_season'
    elif not has_future_games_14d:
        # In-window but no future games in next 14d — between-rounds dormancy
        # (e.g. NBA between playoff rounds in May). Treat as halted with a
        # specific reason; auto-clears when the next round's schedule lands.
        halt_active = True
        halt_reason = 'between_rounds'

    # 2. Edge collapse (NBA only — MLB thresholds not yet calibrated).
    #    The 5/14-5/16 MLB drought had avg edge 0.4-0.5 (not collapsed); the
    #    real driver was a floor/cap collision that `_mlb_pick_drought` catches
    #    directly. Adding an MLB edge-collapse check requires N>=30 calibration
    #    data we don't have yet.
    if not halt_active and sport == 'nba':
        edge_metrics = _nba_edge_collapse(bq, today)
        if edge_metrics is not None:
            halt_active = True
            halt_reason = 'edge_collapse'
            halt_metrics.update(edge_metrics)

    # 3. Fleet blocked — now sport-aware. Skip when the entire production fleet
    #    is mid-swap (fresh model with no MPD rows yet); otherwise the stale
    #    decay_state from the prior model produces a false positive halt.
    #    See _fleet_in_transition docstring for rationale.
    if not halt_active:
        transition = _fleet_in_transition(bq, sport, today)
        if transition is not None:
            # Record the suspension in halt_metrics for audit; do NOT halt.
            halt_metrics.update(transition)
            logger.info(
                f"[halt_state_writer] {sport}: fleet_blocked suspended — fleet in transition "
                f"(models={transition['fleet_in_transition_models']}, "
                f"ages={transition['fleet_in_transition_ages']} days, "
                f"mpd_rows={transition['fleet_in_transition_mpd_rows']})"
            )
        else:
            fleet_metrics = _fleet_blocked(bq, sport, today)
            if fleet_metrics is not None:
                halt_active = True
                halt_reason = 'fleet_blocked'
                halt_metrics.update(fleet_metrics)

    # 4. Predictions inactive — sport-aware. Catches operator-paused / dormant
    #    pipelines where edge_collapse and fleet_blocked checks need recent data
    #    they don't have. Last-resort signal: games scheduled but no predictions.
    if not halt_active:
        pred_metrics = _predictions_inactive(bq, sport, today)
        if pred_metrics is not None:
            halt_active = True
            halt_reason = 'predictions_inactive'
            halt_metrics.update(pred_metrics)

    # 5. MLB-only pick drought. Catches the failure mode where predictions
    #    flow normally but zero picks ship for 2+ consecutive days — exactly
    #    the 5/14-5/16 drought signature (filter squeeze / floor-cap collision).
    if not halt_active and sport == 'mlb':
        drought_metrics = _mlb_pick_drought(bq, today)
        if drought_metrics is not None:
            halt_active = True
            halt_reason = 'pick_drought'
            halt_metrics.update(drought_metrics)

    # 6. Manual operator override (halt_overrides table). Applied LAST: an
    #    operator halt always wins. It can only ADD a halt (force halt_active=
    #    True) — never resume the system — so a forgotten override can never
    #    publish picks during a real off-season. When the system is already
    #    halted naturally, the natural reason is kept; the override is still
    #    recorded in halt_metrics for the audit trail.
    override = _get_active_override(bq, sport, today)
    if override is not None:
        if not halt_active:
            halt_active = True
            halt_reason = override['halt_reason']
        halt_metrics['manual_override'] = override
        logger.info(
            f"[halt_state_writer] {sport}: manual override active "
            f"(reason={override['halt_reason']}, "
            f"created_by={override['override_created_by']})"
        )

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

    # Emit halt_state_age_hours metric (always 0 just after a successful
    # write — that's the point; the alert fires when this grows >36h).
    # Per-sport metric so the alert can distinguish NBA writer death from MLB.
    try:
        from shared.observability.metrics import emit_metric, MetricKind
        for sport in sports:
            if 'error' not in summary['results'].get(sport, {}):
                emit_metric(
                    metric_name='halt_state_age_hours',
                    value=0.0,
                    labels={'sport': sport},
                    kind=MetricKind.GAUGE,
                )
    except Exception as e:
        logger.warning(f"emit halt_state_age_hours failed (non-fatal): {e}")

    summary['written_at'] = datetime.now(timezone.utc).isoformat()
    return summary, 200


# Gen2 entrypoint alias (CLAUDE.md note: Gen2 entry point is immutable)
main = halt_state_writer
