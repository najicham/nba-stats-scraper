"""Decay Detection Cloud Function.

Monitors model performance daily, detects state transitions (HEALTHY → WATCH →
DEGRADING → BLOCKED), and posts Slack alerts with recommended actions.

Reads from model_performance_daily table (populated by ml/analysis/model_performance.py
after grading completes).

Triggered by Cloud Scheduler at 11:00 AM ET daily.

Thresholds:
    WATCH: 7d rolling HR < 58% for 2+ consecutive days
    ALERT: 7d rolling HR < 55% for 3+ consecutive days
    BLOCK: 7d rolling HR < 52.4% (breakeven at -110 odds)

Created: 2026-02-15 (Session 262)
Updated: 2026-02-15 (Session 266) - Added cross-model crash detector
Updated: 2026-02-28 (Session 363) - Added front-load detection
Updated: 2026-03-02 (Session 389) - Added aggregate best bets HR alerting
Updated: 2026-03-03 (Session 390) - Short-window HR, transition logic, pick volume anomaly, cascade fix
"""

import functions_framework
import hashlib
import json
import logging
import os
from datetime import datetime, date, timezone
from flask import Request
from google.cloud import bigquery
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Lazy-initialized clients
_bq_client = None


def _get_bq_client():
    global _bq_client
    if _bq_client is None:
        from shared.clients.bigquery_pool import get_bigquery_client
        from shared.config.gcp_config import get_project_id
        _bq_client = get_bigquery_client(project_id=get_project_id())
    return _bq_client


SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL_ALERTS')
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

# State thresholds
WATCH_THRESHOLD = 58.0
ALERT_THRESHOLD = 55.0
BLOCK_THRESHOLD = 52.4

# Front-load detection thresholds (Session 363)
FRONT_LOAD_HR_GAP = 5.0    # 7d HR must be this much below 14d HR
FRONT_LOAD_MIN_DAYS = 3    # Must be true for this many consecutive days
FRONT_LOAD_MIN_N = 20      # Minimum 7d sample size to be meaningful

# Best bets HR alerting thresholds (Session 389)
BB_HR_WATCH_THRESHOLD = 55.0    # Aggregate best bets HR — approaching concern
BB_HR_CRITICAL_THRESHOLD = 52.4  # Below breakeven at -110 odds
BB_HR_MIN_N = 10                 # Minimum graded picks for alert to fire

# Short-window HR alert (Session 390) — catches acute failures faster
BB_HR_SHORT_WINDOW_DAYS = 5     # Short rolling window
BB_HR_SHORT_CRITICAL = 40.0     # 5-day HR below 40% = something acutely broken
BB_HR_SHORT_MIN_N = 5           # Minimum picks in short window

# Pick volume anomaly detection (Session 390)
PICK_VOLUME_MIN_STD_DEVS = 2.0  # Alert when 2+ std devs from 14-day average
PICK_VOLUME_LOOKBACK_DAYS = 14  # Days to compute average pick volume

# Stale BLOCKED model retrain trigger
MAX_BLOCKED_DAYS = 7  # Trigger retrain alert after model is BLOCKED for this many days
RETRAIN_ON_BLOCKED = os.environ.get('RETRAIN_ON_BLOCKED', 'false').lower() == 'true'
WEEKLY_RETRAIN_URL = os.environ.get('WEEKLY_RETRAIN_URL', '')


def get_latest_performance(target_date: Optional[str] = None) -> List[Dict]:
    """Query model_performance_daily for the latest date with data."""
    bq = _get_bq_client()

    if target_date:
        date_filter = f"game_date = '{target_date}'"
    else:
        date_filter = "game_date = (SELECT MAX(game_date) FROM `{}.nba_predictions.model_performance_daily`)".format(PROJECT_ID)

    query = f"""
    SELECT
      game_date,
      model_id,
      rolling_hr_7d,
      rolling_n_7d,
      rolling_hr_14d,
      rolling_n_14d,
      state,
      consecutive_days_below_watch,
      consecutive_days_below_alert,
      action,
      action_reason,
      days_since_training,
      daily_picks,
      daily_wins,
      daily_hr
    FROM `{PROJECT_ID}.nba_predictions.model_performance_daily`
    WHERE {date_filter}
    ORDER BY model_id
    """

    results = list(bq.query(query).result())
    return [dict(r) for r in results]


def get_previous_day_states(game_date) -> Dict[str, str]:
    """Get the previous day's states for transition detection."""
    bq = _get_bq_client()

    query = f"""
    SELECT model_id, state
    FROM `{PROJECT_ID}.nba_predictions.model_performance_daily`
    WHERE game_date = (
      SELECT MAX(game_date)
      FROM `{PROJECT_ID}.nba_predictions.model_performance_daily`
      WHERE game_date < '{game_date}'
    )
    """
    try:
        results = list(bq.query(query).result())
        return {r.model_id: r.state for r in results}
    except Exception:
        return {}


def find_best_alternative(models: List[Dict], exclude_model: str) -> Optional[Dict]:
    """Find the best alternative model that's above breakeven."""
    candidates = [
        m for m in models
        if m['model_id'] != exclude_model
        and m.get('rolling_hr_7d') is not None
        and m['rolling_hr_7d'] >= BLOCK_THRESHOLD
        and m.get('rolling_n_7d', 0) >= 15
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda m: m['rolling_hr_7d'])


