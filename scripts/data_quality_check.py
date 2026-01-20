#!/usr/bin/env python3
"""
Data Quality Check - Monitor for data integrity issues

Created: 2026-01-14, Session 47
Purpose: Detect data quality issues like fake lines, missing data, etc.

Usage:
    python scripts/data_quality_check.py                    # Check today's data
    python scripts/data_quality_check.py --days=7           # Check last 7 days
    python scripts/data_quality_check.py --slack            # Send alert to Slack

Can be run as a Cloud Scheduler job:
    gcloud scheduler jobs create http data-quality-check \
        --schedule="0 8 * * *" \
        --uri="https://YOUR-SERVICE/data-quality" \
        --location=us-west2
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from google.cloud import bigquery
    from shared.utils.slack_retry import send_slack_webhook_with_retry
except ImportError:
    print("Error: google-cloud-bigquery not installed")
    sys.exit(1)

# ============================================================================
# Configuration
# ============================================================================

PROJECT_ID = "nba-props-platform"

# Thresholds for alerts
THRESHOLDS = {
    "fake_line_pct": 1.0,      # Alert if >1% fake lines (line=20)
    "null_line_pct": 50.0,     # Alert if >50% null lines (warning only)
    "min_predictions": 50,      # Minimum predictions expected per game day
}


def check_data_quality(days: int = 1) -> dict:
    """Check data quality for the specified number of days."""
    client = bigquery.Client(project=PROJECT_ID)

    query = f"""
    SELECT
        game_date,
        COUNT(*) as total_predictions,
        COUNTIF(current_points_line = 20) as fake_line_count,
        COUNTIF(current_points_line IS NULL) as null_line_count,
        COUNT(DISTINCT system_id) as systems_count,
        COUNT(DISTINCT player_lookup) as players_count
    FROM `nba_predictions.player_prop_predictions`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
      AND game_date < CURRENT_DATE()  -- Exclude today (future games)
    GROUP BY game_date
    ORDER BY game_date DESC
    """

    results = list(client.query(query).result())

    issues = []
    warnings = []

    for row in results:
        game_date = row.game_date.strftime("%Y-%m-%d")
        total = row.total_predictions
        fake_count = row.fake_line_count
        null_count = row.null_line_count

        if total == 0:
            continue

        fake_pct = 100.0 * fake_count / total
        null_pct = 100.0 * null_count / total

        # Check for fake lines (CRITICAL)
        if fake_pct > THRESHOLDS["fake_line_pct"]:
            issues.append({
                "type": "FAKE_LINES",
                "severity": "CRITICAL",
                "date": game_date,
                "message": f"{game_date}: {fake_count}/{total} ({fake_pct:.1f}%) predictions have fake line_value=20"
            })

        # Check for high null rate (WARNING)
        if null_pct > THRESHOLDS["null_line_pct"]:
            warnings.append({
                "type": "HIGH_NULL_RATE",
                "severity": "WARNING",
                "date": game_date,
                "message": f"{game_date}: {null_count}/{total} ({null_pct:.1f}%) predictions have NULL lines"
            })

        # Check for low prediction count (WARNING)
        if total < THRESHOLDS["min_predictions"]:
            warnings.append({
                "type": "LOW_PREDICTIONS",
                "severity": "WARNING",
                "date": game_date,
                "message": f"{game_date}: Only {total} predictions (expected >= {THRESHOLDS['min_predictions']})"
            })

    return {
        "checked_at": datetime.utcnow().isoformat(),
        "days_checked": days,
        "dates_analyzed": len(results),
        "issues": issues,
        "warnings": warnings,
        "status": "CRITICAL" if issues else ("WARNING" if warnings else "OK")
    }


def send_slack_alert(result: dict, webhook_url: str = None):
    """Send alert to Slack if there are issues."""
    if not webhook_url:
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

    if not webhook_url:
        print("Warning: No Slack webhook URL configured")
        return

    if result["status"] == "OK":
        return  # Don't send for OK status

    import requests

    emoji = "🚨" if result["status"] == "CRITICAL" else "⚠️"
    color = "#FF0000" if result["status"] == "CRITICAL" else "#FFA500"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} NBA Data Quality Alert - {result['status']}"
            }
        }
    ]

    # Add issues
    for issue in result["issues"]:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{issue['type']}*: {issue['message']}"
            }
        })

    # Add warnings
    for warning in result["warnings"][:3]:  # Limit to 3 warnings
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{warning['type']}*: {warning['message']}"
            }
        })

    payload = {"blocks": blocks}

    try:
        success = send_slack_webhook_with_retry(webhook_url, payload, timeout=10)
        if success:
            print(f"Slack alert sent successfully")
        else:
            print(f"Failed to send Slack alert after retries")
    except Exception as e:
        print(f"Failed to send Slack alert: {e}")


def main():
    parser = argparse.ArgumentParser(description="Check NBA prediction data quality")
    parser.add_argument("--days", type=int, default=1, help="Number of days to check")
    parser.add_argument("--slack", action="store_true", help="Send Slack alert if issues found")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    result = check_data_quality(args.days)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"\n{'='*60}")
        print(f"NBA DATA QUALITY CHECK")
        print(f"{'='*60}")
        print(f"Status: {result['status']}")
        print(f"Days checked: {result['days_checked']}")
        print(f"Dates analyzed: {result['dates_analyzed']}")

        if result["issues"]:
            print(f"\n🚨 CRITICAL ISSUES ({len(result['issues'])}):")
            for issue in result["issues"]:
                print(f"  • {issue['message']}")

        if result["warnings"]:
            print(f"\n⚠️  WARNINGS ({len(result['warnings'])}):")
            for warning in result["warnings"]:
                print(f"  • {warning['message']}")

        if not result["issues"] and not result["warnings"]:
            print("\n✅ No data quality issues detected")

        print()

    if args.slack and result["status"] != "OK":
        send_slack_alert(result)

    # Exit with error code if critical issues
    sys.exit(1 if result["issues"] else 0)


if __name__ == "__main__":
    main()
