# shared/utils/proxy_manager.py
"""
Proxy Manager with Health Tracking and Intelligent Rotation.

This module provides a sophisticated proxy management system with:
- Proxy health scoring based on success/failure rates
- Cooldown periods after failures
- Rotation strategy preferring healthy proxies
- Health metrics for monitoring
- Thread-safe operation

Usage:
    from shared.utils.proxy_manager import get_proxy_manager, ProxyManager

    # Get singleton instance
    manager = get_proxy_manager()

    # Get next proxy for a target (health-weighted)
    proxy = manager.get_proxy_for_target("api.example.com")

    # Record results
    manager.record_success(proxy_url, target_host, response_time_ms=150)
    manager.record_failure(proxy_url, target_host, error_type="timeout")

    # Get health metrics
    metrics = manager.get_health_metrics()
"""

import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

class ProxyConfig:
    """Configuration constants for proxy management."""

    # Health scoring
    INITIAL_HEALTH_SCORE = 100.0
    MIN_HEALTH_SCORE = 0.0
    MAX_HEALTH_SCORE = 100.0

    # Score adjustments
    SUCCESS_SCORE_BOOST = 5.0       # Points gained per success
    FAILURE_SCORE_PENALTY = 15.0    # Points lost per failure
    TIMEOUT_SCORE_PENALTY = 10.0    # Points lost for timeout
    SLOW_RESPONSE_PENALTY = 2.0     # Points lost for slow responses

    # Response time thresholds (ms)
    SLOW_RESPONSE_THRESHOLD_MS = 5000
    VERY_SLOW_RESPONSE_THRESHOLD_MS = 10000

    # Cooldown configuration
    BASE_COOLDOWN_SECONDS = 60      # Base cooldown after failure
    MAX_COOLDOWN_SECONDS = 600      # Maximum cooldown (10 minutes)
    COOLDOWN_MULTIPLIER = 2.0       # Exponential backoff multiplier

    # Health thresholds for rotation
    HEALTHY_THRESHOLD = 70.0        # Score above this is "healthy"
    DEGRADED_THRESHOLD = 40.0       # Score below this is "degraded"
    CRITICAL_THRESHOLD = 20.0       # Score below this triggers cooldown

    # Rotation settings
    MIN_REQUESTS_FOR_SCORING = 5    # Min requests before health affects rotation
    SCORE_DECAY_RATE = 0.01         # Score decay per minute of inactivity
    SCORE_RECOVERY_RATE = 1.0       # Score recovery per minute in cooldown

    # Provider Decodo ports
    DECODO_PORTS = [10001, 10002, 10003]


# ============================================================================
# Data Classes
# ============================================================================

class ProxyStatus(str, Enum):
    """Proxy availability status."""
    AVAILABLE = "available"     # Ready to use
    COOLDOWN = "cooldown"       # Temporarily unavailable
    DEGRADED = "degraded"       # Working but with issues
    UNAVAILABLE = "unavailable" # Not configured or offline


