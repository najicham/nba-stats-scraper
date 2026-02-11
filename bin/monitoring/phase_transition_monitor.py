#!/usr/bin/env python3
"""
Phase Transition Monitor - Real-time Pipeline Health Alerting

Monitors for:
1. Workflow decision gaps (master controller not making decisions)
2. Phase transition delays (Phase N complete but Phase N+1 not started)
3. Stuck processors (running too long)
4. Data completeness issues

Designed to be run every 10-15 minutes by Cloud Scheduler.
Would have caught the 45-hour outage in < 30 minutes.

Usage:
    python bin/monitoring/phase_transition_monitor.py
    python bin/monitoring/phase_transition_monitor.py --alert  # Send Slack alerts
    python bin/monitoring/phase_transition_monitor.py --continuous  # Run every 10 min

Created: 2026-01-25
Part of: Pipeline Resilience Improvements
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery
from google.cloud import firestore
import requests


# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')

# Thresholds (in minutes)
WORKFLOW_DECISION_GAP_WARNING = 60    # Warn if no decision in 1 hour
WORKFLOW_DECISION_GAP_CRITICAL = 120  # Critical if no decision in 2 hours
PHASE_TRANSITION_DELAY_WARNING = 30   # Warn if phase transition > 30 min
PHASE_TRANSITION_DELAY_CRITICAL = 60  # Critical if phase transition > 1 hour
PROCESSOR_STALE_THRESHOLD = 240       # 4 hours = processor likely stuck

ET = ZoneInfo("America/New_York")


class Severity(Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Alert:
    name: str
    severity: Severity
    message: str
    details: Dict[str, Any]
    timestamp: datetime


class PhaseTransitionMonitor:
    """Monitor phase transitions and workflow decisions for pipeline health."""

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)
        self.fs_client = firestore.Client()
        self.alerts: List[Alert] = []

    def run_all_checks(self) -> List[Alert]:
        """Run all monitoring checks and return alerts."""
        self.alerts = []

        print("\n" + "=" * 70)
        print("PHASE TRANSITION MONITOR")
        print(f"Time: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S ET')}")
        print("=" * 70)

        # Check workflow decision gaps
        self._check_workflow_decisions()

        # Check phase transitions
        self._check_phase_transitions()

        # Check for stuck processors
        self._check_stuck_processors()

        # Check data completeness
        self._check_data_completeness()

        # Summary
        self._print_summary()

        return self.alerts

    def _add_alert(self, name: str, severity: Severity, message: str, details: Dict = None):
        """Add an alert to the list."""
        alert = Alert(
            name=name,
            severity=severity,
            message=message,
            details=details or {},
            timestamp=datetime.now(ET)
        )
        self.alerts.append(alert)

        # Print immediately
        icon = {
            Severity.OK: "✅",
            Severity.WARNING: "⚠️",
            Severity.ERROR: "❌",
            Severity.CRITICAL: "🚨"
        }[severity]

        print(f"\n{icon} [{severity.value.upper()}] {name}")
        print(f"   {message}")
        if details:
            for k, v in details.items():
                print(f"   {k}: {v}")

    def _check_workflow_decisions(self):
        """Check for gaps in workflow decisions (master controller health)."""
        print("\n" + "-" * 50)
        print("WORKFLOW DECISION CHECK")
        print("-" * 50)

        query = f"""
        WITH decisions AS (
            SELECT
                decision_time,
                LAG(decision_time) OVER (ORDER BY decision_time) as prev_decision,
                TIMESTAMP_DIFF(
                    decision_time,
                    LAG(decision_time) OVER (ORDER BY decision_time),
                    MINUTE
                ) as gap_minutes
            FROM `{self.project_id}.nba_orchestration.workflow_decisions`
            WHERE decision_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
        )
        SELECT
            MAX(decision_time) as last_decision,
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(decision_time), MINUTE) as minutes_since_last,
            MAX(gap_minutes) as max_gap_minutes,
            COUNT(*) as total_decisions
        FROM decisions
        """

        try:
            results = list(self.bq_client.query(query).result())
            if not results or results[0].last_decision is None:
                self._add_alert(
                    "workflow_decisions",
                    Severity.CRITICAL,
                    "No workflow decisions found in last 48 hours!",
                    {"status": "no_data"}
                )
                return

            row = results[0]
            minutes_since_last = row.minutes_since_last or 0
            max_gap = row.max_gap_minutes or 0
            last_decision = row.last_decision

            print(f"   Last decision: {last_decision}")
            print(f"   Minutes since last: {minutes_since_last}")
            print(f"   Max gap in 48h: {max_gap} minutes")

            # Determine severity
            if minutes_since_last > WORKFLOW_DECISION_GAP_CRITICAL:
                self._add_alert(
                    "workflow_decisions",
                    Severity.CRITICAL,
                    f"Master controller not running! No decisions in {minutes_since_last} minutes",
                    {
                        "minutes_since_last": minutes_since_last,
                        "last_decision": str(last_decision),
                        "threshold": WORKFLOW_DECISION_GAP_CRITICAL
                    }
                )
            elif minutes_since_last > WORKFLOW_DECISION_GAP_WARNING:
                self._add_alert(
                    "workflow_decisions",
                    Severity.WARNING,
                    f"Workflow decisions delayed - {minutes_since_last} minutes since last",
                    {
                        "minutes_since_last": minutes_since_last,
                        "last_decision": str(last_decision)
                    }
                )
            elif max_gap > WORKFLOW_DECISION_GAP_CRITICAL:
                self._add_alert(
                    "workflow_decisions",
                    Severity.ERROR,
                    f"Large gap detected in recent history: {max_gap} minutes",
                    {"max_gap_minutes": max_gap}
                )
            else:
                self._add_alert(
                    "workflow_decisions",
                    Severity.OK,
                    f"Workflow decisions healthy ({minutes_since_last} min since last)",
                    {"minutes_since_last": minutes_since_last}
                )

        except Exception as e:
            self._add_alert(
                "workflow_decisions",
                Severity.ERROR,
                f"Failed to check workflow decisions: {e}",
                {"error": str(e)}
            )

    def _check_phase_transitions(self):
        """Check if phase transitions are completing in expected time."""
        print("\n" + "-" * 50)
        print("PHASE TRANSITION CHECK")
        print("-" * 50)

        today = datetime.now(ET).strftime("%Y-%m-%d")
        yesterday = (datetime.now(ET) - timedelta(days=1)).strftime("%Y-%m-%d")

        for game_date in [today, yesterday]:
            self._check_phase_for_date(game_date)

    def _check_phase_for_date(self, game_date: str):
        """Check phase transitions for a specific date."""
        print(f"\n   Checking {game_date}:")

        # NOTE: Phase 2→3 is event-driven (direct Pub/Sub subscription)
        # and doesn't use the orchestrator trigger pattern. Skip monitoring it.
        # Only check Phase 3→4 and Phase 4→5 which use functional orchestrators.

        p3_status = self._get_phase_status("phase3_completion", game_date)
        p4_status = self._get_phase_status("phase4_completion", game_date)

        # Phase 3 → 4 transition (removed Phase 2→3 check)
                        f"Phase 2→3 delayed for {game_date}: {minutes_waiting} min",
                        {
                            "game_date": game_date,
                            "phase": "2→3",
                            "minutes_waiting": minutes_waiting
                        }
                    )

        # Phase 3 → 4 transition
        if p3_status.get('_triggered') and not p4_status:
            triggered_at = p3_status.get('_first_completion_at')
            if triggered_at:
                minutes_waiting = self._minutes_since(triggered_at)
                if minutes_waiting > PHASE_TRANSITION_DELAY_CRITICAL:
                    self._add_alert(
                        f"phase_transition_{game_date}",
                        Severity.CRITICAL,
                        f"Phase 3→4 STUCK for {game_date}: {minutes_waiting} min waiting",
                        {
                            "game_date": game_date,
                            "phase": "3→4",
                            "minutes_waiting": minutes_waiting
                        }
                    )

        # Log current state
        p3_count = len([k for k in p3_status.keys() if not k.startswith('_')]) if p3_status else 0
        p4_count = len([k for k in p4_status.keys() if not k.startswith('_')]) if p4_status else 0
        print(f"      Phase 3: {p3_count}/5 complete, triggered={p3_status.get('_triggered', False) if p3_status else False}")
        print(f"      Phase 4: {p4_count}/5 complete, triggered={p4_status.get('_triggered', False) if p4_status else False}")

    def _get_phase_status(self, collection: str, game_date: str) -> Dict:
        """Get phase completion status from Firestore."""
        try:
            doc = self.fs_client.collection(collection).document(game_date).get()
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            print(f"      Error reading {collection}/{game_date}: {e}")
        return {}

    def _minutes_since(self, timestamp) -> int:
        """Calculate minutes since a timestamp."""
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                # CRITICAL FIX (Jan 25, 2026): Don't use bare except
                # Bare except catches KeyboardInterrupt, SystemExit, etc.
                return 0

        if hasattr(timestamp, 'timestamp'):
            now = datetime.now(ET)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=ET)
            diff = now - timestamp
            return int(diff.total_seconds() / 60)
        return 0

    def _check_stuck_processors(self):
        """Check for processors that have been running too long."""
        print("\n" + "-" * 50)
        print("STUCK PROCESSOR CHECK")
        print("-" * 50)

        try:
            # Check Firestore run_history for stuck entries
            stuck_docs = list(
                self.fs_client.collection('run_history')
                .where('status', '==', 'running')
                .stream()
            )

            stuck_count = 0
            for doc in stuck_docs:
                data = doc.to_dict()
                started_at = data.get('started_at')
                if started_at:
                    minutes_running = self._minutes_since(started_at)
                    if minutes_running > PROCESSOR_STALE_THRESHOLD:
                        stuck_count += 1
                        self._add_alert(
                            f"stuck_processor_{doc.id}",
                            Severity.WARNING,
                            f"Processor stuck: {data.get('processor_name', 'unknown')} running {minutes_running} min",
                            {
                                "processor": data.get('processor_name'),
                                "minutes_running": minutes_running,
                                "doc_id": doc.id
                            }
                        )

            if stuck_count == 0:
                print("   No stuck processors found")
            else:
                print(f"   Found {stuck_count} stuck processors")

        except Exception as e:
            print(f"   Error checking stuck processors: {e}")

    def _check_data_completeness(self):
        """Quick check on data completeness for today."""
        print("\n" + "-" * 50)
        print("DATA COMPLETENESS CHECK")
        print("-" * 50)

        today = datetime.now(ET).strftime("%Y-%m-%d")

        query = f"""
        WITH schedule AS (
            SELECT COUNT(DISTINCT game_id) as expected_games
            FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
            WHERE game_date = '{today}'
        ),
        boxscores AS (
            SELECT COUNT(DISTINCT game_id) as actual_games
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE game_date = '{today}'
        ),
        predictions AS (
            SELECT
                COUNT(*) as pred_count,
                COUNT(DISTINCT player_lookup) as players
            FROM `{self.project_id}.nba_predictions.player_prop_predictions`
            WHERE game_date = '{today}'
                AND system_id = 'catboost_v8'
                AND is_active = TRUE
        )
        SELECT
            s.expected_games,
            b.actual_games,
            p.pred_count,
            p.players
        FROM schedule s, boxscores b, predictions p
        """

        try:
            results = list(self.bq_client.query(query).result())
            if results:
                row = results[0]
                print(f"   Today ({today}):")
                print(f"      Expected games: {row.expected_games}")
                print(f"      Games with boxscores: {row.actual_games}")
                print(f"      Predictions: {row.pred_count} ({row.players} players)")

                # Alert if games scheduled but no predictions
                if row.expected_games > 0 and row.pred_count == 0:
                    # Check if we're in prediction window (before games start)
                    hour = datetime.now(ET).hour
                    if hour >= 10:  # After 10 AM ET, predictions should exist
                        self._add_alert(
                            "data_completeness",
                            Severity.WARNING,
                            f"No predictions for today despite {row.expected_games} games scheduled",
                            {
                                "expected_games": row.expected_games,
                                "predictions": row.pred_count
                            }
                        )
        except Exception as e:
            print(f"   Error checking completeness: {e}")

    def _print_summary(self):
        """Print summary of all alerts."""
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)

        critical = [a for a in self.alerts if a.severity == Severity.CRITICAL]
        errors = [a for a in self.alerts if a.severity == Severity.ERROR]
        warnings = [a for a in self.alerts if a.severity == Severity.WARNING]
        ok = [a for a in self.alerts if a.severity == Severity.OK]

        print(f"   🚨 Critical: {len(critical)}")
        print(f"   ❌ Errors: {len(errors)}")
        print(f"   ⚠️ Warnings: {len(warnings)}")
        print(f"   ✅ OK: {len(ok)}")

        if critical or errors:
            print("\n   ACTION REQUIRED - Check alerts above!")

        print()

    def send_slack_alerts(self) -> bool:
        """Send critical/error alerts to Slack."""
        if not SLACK_WEBHOOK_URL:
            print("No SLACK_WEBHOOK_URL configured, skipping Slack notification")
            return False

        critical_alerts = [a for a in self.alerts if a.severity in [Severity.CRITICAL, Severity.ERROR]]

        if not critical_alerts:
            print("No critical alerts to send")
            return True

        # Build Slack message
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🚨 Pipeline Alert - Phase Transition Monitor"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{len(critical_alerts)} alerts require attention*"
                }
            },
            {"type": "divider"}
        ]

        for alert in critical_alerts[:5]:  # Limit to 5 alerts
            icon = "🚨" if alert.severity == Severity.CRITICAL else "❌"
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{icon} *{alert.name}*\n{alert.message}"
                }
            })

        payload = {"blocks": blocks}

        try:
            response = requests.post(
                SLACK_WEBHOOK_URL,
                json=payload,
                timeout=10
            )
            if response.status_code == 200:
                print("Slack alert sent successfully")
                return True
            else:
                print(f"Slack alert failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"Error sending Slack alert: {e}")
            return False

    def get_exit_code(self) -> int:
        """Return exit code based on alert severity."""
        if any(a.severity == Severity.CRITICAL for a in self.alerts):
            return 2
        if any(a.severity == Severity.ERROR for a in self.alerts):
            return 1
        return 0


def main():
    parser = argparse.ArgumentParser(description="Monitor phase transitions for pipeline health")
    parser.add_argument('--alert', action='store_true', help='Send Slack alerts for critical issues')
    parser.add_argument('--continuous', action='store_true', help='Run continuously every 10 minutes')
    parser.add_argument('--interval', type=int, default=10, help='Interval in minutes for continuous mode')
    args = parser.parse_args()

    monitor = PhaseTransitionMonitor()

    if args.continuous:
        print(f"Running in continuous mode (every {args.interval} minutes)")
        print("Press Ctrl+C to stop\n")

        while True:
            try:
                monitor.run_all_checks()

                if args.alert:
                    monitor.send_slack_alerts()

                print(f"\nSleeping {args.interval} minutes...")
                time.sleep(args.interval * 60)

            except KeyboardInterrupt:
                print("\nStopping continuous monitoring")
                break
    else:
        monitor.run_all_checks()

        if args.alert:
            monitor.send_slack_alerts()

        sys.exit(monitor.get_exit_code())


if __name__ == "__main__":
    main()
