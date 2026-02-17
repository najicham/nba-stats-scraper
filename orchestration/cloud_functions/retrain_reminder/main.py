"""Retrain Reminder Cloud Function — Per-Family Staleness Reporting.

Sends Slack + Pushover push notification reminders when model families are due for retraining.
Queries model_registry for per-family training age and model_performance_daily for current state.

Session 272: Initial implementation (single production model).
Session 273: Model Management Overhaul — per-family staleness reporting from model_registry.
    Reports all families that are >= 7 days old, not just the production champion.
Session 284: Switched to 7-day cadence (from 14-day). Replay proved +$7,670 P&L.
    Thresholds: 7d ROUTINE, 10d OVERDUE, 14d URGENT.

Triggered by Cloud Scheduler every Monday at 9 AM ET. Skips alert if ALL families
are < 7 days old (weekly with 7-day retrain cadence).

Urgency levels:
    ROUTINE (7-10 days old)  - Normal weekly reminder
    OVERDUE (11-14 days old) - Model aging, should retrain soon
    URGENT  (15+ days old)   - Stale model, likely losing money
"""

import functions_framework
import json
import logging
import os
from datetime import datetime, timezone
from flask import Request
from typing import Dict, List, Optional

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

# Model age thresholds (days) — Session 284: 7-day cadence
SKIP_THRESHOLD = 7        # Don't alert if model is newer than this
ROUTINE_MAX = 10          # 7-10 days = ROUTINE
OVERDUE_MAX = 14          # 11-14 days = OVERDUE
                          # 15+ days = URGENT


def get_stale_families() -> List[Dict]:
    """Query model_registry for per-family staleness.

    Returns list of dicts with family info for each family >= SKIP_THRESHOLD days old.
    """
    bq = _get_bq_client()

    query = f"""
    SELECT
      model_family,
      MAX(training_end_date) AS latest_training_end,
      DATE_DIFF(CURRENT_DATE(), MAX(training_end_date), DAY) AS days_since_training,
      COUNT(*) AS model_count
    FROM `{PROJECT_ID}.nba_predictions.model_registry`
    WHERE enabled = TRUE AND status IN ('active', 'production')
      AND model_family IS NOT NULL
    GROUP BY model_family
    HAVING days_since_training >= {SKIP_THRESHOLD}
    ORDER BY days_since_training DESC
    """

    results = list(bq.query(query).result())
    families = []
    for r in results:
        families.append({
            'model_family': r.model_family,
            'latest_training_end': str(r.latest_training_end),
            'days_since_training': r.days_since_training,
            'model_count': r.model_count,
        })
    return families


def get_production_model_info() -> Optional[Dict]:
    """Query model_registry for the current production model's training dates."""
    bq = _get_bq_client()

    query = f"""
    SELECT
      model_id,
      model_family,
      training_start_date,
      training_end_date,
      DATE_DIFF(CURRENT_DATE(), training_end_date, DAY) as days_since_training,
      production_start_date,
      gcs_path
    FROM `{PROJECT_ID}.nba_predictions.model_registry`
    WHERE is_production = TRUE AND model_version = 'v9'
    LIMIT 1
    """

    results = list(bq.query(query).result())
    if not results:
        return None
    return dict(results[0])


def get_model_performance(model_id: str) -> Optional[Dict]:
    """Query model_performance_daily for the latest performance data."""
    bq = _get_bq_client()

    query = f"""
    SELECT
      model_id,
      game_date,
      rolling_hr_7d,
      rolling_n_7d,
      rolling_hr_14d,
      rolling_n_14d,
      state
    FROM `{PROJECT_ID}.nba_predictions.model_performance_daily`
    WHERE game_date = (
      SELECT MAX(game_date)
      FROM `{PROJECT_ID}.nba_predictions.model_performance_daily`
    )
    AND model_id = '{model_id}'
    LIMIT 1
    """

    results = list(bq.query(query).result())
    if not results:
        return None
    return dict(results[0])


