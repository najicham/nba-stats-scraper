#!/usr/bin/env python3
"""
Prediction Coverage Monitor

Monitors prediction coverage rates and sends alerts when coverage falls below thresholds.
Integrates with the notification system for multi-channel alerting and metrics_utils
for dashboard tracking.

Usage:
    monitor = PredictionCoverageMonitor()
    coverage_ok = monitor.check_coverage(
        players_expected=450,
        players_predicted=440,
        game_date=date.today()
    )
"""

import logging
import os
from datetime import date, datetime
from typing import Dict, List, Optional, Set, Tuple, Any

# Configure module logger
logger = logging.getLogger(__name__)

# Lazy imports for notification and metrics systems
_notification_system_available = None
_metrics_available = None


def _check_notification_system() -> bool:
    """Check if notification system is available (lazy load)."""
    global _notification_system_available
    if _notification_system_available is None:
        try:
            from shared.utils.notification_system import notify_error, notify_warning
            _notification_system_available = True
        except ImportError as e:
            logger.warning(f"Notification system not available: {e}")
            _notification_system_available = False
    return _notification_system_available


def _check_metrics_available() -> bool:
    """Check if metrics utilities are available (lazy load)."""
    global _metrics_available
    if _metrics_available is None:
        try:
            from shared.utils.metrics_utils import send_metric
            _metrics_available = True
        except ImportError as e:
            logger.warning(f"Metrics utilities not available: {e}")
            _metrics_available = False
    return _metrics_available


