"""
Self-Healing Pipeline Cloud Function

Runs 30 minutes after same-day-predictions scheduler to verify predictions exist.
If predictions are missing, triggers the pipeline with bypass flags.

Schedule: 2:15 PM ET daily (15 14 * * * America/New_York)
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
    result = list(bq_client.query(query).result())
    return result[0].games if result else 0


def check_predictions_exist(bq_client, target_date):
    """Check if predictions exist for the target date."""
    query = f"""
    SELECT COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
    WHERE game_date = '{target_date}' AND is_active = TRUE
    """
    result = list(bq_client.query(query).result())
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
    result = list(bq_client.query(query).result())
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
    """Trigger Phase 3 analytics in backfill mode."""
    # Process yesterday's data (needed for tomorrow's predictions)
    yesterday = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    token = get_auth_token(PHASE3_URL)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "start_date": yesterday,
        "end_date": yesterday,
        "processors": ["PlayerGameSummaryProcessor", "UpcomingPlayerGameContextProcessor"],
        "backfill_mode": True
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
    """Trigger Phase 4 ML Feature Store with skip_dependency_check."""
    token = get_auth_token(PHASE4_URL)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "analysis_date": target_date,
        "processors": ["MLFeatureStoreProcessor"],
        "strict_mode": False,
        "skip_dependency_check": True
    }

    response = requests.post(
        f"{PHASE4_URL}/process-date",
        headers=headers,
        json=payload,
        timeout=120
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


@functions_framework.http
def self_heal_check(request):
    """
    Main self-healing check function.

    1. Check if tomorrow has games scheduled
    2. Check if predictions exist
    3. If not, trigger pipeline with bypass flags
    """
    target_date = get_tomorrow_date()
    logger.info(f"Self-heal check for {target_date}")

    result = {
        "target_date": target_date,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actions_taken": [],
        "status": "healthy"
    }

    try:
        bq_client = bigquery.Client()

        # Step 1: Check games scheduled
        games = check_games_scheduled(bq_client, target_date)
        result["games_scheduled"] = games

        if games == 0:
            result["status"] = "no_games"
            result["message"] = f"No games scheduled for {target_date}"
            logger.info(result["message"])
            return jsonify(result), 200

        # Step 2: Check predictions exist
        predictions, players = check_predictions_exist(bq_client, target_date)
        result["predictions"] = predictions
        result["players"] = players

        if predictions > 0:
            # Check quality
            quality = check_quality_score(bq_client, target_date)
            result["quality_score"] = quality

            if quality and quality < 70:
                result["status"] = "low_quality"
                result["message"] = f"Predictions exist but quality ({quality}%) below threshold"
                logger.warning(result["message"])
            else:
                result["status"] = "healthy"
                result["message"] = f"Pipeline healthy: {predictions} predictions for {players} players"
                logger.info(result["message"])

            return jsonify(result), 200

        # Step 3: No predictions - trigger self-healing
        logger.warning(f"No predictions for {target_date} - triggering self-healing")
        result["status"] = "healing"

        # Clear stuck entries
        cleared = clear_stuck_run_history()
        if cleared > 0:
            result["actions_taken"].append(f"Cleared {cleared} stuck run_history entries")

        # Trigger Phase 3
        import time
        try:
            if trigger_phase3(target_date):
                result["actions_taken"].append("Triggered Phase 3 (backfill_mode)")
            else:
                result["actions_taken"].append("Phase 3 trigger failed")
        except Exception as e:
            result["actions_taken"].append(f"Phase 3 error: {str(e)[:100]}")

        # Wait a bit for Phase 3 to complete
        time.sleep(10)

        # Trigger Phase 4
        try:
            if trigger_phase4(target_date):
                result["actions_taken"].append("Triggered Phase 4 (skip_dependency_check)")
            else:
                result["actions_taken"].append("Phase 4 trigger failed")
        except Exception as e:
            result["actions_taken"].append(f"Phase 4 error: {str(e)[:100]}")

        # Wait for Phase 4
        time.sleep(10)

        # Trigger predictions
        try:
            if trigger_predictions(target_date):
                result["actions_taken"].append("Triggered Prediction Coordinator")
            else:
                result["actions_taken"].append("Prediction Coordinator trigger failed")
        except Exception as e:
            result["actions_taken"].append(f"Coordinator error: {str(e)[:100]}")

        result["message"] = f"Self-healing triggered for {target_date}"
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Self-heal check failed: {str(e)}")
        result["status"] = "error"
        result["error"] = str(e)
        return jsonify(result), 500


# For local testing
if __name__ == "__main__":
    from flask import Flask, request
    app = Flask(__name__)

    @app.route("/", methods=["GET", "POST"])
    def test():
        return self_heal_check(request)

    app.run(debug=True, port=8080)
