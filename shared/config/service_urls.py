"""
Cloud Run Service URLs Configuration
=====================================
Centralized configuration for Cloud Run service URLs.

Provides consistent access to service endpoints across the platform,
with support for environment variable overrides.

Usage:
    from shared.config.service_urls import get_service_url, Services

    # Get a service URL
    url = get_service_url(Services.PREDICTION_COORDINATOR)

    # With environment override
    url = get_service_url(Services.PHASE2_PROCESSORS)  # checks PHASE2_PROCESSORS_URL env var first

Version: 1.0
Created: 2026-01-24
"""

import os
from typing import Optional


# Default project number (used in Cloud Run URLs)
# Read from environment variable with fallback to default
DEFAULT_PROJECT_NUMBER = os.environ.get('GCP_PROJECT_NUMBER', '756957797294')


class Services:
    """Cloud Run service identifiers."""
    # Phase 1: Scrapers
    PHASE1_SCRAPERS = 'nba-phase1-scrapers'

    # Phase 2: Raw Processors
    PHASE2_PROCESSORS = 'nba-phase2-raw-processors'

    # Phase 3: Analytics
    PHASE3_ANALYTICS = 'nba-phase3-analytics-processors'

    # Phase 4: Precompute
    PHASE4_PRECOMPUTE = 'nba-phase4-precompute-processors'

    # Phase 5: Predictions
    PREDICTION_COORDINATOR = 'prediction-coordinator'
    PREDICTION_WORKER = 'prediction-worker'

    # Phase 6: Export/Grading
    PHASE6_EXPORT = 'phase6-export'

    # Orchestration services
    SELF_HEAL = 'self-heal'
    PIPELINE_RECONCILIATION = 'pipeline-reconciliation'
    ADMIN_DASHBOARD = 'nba-admin-dashboard'

    # MLB Services
    MLB_PHASE3_ANALYTICS = 'mlb-phase3-analytics-processors'
    MLB_PHASE4_PRECOMPUTE = 'mlb-phase4-precompute-processors'
    MLB_PREDICTION_WORKER = 'mlb-prediction-worker'
    MLB_GRADING_SERVICE = 'mlb-phase6-grading'
    MLB_SELF_HEAL = 'mlb-self-heal'


# Default Cloud Run URLs (project-specific)
_DEFAULT_URLS = {
    # NBA Services
    Services.PHASE1_SCRAPERS: f'https://{Services.PHASE1_SCRAPERS}-{DEFAULT_PROJECT_NUMBER}.us-west2.run.app',
    Services.PHASE2_PROCESSORS: f'https://{Services.PHASE2_PROCESSORS}-{DEFAULT_PROJECT_NUMBER}.us-west2.run.app',
    Services.PHASE3_ANALYTICS: f'https://{Services.PHASE3_ANALYTICS}-{DEFAULT_PROJECT_NUMBER}.us-west2.run.app',
    Services.PHASE4_PRECOMPUTE: f'https://{Services.PHASE4_PRECOMPUTE}-{DEFAULT_PROJECT_NUMBER}.us-west2.run.app',
    Services.PREDICTION_COORDINATOR: f'https://{Services.PREDICTION_COORDINATOR}-{DEFAULT_PROJECT_NUMBER}.us-west2.run.app',
    Services.PREDICTION_WORKER: f'https://{Services.PREDICTION_WORKER}-{DEFAULT_PROJECT_NUMBER}.us-west2.run.app',
    Services.PHASE6_EXPORT: f'https://{Services.PHASE6_EXPORT}-{DEFAULT_PROJECT_NUMBER}.us-west2.run.app',
    # Orchestration Services
    Services.SELF_HEAL: f'https://{Services.SELF_HEAL}-{DEFAULT_PROJECT_NUMBER}.us-west2.run.app',
    Services.PIPELINE_RECONCILIATION: f'https://{Services.PIPELINE_RECONCILIATION}-{DEFAULT_PROJECT_NUMBER}.us-west2.run.app',
    Services.ADMIN_DASHBOARD: f'https://{Services.ADMIN_DASHBOARD}-{DEFAULT_PROJECT_NUMBER}.us-west2.run.app',
    # MLB Services
    Services.MLB_PHASE3_ANALYTICS: f'https://{Services.MLB_PHASE3_ANALYTICS}-{DEFAULT_PROJECT_NUMBER}.us-west2.run.app',
    Services.MLB_PHASE4_PRECOMPUTE: f'https://{Services.MLB_PHASE4_PRECOMPUTE}-{DEFAULT_PROJECT_NUMBER}.us-west2.run.app',
    Services.MLB_PREDICTION_WORKER: f'https://{Services.MLB_PREDICTION_WORKER}-{DEFAULT_PROJECT_NUMBER}.us-west2.run.app',
    Services.MLB_GRADING_SERVICE: f'https://{Services.MLB_GRADING_SERVICE}-{DEFAULT_PROJECT_NUMBER}.us-west2.run.app',
    Services.MLB_SELF_HEAL: f'https://{Services.MLB_SELF_HEAL}-{DEFAULT_PROJECT_NUMBER}.us-west2.run.app',
}

