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

    if not has_transitions and not best_bets_unhealthy:
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

        # Build and send alert if needed
        payload = build_alert_payload(models, transitions, best_bets_model)
        alert_sent = False
        if payload:
            alert_sent = send_slack_alert(payload)
            logger.info(f"Alert sent: {alert_sent}, transitions: {len(transitions)}")
        else:
            logger.info("No alert needed — all models healthy, no transitions")

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
        print(f"  {m['model_id']}: {m.get('rolling_hr_7d')}% HR 7d "
              f"(N={m.get('rolling_n_7d')}), state={m.get('state')}, "
              f"action={m.get('action')}")
