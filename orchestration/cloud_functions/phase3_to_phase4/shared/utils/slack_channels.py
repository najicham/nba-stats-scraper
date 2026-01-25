"""
Slack Channel Utilities

Provides direct Slack posting to specific channels for specialized alerts.
Complements the notification_system.py which routes by severity level.

Channel Mapping (6 channels):
- #daily-orchestration: Daily health, stale cleanup, phase timeouts (primary orchestration channel)
- #nba-pipeline-health: Backfill progress (INFO level) - legacy
- #nba-predictions: Prediction completion (special channel)
- #nba-alerts: Stalls, quality issues, stale data (WARNING level)
- #app-error-alerts: Processor failures, critical issues (ERROR/CRITICAL level)
- #gap-monitoring: Gap detection alerts (existing, unchanged)

Environment Variables:
- SLACK_WEBHOOK_URL: #daily-orchestration (primary - used by Cloud Functions)
- SLACK_WEBHOOK_URL_INFO: #nba-pipeline-health (legacy)
- SLACK_WEBHOOK_URL_PREDICTIONS: #nba-predictions
- SLACK_WEBHOOK_URL_WARNING: #nba-alerts
- SLACK_WEBHOOK_URL_ERROR: #app-error-alerts
- SLACK_WEBHOOK_URL_CRITICAL: #app-error-alerts

Webhook URLs (updated 2026-01-12):
- #daily-orchestration: https://hooks.slack.com/services/T0900NBTAET/B0A85Q6BB45/...
- #nba-pipeline-health: https://hooks.slack.com/services/T0900NBTAET/B0A0JN42AF7/... (legacy)
- #nba-predictions: https://hooks.slack.com/services/T0900NBTAET/B0A11329F1P/...
- #nba-alerts: https://hooks.slack.com/services/T0900NBTAET/B0A0FPJUVK5/...
- #app-error-alerts: https://hooks.slack.com/services/T0900NBTAET/B09HHJXMN8M/...
- #gap-monitoring: https://hooks.slack.com/services/T0900NBTAET/B09JTE8TUR2/...

Version: 1.3
Created: 2025-11-30
Updated: 2026-01-12 - Added #daily-orchestration as primary channel
Updated: 2026-01-25 - Unified on send_slack_webhook_with_retry for all calls
"""

import logging
import os
from typing import Dict, List, Optional

from shared.utils.slack_retry import send_slack_webhook_with_retry

logger = logging.getLogger(__name__)


def send_to_slack(
    webhook_url: str,
    text: str,
    blocks: Optional[List[Dict]] = None,
    username: str = "NBA Pipeline",
    icon_emoji: str = ":basketball:"
) -> bool:
    """
    Send message to Slack webhook with automatic retry logic.

    Uses send_slack_webhook_with_retry internally for reliability.
    Retries up to 3 times with exponential backoff on transient failures.

    Args:
        webhook_url: Slack webhook URL
        text: Fallback text (shown in notifications)
        blocks: Optional rich formatting blocks
        username: Bot username
        icon_emoji: Bot icon

    Returns:
        True if sent successfully
    """
    if not webhook_url:
        logger.warning("No webhook URL provided")
        return False

    payload = {
        "text": text,
        "username": username,
        "icon_emoji": icon_emoji
    }

    if blocks:
        payload["blocks"] = blocks

    return send_slack_webhook_with_retry(webhook_url, payload)


def send_prediction_summary_to_slack(prediction_data: Dict) -> bool:
    """
    Send prediction completion summary to #nba-predictions channel.

    Args:
        prediction_data: Same dict used for email

    Returns:
        True if sent successfully
    """
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL_PREDICTIONS')
    if not webhook_url:
        logger.debug("SLACK_WEBHOOK_URL_PREDICTIONS not set, skipping Slack notification")
        return False

    date_str = prediction_data.get('date', 'Unknown')
    predicted = prediction_data.get('players_predicted', 0)
    total = prediction_data.get('players_total', 0)
    games = prediction_data.get('games_count', 0)
    duration = prediction_data.get('duration_minutes', 0)

    # Build confidence stats
    conf = prediction_data.get('confidence_distribution', {})
    high = conf.get('high', 0)
    medium = conf.get('medium', 0)
    low = conf.get('low', 0)

    # Build top recommendations text
    recs = prediction_data.get('top_recommendations', [])
    recs_text = ""
    if recs:
        recs_lines = []
        for r in recs[:3]:
            recs_lines.append(f"• {r.get('player')}: {r.get('recommendation')} {r.get('line')} pts ({r.get('confidence')}%)")
        recs_text = "\n".join(recs_lines)

    # Build failed players text
    failed = prediction_data.get('failed_players', [])
    failed_text = f"\n\n⚠️ Failed: {len(failed)}" if failed else ""

    # Status emoji
    success_rate = (predicted / total * 100) if total > 0 else 0
    status_emoji = "✅" if success_rate >= 95 else "⚠️" if success_rate >= 80 else "❌"

    text = f"""🏀 *Predictions Ready - {date_str}*

{status_emoji} *{predicted}/{total}* players predicted ({games} games)
⏱️ Duration: {duration} minutes

*Confidence:*
• High (>80%): {high}
• Medium (50-80%): {medium}
• Low (<50%): {low}
{f'''
*Top Picks:*
{recs_text}''' if recs_text else ''}{failed_text}"""

    return send_to_slack(webhook_url, text)