# Environment variable names for each service (allows override)
_ENV_VAR_NAMES = {
    # NBA Services
    Services.PHASE1_SCRAPERS: 'PHASE1_SCRAPERS_URL',
    Services.PHASE2_PROCESSORS: 'PHASE2_PROCESSORS_URL',
    Services.PHASE3_ANALYTICS: 'PHASE3_ANALYTICS_URL',
    Services.PHASE4_PRECOMPUTE: 'PHASE4_PRECOMPUTE_URL',
    Services.PREDICTION_COORDINATOR: 'PREDICTION_COORDINATOR_URL',
    Services.PREDICTION_WORKER: 'PREDICTION_WORKER_URL',
    Services.PHASE6_EXPORT: 'PHASE6_EXPORT_URL',
    # Orchestration Services
    Services.SELF_HEAL: 'SELF_HEAL_URL',
    Services.PIPELINE_RECONCILIATION: 'PIPELINE_RECONCILIATION_URL',
    Services.ADMIN_DASHBOARD: 'ADMIN_DASHBOARD_URL',
    # MLB Services
    Services.MLB_PHASE3_ANALYTICS: 'MLB_PHASE3_ANALYTICS_URL',
    Services.MLB_PHASE4_PRECOMPUTE: 'MLB_PHASE4_PRECOMPUTE_URL',
    Services.MLB_PREDICTION_WORKER: 'MLB_PREDICTION_WORKER_URL',
    Services.MLB_GRADING_SERVICE: 'MLB_GRADING_SERVICE_URL',
    Services.MLB_SELF_HEAL: 'MLB_SELF_HEAL_URL',
}


def get_service_url(service: str, fallback: Optional[str] = None) -> str:
    """
    Get Cloud Run service URL.

    Checks for environment variable override first, then falls back to default.

    Args:
        service: Service identifier from Services class
        fallback: Optional fallback URL if service not found

    Returns:
        Service URL string

    Example:
        url = get_service_url(Services.PREDICTION_COORDINATOR)
        # Returns env var PREDICTION_COORDINATOR_URL if set,
        # otherwise https://prediction-coordinator-756957797294.us-west2.run.app
    """
    # Check environment variable override
    env_var = _ENV_VAR_NAMES.get(service)
    if env_var:
        env_url = os.environ.get(env_var)
        if env_url:
            return env_url

    # Return default URL or fallback
    return _DEFAULT_URLS.get(service, fallback or '')


def get_all_service_urls() -> dict:
    """
    Get all configured service URLs (with env overrides applied).

    Returns:
        Dict mapping service name to URL
    """
    return {
        service: get_service_url(service)
        for service in _DEFAULT_URLS.keys()
    }


# External API endpoints (non-Cloud Run)
class ExternalAPIs:
    """External API endpoints."""
    SENDGRID = 'https://api.sendgrid.com/v3/mail/send'
    BALLDONTLIE = 'https://api.balldontlie.io/v1'
    BALLDONTLIE_LIVE = 'https://api.balldontlie.io/v1/box_scores/live'


def get_external_api(api_name: str) -> str:
    """
    Get external API URL.

    Args:
        api_name: API identifier (e.g., 'sendgrid', 'balldontlie')

    Returns:
        API URL string
    """
    api_map = {
        'sendgrid': ExternalAPIs.SENDGRID,
        'balldontlie': ExternalAPIs.BALLDONTLIE,
        'balldontlie_live': ExternalAPIs.BALLDONTLIE_LIVE,
    }
    return api_map.get(api_name.lower(), '')
