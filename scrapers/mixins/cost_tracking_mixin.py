"""
cost_tracking_mixin.py

Mixin for handling cost tracking in scrapers.

This mixin provides functionality to track and record the costs associated with
scraper operations, including HTTP requests, retries, exports, and overall execution.
It integrates with the ScraperCostTracker to log metrics to BigQuery for analysis.
"""

import logging

logger = logging.getLogger(__name__)


class CostTrackingMixin:
    """
    Mixin for cost tracking in scrapers.

    Handles:
    - Initialization of cost tracking
    - Recording HTTP request metrics
    - Recording retry attempts
    - Recording export metrics
    - Finalizing and saving cost data to BigQuery
    """

    def _init_cost_tracking(self):
        """
        Initialize cost tracking for this scraper run.

        Lazy imports the ScraperCostTracker to avoid circular imports
        and startup overhead when tracking is not needed.
        """
        try:
            from monitoring.scraper_cost_tracker import ScraperCostTracker

            self._cost_tracker = ScraperCostTracker(
                scraper_name=self._get_scraper_name(),
                run_id=self.run_id
            )
            self._cost_tracker.start_tracking()

            # Set execution context
            source, environment, triggered_by = self._determine_execution_source()
            self._cost_tracker.set_context(
                source=source,
                environment=environment,
                workflow=self.opts.get('workflow'),
                game_date=self._extract_game_date()
            )

            logger.debug(f"Cost tracking initialized for {self._get_scraper_name()}")

        except ImportError as e:
            logger.debug(f"Cost tracking not available (module not installed): {e}")
            self._cost_tracker = None
        except Exception as e:
            logger.warning(f"Failed to initialize cost tracking: {e}")
            self._cost_tracker = None

    def _record_cost_request(self, bytes_received: int = 0, duration_ms: float = None):
        """
        Record metrics for an HTTP request (called from download methods).

        Args:
            bytes_received: Number of bytes received in response
            duration_ms: Request duration in milliseconds
        """
        if self._cost_tracker:
            self._cost_tracker.record_request(
                bytes_received=bytes_received,
                duration_ms=duration_ms
            )

        # Also track for internal stats
        self._bytes_downloaded += bytes_received

    def _record_cost_retry(self):
        """Record a retry attempt for cost tracking."""
        if self._cost_tracker:
            self._cost_tracker.record_retry()

    def _record_cost_export(self, bytes_exported: int = 0, duration_seconds: float = 0.0):
        """
        Record export metrics for cost tracking.

        Args:
            bytes_exported: Number of bytes written to GCS
            duration_seconds: Time spent exporting
        """
        if self._cost_tracker:
            self._cost_tracker.record_export(
                bytes_exported=bytes_exported,
                duration_seconds=duration_seconds
            )

        # Also track for internal stats
        self._bytes_exported += bytes_exported

    def _finalize_cost_tracking(self, success: bool = True, error: Exception = None):
        """
        Finalize cost tracking and save metrics to BigQuery.

        Args:
            success: Whether the scraper run was successful
            error: Exception if the run failed
        """
        if not self._cost_tracker:
            return

        try:
            # Get record count from execution status
            _, record_count = self._determine_execution_status()

            # Finalize tracking
            metrics = self._cost_tracker.finish_tracking(
                success=success,
                record_count=record_count,
                error=error
            )

            if metrics:
                # Add to stats for SCRAPER_STATS log line
                self.stats["cost_metrics"] = {
                    "execution_time_seconds": round(metrics.execution_time_seconds, 2),
                    "request_count": metrics.request_count,
                    "retry_count": metrics.retry_count,
                    "bytes_downloaded": metrics.bytes_downloaded,
                    "bytes_exported": metrics.bytes_exported,
                    "total_cost_usd": round(metrics.total_cost, 6),
                }

                # Save to BigQuery (non-blocking)
                self._cost_tracker.save_to_bigquery()

                logger.info(
                    f"Cost tracking: {metrics.request_count} requests, "
                    f"{metrics.bytes_downloaded / 1024:.1f}KB downloaded, "
                    f"${metrics.total_cost:.6f} total cost"
                )

        except Exception as e:
            logger.warning(f"Failed to finalize cost tracking: {e}")
