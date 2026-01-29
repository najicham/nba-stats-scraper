#!/usr/bin/env python3
"""
Scraper Cost Tracker

Tracks and monitors scraper execution costs per scraper including:
- Execution time
- Data volume (bytes scraped)
- Request count
- Error rate
- Estimated cost (based on compute, egress, and API costs)

Architecture:
- Integrates with ScraperBase to collect metrics during execution
- Stores metrics in BigQuery for historical analysis
- Provides aggregated views for dashboard display

Cost Model:
- Cloud Run compute: $0.00002400/vCPU-second, $0.00000250/GB-second
- Network egress: $0.12/GB (to internet)
- API costs: Variable per provider (Odds API, BettingPros, etc.)

Usage:
    # Track metrics during scraper run
    from monitoring.scraper_cost_tracker import ScraperCostTracker

    tracker = ScraperCostTracker(scraper_name='nbac_injury_report')
    tracker.start_tracking()
    # ... scraper execution ...
    tracker.record_request(bytes_received=1024, duration_ms=150)
    tracker.finish_tracking(success=True, record_count=15)

    # Query historical costs
    tracker = ScraperCostTracker()
    costs = tracker.get_scraper_costs(days=7)

Created: 2026-01-23
"""

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from shared.utils.bigquery_batch_writer import get_batch_writer

# Cost constants (USD)
# Cloud Run pricing (us-west1)
COST_PER_VCPU_SECOND = 0.00002400  # per vCPU-second
COST_PER_GB_SECOND = 0.00000250    # per GB-second of memory
COST_PER_REQUEST = 0.0000004      # per request (Cloud Run)
COST_PER_GB_EGRESS = 0.12         # per GB egress to internet

# API provider costs (per request or per unit)
API_COSTS = {
    'odds_api': 0.001,        # ~$0.001 per request (varies by plan)
    'bettingpros': 0.0005,    # estimated
    'nbacom': 0.0,            # free (public API)
    'espn': 0.0,              # free (public API)
    'balldontlie': 0.0,       # free tier
    'bigdataball': 0.0,       # subscription-based
    'pbpstats': 0.0,          # free
    'basketball_ref': 0.0,    # free (web scraping)
}

# Default Cloud Run instance specs
DEFAULT_VCPU = 1.0
DEFAULT_MEMORY_GB = 0.5