class PredictionCoverageMonitor:
    """
    Monitors prediction coverage and sends alerts when thresholds are breached.

    Thresholds:
        - COVERAGE_THRESHOLD (95.0%): Sends WARNING when coverage falls below
        - CRITICAL_THRESHOLD (85.0%): Sends ERROR when coverage falls below

    Features:
        - Tracks missing players for debugging
        - Sends alerts via notification system (email, Slack, Discord)
        - Reports metrics to Cloud Monitoring for dashboards
        - Detailed logging for troubleshooting
    """

    # Coverage thresholds (percentage)
    COVERAGE_THRESHOLD = 95.0  # Warn below this
    CRITICAL_THRESHOLD = 85.0  # Error below this

    # Metric names for Cloud Monitoring
    METRIC_COVERAGE_PERCENT = "predictions/coverage_percent"
    METRIC_MISSING_PLAYERS = "predictions/missing_players_count"
    METRIC_EXPECTED_PLAYERS = "predictions/expected_players_count"
    METRIC_PREDICTED_PLAYERS = "predictions/predicted_players_count"

    def __init__(
        self,
        coverage_threshold: Optional[float] = None,
        critical_threshold: Optional[float] = None,
        project_id: Optional[str] = None,
        processor_name: str = "PredictionCoordinator"
    ):
        """
        Initialize the coverage monitor.

        Args:
            coverage_threshold: Override default WARNING threshold (default: 95.0)
            critical_threshold: Override default CRITICAL threshold (default: 85.0)
            project_id: GCP project ID for metrics (uses env var if not provided)
            processor_name: Name used in alert messages
        """
        self.coverage_threshold = coverage_threshold or self.COVERAGE_THRESHOLD
        self.critical_threshold = critical_threshold or self.CRITICAL_THRESHOLD
        self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.processor_name = processor_name

        # Validate thresholds
        if self.critical_threshold >= self.coverage_threshold:
            logger.warning(
                f"Critical threshold ({self.critical_threshold}%) should be lower than "
                f"warning threshold ({self.coverage_threshold}%). Adjusting critical to {self.coverage_threshold - 10}%"
            )
            self.critical_threshold = self.coverage_threshold - 10.0

        logger.info(
            f"PredictionCoverageMonitor initialized: "
            f"warning_threshold={self.coverage_threshold}%, "
            f"critical_threshold={self.critical_threshold}%"
        )

    def check_coverage(
        self,
        players_expected: int,
        players_predicted: int,
        game_date: date,
        batch_id: Optional[str] = None,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Check prediction coverage and send alerts if below thresholds.

        Args:
            players_expected: Number of players expected to have predictions
            players_predicted: Number of players that actually received predictions
            game_date: The game date being checked
            batch_id: Optional batch identifier for correlation
            additional_context: Optional extra context for alerts

        Returns:
            True if coverage is acceptable (above warning threshold), False otherwise
        """
        # Handle edge cases
        if players_expected <= 0:
            logger.warning("No players expected - cannot calculate coverage")
            return True

        # Calculate coverage percentage
        coverage_percent = (players_predicted / players_expected) * 100
        missing_count = players_expected - players_predicted

        # Format date for logging
        date_str = game_date.strftime("%Y-%m-%d")

        logger.info(
            f"Coverage check for {date_str}: {players_predicted}/{players_expected} "
            f"({coverage_percent:.1f}%) - Missing: {missing_count}"
        )

        # Send metrics to Cloud Monitoring
        self._send_coverage_metrics(
            coverage_percent=coverage_percent,
            expected=players_expected,
            predicted=players_predicted,
            missing=missing_count,
            game_date=game_date
        )

        # Build alert details
        alert_details = {
            "game_date": date_str,
            "players_expected": players_expected,
            "players_predicted": players_predicted,
            "coverage_percent": f"{coverage_percent:.1f}%",
            "missing_count": missing_count,
            "warning_threshold": f"{self.coverage_threshold}%",
            "critical_threshold": f"{self.critical_threshold}%",
        }

        if batch_id:
            alert_details["batch_id"] = batch_id

        if additional_context:
            alert_details.update(additional_context)

        # Determine alert level and send notifications
        if coverage_percent < self.critical_threshold:
            # CRITICAL - send error alert
            self._send_critical_alert(
                coverage_percent=coverage_percent,
                game_date=date_str,
                details=alert_details
            )
            return False

        elif coverage_percent < self.coverage_threshold:
            # WARNING - send warning alert
            self._send_warning_alert(
                coverage_percent=coverage_percent,
                game_date=date_str,
                details=alert_details
            )
            return False

        else:
            # Coverage is acceptable
            logger.info(
                f"Coverage check PASSED: {coverage_percent:.1f}% >= {self.coverage_threshold}%"
            )
            return True

    def track_missing_players(
        self,
        expected_set: Set[str],
        predicted_set: Set[str],
        game_date: date,
        log_all: bool = False
    ) -> List[str]:
        """
        Track and log which players are missing predictions.

        Args:
            expected_set: Set of player identifiers that should have predictions
            predicted_set: Set of player identifiers that received predictions
            game_date: The game date being checked
            log_all: If True, log all missing players. If False, log summary only.

        Returns:
            List of missing player identifiers
        """
        # Find missing players
        missing_players = list(expected_set - predicted_set)
        missing_count = len(missing_players)

        date_str = game_date.strftime("%Y-%m-%d")

        if missing_count == 0:
            logger.info(f"All {len(expected_set)} expected players have predictions for {date_str}")
            return []

        # Log summary
        logger.warning(
            f"Missing predictions for {date_str}: {missing_count} players "
            f"({len(predicted_set)}/{len(expected_set)} covered)"
        )

        # Log individual players if requested or if count is small
        if log_all or missing_count <= 20:
            for idx, player_id in enumerate(sorted(missing_players)[:50], 1):
                logger.warning(f"  Missing player #{idx}: {player_id}")

            if missing_count > 50:
                logger.warning(f"  ... and {missing_count - 50} more")
        else:
            # Log just the first few
            sample_players = sorted(missing_players)[:5]
            logger.warning(
                f"  Sample missing players: {', '.join(sample_players)} "
                f"(and {missing_count - 5} more)"
            )

        # Send metric for missing player count
        self._send_metric(
            self.METRIC_MISSING_PLAYERS,
            float(missing_count),
            labels={
                "game_date": date_str,
            }
        )

        return missing_players

    def _send_critical_alert(
        self,
        coverage_percent: float,
        game_date: str,
        details: Dict[str, Any]
    ) -> None:
        """Send critical/error alert for very low coverage."""
        title = f"CRITICAL: Prediction Coverage at {coverage_percent:.1f}%"
        message = (
            f"Prediction coverage for {game_date} has fallen below the critical threshold "
            f"of {self.critical_threshold}%. Only {details.get('players_predicted', 0)} of "
            f"{details.get('players_expected', 0)} expected players received predictions. "
            f"Immediate investigation required."
        )

        logger.error(f"{title}: {message}", exc_info=True)

        # Add error_type for rate limiting in notification system
        details["error_type"] = "prediction_coverage_critical"

        if _check_notification_system():
            try:
                from shared.utils.notification_system import notify_error
                notify_error(
                    title=title,
                    message=message,
                    details=details,
                    processor_name=self.processor_name
                )
                logger.info("Critical coverage alert sent via notification system")
            except Exception as e:
                logger.error(f"Failed to send critical alert via notification system: {e}", exc_info=True)
        else:
            logger.error("Notification system unavailable - critical alert logged only")

    def _send_warning_alert(
        self,
        coverage_percent: float,
        game_date: str,
        details: Dict[str, Any]
    ) -> None:
        """Send warning alert for below-threshold coverage."""
        title = f"Warning: Prediction Coverage at {coverage_percent:.1f}%"
        message = (
            f"Prediction coverage for {game_date} is below the warning threshold "
            f"of {self.coverage_threshold}%. {details.get('players_predicted', 0)} of "
            f"{details.get('players_expected', 0)} expected players received predictions. "
            f"Please review for potential issues."
        )

        logger.warning(f"{title}: {message}")

        if _check_notification_system():
            try:
                from shared.utils.notification_system import notify_warning
                notify_warning(
                    title=title,
                    message=message,
                    details=details
                    processor_name=self.__class__.__name__
                )
                logger.info("Warning coverage alert sent via notification system")
            except Exception as e:
                logger.error(f"Failed to send warning alert via notification system: {e}", exc_info=True)
        else:
            logger.warning("Notification system unavailable - warning alert logged only")

    def _send_coverage_metrics(
        self,
        coverage_percent: float,
        expected: int,
        predicted: int,
        missing: int,
        game_date: date
    ) -> None:
        """Send coverage metrics to Cloud Monitoring."""
        date_str = game_date.strftime("%Y-%m-%d")

        # Send all coverage metrics
        metrics_to_send = [
            (self.METRIC_COVERAGE_PERCENT, coverage_percent),
            (self.METRIC_EXPECTED_PLAYERS, float(expected)),
            (self.METRIC_PREDICTED_PLAYERS, float(predicted)),
            (self.METRIC_MISSING_PLAYERS, float(missing)),
        ]

        labels = {"game_date": date_str}

        for metric_name, value in metrics_to_send:
            self._send_metric(metric_name, value, labels)

    def _send_metric(
        self,
        metric_name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None
    ) -> bool:
        """Send a single metric to Cloud Monitoring."""
        if not _check_metrics_available():
            logger.debug(f"Metrics unavailable - skipping {metric_name}={value}")
            return False

        try:
            from shared.utils.metrics_utils import send_metric
            success = send_metric(
                metric_name=metric_name,
                value=value,
                labels=labels,
                project_id=self.project_id
            )

            if success:
                logger.debug(f"Sent metric {metric_name}={value} with labels {labels}")
            else:
                logger.error(f"Failed to send metric {metric_name}")

            return success

        except Exception as e:
            logger.error(f"Error sending metric {metric_name}: {e}", exc_info=True)
            return False

    def generate_coverage_report(
        self,
        players_expected: int,
        players_predicted: int,
        game_date: date,
        missing_players: Optional[List[str]] = None,
        execution_time_seconds: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Generate a structured coverage report.

        Args:
            players_expected: Number of players expected
            players_predicted: Number of players with predictions
            game_date: The game date
            missing_players: Optional list of missing player IDs
            execution_time_seconds: Optional execution time

        Returns:
            Dictionary containing the full coverage report
        """
        coverage_percent = (
            (players_predicted / players_expected * 100)
            if players_expected > 0 else 100.0
        )
        missing_count = players_expected - players_predicted

        # Determine status
        if coverage_percent >= self.coverage_threshold:
            status = "HEALTHY"
        elif coverage_percent >= self.critical_threshold:
            status = "WARNING"
        else:
            status = "CRITICAL"

        report = {
            "report_type": "prediction_coverage",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "game_date": game_date.strftime("%Y-%m-%d"),
            "status": status,
            "coverage": {
                "percent": round(coverage_percent, 2),
                "expected": players_expected,
                "predicted": players_predicted,
                "missing": missing_count,
            },
            "thresholds": {
                "warning": self.coverage_threshold,
                "critical": self.critical_threshold,
            },
            "is_acceptable": coverage_percent >= self.coverage_threshold,
        }

        if missing_players:
            report["missing_players"] = {
                "count": len(missing_players),
                "sample": missing_players[:10],  # First 10 for brevity
                "full_list_available": len(missing_players) > 10,
            }

        if execution_time_seconds is not None:
            report["execution_time_seconds"] = round(execution_time_seconds, 2)

        return report


# Convenience function for simple coverage checks
def check_prediction_coverage(
    players_expected: int,
    players_predicted: int,
    game_date: date,
    batch_id: Optional[str] = None
) -> Tuple[bool, float]:
    """
    Quick convenience function to check prediction coverage.

    Args:
        players_expected: Number of expected players
        players_predicted: Number of predicted players
        game_date: The game date
        batch_id: Optional batch ID

    Returns:
        Tuple of (coverage_acceptable, coverage_percent)
    """
    monitor = PredictionCoverageMonitor()

    coverage_percent = (
        (players_predicted / players_expected * 100)
        if players_expected > 0 else 100.0
    )

    is_acceptable = monitor.check_coverage(
        players_expected=players_expected,
        players_predicted=players_predicted,
        game_date=game_date,
        batch_id=batch_id
    )

    return is_acceptable, coverage_percent


# Module initialization logging
logger.debug("coverage_monitor module loaded")
