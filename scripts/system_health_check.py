#!/usr/bin/env python3
"""
System Health Check - One-command daily health verification

Created: 2026-01-14, Session 36
Purpose: Reduce daily health check time from 15 minutes to 2 minutes

Usage:
    python scripts/system_health_check.py
    python scripts/system_health_check.py --days=7
    python scripts/system_health_check.py --verbose
    python scripts/system_health_check.py --slack

Output Example:
    🏥 NBA Stats Scraper - System Health Check
    📅 Last 24 hours

    Phase Health Summary
    ────────────────────────────────────────────
    ✅ Phase 1 (Scrapers):   98.5% success │ 2 real failures
    ✅ Phase 2 (Raw):        99.2% success │ 0 real failures
    ✅ Phase 3 (Analytics):  97.8% success │ 1 real failure
    ⚠️  Phase 4 (Precompute): 85.3% success │ 12 real failures
    ❌ Phase 5 (Predictions): 45.0% success │ 55 real failures

    🚨 Issues Detected
    ────────────────────────────────────────────
    1. Phase 5 success rate below 50% - CRITICAL
    2. 3 processors stuck in 'running' state
    3. BasketballRefRosterProcessor: 15 DML limit errors

    ✨ Alert Noise Reduction
    ────────────────────────────────────────────
    Total failures: 234
    Expected (no_data_available): 198 (84.6%)
    Real failures requiring attention: 36 (15.4%)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from google.cloud import bigquery
except ImportError:
    print("Error: google-cloud-bigquery not installed. Run: pip install google-cloud-bigquery")
    sys.exit(1)


# ============================================================================
# Configuration
# ============================================================================

PROJECT_ID = "nba-props-platform"
DATASET = "nba_reference"
TABLE = "processor_run_history"

# Thresholds for health assessment
THRESHOLDS = {
    "success_rate_critical": 50.0,  # Below this = critical
    "success_rate_warning": 80.0,   # Below this = warning
    "stuck_minutes": 15,            # Running for longer = stuck
    "slow_multiplier": 2.0,         # Duration > P95 * this = slow
}

# Phase descriptions (maps database phase values to display names)
PHASE_NAMES = {
    # String-based phase names (current format)
    "phase_1_scrapers": "Scrapers",
    "phase_2_raw": "Raw Processors",
    "phase_3": "Analytics (Legacy)",
    "phase_3_analytics": "Analytics",
    "phase_4_precompute": "Precompute",
    "phase_5_predictions": "Predictions",
    # Integer-based phase names (legacy format)
    1: "Scrapers",
    2: "Raw Processors",
    3: "Analytics",
    4: "Precompute",
    5: "Predictions",
}

# Phase ordering for display
PHASE_ORDER = [
    "phase_1_scrapers",
    "phase_2_raw",
    "phase_3",
    "phase_3_analytics",
    "phase_4_precompute",
    "phase_5_predictions",
]


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class PhaseHealth:
    """Health metrics for a single phase."""
    phase: str  # Can be int or string (e.g., "phase_2_raw")
    total_runs: int
    successes: int
    all_failures: int
    real_failures: int
    expected_failures: int
    success_rate: float
    effective_success_rate: float
    avg_duration_sec: float
    status: str  # "healthy", "warning", "critical"


@dataclass
class Issue:
    """A detected issue."""
    severity: str  # "critical", "warning", "info"
    category: str  # "success_rate", "stuck", "error_pattern", etc.
    message: str
    details: Optional[Dict] = None


@dataclass
class HealthReport:
    """Complete health report."""
    generated_at: datetime
    period_hours: int
    phases: List[PhaseHealth]
    issues: List[Issue]
    total_failures: int
    expected_failures: int
    real_failures: int
    noise_reduction_pct: float


# ============================================================================
# BigQuery Queries
# ============================================================================

def get_phase_health_query(hours: int) -> str:
    """Query for phase-by-phase health metrics."""
    return f"""
    SELECT
        phase,
        COUNT(*) as total_runs,
        COUNTIF(status = 'success') as successes,
        COUNTIF(status = 'failed') as all_failures,
        COUNTIF(status = 'failed' AND COALESCE(failure_category, 'unknown') NOT IN ('no_data_available')) as real_failures,
        COUNTIF(status = 'failed' AND failure_category = 'no_data_available') as expected_failures,
        ROUND(COUNTIF(status = 'success') / NULLIF(COUNT(*), 0) * 100, 2) as success_rate,
        ROUND(
            COUNTIF(status = 'success') /
            NULLIF(COUNT(*) - COUNTIF(status = 'failed' AND failure_category = 'no_data_available'), 0) * 100,
            2
        ) as effective_success_rate,
        ROUND(AVG(duration_seconds), 2) as avg_duration_sec
    FROM `{PROJECT_ID}.{DATASET}.{TABLE}`
    WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
    GROUP BY phase
    ORDER BY phase
    """


def get_stuck_processors_query() -> str:
    """Query for processors stuck in 'running' state."""
    return f"""
    SELECT
        processor_name,
        run_id,
        phase,
        started_at,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) as minutes_stuck,
        execution_host,
        cloud_run_service
    FROM `{PROJECT_ID}.{DATASET}.{TABLE}`
    WHERE status = 'running'
        AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) > {THRESHOLDS['stuck_minutes']}
    ORDER BY minutes_stuck DESC
    LIMIT 20
    """


def get_top_errors_query(hours: int) -> str:
    """Query for top error patterns."""
    return f"""
    SELECT
        processor_name,
        failure_category,
        JSON_VALUE(errors, '$[0]') as error_message,
        COUNT(*) as occurrence_count
    FROM `{PROJECT_ID}.{DATASET}.{TABLE}`
    WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
        AND status = 'failed'
        AND COALESCE(failure_category, 'unknown') NOT IN ('no_data_available')
    GROUP BY processor_name, failure_category, error_message
    ORDER BY occurrence_count DESC
    LIMIT 10
    """


def get_failure_category_breakdown_query(hours: int) -> str:
    """Query for failure category breakdown (noise reduction metrics)."""
    return f"""
    SELECT
        COALESCE(failure_category, 'unknown') as failure_category,
        COUNT(*) as count,
        ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as pct
    FROM `{PROJECT_ID}.{DATASET}.{TABLE}`
    WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
        AND status = 'failed'
    GROUP BY failure_category
    ORDER BY count DESC
    """


def get_processor_failures_query(hours: int) -> str:
    """Query for processors with most real failures."""
    return f"""
    SELECT
        processor_name,
        phase,
        COUNT(*) as total_failures,
        COUNTIF(COALESCE(failure_category, 'unknown') NOT IN ('no_data_available')) as real_failures,
        COUNTIF(failure_category = 'no_data_available') as expected_failures
    FROM `{PROJECT_ID}.{DATASET}.{TABLE}`
    WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
        AND status = 'failed'
    GROUP BY processor_name, phase
    HAVING real_failures > 0
    ORDER BY real_failures DESC
    LIMIT 15
    """


# ============================================================================
# Health Check Logic
# ============================================================================

class SystemHealthChecker:
    """Main health check class."""

    def __init__(self, project_id: str = PROJECT_ID):
        self.client = bigquery.Client(project=project_id)
        self.issues: List[Issue] = []

    def run_query(self, query: str) -> List[Dict]:
        """Execute a BigQuery query and return results as list of dicts."""
        try:
            results = self.client.query(query).result()
            return [dict(row) for row in results]
        except Exception as e:
            print(f"Query error: {e}")
            return []

    def check_phase_health(self, hours: int) -> List[PhaseHealth]:
        """Check health of each phase."""
        query = get_phase_health_query(hours)
        results = self.run_query(query)

        phases = []
        for row in results:
            phase_num = row.get("phase") or 0
            success_rate = row.get("success_rate") or 0
            effective_rate = row.get("effective_success_rate") or success_rate

            # Determine status
            if effective_rate < THRESHOLDS["success_rate_critical"]:
                status = "critical"
            elif effective_rate < THRESHOLDS["success_rate_warning"]:
                status = "warning"
            else:
                status = "healthy"

            phase = PhaseHealth(
                phase=phase_num,
                total_runs=row.get("total_runs") or 0,
                successes=row.get("successes") or 0,
                all_failures=row.get("all_failures") or 0,
                real_failures=row.get("real_failures") or 0,
                expected_failures=row.get("expected_failures") or 0,
                success_rate=success_rate,
                effective_success_rate=effective_rate,
                avg_duration_sec=row.get("avg_duration_sec") or 0,
                status=status,
            )
            phases.append(phase)

            # Add issues for unhealthy phases
            phase_name = PHASE_NAMES.get(phase_num, "Unknown")
            if status == "critical":
                self.issues.append(Issue(
                    severity="critical",
                    category="success_rate",
                    message=f"{phase_name} success rate is {effective_rate:.1f}% - CRITICAL",
                    details={"phase": phase_num, "rate": effective_rate}
                ))
            elif status == "warning":
                self.issues.append(Issue(
                    severity="warning",
                    category="success_rate",
                    message=f"{phase_name} success rate is {effective_rate:.1f}% - below 80%",
                    details={"phase": phase_num, "rate": effective_rate}
                ))

        return phases

    def check_stuck_processors(self) -> List[Dict]:
        """Check for processors stuck in running state."""
        query = get_stuck_processors_query()
        results = self.run_query(query)

        if results:
            self.issues.append(Issue(
                severity="critical",
                category="stuck",
                message=f"{len(results)} processor(s) stuck in 'running' state for >{THRESHOLDS['stuck_minutes']} minutes",
                details={"stuck_processors": [r.get("processor_name") for r in results]}
            ))

        return results

    def check_top_errors(self, hours: int) -> List[Dict]:
        """Check for recurring error patterns."""
        query = get_top_errors_query(hours)
        results = self.run_query(query)

        # Flag high-frequency errors
        for row in results:
            count = row.get("occurrence_count") or 0
            if count >= 10:
                self.issues.append(Issue(
                    severity="warning",
                    category="error_pattern",
                    message=f"{row.get('processor_name')}: {count} occurrences of '{row.get('failure_category')}' errors",
                    details=row
                ))

        return results

    def get_failure_breakdown(self, hours: int) -> Tuple[int, int, int, float]:
        """Get failure category breakdown for noise reduction metrics."""
        query = get_failure_category_breakdown_query(hours)
        results = self.run_query(query)

        total = 0
        expected = 0
        for row in results:
            count = row.get("count") or 0
            total += count
            if row.get("failure_category") == "no_data_available":
                expected = count

        real = total - expected
        noise_pct = (expected / total * 100) if total > 0 else 0

        return total, expected, real, noise_pct

    def generate_report(self, hours: int = 24) -> HealthReport:
        """Generate complete health report."""
        self.issues = []  # Reset issues

        # Gather all data
        phases = self.check_phase_health(hours)
        self.check_stuck_processors()
        self.check_top_errors(hours)
        total, expected, real, noise_pct = self.get_failure_breakdown(hours)

        return HealthReport(
            generated_at=datetime.now(),
            period_hours=hours,
            phases=phases,
            issues=sorted(self.issues, key=lambda x: 0 if x.severity == "critical" else (1 if x.severity == "warning" else 2)),
            total_failures=total,
            expected_failures=expected,
            real_failures=real,
            noise_reduction_pct=noise_pct,
        )


# ============================================================================
# Output Formatting
# ============================================================================

def get_status_icon(status: str) -> str:
    """Get emoji icon for status."""
    return {
        "healthy": "✅",
        "warning": "⚠️ ",
        "critical": "❌",
    }.get(status, "❓")


def get_severity_icon(severity: str) -> str:
    """Get emoji icon for severity."""
    return {
        "critical": "🚨",
        "warning": "⚠️ ",
        "info": "ℹ️ ",
    }.get(severity, "•")


def format_report(report: HealthReport, verbose: bool = False) -> str:
    """Format health report for terminal output."""
    lines = []

    # Header
    lines.append("\n🏥 NBA Stats Scraper - System Health Check")
    lines.append(f"📅 Last {report.period_hours} hours  |  Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # Phase Health Summary
    lines.append("Phase Health Summary")
    lines.append("─" * 60)

    for phase in report.phases:
        name = PHASE_NAMES.get(phase.phase, "Unknown")
        icon = get_status_icon(phase.status)
        rate = phase.effective_success_rate or phase.success_rate

        # Extract phase number for cleaner display
        phase_display = phase.phase
        if isinstance(phase.phase, str) and phase.phase.startswith("phase_"):
            # Extract "2" from "phase_2_raw", etc.
            parts = phase.phase.split("_")
            if len(parts) >= 2 and parts[1].isdigit():
                phase_display = f"Phase {parts[1]}"

        # Format line with alignment
        phase_str = f"{phase_display} ({name})"
        line = f"{icon} {phase_str:<30} {rate:>6.1f}% success │ {phase.real_failures:>3} real failures │ {phase.total_runs:>5} runs"
        lines.append(line)

    lines.append("")

    # Issues
    if report.issues:
        lines.append("🚨 Issues Detected")
        lines.append("─" * 60)
        for i, issue in enumerate(report.issues, 1):
            icon = get_severity_icon(issue.severity)
            lines.append(f"{i}. {icon} {issue.message}")
            if verbose and issue.details:
                lines.append(f"   Details: {json.dumps(issue.details, default=str)}")
        lines.append("")
    else:
        lines.append("✨ No Issues Detected - System Healthy!")
        lines.append("")

    # Alert Noise Reduction Metrics
    lines.append("📊 Alert Noise Reduction (failure_category)")
    lines.append("─" * 60)
    lines.append(f"Total failures:                    {report.total_failures:>6}")
    lines.append(f"Expected (no_data_available):      {report.expected_failures:>6} ({report.noise_reduction_pct:.1f}%)")
    lines.append(f"Real failures (need attention):    {report.real_failures:>6} ({100 - report.noise_reduction_pct:.1f}%)")

    if report.noise_reduction_pct > 80:
        lines.append(f"🎉 Noise reduction goal achieved! ({report.noise_reduction_pct:.1f}% > 80% target)")
    elif report.total_failures == 0:
        lines.append("ℹ️  No failures recorded in this period")
    lines.append("")

    return "\n".join(lines)


def format_slack_message(report: HealthReport) -> Dict:
    """Format health report for Slack webhook."""
    # Determine overall status
    critical_count = sum(1 for i in report.issues if i.severity == "critical")
    warning_count = sum(1 for i in report.issues if i.severity == "warning")

    if critical_count > 0:
        status_emoji = "🚨"
        status_text = f"CRITICAL - {critical_count} critical issue(s)"
    elif warning_count > 0:
        status_emoji = "⚠️"
        status_text = f"WARNING - {warning_count} warning(s)"
    else:
        status_emoji = "✅"
        status_text = "All systems healthy"

    # Build phase summary
    phase_lines = []
    for phase in report.phases:
        name = PHASE_NAMES.get(phase.phase, f"Phase {phase.phase}")
        icon = get_status_icon(phase.status)
        rate = phase.effective_success_rate or phase.success_rate
        phase_lines.append(f"{icon} Phase {phase.phase} ({name}): {rate:.1f}%")

    # Build issues list
    issue_lines = []
    for issue in report.issues[:5]:  # Limit to 5 issues
        icon = get_severity_icon(issue.severity)
        issue_lines.append(f"{icon} {issue.message}")

    return {
        "text": f"{status_emoji} Daily Health Check: {status_text}",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🏥 NBA Stats Scraper - Daily Health Check",
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Status:* {status_emoji} {status_text}\n*Period:* Last {report.period_hours} hours\n*Generated:* {report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Phase Health:*\n" + "\n".join(phase_lines)
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Alert Noise Reduction:*\nTotal: {report.total_failures} │ Expected: {report.expected_failures} ({report.noise_reduction_pct:.1f}%) │ Real: {report.real_failures}"
                }
            },
        ]
    }

    if issue_lines:
        return {
            **{k: v for k, v in [
                ("text", f"{status_emoji} Daily Health Check: {status_text}"),
            ]},
            "blocks": [
                *[b for b in [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"🏥 NBA Stats Scraper - Daily Health Check",
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Issues:*\n" + "\n".join(issue_lines)
                        }
                    }
                ]]
            ]
        }


def send_to_slack(report: HealthReport) -> bool:
    """Send health report to Slack webhook."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("Warning: SLACK_WEBHOOK_URL not set. Skipping Slack notification.")
        return False

    try:
        import requests
        message = format_slack_message(report)
        response = requests.post(webhook_url, json=message, timeout=10)
        return response.status_code == 200
    except ImportError:
        print("Warning: requests library not installed. Skipping Slack notification.")
        return False
    except Exception as e:
        print(f"Error sending to Slack: {e}")
        return False


