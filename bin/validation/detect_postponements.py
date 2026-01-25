#!/usr/bin/env python3
"""
Detect Postponed Games

This script detects games that may have been postponed by checking for:
1. "Final" status with NULL scores (should never happen)
2. Same game_id appearing on multiple dates (rescheduled)
3. News articles mentioning postponement keywords
4. Final games without any boxscore data

Usage:
    python bin/validation/detect_postponements.py --date 2026-01-24
    python bin/validation/detect_postponements.py --days 3
    python bin/validation/detect_postponements.py --slack  # Send Slack alerts
    python bin/validation/detect_postponements.py --log    # Log to BigQuery
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Any

# Import from shared module
from shared.utils.postponement_detector import (
    PostponementDetector,
    get_affected_predictions
)

# Try to import Slack utilities
try:
    from shared.utils.slack_channels import send_to_slack
    SLACK_AVAILABLE = True
except ImportError:
    SLACK_AVAILABLE = False

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def send_slack_alert(anomalies: List[Dict[str, Any]]) -> bool:
    """
    Send Slack alert for CRITICAL and HIGH severity anomalies.

    Uses SLACK_WEBHOOK_URL_WARNING for alerts channel.

    Returns:
        True if alert sent successfully
    """
    if not SLACK_AVAILABLE:
        logger.warning("Slack utilities not available - skipping Slack alert")
        return False

    webhook_url = os.environ.get('SLACK_WEBHOOK_URL_WARNING')
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL_WARNING not set - skipping Slack alert")
        return False

    # Filter to CRITICAL and HIGH severity only
    urgent = [a for a in anomalies if a.get('severity') in ('CRITICAL', 'HIGH')]
    if not urgent:
        return False

    # Build message
    critical_count = sum(1 for a in urgent if a['severity'] == 'CRITICAL')

    header = "🚨 *Postponement Alert*" if critical_count else "⚠️ *Schedule Anomaly Detected*"

    lines = [header, ""]

    for anomaly in urgent:
        emoji = "🔴" if anomaly['severity'] == 'CRITICAL' else "🟡"
        game_info = anomaly.get('teams', 'Unknown')
        game_date = anomaly.get('game_date') or anomaly.get('original_date', 'Unknown')
        anomaly_type = anomaly['type'].replace('_', ' ').title()
        predictions = anomaly.get('predictions_affected', 0)

        lines.append(f"{emoji} *{anomaly_type}*")
        lines.append(f"   Game: {game_info}")
        lines.append(f"   Date: {game_date}")
        if predictions > 0:
            lines.append(f"   Predictions Affected: {predictions}")
        lines.append(f"   Action: {anomaly.get('recommended_action', 'Investigate')}")
        lines.append("")

    lines.append("_Run `detect_postponements.py` for full details_")

    message = "\n".join(lines)

    try:
        return send_to_slack(webhook_url, message, icon_emoji=":warning:")
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


def print_report(anomalies: List[Dict[str, Any]]):
    """Print a formatted report of detected anomalies."""
    if not anomalies:
        print("\n" + "=" * 60)
        print("NO POSTPONEMENT ANOMALIES DETECTED")
        print("=" * 60)
        return

    print("\n" + "=" * 60)
    print(f"POSTPONEMENT DETECTION REPORT")
    print(f"Found {len(anomalies)} anomalies")
    print("=" * 60)

    # Group by severity
    by_severity = {}
    for a in anomalies:
        sev = a.get('severity', 'UNKNOWN')
        if sev not in by_severity:
            by_severity[sev] = []
        by_severity[sev].append(a)

    for severity in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
        if severity not in by_severity:
            continue

        print(f"\n{severity} ({len(by_severity[severity])} issues)")
        print("-" * 40)

        for a in by_severity[severity]:
            print(f"\nType: {a['type']}")
            if 'teams' in a:
                print(f"  Game: {a['teams']}")
            if 'game_id' in a:
                print(f"  Game ID: {a['game_id']}")
            if 'game_date' in a:
                print(f"  Date: {a['game_date']}")
            if 'all_dates' in a:
                print(f"  All Dates: {', '.join(a['all_dates'])}")
            if 'predictions_affected' in a:
                print(f"  Predictions Affected: {a['predictions_affected']}")
            print(f"  Details: {a['details']}")
            print(f"  Action: {a['recommended_action']}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description='Detect postponed games')
    parser.add_argument('--date', type=str, help='Date to check (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, default=1, help='Number of days to check')
    parser.add_argument('--log', action='store_true', help='Log findings to BigQuery')
    parser.add_argument('--sport', type=str, default='NBA', help='Sport (NBA or MLB)')
    parser.add_argument('--slack', action='store_true', help='Send Slack alert for CRITICAL/HIGH findings')
    parser.add_argument('--no-slack', action='store_true', help='Disable Slack alerts (for testing)')

    args = parser.parse_args()

    # Determine date(s) to check
    if args.date:
        check_dates = [datetime.strptime(args.date, '%Y-%m-%d').date()]
    else:
        today = date.today()
        check_dates = [today - timedelta(days=i) for i in range(args.days)]

    detector = PostponementDetector(sport=args.sport)
    all_anomalies = []

    for check_date in check_dates:
        anomalies = detector.detect_all(check_date)
        all_anomalies.extend(anomalies)

        if args.log:
            for anomaly in anomalies:
                detector.log_to_bigquery(anomaly)

    print_report(all_anomalies)

    # Send Slack alert for CRITICAL/HIGH findings
    has_critical = any(a['severity'] == 'CRITICAL' for a in all_anomalies)
    has_high = any(a['severity'] == 'HIGH' for a in all_anomalies)

    if (has_critical or has_high) and args.slack and not args.no_slack:
        logger.info("Sending Slack alert for detected anomalies...")
        if send_slack_alert(all_anomalies):
            logger.info("Slack alert sent successfully")
        else:
            logger.warning("Failed to send Slack alert")

    # Return exit code based on severity
    if has_critical:
        sys.exit(2)
    elif has_high:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
