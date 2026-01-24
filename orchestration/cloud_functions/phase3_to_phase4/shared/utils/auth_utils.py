# shared/utils/auth_utils.py
"""
Authentication utilities for NBA platform
"""

import os
import logging
from typing import Optional

from google.auth import default
from google.auth.credentials import Credentials
from google.oauth2 import service_account

logger = logging.getLogger(__name__)


def get_service_account_credentials(
    service_account_path: Optional[str] = None
) -> Optional[Credentials]:
    """
    Get Google Cloud service account credentials
    
    Args:
        service_account_path: Path to service account JSON file
                            If None, uses default credential chain
    
    Returns:
        Google Cloud credentials or None if failed
    """
    try:
        if service_account_path and os.path.exists(service_account_path):
            # Use explicit service account file
            credentials = service_account.Credentials.from_service_account_file(
                service_account_path
            )
            logger.info(f"Using service account credentials from {service_account_path}")
            return credentials
        else:
            # Use default credential chain (environment, metadata server, etc.)
            credentials, project = default()
            logger.info(f"Using default credentials for project {project}")
            return credentials
            
    except Exception as e:
        logger.error(f"Failed to get credentials: {e}", exc_info=True)
        return None


def get_project_id() -> Optional[str]:
    """
    Get the current Google Cloud project ID
    
    Returns:
        Project ID or None if not found
    """
    # Try environment variable first
    project_id = os.getenv('GOOGLE_CLOUD_PROJECT') or os.getenv('PROJECT_ID')
    if project_id:
        return project_id
    
    # Try default credentials
    try:
        _, project_id = default()
        return project_id
    except Exception as e:
        logger.warning(f"Could not determine project ID: {e}")
        return None


def is_authenticated() -> bool:
    """
    Check if we have valid Google Cloud credentials
    
    Returns:
        True if authenticated
    """
    try:
        credentials = get_service_account_credentials()
        return credentials is not None
    except Exception as e:
        logger.debug(f"Authentication check failed: {e}")
        return False


def get_api_key(secret_name: str, default_env_var: Optional[str] = None) -> Optional[str]:
    """
    Get API key from Secret Manager or environment variable
    
    Args:
        secret_name: Name of secret in Secret Manager
        default_env_var: Fallback environment variable name
        
    Returns:
        API key or None if not found
    """
    # Try environment variable first (for local development)
    if default_env_var:
        api_key = os.getenv(default_env_var)
        if api_key:
            logger.info(f"Using API key from environment variable {default_env_var}")
            return api_key
    
    # Try Secret Manager
    try:
        from google.cloud import secretmanager
        
        client = secretmanager.SecretManagerServiceClient()
        project_id = get_project_id()
        
        if not project_id:
            logger.error("No project ID available for Secret Manager", exc_info=True)
            return None
        
        secret_path = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": secret_path})
        
        api_key = response.payload.data.decode("UTF-8")
        logger.info(f"Retrieved API key from Secret Manager: {secret_name}")
        return api_key
        
    except Exception as e:
        logger.error(f"Failed to get API key from Secret Manager ({secret_name}): {e}", exc_info=True)
        return None


def setup_google_cloud_auth():
    """
    Set up Google Cloud authentication for the current environment
    
    This function ensures proper authentication is configured and logs
    the authentication status.
    """
    project_id = get_project_id()
    if not project_id:
        logger.warning("No Google Cloud project ID found")
        return False
    
    if not is_authenticated():
        logger.error("Google Cloud authentication not available", exc_info=True)
        return False
    
    logger.info(f"Google Cloud authentication configured for project: {project_id}")
    return True