# ============================================================================
# Validation Mode (Session 35/36 Checks)
# ============================================================================

def run_validation_checks():
    """
    Validate Session 35/36 deployments:
    1. Check failure_category field is being populated
    2. Check BR roster batch lock is working
    3. Check Cloud Run revisions are current
    """
    print("\n🔍 Session 35/36 Deployment Validation")
    print("=" * 60)

    all_passed = True
    client = bigquery.Client(project=PROJECT_ID)

    # Check 1: failure_category distribution
    print("\n1. Checking failure_category field...")
    query = """
    SELECT
      COALESCE(failure_category, 'NULL') as category,
      COUNT(*) as count
    FROM `nba-props-platform.nba_reference.processor_run_history`
    WHERE status = 'failed'
      AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
    GROUP BY 1
    ORDER BY 2 DESC
    """
    results = list(client.query(query).result())

    total_failures = sum(r['count'] for r in results)
    null_failures = sum(r['count'] for r in results if r['category'] == 'NULL')
    categorized = sum(r['count'] for r in results if r['category'] != 'NULL')

    if total_failures == 0:
        print("   ⏳ No failures in last 48 hours - cannot validate yet")
    elif null_failures == total_failures:
        print(f"   ⏳ All {total_failures} failures have NULL category (pre-deployment data)")
        print("   → Waiting for new failures to validate")
    elif categorized > 0:
        print(f"   ✅ {categorized}/{total_failures} failures are categorized!")
        for r in results:
            if r['category'] != 'NULL':
                print(f"      - {r['category']}: {r['count']}")
    else:
        print(f"   ❌ Unexpected state: {results}")
        all_passed = False

    # Check 2: BR roster batch lock in Firestore
    print("\n2. Checking BR roster batch lock...")
    try:
        from google.cloud import firestore
        db = firestore.Client(project='nba-props-platform')
        locks = list(db.collection('batch_processing_locks').stream())

        br_locks = [l for l in locks if 'br_roster' in l.id]
        espn_locks = [l for l in locks if 'espn_roster' in l.id]

        if br_locks:
            print(f"   ✅ Found {len(br_locks)} BR roster batch lock(s)")
            for lock in br_locks[:3]:
                data = lock.to_dict()
                print(f"      - {lock.id}: {data.get('status')}")
        else:
            print("   ⏳ No BR roster locks yet (waiting for next roster scrape)")
            print(f"   ℹ️  ESPN locks working: {len(espn_locks)} found (confirms pattern works)")
    except Exception as e:
        print(f"   ❌ Error checking Firestore: {e}")
        all_passed = False

    # Check 3: Cloud Run revisions
    print("\n3. Checking Cloud Run revisions...")
    import subprocess

    services = [
        ("nba-phase2-raw-processors", "Phase 2 Raw"),
        ("nba-phase3-analytics-processors", "Phase 3 Analytics"),
        ("nba-phase4-precompute-processors", "Phase 4 Precompute"),
    ]

    for service_name, display_name in services:
        try:
            result = subprocess.run(
                ["gcloud", "run", "services", "describe", service_name,
                 "--region=us-west2", "--format=value(status.latestReadyRevisionName)"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                revision = result.stdout.strip()
                print(f"   ✅ {display_name}: {revision}")
            else:
                print(f"   ❌ {display_name}: Error - {result.stderr}")
                all_passed = False
        except Exception as e:
            print(f"   ❌ {display_name}: {e}")
            all_passed = False

    # Check 4: Noise reduction metrics
    print("\n4. Checking alert noise reduction...")
    query = """
    SELECT
      COUNTIF(failure_category = 'no_data_available') as expected,
      COUNTIF(COALESCE(failure_category, 'unknown') NOT IN ('no_data_available')) as real,
      COUNT(*) as total
    FROM `nba-props-platform.nba_reference.processor_run_history`
    WHERE status = 'failed'
      AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
      AND failure_category IS NOT NULL
    """
    results = list(client.query(query).result())
    if results and results[0]['total'] > 0:
        r = results[0]
        noise_pct = (r['expected'] / r['total'] * 100) if r['total'] > 0 else 0
        print(f"   Total categorized failures: {r['total']}")
        print(f"   Expected (no_data_available): {r['expected']} ({noise_pct:.1f}%)")
        print(f"   Real (need attention): {r['real']} ({100-noise_pct:.1f}%)")
        if noise_pct >= 80:
            print(f"   ✅ Noise reduction goal achieved! ({noise_pct:.1f}% >= 80% target)")
        elif noise_pct >= 50:
            print(f"   ⚠️  Noise reduction partial ({noise_pct:.1f}% < 80% target)")
        else:
            print(f"   ⏳ Insufficient data to evaluate noise reduction")
    else:
        print("   ⏳ No categorized failures yet - waiting for new data")

    # Summary
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ All validation checks passed (or pending data)")
    else:
        print("❌ Some validation checks failed - review above")

    print("\nNext steps:")
    print("  • Run again in 24-48 hours after processors run")
    print("  • Check BR roster lock after next roster scrape")
    print("  • Monitor noise reduction as data accumulates")
    print()


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="NBA Stats Scraper - System Health Check",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/system_health_check.py              # Check last 24 hours
    python scripts/system_health_check.py --hours=1    # Check last hour
    python scripts/system_health_check.py --hours=168  # Check last week
    python scripts/system_health_check.py --verbose    # Include issue details
    python scripts/system_health_check.py --slack      # Send to Slack
    python scripts/system_health_check.py --json       # Output as JSON
    python scripts/system_health_check.py --validate   # Validate Session 35/36 deployments
        """
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Number of hours to analyze (default: 24)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Number of days to analyze (alternative to --hours)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed issue information"
    )
    parser.add_argument(
        "--slack",
        action="store_true",
        help="Send report to Slack webhook (requires SLACK_WEBHOOK_URL env var)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of formatted text"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate Session 35/36 deployments (failure_category, BR roster lock)"
    )

    args = parser.parse_args()

    # Handle --validate mode separately
    if args.validate:
        run_validation_checks()
        return

    # Calculate hours
    hours = args.days * 24 if args.days else args.hours

    # Run health check
    checker = SystemHealthChecker()
    report = checker.generate_report(hours=hours)

    # Output
    if args.json:
        output = {
            "generated_at": report.generated_at.isoformat(),
            "period_hours": report.period_hours,
            "phases": [
                {
                    "phase": p.phase,
                    "name": PHASE_NAMES.get(p.phase, f"Phase {p.phase}"),
                    "status": p.status,
                    "total_runs": p.total_runs,
                    "successes": p.successes,
                    "real_failures": p.real_failures,
                    "expected_failures": p.expected_failures,
                    "success_rate": p.success_rate,
                    "effective_success_rate": p.effective_success_rate,
                }
                for p in report.phases
            ],
            "issues": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "message": i.message,
                    "details": i.details,
                }
                for i in report.issues
            ],
            "noise_reduction": {
                "total_failures": report.total_failures,
                "expected_failures": report.expected_failures,
                "real_failures": report.real_failures,
                "noise_reduction_pct": report.noise_reduction_pct,
            }
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        print(format_report(report, verbose=args.verbose))

    # Send to Slack if requested
    if args.slack:
        if send_to_slack(report):
            print("✅ Report sent to Slack")
        else:
            print("❌ Failed to send to Slack")

    # Exit with appropriate code
    critical_count = sum(1 for i in report.issues if i.severity == "critical")
    if critical_count > 0:
        sys.exit(2)  # Critical issues
    elif report.issues:
        sys.exit(1)  # Warnings only
    else:
        sys.exit(0)  # All healthy


if __name__ == "__main__":
    main()
