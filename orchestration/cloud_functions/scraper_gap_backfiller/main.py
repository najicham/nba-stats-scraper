"""
Scraper Gap Backfiller Cloud Function

Automatically detects and backfills gaps when scrapers recover from failures.

Schedule: Every 4 hours
Logic:
1. For each scraper with unbackfilled failures (last 7 days):
   - Test if scraper is healthy (try current date)
   - If healthy, backfill oldest unbackfilled date
   - Mark as backfilled on success
   - Rate limit: 1 backfill per scraper per run

Table: nba_orchestration.scraper_failures
"""

import functions_framework
from flask import jsonify
from google.cloud import bigquery
from datetime import datetime, timezone
import requests
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
SCRAPER_SERVICE_URL = os.getenv(
    "SCRAPER_SERVICE_URL",
    "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"
)
LOOKBACK_DAYS = 7
REQUEST_TIMEOUT = 180  # 3 minutes for scraper to complete


def get_unbackfilled_failures(client: bigquery.Client) -> list:
    """Get all unbackfilled failures from the last 7 days, grouped by scraper."""
    query = """
    SELECT
        scraper_name,
        MIN(game_date) as oldest_gap_date,
        COUNT(*) as gap_count
    FROM `nba-props-platform.nba_orchestration.scraper_failures`
    WHERE backfilled = FALSE
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @lookback_days DAY)
    GROUP BY scraper_name
    ORDER BY oldest_gap_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("lookback_days", "INT64", LOOKBACK_DAYS)
        ]
    )

    result = client.query(query, job_config=job_config).result()
    return [dict(row) for row in result]


def test_scraper_health(scraper_name: str, test_date: str) -> bool:
    """Test if a scraper is healthy by trying to scrape a date."""
    try:
        response = requests.post(
            f"{SCRAPER_SERVICE_URL}/scrape",
            json={"scraper": scraper_name, "date": test_date},
            timeout=REQUEST_TIMEOUT,
            headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            data = response.json()
            return data.get("status") == "success"
        return False

    except Exception as e:
        logger.warning(f"Health check failed for {scraper_name}: {e}")
        return False


def trigger_backfill(scraper_name: str, game_date: str) -> bool:
    """Trigger a backfill for a specific scraper and date."""
    try:
        logger.info(f"Triggering backfill: {scraper_name} for {game_date}")

        response = requests.post(
            f"{SCRAPER_SERVICE_URL}/scrape",
            json={"scraper": scraper_name, "date": game_date},
            timeout=REQUEST_TIMEOUT,
            headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            data = response.json()
            success = data.get("status") == "success"
            if success:
                logger.info(f"✅ Backfill succeeded: {scraper_name} / {game_date}")
            else:
                logger.warning(f"❌ Backfill returned non-success: {data}")
            return success
        else:
            logger.warning(f"❌ Backfill HTTP {response.status_code}: {response.text[:200]}")
            return False

    except Exception as e:
        logger.error(f"Backfill failed for {scraper_name}/{game_date}: {e}")
        return False


def mark_as_backfilled(client: bigquery.Client, scraper_name: str, game_date: str):
    """Mark a failure as backfilled."""
    query = """
    UPDATE `nba-props-platform.nba_orchestration.scraper_failures`
    SET backfilled = TRUE, backfilled_at = CURRENT_TIMESTAMP()
    WHERE scraper_name = @scraper_name AND game_date = @game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("scraper_name", "STRING", scraper_name),
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    client.query(query, job_config=job_config).result()
    logger.info(f"Marked as backfilled: {scraper_name} / {game_date}")


@functions_framework.http
def scraper_gap_backfiller(request):
    """
    Main entry point for the Cloud Function.

    Query params:
    - dry_run: If true, don't actually run backfills, just report gaps
    - scraper: Limit to a specific scraper name
    """
    try:
        dry_run = request.args.get("dry_run", "false").lower() == "true"
        target_scraper = request.args.get("scraper")

        client = bigquery.Client()

        # Get all unbackfilled failures
        failures = get_unbackfilled_failures(client)

        if target_scraper:
            failures = [f for f in failures if f["scraper_name"] == target_scraper]

        if not failures:
            return jsonify({
                "status": "ok",
                "message": "No gaps to backfill",
                "gaps_found": 0
            })

        results = {
            "status": "ok",
            "gaps_found": sum(f["gap_count"] for f in failures),
            "scrapers_with_gaps": len(failures),
            "actions": []
        }

        if dry_run:
            results["dry_run"] = True
            results["gaps"] = [
                {
                    "scraper": f["scraper_name"],
                    "oldest_gap": str(f["oldest_gap_date"]),
                    "gap_count": f["gap_count"]
                }
                for f in failures
            ]
            return jsonify(results)

        # Process each scraper with gaps
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for failure in failures:
            scraper_name = failure["scraper_name"]
            oldest_gap = str(failure["oldest_gap_date"])

            action = {
                "scraper": scraper_name,
                "oldest_gap": oldest_gap,
                "gap_count": failure["gap_count"]
            }

            # Skip health check if today is the gap (can't test with today)
            if oldest_gap == today:
                # Just try the backfill directly
                action["health_check"] = "skipped_same_day"
            else:
                # Test health with today's date
                if not test_scraper_health(scraper_name, today):
                    action["health_check"] = "failed"
                    action["backfill"] = "skipped"
                    results["actions"].append(action)
                    continue
                action["health_check"] = "passed"

            # Trigger backfill for oldest gap
            if trigger_backfill(scraper_name, oldest_gap):
                mark_as_backfilled(client, scraper_name, oldest_gap)
                action["backfill"] = "success"
            else:
                action["backfill"] = "failed"

            results["actions"].append(action)

        return jsonify(results)

    except Exception as e:
        logger.error(f"Gap backfiller error: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500
