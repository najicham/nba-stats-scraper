"""
Self-Healing Pipeline Cloud Function

Checks for missing predictions and triggers healing pipelines if necessary.
Runs 15 minutes BEFORE Phase 6 tonight-picks export to allow time for
self-healing before exports run.

Schedule: 12:45 PM ET daily (45 12 * * * America/New_York)

UPDATED 2026-01-12: Added Phase 3 data validation
- Now checks if player_game_summary exists for yesterday
- If Phase 3 data is missing, triggers Phase 3 before checking predictions
- This catches Phase 3 failures that would otherwise go undetected
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

# Simple retry decorator for HTTP calls (prevents self-heal failures on transient errors)
import time
import random

def retry_with_backoff(max_attempts=3, base_delay=2.0, max_delay=30.0, exceptions=(Exception,)):
    """Simple retry decorator with exponential backoff"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt >= max_attempts:
                        logger.error(f"{func.__name__} failed after {max_attempts} attempts: {e}")
                        raise
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    logger.warning(f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
        return wrapper
    return decorator

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


def get_yesterday_date():
    """Get yesterday's date in ET timezone."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    yesterday = datetime.now(et) - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


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


def check_phase3_data(bq_client, target_date):
    """
    Check if Phase 3 data (player_game_summary) exists for the target date.

    Phase 3 processes game results into analytics. If this data is missing
    for yesterday, predictions for today/tomorrow may be affected.

    Returns:
        dict with:
        - records: Number of player_game_summary records
        - players: Number of distinct players
        - exists: True if records > 0
    """
    query = f"""
    SELECT
        COUNT(*) as records,
        COUNT(DISTINCT player_lookup) as players
    FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
    WHERE game_date = '{target_date}'
    """
    result = list(bq_client.query(query).result(timeout=60))
    if result:
        records = result[0].records or 0
        players = result[0].players or 0
        return {
            'records': records,
            'players': players,
            'exists': records > 0
        }
    return {'records': 0, 'players': 0, 'exists': False}


def check_odds_data_freshness(bq_client, target_date):
    """
    Check if OddsAPI data exists and is fresh for the target date.

    This catches Phase 2 OddsAPI batch processing failures that would
    prevent accurate predictions.

    ADDED: 2026-01-14 Session 48 - Enhanced self-healing for OddsAPI batch failures

    Returns:
        dict with:
        - game_lines_count: Number of game lines records
        - props_count: Number of player props records
        - games_with_lines: Games with betting lines
        - games_with_props: Games with player props
        - is_fresh: True if data exists and is reasonably fresh
    """
    # Check game lines
    lines_query = f"""
    SELECT
        COUNT(*) as records,
        COUNT(DISTINCT game_id) as games
    FROM `{PROJECT_ID}.nba_raw.odds_api_game_lines`
    WHERE game_date = '{target_date}'
    """
    lines_result = list(bq_client.query(lines_query).result(timeout=60))
    lines_count = lines_result[0].records if lines_result else 0
    lines_games = lines_result[0].games if lines_result else 0

    # Check player props
    props_query = f"""
    SELECT
        COUNT(*) as records,
        COUNT(DISTINCT game_id) as games
    FROM `{PROJECT_ID}.nba_raw.odds_api_player_points_props`
    WHERE game_date = '{target_date}'
    """
    props_result = list(bq_client.query(props_query).result(timeout=60))
    props_count = props_result[0].records if props_result else 0
    props_games = props_result[0].games if props_result else 0

    # Data is fresh if we have both lines and props for at least one game
    is_fresh = lines_count > 0 and props_count > 0

    return {
        'game_lines_count': lines_count,
        'props_count': props_count,
        'games_with_lines': lines_games,
        'games_with_props': props_games,
        'is_fresh': is_fresh
    }


def trigger_phase3_only(target_date):
    """
    Trigger Phase 3 for a specific date without triggering the full pipeline.

    Used when Phase 3 data is missing but we want to generate it first
    before checking if predictions need to be regenerated.
    """
    token = get_auth_token(PHASE3_URL)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "start_date": target_date,
        "end_date": target_date,
        "processors": ["PlayerGameSummaryProcessor"],
        "backfill_mode": False,  # Must be False - True would query empty player_game_summary
        "skip_dependency_check": True
    }

    @retry_with_backoff(
        max_attempts=3,
        base_delay=2.0,
        max_delay=30.0,
        exceptions=(requests.RequestException, requests.Timeout, ConnectionError)
    )
    def _make_request():
        response = requests.post(
            f"{PHASE3_URL}/process-date-range",
            headers=headers,
            json=payload,
            timeout=180  # 3 minutes for just Phase 3
        )
        response.raise_for_status()
        return response

    try:
        response = _make_request()
        logger.info(f"Phase 3 only response for {target_date}: {response.status_code} - {response.text[:200]}")
        return True
    except Exception as e:
        logger.error(f"Phase 3 only failed for {target_date} after retries: {e}")
        return False


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

    @retry_with_backoff(
        max_attempts=3,
        base_delay=2.0,
        max_delay=30.0,
        exceptions=(requests.RequestException, requests.Timeout, ConnectionError)
    )
    def _make_request():
        response = requests.post(
            f"{PHASE3_URL}/process-date-range",
            headers=headers,
            json=payload,
            timeout=120
        )
        response.raise_for_status()
        return response

    try:
        response = _make_request()
        logger.info(f"Phase 3 response: {response.status_code} - {response.text[:200]}")
        return True
    except Exception as e:
        logger.error(f"Phase 3 failed after retries: {e}")
        return False


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

    @retry_with_backoff(
        max_attempts=3,
        base_delay=2.0,
        max_delay=30.0,
        exceptions=(requests.RequestException, requests.Timeout, ConnectionError)
    )
    def _make_request():
        # Increased timeout to 300s (5 min) since we now run all 5 processors
        response = requests.post(
            f"{PHASE4_URL}/process-date",
            headers=headers,
            json=payload,
            timeout=300
        )
        response.raise_for_status()
        return response

    try:
        response = _make_request()
        logger.info(f"Phase 4 response: {response.status_code} - {response.text[:200]}")
        return True
    except Exception as e:
        logger.error(f"Phase 4 failed after retries: {e}")
        return False


def trigger_predictions(target_date):
    """Trigger prediction coordinator."""
    token = get_auth_token(COORDINATOR_URL)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {"game_date": target_date}

    @retry_with_backoff(
        max_attempts=3,
        base_delay=2.0,
        max_delay=30.0,
        exceptions=(requests.RequestException, requests.Timeout, ConnectionError)
    )
    def _make_request():
        response = requests.post(
            f"{COORDINATOR_URL}/start",
            headers=headers,
            json=payload,
            timeout=120
        )
        response.raise_for_status()
        return response

    try:
        response = _make_request()
        logger.info(f"Coordinator response: {response.status_code} - {response.text[:200]}")
        return True
    except Exception as e:
        logger.error(f"Coordinator failed after retries: {e}")
        return False


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

    UPDATED 2026-01-12: Now includes Phase 3 data validation.

    Checks performed:
    1. Phase 3 data check: Verify player_game_summary exists for yesterday
       - If missing, trigger Phase 3 to generate analytics
    2. Today prediction check: Verify predictions exist for today's games
    3. Tomorrow prediction check: Verify predictions exist for tomorrow's games
    4. If predictions missing, trigger full healing pipeline (Phase 3→4→Predictions)
    """
    today = get_today_date()
    tomorrow = get_tomorrow_date()
    yesterday = get_yesterday_date()
    logger.info(f"Self-heal check: yesterday={yesterday}, today={today}, tomorrow={tomorrow}")

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": [],
        "actions_taken": [],
        "status": "healthy"
    }

    try:
        bq_client = get_bigquery_client(project_id=PROJECT_ID)

        # =================================================================
        # PHASE 3 DATA CHECK (NEW)
        # Check if player_game_summary exists for yesterday's games
        # This catches Phase 3 failures that would otherwise go undetected
        # =================================================================
        yesterday_games = check_games_scheduled(bq_client, yesterday)
        if yesterday_games > 0:
            phase3_data = check_phase3_data(bq_client, yesterday)

            phase3_check = {
                "date": yesterday,
                "type": "phase3_analytics",
                "games_played": yesterday_games,
                "records": phase3_data['records'],
                "players": phase3_data['players']
            }
            result["checks"].append(phase3_check)

            if not phase3_data['exists']:
                logger.warning(
                    f"PHASE 3 DATA MISSING: {yesterday_games} games played yesterday "
                    f"but no player_game_summary records. Triggering Phase 3."
                )
                phase3_check["status"] = "missing"
                result["status"] = "healing_phase3"

                # Clear stuck entries first
                if not result.get("_cleared_stuck"):
                    cleared = clear_stuck_run_history()
                    if cleared > 0:
                        result["actions_taken"].append(f"Cleared {cleared} stuck run_history entries")
                    result["_cleared_stuck"] = True

                # Trigger Phase 3 only (not full pipeline)
                try:
                    if trigger_phase3_only(yesterday):
                        result["actions_taken"].append(f"Phase 3 triggered for {yesterday} (missing analytics)")
                    else:
                        result["actions_taken"].append(f"Phase 3 trigger failed for {yesterday}")
                except Exception as e:
                    result["actions_taken"].append(f"Phase 3 error ({yesterday}): {str(e)[:50]}")
            else:
                phase3_check["status"] = "healthy"
                logger.info(
                    f"Phase 3 OK for {yesterday}: {phase3_data['records']} records "
                    f"for {phase3_data['players']} players"
                )
        else:
            result["checks"].append({
                "date": yesterday,
                "type": "phase3_analytics",
                "games_played": 0,
                "status": "no_games"
            })
            logger.info(f"No games were played yesterday ({yesterday})")

        # =================================================================
        # PHASE 2 ODDSAPI DATA CHECK (NEW - Session 48)
        # Check if OddsAPI data exists for today's games
        # This catches Phase 2 batch processing failures
        # =================================================================
        today_games = check_games_scheduled(bq_client, today)
        if today_games > 0:
            odds_data = check_odds_data_freshness(bq_client, today)

            odds_check = {
                "date": today,
                "type": "phase2_odds",
                "games_scheduled": today_games,
                "game_lines": odds_data['game_lines_count'],
                "props": odds_data['props_count'],
                "games_with_lines": odds_data['games_with_lines'],
                "games_with_props": odds_data['games_with_props']
            }
            result["checks"].append(odds_check)

            if not odds_data['is_fresh']:
                logger.warning(
                    f"ODDSAPI DATA MISSING: {today_games} games scheduled today "
                    f"but odds data incomplete (lines={odds_data['game_lines_count']}, "
                    f"props={odds_data['props_count']}). Check OddsAPI batch processing."
                )
                odds_check["status"] = "missing"
                # Don't trigger healing for odds - this is informational only
                # OddsAPI batch processing runs on file arrival, not schedule
                result["actions_taken"].append(
                    f"WARNING: OddsAPI data incomplete for {today} - "
                    f"lines={odds_data['game_lines_count']}, props={odds_data['props_count']}"
                )
            else:
                odds_check["status"] = "healthy"
                logger.info(
                    f"OddsAPI OK for {today}: {odds_data['game_lines_count']} lines, "
                    f"{odds_data['props_count']} props for {odds_data['games_with_props']} games"
                )

        # Check TODAY predictions (most important for same-day predictions)
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
                # Update status based on what we're already healing
                if result["status"] == "healing_phase3":
                    result["status"] = "healing_phase3_and_today"
                else:
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
                # Update status based on what we're already healing
                current_status = result["status"]
                if current_status == "healthy":
                    result["status"] = "healing_tomorrow"
                elif current_status == "healing_phase3":
                    result["status"] = "healing_phase3_and_tomorrow"
                elif current_status in ("healing_today", "healing_phase3_and_today"):
                    result["status"] = "healing_all"
                else:
                    result["status"] = "healing_multiple"
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
