"""
Self-Healing Pipeline Cloud Function

Checks for missing predictions and triggers healing pipelines if necessary.
Runs 15 minutes BEFORE Phase 6 tonight-picks export to allow time for
self-healing before exports run.

Schedule: 12:45 PM ET daily (45 12 * * * America/New_York)
"""

import functions_framework
from flask import jsonify
from google.cloud import bigquery, firestore
from datetime import datetime, timedelta, timezone
import requests
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Service URLs
PHASE3_URL = "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app"
PHASE4_URL = "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app"
COORDINATOR_URL = "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"

PROJECT_ID = os.environ.get("GCP_PROJECT", "nba-props-platform")


def get_auth_token(audience):
    """Get identity token for authenticated service calls using metadata server."""
    import urllib.request

    # Use the metadata server (works in Cloud Run/Cloud Functions)
    metadata_url = f"http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience={audience}"
    req = urllib.request.Request(metadata_url, headers={"Metadata-Flavor": "Google"})

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to get auth token: {e}")
        raise


def get_today_date():
    """Get today's date in ET timezone."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    today = datetime.now(et)
    return today.strftime("%Y-%m-%d")


def get_tomorrow_date():
    """Get tomorrow's date in ET timezone."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    tomorrow = datetime.now(et) + timedelta(days=1)
    return tomorrow.strftime("%Y-%m-%d")


def check_games_scheduled(bq_client, target_date):
    """Check if games are scheduled for the target date."""
    query = f"""
    SELECT COUNT(*) as games
    FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
    WHERE game_date = '{target_date}'
    """
    result = list(bq_client.query(query).result(timeout=60))
    return result[0].games if result else 0


def check_predictions_exist(bq_client, target_date):
    """Check if predictions exist for the target date."""
    query = f"""
    SELECT COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
    WHERE game_date = '{target_date}' AND is_active = TRUE
    """
    result = list(bq_client.query(query).result(timeout=60))
    if result:
        return result[0].predictions, result[0].players
    return 0, 0


def check_quality_score(bq_client, target_date):
    """Check average quality score for the target date."""
    query = f"""
    SELECT ROUND(AVG(feature_quality_score), 1) as avg_quality
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
    WHERE game_date = '{target_date}'
    """
    result = list(bq_client.query(query).result(timeout=60))
    if result and result[0].avg_quality:
        return float(result[0].avg_quality)
    return None


def clear_stuck_run_history():
    """Clear run_history entries stuck in 'running' state for >4 hours."""
    db = firestore.Client()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=4)

    cleared = 0
    docs = db.collection('run_history').where('status', '==', 'running').stream()
    for doc in docs:
        data = doc.to_dict()
        started = data.get('started_at')
        if started and started < cutoff:
            doc.reference.delete()
            cleared += 1
            logger.info(f"Cleared stuck entry: {doc.id}")

    return cleared


def trigger_phase3(target_date):
    """Trigger Phase 3 analytics for tomorrow's predictions."""
    # Process yesterday's data (needed for tomorrow's predictions)
    yesterday = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    token = get_auth_token(PHASE3_URL)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Note: backfill_mode=False because we need accurate player lists for predictions
    # backfill_mode=True would query player_game_summary which is for historical data
    payload = {
        "start_date": yesterday,
        "end_date": yesterday,
        "processors": ["PlayerGameSummaryProcessor", "UpcomingPlayerGameContextProcessor"],
        "backfill_mode": False,
        "skip_dependency_check": True
    }

    response = requests.post(
        f"{PHASE3_URL}/process-date-range",
        headers=headers,
        json=payload,
        timeout=120
    )

    logger.info(f"Phase 3 response: {response.status_code} - {response.text[:200]}")
    return response.status_code == 200


def trigger_phase4(target_date):
    """Trigger ALL Phase 4 processors with skip_dependency_check.

    Phase 4 has 5 processors with dependencies:
    1. TeamDefenseZoneAnalysisProcessor - no deps
    2. PlayerShotZoneAnalysisProcessor - no deps
    3. PlayerDailyCacheProcessor - no deps
    4. PlayerCompositeFactorsProcessor - depends on 1-3
    5. MLFeatureStoreProcessor - depends on 1-4

    By passing empty processors list, the service runs ALL in order.
    """
    token = get_auth_token(PHASE4_URL)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Empty processors list = run ALL Phase 4 processors in correct order
    # Previously only ran MLFeatureStoreProcessor, which caused missing features
    payload = {
        "analysis_date": target_date,
        "processors": [],  # Run ALL processors, not just MLFeatureStoreProcessor
        "strict_mode": False,
        "skip_dependency_check": True
    }

    # Increased timeout to 300s (5 min) since we now run all 5 processors
    response = requests.post(
        f"{PHASE4_URL}/process-date",
        headers=headers,
        json=payload,
        timeout=300
    )

    logger.info(f"Phase 4 response: {response.status_code} - {response.text[:200]}")
    return response.status_code == 200


def trigger_predictions(target_date):
    """Trigger prediction coordinator."""
    token = get_auth_token(COORDINATOR_URL)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {"game_date": target_date}

    response = requests.post(
        f"{COORDINATOR_URL}/start",
        headers=headers,
        json=payload,
        timeout=120
    )

    logger.info(f"Coordinator response: {response.status_code} - {response.text[:200]}")
    return response.status_code == 200


