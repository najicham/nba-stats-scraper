#!/usr/bin/env python3
"""
Workflow Health Monitor - Orchestration Health Validation

Monitors the master controller and workflow orchestration to detect:
1. Workflow decision gaps (master controller not running)
2. Phase transition delays (phases taking too long)
3. Processor execution failures (processors not completing)
4. Firestore/state inconsistencies

This script addresses the 45-hour outage that went undetected (Jan 23-25, 2026)
because count-based validation showed "data exists" but orchestration was dead.

Usage:
    python bin/validation/workflow_health.py
    python bin/validation/workflow_health.py --alert
    python bin/validation/workflow_health.py --hours 48 --threshold-minutes 120

Created: 2026-01-25
Part of: Pipeline Resilience Improvements
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Any
from enum import Enum

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')


class Severity(Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class HealthCheck:
    """Result of a health check."""
    name: str
    severity: Severity
    message: str
    details: Dict[str, Any]

    def to_dict(self):
        d = asdict(self)
        d['severity'] = self.severity.value
        return d


class WorkflowHealthMonitor:
    """
    Monitors orchestration health to detect outages early.

    Key insight from Jan 23-25 outage: The master controller stopped making
    workflow decisions for 45 hours, but this wasn't detected because data
    validation only checked "does data exist?" not "is orchestration running?"
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)
        self.checks: List[HealthCheck] = []

    def run_all_checks(self, hours: int = 48, threshold_minutes: int = 120) -> List[HealthCheck]:
        """Run all orchestration health checks."""
        self.checks = []

        # 1. Workflow decision gaps
        self._check_workflow_decision_gaps(hours, threshold_minutes)

        # 2. Recent phase transitions
        self._check_phase_transitions(hours)

        # 3. Processor completion rates
        self._check_processor_completions(hours)

        # 4. Failed processor queue
        self._check_failed_processor_queue()

        # 5. Decision frequency during business hours
        self._check_decision_frequency()

        # 6. Phase timing SLAs
        self._check_phase_timing_slas(hours)

        return self.checks

    def _query(self, sql: str) -> List[Dict]:
        """Execute a query and return results as dicts."""
        try:
            results = list(self.client.query(sql).result())
            return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []

    def _add_check(self, name: str, severity: Severity, message: str, details: Dict[str, Any]):
        """Add a health check result."""
        self.checks.append(HealthCheck(
            name=name,
            severity=severity,
            message=message,
            details=details
        ))

    def _check_workflow_decision_gaps(self, hours: int, threshold_minutes: int):
        """Check for gaps in workflow decisions (master controller health).

        This is the PRIMARY indicator of orchestration health. If no decisions
        are being made, the pipeline is effectively dead even if data exists.
        """
        query = f"""
        WITH decisions_with_gaps AS (
          SELECT
            decision_time,
            LAG(decision_time) OVER (ORDER BY decision_time) as prev_decision,
            TIMESTAMP_DIFF(
              decision_time,
              LAG(decision_time) OVER (ORDER BY decision_time),
              MINUTE
            ) as gap_minutes
          FROM `{self.project_id}.nba_orchestration.workflow_decisions`
          WHERE decision_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
        ),
        gap_analysis AS (
          SELECT
            MAX(gap_minutes) as max_gap_minutes,
            AVG(gap_minutes) as avg_gap_minutes,
            COUNT(*) as decision_count,
            MAX(decision_time) as last_decision,
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(decision_time), MINUTE) as minutes_since_last,
            COUNTIF(gap_minutes > {threshold_minutes}) as large_gaps
          FROM decisions_with_gaps
        ),
        largest_gaps AS (
          SELECT
            decision_time,
            gap_minutes
          FROM decisions_with_gaps
          WHERE gap_minutes > {threshold_minutes}
          ORDER BY gap_minutes DESC
          LIMIT 5
        )
        SELECT
          g.*,
          ARRAY_AGG(STRUCT(lg.decision_time, lg.gap_minutes) ORDER BY lg.gap_minutes DESC) as top_gaps
        FROM gap_analysis g
        LEFT JOIN largest_gaps lg ON TRUE
        GROUP BY g.max_gap_minutes, g.avg_gap_minutes, g.decision_count,
                 g.last_decision, g.minutes_since_last, g.large_gaps
        """

        results = self._query(query)

        if not results or results[0].get('last_decision') is None:
            self._add_check(
                name="workflow_decision_gaps",
                severity=Severity.CRITICAL,
                message=f"NO WORKFLOW DECISIONS in last {hours} hours! Master controller may be dead.",
                details={
                    "hours_checked": hours,
                    "decision_count": 0,
                    "status": "no_data"
                }
            )
            return

        row = results[0]
        max_gap = row.get('max_gap_minutes') or 0
        avg_gap = row.get('avg_gap_minutes') or 0
        minutes_since = row.get('minutes_since_last') or 0
        large_gaps = row.get('large_gaps') or 0
        decision_count = row.get('decision_count') or 0

        # Determine severity
        if minutes_since > threshold_minutes:
            severity = Severity.CRITICAL
            message = f"Master controller stopped! Last decision {minutes_since} minutes ago (threshold: {threshold_minutes})"
        elif max_gap > threshold_minutes * 2:
            severity = Severity.CRITICAL
            message = f"CRITICAL gap detected: {max_gap} min gap in workflow decisions"
        elif max_gap > threshold_minutes:
            severity = Severity.ERROR
            message = f"Large gap in decisions: {max_gap} min (threshold: {threshold_minutes})"
        elif large_gaps > 0:
            severity = Severity.WARNING
            message = f"{large_gaps} gaps > {threshold_minutes} min detected"
        else:
            severity = Severity.OK
            message = f"Workflow decisions healthy: {decision_count} decisions, max gap {max_gap} min"

        self._add_check(
            name="workflow_decision_gaps",
            severity=severity,
            message=message,
            details={
                "hours_checked": hours,
                "threshold_minutes": threshold_minutes,
                "decision_count": decision_count,
                "max_gap_minutes": max_gap,
                "avg_gap_minutes": round(avg_gap, 1) if avg_gap else 0,
                "minutes_since_last": minutes_since,
                "large_gaps_count": large_gaps
            }
        )

    def _check_phase_transitions(self, hours: int):
        """Check if phase transitions are happening."""
        query = f"""
        SELECT
          phase,
          COUNT(*) as transition_count,
          MAX(timestamp) as last_transition,
          TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(timestamp), HOUR) as hours_since_last
        FROM `{self.project_id}.nba_orchestration.pipeline_event_log`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
          AND event_type IN ('phase_start', 'phase_complete')
        GROUP BY phase
        ORDER BY phase
        """

        results = self._query(query)

        if not results:
            self._add_check(
                name="phase_transitions",
                severity=Severity.ERROR,
                message=f"No phase transitions in last {hours} hours",
                details={"hours_checked": hours, "status": "no_transitions"}
            )
            return

        # Check each phase
        phases_seen = {r['phase'] for r in results}
        expected_phases = {'phase_2', 'phase_3', 'phase_4', 'phase_5', 'phase_6'}
        missing_phases = expected_phases - phases_seen

        max_hours_since = max(r.get('hours_since_last', 0) or 0 for r in results)
        total_transitions = sum(r['transition_count'] for r in results)

        if missing_phases and max_hours_since < 24:
            # Some phases missing but recent activity
            severity = Severity.WARNING
            message = f"Missing activity in phases: {missing_phases}"
        elif max_hours_since > 12:
            severity = Severity.ERROR
            message = f"Stale phase transitions: last activity {max_hours_since} hours ago"
        elif max_hours_since > 6:
            severity = Severity.WARNING
            message = f"Phase transitions slowing: {max_hours_since} hours since last"
        else:
            severity = Severity.OK
            message = f"Phase transitions healthy: {total_transitions} transitions in {hours}h"

        self._add_check(
            name="phase_transitions",
            severity=severity,
            message=message,
            details={
                "hours_checked": hours,
                "total_transitions": total_transitions,
                "phases_active": list(phases_seen),
                "missing_phases": list(missing_phases),
                "by_phase": {r['phase']: r['transition_count'] for r in results}
            }
        )

    def _check_processor_completions(self, hours: int):
        """Check processor completion rates."""
        query = f"""
        WITH processor_events AS (
          SELECT
            processor_name,
            event_type,
            COUNT(*) as count
          FROM `{self.project_id}.nba_orchestration.pipeline_event_log`
          WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
            AND event_type IN ('processor_start', 'processor_complete', 'error')
          GROUP BY processor_name, event_type
        ),
        processor_stats AS (
          SELECT
            processor_name,
            MAX(CASE WHEN event_type = 'processor_start' THEN count ELSE 0 END) as starts,
            MAX(CASE WHEN event_type = 'processor_complete' THEN count ELSE 0 END) as completions,
            MAX(CASE WHEN event_type = 'error' THEN count ELSE 0 END) as errors
          FROM processor_events
          GROUP BY processor_name
        )
        SELECT
          processor_name,
          starts,
          completions,
          errors,
          CASE WHEN starts > 0 THEN ROUND(completions * 100.0 / starts, 1) ELSE 0 END as completion_rate
        FROM processor_stats
        WHERE starts > completions OR errors > 0
        ORDER BY errors DESC, completion_rate ASC
        """

        results = self._query(query)

        total_errors = sum(r.get('errors', 0) for r in results)
        low_completion = [r for r in results if r.get('completion_rate', 100) < 80]

        if total_errors > 10:
            severity = Severity.ERROR
            message = f"{total_errors} processor errors in last {hours} hours"
        elif low_completion:
            severity = Severity.WARNING
            message = f"{len(low_completion)} processors with low completion rate"
        else:
            severity = Severity.OK
            message = f"Processor completions healthy"

        self._add_check(
            name="processor_completions",
            severity=severity,
            message=message,
            details={
                "hours_checked": hours,
                "total_errors": total_errors,
                "low_completion_processors": [r['processor_name'] for r in low_completion],
                "problem_processors": [{
                    "name": r['processor_name'],
                    "starts": r['starts'],
                    "completions": r['completions'],
                    "errors": r['errors']
                } for r in results[:5]]
            }
        )

    def _check_failed_processor_queue(self):
        """Check the auto-retry failed processor queue."""
        query = f"""
        SELECT
          processor_name,
          error_type,
          retry_count,
          created_at,
          TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_at, HOUR) as hours_in_queue
        FROM `{self.project_id}.nba_orchestration.failed_processor_queue`
        WHERE status = 'pending'
        ORDER BY created_at
        """

        results = self._query(query)

        if not results:
            self._add_check(
                name="failed_processor_queue",
                severity=Severity.OK,
                message="No pending failed processors in retry queue",
                details={"pending_count": 0}
            )
            return

        old_failures = [r for r in results if r.get('hours_in_queue', 0) > 4]
        max_retries = max(r.get('retry_count', 0) for r in results)

        if old_failures:
            severity = Severity.ERROR
            message = f"{len(old_failures)} processors stuck in retry queue > 4 hours"
        elif max_retries >= 3:
            severity = Severity.WARNING
            message = f"Processors hitting retry limit (max retries: {max_retries})"
        else:
            severity = Severity.OK
            message = f"{len(results)} processors in retry queue (normal operation)"

        self._add_check(
            name="failed_processor_queue",
            severity=severity,
            message=message,
            details={
                "pending_count": len(results),
                "old_failures": len(old_failures),
                "max_retry_count": max_retries,
                "queued_processors": [r['processor_name'] for r in results[:5]]
            }
        )

    def _check_decision_frequency(self):
        """Check decision frequency during business hours (when games happen)."""
        query = f"""
        WITH hourly_decisions AS (
          SELECT
            EXTRACT(HOUR FROM decision_time) as hour,
            COUNT(*) as decision_count
          FROM `{self.project_id}.nba_orchestration.workflow_decisions`
          WHERE decision_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
          GROUP BY hour
        )
        SELECT
          hour,
          decision_count,
          CASE
            WHEN hour BETWEEN 18 AND 23 THEN 'prime_time'  -- 6 PM - 11 PM (game time)
            WHEN hour BETWEEN 0 AND 3 THEN 'late_night'     -- Midnight - 3 AM (post-game)
            ELSE 'off_hours'
          END as time_category
        FROM hourly_decisions
        ORDER BY hour
        """

        results = self._query(query)

        if not results:
            self._add_check(
                name="decision_frequency",
                severity=Severity.WARNING,
                message="No decision frequency data available",
                details={"status": "no_data"}
            )
            return

        # Check prime time coverage (when games happen)
        prime_time = [r for r in results if r.get('time_category') == 'prime_time']
        prime_time_avg = sum(r['decision_count'] for r in prime_time) / len(prime_time) if prime_time else 0

        if prime_time_avg < 5:
            severity = Severity.WARNING
            message = f"Low decision frequency during game hours (avg: {prime_time_avg:.1f}/hour)"
        else:
            severity = Severity.OK
            message = f"Decision frequency healthy (prime time avg: {prime_time_avg:.1f}/hour)"

        self._add_check(
            name="decision_frequency",
            severity=severity,
            message=message,
            details={
                "prime_time_avg": round(prime_time_avg, 1),
                "by_hour": {r['hour']: r['decision_count'] for r in results}
            }
        )

    def _check_phase_timing_slas(self, hours: int):
        """Check if phases are completing within expected time windows."""
        query = f"""
        WITH phase_durations AS (
          SELECT
            phase,
            game_date,
            MIN(CASE WHEN event_type = 'phase_start' THEN timestamp END) as start_time,
            MAX(CASE WHEN event_type = 'phase_complete' THEN timestamp END) as end_time
          FROM `{self.project_id}.nba_orchestration.pipeline_event_log`
          WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
            AND phase IS NOT NULL
          GROUP BY phase, game_date
          HAVING start_time IS NOT NULL AND end_time IS NOT NULL
        )
        SELECT
          phase,
          COUNT(*) as executions,
          AVG(TIMESTAMP_DIFF(end_time, start_time, MINUTE)) as avg_duration_min,
          MAX(TIMESTAMP_DIFF(end_time, start_time, MINUTE)) as max_duration_min
        FROM phase_durations
        GROUP BY phase
        ORDER BY phase
        """

        results = self._query(query)

        if not results:
            self._add_check(
                name="phase_timing_slas",
                severity=Severity.OK,
                message="No phase timing data to analyze",
                details={"status": "no_data"}
            )
            return

        # Define SLAs (in minutes)
        slas = {
            'phase_2': 30,   # Boxscore scraping
            'phase_3': 60,   # Analytics
            'phase_4': 45,   # Features
            'phase_5': 30,   # Predictions
            'phase_6': 15    # Export
        }

        violations = []
        for row in results:
            phase = row['phase']
            max_duration = row.get('max_duration_min') or 0
            sla = slas.get(phase, 60)

            if max_duration > sla * 2:
                violations.append(f"{phase}: {max_duration:.0f} min (SLA: {sla} min)")

        if violations:
            severity = Severity.WARNING
            message = f"Phase timing violations: {', '.join(violations[:3])}"
        else:
            severity = Severity.OK
            message = "All phases within timing SLAs"

        self._add_check(
            name="phase_timing_slas",
            severity=severity,
            message=message,
            details={
                "violations": violations,
                "by_phase": {
                    r['phase']: {
                        "avg_min": round(r.get('avg_duration_min') or 0, 1),
                        "max_min": round(r.get('max_duration_min') or 0, 1),
                        "sla_min": slas.get(r['phase'], 60)
                    }
                    for r in results
                }
            }
        )


