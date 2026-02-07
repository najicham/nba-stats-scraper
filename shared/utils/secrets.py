"""
Centralized secret management using GCP Secret Manager.

Usage:
    from shared.utils.secrets import get_secret_manager

    secrets = get_secret_manager()
    api_key = secrets.get_odds_api_key()
"""

from google.cloud import secretmanager
from functools import lru_cache
import os
import logging

logger = logging.getLogger(__name__)


class SecretManager:
    """Centralized secret management using GCP Secret Manager."""

    def __init__(self):
        from shared.config.gcp_config import get_project_id
        self.project_id = get_project_id()
        self.client = secretmanager.SecretManagerServiceClient()
        logger.info(f"SecretManager initialized for project: {self.project_id}")

    @lru_cache(maxsize=32)
    def get_secret(self, secret_name: str, version: str = 'latest', fallback_env_var: str = None) -> str:
        """
        Retrieve secret from Secret Manager (cached), with fallback to environment variable.

        Args:
            secret_name: Name of the secret in GCP Secret Manager
            version: Version to retrieve (default: 'latest')
            fallback_env_var: Environment variable to fall back to if Secret Manager fails

        Returns:
            Secret value as string

        Raises:
            ValueError: If secret retrieval fails and no fallback is available
        """
        name = f"projects/{self.project_id}/secrets/{secret_name}/versions/{version}"

        try:
            response = self.client.access_secret_version(request={"name": name})
            secret_value = response.payload.data.decode('UTF-8')
            logger.debug(f"Retrieved secret from Secret Manager: {secret_name}")
            return secret_value
        except Exception as e:
            # Try fallback to environment variable
            if fallback_env_var:
                env_value = os.environ.get(fallback_env_var)
                if env_value:
                    logger.warning(f"Secret Manager unavailable for {secret_name}, using env var {fallback_env_var}")
                    return env_value

            logger.error(f"Failed to retrieve secret {secret_name} from Secret Manager or env: {e}", exc_info=True)
            raise ValueError(f"Failed to retrieve secret {secret_name}: {e}")

    def get_odds_api_key(self) -> str:
        """Get Odds API key."""
        return self.get_secret('odds-api-key', fallback_env_var='ODDS_API_KEY')

    def get_brevo_smtp_password(self) -> str:
        """Get Brevo SMTP password."""
        return self.get_secret('brevo-smtp-password', fallback_env_var='BREVO_SMTP_PASSWORD')

    def get_aws_ses_access_key_id(self) -> str:
        """Get AWS SES access key ID."""
        return self.get_secret('aws-ses-access-key-id', fallback_env_var='AWS_SES_ACCESS_KEY_ID')

    def get_aws_ses_secret_key(self) -> str:
        """Get AWS SES secret access key."""
        return self.get_secret('aws-ses-secret-access-key', fallback_env_var='AWS_SES_SECRET_ACCESS_KEY')

    def get_anthropic_api_key(self) -> str:
        """Get Anthropic API key."""
        return self.get_secret('anthropic-api-key', fallback_env_var='ANTHROPIC_API_KEY')

    def get_slack_webhook_url(self) -> str:
        """Get Slack webhook URL."""
        return self.get_secret('slack-webhook-url', fallback_env_var='SLACK_WEBHOOK_URL')

    def get_slack_webhook_url_reminders(self) -> str:
        """Get Slack webhook URL for reminders channel."""
        return self.get_secret('slack-webhook-url-reminders', fallback_env_var='SLACK_WEBHOOK_URL_REMINDERS')

    def get_coordinator_api_key(self) -> str:
        """Get Coordinator API key."""
        return self.get_secret('coordinator-api-key', fallback_env_var='COORDINATOR_API_KEY')


# Singleton instance
_secret_manager = None


def get_secret_manager() -> SecretManager:
    """Get singleton SecretManager instance."""
    global _secret_manager
    if _secret_manager is None:
        _secret_manager = SecretManager()
    return _secret_manager
