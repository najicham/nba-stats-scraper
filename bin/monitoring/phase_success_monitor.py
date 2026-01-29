#!/usr/bin/env python3
"""
Phase Success Rate Monitor - Real-time completion rate alerting.

Monitors pipeline_event_log for phase completion rates and alerts when
they drop below thresholds. Designed to catch Phase 3 and Phase 4 issues
before they cascade into missing predictions.

Thresholds:
- Phase 3: Alert if < 80% success rate
- Phase 4: Alert if < 80% success rate

Usage:
    python bin/monitoring/phase_success_monitor.py
    python bin/monitoring/phase_success_monitor.py --hours 2
    python bin/monitoring/phase_success_monitor.py --hours 4 --alert
    python bin/monitoring/phase_success_monitor.py --continuous --interval 15

Created: 2026-01-28
Part of: Pipeline Resilience Improvements
"""

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery
import requests


# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
ORCHESTRATION_DATASET = os.environ.get('ORCHESTRATION_DATASET', 'nba_orchestration')

# Timezone
ET = ZoneInfo("America/New_York")

# Default thresholds
DEFAULT_PHASE_3_THRESHOLD = 80.0  # Alert if Phase 3 success rate < 80%
DEFAULT_PHASE_4_THRESHOLD = 80.0  # Alert if Phase 4 success rate < 80%

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """Alert severity levels."""
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


def calculate_phase_status(start_count: int, success_rate: float, threshold: float) -> Severity:
    """
    Calculate severity status based on success rate vs threshold.

    Args:
        start_count: Number of processor starts
        success_rate: Current success rate as percentage
        threshold: Threshold percentage

    Returns:
        Severity level
    """
    if start_count == 0:
        return Severity.OK  # No data, nothing to alert on
    elif success_rate < threshold:
        if success_rate < threshold - 20:
            return Severity.CRITICAL
        else:
            return Severity.ERROR
    elif success_rate < threshold + 10:
        return Severity.WARNING
    else:
        return Severity.OK


@dataclass
class PhaseStats:
    """Statistics for a single phase."""
    phase: str
    start_count: int
    complete_count: int
    error_count: int
    success_rate: float
    threshold: float
    status: Severity = Severity.OK

    def __post_init__(self):
        """Determine status based on success rate vs threshold."""
        self.status = calculate_phase_status(self.start_count, self.success_rate, self.threshold)


@dataclass
class MonitorResult:
    """Result of monitoring run."""
    timestamp: datetime
    hours_checked: int
    phases: List[PhaseStats] = field(default_factory=list)
    overall_status: Severity = Severity.OK
    errors_by_processor: Dict[str, int] = field(default_factory=dict)

    def add_phase(self, phase: PhaseStats):
        """Add phase stats and update overall status."""
        self.phases.append(phase)
        if phase.status == Severity.CRITICAL:
            self.overall_status = Severity.CRITICAL
        elif phase.status == Severity.ERROR and self.overall_status != Severity.CRITICAL:
            self.overall_status = Severity.ERROR
        elif phase.status == Severity.WARNING and self.overall_status in [Severity.OK]:
            self.overall_status = Severity.WARNING


