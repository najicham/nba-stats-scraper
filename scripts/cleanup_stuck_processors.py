#!/usr/bin/env python3
"""
Cleanup Stuck Processors - Automated cleanup of processors stuck in 'running' state

Created: 2026-01-14, Session 38
Purpose: Automatically clean up processors that get stuck due to auth failures, timeouts, etc.

Usage:
    python scripts/cleanup_stuck_processors.py                    # Dry run (preview)
    python scripts/cleanup_stuck_processors.py --execute          # Actually clean up
    python scripts/cleanup_stuck_processors.py --threshold=60     # Custom threshold (minutes)
    python scripts/cleanup_stuck_processors.py --execute --slack  # Clean up and notify Slack

Can be run as a Cloud Scheduler job every 30 minutes:
    gcloud scheduler jobs create http cleanup-stuck-processors \
        --schedule="*/30 * * * *" \
        --uri="https://YOUR-SERVICE/cleanup-stuck" \
        --location=us-west2

Or locally via cron:
    */30 * * * * /usr/bin/python3 /path/to/cleanup_stuck_processors.py --execute
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from google.cloud import bigquery
    from shared.utils.slack_retry import send_slack_webhook_with_retry
except ImportError:
    print("Error: google-cloud-bigquery not installed. Run: pip install google-cloud-bigquery")
    sys.exit(1)


# ============================================================================
# Configuration
# ============================================================================

PROJECT_ID = "nba-props-platform"
DATASET = "nba_reference"
TABLE = "processor_run_history"

# Default threshold: processors running longer than this are considered stuck
DEFAULT_THRESHOLD_MINUTES = 30

# Maximum processors to clean up in one run (safety limit)
MAX_CLEANUP_BATCH = 500


# ============================================================================
# Main Logic
# ============================================================================

def get_stuck_processors(client: bigquery.Client, threshold_minutes: int) -> List[Dict]:
    """Query for processors stuck in 'running' state."""
    query = f"""
    SELECT
        processor_name,
        run_id,
        phase,
        data_date,
        started_at,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) as minutes_stuck,
        cloud_run_service,
        cloud_run_revision
    FROM `{PROJECT_ID}.{DATASET}.{TABLE}`
    WHERE status = 'running'
        AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) > {threshold_minutes}
    ORDER BY minutes_stuck DESC
    LIMIT {MAX_CLEANUP_BATCH}
    """

    try:
        results = client.query(query).result()
        return [dict(row) for row in results]
    except Exception as e:
        print(f"Error querying stuck processors: {e}")
        return []


def cleanup_stuck_processors(
    client: bigquery.Client,
    threshold_minutes: int,
    failure_category: str = "timeout"
) -> int:
    """Mark stuck processors as failed.

    Returns the number of processors cleaned up.
    """
    # Build JSON error message - using simple format to avoid escaping issues
    error_json = json.dumps({
        "cleanup_reason": "stale_running_cleanup",
        "message": f"marked as failed after being stuck in running state for >{threshold_minutes} minutes"
    })

    query = f"""
    UPDATE `{PROJECT_ID}.{DATASET}.{TABLE}`
    SET
        status = 'failed',
        failure_category = '{failure_category}',
        processed_at = CURRENT_TIMESTAMP(),
        errors = JSON '{error_json}'
    WHERE status = 'running'
        AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) > {threshold_minutes}
    """

    try:
        result = client.query(query).result()
        # Get the number of affected rows
        return result.num_dml_affected_rows or 0
    except Exception as e:
        print(f"Error cleaning up stuck processors: {e}")
        return 0


def send_slack_notification(
    stuck_count: int,
    cleaned_count: int,
    threshold_minutes: int,
    processors: List[Dict]
) -> bool:
    """Send Slack notification about cleanup."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("Warning: SLACK_WEBHOOK_URL not set. Skipping Slack notification.")
        return False

    try:
        import requests

        # Build processor summary
        processor_summary = {}
        for p in processors[:20]:  # Limit to 20 for message brevity
            name = p.get("processor_name", "Unknown")
            processor_summary[name] = processor_summary.get(name, 0) + 1

        summary_lines = [f"• {name}: {count}" for name, count in sorted(processor_summary.items(), key=lambda x: -x[1])[:10]]

        message = {
            "text": f"🧹 Stuck Processor Cleanup: {cleaned_count} processors cleaned",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🧹 Stuck Processor Cleanup"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Found:* {stuck_count} stuck processors (>{threshold_minutes} min)\n*Cleaned:* {cleaned_count} processors marked as failed\n*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Affected processors:*\n" + "\n".join(summary_lines) if summary_lines else "*No processors affected*"
                    }
                }
            ]
        }

        success = send_slack_webhook_with_retry(webhook_url, message, timeout=10)
        return success
    except ImportError:
        print("Warning: requests library not installed. Skipping Slack notification.")
        return False
    except Exception as e:
        print(f"Error sending Slack notification: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Clean up processors stuck in 'running' state",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/cleanup_stuck_processors.py                    # Dry run (preview)
    python scripts/cleanup_stuck_processors.py --execute          # Actually clean up
    python scripts/cleanup_stuck_processors.py --threshold=60     # Custom threshold (60 min)
    python scripts/cleanup_stuck_processors.py --execute --slack  # Clean up and notify
        """
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the cleanup (default is dry run)"
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD_MINUTES,
        help=f"Minutes before a processor is considered stuck (default: {DEFAULT_THRESHOLD_MINUTES})"
    )
    parser.add_argument(
        "--failure-category",
        type=str,
        default="timeout",
        help="Failure category to assign (default: timeout)"
    )
    parser.add_argument(
        "--slack",
        action="store_true",
        help="Send Slack notification after cleanup"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON"
    )

    args = parser.parse_args()

    # Initialize BigQuery client
    client = bigquery.Client(project=PROJECT_ID)

    # Get stuck processors
    stuck_processors = get_stuck_processors(client, args.threshold)

    if args.json and not args.execute:
        # JSON output for dry run
        output = {
            "mode": "dry_run",
            "threshold_minutes": args.threshold,
            "stuck_count": len(stuck_processors),
            "processors": [
                {
                    "processor_name": p.get("processor_name"),
                    "phase": p.get("phase"),
                    "data_date": str(p.get("data_date")),
                    "minutes_stuck": p.get("minutes_stuck"),
                    "run_id": p.get("run_id"),
                }
                for p in stuck_processors
            ]
        }
        print(json.dumps(output, indent=2, default=str))
        return

    if not stuck_processors:
        if args.json:
            print(json.dumps({"mode": "execute" if args.execute else "dry_run", "stuck_count": 0, "cleaned_count": 0}))
        else:
            print(f"✅ No processors stuck for >{args.threshold} minutes. Nothing to clean up.")
        return

    # Print summary
    if not args.json:
        print(f"\n🔍 Found {len(stuck_processors)} processor(s) stuck for >{args.threshold} minutes:\n")

        # Group by processor name
        by_processor = {}
        for p in stuck_processors:
            name = p.get("processor_name", "Unknown")
            by_processor[name] = by_processor.get(name, 0) + 1

        for name, count in sorted(by_processor.items(), key=lambda x: -x[1]):
            print(f"  • {name}: {count}")

        print(f"\n  Total: {len(stuck_processors)} stuck processors")

    if args.execute:
        # Actually clean up
        if not args.json:
            print(f"\n🧹 Cleaning up {len(stuck_processors)} stuck processors...")

        cleaned_count = cleanup_stuck_processors(
            client,
            args.threshold,
            args.failure_category
        )

        if args.json:
            output = {
                "mode": "execute",
                "threshold_minutes": args.threshold,
                "stuck_count": len(stuck_processors),
                "cleaned_count": cleaned_count,
                "failure_category": args.failure_category,
            }
            print(json.dumps(output, indent=2))
        else:
            print(f"✅ Cleaned up {cleaned_count} stuck processors (marked as '{args.failure_category}')")

        # Send Slack notification if requested
        if args.slack and cleaned_count > 0:
            if send_slack_notification(len(stuck_processors), cleaned_count, args.threshold, stuck_processors):
                if not args.json:
                    print("📨 Slack notification sent")
            else:
                if not args.json:
                    print("⚠️  Failed to send Slack notification")
    else:
        # Dry run
        if not args.json:
            print(f"\n⚠️  DRY RUN - No changes made. Use --execute to actually clean up.")
            print(f"   Command: python scripts/cleanup_stuck_processors.py --execute --threshold={args.threshold}")


if __name__ == "__main__":
    main()
