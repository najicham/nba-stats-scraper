"""
NBA Admin Dashboard - Application Factory

Creates and configures the Flask application with all blueprints registered.

Usage:
    from services.admin_dashboard.app import create_app

    app = create_app()

    if __name__ == '__main__':
        app.run()
"""

import os
import sys
import logging

from flask import Flask

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_app(config=None):
    """
    Create and configure the Flask application.

    Args:
        config: Optional configuration dictionary

    Returns:
        Configured Flask application
    """
    # Import path setup needed before shared imports
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

    # Validate required environment variables
    from shared.utils.env_validation import validate_required_env_vars
    validate_required_env_vars(
        ['GCP_PROJECT_ID', 'ADMIN_DASHBOARD_API_KEY'],
        service_name='AdminDashboard'
    )

    # Create Flask app
    app = Flask(__name__)

    # Apply configuration
    app.config.update(
        SECRET_KEY=os.environ.get('FLASK_SECRET_KEY', os.urandom(32)),
        JSON_SORT_KEYS=False,
        JSONIFY_PRETTYPRINT_REGULAR=True,
    )

    if config:
        app.config.update(config)

    # Initialize rate limiter
    from .services.rate_limiter import init_rate_limiter
    rate_limit_rpm = int(os.environ.get('RATE_LIMIT_RPM', '100'))
    init_rate_limiter(requests_per_minute=rate_limit_rpm)
    logger.info(f"Rate limiter initialized: {rate_limit_rpm} requests/minute")

    # Register health check blueprint
    try:
        from shared.endpoints.health import create_health_blueprint, HealthChecker
        health_bp = create_health_blueprint(HealthChecker())
        app.register_blueprint(health_bp)
        logger.info("Health check blueprint registered")
    except ImportError as e:
        logger.warning(f"Could not import health blueprint: {e}")

    # Register all blueprints
    from .blueprints import register_blueprints
    register_blueprints(app)
    logger.info("All blueprints registered")

    # Log registered routes in debug mode
    if app.debug:
        for rule in app.url_map.iter_rules():
            logger.debug(f"Route: {rule.rule} -> {rule.endpoint}")

    return app


def run_development_server():
    """Run the development server."""
    app = create_app()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)


if __name__ == '__main__':
    run_development_server()
