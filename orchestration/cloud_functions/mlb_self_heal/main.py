"""
MLB Self-Healing Pipeline Cloud Function

Checks for missing MLB predictions and triggers healing pipelines if necessary.
Runs before Phase 6 exports to allow time for self-healing.

Schedule: 12:45 PM ET daily (45 12 * * * America/New_York)

MLB-Specific: Checks pitcher strikeout predictions
"""

import functions_framework
from flask import jsonify
from google.cloud import bigquery, firestore
from shared.clients.bigquery_pool import get_bigquery_client
from datetime import datetime, timedelta, timezone
import requests
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MLB Service URLs
PHASE3_URL = "https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app"
PHASE4_URL = "https://mlb-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app"
PREDICTION_URL = "https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app"

PROJECT_ID = os.environ.get("GCP_PROJECT_ID") or os.environ.get("GCP_PROJECT", "nba-props-platform")


def get_auth_token(audience):
    """Get identity token for authenticated service calls using metadata server."""
    import urllib.request

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
    """Check if MLB games are scheduled for the target date."""
    query = f"""
    SELECT COUNT(DISTINCT game_pk) as games
    FROM `{PROJECT_ID}.mlb_raw.mlb_schedule`
    WHERE game_date = '{target_date}'
    """
    try:
        result = list(bq_client.query(query).result(timeout=60))
        return result[0].games if result else 0
    except Exception as e:
        logger.warning(f"Games check failed: {e}")
        return 0


def check_predictions_exist(bq_client, target_date):
    """Check if MLB predictions exist for the target date."""
    query = f"""
    SELECT COUNT(*) as predictions, COUNT(DISTINCT pitcher_lookup) as pitchers
    FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
    WHERE game_date = '{target_date}'
    """
    try:
        result = list(bq_client.query(query).result(timeout=60))
        if result:
            return result[0].predictions, result[0].pitchers
    except Exception as e:
        logger.warning(f"Predictions check failed: {e}")
    return 0, 0


def check_analytics_data(bq_client, target_date):
    """Check if analytics data exists (prerequisite for predictions)."""
    query = f"""
    SELECT COUNT(*) as records
    FROM `{PROJECT_ID}.mlb_analytics.pitcher_game_summary`
    WHERE game_date >= DATE_SUB(DATE('{target_date}'), INTERVAL 7 DAY)
    """
    try:
        result = list(bq_client.query(query).result(timeout=60))
        return result[0].records if result else 0
    except Exception as e:
        logger.warning(f"Analytics check failed: {e}")
        return 0


def check_precompute_data(bq_client, target_date):
    """Check if precompute features exist."""
    query = f"""
    SELECT COUNT(*) as records
    FROM `{PROJECT_ID}.mlb_precompute.pitcher_ml_features`
    WHERE game_date = '{target_date}'
    """
    try:
        result = list(bq_client.query(query).result(timeout=60))
        return result[0].records if result else 0
    except Exception as e:
        logger.warning(f"Precompute check failed: {e}")
        return 0


def clear_stuck_mlb_state():
    """Clear any stuck MLB orchestration state in Firestore."""
    db = firestore.Client()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=4)

    cleared = 0

    # Check mlb_phase3_completion and mlb_phase4_completion for stuck entries
    for collection in ['mlb_phase3_completion', 'mlb_phase4_completion']:
        try:
            docs = db.collection(collection).stream()
            for doc in docs:
                data = doc.to_dict()
                # Check if triggered but very old
                triggered_at = data.get('_triggered_at')
                if triggered_at and hasattr(triggered_at, 'timestamp'):
                    if triggered_at.timestamp() < cutoff.timestamp():
                        # Old entry, can be cleared
                        doc.reference.delete()
                        cleared += 1
                        logger.info(f"Cleared old {collection} entry: {doc.id}")
        except Exception as e:
            logger.warning(f"Error checking {collection}: {e}")

    return cleared


def trigger_phase3(target_date):
    """Trigger MLB Phase 3 analytics."""
    token = get_auth_token(PHASE3_URL)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Process recent data for predictions
    yesterday = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    payload = {
        "game_date": yesterday
    }

    try:
        response = requests.post(
            f"{PHASE3_URL}/process-date",
            headers=headers,
            json=payload,
            timeout=120
        )
        logger.info(f"Phase 3 response: {response.status_code} - {response.text[:200]}")
        return response.status_code in [200, 207]
    except Exception as e:
        logger.error(f"Phase 3 trigger failed: {e}")
        return False


def trigger_phase4(target_date):
    """Trigger MLB Phase 4 precompute."""
    token = get_auth_token(PHASE4_URL)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "game_date": target_date
    }

    try:
        response = requests.post(
            f"{PHASE4_URL}/process-date",
            headers=headers,
            json=payload,
            timeout=120
        )
        logger.info(f"Phase 4 response: {response.status_code} - {response.text[:200]}")
        return response.status_code in [200, 207]
    except Exception as e:
        logger.error(f"Phase 4 trigger failed: {e}")
        return False


def trigger_predictions(target_date):
    """Trigger MLB prediction worker for batch predictions."""
    token = get_auth_token(PREDICTION_URL)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {"game_date": target_date}

    try:
        response = requests.post(
            f"{PREDICTION_URL}/predict-batch",
            headers=headers,
            json=payload,
            timeout=180
        )
        logger.info(f"Prediction response: {response.status_code} - {response.text[:200]}")
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Prediction trigger failed: {e}")
        return False