class PhaseSuccessMonitor:
    """
    Monitor phase success rates using pipeline_event_log.

    Queries BigQuery for processor_start and processor_complete events
    to calculate success rates per phase.
    """

    def __init__(
        self,
        project_id: str = PROJECT_ID,
        dataset: str = ORCHESTRATION_DATASET,
        phase3_threshold: float = DEFAULT_PHASE_3_THRESHOLD,
        phase4_threshold: float = DEFAULT_PHASE_4_THRESHOLD
    ):
        self.project_id = project_id
        self.dataset = dataset
        self.phase3_threshold = phase3_threshold
        self.phase4_threshold = phase4_threshold
        self.bq_client = bigquery.Client(project=project_id)

    def check_success_rates(self, hours: int = 2) -> MonitorResult:
        """
        Check phase success rates for the last N hours.

        Args:
            hours: Number of hours to look back

        Returns:
            MonitorResult with phase statistics
        """
        result = MonitorResult(
            timestamp=datetime.now(ET),
            hours_checked=hours
        )

        print("\n" + "=" * 70)
        print("PHASE SUCCESS RATE MONITOR")
        print(f"Time: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S ET')}")
        print(f"Checking last {hours} hours")
        print("=" * 70)

        # Query for phase success rates
        phase_stats = self._query_phase_success_rates(hours)

        # Check Phase 3
        phase_3_stats = phase_stats.get('phase_3', {})
        phase_3 = PhaseStats(
            phase='phase_3',
            start_count=phase_3_stats.get('start_count', 0),
            complete_count=phase_3_stats.get('complete_count', 0),
            error_count=phase_3_stats.get('error_count', 0),
            success_rate=phase_3_stats.get('success_rate', 100.0),
            threshold=self.phase3_threshold
        )
        result.add_phase(phase_3)

        # Check Phase 4
        phase_4_stats = phase_stats.get('phase_4', {})
        phase_4 = PhaseStats(
            phase='phase_4',
            start_count=phase_4_stats.get('start_count', 0),
            complete_count=phase_4_stats.get('complete_count', 0),
            error_count=phase_4_stats.get('error_count', 0),
            success_rate=phase_4_stats.get('success_rate', 100.0),
            threshold=self.phase4_threshold
        )
        result.add_phase(phase_4)

        # Get error breakdown
        result.errors_by_processor = self._query_error_breakdown(hours)

        # Print results
        self._print_results(result)

        return result

    def _query_phase_success_rates(self, hours: int) -> Dict[str, Dict[str, Any]]:
        """
        Query BigQuery for phase success rates.

        Calculates: success_rate = (processor_complete / processor_start) * 100

        Args:
            hours: Number of hours to look back

        Returns:
            Dict mapping phase name to stats
        """
        query = f"""
        WITH events AS (
            SELECT
                phase,
                event_type,
                processor_name,
                timestamp
            FROM `{self.project_id}.{self.dataset}.pipeline_event_log`
            WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
              AND phase IN ('phase_3', 'phase_4')
              AND event_type IN ('processor_start', 'processor_complete', 'error')
        ),
        phase_counts AS (
            SELECT
                phase,
                COUNTIF(event_type = 'processor_start') as start_count,
                COUNTIF(event_type = 'processor_complete') as complete_count,
                COUNTIF(event_type = 'error') as error_count
            FROM events
            GROUP BY phase
        )
        SELECT
            phase,
            start_count,
            complete_count,
            error_count,
            CASE
                WHEN start_count = 0 THEN 100.0
                ELSE ROUND((complete_count * 100.0) / start_count, 2)
            END as success_rate
        FROM phase_counts
        ORDER BY phase
        """

        try:
            results = list(self.bq_client.query(query).result())

            phase_stats = {}
            for row in results:
                phase_stats[row.phase] = {
                    'start_count': row.start_count,
                    'complete_count': row.complete_count,
                    'error_count': row.error_count,
                    'success_rate': row.success_rate
                }

            return phase_stats

        except Exception as e:
            logger.error(f"Failed to query phase success rates: {e}")
            return {}

    def _query_error_breakdown(self, hours: int) -> Dict[str, int]:
        """
        Query for error counts by processor.

        Args:
            hours: Number of hours to look back

        Returns:
            Dict mapping processor_name to error count
        """
        query = f"""
        SELECT
            processor_name,
            COUNT(*) as error_count
        FROM `{self.project_id}.{self.dataset}.pipeline_event_log`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
          AND event_type = 'error'
          AND phase IN ('phase_3', 'phase_4')
        GROUP BY processor_name
        ORDER BY error_count DESC
        LIMIT 10
        """

        try:
            results = list(self.bq_client.query(query).result())
            return {row.processor_name: row.error_count for row in results}

        except Exception as e:
            logger.warning(f"Failed to query error breakdown: {e}")
            return {}

    def _print_results(self, result: MonitorResult):
        """Print monitoring results to console."""
        status_icons = {
            Severity.OK: "[OK]",
            Severity.WARNING: "[WARN]",
            Severity.ERROR: "[ERROR]",
            Severity.CRITICAL: "[CRITICAL]"
        }

        print("\n" + "-" * 50)
        print("PHASE SUCCESS RATES")
        print("-" * 50)

        for phase in result.phases:
            icon = status_icons[phase.status]
            print(f"\n{icon} {phase.phase.upper()}")
            print(f"   Started: {phase.start_count}")
            print(f"   Completed: {phase.complete_count}")
            print(f"   Errors: {phase.error_count}")
            print(f"   Success Rate: {phase.success_rate:.1f}% (threshold: {phase.threshold}%)")

        if result.errors_by_processor:
            print("\n" + "-" * 50)
            print("TOP ERRORS BY PROCESSOR")
            print("-" * 50)
            for processor, count in result.errors_by_processor.items():
                print(f"   {processor}: {count} errors")

        print("\n" + "=" * 70)
        print(f"OVERALL STATUS: {status_icons[result.overall_status]} {result.overall_status.value.upper()}")
        print("=" * 70 + "\n")

    def send_slack_alert(self, result: MonitorResult) -> bool:
        """
        Send Slack notification for phase success rate issues.

        Only sends if there are errors or critical issues.

        Args:
            result: MonitorResult with phase statistics

        Returns:
            True if alert was sent successfully
        """
        if not SLACK_WEBHOOK_URL:
            logger.warning("No SLACK_WEBHOOK_URL configured, skipping notification")
            return False

        # Only alert on error or critical
        if result.overall_status not in [Severity.ERROR, Severity.CRITICAL]:
            logger.info("No errors to alert on, skipping Slack notification")
            return True

        # Build Slack message
        severity_emoji = {
            Severity.ERROR: ":warning:",
            Severity.CRITICAL: ":rotating_light:"
        }

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{severity_emoji.get(result.overall_status, ':warning:')} Phase Success Rate Alert",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Status:* {result.overall_status.value.upper()}\n*Time Range:* Last {result.hours_checked} hours"
                }
            },
            {"type": "divider"}
        ]

        # Add phase details for failed phases
        for phase in result.phases:
            if phase.status in [Severity.ERROR, Severity.CRITICAL]:
                status_emoji = ":x:" if phase.status == Severity.CRITICAL else ":warning:"
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"{status_emoji} *{phase.phase.upper()}*\n"
                            f"Success Rate: *{phase.success_rate:.1f}%* (threshold: {phase.threshold}%)\n"
                            f"Started: {phase.start_count} | Completed: {phase.complete_count} | Errors: {phase.error_count}"
                        )
                    }
                })

        # Add error breakdown if available
        if result.errors_by_processor:
            error_lines = [f"- {proc}: {count} errors" for proc, count in list(result.errors_by_processor.items())[:5]]
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Top Errors by Processor:*\n" + "\n".join(error_lines)
                }
            })

        # Add context
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"Generated: {result.timestamp.strftime('%Y-%m-%d %H:%M ET')} | "
                       f"Run: `python bin/monitoring/phase_success_monitor.py --hours {result.hours_checked}`"
            }]
        })

        payload = {"blocks": blocks}

        try:
            response = requests.post(
                SLACK_WEBHOOK_URL,
                json=payload,
                timeout=10
            )
            if response.status_code == 200:
                logger.info("Slack alert sent successfully")
                return True
            else:
                logger.error(f"Slack alert failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error sending Slack alert: {e}")
            return False

    def get_exit_code(self, result: MonitorResult) -> int:
        """
        Get exit code based on result status.

        Returns:
            0 for OK/WARNING, 1 for ERROR, 2 for CRITICAL
        """
        if result.overall_status == Severity.CRITICAL:
            return 2
        elif result.overall_status == Severity.ERROR:
            return 1
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Monitor phase success rates and alert on drops below threshold"
    )
    parser.add_argument(
        '--hours',
        type=int,
        default=2,
        help='Number of hours to look back (default: 2)'
    )
    parser.add_argument(
        '--alert',
        action='store_true',
        help='Send Slack alerts for issues'
    )
    parser.add_argument(
        '--continuous',
        action='store_true',
        help='Run continuously at specified interval'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=15,
        help='Interval in minutes for continuous mode (default: 15)'
    )
    parser.add_argument(
        '--phase3-threshold',
        type=float,
        default=DEFAULT_PHASE_3_THRESHOLD,
        help=f'Phase 3 success rate threshold (default: {DEFAULT_PHASE_3_THRESHOLD})'
    )
    parser.add_argument(
        '--phase4-threshold',
        type=float,
        default=DEFAULT_PHASE_4_THRESHOLD,
        help=f'Phase 4 success rate threshold (default: {DEFAULT_PHASE_4_THRESHOLD})'
    )
    args = parser.parse_args()

    monitor = PhaseSuccessMonitor(
        phase3_threshold=args.phase3_threshold,
        phase4_threshold=args.phase4_threshold
    )

    if args.continuous:
        print(f"Running in continuous mode (every {args.interval} minutes)")
        print("Press Ctrl+C to stop\n")

        while True:
            try:
                result = monitor.check_success_rates(hours=args.hours)

                if args.alert:
                    monitor.send_slack_alert(result)

                print(f"Sleeping {args.interval} minutes...")
                time.sleep(args.interval * 60)

            except KeyboardInterrupt:
                print("\nStopping continuous monitoring")
                break
    else:
        result = monitor.check_success_rates(hours=args.hours)

        if args.alert:
            monitor.send_slack_alert(result)

        sys.exit(monitor.get_exit_code(result))


if __name__ == "__main__":
    main()