def send_health_summary_to_slack(health_data: Dict) -> bool:
    """
    Send pipeline health summary to #nba-pipeline-health channel.

    Args:
        health_data: Same dict used for email

    Returns:
        True if sent successfully
    """
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL_INFO')
    if not webhook_url:
        logger.debug("SLACK_WEBHOOK_URL_INFO not set, skipping Slack notification")
        return False

    date_str = health_data.get('date', 'Unknown')
    phases = health_data.get('phases', {})
    quality = health_data.get('data_quality', 'UNKNOWN')
    duration = health_data.get('total_duration_minutes', 0)
    gaps = health_data.get('gaps_detected', 0)

    # Build phase status lines
    phase_lines = []
    for phase_name, info in phases.items():
        complete = info.get('complete', 0)
        total = info.get('total', 0)
        status = info.get('status', 'unknown')
        emoji = "✅" if status == 'success' else "⚠️" if status == 'partial' else "❌"
        phase_lines.append(f"{emoji} {phase_name}: {complete}/{total}")

    phases_text = "\n".join(phase_lines)

    # Quality emoji
    quality_emoji = "🥇" if quality == "GOLD" else "🥈" if quality == "SILVER" else "🥉"

    text = f"""✅ *Pipeline Health - {date_str}*

{phases_text}

{quality_emoji} Quality: *{quality}*
⏱️ Duration: {duration} minutes
{'⚠️ Gaps: ' + str(gaps) if gaps > 0 else '✅ No gaps detected'}"""

    return send_to_slack(webhook_url, text)


def send_stall_alert_to_slack(stall_data: Dict) -> bool:
    """
    Send stall alert to #nba-alerts channel.

    Args:
        stall_data: Same dict used for email

    Returns:
        True if sent successfully
    """
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL_WARNING')
    if not webhook_url:
        logger.debug("SLACK_WEBHOOK_URL_WARNING not set, skipping Slack notification")
        return False

    waiting = stall_data.get('waiting_phase', 'Unknown')
    blocked_by = stall_data.get('blocked_by_phase', 'Unknown')
    wait_mins = stall_data.get('wait_minutes', 0)
    completed = stall_data.get('completed_count', 0)
    total = stall_data.get('total_count', 0)
    missing = stall_data.get('missing_processors', [])

    missing_text = "\n".join([f"• {p}" for p in missing[:5]])
    if len(missing) > 5:
        missing_text += f"\n• ...and {len(missing) - 5} more"

    text = f"""⏳ *Pipeline Stall Detected*

*{waiting}* waiting *{wait_mins} minutes* for *{blocked_by}*

Status: {completed}/{total} processors complete

*Missing:*
{missing_text}

_Check Cloud Run logs for the missing processors_"""

    return send_to_slack(webhook_url, text, icon_emoji=":warning:")


def test_all_channels() -> Dict[str, bool]:
    """
    Send test messages to all configured channels.

    Returns:
        Dict mapping channel name to success status
    """
    results = {}

    # Test #nba-pipeline-health
    webhook = os.environ.get('SLACK_WEBHOOK_URL_INFO')
    if webhook:
        results['#nba-pipeline-health'] = send_to_slack(
            webhook,
            "✅ Test message to #nba-pipeline-health\n\nThis channel receives daily health summaries and backfill progress."
        )
    else:
        results['#nba-pipeline-health'] = False

    # Test #nba-predictions
    webhook = os.environ.get('SLACK_WEBHOOK_URL_PREDICTIONS')
    if webhook:
        results['#nba-predictions'] = send_to_slack(
            webhook,
            "🏀 Test message to #nba-predictions\n\nThis channel receives daily prediction completion notifications."
        )
    else:
        results['#nba-predictions'] = False

    # Test #nba-alerts
    webhook = os.environ.get('SLACK_WEBHOOK_URL_WARNING')
    if webhook:
        results['#nba-alerts'] = send_to_slack(
            webhook,
            "⚠️ Test message to #nba-alerts\n\nThis channel receives stalls, quality issues, and errors.",
            icon_emoji=":warning:"
        )
    else:
        results['#nba-alerts'] = False

    return results