def detect_cross_model_crash(models: List[Dict]) -> Optional[Dict]:
    """Detect when 2+ models crash on the same day (market disruption, not model decay).

    If multiple models have daily_hr < 40% simultaneously, the cause is likely
    a market event (unusual game outcomes), not individual model problems.
    The recommended response differs: halt all betting vs switch models.

    Returns:
        Slack payload if crash detected, None otherwise.
    """
    CRASH_THRESHOLD = 40.0
    MIN_MODELS_FOR_CRASH = 2

    crashed = [
        m for m in models
        if m.get('daily_hr') is not None
        and m.get('daily_picks', 0) >= 5
        and m['daily_hr'] < CRASH_THRESHOLD
    ]

    if len(crashed) < MIN_MODELS_FOR_CRASH:
        return None

    game_date = models[0]['game_date'] if models else 'unknown'

    crash_lines = []
    for m in crashed:
        crash_lines.append(
            f"• *{m['model_id']}*: {m['daily_hr']:.1f}% "
            f"({m.get('daily_wins', 0)}/{m.get('daily_picks', 0)} picks)"
        )

    non_crashed = [m for m in models if m not in crashed and m.get('daily_hr') is not None]
    context_lines = []
    for m in non_crashed:
        context_lines.append(
            f"• {m['model_id']}: {m['daily_hr']:.1f}% "
            f"({m.get('daily_wins', 0)}/{m.get('daily_picks', 0)} picks)"
        )

    blocks = [
        {
            'type': 'header',
            'text': {
                'type': 'plain_text',
                'text': '🌊 MARKET DISRUPTION — Multi-Model Crash',
                'emoji': True,
            }
        },
        {
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': (
                    f"*{len(crashed)} models crashed below {CRASH_THRESHOLD:.0f}% on {game_date}*\n"
                    "This is likely a market event (unusual game outcomes), not model-specific decay.\n\n"
                    "*Crashed models:*\n" + '\n'.join(crash_lines)
                )
            }
        },
    ]

    if context_lines:
        blocks.append({
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': '*Other models:*\n' + '\n'.join(context_lines)
            }
        })

    blocks.append({
        'type': 'section',
        'text': {
            'type': 'mrkdwn',
            'text': (
                '*Recommended action:* Pause betting for 1 day. '
                'Do NOT switch models — all are affected. '
                'Check if unusual game outcomes (blowouts, OT, injuries) explain the miss.'
            )
        }
    })

    blocks.append({
        'type': 'context',
        'elements': [{
            'type': 'mrkdwn',
            'text': f"Date: {game_date} | Run: {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        }]
    })

    return {
        'attachments': [{
            'color': '#8B0000',
            'blocks': blocks
        }]
    }


def get_aggregate_best_bets_hr(target_date: Optional[str] = None) -> Optional[Dict]:
    """Query aggregate best bets HR across all models (21-day rolling).

    Best bets draws from all models, so aggregate HR is what matters for
    overall system health — not per-model HR.

    Session 389: This was the biggest monitoring gap — no automated alerting
    on the metric that actually determines profitability.
    """
    bq = _get_bq_client()

    if target_date:
        date_expr = "DATE('{}')".format(target_date)
    else:
        date_expr = "(SELECT MAX(game_date) FROM `{}.nba_predictions.signal_best_bets_picks`)".format(PROJECT_ID)

    query = f"""
    WITH target AS (
      SELECT {date_expr} AS target_date
    ),
    bb_graded AS (
      SELECT
        bb.game_date,
        bb.recommendation,
        pa.prediction_correct
      FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks` bb
      CROSS JOIN target t
      JOIN `{PROJECT_ID}.nba_predictions.prediction_accuracy` pa
        ON bb.player_lookup = pa.player_lookup
        AND bb.game_date = pa.game_date
        AND bb.system_id = pa.system_id
        AND pa.recommendation = bb.recommendation
        AND pa.line_value = bb.line_value
        AND pa.is_voided IS NOT TRUE
        AND pa.game_date BETWEEN DATE_SUB(t.target_date, INTERVAL 21 DAY) AND t.target_date
      WHERE bb.game_date BETWEEN DATE_SUB(t.target_date, INTERVAL 21 DAY) AND t.target_date
        AND pa.prediction_correct IS NOT NULL
    )
    SELECT
      COUNTIF(prediction_correct = TRUE) AS wins,
      COUNTIF(prediction_correct = FALSE) AS losses,
      COUNT(*) AS total,
      SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100.0 AS hr_21d,
      -- Directional splits
      SAFE_DIVIDE(
        COUNTIF(recommendation = 'OVER' AND prediction_correct = TRUE),
        NULLIF(COUNTIF(recommendation = 'OVER'), 0)
      ) * 100.0 AS over_hr_21d,
      COUNTIF(recommendation = 'OVER') AS over_n,
      SAFE_DIVIDE(
        COUNTIF(recommendation = 'UNDER' AND prediction_correct = TRUE),
        NULLIF(COUNTIF(recommendation = 'UNDER'), 0)
      ) * 100.0 AS under_hr_21d,
      COUNTIF(recommendation = 'UNDER') AS under_n
    FROM bb_graded
    """

    try:
        results = list(bq.query(query).result())
        if not results:
            return None
        row = results[0]
        total = row.total or 0
        if total < BB_HR_MIN_N:
            return None
        return {
            'hr_21d': round(row.hr_21d, 1) if row.hr_21d is not None else None,
            'wins': row.wins,
            'losses': row.losses,
            'total': total,
            'over_hr_21d': round(row.over_hr_21d, 1) if row.over_hr_21d is not None else None,
            'over_n': row.over_n,
            'under_hr_21d': round(row.under_hr_21d, 1) if row.under_hr_21d is not None else None,
            'under_n': row.under_n,
        }
    except Exception as e:
        logger.warning(f"Best bets HR query failed: {e}")
        return None


def build_best_bets_alert(bb_stats: Dict, game_date) -> Optional[Dict]:
    """Build Slack alert if aggregate best bets HR is below thresholds.

    Session 389: This is the single most important alert — it monitors the
    metric that directly determines profitability.
    """
    if not bb_stats or bb_stats.get('hr_21d') is None:
        return None

    hr = bb_stats['hr_21d']
    total = bb_stats['total']

    if hr >= BB_HR_WATCH_THRESHOLD:
        return None  # Healthy — no alert needed

    if hr < BB_HR_CRITICAL_THRESHOLD:
        emoji = '🚨'
        severity = 'CRITICAL — BELOW BREAKEVEN'
        color = '#8B0000'
        action = (
            '*Recommended action:* Best bets is losing money. '
            'Review filter stack effectiveness, check for disabled model leaks, '
            'and consider tightening edge floor or signal count gate.'
        )
    else:
        emoji = '⚠️'
        severity = 'WATCH'
        color = '#FF8C00'
        action = (
            '*Recommended action:* Monitor closely. Check if OVER or UNDER is '
            'dragging performance. Consider tightening filters on the weaker direction.'
        )

    over_str = f"{bb_stats['over_hr_21d']:.1f}% ({bb_stats['over_n']})" if bb_stats.get('over_hr_21d') is not None else 'N/A'
    under_str = f"{bb_stats['under_hr_21d']:.1f}% ({bb_stats['under_n']})" if bb_stats.get('under_hr_21d') is not None else 'N/A'

    blocks = [
        {
            'type': 'header',
            'text': {
                'type': 'plain_text',
                'text': f'{emoji} BEST BETS HR — {severity}',
                'emoji': True,
            }
        },
        {
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': (
                    f"*Aggregate best bets HR (21d): {hr:.1f}%* "
                    f"({bb_stats['wins']}W-{bb_stats['losses']}L, N={total})\n\n"
                    f"OVER: {over_str} | UNDER: {under_str}\n\n"
                    f"Breakeven: 52.4% | Watch: <{BB_HR_WATCH_THRESHOLD:.0f}% | "
                    f"Critical: <{BB_HR_CRITICAL_THRESHOLD:.1f}%"
                )
            }
        },
        {
            'type': 'section',
            'text': {'type': 'mrkdwn', 'text': action}
        },
        {
            'type': 'context',
            'elements': [{
                'type': 'mrkdwn',
                'text': f"Date: {game_date} | Run: {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
            }]
        }
    ]

    return {
        'attachments': [{
            'color': color,
            'blocks': blocks
        }]
    }


