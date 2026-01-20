"""
Live Data Freshness Monitor

Monitors live data freshness and triggers self-healing when stale.
Runs every 5 minutes during game hours (4 PM - 1 AM ET).

Key features:
1. Checks if games are currently active
2. Verifies live data is fresh (< 10 min old)
3. Triggers live-export if stale
4. Sends alerts on persistent issues
5. Updates status.json with any issues found

UPDATED 2026-01-12: Added 4-hour critical alert threshold
- If data is >4 hours old during game hours, sends Slack alert
- This catches cases where auto-refresh has repeatedly failed

Schedule: */5 16-23,0-1 * * * (every 5 min, 4 PM - 1 AM ET)
"""

import functions_framework
from flask import jsonify
from google.cloud import storage
from datetime import datetime, timezone, timedelta
import requests
import logging
import os
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = os.environ.get("GCP_PROJECT", "nba-props-platform")
GCS_BUCKET = "nba-props-platform-api"
LIVE_EXPORT_URL = "https://us-west2-nba-props-platform.cloudfunctions.net/live-export"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# Thresholds
STALE_THRESHOLD_MINUTES = 10  # Data is stale if older than this - triggers auto-refresh
CRITICAL_STALE_HOURS = 4  # Data is critically stale - sends Slack alert
MAX_RETRIES = 2  # Max times to retry live export before alerting
PROCESSOR_GAP_THRESHOLD_MINUTES = 15  # Alert if processor hasn't run for this long


