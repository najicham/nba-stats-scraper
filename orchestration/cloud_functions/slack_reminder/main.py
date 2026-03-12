"""Reminder Forwarder — Sends scheduled reminders via Slack + Pushover.

Accepts a JSON POST body with a "message" field and forwards it to both
Slack and Pushover (phone push notification).

Used by MLB season reminders and any other scheduled alerts.

Env vars:
    SLACK_WEBHOOK_URL: Slack webhook URL for #nba-alerts channel
    PUSHOVER_USER_KEY: Pushover user key (from dashboard)
    PUSHOVER_APP_TOKEN: Pushover application API token

Created: Session 469 (2026-03-11)
"""

import json
import logging
import os
import urllib.parse
import urllib.request

import functions_framework

logger = logging.getLogger(__name__)


def _send_slack(webhook_url: str, source: str, message: str) -> bool:
    """Send message to Slack via webhook."""
    emoji = '\u26be' if 'mlb' in source.lower() else '\U0001f3c0' if 'nba' in source.lower() else '\U0001f4cb'
    slack_payload = {
        'text': f'{emoji} *Reminder* ({source})\n{message}',
        'unfurl_links': False,
    }
    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(slack_payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.error(f'Slack send failed: {e}')
        return False


def _send_pushover(user_key: str, app_token: str, source: str, message: str) -> bool:
    """Send push notification via Pushover API."""
    title = f'MLB Reminder' if 'mlb' in source.lower() else f'NBA Reminder' if 'nba' in source.lower() else 'Reminder'
    payload = urllib.parse.urlencode({
        'token': app_token,
        'user': user_key,
        'message': message,
        'title': title,
        'priority': 0,  # Normal priority with sound
    }).encode('utf-8')
    try:
        req = urllib.request.Request(
            'https://api.pushover.net/1/messages.json',
            data=payload,
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get('status') == 1
    except Exception as e:
        logger.error(f'Pushover send failed: {e}')
        return False


@functions_framework.http
def send_reminder(request):
    """Forward a reminder message to Slack and Pushover.

    Expected POST body:
        {"source": "mlb-reminder", "message": "Your reminder text here"}

    Returns 200 if at least one delivery succeeds.
    """
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}

    message = data.get('message', '')
    source = data.get('source', 'unknown')

    if not message:
        return 'No message provided', 400

    results = []

    # Send to Slack
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if webhook_url:
        ok = _send_slack(webhook_url, source, message)
        results.append(f'slack={"ok" if ok else "fail"}')
    else:
        results.append('slack=not_configured')

    # Send to Pushover (phone notification)
    pushover_user = os.environ.get('PUSHOVER_USER_KEY')
    pushover_token = os.environ.get('PUSHOVER_APP_TOKEN')
    if pushover_user and pushover_token:
        ok = _send_pushover(pushover_user, pushover_token, source, message)
        results.append(f'pushover={"ok" if ok else "fail"}')
    else:
        results.append('pushover=not_configured')

    any_ok = any('=ok' in r for r in results)
    status = 200 if any_ok else 500
    return f'{", ".join(results)} | {message[:80]}', status


# Cloud Function entry point alias (Gen2 immutable entry point workaround)
main = send_reminder