def get_best_bets_hr_short_window(target_date: Optional[str] = None) -> Optional[Dict]:
    """Query best bets HR over a short window (5 days) for acute failure detection.

    Session 390: The 21-day rolling HR is too slow to catch acute drops.
    A 5-day window at 40% threshold fires immediately when something breaks.
    """
    bq = _get_bq_client()

    if target_date:
        date_expr = "DATE('{}')".format(target_date)
    else:
        date_expr = "(SELECT MAX(game_date) FROM `{}.nba_predictions.signal_best_bets_picks`)".format(PROJECT_ID)

    query = f"""
    WITH target AS (
      SELECT {date_expr} AS target_date
    ),
    bb_graded AS (
      SELECT
        bb.game_date,
        pa.prediction_correct
      FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks` bb
      CROSS JOIN target t
      JOIN `{PROJECT_ID}.nba_predictions.prediction_accuracy` pa
        ON bb.player_lookup = pa.player_lookup
        AND bb.game_date = pa.game_date
        AND bb.system_id = pa.system_id
        AND pa.recommendation = bb.recommendation
        AND pa.line_value = bb.line_value
        AND pa.is_voided IS NOT TRUE
        AND pa.game_date BETWEEN DATE_SUB(t.target_date, INTERVAL {BB_HR_SHORT_WINDOW_DAYS} DAY) AND t.target_date
      WHERE bb.game_date BETWEEN DATE_SUB(t.target_date, INTERVAL {BB_HR_SHORT_WINDOW_DAYS} DAY) AND t.target_date
        AND pa.prediction_correct IS NOT NULL
    )
    SELECT
      COUNTIF(prediction_correct = TRUE) AS wins,
      COUNT(*) - COUNTIF(prediction_correct = TRUE) AS losses,
      COUNT(*) AS total,
      SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100.0 AS hr
    FROM bb_graded
    """

    try:
        results = list(bq.query(query).result())
        if not results:
            return None
        row = results[0]
        total = row.total or 0
        if total < BB_HR_SHORT_MIN_N:
            return None
        return {
            'hr': round(row.hr, 1) if row.hr is not None else None,
            'wins': row.wins,
            'losses': row.losses,
            'total': total,
        }
    except Exception as e:
        logger.warning(f"Short-window best bets HR query failed: {e}")
        return None


def build_short_window_alert(short_stats: Dict, game_date) -> Optional[Dict]:
    """Build Slack alert if short-window HR is critically low.

    Session 390: Fires only when 5-day HR < 40% — something is acutely broken.
    """
    if not short_stats or short_stats.get('hr') is None:
        return None

    hr = short_stats['hr']
    if hr >= BB_HR_SHORT_CRITICAL:
        return None

    blocks = [
        {
            'type': 'header',
            'text': {
                'type': 'plain_text',
                'text': '🔥 ACUTE FAILURE — Best Bets 5-Day HR Critical',
                'emoji': True,
            }
        },
        {
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': (
                    f"*{BB_HR_SHORT_WINDOW_DAYS}-day best bets HR: {hr:.1f}%* "
                    f"({short_stats['wins']}W-{short_stats['losses']}L, N={short_stats['total']})\n\n"
                    f"Threshold: <{BB_HR_SHORT_CRITICAL:.0f}% over {BB_HR_SHORT_WINDOW_DAYS} days\n\n"
                    '*This indicates an acute system failure, not gradual drift.*'
                )
            }
        },
        {
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': (
                    '*Recommended action:* Immediately investigate:\n'
                    '1. Check if a miscalibrated model leaked into best bets\n'
                    '2. Check for disabled model picks still in signal_best_bets_picks\n'
                    '3. Check filter stack effectiveness with `filter_health_audit.py`\n'
                    '4. Consider pausing best bets until root cause identified'
                )
            }
        },
        {
            'type': 'context',
            'elements': [{
                'type': 'mrkdwn',
                'text': f"Date: {game_date} | Run: {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
            }]
        }
    ]

    return {
        'attachments': [{
            'color': '#8B0000',
            'blocks': blocks
        }]
    }


def get_previous_bb_hr(game_date) -> Optional[float]:
    """Get previous day's best bets 21-day HR for transition detection.

    Session 390: Used to implement state transition logic so alerts
    only fire on transitions (HEALTHY→WATCH, WATCH→CRITICAL), not daily.
    """
    bq = _get_bq_client()

    prev_date = f"DATE_SUB(DATE('{game_date}'), INTERVAL 1 DAY)"
    query = f"""
    WITH bb_graded AS (
      SELECT pa.prediction_correct
      FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks` bb
      JOIN `{PROJECT_ID}.nba_predictions.prediction_accuracy` pa
        ON bb.player_lookup = pa.player_lookup
        AND bb.game_date = pa.game_date
        AND bb.system_id = pa.system_id
        AND pa.recommendation = bb.recommendation
        AND pa.line_value = bb.line_value
        AND pa.is_voided IS NOT TRUE
        AND pa.game_date BETWEEN DATE_SUB({prev_date}, INTERVAL 21 DAY) AND {prev_date}
      WHERE bb.game_date BETWEEN DATE_SUB({prev_date}, INTERVAL 21 DAY) AND {prev_date}
        AND pa.prediction_correct IS NOT NULL
    )
    SELECT
      SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100.0 AS hr,
      COUNT(*) AS total
    FROM bb_graded
    """

    try:
        results = list(bq.query(query).result())
        if not results or (results[0].total or 0) < BB_HR_MIN_N:
            return None
        return round(results[0].hr, 1) if results[0].hr is not None else None
    except Exception:
        return None


def classify_bb_state(hr: Optional[float]) -> str:
    """Classify best bets HR into a state for transition detection."""
    if hr is None:
        return 'UNKNOWN'
    if hr < BB_HR_CRITICAL_THRESHOLD:
        return 'CRITICAL'
    if hr < BB_HR_WATCH_THRESHOLD:
        return 'WATCH'
    return 'HEALTHY'


