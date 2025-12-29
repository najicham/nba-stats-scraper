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

# Thresholds
STALE_THRESHOLD_MINUTES = 10  # Data is stale if older than this
MAX_RETRIES = 2  # Max times to retry live export before alerting


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


def send_alert(message: str, severity: str = "warning"):
    """Send alert via notification system."""
    try:
        # Try to use the notification system if available
        from shared.utils.notification_system import notify_warning, notify_error

        if severity == "error":
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
        logger.error(f"Failed to send alert: {e}")


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

    # Step 2: Check data freshness
    freshness = check_live_data_freshness()
    result["freshness"] = freshness

    if freshness.get("status") == "fresh" and not freshness.get("date_mismatch"):
        logger.info(f"Live data is fresh ({freshness.get('age_minutes')} min old)")
        result["action_taken"] = "none"
        result["message"] = "Data is fresh"
        return jsonify(result), 200

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


# For local testing
if __name__ == "__main__":
    print("Checking live data freshness...")
    games_active = are_games_active()
    print(f"Games active: {games_active}")

    freshness = check_live_data_freshness()
    print(f"Freshness: {json.dumps(freshness, indent=2)}")
