"""
NBA Admin Dashboard - Pipeline Orchestration Monitoring

A Flask-based admin dashboard for monitoring the NBA Props pipeline.
Shows phase completion status, errors, scheduler history, and allows manual actions.

Refactored: 2026-01-25 - Migrated to blueprint architecture
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

# Import path setup needed before shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# Shared utilities
from shared.utils.env_validation import validate_required_env_vars
from shared.endpoints.health import create_health_blueprint
from shared.utils.prometheus_metrics import PrometheusMetrics, create_metrics_blueprint

# Validate required environment variables at startup
validate_required_env_vars(
    ['GCP_PROJECT_ID', 'ADMIN_DASHBOARD_API_KEY'],
    service_name='AdminDashboard'
)

# Initialize services - using absolute imports from repo root
from services.admin_dashboard.services.rate_limiter import init_rate_limiter
from services.admin_dashboard.services.audit_logger import get_audit_logger

# Initialize rate limiter (100 requests per minute per IP)
init_rate_limiter(requests_per_minute=100)
logger.info("Rate limiter initialized: 100 req/min per IP")

# Initialize audit logger
audit_logger = get_audit_logger()
logger.info("Audit logger initialized")


def create_app():
    """Application factory for Flask app."""
    app = Flask(__name__)

    # =============================================================================
    # HEALTH CHECK & METRICS
    # =============================================================================

    # Register health check endpoints
    app.register_blueprint(create_health_blueprint('admin-dashboard'))
    logger.info("Health check endpoints registered: /health, /ready, /health/deep")

    # Register Prometheus metrics endpoint
    prometheus_metrics = PrometheusMetrics(service_name='admin-dashboard', version='1.0.0')
    app.register_blueprint(create_metrics_blueprint(prometheus_metrics))
    logger.info("Prometheus metrics endpoint registered: /metrics, /metrics/json")

    # Register custom metrics for admin dashboard
    dashboard_api_requests = prometheus_metrics.register_counter(
        'dashboard_api_requests_total',
        'Total dashboard API requests by endpoint',
        ['endpoint', 'sport']
    )
    dashboard_action_requests = prometheus_metrics.register_counter(
        'dashboard_action_requests_total',
        'Total admin action requests',
        ['action_type', 'result']
    )
    pipeline_status_checks = prometheus_metrics.register_counter(
        'pipeline_status_checks_total',
        'Total pipeline status checks',
        ['sport', 'date_type']
    )

    # Store metrics in app config for blueprint access
    app.config['prometheus_metrics'] = prometheus_metrics
    app.config['dashboard_api_requests'] = dashboard_api_requests
    app.config['dashboard_action_requests'] = dashboard_action_requests
    app.config['pipeline_status_checks'] = pipeline_status_checks

    # =============================================================================
    # BLUEPRINT REGISTRATION
    # =============================================================================

    from services.admin_dashboard.blueprints import register_blueprints
    register_blueprints(app)
    logger.info("All blueprints registered successfully")

    return app


# Create the Flask app
app = create_app()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('FLASK_ENV') == 'development'
    logger.info(f"Starting Admin Dashboard on port {port} (debug={debug})")
    app.run(host='0.0.0.0', port=port, debug=debug)