def check_pick_volume_anomaly(game_date) -> Optional[Dict]:
    """Detect pick volume anomalies — 0 picks on game days or 2+ std devs from average.

    Session 390: 0 picks on a game day means something is broken upstream but
    currently has no alert. Also detects unusual volume changes.
    Session 391: Added consecutive drought detection — escalates severity when
    multiple game days in a row have 0 best bets picks.
    """
    bq = _get_bq_client()

    query = f"""
    WITH games_today AS (
      SELECT COUNT(*) as game_count
      FROM `{PROJECT_ID}.nba_reference.nba_schedule`
      WHERE game_date = DATE('{game_date}')
        AND game_status = 1  -- Scheduled
    ),
    picks_today AS (
      SELECT COUNT(*) as pick_count
      FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks`
      WHERE game_date = DATE('{game_date}')
    ),
    -- Session 391: Check last 5 game days for consecutive drought
    recent_game_days AS (
      SELECT
        s.game_date,
        COALESCE(p.pick_count, 0) as pick_count
      FROM (
        SELECT DISTINCT game_date
        FROM `{PROJECT_ID}.nba_reference.nba_schedule`
        WHERE game_date BETWEEN DATE_SUB(DATE('{game_date}'), INTERVAL 7 DAY)
          AND DATE('{game_date}')
          AND game_status IN (1, 2, 3)  -- Any scheduled/in-progress/completed
      ) s
      LEFT JOIN (
        SELECT game_date, COUNT(*) as pick_count
        FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks`
        WHERE game_date BETWEEN DATE_SUB(DATE('{game_date}'), INTERVAL 7 DAY)
          AND DATE('{game_date}')
        GROUP BY game_date
      ) p ON s.game_date = p.game_date
      ORDER BY s.game_date DESC
      LIMIT 5
    ),
    historical AS (
      SELECT
        game_date,
        COUNT(*) as daily_picks
      FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks`
      WHERE game_date >= DATE_SUB(DATE('{game_date}'), INTERVAL {PICK_VOLUME_LOOKBACK_DAYS} DAY)
        AND game_date < DATE('{game_date}')
      GROUP BY game_date
    ),
    stats AS (
      SELECT
        AVG(daily_picks) as avg_picks,
        STDDEV(daily_picks) as std_picks,
        COUNT(*) as days_with_picks
      FROM historical
    )
    SELECT
      gt.game_count,
      pt.pick_count,
      ROUND(s.avg_picks, 1) as avg_picks,
      ROUND(s.std_picks, 1) as std_picks,
      s.days_with_picks,
      rgd_agg.recent_days
    FROM games_today gt
    CROSS JOIN picks_today pt
    CROSS JOIN stats s
    CROSS JOIN (
      SELECT ARRAY_AGG(STRUCT(game_date, pick_count) ORDER BY game_date DESC) as recent_days
      FROM recent_game_days
    ) rgd_agg
    """

    try:
        results = list(bq.query(query).result())
        if not results:
            return None
        row = results[0]

        game_count = row.game_count or 0
        pick_count = row.pick_count or 0
        avg_picks = row.avg_picks
        std_picks = row.std_picks
        days_with_picks = row.days_with_picks or 0

        # No games today — 0 picks is expected
        if game_count == 0:
            return None

        # Session 391: Count consecutive zero-pick game days (most recent first)
        consecutive_drought = 0
        recent_days = row.recent_days if hasattr(row, 'recent_days') and row.recent_days else []
        for day in recent_days:
            if day['pick_count'] == 0:
                consecutive_drought += 1
            else:
                break

        alerts = []
        is_drought = False

        # Alert 1: Zero picks on a game day
        if pick_count == 0 and game_count > 0:
            if consecutive_drought >= 2:
                is_drought = True
                alerts.append(
                    f"*DROUGHT: ZERO picks for {consecutive_drought} consecutive game days* "
                    f"on a {game_count}-game slate. "
                    "All models may be filtered, disabled, or pipeline is broken. "
                    "Immediate investigation required."
                )
            else:
                alerts.append(
                    f"*ZERO picks* on a {game_count}-game day. "
                    "Pipeline may not have run or all picks filtered."
                )

        # Alert 2: Volume anomaly (2+ std devs from average)
        if (avg_picks is not None and std_picks is not None
                and std_picks > 0 and days_with_picks >= 5):
            z_score = (pick_count - avg_picks) / std_picks
            if abs(z_score) >= PICK_VOLUME_MIN_STD_DEVS:
                direction = "above" if z_score > 0 else "below"
                alerts.append(
                    f"Pick count ({pick_count}) is {abs(z_score):.1f} std devs "
                    f"{direction} {PICK_VOLUME_LOOKBACK_DAYS}-day avg ({avg_picks:.0f} "
                    f"+/- {std_picks:.0f})."
                )

        if not alerts:
            return None

        header_text = '🚨 BEST BETS DROUGHT' if is_drought else '📦 PICK VOLUME ANOMALY'
        blocks = [
            {
                'type': 'header',
                'text': {
                    'type': 'plain_text',
                    'text': header_text,
                    'emoji': True,
                }
            },
            {
                'type': 'section',
                'text': {
                    'type': 'mrkdwn',
                    'text': '\n'.join(f"• {a}" for a in alerts)
                }
            },
            {
                'type': 'section',
                'text': {
                    'type': 'mrkdwn',
                    'text': (
                        f"Games today: {game_count} | Picks today: {pick_count} | "
                        f"14d avg: {avg_picks:.0f}" if avg_picks else
                        f"Games today: {game_count} | Picks today: {pick_count}"
                    )
                }
            },
            {
                'type': 'context',
                'elements': [{
                    'type': 'mrkdwn',
                    'text': f"Date: {game_date} | Run: {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
                }]
            }
        ]

        # Red for drought (critical), orange for single-day anomaly
        alert_color = '#FF0000' if is_drought else '#FF4500'
        return {
            'attachments': [{
                'color': alert_color,
                'blocks': blocks
            }]
        }

    except Exception as e:
        logger.warning(f"Pick volume anomaly check failed: {e}")
        return None


