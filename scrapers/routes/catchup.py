"""
catchup.py

Flask blueprint for catch-up endpoint (retrying scrapers with missing data).
Extracted from main_scraper_service.py lines 484-683.

Path: scrapers/routes/catchup.py
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from flask import Blueprint, request, jsonify
from google.cloud import bigquery
import yaml

# Import from centralized registry
from scrapers.registry import (
    get_scraper_instance,
    scraper_exists
)

# Create blueprint
catchup = Blueprint('catchup', __name__)


@catchup.route('/catchup', methods=['POST'])
def catchup_scraper():
    """
    Catch-up endpoint for retrying scrapers with missing data.
    Called by Cloud Scheduler at various times throughout the day.

    Expected JSON body:
    {
        "scraper_name": "bdl_box_scores",
        "lookback_days": 3,
        "workflow": "bdl_catchup_midday"
    }

    Flow:
    1. Runs completeness check to find dates with missing data
    2. For each missing date, invokes the scraper via /scrape
    3. Returns summary of retries
    """
    try:
        data = request.get_json() or {}

        scraper_name = data.get('scraper_name')
        if not scraper_name:
            return jsonify({
                "error": "Missing required parameter: scraper_name",
                "available_scrapers": ["bdl_box_scores", "nbac_gamebook_pdf", "oddsa_player_props"]
            }), 400

        lookback_days = data.get('lookback_days', 3)
        workflow = data.get('workflow', 'catchup')

        logging.info(f"🔄 Catch-up: {scraper_name} (lookback: {lookback_days} days, workflow: {workflow})")

        # Step 1: Find missing dates using completeness query
        try:
            bq_client = bigquery.Client()

            # Load config to get the completeness query
            config_path = Path(__file__).parent.parent.parent / "shared" / "config" / "scraper_retry_config.yaml"

            if not config_path.exists():
                return jsonify({
                    "status": "error",
                    "message": f"Config not found: {config_path}",
                    "scraper_name": scraper_name
                }), 500

            with open(config_path) as f:
                config = yaml.safe_load(f)

            # Get completeness query for this scraper
            queries = config.get("completeness_queries", {})
            query_template = queries.get(scraper_name)

            if not query_template:
                return jsonify({
                    "status": "error",
                    "message": f"No completeness query configured for {scraper_name}",
                    "scraper_name": scraper_name
                }), 400

            # Format query with lookback days
            query = query_template.format(lookback_days=lookback_days)
            logging.info(f"Running completeness check for {scraper_name}...")

            results = bq_client.query(query).result()

            missing_dates = set()
            for row in results:
                if hasattr(row, 'game_date'):
                    missing_dates.add(str(row.game_date))

            missing_dates = sorted(missing_dates)
            logging.info(f"Found {len(missing_dates)} dates with missing {scraper_name} data")

        except FileNotFoundError as e:
            logging.error(f"Completeness config not found: {e}")
            return jsonify({
                "status": "error",
                "message": f"Config file not found: {e}",
                "scraper_name": scraper_name
            }), 500
        except (KeyError, TypeError) as e:
            logging.error(f"Completeness config parse error: {e}")
            return jsonify({
                "status": "error",
                "message": f"Config parse error: {e}",
                "scraper_name": scraper_name
            }), 500
        except Exception as e:
            logging.error(f"Completeness check failed ({type(e).__name__}): {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": f"Completeness check failed: {e}",
                "scraper_name": scraper_name
            }), 500

        if not missing_dates:
            logging.info(f"✅ No missing data found for {scraper_name}")
            return jsonify({
                "status": "complete",
                "message": "No missing data to retry",
                "scraper_name": scraper_name,
                "lookback_days": lookback_days,
                "dates_checked": 0
            }), 200

        logging.info(f"Found {len(missing_dates)} dates with missing data: {missing_dates}")

        # Step 2: Invoke scraper for each missing date
        results = []
        successes = 0
        failures = 0

        for date in missing_dates:
            try:
                # Get scraper instance and run it
                if not scraper_exists(scraper_name):
                    results.append({"date": date, "status": "error", "message": f"Unknown scraper: {scraper_name}"})
                    failures += 1
                    continue

                logging.info(f"  Retrying {scraper_name} for {date}...")
                scraper = get_scraper_instance(scraper_name)

                # Run scraper with date and workflow
                scraper_params = {
                    "date": date,
                    "workflow": workflow,
                    "group": "prod"
                }

                result = scraper.run(scraper_params)

                if result:
                    results.append({
                        "date": date,
                        "status": "success",
                        "run_id": scraper.run_id,
                        "stats": scraper.get_scraper_stats()
                    })
                    successes += 1
                else:
                    results.append({
                        "date": date,
                        "status": "failed",
                        "run_id": scraper.run_id
                    })
                    failures += 1

            except (ImportError, AttributeError) as e:
                logging.error(f"  Failed to load scraper for {date}: {e}")
                results.append({
                    "date": date,
                    "status": "error",
                    "message": f"Scraper load error: {e}"
                })
                failures += 1
            except (ValueError, KeyError, TypeError) as e:
                logging.error(f"  Data error retrying {date}: {e}")
                results.append({
                    "date": date,
                    "status": "error",
                    "message": f"Data error: {e}"
                })
                failures += 1
            except Exception as e:
                logging.error(f"  Failed to retry {date} ({type(e).__name__}): {e}", exc_info=True)
                results.append({
                    "date": date,
                    "status": "error",
                    "message": str(e)
                })
                failures += 1

        status = "complete" if failures == 0 else "partial"
        logging.info(f"🔄 Catch-up complete: {successes} succeeded, {failures} failed")

        return jsonify({
            "status": status,
            "scraper_name": scraper_name,
            "lookback_days": lookback_days,
            "workflow": workflow,
            "dates_retried": len(missing_dates),
            "successes": successes,
            "failures": failures,
            "results": results
        }), 200

    except Exception as e:
        logging.error(f"Catch-up failed: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e),
            "error_type": type(e).__name__
        }), 500
