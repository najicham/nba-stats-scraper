"""
Cloud Function: Source Block Alert

Monitors source_blocked_resources table and sends Slack alerts when:
1. New source blocks are detected
2. Source blocks persist beyond threshold
3. Blocking patterns emerge (multiple games from same source)

Triggered: Scheduled (Cloud Scheduler) - runs every 6 hours
"""

import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any
import requests
from google.cloud import bigquery


def source_block_alert(request=None):
    """
    Main Cloud Function entry point.

    Checks for source blocks and sends Slack alerts.
    """
    try:
        client = bigquery.Client()

        # Check for new blocks (last 6 hours)
        new_blocks = check_new_blocks(client)

        # Check for persistent blocks (>24 hours)
        persistent_blocks = check_persistent_blocks(client)

        # Check for blocking patterns
        patterns = check_blocking_patterns(client)

        # Send alerts if issues found
        if new_blocks or persistent_blocks or patterns:
            send_slack_alert(new_blocks, persistent_blocks, patterns)
            return {'status': 'alerts_sent', 'new_blocks': len(new_blocks),
                   'persistent': len(persistent_blocks), 'patterns': len(patterns)}

        return {'status': 'ok', 'message': 'No source blocks detected'}

    except Exception as e:
        error_msg = f"Source block alert failed: {str(e)}"
        send_error_alert(error_msg)
        return {'status': 'error', 'message': error_msg}, 500


def check_new_blocks(client: bigquery.Client) -> List[Dict[str, Any]]:
    """Check for source blocks detected in last 6 hours."""

    query = """
    SELECT
        resource_id,
        resource_type,
        source_system,
        http_status_code,
        game_date,
        first_detected_at,
        notes
    FROM `nba-props-platform.nba_orchestration.source_blocked_resources`
    WHERE first_detected_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR)
      AND is_resolved = FALSE
    ORDER BY first_detected_at DESC
    """

    results = client.query(query).result()
    return [dict(row) for row in results]


def check_persistent_blocks(client: bigquery.Client) -> List[Dict[str, Any]]:
    """Check for blocks persisting >24 hours."""

    query = """
    SELECT
        resource_id,
        resource_type,
        source_system,
        http_status_code,
        game_date,
        first_detected_at,
        verification_count,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), first_detected_at, HOUR) as hours_blocked
    FROM `nba-props-platform.nba_orchestration.source_blocked_resources`
    WHERE is_resolved = FALSE
      AND first_detected_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
    ORDER BY first_detected_at ASC
    """

    results = client.query(query).result()
    return [dict(row) for row in results]


def check_blocking_patterns(client: bigquery.Client) -> List[Dict[str, Any]]:
    """Check for concerning patterns (multiple blocks from same source/date)."""

    query = """
    SELECT
        source_system,
        game_date,
        resource_type,
        COUNT(*) as blocked_count,
        STRING_AGG(resource_id, ', ' ORDER BY resource_id) as blocked_resources
    FROM `nba-props-platform.nba_orchestration.source_blocked_resources`
    WHERE is_resolved = FALSE
      AND game_date >= CURRENT_DATE() - 7
    GROUP BY source_system, game_date, resource_type
    HAVING COUNT(*) >= 2  -- 2+ blocks = pattern
    ORDER BY blocked_count DESC, game_date DESC
    """

    results = client.query(query).result()
    return [dict(row) for row in results]


def send_slack_alert(new_blocks: List[Dict], persistent_blocks: List[Dict],
                     patterns: List[Dict]):
    """Send formatted Slack alert with source block details."""

    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if not webhook_url:
        print("WARNING: SLACK_WEBHOOK_URL not set, skipping Slack notification")
        return

    # Build message
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "⚠️ Source Block Alert",
                "emoji": True
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}"
                }
            ]
        },
        {"type": "divider"}
    ]

    # New blocks section
    if new_blocks:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🆕 New Source Blocks ({len(new_blocks)}):*"
            }
        })

        for block in new_blocks[:5]:  # Limit to 5 most recent
            game_date = block['game_date'].strftime('%Y-%m-%d') if hasattr(block['game_date'], 'strftime') else str(block['game_date'])
            blocks.append({
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Resource:* `{block['resource_id']}`"},
                    {"type": "mrkdwn", "text": f"*Type:* {block['resource_type']}"},
                    {"type": "mrkdwn", "text": f"*Source:* {block['source_system']}"},
                    {"type": "mrkdwn", "text": f"*HTTP:* {block['http_status_code']}"},
                    {"type": "mrkdwn", "text": f"*Game Date:* {game_date}"},
                    {"type": "mrkdwn", "text": f"*Notes:* {block.get('notes', 'N/A')}"}
                ]
            })

        if len(new_blocks) > 5:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_...and {len(new_blocks) - 5} more_"}]
            })

        blocks.append({"type": "divider"})

    # Persistent blocks section
    if persistent_blocks:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*⏰ Persistent Blocks >24h ({len(persistent_blocks)}):*"
            }
        })

        for block in persistent_blocks[:3]:  # Top 3 oldest
            game_date = block['game_date'].strftime('%Y-%m-%d') if hasattr(block['game_date'], 'strftime') else str(block['game_date'])
            blocks.append({
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Resource:* `{block['resource_id']}`"},
                    {"type": "mrkdwn", "text": f"*Hours Blocked:* {int(block['hours_blocked'])}h"},
                    {"type": "mrkdwn", "text": f"*Source:* {block['source_system']}"},
                    {"type": "mrkdwn", "text": f"*Verifications:* {block['verification_count']}"}
                ]
            })

        blocks.append({"type": "divider"})

    # Patterns section
    if patterns:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*📊 Blocking Patterns ({len(patterns)}):*"
            }
        })

        for pattern in patterns[:3]:  # Top 3 patterns
            game_date = pattern['game_date'].strftime('%Y-%m-%d') if hasattr(pattern['game_date'], 'strftime') else str(pattern['game_date'])
            blocks.append({
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Source:* {pattern['source_system']}"},
                    {"type": "mrkdwn", "text": f"*Date:* {game_date}"},
                    {"type": "mrkdwn", "text": f"*Type:* {pattern['resource_type']}"},
                    {"type": "mrkdwn", "text": f"*Count:* {pattern['blocked_count']} blocked"},
                    {"type": "mrkdwn", "text": f"*Resources:* {pattern['blocked_resources'][:100]}..."}
                ]
            })

    # Footer with actions
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "*Next Steps:*\n• Check admin dashboard for details\n• Verify if data available from alternative sources\n• Mark as resolved if blocks clear"
        }
    })

    # Send to Slack
    payload = {
        "blocks": blocks,
        "text": f"Source Block Alert: {len(new_blocks)} new, {len(persistent_blocks)} persistent"
    }

    response = requests.post(webhook_url, json=payload, timeout=10)
    response.raise_for_status()

    print(f"Slack alert sent: {len(new_blocks)} new blocks, {len(persistent_blocks)} persistent, {len(patterns)} patterns")


def send_error_alert(error_message: str):
    """Send error notification to Slack."""

    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if not webhook_url:
        print(f"ERROR (no webhook): {error_message}")
        return

    payload = {
        "text": f"❌ Source Block Alert Function Error",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Source Block Alert Failed*\n```{error_message}```"
                }
            }
        ]
    }

    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        print(f"Failed to send error alert: {e}")


# For local testing
if __name__ == '__main__':
    print("Testing source block alert...")
    result = source_block_alert()
    print(f"Result: {json.dumps(result, indent=2, default=str)}")
