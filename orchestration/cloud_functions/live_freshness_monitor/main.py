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
PROJECT_ID = os.environ.get("GCP_PROJECT_ID") or os.environ.get("GCP_PROJECT", "nba-props-platform")
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
        logger.error(f"Error checking live data freshness: {e}", exc_info=True)
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
        bq_client = bigquery.Client(project=PROJECT_ID)

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
        logger.error(f"Error checking processor health: {e}", exc_info=True)
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
        logger.error(f"Error triggering live export: {e}", exc_info=True)
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
        logger.error(f"Failed to send Slack alert: {e}", exc_info=True)
        return False


def check_live_grading_freshness() -> dict:
    """
    Check live-grading JSON content quality (not just file freshness).

    Detects silent failures where the file is updated every 3 min but contains
    stale/useless data (e.g., all predictions pending, all games scheduled,
    zero score sources). This catches the Feb 22 scenario where BDL_API_KEY
    was wiped and live-grading regenerated stale data for hours.

    Returns:
        dict with content_quality, details, and diagnostics
    """
    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob("v1/live-grading/latest.json")

        if not blob.exists():
            return {
                "content_quality": "missing",
                "details": "live-grading/latest.json not found"
            }

        content = blob.download_as_text()
        data = json.loads(content)

        predictions = data.get("predictions", [])
        game_date = data.get("game_date", "")
        total = len(predictions)

        if total == 0:
            return {
                "content_quality": "empty",
                "details": "Zero predictions in file",
                "game_date": game_date
            }

        # Count diagnostic signals
        pending_count = sum(
            1 for p in predictions
            if p.get("grade") in (None, "pending", "PENDING")
        )
        scheduled_count = sum(
            1 for p in predictions
            if p.get("game_status") in (None, 1, "1", "Scheduled")
        )
        null_actual_count = sum(
            1 for p in predictions
            if p.get("actual") is None and p.get("actual_points") is None
        )
        null_source_count = sum(
            1 for p in predictions
            if not p.get("score_source") and not p.get("actual_source")
        )

        pct_pending = pending_count / total * 100
        pct_scheduled = scheduled_count / total * 100
        pct_null_actual = null_actual_count / total * 100
        pct_null_source = null_source_count / total * 100

        diagnostics = {
            "game_date": game_date,
            "total_predictions": total,
            "pending_count": pending_count,
            "pct_pending": round(pct_pending, 1),
            "scheduled_count": scheduled_count,
            "pct_scheduled": round(pct_scheduled, 1),
            "null_actual_count": null_actual_count,
            "pct_null_actual": round(pct_null_actual, 1),
            "null_source_count": null_source_count,
            "pct_null_source": round(pct_null_source, 1),
        }

        # Determine content quality
        # If games are active/final but everything is still pending with no actuals,
        # the live-grading system is broken (likely missing BDL_API_KEY)
        if pct_pending == 100 and pct_null_actual == 100:
            return {
                "content_quality": "stale_content",
                "details": "ALL predictions pending with zero actuals — live scoring likely broken (check BDL_API_KEY)",
                **diagnostics
            }

        if pct_scheduled == 100 and pct_null_source == 100:
            return {
                "content_quality": "stale_content",
                "details": "ALL games showing scheduled with no score sources — BDL data not flowing",
                **diagnostics
            }

        if pct_null_source > 80:
            return {
                "content_quality": "degraded",
                "details": f"{pct_null_source:.0f}% of predictions have no score source",
                **diagnostics
            }

        return {
            "content_quality": "healthy",
            "details": f"{total - pending_count}/{total} predictions graded",
            **diagnostics
        }

    except Exception as e:
        logger.error(f"Error checking live grading freshness: {e}", exc_info=True)
        return {
            "content_quality": "error",
            "details": str(e)
        }


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
        "grading_freshness": {},
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
            logger.error(f"PROCESSOR DOWN: BdlLiveBoxscoresProcessor hasn't run in {minutes_ago} minutes", exc_info=True)
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

    # Step 1.75: Check live-grading content quality (catches silent data failures)
    # ADDED: 2026-02-22 Session 302 - BDL_API_KEY wipe caused stale-content loop
    grading_freshness = check_live_grading_freshness()
    result["grading_freshness"] = grading_freshness

    if grading_freshness.get("content_quality") == "stale_content":
        logger.error(f"STALE CONTENT: {grading_freshness.get('details')}")
        send_slack_alert(
            message=f"Live-grading content is STALE despite file updates!\n"
                    f"{grading_freshness.get('details')}\n\n"
                    f"This usually means BDL_API_KEY is missing from live-export.",
            severity="critical",
            context={
                "Game Date": grading_freshness.get("game_date", "Unknown"),
                "Total Predictions": str(grading_freshness.get("total_predictions", 0)),
                "Pending": f"{grading_freshness.get('pct_pending', '?')}%",
                "Null Actuals": f"{grading_freshness.get('pct_null_actual', '?')}%",
                "Null Sources": f"{grading_freshness.get('pct_null_source', '?')}%",
            }
        )
        result["grading_content_alert_sent"] = True
    elif grading_freshness.get("content_quality") == "degraded":
        logger.warning(f"DEGRADED CONTENT: {grading_freshness.get('details')}")
        send_slack_alert(
            message=f"Live-grading content quality degraded: {grading_freshness.get('details')}",
            severity="warning",
            context={
                "Game Date": grading_freshness.get("game_date", "Unknown"),
                "Total Predictions": str(grading_freshness.get("total_predictions", 0)),
                "Null Sources": f"{grading_freshness.get('pct_null_source', '?')}%",
            }
        )

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
        logger.error(f"CRITICAL: Live data is {age_hours} hours old (threshold: {CRITICAL_STALE_HOURS}h)", exc_info=True)
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

    send_slack_alert(
        message=f"Live data is stale and couldn't be refreshed after {MAX_RETRIES} attempts.\n"
                f"Age: {freshness.get('age_minutes')} min. "
                f"Game date: {freshness.get('game_date')}, Expected: {freshness.get('expected_date')}",
        severity="critical",
        context={
            "Age (minutes)": str(freshness.get("age_minutes", "?")),
            "Game Date": freshness.get("game_date", "Unknown"),
            "Expected Date": freshness.get("expected_date", "Unknown"),
        }
    )

    # Always return 200: reporter, not gatekeeper. Findings are in the response body.
    return jsonify(result), 200


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
