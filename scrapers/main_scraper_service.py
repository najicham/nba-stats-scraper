"""
main_scraper_service.py

Single Cloud Run service that routes to all scrapers AND orchestration endpoints.
Version 2.4.0 - Added startup verification to detect wrong code deployment

Path: scrapers/main_scraper_service.py
"""

import os
import logging
from flask import Flask
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# Startup verification - MUST be early to detect wrong code deployment
try:
    from shared.utils.startup_verification import verify_startup
    verify_startup(
        expected_module="scrapers",
        service_name="nba-scrapers",
        version="2.4.0"
    )
except ImportError:
    # Shared module not available (local dev without full setup)
    logging.warning("startup_verification not available - running without verification")

# Import blueprints
from .routes import health, scraper, orchestration, cleanup_bp, catchup, schedule_fix


def create_app():
    """Create the main scraper routing service with orchestration."""
    app = Flask(__name__)
    if load_dotenv:
        load_dotenv()

    # Configure logging for Cloud Run
    if not app.debug:
        logging.basicConfig(level=logging.INFO)

    # Register blueprints
    app.register_blueprint(health)
    app.register_blueprint(scraper)
    app.register_blueprint(orchestration)
    app.register_blueprint(cleanup_bp)
    app.register_blueprint(catchup)
    app.register_blueprint(schedule_fix)

    return app


# Create app instance for gunicorn
app = create_app()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="NBA Scrapers Service with Phase 1 Orchestration")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 8080)))
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--host", default="0.0.0.0")
    
    args = parser.parse_args()
    
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)