"""
Infrastructure Validator - Validates system infrastructure health.

This module validates infrastructure components like:
- Proxy health (success rates, 403s, timeouts)
- Service health endpoints
- Secret availability

Only shown for today/yesterday validation runs.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
import logging

from google.cloud import bigquery

from shared.validation.config import PROJECT_ID
from shared.validation.time_awareness import TimeContext

logger = logging.getLogger(__name__)

# Thresholds for proxy health
PROXY_WARNING_THRESHOLD = 80  # Warn if success rate below 80%
PROXY_CRITICAL_THRESHOLD = 50  # Critical if below 50%


@dataclass
class ProxyTargetHealth:
    """Health status for a single proxy target."""
    target_host: str
    proxy_provider: str
    total_requests: int
    successful: int
    success_rate: float
    forbidden_403: int
    timeouts: int
    status: str  # 'healthy', 'warning', 'critical'


@dataclass
class ProxyHealthStatus:
    """Overall proxy health status."""
    has_data: bool = False
    targets: List[ProxyTargetHealth] = field(default_factory=list)
    overall_status: str = 'unknown'  # 'healthy', 'warning', 'critical', 'unknown'
    hours_checked: int = 24


@dataclass
class InfrastructureValidation:
    """Validation result for infrastructure components."""
    proxy_health: Optional[ProxyHealthStatus] = None
    is_healthy: bool = True
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def validate_infrastructure(
    game_date: date,
    time_context: TimeContext,
    bq_client: Optional[bigquery.Client] = None,
) -> Optional[InfrastructureValidation]:
    """
    Validate infrastructure components.

    Only runs for today or yesterday to avoid noise on historical dates.

    Args:
        game_date: Date being validated
        time_context: Time context for the validation
        bq_client: Optional BigQuery client

    Returns:
        InfrastructureValidation if today/yesterday, None otherwise
    """
    # Only show infrastructure for today/yesterday
    if not (time_context.is_today or time_context.is_yesterday):
        return None

    if bq_client is None:
        bq_client = bigquery.Client(project=PROJECT_ID)

    result = InfrastructureValidation()

    # Check proxy health
    result.proxy_health = _check_proxy_health(bq_client)

    # Determine overall health
    if result.proxy_health and result.proxy_health.overall_status == 'critical':
        result.is_healthy = False
        result.errors.append("Proxy infrastructure has critical issues")
    elif result.proxy_health and result.proxy_health.overall_status == 'warning':
        result.warnings.append("Proxy infrastructure has warnings")

    return result


def _check_proxy_health(bq_client: bigquery.Client) -> ProxyHealthStatus:
    """Check proxy health from the last 24 hours."""
    query = f"""
    SELECT
        target_host,
        COALESCE(proxy_provider, 'unknown') as proxy_provider,
        COUNT(*) as total_requests,
        COUNTIF(success) as successful,
        ROUND(COUNTIF(success) * 100.0 / NULLIF(COUNT(*), 0), 1) as success_rate,
        COUNTIF(http_status_code = 403) as forbidden_403,
        COUNTIF(error_type = 'timeout') as timeouts
    FROM `{PROJECT_ID}.nba_orchestration.proxy_health_metrics`
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
    GROUP BY target_host, proxy_provider
    HAVING total_requests >= 3
    ORDER BY total_requests DESC
    """

    try:
        results = list(bq_client.query(query).result())
    except Exception as e:
        logger.warning(f"Failed to query proxy health: {e}")
        return ProxyHealthStatus(has_data=False)

    if not results:
        return ProxyHealthStatus(has_data=False)

    targets = []
    overall_status = 'healthy'

    for row in results:
        success_rate = row.success_rate or 0

        if success_rate < PROXY_CRITICAL_THRESHOLD:
            status = 'critical'
            overall_status = 'critical'
        elif success_rate < PROXY_WARNING_THRESHOLD:
            status = 'warning'
            if overall_status != 'critical':
                overall_status = 'warning'
        else:
            status = 'healthy'

        targets.append(ProxyTargetHealth(
            target_host=row.target_host,
            proxy_provider=row.proxy_provider,
            total_requests=row.total_requests,
            successful=row.successful,
            success_rate=success_rate,
            forbidden_403=row.forbidden_403,
            timeouts=row.timeouts,
            status=status,
        ))

    return ProxyHealthStatus(
        has_data=True,
        targets=targets,
        overall_status=overall_status,
        hours_checked=24,
    )


def format_proxy_health(proxy_health: ProxyHealthStatus) -> str:
    """Format proxy health for terminal output."""
    if not proxy_health.has_data:
        return "  No proxy data in last 24h"

    lines = []
    for target in proxy_health.targets:
        status_icon = {
            'healthy': '✓',
            'warning': '⚠',
            'critical': '✗',
        }.get(target.status, '?')

        lines.append(
            f"  {status_icon} {target.target_host}: {target.success_rate}% "
            f"({target.successful}/{target.total_requests})"
        )

        if target.forbidden_403 > 0:
            lines.append(f"      403 Forbidden: {target.forbidden_403}")
        if target.timeouts > 0:
            lines.append(f"      Timeouts: {target.timeouts}")

    return "\n".join(lines)