def heal_for_date(target_date, result, bq_client):
    """Trigger healing pipeline for a specific date."""
    import time

    logger.info(f"Starting MLB healing pipeline for {target_date}")

    # Clear stuck state (only once per invocation)
    if not result.get("_cleared_stuck"):
        cleared = clear_stuck_mlb_state()
        if cleared > 0:
            result["actions_taken"].append(f"Cleared {cleared} stuck orchestration entries")
        result["_cleared_stuck"] = True

    # Check if we have recent analytics data
    analytics_count = check_analytics_data(bq_client, target_date)

    if analytics_count < 10:
        # Need to run Phase 3 first
        try:
            if trigger_phase3(target_date):
                result["actions_taken"].append(f"Phase 3 triggered for {target_date}")
            else:
                result["actions_taken"].append(f"Phase 3 trigger failed for {target_date}")
        except Exception as e:
            result["actions_taken"].append(f"Phase 3 error ({target_date}): {str(e)[:50]}")
        time.sleep(15)

    # Check if we have precompute features
    precompute_count = check_precompute_data(bq_client, target_date)

    if precompute_count < 5:
        # Need to run Phase 4
        try:
            if trigger_phase4(target_date):
                result["actions_taken"].append(f"Phase 4 triggered for {target_date}")
            else:
                result["actions_taken"].append(f"Phase 4 trigger failed for {target_date}")
        except Exception as e:
            result["actions_taken"].append(f"Phase 4 error ({target_date}): {str(e)[:50]}")
        time.sleep(15)

    # Trigger predictions
    try:
        if trigger_predictions(target_date):
            result["actions_taken"].append(f"Predictions triggered for {target_date}")
        else:
            result["actions_taken"].append(f"Predictions trigger failed for {target_date}")
    except Exception as e:
        result["actions_taken"].append(f"Predictions error ({target_date}): {str(e)[:50]}")


@functions_framework.http
def mlb_self_heal_check(request):
    """
    MLB Self-healing check function.

    Checks if MLB predictions exist for today and tomorrow.
    If missing, triggers the healing pipeline.

    Note: Only runs during MLB season (April-October).
    """
    today = get_today_date()
    tomorrow = get_tomorrow_date()
    logger.info(f"MLB Self-heal check for today={today} and tomorrow={tomorrow}")

    result = {
        "sport": "mlb",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": [],
        "actions_taken": [],
        "status": "healthy"
    }

    try:
        bq_client = get_bigquery_client(project_id=PROJECT_ID)

        # Check TODAY
        today_games = check_games_scheduled(bq_client, today)
        if today_games > 0:
            today_predictions, today_pitchers = check_predictions_exist(bq_client, today)

            today_check = {
                "date": today,
                "type": "today",
                "games": today_games,
                "predictions": today_predictions,
                "pitchers": today_pitchers
            }
            result["checks"].append(today_check)

            if today_predictions == 0:
                logger.warning(f"No MLB predictions for TODAY ({today}) - triggering self-healing")
                result["status"] = "healing_today"
                today_check["status"] = "healing"
                heal_for_date(today, result, bq_client)
            else:
                today_check["status"] = "healthy"
                logger.info(f"TODAY ({today}): {today_predictions} predictions for {today_pitchers} pitchers")
        else:
            result["checks"].append({
                "date": today,
                "type": "today",
                "games": 0,
                "status": "no_games"
            })
            logger.info(f"No MLB games scheduled for TODAY ({today})")

        # Check TOMORROW
        tomorrow_games = check_games_scheduled(bq_client, tomorrow)
        if tomorrow_games > 0:
            tomorrow_predictions, tomorrow_pitchers = check_predictions_exist(bq_client, tomorrow)

            tomorrow_check = {
                "date": tomorrow,
                "type": "tomorrow",
                "games": tomorrow_games,
                "predictions": tomorrow_predictions,
                "pitchers": tomorrow_pitchers
            }
            result["checks"].append(tomorrow_check)

            if tomorrow_predictions == 0:
                logger.warning(f"No MLB predictions for TOMORROW ({tomorrow}) - triggering self-healing")
                if result["status"] == "healthy":
                    result["status"] = "healing_tomorrow"
                else:
                    result["status"] = "healing_both"
                tomorrow_check["status"] = "healing"
                heal_for_date(tomorrow, result, bq_client)
            else:
                tomorrow_check["status"] = "healthy"
                logger.info(f"TOMORROW ({tomorrow}): {tomorrow_predictions} predictions for {tomorrow_pitchers} pitchers")
        else:
            result["checks"].append({
                "date": tomorrow,
                "type": "tomorrow",
                "games": 0,
                "status": "no_games"
            })
            logger.info(f"No MLB games scheduled for TOMORROW ({tomorrow})")

        # Clean up internal tracking field
        result.pop("_cleared_stuck", None)

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"MLB Self-heal check failed: {str(e)}")
        result["status"] = "error"
        result["error"] = str(e)
        return jsonify(result), 500


@functions_framework.http
def health(request):
    """Health check endpoint for the mlb_self_heal function."""
    return jsonify({
        'status': 'healthy',
        'function': 'mlb_self_heal',
        'sport': 'mlb'
    }), 200


# For local testing
if __name__ == "__main__":
    from flask import Flask, request
    app = Flask(__name__)

    @app.route("/", methods=["GET", "POST"])
    def test():
        return mlb_self_heal_check(request)

    @app.route("/health", methods=["GET"])
    def health_check():
        return health(request)

    app.run(debug=True, port=8081)