@dataclass
class ProxyStats:
    """Statistics for a single proxy."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    timeout_count: int = 0
    total_response_time_ms: int = 0
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_requests == 0:
            return 100.0
        return (self.successful_requests / self.total_requests) * 100.0

    @property
    def average_response_time_ms(self) -> float:
        """Calculate average response time."""
        if self.successful_requests == 0:
            return 0.0
        return self.total_response_time_ms / self.successful_requests


@dataclass
class ProxyHealth:
    """Health information for a proxy."""
    proxy_url: str
    provider: str
    health_score: float = ProxyConfig.INITIAL_HEALTH_SCORE
    status: ProxyStatus = ProxyStatus.AVAILABLE
    cooldown_until: Optional[datetime] = None
    cooldown_count: int = 0  # Number of times entered cooldown
    stats: ProxyStats = field(default_factory=ProxyStats)
    per_target_stats: Dict[str, ProxyStats] = field(default_factory=dict)

    def is_available(self) -> bool:
        """Check if proxy is available for use."""
        if self.status == ProxyStatus.UNAVAILABLE:
            return False
        if self.status == ProxyStatus.COOLDOWN:
            if self.cooldown_until and datetime.now(timezone.utc) < self.cooldown_until:
                return False
            # Cooldown expired, reset status
            self.status = ProxyStatus.AVAILABLE
            self.cooldown_until = None
        return True

    def get_target_stats(self, target_host: str) -> ProxyStats:
        """Get or create stats for a specific target."""
        if target_host not in self.per_target_stats:
            self.per_target_stats[target_host] = ProxyStats()
        return self.per_target_stats[target_host]


@dataclass
class ProxyHealthMetrics:
    """Aggregated health metrics for monitoring."""
    timestamp: datetime
    total_proxies: int
    available_proxies: int
    degraded_proxies: int
    cooldown_proxies: int
    unavailable_proxies: int
    average_health_score: float
    total_requests: int
    total_successes: int
    total_failures: int
    overall_success_rate: float
    providers: Dict[str, Dict[str, any]] = field(default_factory=dict)


# ============================================================================
# Proxy Provider Handling
# ============================================================================

def _url_encode_credentials(creds: str) -> str:
    """URL encode username:password, handling special characters."""
    if ":" not in creds:
        return creds
    username, password = creds.split(":", 1)
    return f"{quote(username, safe='')}:{quote(password, safe='')}"


def extract_provider_from_url(proxy_url: str) -> str:
    """Extract provider name from proxy URL."""
    url_lower = proxy_url.lower()
    if "proxyfuel" in url_lower:
        return "proxyfuel"
    elif "decodo" in url_lower or "smartproxy" in url_lower:
        return "decodo"
    elif "brightdata" in url_lower or "brd.superproxy" in url_lower:
        return "brightdata"
    return "unknown"


def get_configured_proxy_urls() -> List[Tuple[str, str]]:
    """
    Get all configured proxy URLs with their providers.

    Returns:
        List of (proxy_url, provider_name) tuples
    """
    proxies = []

    # ProxyFuel (primary)
    proxyfuel_creds = os.getenv("PROXYFUEL_CREDENTIALS", "nchammas.gmail.com:bbuyfd")
    if proxyfuel_creds:
        proxies.append((f"http://{proxyfuel_creds}@gate2.proxyfuel.com:2000", "proxyfuel"))

    # Decodo/Smartproxy (secondary)
    decodo_creds = os.getenv("DECODO_PROXY_CREDENTIALS")
    if decodo_creds:
        encoded_creds = _url_encode_credentials(decodo_creds)
        for port in ProxyConfig.DECODO_PORTS:
            proxies.append((f"http://{encoded_creds}@gate.decodo.com:{port}", "decodo"))

    # Bright Data (tertiary)
    brightdata_creds = os.getenv("BRIGHTDATA_CREDENTIALS")
    if brightdata_creds:
        encoded_creds = _url_encode_credentials(brightdata_creds)
        proxies.append((f"http://{encoded_creds}@brd.superproxy.io:22225", "brightdata"))

    return proxies


# ============================================================================
# Proxy Manager
# ============================================================================

class ProxyManager:
    """
    Intelligent proxy manager with health tracking and rotation.

    Features:
    - Health scoring based on success/failure history
    - Cooldown periods for failing proxies
    - Weighted rotation preferring healthy proxies
    - Per-target tracking for site-specific issues
    - Thread-safe operation
    """

    def __init__(self, enable_bigquery_logging: bool = True):
        """
        Initialize proxy manager.

        Args:
            enable_bigquery_logging: If True, log metrics to BigQuery
        """
        self._lock = threading.RLock()
        self._proxies: Dict[str, ProxyHealth] = {}
        self._enable_bigquery = enable_bigquery_logging
        self._bq_client = None
        self._last_metrics_log = None
        self._metrics_log_interval = timedelta(minutes=5)

        # Initialize proxies
        self._load_proxies()

        logger.info(f"ProxyManager initialized with {len(self._proxies)} proxies")

    def _load_proxies(self):
        """Load and initialize all configured proxies."""
        with self._lock:
            configured = get_configured_proxy_urls()
            for proxy_url, provider in configured:
                if proxy_url not in self._proxies:
                    self._proxies[proxy_url] = ProxyHealth(
                        proxy_url=proxy_url,
                        provider=provider
                    )

    def _get_bq_client(self):
        """Lazy-load BigQuery client."""
        if self._bq_client is None and self._enable_bigquery:
            try:
                from google.cloud import bigquery
                self._bq_client = bigquery.Client()
            except Exception as e:
                logger.warning(f"Failed to initialize BigQuery client: {e}")
                self._enable_bigquery = False
        return self._bq_client

    # ========================================================================
    # Health Score Management
    # ========================================================================

    def _calculate_health_score(self, health: ProxyHealth, target_host: Optional[str] = None) -> float:
        """
        Calculate current health score for a proxy.

        Args:
            health: ProxyHealth object
            target_host: Optional target for target-specific scoring

        Returns:
            Health score (0-100)
        """
        stats = health.get_target_stats(target_host) if target_host else health.stats

        # Start with base score
        score = health.health_score

        # Apply time-based decay for inactive proxies
        if stats.last_used_at:
            inactive_minutes = (datetime.now(timezone.utc) - stats.last_used_at).total_seconds() / 60
            decay = min(inactive_minutes * ProxyConfig.SCORE_DECAY_RATE, 10)  # Max 10 point decay
            score = max(score - decay, health.health_score - 10)  # Limit decay

        # Apply recovery for proxies in/exiting cooldown
        if health.cooldown_until and datetime.now(timezone.utc) >= health.cooldown_until:
            recovery_minutes = (datetime.now(timezone.utc) - health.cooldown_until).total_seconds() / 60
            recovery = recovery_minutes * ProxyConfig.SCORE_RECOVERY_RATE
            score = min(score + recovery, ProxyConfig.HEALTHY_THRESHOLD)

        return max(ProxyConfig.MIN_HEALTH_SCORE, min(ProxyConfig.MAX_HEALTH_SCORE, score))

    def _update_health_score(
        self,
        proxy_url: str,
        success: bool,
        response_time_ms: Optional[int] = None,
        error_type: Optional[str] = None
    ):
        """Update health score based on request result."""
        with self._lock:
            if proxy_url not in self._proxies:
                return

            health = self._proxies[proxy_url]

            if success:
                # Boost score on success
                health.health_score = min(
                    health.health_score + ProxyConfig.SUCCESS_SCORE_BOOST,
                    ProxyConfig.MAX_HEALTH_SCORE
                )

                # Penalty for slow responses
                if response_time_ms:
                    if response_time_ms > ProxyConfig.VERY_SLOW_RESPONSE_THRESHOLD_MS:
                        health.health_score -= ProxyConfig.SLOW_RESPONSE_PENALTY * 2
                    elif response_time_ms > ProxyConfig.SLOW_RESPONSE_THRESHOLD_MS:
                        health.health_score -= ProxyConfig.SLOW_RESPONSE_PENALTY

                # Reset cooldown counter on consistent success
                if health.stats.consecutive_successes >= 3:
                    health.cooldown_count = max(0, health.cooldown_count - 1)
            else:
                # Penalty based on error type
                if error_type == "timeout":
                    penalty = ProxyConfig.TIMEOUT_SCORE_PENALTY
                else:
                    penalty = ProxyConfig.FAILURE_SCORE_PENALTY

                health.health_score = max(
                    health.health_score - penalty,
                    ProxyConfig.MIN_HEALTH_SCORE
                )

                # Check if should enter cooldown
                if health.health_score < ProxyConfig.CRITICAL_THRESHOLD:
                    self._enter_cooldown(health)

            # Update status based on score
            if health.status != ProxyStatus.COOLDOWN:
                if health.health_score >= ProxyConfig.HEALTHY_THRESHOLD:
                    health.status = ProxyStatus.AVAILABLE
                elif health.health_score >= ProxyConfig.DEGRADED_THRESHOLD:
                    health.status = ProxyStatus.DEGRADED

    def _enter_cooldown(self, health: ProxyHealth):
        """Put a proxy into cooldown."""
        health.cooldown_count += 1
        cooldown_seconds = min(
            ProxyConfig.BASE_COOLDOWN_SECONDS * (ProxyConfig.COOLDOWN_MULTIPLIER ** (health.cooldown_count - 1)),
            ProxyConfig.MAX_COOLDOWN_SECONDS
        )
        health.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)
        health.status = ProxyStatus.COOLDOWN

        logger.warning(
            f"Proxy {health.provider} entered cooldown for {cooldown_seconds}s "
            f"(score={health.health_score:.1f}, count={health.cooldown_count})"
        )

    # ========================================================================
    # Request Recording
    # ========================================================================

    def record_success(
        self,
        proxy_url: str,
        target_host: str,
        response_time_ms: Optional[int] = None
    ):
        """
        Record a successful proxy request.

        Args:
            proxy_url: The proxy URL used
            target_host: Target hostname
            response_time_ms: Response time in milliseconds
        """
        with self._lock:
            if proxy_url not in self._proxies:
                return

            health = self._proxies[proxy_url]
            now = datetime.now(timezone.utc)

            # Update global stats
            health.stats.total_requests += 1
            health.stats.successful_requests += 1
            health.stats.consecutive_successes += 1
            health.stats.consecutive_failures = 0
            health.stats.last_success_at = now
            health.stats.last_used_at = now
            if response_time_ms:
                health.stats.total_response_time_ms += response_time_ms

            # Update target-specific stats
            target_stats = health.get_target_stats(target_host)
            target_stats.total_requests += 1
            target_stats.successful_requests += 1
            target_stats.consecutive_successes += 1
            target_stats.consecutive_failures = 0
            target_stats.last_success_at = now
            target_stats.last_used_at = now
            if response_time_ms:
                target_stats.total_response_time_ms += response_time_ms

            # Update health score
            self._update_health_score(proxy_url, True, response_time_ms)

        # Log to BigQuery (outside lock)
        self._log_to_bigquery(proxy_url, target_host, True, response_time_ms)

    def record_failure(
        self,
        proxy_url: str,
        target_host: str,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        http_status_code: Optional[int] = None
    ):
        """
        Record a failed proxy request.

        Args:
            proxy_url: The proxy URL used
            target_host: Target hostname
            error_type: Type of error (e.g., "timeout", "forbidden")
            error_message: Detailed error message
            http_status_code: HTTP status code if available
        """
        with self._lock:
            if proxy_url not in self._proxies:
                return

            health = self._proxies[proxy_url]
            now = datetime.now(timezone.utc)

            # Update global stats
            health.stats.total_requests += 1
            health.stats.failed_requests += 1
            health.stats.consecutive_failures += 1
            health.stats.consecutive_successes = 0
            health.stats.last_failure_at = now
            health.stats.last_used_at = now
            if error_type == "timeout":
                health.stats.timeout_count += 1

            # Update target-specific stats
            target_stats = health.get_target_stats(target_host)
            target_stats.total_requests += 1
            target_stats.failed_requests += 1
            target_stats.consecutive_failures += 1
            target_stats.consecutive_successes = 0
            target_stats.last_failure_at = now
            target_stats.last_used_at = now
            if error_type == "timeout":
                target_stats.timeout_count += 1

            # Update health score
            self._update_health_score(proxy_url, False, error_type=error_type)

        # Log to BigQuery (outside lock)
        self._log_to_bigquery(
            proxy_url, target_host, False,
            error_type=error_type,
            error_message=error_message,
            http_status_code=http_status_code
        )

    # ========================================================================
    # Proxy Selection
    # ========================================================================

    def get_proxy_for_target(
        self,
        target_host: str,
        exclude_providers: Optional[List[str]] = None
    ) -> Optional[str]:
        """
        Get the best available proxy for a target.

        Uses weighted random selection based on health scores,
        preferring healthier proxies.

        Args:
            target_host: Target hostname
            exclude_providers: Optional list of providers to exclude

        Returns:
            Proxy URL or None if no proxies available
        """
        with self._lock:
            # Filter available proxies
            available = []
            for proxy_url, health in self._proxies.items():
                if not health.is_available():
                    continue
                if exclude_providers and health.provider in exclude_providers:
                    continue

                # Calculate effective score for this target
                score = self._calculate_health_score(health, target_host)
                available.append((proxy_url, health, score))

            if not available:
                logger.warning(f"No available proxies for {target_host}")
                # Return any proxy as fallback
                all_proxies = list(self._proxies.keys())
                return random.choice(all_proxies) if all_proxies else None

            # Weighted random selection based on health scores
            return self._weighted_select(available)

    def get_all_proxies_for_target(
        self,
        target_host: str,
        shuffle: bool = True
    ) -> List[str]:
        """
        Get all proxies ordered by health for a target.

        Args:
            target_host: Target hostname
            shuffle: If True, apply weighted shuffle; if False, strict ordering

        Returns:
            List of proxy URLs ordered by preference
        """
        with self._lock:
            # Calculate scores for all proxies
            scored = []
            for proxy_url, health in self._proxies.items():
                if not health.is_available():
                    continue
                score = self._calculate_health_score(health, target_host)
                scored.append((proxy_url, score))

            if shuffle:
                # Weighted shuffle - higher scores more likely to be first
                return self._weighted_shuffle(scored)
            else:
                # Strict ordering by score
                scored.sort(key=lambda x: x[1], reverse=True)
                return [url for url, _ in scored]

    def _weighted_select(self, available: List[Tuple[str, ProxyHealth, float]]) -> str:
        """Select a proxy with probability weighted by health score."""
        # Normalize scores to probabilities
        total_score = sum(max(score, 1) for _, _, score in available)  # min 1 to avoid division by zero

        r = random.random() * total_score
        cumulative = 0

        for proxy_url, _, score in available:
            cumulative += max(score, 1)
            if cumulative >= r:
                return proxy_url

        # Fallback to last one
        return available[-1][0]

    def _weighted_shuffle(self, scored: List[Tuple[str, float]]) -> List[str]:
        """Shuffle proxies with health-weighted ordering."""
        result = []
        remaining = list(scored)

        while remaining:
            total = sum(max(score, 1) for _, score in remaining)
            r = random.random() * total
            cumulative = 0

            for i, (url, score) in enumerate(remaining):
                cumulative += max(score, 1)
                if cumulative >= r:
                    result.append(url)
                    remaining.pop(i)
                    break

        return result

    # ========================================================================
    # Health Metrics
    # ========================================================================

    def get_proxy_health(self, proxy_url: str) -> Optional[ProxyHealth]:
        """Get health information for a specific proxy."""
        with self._lock:
            return self._proxies.get(proxy_url)

    def get_health_metrics(self) -> ProxyHealthMetrics:
        """
        Get aggregated health metrics for monitoring.

        Returns:
            ProxyHealthMetrics with overall system health
        """
        with self._lock:
            now = datetime.now(timezone.utc)

            total = len(self._proxies)
            available = 0
            degraded = 0
            cooldown = 0
            unavailable = 0
            total_score = 0.0
            total_requests = 0
            total_successes = 0
            total_failures = 0
            providers: Dict[str, Dict] = {}

            for health in self._proxies.values():
                # Count by status
                if health.is_available():
                    if health.status == ProxyStatus.DEGRADED:
                        degraded += 1
                    else:
                        available += 1
                elif health.status == ProxyStatus.COOLDOWN:
                    cooldown += 1
                else:
                    unavailable += 1

                # Aggregate scores
                total_score += health.health_score

                # Aggregate stats
                total_requests += health.stats.total_requests
                total_successes += health.stats.successful_requests
                total_failures += health.stats.failed_requests

                # Per-provider stats
                provider = health.provider
                if provider not in providers:
                    providers[provider] = {
                        "count": 0,
                        "available": 0,
                        "average_score": 0.0,
                        "total_requests": 0,
                        "success_rate": 0.0
                    }
                providers[provider]["count"] += 1
                if health.is_available():
                    providers[provider]["available"] += 1
                providers[provider]["average_score"] += health.health_score
                providers[provider]["total_requests"] += health.stats.total_requests

            # Calculate averages
            avg_score = total_score / total if total > 0 else 0.0
            success_rate = (total_successes / total_requests * 100) if total_requests > 0 else 100.0

            for provider, data in providers.items():
                count = data["count"]
                data["average_score"] = data["average_score"] / count if count > 0 else 0.0
                reqs = data["total_requests"]
                # Calculate provider success rate from individual proxy stats
                provider_successes = sum(
                    h.stats.successful_requests
                    for h in self._proxies.values()
                    if h.provider == provider
                )
                data["success_rate"] = (provider_successes / reqs * 100) if reqs > 0 else 100.0

            return ProxyHealthMetrics(
                timestamp=now,
                total_proxies=total,
                available_proxies=available,
                degraded_proxies=degraded,
                cooldown_proxies=cooldown,
                unavailable_proxies=unavailable,
                average_health_score=avg_score,
                total_requests=total_requests,
                total_successes=total_successes,
                total_failures=total_failures,
                overall_success_rate=success_rate,
                providers=providers
            )

    def get_status_summary(self) -> Dict[str, any]:
        """
        Get a simple status summary for logging.

        Returns:
            Dictionary with key metrics
        """
        metrics = self.get_health_metrics()
        return {
            "total_proxies": metrics.total_proxies,
            "available": metrics.available_proxies,
            "degraded": metrics.degraded_proxies,
            "cooldown": metrics.cooldown_proxies,
            "average_health": round(metrics.average_health_score, 1),
            "success_rate": round(metrics.overall_success_rate, 1),
            "total_requests": metrics.total_requests
        }

    # ========================================================================
    # BigQuery Logging
    # ========================================================================

    def _log_to_bigquery(
        self,
        proxy_url: str,
        target_host: str,
        success: bool,
        response_time_ms: Optional[int] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        http_status_code: Optional[int] = None
    ):
        """Log proxy result to BigQuery for monitoring."""
        if not self._enable_bigquery:
            return

        try:
            client = self._get_bq_client()
            if client is None:
                return

            provider = extract_provider_from_url(proxy_url)
            health = self._proxies.get(proxy_url)
            health_score = health.health_score if health else None

            row = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "proxy_provider": provider,
                "target_host": target_host,
                "http_status_code": http_status_code,
                "response_time_ms": response_time_ms,
                "success": success,
                "error_type": error_type,
                "error_message": error_message[:500] if error_message else None,
                "health_score": health_score,
                "scraper_name": "proxy_manager"  # Generic source
            }

            from shared.config.gcp_config import get_table_id
            table_ref = get_table_id("nba_orchestration", "proxy_health_metrics")
            errors = client.insert_rows_json(table_ref, [row])

            if errors:
                logger.debug(f"BigQuery insert errors: {errors}")

        except Exception as e:
            logger.debug(f"Failed to log proxy result to BigQuery: {e}")

    def log_health_metrics(self):
        """Log current health metrics to BigQuery."""
        if not self._enable_bigquery:
            return

        # Rate limit logging
        now = datetime.now(timezone.utc)
        if self._last_metrics_log and (now - self._last_metrics_log) < self._metrics_log_interval:
            return

        try:
            metrics = self.get_health_metrics()
            client = self._get_bq_client()
            if client is None:
                return

            row = {
                "timestamp": metrics.timestamp.isoformat(),
                "total_proxies": metrics.total_proxies,
                "available_proxies": metrics.available_proxies,
                "degraded_proxies": metrics.degraded_proxies,
                "cooldown_proxies": metrics.cooldown_proxies,
                "average_health_score": metrics.average_health_score,
                "overall_success_rate": metrics.overall_success_rate,
                "total_requests": metrics.total_requests,
                "provider_stats": str(metrics.providers)  # JSON as string for simplicity
            }

            from shared.config.gcp_config import get_table_id
            table_ref = get_table_id("nba_orchestration", "proxy_health_snapshots")
            errors = client.insert_rows_json(table_ref, [row])

            if errors:
                logger.debug(f"BigQuery metrics insert errors: {errors}")
            else:
                self._last_metrics_log = now

        except Exception as e:
            logger.debug(f"Failed to log health metrics to BigQuery: {e}")

    # ========================================================================
    # Utility Methods
    # ========================================================================

    def reset_proxy_health(self, proxy_url: str):
        """Reset health metrics for a specific proxy."""
        with self._lock:
            if proxy_url in self._proxies:
                health = self._proxies[proxy_url]
                health.health_score = ProxyConfig.INITIAL_HEALTH_SCORE
                health.status = ProxyStatus.AVAILABLE
                health.cooldown_until = None
                health.cooldown_count = 0
                health.stats = ProxyStats()
                health.per_target_stats.clear()
                logger.info(f"Reset health for proxy: {health.provider}")

    def reset_all_health(self):
        """Reset health metrics for all proxies."""
        with self._lock:
            for proxy_url in self._proxies:
                self.reset_proxy_health(proxy_url)
            logger.info("Reset health for all proxies")

    def force_cooldown(self, proxy_url: str, duration_seconds: int = 300):
        """Manually put a proxy into cooldown."""
        with self._lock:
            if proxy_url in self._proxies:
                health = self._proxies[proxy_url]
                health.status = ProxyStatus.COOLDOWN
                health.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
                logger.info(f"Forced cooldown for proxy {health.provider}: {duration_seconds}s")

    def refresh_proxies(self):
        """Refresh proxy list from environment."""
        self._load_proxies()
        logger.info(f"Refreshed proxy list, now have {len(self._proxies)} proxies")


# ============================================================================
# Singleton Instance
# ============================================================================

_proxy_manager_instance: Optional[ProxyManager] = None
_proxy_manager_lock = threading.Lock()


def get_proxy_manager(enable_bigquery: bool = True) -> ProxyManager:
    """
    Get the singleton ProxyManager instance.

    Args:
        enable_bigquery: Enable BigQuery logging (only used on first call)

    Returns:
        ProxyManager instance
    """
    global _proxy_manager_instance

    if _proxy_manager_instance is None:
        with _proxy_manager_lock:
            if _proxy_manager_instance is None:
                _proxy_manager_instance = ProxyManager(enable_bigquery_logging=enable_bigquery)

    return _proxy_manager_instance


# ============================================================================
# Convenience Functions (backward compatible)
# ============================================================================

def get_healthy_proxy_urls(target_host: Optional[str] = None) -> List[str]:
    """
    Get proxy URLs ordered by health.

    Convenience function that maintains backward compatibility.

    Args:
        target_host: Optional target for target-specific ordering

    Returns:
        List of proxy URLs
    """
    manager = get_proxy_manager()
    if target_host:
        return manager.get_all_proxies_for_target(target_host)

    # Get all configured proxies with basic health ordering
    with manager._lock:
        scored = [(url, health.health_score) for url, health in manager._proxies.items()]
        return manager._weighted_shuffle(scored)


def record_proxy_result(
    proxy_url: str,
    target_host: str,
    success: bool,
    response_time_ms: Optional[int] = None,
    error_type: Optional[str] = None
):
    """
    Record a proxy request result.

    Convenience function for simple recording.
    """
    manager = get_proxy_manager()
    if success:
        manager.record_success(proxy_url, target_host, response_time_ms)
    else:
        manager.record_failure(proxy_url, target_host, error_type)
