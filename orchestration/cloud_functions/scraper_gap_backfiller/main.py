"""
Scraper Gap Backfiller Cloud Function

Automatically detects and backfills gaps when scrapers recover from failures.
Also alerts when gaps accumulate beyond threshold.

Schedule: Every 4 hours
Logic:
1. Check for accumulated gaps (>= threshold) and send alerts
2. For each scraper with unbackfilled failures (last 7 days):
   - Test if scraper is healthy (try current date)
   - If healthy, backfill oldest unbackfilled date
   - Mark as backfilled on success
   - Rate limit: 1 backfill per scraper per run

Table: nba_orchestration.scraper_failures
"""

import functions_framework
from flask import jsonify
from google.cloud import bigquery
from google.cloud import secretmanager
from datetime import datetime, timezone
import requests
import logging
import os
import html
import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
SCRAPER_SERVICE_URL = os.getenv(
    "SCRAPER_SERVICE_URL",
    "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"
)
LOOKBACK_DAYS = 7
REQUEST_TIMEOUT = 180  # 3 minutes for scraper to complete
GAP_ALERT_THRESHOLD = 3  # Alert when any scraper has >= 3 days of gaps


# ============================================================================
# Gap Alerting Functions
# ============================================================================

def get_secret(secret_id: str) -> str:
    """Get secret from Google Secret Manager."""
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/nba-props-platform/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        logger.warning(f"Failed to get secret {secret_id}: {e}")
        return None


def send_gap_alert_email(gap_data: dict) -> bool:
    """Send gap alert email via AWS SES."""
    try:
        # Get AWS credentials from Secret Manager
        aws_access_key = get_secret("aws-ses-access-key-id")
        aws_secret_key = get_secret("aws-ses-secret-access-key")

        if not aws_access_key or not aws_secret_key:
            logger.error("AWS SES credentials not available", exc_info=True)
            return False

        ses_client = boto3.client(
            'ses',
            region_name='us-west-2',
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key
        )

        scrapers = gap_data.get('scrapers', [])
        total_gaps = gap_data.get('total_gaps', 0)
        threshold = gap_data.get('threshold', GAP_ALERT_THRESHOLD)

        # Build scraper rows
        scraper_rows = ""
        for scraper in scrapers:
            name = html.escape(scraper.get('scraper_name', 'Unknown'))
            gaps = scraper.get('gap_count', 0)
            oldest = html.escape(str(scraper.get('oldest_gap', 'Unknown')))

            if gaps >= 5:
                color = "#d32f2f"
                icon = "🔴"
            elif gaps >= 3:
                color = "#ff9800"
                icon = "🟠"
            else:
                color = "#28a745"
                icon = "🟢"

            scraper_rows += f"""
            <tr>
                <td>{icon} {name}</td>
                <td style="color: {color}; font-weight: bold;">{gaps} gaps</td>
                <td>{oldest}</td>
            </tr>
            """

        html_body = f"""
        <html>
        <body>
            <h2 style="color: #ff9800;">⚠️ Scraper Gap Alert</h2>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>

            <p style="font-size: 16px;">
                <strong>{len(scrapers)} scraper(s)</strong> have accumulated
                <strong style="color: #d32f2f;">{total_gaps} gaps</strong>
                (threshold: {threshold}+ days).
            </p>

            <h3>Affected Scrapers</h3>
            <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
                <tr style="background-color: #f5f5f5;">
                    <th>Scraper</th>
                    <th>Gap Count</th>
                    <th>Oldest Gap</th>
                </tr>
                {scraper_rows}
            </table>

            <h3>Recommended Actions</h3>
            <ul>
                <li>Check proxy health - proxies may be blocked</li>
                <li>Review scraper logs in Cloud Run</li>
                <li>Verify source APIs are accessible</li>
            </ul>

            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated alert from the NBA Scraper Resilience System.
            </p>
        </body>
        </html>
        """

        subject = f"[NBA Registry WARNING] ⚠️ Scraper Gaps - {total_gaps} gaps across {len(scrapers)} scrapers"

        response = ses_client.send_email(
            Source="NBA Registry System <alert@989.ninja>",
            Destination={'ToAddresses': ['nchammas@gmail.com']},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {'Html': {'Data': html_body, 'Charset': 'UTF-8'}}
            }
        )

        logger.info(f"Gap alert email sent. MessageId: {response['MessageId']}")
        return True

    except ClientError as e:
        logger.error(f"AWS SES error: {e.response['Error']['Message']}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Failed to send gap alert: {e}", exc_info=True)
        return False


def check_and_alert_gaps(client: bigquery.Client, failures: list) -> dict:
    """Check for accumulated gaps and send alert if threshold exceeded."""
    # Filter to scrapers with >= threshold gaps
    alertable = [f for f in failures if f.get('gap_count', 0) >= GAP_ALERT_THRESHOLD]

    if not alertable:
        return {"alerted": False, "reason": "No scrapers above threshold"}

    total_gaps = sum(f.get('gap_count', 0) for f in alertable)

    gap_data = {
        "scrapers": [
            {
                "scraper_name": f["scraper_name"],
                "gap_count": f["gap_count"],
                "oldest_gap": str(f["oldest_gap_date"])
            }
            for f in alertable
        ],
        "total_gaps": total_gaps,
        "threshold": GAP_ALERT_THRESHOLD
    }

    success = send_gap_alert_email(gap_data)

    return {
        "alerted": success,
        "scrapers_alerted": len(alertable),
        "total_gaps": total_gaps
    }


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
        logger.error(f"Backfill failed for {scraper_name}/{game_date}: {e}", exc_info=True)
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
                "gaps_found": 0,
                "alert": {"alerted": False, "reason": "No gaps"}
            })

        results = {
            "status": "ok",
            "gaps_found": sum(f["gap_count"] for f in failures),
            "scrapers_with_gaps": len(failures),
            "actions": []
        }

        # Check for accumulated gaps and send alert if needed
        alert_result = check_and_alert_gaps(client, failures)
        results["alert"] = alert_result

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


@functions_framework.http
def health(request):
    """Health check endpoint for scraper_gap_backfiller."""
    return json.dumps({
        'status': 'healthy',
        'function': 'scraper_gap_backfiller',
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}