def heal_for_date(target_date, result):
    """Trigger healing pipeline for a specific date."""
    import time

    logger.info(f"Starting healing pipeline for {target_date}")

    # Clear stuck entries (only once per invocation)
    if not result.get("_cleared_stuck"):
        cleared = clear_stuck_run_history()
        if cleared > 0:
            result["actions_taken"].append(f"Cleared {cleared} stuck run_history entries")
        result["_cleared_stuck"] = True

    # Trigger Phase 3
    try:
        if trigger_phase3(target_date):
            result["actions_taken"].append(f"Phase 3 triggered for {target_date}")
        else:
            result["actions_taken"].append(f"Phase 3 trigger failed for {target_date}")
    except Exception as e:
        result["actions_taken"].append(f"Phase 3 error ({target_date}): {str(e)[:50]}")

    time.sleep(10)

    # Trigger Phase 4
    try:
        if trigger_phase4(target_date):
            result["actions_taken"].append(f"Phase 4 triggered for {target_date}")
        else:
            result["actions_taken"].append(f"Phase 4 trigger failed for {target_date}")
    except Exception as e:
        result["actions_taken"].append(f"Phase 4 error ({target_date}): {str(e)[:50]}")

    time.sleep(10)

    # Trigger predictions
    try:
        if trigger_predictions(target_date):
            result["actions_taken"].append(f"Predictions triggered for {target_date}")
        else:
            result["actions_taken"].append(f"Predictions trigger failed for {target_date}")
    except Exception as e:
        result["actions_taken"].append(f"Predictions error ({target_date}): {str(e)[:50]}")


@functions_framework.http
def self_heal_check(request):
    """
    Main self-healing check function.

    UPDATED: Now checks BOTH today AND tomorrow for missing predictions.

    1. Check if TODAY has games scheduled and predictions exist
    2. Check if TOMORROW has games scheduled and predictions exist
    3. If either is missing predictions, trigger self-healing pipeline
    """
    today = get_today_date()
    tomorrow = get_tomorrow_date()
    logger.info(f"Self-heal check for today={today} and tomorrow={tomorrow}")

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": [],
        "actions_taken": [],
        "status": "healthy"
    }

    try:
        bq_client = bigquery.Client()

        # Check TODAY first (most important for same-day predictions)
        today_games = check_games_scheduled(bq_client, today)
        if today_games > 0:
            today_predictions, today_players = check_predictions_exist(bq_client, today)
            today_quality = check_quality_score(bq_client, today) if today_predictions > 0 else None

            today_check = {
                "date": today,
                "type": "today",
                "games": today_games,
                "predictions": today_predictions,
                "players": today_players,
                "quality_score": today_quality
            }
            result["checks"].append(today_check)

            if today_predictions == 0:
                logger.warning(f"No predictions for TODAY ({today}) - triggering self-healing")
                result["status"] = "healing_today"
                heal_for_date(today, result)
            elif today_quality and today_quality < 70:
                logger.warning(f"Low quality ({today_quality}%) for TODAY ({today})")
                today_check["status"] = "low_quality"
            else:
                today_check["status"] = "healthy"
                logger.info(f"TODAY ({today}): {today_predictions} predictions for {today_players} players")
        else:
            result["checks"].append({
                "date": today,
                "type": "today",
                "games": 0,
                "status": "no_games"
            })
            logger.info(f"No games scheduled for TODAY ({today})")

        # Then check TOMORROW (existing behavior)
        tomorrow_games = check_games_scheduled(bq_client, tomorrow)
        if tomorrow_games > 0:
            tomorrow_predictions, tomorrow_players = check_predictions_exist(bq_client, tomorrow)
            tomorrow_quality = check_quality_score(bq_client, tomorrow) if tomorrow_predictions > 0 else None

            tomorrow_check = {
                "date": tomorrow,
                "type": "tomorrow",
                "games": tomorrow_games,
                "predictions": tomorrow_predictions,
                "players": tomorrow_players,
                "quality_score": tomorrow_quality
            }
            result["checks"].append(tomorrow_check)

            if tomorrow_predictions == 0:
                logger.warning(f"No predictions for TOMORROW ({tomorrow}) - triggering self-healing")
                if result["status"] == "healthy":
                    result["status"] = "healing_tomorrow"
                else:
                    result["status"] = "healing_both"
                heal_for_date(tomorrow, result)
            elif tomorrow_quality and tomorrow_quality < 70:
                logger.warning(f"Low quality ({tomorrow_quality}%) for TOMORROW ({tomorrow})")
                tomorrow_check["status"] = "low_quality"
            else:
                tomorrow_check["status"] = "healthy"
                logger.info(f"TOMORROW ({tomorrow}): {tomorrow_predictions} predictions for {tomorrow_players} players")
        else:
            result["checks"].append({
                "date": tomorrow,
                "type": "tomorrow",
                "games": 0,
                "status": "no_games"
            })
            logger.info(f"No games scheduled for TOMORROW ({tomorrow})")

        # Clean up internal tracking field
        result.pop("_cleared_stuck", None)

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Self-heal check failed: {str(e)}")
        result["status"] = "error"
        result["error"] = str(e)
        return jsonify(result), 500


# ============================================================================
# HTTP ENDPOINTS (for health checks)
# ============================================================================

@functions_framework.http
def health(request):
    """Health check endpoint for the self_heal function."""
    return jsonify({
        'status': 'healthy',
        'function': 'self_heal'
    }), 200


# For local testing
if __name__ == "__main__":
    from flask import Flask, request
    app = Flask(__name__)

    @app.route("/", methods=["GET", "POST"])
    def test():
        return self_heal_check(request)

    app.run(debug=True, port=8080)
