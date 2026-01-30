"""
Startup verification for Cloud Run services.
Logs which module is being loaded to help detect deployment issues.

Usage:
    from shared.utils.startup_verification import verify_startup

    # At the top of your main.py
    verify_startup(
        expected_module="coordinator",
        service_name="prediction-coordinator"
    )
"""
import logging
import os
import sys
from typing import Optional

logger = logging.getLogger(__name__)


def verify_startup(
    expected_module: str,
    service_name: str,
    version: Optional[str] = None
) -> None:
    """
    Log startup verification info. Call this at service startup.

    This helps detect deployment issues where the wrong code is deployed
    to a service (e.g., coordinator code deployed to worker service).

    Args:
        expected_module: The module name that should be loaded (e.g., 'coordinator')
        service_name: The Cloud Run service name
        version: Optional version string for the module
    """
    build_commit = os.environ.get('BUILD_COMMIT', 'unknown')
    build_timestamp = os.environ.get('BUILD_TIMESTAMP', 'unknown')
    k_service = os.environ.get('K_SERVICE', 'local')
    k_revision = os.environ.get('K_REVISION', 'local')

    # Detect environment
    if k_service == 'local':
        environment = 'local'
    else:
        environment = 'cloud_run'

    logger.info("=" * 50)
    logger.info("STARTUP VERIFICATION")
    logger.info("=" * 50)
    logger.info(f"Service name:     {service_name}")
    logger.info(f"Expected module:  {expected_module}")
    if version:
        logger.info(f"Module version:   {version}")
    logger.info(f"Environment:      {environment}")
    logger.info(f"K_SERVICE:        {k_service}")
    logger.info(f"K_REVISION:       {k_revision}")
    logger.info(f"BUILD_COMMIT:     {build_commit}")
    logger.info(f"BUILD_TIMESTAMP:  {build_timestamp}")
    logger.info(f"Python version:   {sys.version.split()[0]}")
    logger.info(f"Working dir:      {os.getcwd()}")
    logger.info(f"Python path:      {sys.path[:3]}...")
    logger.info("=" * 50)

    # Warn if K_SERVICE doesn't match expected service name
    if environment == 'cloud_run' and k_service != service_name:
        logger.warning(
            f"DEPLOYMENT MISMATCH: K_SERVICE={k_service} but "
            f"expected service_name={service_name}. "
            "This may indicate wrong code was deployed!"
        )


def get_build_info() -> dict:
    """
    Get build information as a dictionary.
    Useful for including in health check responses.

    Returns:
        Dictionary with build_commit, build_timestamp, k_service, k_revision
    """
    return {
        'build_commit': os.environ.get('BUILD_COMMIT', 'unknown'),
        'build_timestamp': os.environ.get('BUILD_TIMESTAMP', 'unknown'),
        'k_service': os.environ.get('K_SERVICE', 'local'),
        'k_revision': os.environ.get('K_REVISION', 'local'),
    }
