"""
health.py

Flask blueprint for health check and scraper listing endpoints.
Extracted from main_scraper_service.py

Routes:
- / (GET) - Health check endpoint
- /health (GET) - Health check endpoint
- /scrapers (GET) - List all available scrapers

Path: scrapers/routes/health.py
"""

from datetime import datetime, timezone
from flask import Blueprint, jsonify

from scrapers.registry import (
    get_scraper_info,
    list_scrapers
)

from orchestration.config_loader import WorkflowConfig


# Create blueprint
health = Blueprint('health', __name__)


# Lazy load orchestration config
_config = None

def get_config():
    global _config
    if _config is None:
        _config = WorkflowConfig()
    return _config


@health.route('/', methods=['GET'])
@health.route('/health', methods=['GET'])
def health_check():
    """Enhanced health check with orchestration component status."""
    try:
        # Check orchestration components
        config = get_config()
        enabled_workflows = config.get_enabled_workflows()

        health_status = {
            "status": "healthy",
            "service": "nba-scrapers",
            "version": "2.3.0",
            "deployment": "orchestration-phase1-enabled",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {
                "scrapers": {
                    "available": len(list_scrapers()),
                    "status": "operational"
                },
                "orchestration": {
                    "master_controller": "available",
                    "workflow_executor": "available",
                    "cleanup_processor": "available",
                    "schedule_locker": "available",
                    "enabled_workflows": len(enabled_workflows),
                    "workflows": enabled_workflows
                }
            }
        }

        return jsonify(health_status), 200

    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"Health check failed: {e}")
        return jsonify({
            "status": "degraded",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 503

@health.route('/scrapers', methods=['GET'])
def list_all_scrapers():
    """List all available scrapers with their module information."""
    scraper_info = get_scraper_info()
    return jsonify(scraper_info), 200