def determine_urgency(days_since_training: int) -> str:
    """Determine alert urgency based on model age."""
    if days_since_training <= ROUTINE_MAX:
        return 'ROUTINE'
    elif days_since_training <= OVERDUE_MAX:
        return 'OVERDUE'
    else:
        return 'URGENT'


def build_slack_payload(
    stale_families: List[Dict],
    prod_info: Optional[Dict],
    prod_perf: Optional[Dict],
    overall_urgency: str,
) -> Dict:
    """Build Slack alert payload with per-family staleness."""
    emoji_map = {
        'ROUTINE': ':arrows_counterclockwise:',
        'OVERDUE': ':warning:',
        'URGENT': ':rotating_light:',
    }
    color_map = {
        'ROUTINE': '#439FE0',
        'OVERDUE': '#FFA500',
        'URGENT': '#FF0000',
    }
    emoji = emoji_map.get(overall_urgency, ':arrows_counterclockwise:')
    color = color_map.get(overall_urgency, '#439FE0')

    # Build per-family lines
    family_lines = []
    for fam in stale_families:
        urgency = determine_urgency(fam['days_since_training'])
        family_lines.append(
            f"`{fam['model_family']:<20s}` {fam['days_since_training']}d old ({urgency}) "
            f"— `./bin/retrain.sh --family {fam['model_family']}`"
        )

    family_text = "\n".join(family_lines)

    # Champion info
    champion_text = ""
    if prod_info:
        hr_str = 'N/A'
        state_str = 'UNKNOWN'
        if prod_perf:
            hr = prod_perf.get('rolling_hr_7d')
            hr_str = f"{hr:.1f}%" if hr is not None else 'N/A'
            state_str = prod_perf.get('state', 'UNKNOWN')
        champion_text = (
            f"\n*Champion:* `{prod_info['model_id']}` | "
            f"HR: {hr_str} | State: {state_str}"
        )

    blocks = [
        {
            'type': 'header',
            'text': {
                'type': 'plain_text',
                'text': f'{emoji} MODEL RETRAIN REMINDER — {len(stale_families)} families stale',
                'emoji': True,
            }
        },
        {
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': family_text + champion_text,
            }
        },
        {
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': (
                    "Retrain all families:\n"
                    "```./bin/retrain.sh --all --promote```"
                )
            }
        },
        {
            'type': 'context',
            'elements': [{
                'type': 'mrkdwn',
                'text': (
                    f"Run: {datetime.now(timezone.utc).strftime('%H:%M UTC')} | "
                    f"Urgency: {overall_urgency} | "
                    f"7d cadence (Session 284) — replay proved +$7,670 P&L"
                )
            }]
        },
    ]

    return {
        'attachments': [{
            'color': color,
            'blocks': blocks
        }]
    }


def build_push_message(stale_families: List[Dict], overall_urgency: str) -> str:
    """Build concise push notification message."""
    prefix = 'RETRAIN'
    if overall_urgency == 'URGENT':
        prefix = 'RETRAIN URGENT'
    elif overall_urgency == 'OVERDUE':
        prefix = 'RETRAIN OVERDUE'

    family_summary = ", ".join(
        f"{f['model_family']}({f['days_since_training']}d)"
        for f in stale_families[:3]
    )
    if len(stale_families) > 3:
        family_summary += f" +{len(stale_families) - 3} more"

    return f"{prefix} {len(stale_families)} families: {family_summary}. Run: ./bin/retrain.sh --all"


def send_slack_alert(payload: Dict) -> bool:
    """Send alert to Slack."""
    if not SLACK_WEBHOOK_URL:
        logger.warning("No SLACK_WEBHOOK_URL_ALERTS configured, skipping Slack alert")
        return False

    try:
        from shared.utils.slack_retry import send_slack_webhook_with_retry
        return send_slack_webhook_with_retry(SLACK_WEBHOOK_URL, payload, timeout=10)
    except ImportError:
        import requests
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        return resp.status_code == 200