@dataclass
class ScraperMetrics:
    """Container for scraper execution metrics."""
    scraper_name: str
    run_id: str

    # Timing
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    execution_time_seconds: float = 0.0
    download_time_seconds: float = 0.0
    export_time_seconds: float = 0.0

    # Request tracking
    request_count: int = 0
    retry_count: int = 0

    # Data volume
    bytes_downloaded: int = 0
    bytes_exported: int = 0
    record_count: int = 0

    # Status
    success: bool = False
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    # Resource usage (estimated)
    vcpu_used: float = DEFAULT_VCPU
    memory_gb_used: float = DEFAULT_MEMORY_GB

    # Cost breakdown
    compute_cost: float = 0.0
    network_cost: float = 0.0
    api_cost: float = 0.0
    total_cost: float = 0.0

    # Context
    source: str = 'UNKNOWN'
    environment: str = 'prod'
    workflow: Optional[str] = None
    game_date: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for BigQuery insertion."""
        return {
            'scraper_name': self.scraper_name,
            'run_id': self.run_id,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'execution_time_seconds': round(self.execution_time_seconds, 3),
            'download_time_seconds': round(self.download_time_seconds, 3),
            'export_time_seconds': round(self.export_time_seconds, 3),
            'request_count': self.request_count,
            'retry_count': self.retry_count,
            'bytes_downloaded': self.bytes_downloaded,
            'bytes_exported': self.bytes_exported,
            'record_count': self.record_count,
            'success': self.success,
            'error_type': self.error_type,
            'error_message': self.error_message[:500] if self.error_message else None,
            'vcpu_used': self.vcpu_used,
            'memory_gb_used': self.memory_gb_used,
            'compute_cost': round(self.compute_cost, 8),
            'network_cost': round(self.network_cost, 8),
            'api_cost': round(self.api_cost, 8),
            'total_cost': round(self.total_cost, 8),
            'source': self.source,
            'environment': self.environment,
            'workflow': self.workflow,
            'game_date': self.game_date,
            'created_at': datetime.now(timezone.utc).isoformat(),
        }


class ScraperCostTracker:
    """
    Track and analyze scraper execution costs.

    Collects metrics during scraper execution and stores them in BigQuery
    for historical analysis and cost optimization.
    """

    def __init__(self, scraper_name: str = None, run_id: str = None):
        """
        Initialize cost tracker.

        Args:
            scraper_name: Name of the scraper being tracked
            run_id: Unique run identifier
        """
        self.scraper_name = scraper_name
        self.run_id = run_id
        self.metrics: Optional[ScraperMetrics] = None
        self._bq_client = None
        self._project_id = None

        # Request timing buffer
        self._request_start_time: Optional[float] = None

    @property
    def project_id(self) -> str:
        """Get project ID."""
        if self._project_id is None:
            try:
                from shared.config.gcp_config import get_project_id
                self._project_id = get_project_id()
            except ImportError:
                self._project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        return self._project_id

    @property
    def bq_client(self):
        """Lazy-load BigQuery client."""
        if self._bq_client is None:
            try:
                from google.cloud import bigquery
                self._bq_client = bigquery.Client(project=self.project_id)
            except Exception as e:
                logger.warning(f"Failed to initialize BigQuery client: {e}")
        return self._bq_client

    def _get_api_provider(self) -> str:
        """Extract API provider from scraper name."""
        if not self.scraper_name:
            return 'unknown'

        name_lower = self.scraper_name.lower()

        if 'oddsa' in name_lower or 'odds_api' in name_lower:
            return 'odds_api'
        elif 'bp_' in name_lower or 'bettingpros' in name_lower:
            return 'bettingpros'
        elif 'nbac' in name_lower or 'nba_com' in name_lower:
            return 'nbacom'
        elif 'espn' in name_lower:
            return 'espn'
        elif 'bdl' in name_lower or 'balldontlie' in name_lower:
            return 'balldontlie'
        elif 'bdb' in name_lower or 'bigdataball' in name_lower:
            return 'bigdataball'
        elif 'pbp' in name_lower:
            return 'pbpstats'
        elif 'br_' in name_lower or 'basketball_ref' in name_lower:
            return 'basketball_ref'
        else:
            return 'unknown'

    def start_tracking(self) -> None:
        """Start tracking metrics for a scraper run."""
        if not self.scraper_name or not self.run_id:
            logger.warning("Cannot start tracking without scraper_name and run_id")
            return

        self.metrics = ScraperMetrics(
            scraper_name=self.scraper_name,
            run_id=self.run_id,
            start_time=datetime.now(timezone.utc)
        )
        logger.debug(f"Started cost tracking for {self.scraper_name} (run_id: {self.run_id})")

    def record_request_start(self) -> None:
        """Mark the start of an HTTP request."""
        self._request_start_time = time.time()

    def record_request(self, bytes_received: int = 0, duration_ms: Optional[float] = None,
                       success: bool = True) -> None:
        """
        Record metrics for a single HTTP request.

        Args:
            bytes_received: Number of bytes received in response
            duration_ms: Request duration in milliseconds (auto-calculated if not provided)
            success: Whether the request was successful
        """
        if not self.metrics:
            return

        self.metrics.request_count += 1
        self.metrics.bytes_downloaded += bytes_received

        # Calculate duration if not provided
        if duration_ms is None and self._request_start_time:
            duration_ms = (time.time() - self._request_start_time) * 1000
            self._request_start_time = None

        if duration_ms:
            self.metrics.download_time_seconds += duration_ms / 1000.0

    def record_retry(self) -> None:
        """Record a retry attempt."""
        if self.metrics:
            self.metrics.retry_count += 1

    def record_export(self, bytes_exported: int = 0, duration_seconds: float = 0.0) -> None:
        """
        Record export metrics.

        Args:
            bytes_exported: Number of bytes written to GCS
            duration_seconds: Time spent exporting
        """
        if not self.metrics:
            return

        self.metrics.bytes_exported += bytes_exported
        self.metrics.export_time_seconds += duration_seconds

    def set_context(self, source: str = None, environment: str = None,
                    workflow: str = None, game_date: str = None) -> None:
        """Set execution context for the metrics."""
        if not self.metrics:
            return

        if source:
            self.metrics.source = source
        if environment:
            self.metrics.environment = environment
        if workflow:
            self.metrics.workflow = workflow
        if game_date:
            self.metrics.game_date = game_date

    def _calculate_costs(self) -> None:
        """Calculate cost breakdown based on collected metrics."""
        if not self.metrics:
            return

        # Compute cost: vCPU-seconds + memory GB-seconds
        execution_time = self.metrics.execution_time_seconds
        compute_cost = (
            (self.metrics.vcpu_used * execution_time * COST_PER_VCPU_SECOND) +
            (self.metrics.memory_gb_used * execution_time * COST_PER_GB_SECOND) +
            (self.metrics.request_count * COST_PER_REQUEST)
        )
        self.metrics.compute_cost = compute_cost

        # Network cost: egress for downloaded bytes
        bytes_total = self.metrics.bytes_downloaded + self.metrics.bytes_exported
        gb_transferred = bytes_total / (1024 ** 3)
        self.metrics.network_cost = gb_transferred * COST_PER_GB_EGRESS

        # API cost: based on provider
        provider = self._get_api_provider()
        api_cost_per_request = API_COSTS.get(provider, 0.0)
        self.metrics.api_cost = self.metrics.request_count * api_cost_per_request

        # Total cost
        self.metrics.total_cost = (
            self.metrics.compute_cost +
            self.metrics.network_cost +
            self.metrics.api_cost
        )

    def finish_tracking(self, success: bool = True, record_count: int = 0,
                        error: Optional[Exception] = None) -> Optional[ScraperMetrics]:
        """
        Finish tracking and calculate final metrics.

        Args:
            success: Whether the scraper run was successful
            record_count: Number of records processed
            error: Exception if the run failed

        Returns:
            Completed ScraperMetrics or None if tracking wasn't started
        """
        if not self.metrics:
            return None

        self.metrics.end_time = datetime.now(timezone.utc)
        self.metrics.success = success
        self.metrics.record_count = record_count

        # Calculate execution time
        if self.metrics.start_time:
            delta = self.metrics.end_time - self.metrics.start_time
            self.metrics.execution_time_seconds = delta.total_seconds()

        # Record error details
        if error:
            self.metrics.error_type = type(error).__name__
            self.metrics.error_message = str(error)

        # Calculate costs
        self._calculate_costs()

        logger.debug(
            f"Finished cost tracking for {self.scraper_name}: "
            f"duration={self.metrics.execution_time_seconds:.2f}s, "
            f"requests={self.metrics.request_count}, "
            f"bytes={self.metrics.bytes_downloaded}, "
            f"cost=${self.metrics.total_cost:.6f}"
        )

        return self.metrics

    def save_to_bigquery(self) -> bool:
        """
        Save metrics to BigQuery using BigQueryBatchWriter.

        Returns:
            True if successful, False otherwise
        """
        if not self.metrics:
            logger.warning("No metrics to save")
            return False

        try:
            table_id = "nba_orchestration.scraper_cost_metrics"
            row = self.metrics.to_dict()

            # Use BigQueryBatchWriter for efficient batched writes
            writer = get_batch_writer(table_id, project_id=self.project_id)
            writer.add_record(row)
            # Flush immediately to ensure metrics are persisted before process exits
            writer.flush()

            logger.info(f"Saved cost metrics for {self.scraper_name} (run_id: {self.run_id})")
            return True

        except Exception as e:
            logger.error(f"Error saving cost metrics to BigQuery: {e}")
            return False

    # =========================================================================
    # Query Methods for Dashboard
    # =========================================================================

    def get_scraper_costs(self, days: int = 7) -> List[Dict]:
        """
        Get aggregated costs per scraper for the last N days.

        Args:
            days: Number of days to look back

        Returns:
            List of per-scraper cost summaries
        """
        if not self.bq_client:
            return []

        query = f"""
        SELECT
            scraper_name,
            COUNT(*) as run_count,
            COUNTIF(success = true) as success_count,
            COUNTIF(success = false) as failure_count,
            ROUND(COUNTIF(success = true) * 100.0 / COUNT(*), 1) as success_rate_pct,
            ROUND(AVG(execution_time_seconds), 2) as avg_execution_time,
            ROUND(MAX(execution_time_seconds), 2) as max_execution_time,
            SUM(request_count) as total_requests,
            SUM(retry_count) as total_retries,
            SUM(bytes_downloaded) as total_bytes_downloaded,
            ROUND(SUM(bytes_downloaded) / (1024 * 1024), 2) as total_mb_downloaded,
            SUM(record_count) as total_records,
            ROUND(AVG(record_count), 1) as avg_records_per_run,
            ROUND(SUM(compute_cost), 6) as total_compute_cost,
            ROUND(SUM(network_cost), 6) as total_network_cost,
            ROUND(SUM(api_cost), 6) as total_api_cost,
            ROUND(SUM(total_cost), 6) as total_cost,
            ROUND(AVG(total_cost), 8) as avg_cost_per_run,
            MIN(start_time) as first_run,
            MAX(start_time) as last_run
        FROM `{self.project_id}.nba_orchestration.scraper_cost_metrics`
        WHERE start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
        GROUP BY scraper_name
        ORDER BY total_cost DESC
        """

        try:
            result = self.bq_client.query(query).result(timeout=120)
            return [
                {
                    'scraper_name': row.scraper_name,
                    'run_count': row.run_count,
                    'success_count': row.success_count,
                    'failure_count': row.failure_count,
                    'success_rate_pct': row.success_rate_pct,
                    'avg_execution_time': row.avg_execution_time,
                    'max_execution_time': row.max_execution_time,
                    'total_requests': row.total_requests,
                    'total_retries': row.total_retries,
                    'total_bytes_downloaded': row.total_bytes_downloaded,
                    'total_mb_downloaded': row.total_mb_downloaded,
                    'total_records': row.total_records,
                    'avg_records_per_run': row.avg_records_per_run,
                    'total_compute_cost': row.total_compute_cost,
                    'total_network_cost': row.total_network_cost,
                    'total_api_cost': row.total_api_cost,
                    'total_cost': row.total_cost,
                    'avg_cost_per_run': row.avg_cost_per_run,
                    'first_run': row.first_run.isoformat() if row.first_run else None,
                    'last_run': row.last_run.isoformat() if row.last_run else None,
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying scraper costs: {e}")
            return []

    def get_daily_costs(self, days: int = 7) -> List[Dict]:
        """
        Get daily aggregated costs across all scrapers.

        Args:
            days: Number of days to look back

        Returns:
            List of daily cost summaries
        """
        if not self.bq_client:
            return []

        query = f"""
        SELECT
            DATE(start_time) as date,
            COUNT(*) as run_count,
            COUNTIF(success = true) as success_count,
            COUNT(DISTINCT scraper_name) as unique_scrapers,
            SUM(request_count) as total_requests,
            SUM(bytes_downloaded) as total_bytes_downloaded,
            ROUND(SUM(bytes_downloaded) / (1024 * 1024), 2) as total_mb_downloaded,
            SUM(record_count) as total_records,
            ROUND(SUM(execution_time_seconds), 1) as total_execution_time,
            ROUND(SUM(compute_cost), 6) as compute_cost,
            ROUND(SUM(network_cost), 6) as network_cost,
            ROUND(SUM(api_cost), 6) as api_cost,
            ROUND(SUM(total_cost), 6) as total_cost
        FROM `{self.project_id}.nba_orchestration.scraper_cost_metrics`
        WHERE start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
        GROUP BY date
        ORDER BY date DESC
        """

        try:
            result = self.bq_client.query(query).result(timeout=120)
            return [
                {
                    'date': row.date.isoformat(),
                    'run_count': row.run_count,
                    'success_count': row.success_count,
                    'unique_scrapers': row.unique_scrapers,
                    'total_requests': row.total_requests,
                    'total_bytes_downloaded': row.total_bytes_downloaded,
                    'total_mb_downloaded': row.total_mb_downloaded,
                    'total_records': row.total_records,
                    'total_execution_time': row.total_execution_time,
                    'compute_cost': row.compute_cost,
                    'network_cost': row.network_cost,
                    'api_cost': row.api_cost,
                    'total_cost': row.total_cost,
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying daily costs: {e}")
            return []

    def get_cost_summary(self, days: int = 7) -> Dict:
        """
        Get overall cost summary with totals and averages.

        Args:
            days: Number of days to look back

        Returns:
            Summary dict with aggregated metrics
        """
        if not self.bq_client:
            return {'error': 'BigQuery client not available'}

        query = f"""
        SELECT
            COUNT(*) as total_runs,
            COUNTIF(success = true) as successful_runs,
            COUNTIF(success = false) as failed_runs,
            ROUND(COUNTIF(success = true) * 100.0 / COUNT(*), 1) as success_rate_pct,
            COUNT(DISTINCT scraper_name) as unique_scrapers,
            SUM(request_count) as total_requests,
            SUM(retry_count) as total_retries,
            SUM(bytes_downloaded) as total_bytes_downloaded,
            ROUND(SUM(bytes_downloaded) / (1024 * 1024 * 1024), 4) as total_gb_downloaded,
            SUM(record_count) as total_records,
            ROUND(AVG(execution_time_seconds), 2) as avg_execution_time,
            ROUND(MAX(execution_time_seconds), 2) as max_execution_time,
            ROUND(SUM(execution_time_seconds), 1) as total_execution_time,
            ROUND(SUM(execution_time_seconds) / 3600, 2) as total_execution_hours,
            ROUND(SUM(compute_cost), 4) as total_compute_cost,
            ROUND(SUM(network_cost), 4) as total_network_cost,
            ROUND(SUM(api_cost), 4) as total_api_cost,
            ROUND(SUM(total_cost), 4) as total_cost,
            ROUND(AVG(total_cost), 6) as avg_cost_per_run,
            MIN(start_time) as earliest_run,
            MAX(start_time) as latest_run
        FROM `{self.project_id}.nba_orchestration.scraper_cost_metrics`
        WHERE start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
        """

        try:
            result = list(self.bq_client.query(query).result(timeout=120))

            if not result:
                return {'error': 'No data found'}

            row = result[0]
            return {
                'period_days': days,
                'total_runs': row.total_runs or 0,
                'successful_runs': row.successful_runs or 0,
                'failed_runs': row.failed_runs or 0,
                'success_rate_pct': row.success_rate_pct or 0,
                'unique_scrapers': row.unique_scrapers or 0,
                'total_requests': row.total_requests or 0,
                'total_retries': row.total_retries or 0,
                'total_bytes_downloaded': row.total_bytes_downloaded or 0,
                'total_gb_downloaded': row.total_gb_downloaded or 0,
                'total_records': row.total_records or 0,
                'avg_execution_time': row.avg_execution_time or 0,
                'max_execution_time': row.max_execution_time or 0,
                'total_execution_time': row.total_execution_time or 0,
                'total_execution_hours': row.total_execution_hours or 0,
                'total_compute_cost': row.total_compute_cost or 0,
                'total_network_cost': row.total_network_cost or 0,
                'total_api_cost': row.total_api_cost or 0,
                'total_cost': row.total_cost or 0,
                'avg_cost_per_run': row.avg_cost_per_run or 0,
                'earliest_run': row.earliest_run.isoformat() if row.earliest_run else None,
                'latest_run': row.latest_run.isoformat() if row.latest_run else None,
                'generated_at': datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.error(f"Error getting cost summary: {e}")
            return {'error': str(e)}

    def get_error_breakdown(self, days: int = 7) -> List[Dict]:
        """
        Get error breakdown by scraper and error type.

        Args:
            days: Number of days to look back

        Returns:
            List of error summaries
        """
        if not self.bq_client:
            return []

        query = f"""
        SELECT
            scraper_name,
            error_type,
            COUNT(*) as error_count,
            MIN(start_time) as first_occurrence,
            MAX(start_time) as last_occurrence,
            ROUND(AVG(execution_time_seconds), 2) as avg_time_before_error
        FROM `{self.project_id}.nba_orchestration.scraper_cost_metrics`
        WHERE start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
          AND success = false
          AND error_type IS NOT NULL
        GROUP BY scraper_name, error_type
        ORDER BY error_count DESC
        LIMIT 50
        """

        try:
            result = self.bq_client.query(query).result(timeout=120)
            return [
                {
                    'scraper_name': row.scraper_name,
                    'error_type': row.error_type,
                    'error_count': row.error_count,
                    'first_occurrence': row.first_occurrence.isoformat() if row.first_occurrence else None,
                    'last_occurrence': row.last_occurrence.isoformat() if row.last_occurrence else None,
                    'avg_time_before_error': row.avg_time_before_error,
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying error breakdown: {e}")
            return []

    def get_all_metrics(self, days: int = 7) -> Dict:
        """
        Get all cost metrics for dashboard display.

        Args:
            days: Number of days to look back

        Returns:
            Dict with all cost metrics organized by type
        """
        return {
            'summary': self.get_cost_summary(days),
            'by_scraper': self.get_scraper_costs(days),
            'by_day': self.get_daily_costs(days),
            'errors': self.get_error_breakdown(days),
            'period_days': days,
            'generated_at': datetime.now(timezone.utc).isoformat(),
        }


def main():
    """CLI for testing scraper cost tracking."""
    import argparse

    parser = argparse.ArgumentParser(description="Scraper cost tracking")
    parser.add_argument('--days', type=int, default=7, help='Days to look back')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--scraper', type=str, help='Filter by scraper name')
    args = parser.parse_args()

    tracker = ScraperCostTracker()

    if args.json:
        data = tracker.get_all_metrics(args.days)
        print(json.dumps(data, indent=2))
    else:
        summary = tracker.get_cost_summary(args.days)

        print("\n" + "=" * 70)
        print("SCRAPER COST TRACKING REPORT")
        print("=" * 70)
        print(f"Period: Last {args.days} days")
        print()

        if 'error' in summary:
            print(f"Error: {summary['error']}")
            return

        print("SUMMARY:")
        print(f"  Total Runs: {summary['total_runs']:,}")
        print(f"  Success Rate: {summary['success_rate_pct']}%")
        print(f"  Unique Scrapers: {summary['unique_scrapers']}")
        print(f"  Total Requests: {summary['total_requests']:,}")
        print(f"  Total GB Downloaded: {summary['total_gb_downloaded']:.4f} GB")
        print(f"  Total Records: {summary['total_records']:,}")
        print(f"  Total Execution Hours: {summary['total_execution_hours']:.2f} hrs")
        print()
        print("COST BREAKDOWN:")
        print(f"  Compute Cost: ${summary['total_compute_cost']:.4f}")
        print(f"  Network Cost: ${summary['total_network_cost']:.4f}")
        print(f"  API Cost: ${summary['total_api_cost']:.4f}")
        print(f"  TOTAL COST: ${summary['total_cost']:.4f}")
        print(f"  Avg Cost/Run: ${summary['avg_cost_per_run']:.6f}")
        print()

        # Per-scraper breakdown
        scrapers = tracker.get_scraper_costs(args.days)
        if scrapers:
            print("TOP SCRAPERS BY COST:")
            print(f"  {'Scraper':<35} {'Runs':>8} {'Cost':>12} {'Avg Cost':>12}")
            print("  " + "-" * 70)
            for s in scrapers[:10]:
                print(f"  {s['scraper_name']:<35} {s['run_count']:>8} "
                      f"${s['total_cost']:>10.4f} ${s['avg_cost_per_run']:>10.6f}")

        print("\n" + "=" * 70)


if __name__ == '__main__':
    main()