def auto_disable_blocked_models(models: List[Dict], best_bets_model: str,
                                game_date) -> Tuple[List[str], Optional[Dict]]:
    """Auto-disable models that have been BLOCKED (7d HR < breakeven).

    Session 389: BLOCKED models were NOT auto-disabled — required manual
    deactivate_model.py. This closes the gap by disabling in the registry,
    which prevents new predictions and triggers signal exporter filtering.

    Session 405: Added additional safeguards:
    - AUTO_DISABLE_ENABLED env var (defaults to False until validated)
    - Minimum 3 enabled models safety floor
    - Minimum 7-day model age (insufficient data for younger models)
    - consecutive_days_below_alert >= 3 (not just one bad day)

    Safeguards:
    - Never disables the champion/best_bets model (manual decision only)
    - Requires N >= 15 graded picks (avoids disabling on sparse data)
    - Never disables if fewer than 3 models would remain enabled
    - Never disables models less than 7 days old
    - Requires 3+ consecutive days below alert threshold
    - Logs audit trail to service_errors
    """
    # Session 405: Feature flag — defaults to off until validated in production
    if not os.environ.get('AUTO_DISABLE_ENABLED', '').lower() in ('true', '1', 'yes'):
        logger.info("Auto-disable is disabled (set AUTO_DISABLE_ENABLED=true to enable)")
        return [], None

    bq = _get_bq_client()
    disabled = []

    # Session 405: Count currently enabled models for safety floor
    enabled_count = 0
    try:
        enabled_query = f"""
        SELECT COUNT(*) as cnt
        FROM `{PROJECT_ID}.nba_predictions.model_registry`
        WHERE enabled = TRUE
        """
        enabled_rows = list(bq.query(enabled_query).result())
        enabled_count = enabled_rows[0].cnt if enabled_rows else 0
    except Exception as e:
        logger.warning(f"Failed to count enabled models: {e}")
        return [], None

    MIN_ENABLED_MODELS = 3
    MIN_MODEL_AGE_DAYS = 7
    MIN_CONSECUTIVE_DAYS_BELOW = 3

    blocked_models = [
        m for m in models
        if m.get('state') == 'BLOCKED'
        and m['model_id'] != best_bets_model
        and m.get('rolling_n_7d', 0) >= 15
        and m.get('consecutive_days_below_alert', 0) >= MIN_CONSECUTIVE_DAYS_BELOW
        and m.get('days_since_training', 0) >= MIN_MODEL_AGE_DAYS
    ]

    if not blocked_models:
        return [], None

    # Session 405: Safety floor — never auto-disable if too few models remain
    max_to_disable = enabled_count - MIN_ENABLED_MODELS
    if max_to_disable <= 0:
        logger.info(
            f"Safety floor: only {enabled_count} enabled models, "
            f"need minimum {MIN_ENABLED_MODELS} — skipping auto-disable"
        )
        return [], None

    # Limit disabled count to stay above safety floor
    blocked_models = blocked_models[:max_to_disable]

    for m in blocked_models:
        model_id = m['model_id']
        try:
            # Check if already disabled in registry
            check_query = f"""
            SELECT enabled, status
            FROM `{PROJECT_ID}.nba_predictions.model_registry`
            WHERE model_id = @model_id
            """
            check_params = [bigquery.ScalarQueryParameter('model_id', 'STRING', model_id)]
            rows = list(bq.query(
                check_query,
                job_config=bigquery.QueryJobConfig(query_parameters=check_params),
            ).result(timeout=15))

            if not rows:
                logger.warning(f"Model {model_id} not in registry — skipping auto-disable")
                continue

            row = rows[0]
            if not row.enabled and row.status == 'blocked':
                logger.info(f"Model {model_id} already disabled — skipping")
                continue

            # Disable in registry
            disable_query = f"""
            UPDATE `{PROJECT_ID}.nba_predictions.model_registry`
            SET enabled = FALSE, status = 'blocked'
            WHERE model_id = @model_id
            """
            job = bq.query(
                disable_query,
                job_config=bigquery.QueryJobConfig(query_parameters=check_params),
            )
            job.result(timeout=15)

            # Deactivate predictions for today (matches deactivate_model.py step 4)
            deactivate_query = f"""
            UPDATE `{PROJECT_ID}.nba_predictions.player_prop_predictions`
            SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP()
            WHERE system_id = @model_id
              AND game_date = CURRENT_DATE()
              AND is_active = TRUE
            """
            try:
                deact_job = bq.query(
                    deactivate_query,
                    job_config=bigquery.QueryJobConfig(query_parameters=check_params),
                )
                deact_job.result(timeout=30)
                logger.info(
                    f"Deactivated {deact_job.num_dml_affected_rows} predictions "
                    f"for {model_id}"
                )
            except Exception as deact_err:
                logger.warning(f"Failed to deactivate predictions for {model_id}: {deact_err}")

            # Remove signal picks for today (matches deactivate_model.py step 5)
            delete_picks_query = f"""
            DELETE FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks`
            WHERE system_id = @model_id
              AND game_date = CURRENT_DATE()
            """
            try:
                del_job = bq.query(
                    delete_picks_query,
                    job_config=bigquery.QueryJobConfig(query_parameters=check_params),
                )
                del_job.result(timeout=30)
                logger.info(
                    f"Removed {del_job.num_dml_affected_rows} signal picks "
                    f"for {model_id}"
                )
            except Exception as del_err:
                logger.warning(f"Failed to remove signal picks for {model_id}: {del_err}")

            # Audit trail — write to nba_orchestration.service_errors
            now = datetime.now(timezone.utc)
            error_msg = (
                f'Auto-disabled BLOCKED model {model_id}: '
                f'7d HR={m.get("rolling_hr_7d")}% (N={m.get("rolling_n_7d")})'
            )
            error_id = hashlib.md5(
                f'decay_detection_auto_disable:model_auto_disabled:{error_msg}:{now.strftime("%Y%m%d%H%M")}'.encode()
            ).hexdigest()
            audit_query = f"""
            INSERT INTO `{PROJECT_ID}.nba_orchestration.service_errors`
            (error_id, service_name, error_timestamp, error_type, error_category,
             severity, error_message, game_date, phase, recovery_attempted, recovery_successful)
            VALUES (
              @error_id,
              'decay_detection_auto_disable',
              @error_timestamp,
              'model_auto_disabled',
              'model_lifecycle',
              'info',
              @message,
              @game_date,
              'phase_5_predictions',
              FALSE,
              FALSE
            )
            """
            audit_params = [
                bigquery.ScalarQueryParameter('error_id', 'STRING', error_id),
                bigquery.ScalarQueryParameter('error_timestamp', 'TIMESTAMP', now.isoformat()),
                bigquery.ScalarQueryParameter('message', 'STRING', error_msg),
                bigquery.ScalarQueryParameter('game_date', 'DATE', str(game_date)),
            ]
            try:
                bq.query(
                    audit_query,
                    job_config=bigquery.QueryJobConfig(query_parameters=audit_params),
                ).result(timeout=15)
            except Exception as audit_err:
                logger.warning(f"Failed to log audit for {model_id}: {audit_err}")

            disabled.append(model_id)
            logger.info(
                f"Auto-disabled BLOCKED model {model_id}: "
                f"7d HR={m.get('rolling_hr_7d')}% (N={m.get('rolling_n_7d')})"
            )

        except Exception as e:
            logger.error(f"Failed to auto-disable {model_id}: {e}")

    if not disabled:
        return [], None

    # Build Slack alert
    lines = [f"• `{mid}`" for mid in disabled]
    blocks = [
        {
            'type': 'header',
            'text': {
                'type': 'plain_text',
                'text': '🔒 AUTO-DISABLED — BLOCKED Models',
                'emoji': True,
            }
        },
        {
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': (
                    f"*{len(disabled)} model(s) auto-disabled* (7d HR below "
                    f"{BLOCK_THRESHOLD:.1f}% breakeven with N >= 15):\n"
                    + '\n'.join(lines) + '\n\n'
                    'Registry set to `enabled=FALSE, status=blocked`. '
                    'Signal exporter will filter these from best bets on next export.\n\n'
                    f'*Champion model `{best_bets_model}` is protected* — '
                    'never auto-disabled.'
                )
            }
        },
        {
            'type': 'context',
            'elements': [{
                'type': 'mrkdwn',
                'text': (
                    f"Date: {game_date} | "
                    f"Re-enable: manual BQ `UPDATE model_registry SET enabled=TRUE, status='shadow'` | "
                    f"Run: {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
                )
            }]
        }
    ]

    payload = {
        'attachments': [{
            'color': '#FF4500',
            'blocks': blocks
        }]
    }

    return disabled, payload