def send_push_alert(message: str, urgency: str) -> bool:
    """Send push notification via Pushover."""
    try:
        from shared.utils.pushover_notifier import PushoverNotifier
        notifier = PushoverNotifier()
        if not notifier.is_configured():
            logger.warning("Pushover not configured, skipping push notification")
            return False
        priority = 1 if urgency == 'URGENT' else 0
        return notifier.send(message, title="NBA Model Retrain", priority=priority)
    except ImportError:
        logger.warning("PushoverNotifier not available, skipping push notification")
        return False
    except Exception as e:
        logger.error(f"Push notification failed: {e}")
        return False


@functions_framework.http
def retrain_reminder(request: Request):
    """HTTP entry point for retrain reminder.

    Triggered by Cloud Scheduler weekly (Mondays 9 AM ET).
    Reports per-family staleness. Skips if ALL families < 10 days old.
    Always returns 200 (reporter pattern - Session 219).
    """
    logger.info("Starting retrain reminder check...")

    try:
        # Get stale families from model_registry
        stale_families = get_stale_families()

        if not stale_families:
            logger.info(f"All families fresh (< {SKIP_THRESHOLD}d), skipping alert")
            return json.dumps({
                'status': 'skipped',
                'reason': f'All families fresh (< {SKIP_THRESHOLD}d threshold)',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }), 200, {'Content-Type': 'application/json'}

        logger.info(f"Found {len(stale_families)} stale families")

        # Get production model info for champion context
        prod_info = get_production_model_info()
        prod_perf = None
        if prod_info:
            prod_perf = get_model_performance(prod_info['model_id'])

        # Overall urgency = worst among all stale families
        max_days = max(f['days_since_training'] for f in stale_families)
        overall_urgency = determine_urgency(max_days)

        logger.info(f"Overall urgency: {overall_urgency} (max {max_days}d)")

        # Send Slack alert
        slack_payload = build_slack_payload(stale_families, prod_info, prod_perf, overall_urgency)
        slack_sent = send_slack_alert(slack_payload)
        logger.info(f"Slack alert sent: {slack_sent}")

        # Send push notification
        push_message = build_push_message(stale_families, overall_urgency)
        push_sent = send_push_alert(push_message, overall_urgency)
        logger.info(f"Push notification sent: {push_sent}")

        return json.dumps({
            'status': 'success',
            'stale_families': len(stale_families),
            'families': [
                {'family': f['model_family'], 'days': f['days_since_training'],
                 'urgency': determine_urgency(f['days_since_training'])}
                for f in stale_families
            ],
            'overall_urgency': overall_urgency,
            'champion_model': prod_info['model_id'] if prod_info else None,
            'slack_sent': slack_sent,
            'push_sent': push_sent,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 200, {'Content-Type': 'application/json'}

    except Exception as e:
        logger.error(f"Error in retrain reminder: {e}", exc_info=True)
        return json.dumps({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 200, {'Content-Type': 'application/json'}


# Gen2 CRITICAL: Main alias (Session 219)
main = retrain_reminder


if __name__ == '__main__':
    """Local testing: python orchestration/cloud_functions/retrain_reminder/main.py"""
    import sys

    stale = get_stale_families()
    if not stale:
        print("All families fresh")
        sys.exit(0)

    prod_info = get_production_model_info()
    prod_perf = None
    if prod_info:
        prod_perf = get_model_performance(prod_info['model_id'])

    max_days = max(f['days_since_training'] for f in stale)
    urgency = determine_urgency(max_days)

    print(f"\n{len(stale)} stale families (urgency: {urgency}):")
    for f in stale:
        fam_urgency = determine_urgency(f['days_since_training'])
        print(f"  {f['model_family']:<20s} {f['days_since_training']}d old ({fam_urgency})")

    if prod_info:
        print(f"\nChampion: {prod_info['model_id']} ({prod_info.get('days_since_training', '?')}d)")
        if prod_perf:
            print(f"  7d HR: {prod_perf.get('rolling_hr_7d')}% (N={prod_perf.get('rolling_n_7d')})")
            print(f"  State: {prod_perf.get('state')}")

    print(f"\nPush: {build_push_message(stale, urgency)}")
