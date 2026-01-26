"""
scraper.py

Flask blueprint for scraper execution routes.
Extracted from main_scraper_service.py for modular routing.

Path: scrapers/routes/scraper.py
"""

import logging
from flask import Blueprint, request, jsonify, current_app

# Import from centralized registry
from scrapers.registry import (
    get_scraper_instance,
    list_scrapers,
    scraper_exists
)

# Create blueprint
scraper = Blueprint('scraper', __name__)


@scraper.route('/scrape', methods=['POST'])
def route_scraper():
    """Route to the appropriate scraper based on 'scraper' parameter."""
    try:
        # Get parameters from JSON body or query params
        params = None
        if request.is_json:
            params = request.get_json(silent=True)

        # Fallback to query params if JSON is None or not provided
        if params is None:
            params = request.args.to_dict()

        # Final safety check - ensure params is never None
        if params is None:
            params = {}

        # Get scraper name
        scraper_name = params.get("scraper")
        if not scraper_name:
            return jsonify({
                "error": "Missing required parameter: scraper",
                "available_scrapers": list_scrapers(),
                "note": "Provide scraper name in JSON body or query parameter"
            }), 400

        # Verify scraper exists
        if not scraper_exists(scraper_name):
            return jsonify({
                "error": f"Unknown scraper: {scraper_name}",
                "available_scrapers": list_scrapers()
            }), 400

        # Load scraper using registry
        try:
            current_app.logger.info(f"Loading scraper: {scraper_name}")
            scraper = get_scraper_instance(scraper_name)
            current_app.logger.info(f"Successfully loaded {scraper_name}")
        except (ImportError, AttributeError) as e:
            current_app.logger.error(f"Failed to import scraper {scraper_name}: {e}")
            return jsonify({
                "error": f"Failed to load scraper: {scraper_name}",
                "details": str(e)
            }), 500

        # Remove 'scraper' from params before passing to scraper
        scraper_params = {k: v for k, v in params.items() if k != "scraper"}

        # Add default values
        scraper_params.setdefault("group", "prod")
        scraper_params.setdefault("debug", False)

        # Set debug logging if requested
        if scraper_params.get("debug"):
            logging.getLogger().setLevel(logging.DEBUG)

        # Run the scraper
        current_app.logger.info(f"Running scraper {scraper_name} with params: {scraper_params}")
        result = scraper.run(scraper_params)

        if result:
            return jsonify({
                "status": "success",
                "message": f"{scraper_name} completed successfully",
                "scraper": scraper_name,
                "run_id": scraper.run_id,
                "data_summary": scraper.get_scraper_stats()
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": f"{scraper_name} failed",
                "scraper": scraper_name,
                "run_id": scraper.run_id
            }), 500

    except Exception as e:
        current_app.logger.error(f"Scraper routing error: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e),
            "scraper": params.get("scraper", "unknown") if params else "unknown",
            "error_type": type(e).__name__
        }), 500