def trigger_retrain_if_stale(
    bq: bigquery.Client,
    target_date: str,
) -> List[str]:
    """Alert (or trigger) retrain for BLOCKED models stale for MAX_BLOCKED_DAYS days.

    When RETRAIN_ON_BLOCKED=false (default): logs warning and sends Slack alert.
    When RETRAIN_ON_BLOCKED=true: additionally POSTs to WEEKLY_RETRAIN_URL to
    trigger an immediate retrain for the blocked family.

    Returns list of model IDs that triggered the alert/retrain.
    """
    query = f"""
    SELECT
        mpd.model_id,
        mpd.consecutive_days_below_alert,
        mpd.rolling_hr_7d,
        mr.training_end_date
    FROM `{PROJECT_ID}.nba_predictions.model_performance_daily` mpd
    JOIN `{PROJECT_ID}.nba_predictions.model_registry` mr
        ON mpd.model_id = mr.model_id
    WHERE mpd.game_date = @target_date
      AND mpd.state = 'BLOCKED'
      AND mpd.consecutive_days_below_alert >= {MAX_BLOCKED_DAYS}
      AND mr.enabled = TRUE
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter('target_date', 'DATE', target_date)]
    )
    try:
        rows = list(bq.query(query, job_config=job_config).result(timeout=60))
    except Exception as e:
        logger.error(f"trigger_retrain_if_stale: query failed: {e}")
        return []

    if not rows:
        return []

    triggered = []
    for row in rows:
        model_id = row.model_id
        days_blocked = row.consecutive_days_below_alert
        hr_7d = row.rolling_hr_7d

        msg = (
            f"Model `{model_id}` has been BLOCKED for {days_blocked} days "
            f"(7d HR={hr_7d:.1f}%). "
        )

        if RETRAIN_ON_BLOCKED and WEEKLY_RETRAIN_URL:
            # Trigger immediate retrain for this model
            try:
                import urllib.request
                import json as _json
                payload = _json.dumps({"model_id": model_id, "force": True}).encode()
                req = urllib.request.Request(
                    WEEKLY_RETRAIN_URL,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status_code = resp.status
                msg += f"Auto-retrain triggered (HTTP {status_code})."
                logger.info(f"Auto-retrain triggered for model '{model_id}': {msg}")
            except Exception as e:
                msg += f"Auto-retrain FAILED: {e}. Manual retrain required."
                logger.error(f"Auto-retrain failed for '{model_id}': {e}")
        else:
            msg += (
                "Set `RETRAIN_ON_BLOCKED=true` + `WEEKLY_RETRAIN_URL` env vars on "
                "decay-detection CF to enable auto-retrain."
            )
            logger.warning(f"Stale BLOCKED model detected (retrain disabled): {msg}")

        # Send Slack alert
        slack_payload = {
            'attachments': [{
                'color': '#FF8C00',
                'blocks': [
                    {
                        'type': 'header',
                        'text': {
                            'type': 'plain_text',
                            'text': ':rotating_light: Stale BLOCKED Model Alert',
                            'emoji': True,
                        }
                    },
                    {
                        'type': 'section',
                        'text': {'type': 'mrkdwn', 'text': msg}
                    },
                    {
                        'type': 'context',
                        'elements': [{
                            'type': 'mrkdwn',
                            'text': (
                                f"Date: {target_date} | "
                                f"Run: {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
                            )
                        }]
                    }
                ]
            }]
        }
        send_slack_alert(slack_payload)

        triggered.append(model_id)

    return triggered


def detect_front_loading(game_date) -> Tuple[List[Dict], Optional[Dict]]:
    """Detect models exhibiting front-loading pattern.

    Front-loading: 7d rolling HR consistently lower than 14d rolling HR,
    indicating the model performed well initially but is now degrading.

    Pattern: rolling_hr_7d < rolling_hr_14d - FRONT_LOAD_HR_GAP for
    FRONT_LOAD_MIN_DAYS+ consecutive days.

    Session 363: Observed in catboost_v12_train1225_0205 (Session 360) —
    7d HR was consistently 6-8pp below 14d HR, declining 50% → 32% in a week.

    Returns:
        Tuple of (front_loaded_models list, slack_payload or None)
    """
    bq = _get_bq_client()

    query = f"""
    SELECT
      game_date,
      model_id,
      rolling_hr_7d,
      rolling_hr_14d,
      rolling_n_7d,
      rolling_n_14d,
      state
    FROM `{PROJECT_ID}.nba_predictions.model_performance_daily`
    WHERE game_date >= DATE_SUB(DATE('{game_date}'), INTERVAL 7 DAY)
      AND game_date <= '{game_date}'
      AND rolling_hr_7d IS NOT NULL
      AND rolling_hr_14d IS NOT NULL
      AND rolling_n_7d >= {FRONT_LOAD_MIN_N}
    ORDER BY model_id, game_date DESC
    """

    try:
        results = list(bq.query(query).result())
    except Exception as e:
        logger.warning(f"Front-load detection query failed: {e}")
        return [], None

    # Group by model_id (results ordered by game_date DESC within each model)
    by_model: Dict[str, List[Dict]] = {}
    for r in results:
        mid = r.model_id
        if mid not in by_model:
            by_model[mid] = []
        by_model[mid].append(dict(r))

    front_loaded = []
    for model_id, days in by_model.items():
        # days are ordered DESC — check consecutive most recent days
        consecutive = 0
        for day in days:
            gap = day['rolling_hr_14d'] - day['rolling_hr_7d']
            if gap >= FRONT_LOAD_HR_GAP:
                consecutive += 1
            else:
                break

        if consecutive >= FRONT_LOAD_MIN_DAYS:
            latest = days[0]
            front_loaded.append({
                'model_id': model_id,
                'consecutive_days': consecutive,
                'hr_7d': latest['rolling_hr_7d'],
                'hr_14d': latest['rolling_hr_14d'],
                'gap': round(latest['rolling_hr_14d'] - latest['rolling_hr_7d'], 1),
                'state': latest.get('state'),
                'n_7d': latest.get('rolling_n_7d'),
            })

    if not front_loaded:
        return [], None

    # Build Slack alert
    lines = []
    for fl in front_loaded:
        lines.append(
            f"• *{fl['model_id']}*: 7d {fl['hr_7d']:.1f}% vs 14d {fl['hr_14d']:.1f}% "
            f"(gap: {fl['gap']}pp for {fl['consecutive_days']} days, N={fl['n_7d']})"
        )

    blocks = [
        {
            'type': 'header',
            'text': {
                'type': 'plain_text',
                'text': '📉 FRONT-LOAD DETECTED — Model Degrading After Initial Success',
                'emoji': True,
            }
        },
        {
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': (
                    f"*{len(front_loaded)} model(s) showing front-load pattern*\n"
                    f"7-day HR consistently {FRONT_LOAD_HR_GAP:.0f}+ pp below 14-day HR "
                    f"for {FRONT_LOAD_MIN_DAYS}+ consecutive days.\n\n"
                    + '\n'.join(lines)
                )
            }
        },
        {
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': (
                    '*What this means:* The model performed well initially but recent predictions '
                    'are significantly worse. This often indicates the model learned patterns '
                    'that were temporary. Consider disabling or retraining.'
                )
            }
        },
        {
            'type': 'context',
            'elements': [{
                'type': 'mrkdwn',
                'text': f"Date: {game_date} | Run: {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
            }]
        }
    ]

    payload = {
        'attachments': [{
            'color': '#FF8C00',  # Dark orange
            'blocks': blocks
        }]
    }

    return front_loaded, payload


def build_alert_payload(models: List[Dict], transitions: List[Dict],
                        best_bets_model: str) -> Optional[Dict]:
    """Build Slack alert payload if any model has state transitions or is degraded."""
    # Only alert on transitions or if best bets model is unhealthy
    best_bets_state = None
    for m in models:
        if m['model_id'] == best_bets_model:
            best_bets_state = m.get('state')
            break

    has_transitions = len(transitions) > 0
    best_bets_unhealthy = best_bets_state in ('WATCH', 'DEGRADING', 'BLOCKED')

    # Check if any challenger outperforms champion by 5+ points with N >= 30
    best_bets_hr = None
    for m in models:
        if m['model_id'] == best_bets_model:
            best_bets_hr = m.get('rolling_hr_7d')
            break
    challenger_outperforming = False
    if best_bets_hr is not None:
        for m in models:
            if m['model_id'] == best_bets_model:
                continue
            c_hr = m.get('rolling_hr_7d')
            c_n = m.get('rolling_n_7d', 0)
            if c_hr is not None and c_n >= 30 and c_hr - best_bets_hr >= 5.0:
                challenger_outperforming = True
                break

    if not has_transitions and not best_bets_unhealthy and not challenger_outperforming:
        return None

    game_date = models[0]['game_date'] if models else 'unknown'

    # Build blocks
    blocks = []

    # Header
    if best_bets_state == 'BLOCKED':
        emoji = '🚨'
        color = 'danger'
        header = f'{emoji} MODEL DECAY — BLOCKED'
    elif best_bets_state == 'DEGRADING':
        emoji = '⚠️'
        color = 'warning'
        header = f'{emoji} MODEL DECAY — DEGRADING'
    elif best_bets_state == 'WATCH':
        emoji = '👀'
        color = 'warning'
        header = f'{emoji} MODEL DECAY — WATCH'
    else:
        emoji = '📊'
        color = '#439FE0'
        header = f'{emoji} Model State Change'

    blocks.append({
        'type': 'header',
        'text': {'type': 'plain_text', 'text': header, 'emoji': True}
    })

    # Model summary table
    model_lines = []
    for m in models:
        state_icon = {
            'HEALTHY': '✅',
            'WATCH': '👀',
            'DEGRADING': '⚠️',
            'BLOCKED': '🚨',
            'INSUFFICIENT_DATA': '❓',
        }.get(m.get('state', ''), '❓')

        hr = m.get('rolling_hr_7d')
        n = m.get('rolling_n_7d', 0)
        days = m.get('days_since_training')

        hr_str = f"{hr:.1f}%" if hr is not None else 'N/A'
        days_str = f" ({days}d stale)" if days and days > 20 else ''

        label = f"*{m['model_id']}*" if m['model_id'] == best_bets_model else m['model_id']
        model_lines.append(
            f"{state_icon} {label}: {hr_str} HR 7d (N={n}){days_str}"
        )

    blocks.append({
        'type': 'section',
        'text': {
            'type': 'mrkdwn',
            'text': '\n'.join(model_lines)
        }
    })

    # Transitions
    if transitions:
        trans_lines = []
        for t in transitions:
            trans_lines.append(
                f"• *{t['model_id']}*: {t['from_state']} → {t['to_state']} "
                f"— {t.get('reason', '')}"
            )
        blocks.append({
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': '*State Transitions:*\n' + '\n'.join(trans_lines)
            }
        })

    # Recommendation
    if best_bets_state in ('BLOCKED', 'DEGRADING'):
        alt = find_best_alternative(models, best_bets_model)
        if alt:
            blocks.append({
                'type': 'section',
                'text': {
                    'type': 'mrkdwn',
                    'text': (
                        f"*Recommended:* Switch best bets to "
                        f"`{alt['model_id']}` ({alt['rolling_hr_7d']:.1f}% HR, "
                        f"N={alt['rolling_n_7d']})"
                    )
                }
            })
        else:
            blocks.append({
                'type': 'section',
                'text': {
                    'type': 'mrkdwn',
                    'text': '*No viable alternative model above breakeven.* Consider retraining.'
                }
            })

    # Challenger outperformance alert (even when champion is HEALTHY/WATCH)
    best_bets_hr = None
    for m in models:
        if m['model_id'] == best_bets_model:
            best_bets_hr = m.get('rolling_hr_7d')
            break

    if best_bets_hr is not None:
        for m in models:
            if m['model_id'] == best_bets_model:
                continue
            challenger_hr = m.get('rolling_hr_7d')
            challenger_n = m.get('rolling_n_7d', 0)
            if (challenger_hr is not None
                    and challenger_n >= 30
                    and challenger_hr - best_bets_hr >= 5.0):
                margin = round(challenger_hr - best_bets_hr, 1)
                blocks.append({
                    'type': 'section',
                    'text': {
                        'type': 'mrkdwn',
                        'text': (
                            f"📈 *Challenger `{m['model_id']}` outperforming by "
                            f"{margin}pp* ({challenger_hr:.1f}% vs {best_bets_hr:.1f}%, "
                            f"N={challenger_n}). Consider promotion."
                        )
                    }
                })

    # Timestamp
    blocks.append({
        'type': 'context',
        'elements': [{
            'type': 'mrkdwn',
            'text': f"Date: {game_date} | Run: {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        }]
    })

    return {
        'attachments': [{
            'color': color,
            'blocks': blocks
        }]
    }


def send_slack_alert(payload: Dict) -> bool:
    """Send alert to Slack."""
    if not SLACK_WEBHOOK_URL:
        logger.warning("No SLACK_WEBHOOK_URL_ALERTS configured, skipping alert")
        return False

    try:
        from shared.utils.slack_retry import send_slack_webhook_with_retry
        return send_slack_webhook_with_retry(SLACK_WEBHOOK_URL, payload, timeout=10)
    except ImportError:
        # Fallback if shared utils not available
        import requests
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        return resp.status_code == 200


@functions_framework.http
def decay_detection(request: Request):
    """HTTP entry point for decay detection.

    Triggered by Cloud Scheduler daily at 11:00 AM ET.
    Always returns 200 (reporter pattern — Session 219).
    """
    logger.info("Starting decay detection check...")

    try:
        # Get current model performance
        models = get_latest_performance()

        if not models:
            logger.info("No model performance data found")
            return json.dumps({
                'status': 'no_data',
                'message': 'No model_performance_daily data found',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }), 200, {'Content-Type': 'application/json'}

        game_date = models[0]['game_date']
        logger.info(f"Analyzing {len(models)} models for {game_date}")

        # Detect state transitions
        prev_states = get_previous_day_states(game_date)
        transitions = []
        for m in models:
            mid = m['model_id']
            current_state = m.get('state', 'UNKNOWN')
            prev_state = prev_states.get(mid, 'UNKNOWN')
            if current_state != prev_state and prev_state != 'UNKNOWN':
                transitions.append({
                    'model_id': mid,
                    'from_state': prev_state,
                    'to_state': current_state,
                    'reason': m.get('action_reason', ''),
                })

        # Determine best bets model
        from shared.config.model_selection import get_best_bets_model_id
        best_bets_model = get_best_bets_model_id()

        # Check for cross-model crash (market disruption)
        cross_model_crash = detect_cross_model_crash(models)
        crash_alert_sent = False
        if cross_model_crash:
            crash_alert_sent = send_slack_alert(cross_model_crash)
            logger.info(f"Cross-model crash alert sent: {crash_alert_sent}")

        # Build and send decay alert if needed (skip if crash already alerted)
        payload = build_alert_payload(models, transitions, best_bets_model)
        alert_sent = False
        if payload and not cross_model_crash:
            alert_sent = send_slack_alert(payload)
            logger.info(f"Alert sent: {alert_sent}, transitions: {len(transitions)}")
        elif not payload and not cross_model_crash:
            logger.info("No alert needed — all models healthy, no transitions")

        # Check for front-loading pattern (Session 363)
        front_loaded, front_load_payload = detect_front_loading(game_date)
        front_load_alert_sent = False
        if front_load_payload:
            front_load_alert_sent = send_slack_alert(front_load_payload)
            logger.info(
                f"Front-load alert sent: {front_load_alert_sent}, "
                f"models: {[fl['model_id'] for fl in front_loaded]}"
            )

        # Auto-disable BLOCKED models (Session 389)
        # Skip during cross-model crash (market disruption, not model fault)
        auto_disabled = []
        auto_disable_alert_sent = False
        if not cross_model_crash:
            auto_disabled, auto_disable_payload = auto_disable_blocked_models(
                models, best_bets_model, game_date
            )
            if auto_disable_payload:
                auto_disable_alert_sent = send_slack_alert(auto_disable_payload)
                logger.info(
                    f"Auto-disabled {len(auto_disabled)} BLOCKED models: "
                    f"{auto_disabled}"
                )
        else:
            logger.info("Skipping auto-disable during cross-model crash")

        # Check for models that have been BLOCKED for too long and alert/trigger retrain
        stale_families = []
        try:
            bq = _get_bq_client()
            stale_families = trigger_retrain_if_stale(bq, str(game_date))
            if stale_families:
                logger.info(f"Stale BLOCKED model check complete: {len(stale_families)} families alerted")
        except Exception as e:
            logger.error(f"trigger_retrain_if_stale failed (non-blocking): {e}")

        # Check aggregate best bets HR with transition logic (Sessions 389-390)
        bb_stats = get_aggregate_best_bets_hr(str(game_date))
        bb_alert_sent = False
        bb_state = 'UNKNOWN'
        if bb_stats:
            current_hr = bb_stats.get('hr_21d')
            bb_state = classify_bb_state(current_hr)

            # Transition logic (Session 390): only alert on state changes
            prev_hr = get_previous_bb_hr(game_date)
            prev_bb_state = classify_bb_state(prev_hr)

            # Alert on transitions or first time below threshold
            state_changed = bb_state != prev_bb_state and prev_bb_state != 'UNKNOWN'
            first_detection = prev_bb_state == 'UNKNOWN' and bb_state != 'HEALTHY'

            if state_changed or first_detection:
                bb_payload = build_best_bets_alert(bb_stats, game_date)
                if bb_payload:
                    bb_alert_sent = send_slack_alert(bb_payload)
                    transition_str = f"{prev_bb_state} → {bb_state}" if state_changed else f"initial {bb_state}"
                    logger.info(
                        f"Best bets HR alert sent: {bb_alert_sent}, "
                        f"HR={current_hr}% (N={bb_stats['total']}), "
                        f"transition: {transition_str}"
                    )
            else:
                logger.info(
                    f"Best bets HR {bb_state}: {current_hr}% "
                    f"(N={bb_stats['total']}), no state change from {prev_bb_state}"
                )
        else:
            logger.info("No best bets HR data available (insufficient graded picks)")

        # Short-window HR alert for acute failures (Session 390)
        short_alert_sent = False
        short_stats = get_best_bets_hr_short_window(str(game_date))
        if short_stats:
            short_payload = build_short_window_alert(short_stats, game_date)
            if short_payload:
                short_alert_sent = send_slack_alert(short_payload)
                logger.info(
                    f"Short-window HR alert sent: {short_alert_sent}, "
                    f"{BB_HR_SHORT_WINDOW_DAYS}d HR={short_stats['hr']}% "
                    f"(N={short_stats['total']})"
                )
            else:
                logger.info(
                    f"Short-window HR OK: {BB_HR_SHORT_WINDOW_DAYS}d "
                    f"HR={short_stats['hr']}% (N={short_stats['total']})"
                )

        # Pick volume anomaly detection (Session 390)
        volume_alert_sent = False
        volume_payload = check_pick_volume_anomaly(game_date)
        if volume_payload:
            volume_alert_sent = send_slack_alert(volume_payload)
            logger.info(f"Pick volume anomaly alert sent: {volume_alert_sent}")

        # Build response
        model_summary = {}
        for m in models:
            model_summary[m['model_id']] = {
                'state': m.get('state'),
                'rolling_hr_7d': m.get('rolling_hr_7d'),
                'rolling_n_7d': m.get('rolling_n_7d'),
                'days_since_training': m.get('days_since_training'),
            }

        return json.dumps({
            'status': 'success',
            'game_date': str(game_date),
            'models': model_summary,
            'transitions': transitions,
            'alert_sent': alert_sent,
            'crash_alert_sent': crash_alert_sent,
            'front_load_alert_sent': front_load_alert_sent,
            'front_loaded_models': [fl['model_id'] for fl in front_loaded],
            'best_bets_model': best_bets_model,
            'best_bets_hr': bb_stats,
            'bb_state': bb_state,
            'bb_alert_sent': bb_alert_sent,
            'short_window_hr': short_stats,
            'short_alert_sent': short_alert_sent,
            'volume_alert_sent': volume_alert_sent,
            'auto_disabled_models': auto_disabled,
            'auto_disable_alert_sent': auto_disable_alert_sent,
            'stale_blocked_models_alerted': stale_families,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 200, {'Content-Type': 'application/json'}

    except Exception as e:
        logger.error(f"Error in decay detection: {e}", exc_info=True)
        return json.dumps({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 200, {'Content-Type': 'application/json'}


# Gen2 CRITICAL: Main alias (Session 219)
main = decay_detection


if __name__ == '__main__':
    """Local testing: python orchestration/cloud_functions/decay_detection/main.py [date]"""
    import sys
    target_date = sys.argv[1] if len(sys.argv) > 1 else None
    models = get_latest_performance(target_date)
    print(f"\nModels ({len(models)}):")
    for m in models:
        hr_7d = m.get('rolling_hr_7d')
        hr_14d = m.get('rolling_hr_14d')
        gap_str = ''
        if hr_7d is not None and hr_14d is not None:
            gap = hr_14d - hr_7d
            if gap >= FRONT_LOAD_HR_GAP:
                gap_str = f' [FRONT-LOAD GAP: {gap:.1f}pp]'
        print(f"  {m['model_id']}: {hr_7d}% HR 7d / {hr_14d}% HR 14d "
              f"(N={m.get('rolling_n_7d')}), state={m.get('state')}, "
              f"action={m.get('action')}{gap_str}")

    if models:
        game_date = models[0].get('game_date')
        if game_date:
            front_loaded, _ = detect_front_loading(str(game_date))
            if front_loaded:
                print(f"\nFront-loaded models ({len(front_loaded)}):")
                for fl in front_loaded:
                    print(f"  {fl['model_id']}: 7d {fl['hr_7d']:.1f}% vs 14d {fl['hr_14d']:.1f}% "
                          f"(gap: {fl['gap']}pp for {fl['consecutive_days']} consecutive days)")
            else:
                print("\nNo front-loading detected.")

            # Best bets HR (Sessions 389-390)
            bb_stats = get_aggregate_best_bets_hr(str(game_date))
            if bb_stats:
                hr = bb_stats['hr_21d']
                bb_state = classify_bb_state(hr)
                over_str = f"{bb_stats['over_hr_21d']:.1f}% (N={bb_stats['over_n']})" if bb_stats.get('over_hr_21d') else 'N/A'
                under_str = f"{bb_stats['under_hr_21d']:.1f}% (N={bb_stats['under_n']})" if bb_stats.get('under_hr_21d') else 'N/A'
                print(f"\nBest Bets HR (21d): {hr:.1f}% [{bb_state}] "
                      f"({bb_stats['wins']}W-{bb_stats['losses']}L, N={bb_stats['total']})")
                print(f"  OVER: {over_str} | UNDER: {under_str}")
            else:
                print("\nNo best bets HR data available.")

            # Short-window HR (Session 390)
            short_stats = get_best_bets_hr_short_window(str(game_date))
            if short_stats:
                short_status = 'CRITICAL' if short_stats['hr'] < BB_HR_SHORT_CRITICAL else 'OK'
                print(f"Best Bets HR ({BB_HR_SHORT_WINDOW_DAYS}d): {short_stats['hr']:.1f}% [{short_status}] "
                      f"({short_stats['wins']}W-{short_stats['losses']}L, N={short_stats['total']})")

            # Pick volume (Session 390)
            volume_payload = check_pick_volume_anomaly(game_date)
            if volume_payload:
                print("\nPick volume anomaly detected!")
            else:
                print("\nPick volume normal.")
