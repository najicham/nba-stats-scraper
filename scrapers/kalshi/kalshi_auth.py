"""Kalshi API Authentication Module.

Handles RSA-based authentication for Kalshi Trading API.
"""

import base64
import logging
from datetime import datetime, timezone
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from google.cloud import secretmanager

logger = logging.getLogger(__name__)


class KalshiAuthenticator:
    """RSA-based authentication for Kalshi API.

    Kalshi requires signed requests using RSA-SHA256. Each request must include:
    - KALSHI-ACCESS-KEY: The API key ID
    - KALSHI-ACCESS-SIGNATURE: Base64-encoded RSA signature
    - KALSHI-ACCESS-TIMESTAMP: ISO8601 timestamp

    The signature is computed over: {timestamp}{method}{path}
    """

    def __init__(
        self,
        api_key_id: Optional[str] = None,
        private_key_secret_name: str = "kalshi-api-private-key",
        project_id: str = "nba-props-platform"
    ):
        """Initialize authenticator.

        Args:
            api_key_id: Kalshi API key ID. If None, reads from KALSHI_API_KEY_ID
                       environment variable or Secret Manager.
            private_key_secret_name: Name of the secret containing private key.
            project_id: GCP project ID.
        """
        self.api_key_id = api_key_id
        self.private_key_secret_name = private_key_secret_name
        self.project_id = project_id
        self._private_key = None
        self._secret_client = None

    def _get_secret_client(self) -> secretmanager.SecretManagerServiceClient:
        """Get or create Secret Manager client."""
        if self._secret_client is None:
            self._secret_client = secretmanager.SecretManagerServiceClient()
        return self._secret_client

    def _load_api_key_id(self) -> str:
        """Load API key ID from environment or Secret Manager."""
        import os

        # Check environment first
        api_key_id = os.environ.get("KALSHI_API_KEY_ID")
        if api_key_id:
            return api_key_id

        # Try Secret Manager
        try:
            client = self._get_secret_client()
            secret_name = f"projects/{self.project_id}/secrets/kalshi-api-key-id/versions/latest"
            response = client.access_secret_version(request={"name": secret_name})
            return response.payload.data.decode("UTF-8").strip()
        except Exception as e:
            logger.warning(f"Could not load API key ID from Secret Manager: {e}")
            raise ValueError(
                "KALSHI_API_KEY_ID environment variable not set and "
                "kalshi-api-key-id secret not found in Secret Manager"
            )

    def _load_private_key(self):
        """Load RSA private key from Secret Manager."""
        try:
            client = self._get_secret_client()
            secret_name = f"projects/{self.project_id}/secrets/{self.private_key_secret_name}/versions/latest"
            response = client.access_secret_version(request={"name": secret_name})
            key_pem = response.payload.data.decode("UTF-8")

            self._private_key = serialization.load_pem_private_key(
                key_pem.encode(),
                password=None
            )
            logger.info("Loaded Kalshi private key from Secret Manager")
        except Exception as e:
            logger.error(f"Failed to load private key from Secret Manager: {e}")
            raise

    def get_auth_headers(self, method: str, path: str) -> dict:
        """Generate signed authentication headers for API request.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., /trade-api/v2/events)

        Returns:
            Dictionary of authentication headers.
        """
        # Load key if not already loaded
        if self._private_key is None:
            self._load_private_key()

        # Load API key ID if not set
        if self.api_key_id is None:
            self.api_key_id = self._load_api_key_id()

        # Generate timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Create message to sign: {timestamp}{method}{path}
        message = f"{timestamp}{method}{path}"

        # Sign with RSA-SHA256 using PKCS1v15 padding
        signature = self._private_key.sign(
            message.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )

        # Base64 encode signature
        signature_b64 = base64.b64encode(signature).decode("utf-8")

        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature_b64,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }


def test_authentication():
    """Test that authentication is properly configured."""
    import os

    # Check if API key ID is available
    api_key_id = os.environ.get("KALSHI_API_KEY_ID")
    if not api_key_id:
        print("KALSHI_API_KEY_ID not set, checking Secret Manager...")
        try:
            client = secretmanager.SecretManagerServiceClient()
            secret_name = "projects/nba-props-platform/secrets/kalshi-api-key-id/versions/latest"
            response = client.access_secret_version(request={"name": secret_name})
            api_key_id = response.payload.data.decode("UTF-8").strip()
            print(f"Found API key ID in Secret Manager: {api_key_id[:8]}...")
        except Exception as e:
            print(f"API key ID not found: {e}")
            return False
    else:
        print(f"Found API key ID in environment: {api_key_id[:8]}...")

    # Check private key
    try:
        client = secretmanager.SecretManagerServiceClient()
        secret_name = "projects/nba-props-platform/secrets/kalshi-api-private-key/versions/latest"
        response = client.access_secret_version(request={"name": secret_name})
        key_pem = response.payload.data.decode("UTF-8")

        # Try to load it
        private_key = serialization.load_pem_private_key(
            key_pem.encode(),
            password=None
        )
        print(f"Private key loaded successfully: {private_key.key_size} bits")
    except Exception as e:
        print(f"Private key error: {e}")
        return False

    # Try generating headers
    try:
        auth = KalshiAuthenticator(api_key_id=api_key_id)
        headers = auth.get_auth_headers("GET", "/trade-api/v2/exchange/status")
        print(f"Generated auth headers successfully")
        print(f"  Timestamp: {headers['KALSHI-ACCESS-TIMESTAMP']}")
        print(f"  Signature: {headers['KALSHI-ACCESS-SIGNATURE'][:20]}...")
        return True
    except Exception as e:
        print(f"Header generation error: {e}")
        return False


if __name__ == "__main__":
    test_authentication()