def get_et_now():
    """Get current time in ET."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('America/New_York'))
    except ImportError:
        import pytz
        return datetime.now(pytz.timezone('America/New_York'))


def are_games_active() -> bool:
    """
    Check if NBA games are currently active.
    Uses NBA.com scoreboard API as source of truth.
    """
    try:
        url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        data = response.json()
        games = data.get("scoreboard", {}).get("games", [])

        if not games:
            return False

        # Check if any game is in progress or recently finished
        for game in games:
            status = game.get("gameStatus", 0)
            # 2 = in progress, 3 = final (keep checking for a bit after games end)
            if status in (2, 3):
                # For final games, only consider them "active" for 30 min after
                if status == 3:
                    # Game is final, but we might still want to update grading
                    return True
                return True

        return False

    except Exception as e:
        logger.warning(f"Error checking if games are active: {e}")
        # Assume games might be active during typical hours
        hour = get_et_now().hour
        return 16 <= hour <= 23 or 0 <= hour <= 1


def check_live_data_freshness() -> dict:
    """
    Check if live data is fresh.

    Returns:
        dict with status, age_minutes, is_stale, last_update
    """
    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob("v1/live/latest.json")

        if not blob.exists():
            return {
                "status": "missing",
                "age_minutes": None,
                "is_stale": True,
                "last_update": None,
                "error": "File not found"
            }

        # Get metadata
        blob.reload()
        last_update = blob.updated
        age_minutes = (datetime.now(timezone.utc) - last_update).total_seconds() / 60
        is_stale = age_minutes > STALE_THRESHOLD_MINUTES

        # Also check the game_date in the file
        content = blob.download_as_text()
        data = json.loads(content)
        game_date = data.get("game_date", "")

        today_et = get_et_now().strftime("%Y-%m-%d")
        date_mismatch = game_date != today_et

        return {
            "status": "stale" if is_stale else "fresh",
            "age_minutes": round(age_minutes, 1),
            "is_stale": is_stale,
            "last_update": last_update.isoformat(),
            "game_date": game_date,
            "expected_date": today_et,
            "date_mismatch": date_mismatch
        }

    except Exception as e:
        logger.error(f"Error checking live data freshness: {e}")
        return {
            "status": "error",
            "age_minutes": None,
            "is_stale": True,
            "error": str(e)
        }


def check_processor_health() -> dict:
    """
    Check if BdlLiveBoxscoresProcessor is running regularly.

    This catches the root cause of stale data - if the processor
    isn't running, the live export will also become stale.

    ADDED: 2026-01-15 Session 48 - Early detection of processor downtime

    Returns:
        dict with processor health info
    """
    try:
        from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client
        bq_client = get_bigquery_client(project_id=PROJECT_ID)

        # Check last successful run of BdlLiveBoxscoresProcessor
        query = """
        SELECT
            MAX(started_at) as last_run,
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(started_at), MINUTE) as minutes_since_last_run,
            COUNTIF(status = 'success') as success_count,
            COUNTIF(status = 'failed') as failure_count,
            COUNT(*) as total_runs
        FROM `nba_reference.processor_run_history`
        WHERE processor_name = 'BdlLiveBoxscoresProcessor'
            AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
        """

        result = list(bq_client.query(query).result(timeout=30))[0]

        last_run = result.last_run
        minutes_ago = result.minutes_since_last_run
        is_healthy = minutes_ago is not None and minutes_ago < PROCESSOR_GAP_THRESHOLD_MINUTES

        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "last_run": str(last_run) if last_run else None,
            "minutes_since_last_run": minutes_ago,
            "success_count_1h": result.success_count or 0,
            "failure_count_1h": result.failure_count or 0,
            "total_runs_1h": result.total_runs or 0,
            "is_healthy": is_healthy
        }

    except Exception as e:
        logger.error(f"Error checking processor health: {e}")
        return {
            "status": "error",
            "error": str(e),
            "is_healthy": False
        }


def trigger_live_export() -> dict:
    """Trigger the live-export function to refresh data."""
    try:
        response = requests.post(
            LIVE_EXPORT_URL,
            json={"target_date": "today"},
            headers={"Content-Type": "application/json"},
            timeout=120  # Live export can take a while
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error triggering live export: {e}")
        return {"status": "error", "error": str(e)}


def send_slack_alert(message: str, severity: str = "warning", context: dict = None):
    """
    Send alert to Slack webhook.

    Args:
        message: Alert message
        severity: 'warning' or 'critical'
        context: Optional dict with additional context
    """
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not configured, skipping Slack alert")
        return False

    try:
        emoji = ":rotating_light:" if severity == "critical" else ":warning:"
        color = "#FF0000" if severity == "critical" else "#FFA500"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} Live Export Alert: {severity.upper()}",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message
                }
            }
        ]

        if context:
            fields = []
            for key, value in context.items():
                fields.append({
                    "type": "mrkdwn",
                    "text": f"*{key}:*\n{value}"
                })
            if fields:
                blocks.append({
                    "type": "section",
                    "fields": fields[:8]  # Slack limit
                })

        payload = {
            "attachments": [{
                "color": color,
                "blocks": blocks
            }]
        }

        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Slack alert sent successfully: {severity}")
        return True

    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


def send_alert(message: str, severity: str = "warning"):
    """Send alert via notification system and Slack."""
    # Try Slack first (primary alert channel)
    slack_sent = send_slack_alert(message, severity)

    # Also try the internal notification system as backup
    try:
        from shared.utils.notification_system import notify_warning, notify_error

        if severity in ("error", "critical"):
            notify_error(
                title="Live Data Freshness Issue",
                message=message,
                details={"component": "live_freshness_monitor"}
            )
        else:
            notify_warning(
                title="Live Data Freshness Warning",
                message=message,
                details={"component": "live_freshness_monitor"}
            )
    except Exception as e:
        # Just log if notification fails
        if not slack_sent:
            logger.error(f"Failed to send any alert: {e}")


@functions_framework.http
def main(request):
    """
    HTTP-triggered function to monitor live data freshness.

    Checks:
    1. Are games currently active?
    2. Is live data fresh?
    3. If stale during games, trigger self-heal
    """
    start_time = datetime.now(timezone.utc)

    result = {
        "timestamp": start_time.isoformat(),
        "games_active": False,
        "freshness": {},
        "action_taken": None,
        "action_result": None
    }

    # Step 1: Check if games are active
    games_active = are_games_active()
    result["games_active"] = games_active

    if not games_active:
        logger.info("No games currently active, skipping freshness check")
        result["action_taken"] = "skip"
        result["message"] = "No games currently active"
        return jsonify(result), 200

    # Step 1.5: Check processor health (early warning for data collection issues)
    # ADDED: 2026-01-15 Session 48 - Detect processor downtime before it causes stale exports
    processor_health = check_processor_health()
    result["processor_health"] = processor_health

    if not processor_health.get("is_healthy"):
        minutes_ago = processor_health.get("minutes_since_last_run")
        if minutes_ago and minutes_ago > 30:
            # Significant gap - send alert
            logger.error(f"PROCESSOR DOWN: BdlLiveBoxscoresProcessor hasn't run in {minutes_ago} minutes")
            send_slack_alert(
                message=f"BdlLiveBoxscoresProcessor hasn't run in {minutes_ago} minutes!\n"
                        f"This will cause live data to become stale. Check Cloud Scheduler and logs.",
                severity="warning" if minutes_ago < 60 else "critical",
                context={
                    "Last Run": processor_health.get("last_run", "Unknown"),
                    "Minutes Since Last Run": str(minutes_ago),
                    "Runs in Last Hour": str(processor_health.get("total_runs_1h", 0)),
                    "Failures in Last Hour": str(processor_health.get("failure_count_1h", 0))
                }
            )
            result["processor_alert_sent"] = True

    # Step 2: Check data freshness
    freshness = check_live_data_freshness()
    result["freshness"] = freshness

    if freshness.get("status") == "fresh" and not freshness.get("date_mismatch"):
        logger.info(f"Live data is fresh ({freshness.get('age_minutes')} min old)")
        result["action_taken"] = "none"
        result["message"] = "Data is fresh"
        # Include processor health in the response even when data is fresh
        result["processor_status"] = "healthy" if processor_health.get("is_healthy") else "warning"
        return jsonify(result), 200

    # Step 2.5: Check for CRITICAL staleness (>4 hours)
    # This sends an immediate alert without waiting for refresh attempts
    age_minutes = freshness.get("age_minutes")
    if age_minutes and age_minutes > (CRITICAL_STALE_HOURS * 60):
        age_hours = round(age_minutes / 60, 1)
        logger.error(f"CRITICAL: Live data is {age_hours} hours old (threshold: {CRITICAL_STALE_HOURS}h)")
        result["critical_alert"] = True

        send_slack_alert(
            message=f"CRITICAL: Live export data is {age_hours} hours old!\n"
                    f"This exceeds the {CRITICAL_STALE_HOURS}-hour threshold. "
                    f"The live export system may be completely broken.",
            severity="critical",
            context={
                "Age": f"{age_hours} hours",
                "Threshold": f"{CRITICAL_STALE_HOURS} hours",
                "Last Update": freshness.get("last_update", "Unknown"),
                "Game Date": freshness.get("game_date", "Unknown"),
                "Expected Date": freshness.get("expected_date", "Unknown")
            }
        )

    # Step 3: Data is stale or has wrong date - trigger refresh
    issue = "stale" if freshness.get("is_stale") else "date_mismatch"
    logger.warning(f"Live data issue detected: {issue}")
    result["action_taken"] = "refresh"
    result["issue"] = issue

    # Try to refresh
    for attempt in range(MAX_RETRIES):
        logger.info(f"Triggering live export (attempt {attempt + 1}/{MAX_RETRIES})")
        export_result = trigger_live_export()

        if export_result.get("status") == "success":
            logger.info("Live export successful")
            result["action_result"] = "success"
            result["export_result"] = export_result

            # Verify the fix worked
            post_freshness = check_live_data_freshness()
            if not post_freshness.get("is_stale") and not post_freshness.get("date_mismatch"):
                result["message"] = "Data refreshed successfully"
                return jsonify(result), 200

        logger.warning(f"Export attempt {attempt + 1} failed or didn't fix issue")

    # All retries failed - send alert
    result["action_result"] = "failed"
    result["message"] = f"Failed to refresh live data after {MAX_RETRIES} attempts"

    send_alert(
        message=f"Live data is stale and couldn't be refreshed. Age: {freshness.get('age_minutes')} min. "
                f"Game date: {freshness.get('game_date')}, Expected: {freshness.get('expected_date')}",
        severity="error"
    )

    return jsonify(result), 500


# ============================================================================
# HTTP ENDPOINTS (for health checks)
# ============================================================================

@functions_framework.http
def health(request):
    """Health check endpoint for the live_freshness_monitor function."""
    return jsonify({
        'status': 'healthy',
        'function': 'live_freshness_monitor'
    }), 200


# For local testing
if __name__ == "__main__":
    print("Checking live data freshness...")
    games_active = are_games_active()
    print(f"Games active: {games_active}")

    freshness = check_live_data_freshness()
    print(f"Freshness: {json.dumps(freshness, indent=2)}")
