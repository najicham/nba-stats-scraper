# shared/utils/env_validation.py
"""
Environment variable validation utilities.

Provides functions to validate required environment variables at service startup,
ensuring all necessary configuration is present before the service begins processing.
"""

import os
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class MissingEnvironmentVariablesError(Exception):
    """
    Raised when required environment variables are not set.

    Contains the list of missing variable names for clear error reporting.
    """

    def __init__(self, missing_vars: List[str], service_name: Optional[str] = None):
        self.missing_vars = missing_vars
        self.service_name = service_name

        # Build clear error message
        if service_name:
            message = f"[{service_name}] Missing required environment variables: {', '.join(missing_vars)}"
        else:
            message = f"Missing required environment variables: {', '.join(missing_vars)}"

        super().__init__(message)


def validate_required_env_vars(
    required_vars: List[str],
    service_name: Optional[str] = None,
    raise_on_missing: bool = True
) -> List[str]:
    """
    Validate that required environment variables are set.

    This function should be called at service startup (e.g., at the top of main())
    to ensure all necessary configuration is present before processing begins.

    Args:
        required_vars: List of environment variable names that must be set.
                      Variables with empty string values are considered unset.
        service_name: Optional service name for clearer error messages.
        raise_on_missing: If True (default), raises MissingEnvironmentVariablesError
                         when variables are missing. If False, logs an error and
                         returns the list of missing variables.

    Returns:
        List of missing variable names (empty if all are set).

    Raises:
        MissingEnvironmentVariablesError: If raise_on_missing is True and
                                          any required variables are missing.

    Example:
        >>> # At the top of main() or service initialization
        >>> validate_required_env_vars(
        ...     ['GCP_PROJECT_ID', 'ADMIN_DASHBOARD_API_KEY'],
        ...     service_name='AdminDashboard'
        ... )

        >>> # With graceful handling
        >>> missing = validate_required_env_vars(
        ...     ['GCP_PROJECT_ID'],
        ...     raise_on_missing=False
        ... )
        >>> if missing:
        ...     # Handle missing config (e.g., use defaults or exit)
        ...     pass
    """
    missing_vars = []

    for var_name in required_vars:
        value = os.environ.get(var_name)
        # Treat empty string as unset
        if value is None or value.strip() == '':
            missing_vars.append(var_name)

    if missing_vars:
        error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
        if service_name:
            error_msg = f"[{service_name}] {error_msg}"

        logger.error(error_msg)

        # Log each missing variable for easier debugging
        for var in missing_vars:
            logger.error(f"  - {var} is not set")

        if raise_on_missing:
            raise MissingEnvironmentVariablesError(missing_vars, service_name)
    else:
        if service_name:
            logger.info(f"[{service_name}] All required environment variables validated successfully")
        else:
            logger.debug("All required environment variables validated successfully")

    return missing_vars


def get_required_env_var(var_name: str, service_name: Optional[str] = None) -> str:
    """
    Get a single required environment variable, raising an error if not set.

    Args:
        var_name: Name of the environment variable.
        service_name: Optional service name for clearer error messages.

    Returns:
        The value of the environment variable.

    Raises:
        MissingEnvironmentVariablesError: If the variable is not set.
    """
    value = os.environ.get(var_name)

    if value is None or value.strip() == '':
        raise MissingEnvironmentVariablesError([var_name], service_name)

    return value
