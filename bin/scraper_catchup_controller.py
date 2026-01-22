#!/usr/bin/env python3
"""
Scraper Catch-Up Controller

Orchestrates catch-up retries for scrapers with missing data.
This is the missing piece that connects Cloud Scheduler to actual retries.

Flow:
1. Cloud Scheduler triggers this controller with scraper_name + lookback_days
2. Controller runs completeness check to find dates with missing data
3. For each missing date, controller invokes the scraper service

Usage:
    # CLI - check and retry BDL for last 3 days
    python bin/scraper_catchup_controller.py bdl_box_scores --days 3

    # CLI - dry run (just show what would be retried)
    python bin/scraper_catchup_controller.py bdl_box_scores --days 3 --dry-run

    # As Flask endpoint (for Cloud Scheduler)
    POST /catchup
    {"scraper_name": "bdl_box_scores", "lookback_days": 3, "workflow": "bdl_catchup_midday"}

Created: January 22, 2026
Purpose: Bridge between Cloud Scheduler and scraper retry logic
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================================
# Configuration
# ============================================================================

# Scraper service endpoints (Cloud Run)
# These are discovered dynamically or set via environment
SCRAPER_ENDPOINTS = {
    "bdl_box_scores": "/bdl_box_scores",
    "nbac_gamebook_pdf": "/nbac_gamebook_pdf",
    "oddsa_player_props": "/oddsa_player_props",
}

# Default service URL (override via SCRAPER_SERVICE_URL env var)
DEFAULT_SERVICE_URL = os.getenv(
    "SCRAPER_SERVICE_URL",
    "https://nba-phase1-scrapers-756957797294.us-west2.run.app"
)


def get_service_url() -> str:
    """Get the scraper service base URL."""
    return os.getenv("SCRAPER_SERVICE_URL", DEFAULT_SERVICE_URL)


def get_id_token() -> Optional[str]:
    """Get an identity token for authenticating to Cloud Run."""
    try:
        import google.auth.transport.requests
        import google.oauth2.id_token

        auth_req = google.auth.transport.requests.Request()
        target_audience = get_service_url()
        token = google.oauth2.id_token.fetch_id_token(auth_req, target_audience)
        return token
    except Exception as e:
        logger.warning(f"Could not get ID token (may be running locally): {e}")
        return None


# ============================================================================
# Completeness Check
# ============================================================================

def find_missing_dates(scraper_name: str, lookback_days: int = 3) -> List[str]:
    """
    Find dates with missing data for the specified scraper.

    Returns:
        List of date strings (YYYY-MM-DD) that need retrying
    """
    try:
        from google.cloud import bigquery
        client = bigquery.Client()
    except Exception as e:
        logger.error(f"Failed to initialize BigQuery client: {e}")
        raise

    # Load config to get the completeness query
    config_path = PROJECT_ROOT / "shared" / "config" / "scraper_retry_config.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    import yaml
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Get completeness query for this scraper
    queries = config.get("completeness_queries", {})
    query_template = queries.get(scraper_name)

    if not query_template:
        raise ValueError(f"No completeness query configured for {scraper_name}")

    # Format query with lookback days
    query = query_template.format(lookback_days=lookback_days)

    logger.info(f"Running completeness check for {scraper_name} (last {lookback_days} days)...")

    try:
        results = client.query(query).result()

        missing_dates = set()
        for row in results:
            if hasattr(row, 'game_date'):
                missing_dates.add(str(row.game_date))

        missing_dates = sorted(missing_dates)
        logger.info(f"Found {len(missing_dates)} dates with missing {scraper_name} data")

        return missing_dates

    except Exception as e:
        logger.error(f"Completeness query failed: {e}")
        raise


# ============================================================================
# Scraper Invocation
# ============================================================================

def invoke_scraper(
    scraper_name: str,
    date: str,
    workflow: str,
    dry_run: bool = False,
    timeout: int = 300
) -> Dict[str, Any]:
    """
    Invoke a scraper for a specific date.

    Args:
        scraper_name: Name of the scraper (e.g., 'bdl_box_scores')
        date: Date to scrape (YYYY-MM-DD)
        workflow: Workflow name for tracking
        dry_run: If True, don't actually invoke
        timeout: Request timeout in seconds

    Returns:
        Dict with status and response info
    """
    endpoint = SCRAPER_ENDPOINTS.get(scraper_name)
    if not endpoint:
        return {
            "status": "error",
            "message": f"Unknown scraper: {scraper_name}",
            "date": date
        }

    url = f"{get_service_url()}{endpoint}"

    payload = {
        "date": date,
        "workflow": workflow,
    }

    if dry_run:
        logger.info(f"[DRY RUN] Would invoke {scraper_name} for {date}")
        return {
            "status": "dry_run",
            "date": date,
            "url": url,
            "payload": payload
        }

    logger.info(f"Invoking {scraper_name} for {date}...")

    try:
        headers = {"Content-Type": "application/json"}

        # Add authentication if running in GCP
        token = get_id_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=timeout
        )

        if response.status_code == 200:
            logger.info(f"  Success: {scraper_name} for {date}")
            return {
                "status": "success",
                "date": date,
                "response_code": response.status_code,
            }
        else:
            logger.warning(f"  Failed: {scraper_name} for {date} - HTTP {response.status_code}")
            return {
                "status": "failed",
                "date": date,
                "response_code": response.status_code,
                "response_text": response.text[:500] if response.text else None
            }

    except requests.Timeout:
        logger.error(f"  Timeout: {scraper_name} for {date}")
        return {
            "status": "timeout",
            "date": date,
        }
    except Exception as e:
        logger.error(f"  Error: {scraper_name} for {date} - {e}")
        return {
            "status": "error",
            "date": date,
            "error": str(e)
        }


# ============================================================================
# Main Controller Logic
# ============================================================================

def run_catchup(
    scraper_name: str,
    lookback_days: int = 3,
    workflow: str = "catchup",
    dry_run: bool = False,
    delay_between_calls: float = 2.0
) -> Dict[str, Any]:
    """
    Run catch-up for a scraper.

    Args:
        scraper_name: Name of the scraper
        lookback_days: Days to look back for missing data
        workflow: Workflow name for tracking
        dry_run: If True, don't actually invoke scrapers
        delay_between_calls: Seconds to wait between scraper calls

    Returns:
        Summary of catch-up results
    """
    start_time = datetime.now()
    results = {
        "scraper_name": scraper_name,
        "lookback_days": lookback_days,
        "workflow": workflow,
        "dry_run": dry_run,
        "started_at": start_time.isoformat(),
        "dates_checked": [],
        "dates_retried": [],
        "successes": 0,
        "failures": 0,
        "errors": [],
    }

    try:
        # Step 1: Find missing dates
        missing_dates = find_missing_dates(scraper_name, lookback_days)
        results["dates_checked"] = missing_dates

        if not missing_dates:
            logger.info(f"No missing data found for {scraper_name}")
            results["status"] = "complete"
            results["message"] = "No missing data to retry"
            return results

        logger.info(f"Will retry {len(missing_dates)} dates: {missing_dates}")

        # Step 2: Invoke scraper for each missing date
        for i, date in enumerate(missing_dates):
            result = invoke_scraper(
                scraper_name=scraper_name,
                date=date,
                workflow=workflow,
                dry_run=dry_run
            )

            results["dates_retried"].append({
                "date": date,
                "result": result
            })

            if result.get("status") == "success" or result.get("status") == "dry_run":
                results["successes"] += 1
            else:
                results["failures"] += 1
                if result.get("error"):
                    results["errors"].append(f"{date}: {result.get('error')}")

            # Delay between calls to avoid overwhelming the service
            if i < len(missing_dates) - 1 and not dry_run:
                time.sleep(delay_between_calls)

        results["status"] = "complete" if results["failures"] == 0 else "partial"
        results["message"] = f"Retried {len(missing_dates)} dates: {results['successes']} succeeded, {results['failures']} failed"

    except Exception as e:
        logger.error(f"Catch-up failed: {e}")
        results["status"] = "error"
        results["message"] = str(e)

    results["completed_at"] = datetime.now().isoformat()
    results["duration_seconds"] = (datetime.now() - start_time).total_seconds()

    return results


# ============================================================================
# Flask Endpoint (for Cloud Scheduler)
# ============================================================================

def create_flask_app():
    """Create Flask app for Cloud Run deployment."""
    from flask import Flask, request, jsonify

    app = Flask(__name__)

    @app.route("/catchup", methods=["POST"])
    def catchup_endpoint():
        """
        Catch-up endpoint for Cloud Scheduler.

        Expected payload:
        {
            "scraper_name": "bdl_box_scores",
            "lookback_days": 3,
            "workflow": "bdl_catchup_midday"
        }
        """
        try:
            data = request.get_json() or {}

            scraper_name = data.get("scraper_name")
            if not scraper_name:
                return jsonify({"error": "scraper_name is required"}), 400

            lookback_days = data.get("lookback_days", 3)
            workflow = data.get("workflow", "catchup")

            result = run_catchup(
                scraper_name=scraper_name,
                lookback_days=lookback_days,
                workflow=workflow,
                dry_run=False
            )

            status_code = 200 if result.get("status") != "error" else 500
            return jsonify(result), status_code

        except Exception as e:
            logger.error(f"Catch-up endpoint error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "healthy"}), 200

    return app


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Run catch-up retries for scrapers with missing data"
    )
    parser.add_argument(
        "scraper",
        nargs="?",
        help="Scraper name to retry (e.g., bdl_box_scores)"
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=3,
        help="Number of days to look back (default: 3)"
    )
    parser.add_argument(
        "--workflow", "-w",
        default="manual_catchup",
        help="Workflow name for tracking (default: manual_catchup)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be retried without actually invoking scrapers"
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Run as Flask server"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for Flask server (default: 8080)"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available scrapers"
    )

    args = parser.parse_args()

    if args.list:
        print("\nAvailable scrapers for catch-up:")
        for name in SCRAPER_ENDPOINTS.keys():
            print(f"  - {name}")
        print()
        return 0

    if args.serve:
        app = create_flask_app()
        app.run(host="0.0.0.0", port=args.port, debug=True)
        return 0

    if not args.scraper:
        parser.print_help()
        print("\nError: Specify a scraper name or use --serve")
        return 1

    # Run catch-up
    result = run_catchup(
        scraper_name=args.scraper,
        lookback_days=args.days,
        workflow=args.workflow,
        dry_run=args.dry_run
    )

    # Print results
    print("\n" + "=" * 60)
    print("CATCH-UP RESULTS")
    print("=" * 60)
    print(f"Scraper: {result['scraper_name']}")
    print(f"Status: {result['status']}")
    print(f"Message: {result.get('message', 'N/A')}")
    print(f"Dates checked: {len(result.get('dates_checked', []))}")
    print(f"Successes: {result.get('successes', 0)}")
    print(f"Failures: {result.get('failures', 0)}")

    if result.get('errors'):
        print("\nErrors:")
        for err in result['errors']:
            print(f"  - {err}")

    print("=" * 60 + "\n")

    # Return exit code based on status
    return 0 if result.get("status") == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
