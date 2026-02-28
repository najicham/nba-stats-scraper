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
"""

import functions_framework
import json
import logging
import os
from datetime import datetime, date, timezone
from flask import Request
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
