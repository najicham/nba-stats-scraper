# scrapers/utils/proxy_utils.py
"""
Proxy configuration for web scrapers with circuit breaker pattern.

Supports multiple proxy providers with automatic fallback and circuit breaker:
1. ProxyFuel (datacenter rotating) - Primary, already paid
2. Decodo/Smartproxy (residential) - Fallback for blocked sites
3. [Future] Bright Data - Premium fallback

Circuit Breaker Pattern:
- CLOSED: Proxy is working, use normally
- OPEN: Proxy is blocked for target, skip it
- HALF_OPEN: Testing if proxy has recovered

Environment Variables:
- DECODO_PROXY_CREDENTIALS: "username:password" for Decodo (from Secret Manager)
- PROXYFUEL_CREDENTIALS: "username:password" for ProxyFuel (optional override)
- BRIGHTDATA_CREDENTIALS: "username:password" for Bright Data (future)

Usage:
    from scrapers.utils.proxy_utils import get_proxy_urls, ProxyCircuitBreaker

    # Get all proxies
    proxies = get_proxy_urls()

    # With circuit breaker
    circuit_breaker = ProxyCircuitBreaker()
    proxies = get_proxy_urls_with_circuit_breaker("api.bettingpros.com", circuit_breaker)
"""

import os
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import List, Optional, Dict
from urllib.parse import quote, urlparse

logger = logging.getLogger(__name__)

# Decodo ports - different ports may use different IP pools
DECODO_PORTS = [10001, 10002, 10003]

# Circuit breaker configuration
CIRCUIT_FAILURE_THRESHOLD = 3  # Consecutive failures to open circuit
CIRCUIT_COOLDOWN_MINUTES = 5   # Time before testing OPEN circuit


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "CLOSED"       # Proxy is working, use normally
    OPEN = "OPEN"           # Proxy is blocked, skip it
    HALF_OPEN = "HALF_OPEN" # Testing if proxy recovered


@dataclass
class CircuitStatus:
    """Status of a circuit for a proxy+target combination."""
    proxy_provider: str
    target_host: str
    state: CircuitState
    failure_count: int
    last_failure_at: Optional[datetime]
    last_success_at: Optional[datetime]
    opened_at: Optional[datetime]


# ============================================================================
# Proxy Provider Abstraction
# ============================================================================