def print_report(checks: List[HealthCheck]):
    """Print a formatted health report."""
    print("\n" + "=" * 80)
    print("WORKFLOW HEALTH MONITOR")
    print(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # Count by severity
    by_severity = {}
    for check in checks:
        sev = check.severity.value
        by_severity[sev] = by_severity.get(sev, 0) + 1

    # Summary
    print(f"\nSummary: {len(checks)} checks")
    for sev in ['critical', 'error', 'warning', 'ok']:
        count = by_severity.get(sev, 0)
        if count > 0:
            emoji = {'critical': '\U0001F534', 'error': '\U0001F7E0', 'warning': '\U0001F7E1', 'ok': '\U0001F7E2'}[sev]
            print(f"  {emoji} {sev.upper()}: {count}")

    # Details
    for check in checks:
        emoji = {
            Severity.CRITICAL: '\U0001F534',
            Severity.ERROR: '\U0001F7E0',
            Severity.WARNING: '\U0001F7E1',
            Severity.OK: '\U0001F7E2'
        }[check.severity]

        print(f"\n{'-'*40}")
        print(f"{emoji} {check.name}")
        print(f"   {check.message}")

        if check.severity != Severity.OK:
            for key, value in list(check.details.items())[:5]:
                if key not in ['status', 'by_hour', 'by_phase']:
                    print(f"   - {key}: {value}")

    print("\n" + "=" * 80)

    # Return exit code
    if by_severity.get('critical', 0) > 0:
        return 2
    elif by_severity.get('error', 0) > 0:
        return 1
    return 0


def send_alert(checks: List[HealthCheck]):
    """Send Slack alert for issues."""
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set, skipping alert")
        return

    import requests

    issues = [c for c in checks if c.severity in [Severity.CRITICAL, Severity.ERROR]]
    if not issues:
        return

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "\U0001F6A8 Orchestration Health Alert", "emoji": True}
        }
    ]

    for check in issues:
        emoji = '\U0001F534' if check.severity == Severity.CRITICAL else '\U0001F7E0'
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{emoji} *{check.name}*: {check.message}"}
        })

    try:
        response = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
        response.raise_for_status()
        logger.info("Alert sent to Slack")
    except Exception as e:
        logger.error(f"Failed to send alert: {e}")


def main():
    parser = argparse.ArgumentParser(description="Workflow health monitor")
    parser.add_argument('--hours', type=int, default=48, help='Hours to check (default: 48)')
    parser.add_argument('--threshold-minutes', type=int, default=120,
                        help='Gap threshold in minutes (default: 120)')
    parser.add_argument('--alert', action='store_true', help='Send Slack alert on issues')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    monitor = WorkflowHealthMonitor()
    checks = monitor.run_all_checks(hours=args.hours, threshold_minutes=args.threshold_minutes)

    if args.json:
        output = {
            "run_time": datetime.now().isoformat(),
            "checks": [c.to_dict() for c in checks]
        }
        print(json.dumps(output, indent=2))
        exit_code = 0
    else:
        exit_code = print_report(checks)

    if args.alert:
        send_alert(checks)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