class ProxyProvider(ABC):
    """Abstract base class for proxy providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging and circuit breaker."""
        pass

    @property
    @abstractmethod
    def priority(self) -> int:
        """Priority order (lower = try first)."""
        pass

    @abstractmethod
    def get_proxy_urls(self) -> List[str]:
        """Get list of proxy URLs for this provider."""
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if this provider has valid credentials configured."""
        pass


class ProxyFuelProvider(ProxyProvider):
    """ProxyFuel datacenter proxy provider."""

    @property
    def name(self) -> str:
        return "proxyfuel"

    @property
    def priority(self) -> int:
        return 1  # Primary - cheapest

    def get_proxy_urls(self) -> List[str]:
        creds = os.getenv("PROXYFUEL_CREDENTIALS", "nchammas.gmail.com:bbuyfd")
        if creds:
            return [f"http://{creds}@gate2.proxyfuel.com:2000"]
        return []

    def is_configured(self) -> bool:
        return bool(os.getenv("PROXYFUEL_CREDENTIALS", "nchammas.gmail.com:bbuyfd"))


class DecodoProvider(ProxyProvider):
    """Decodo/Smartproxy residential proxy provider."""

    @property
    def name(self) -> str:
        return "decodo"

    @property
    def priority(self) -> int:
        return 2  # Secondary - residential

    def get_proxy_urls(self) -> List[str]:
        creds = os.getenv("DECODO_PROXY_CREDENTIALS")
        if not creds:
            return []

        encoded_creds = _url_encode_credentials(creds)
        return [f"http://{encoded_creds}@gate.decodo.com:{port}" for port in DECODO_PORTS]

    def is_configured(self) -> bool:
        return bool(os.getenv("DECODO_PROXY_CREDENTIALS"))


class BrightDataProvider(ProxyProvider):
    """Bright Data proxy provider (future integration)."""

    @property
    def name(self) -> str:
        return "brightdata"

    @property
    def priority(self) -> int:
        return 3  # Tertiary - premium fallback

    def get_proxy_urls(self) -> List[str]:
        creds = os.getenv("BRIGHTDATA_CREDENTIALS")
        if not creds:
            return []

        # Bright Data format: username:password@brd.superproxy.io:22225
        encoded_creds = _url_encode_credentials(creds)
        return [f"http://{encoded_creds}@brd.superproxy.io:22225"]

    def is_configured(self) -> bool:
        return bool(os.getenv("BRIGHTDATA_CREDENTIALS"))


# Global registry of providers
PROXY_PROVIDERS: List[ProxyProvider] = [
    ProxyFuelProvider(),
    DecodoProvider(),
    BrightDataProvider(),
]


# ============================================================================
# Circuit Breaker
# ============================================================================

class ProxyCircuitBreaker:
    """
    Circuit breaker for proxy+target combinations.

    Prevents using proxies that are known to be blocked for specific targets.
    Uses BigQuery for persistent state (across Cloud Run instances).
    """

    def __init__(self, use_bigquery: bool = True):
        """
        Initialize circuit breaker.

        Args:
            use_bigquery: If True, persist state to BigQuery. If False, use in-memory only.
        """
        self.use_bigquery = use_bigquery
        self._local_cache: Dict[str, CircuitStatus] = {}
        self._bq_client = None

    def _get_bq_client(self):
        """Lazy-load BigQuery client."""
        if self._bq_client is None and self.use_bigquery:
            try:
                from google.cloud import bigquery
                self._bq_client = bigquery.Client()
            except Exception as e:
                logger.warning(f"Failed to init BigQuery client for circuit breaker: {e}")
                self.use_bigquery = False
        return self._bq_client

    def _cache_key(self, proxy_provider: str, target_host: str) -> str:
        """Generate cache key for proxy+target combination."""
        return f"{proxy_provider}:{target_host}"

    def get_circuit_state(self, proxy_provider: str, target_host: str) -> CircuitState:
        """
        Get current circuit state for a proxy+target combination.

        Args:
            proxy_provider: Provider name (e.g., "proxyfuel", "decodo")
            target_host: Target hostname (e.g., "api.bettingpros.com")

        Returns:
            Current circuit state
        """
        status = self._get_status(proxy_provider, target_host)
        if not status:
            return CircuitState.CLOSED

        # Check if OPEN circuit should transition to HALF_OPEN
        if status.state == CircuitState.OPEN and status.opened_at:
            cooldown_elapsed = datetime.now(timezone.utc) - status.opened_at
            if cooldown_elapsed >= timedelta(minutes=CIRCUIT_COOLDOWN_MINUTES):
                logger.info(f"Circuit {proxy_provider}+{target_host}: OPEN → HALF_OPEN (cooldown elapsed)")
                self._update_state(proxy_provider, target_host, CircuitState.HALF_OPEN)
                return CircuitState.HALF_OPEN

        return status.state

    def should_skip_proxy(self, proxy_provider: str, target_host: str) -> bool:
        """
        Check if a proxy should be skipped for a target.

        Returns True if circuit is OPEN (skip proxy).
        Returns False if circuit is CLOSED or HALF_OPEN (try proxy).
        """
        state = self.get_circuit_state(proxy_provider, target_host)
        return state == CircuitState.OPEN

    def record_success(self, proxy_provider: str, target_host: str):
        """Record a successful request - closes circuit if HALF_OPEN."""
        status = self._get_status(proxy_provider, target_host)
        current_state = status.state if status else CircuitState.CLOSED

        if current_state == CircuitState.HALF_OPEN:
            logger.info(f"Circuit {proxy_provider}+{target_host}: HALF_OPEN → CLOSED (success)")

        self._upsert_status(proxy_provider, target_host, CircuitStatus(
            proxy_provider=proxy_provider,
            target_host=target_host,
            state=CircuitState.CLOSED,
            failure_count=0,
            last_failure_at=status.last_failure_at if status else None,
            last_success_at=datetime.now(timezone.utc),
            opened_at=None
        ))

    def record_failure(self, proxy_provider: str, target_host: str):
        """Record a failed request - may open circuit if threshold reached."""
        status = self._get_status(proxy_provider, target_host)
        failure_count = (status.failure_count if status else 0) + 1
        current_state = status.state if status else CircuitState.CLOSED
        now = datetime.now(timezone.utc)

        # Determine new state
        if current_state == CircuitState.HALF_OPEN:
            # Failed while testing - back to OPEN
            new_state = CircuitState.OPEN
            opened_at = now
            logger.warning(f"Circuit {proxy_provider}+{target_host}: HALF_OPEN → OPEN (test failed)")
        elif failure_count >= CIRCUIT_FAILURE_THRESHOLD:
            # Threshold reached - open circuit
            new_state = CircuitState.OPEN
            opened_at = now
            logger.warning(f"Circuit {proxy_provider}+{target_host}: CLOSED → OPEN ({failure_count} failures)")
        else:
            new_state = CircuitState.CLOSED
            opened_at = None

        self._upsert_status(proxy_provider, target_host, CircuitStatus(
            proxy_provider=proxy_provider,
            target_host=target_host,
            state=new_state,
            failure_count=failure_count,
            last_failure_at=now,
            last_success_at=status.last_success_at if status else None,
            opened_at=opened_at
        ))

    def _get_status(self, proxy_provider: str, target_host: str) -> Optional[CircuitStatus]:
        """Get current status from cache or BigQuery."""
        cache_key = self._cache_key(proxy_provider, target_host)

        # Check local cache first
        if cache_key in self._local_cache:
            return self._local_cache[cache_key]

        # Try BigQuery
        if self.use_bigquery:
            client = self._get_bq_client()
            if client:
                try:
                    query = """
                    SELECT proxy_provider, target_host, circuit_state, failure_count,
                           last_failure_at, last_success_at, opened_at
                    FROM `nba-props-platform.nba_orchestration.proxy_circuit_breaker`
                    WHERE proxy_provider = @proxy_provider AND target_host = @target_host
                    """
                    from google.cloud import bigquery
                    job_config = bigquery.QueryJobConfig(query_parameters=[
                        bigquery.ScalarQueryParameter("proxy_provider", "STRING", proxy_provider),
                        bigquery.ScalarQueryParameter("target_host", "STRING", target_host),
                    ])
                    result = list(client.query(query, job_config=job_config).result())
                    if result:
                        row = result[0]
                        status = CircuitStatus(
                            proxy_provider=row.proxy_provider,
                            target_host=row.target_host,
                            state=CircuitState(row.circuit_state),
                            failure_count=row.failure_count or 0,
                            last_failure_at=row.last_failure_at,
                            last_success_at=row.last_success_at,
                            opened_at=row.opened_at
                        )
                        self._local_cache[cache_key] = status
                        return status
                except Exception as e:
                    logger.debug(f"BigQuery circuit breaker query failed: {e}")

        return None

    def _update_state(self, proxy_provider: str, target_host: str, new_state: CircuitState):
        """Update just the state field."""
        status = self._get_status(proxy_provider, target_host)
        if status:
            status.state = new_state
            if new_state == CircuitState.HALF_OPEN:
                status.opened_at = None
            self._upsert_status(proxy_provider, target_host, status)

    def _upsert_status(self, proxy_provider: str, target_host: str, status: CircuitStatus):
        """Upsert status to cache and BigQuery."""
        cache_key = self._cache_key(proxy_provider, target_host)
        self._local_cache[cache_key] = status

        if self.use_bigquery:
            client = self._get_bq_client()
            if client:
                try:
                    query = """
                    MERGE `nba-props-platform.nba_orchestration.proxy_circuit_breaker` T
                    USING (SELECT @proxy_provider as proxy_provider, @target_host as target_host) S
                    ON T.proxy_provider = S.proxy_provider AND T.target_host = S.target_host
                    WHEN MATCHED THEN
                        UPDATE SET
                            circuit_state = @circuit_state,
                            failure_count = @failure_count,
                            last_failure_at = @last_failure_at,
                            last_success_at = @last_success_at,
                            opened_at = @opened_at,
                            updated_at = CURRENT_TIMESTAMP()
                    WHEN NOT MATCHED THEN
                        INSERT (proxy_provider, target_host, circuit_state, failure_count,
                                last_failure_at, last_success_at, opened_at, updated_at)
                        VALUES (@proxy_provider, @target_host, @circuit_state, @failure_count,
                                @last_failure_at, @last_success_at, @opened_at, CURRENT_TIMESTAMP())
                    """
                    from google.cloud import bigquery
                    job_config = bigquery.QueryJobConfig(query_parameters=[
                        bigquery.ScalarQueryParameter("proxy_provider", "STRING", proxy_provider),
                        bigquery.ScalarQueryParameter("target_host", "STRING", target_host),
                        bigquery.ScalarQueryParameter("circuit_state", "STRING", status.state.value),
                        bigquery.ScalarQueryParameter("failure_count", "INT64", status.failure_count),
                        bigquery.ScalarQueryParameter("last_failure_at", "TIMESTAMP", status.last_failure_at),
                        bigquery.ScalarQueryParameter("last_success_at", "TIMESTAMP", status.last_success_at),
                        bigquery.ScalarQueryParameter("opened_at", "TIMESTAMP", status.opened_at),
                    ])
                    client.query(query, job_config=job_config).result()
                except Exception as e:
                    logger.warning(f"Failed to update circuit breaker in BigQuery: {e}")


# ============================================================================
# Helper Functions
# ============================================================================

def _url_encode_credentials(creds: str) -> str:
    """URL encode username:password, handling special characters."""
    if ":" not in creds:
        return creds
    username, password = creds.split(":", 1)
    # URL encode password (special chars like ~ need encoding for proxy auth)
    return f"{quote(username, safe='')}:{quote(password, safe='')}"


def extract_provider_from_url(proxy_url: str) -> str:
    """Extract provider name from proxy URL."""
    if "proxyfuel" in proxy_url.lower():
        return "proxyfuel"
    elif "decodo" in proxy_url.lower() or "smartproxy" in proxy_url.lower():
        return "decodo"
    elif "brightdata" in proxy_url.lower() or "brd.superproxy" in proxy_url.lower():
        return "brightdata"
    return "unknown"


# ============================================================================
# Public API (Backward Compatible)
# ============================================================================

def get_proxy_urls() -> List[str]:
    """
    Returns a list of proxy URLs to try in order.

    Order:
    1. ProxyFuel (datacenter) - cheaper, try first
    2. Decodo (residential) - multiple ports for different IP pools
    3. Bright Data (if configured) - premium fallback
    """
    proxies = []

    # Get from all configured providers in priority order
    for provider in sorted(PROXY_PROVIDERS, key=lambda p: p.priority):
        if provider.is_configured():
            proxies.extend(provider.get_proxy_urls())

    if not proxies:
        logger.warning("No proxy credentials configured!")

    return proxies


def get_proxy_urls_with_circuit_breaker(
    target_host: str,
    circuit_breaker: Optional[ProxyCircuitBreaker] = None
) -> List[str]:
    """
    Get proxy URLs filtered by circuit breaker state.

    Args:
        target_host: Target hostname to check circuits against
        circuit_breaker: Circuit breaker instance (creates new if None)

    Returns:
        List of proxy URLs with OPEN circuits filtered out
    """
    if circuit_breaker is None:
        circuit_breaker = ProxyCircuitBreaker()

    all_proxies = get_proxy_urls()
    filtered = []

    for proxy_url in all_proxies:
        provider = extract_provider_from_url(proxy_url)
        if not circuit_breaker.should_skip_proxy(provider, target_host):
            filtered.append(proxy_url)
        else:
            logger.debug(f"Skipping {provider} for {target_host} (circuit OPEN)")

    if not filtered:
        # All circuits open - return all proxies as last resort
        logger.warning(f"All circuits OPEN for {target_host}, trying all proxies anyway")
        return all_proxies

    return filtered


def get_decodo_proxy_url(port: int = 10001) -> Optional[str]:
    """
    Get Decodo proxy URL specifically (for cases where residential is required).

    Args:
        port: Decodo port (10001-10010), different ports may use different IP pools
    """
    decodo_creds = os.getenv("DECODO_PROXY_CREDENTIALS")
    if decodo_creds:
        encoded_creds = _url_encode_credentials(decodo_creds)
        return f"http://{encoded_creds}@gate.decodo.com:{port}"
    return None


def get_proxyfuel_proxy_url() -> Optional[str]:
    """Get ProxyFuel proxy URL specifically."""
    proxyfuel_creds = os.getenv("PROXYFUEL_CREDENTIALS", "nchammas.gmail.com:bbuyfd")
    if proxyfuel_creds:
        return f"http://{proxyfuel_creds}@gate2.proxyfuel.com:2000"
    return None


def get_configured_providers() -> List[str]:
    """Get list of configured provider names."""
    return [p.name for p in PROXY_PROVIDERS if p.is_configured()]
