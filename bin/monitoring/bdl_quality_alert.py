#!/usr/bin/env python3
"""
BDL Data Quality Alerting

Runs daily to monitor BDL data quality and sends Slack alerts when:
- BDL coverage drops below threshold
- Data accuracy is poor (high mismatch rate)
- BDL data quality improves (so we can consider re-enabling)

Can be run via:
- Cloud Scheduler (recommended)
- Cron job
- Manual invocation

Usage:
    python bin/monitoring/bdl_quality_alert.py [--date YYYY-MM-DD] [--dry-run]

Environment Variables:
    SLACK_WEBHOOK_URL: Webhook for #nba-alerts channel
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

import requests
from google.cloud import bigquery


# Thresholds for alerts
COVERAGE_THRESHOLD = 80  # Alert if BDL coverage < 80%
MISMATCH_THRESHOLD = 15  # Alert if >15% major mismatches
IMPROVEMENT_THRESHOLD = 5  # Alert (good news) if <5% mismatches


def get_bdl_quality_stats(game_date: str) -> dict:
    """Get BDL quality stats for a specific date."""

    client = bigquery.Client()

    query = f"""
    WITH gamebook AS (
        SELECT
            player_lookup,
            SAFE_CAST(REGEXP_EXTRACT(minutes, r'^([0-9]+)') AS INT64) as minutes_int,
            points
        FROM nba_raw.nbac_gamebook_player_stats
        WHERE game_date = '{game_date}'
          AND player_status = 'active'
          AND SAFE_CAST(REGEXP_EXTRACT(minutes, r'^([0-9]+)') AS INT64) > 0
    ),
    bdl AS (
        SELECT
            player_lookup,
            SAFE_CAST(minutes AS INT64) as minutes_int,
            points
        FROM nba_raw.bdl_player_boxscores
        WHERE game_date = '{game_date}'
    ),
    comparison AS (
        SELECT
            g.player_lookup,
            g.minutes_int as gamebook_min,
            g.points as gamebook_pts,
            b.minutes_int as bdl_min,
            b.points as bdl_pts,
            ABS(COALESCE(g.minutes_int, 0) - COALESCE(b.minutes_int, 0)) as minutes_diff
        FROM gamebook g
        LEFT JOIN bdl b ON g.player_lookup = b.player_lookup
    )
    SELECT
        COUNT(*) as total_players,
        COUNTIF(bdl_min IS NOT NULL) as bdl_coverage,
        COUNTIF(minutes_diff <= 2) as minutes_close_match,
        COUNTIF(minutes_diff > 5) as minutes_major_mismatch,
        AVG(minutes_diff) as avg_minutes_diff,
        MAX(minutes_diff) as max_minutes_diff
    FROM comparison
    """

    result = client.query(query).result()
    row = list(result)[0]

    if row.total_players == 0:
        return None  # No games on this date

    return {
        'date': game_date,
        'total_players': row.total_players,
        'bdl_coverage': row.bdl_coverage,
        'bdl_coverage_pct': round(100 * row.bdl_coverage / row.total_players, 1),
        'minutes_close_match': row.minutes_close_match,
        'minutes_major_mismatch': row.minutes_major_mismatch,
        'mismatch_pct': round(100 * row.minutes_major_mismatch / row.total_players, 1),
        'avg_minutes_diff': round(row.avg_minutes_diff or 0, 1),
        'max_minutes_diff': row.max_minutes_diff or 0,
    }


def send_slack_alert(webhook_url: str, blocks: list, color: str = "#FF0000"):
    """Send alert to Slack."""

    payload = {
        "attachments": [{
            "color": color,
            "blocks": blocks
        }]
    }

    response = requests.post(webhook_url, json=payload, timeout=10)
    response.raise_for_status()


def build_poor_quality_alert(stats: dict) -> tuple:
    """Build Slack blocks for poor quality alert."""

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":warning: BDL Data Quality Alert"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Date:* {stats['date']}\n*Status:* BDL data quality is poor - keeping disabled"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Coverage:*\n{stats['bdl_coverage']}/{stats['total_players']} ({stats['bdl_coverage_pct']}%)"},
                {"type": "mrkdwn", "text": f"*Major Mismatches:*\n{stats['minutes_major_mismatch']} ({stats['mismatch_pct']}%)"},
                {"type": "mrkdwn", "text": f"*Avg Diff:*\n{stats['avg_minutes_diff']} min"},
                {"type": "mrkdwn", "text": f"*Max Diff:*\n{stats['max_minutes_diff']} min"}
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":x: BDL API continues to return incorrect data. NBA.com gamebook remains primary source."
                }
            ]
        }
    ]

    return blocks, "#FF9900"  # Orange for warning


def build_improvement_alert(stats: dict) -> tuple:
    """Build Slack blocks for quality improvement alert."""

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":white_check_mark: BDL Data Quality Improved!"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Date:* {stats['date']}\n*Status:* BDL data quality has improved - consider re-enabling"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Coverage:*\n{stats['bdl_coverage']}/{stats['total_players']} ({stats['bdl_coverage_pct']}%)"},
                {"type": "mrkdwn", "text": f"*Major Mismatches:*\n{stats['minutes_major_mismatch']} ({stats['mismatch_pct']}%)"},
                {"type": "mrkdwn", "text": f"*Avg Diff:*\n{stats['avg_minutes_diff']} min"},
                {"type": "mrkdwn", "text": f"*Max Diff:*\n{stats['max_minutes_diff']} min"}
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":bulb: To re-enable BDL: Set `USE_BDL_DATA = True` in PlayerGameSummaryProcessor"
                }
            ]
        }
    ]

    return blocks, "#36A64F"  # Green for good news


def main():
    parser = argparse.ArgumentParser(description='BDL Data Quality Alerting')
    parser.add_argument('--date', type=str, help='Date to check (default: yesterday)')
    parser.add_argument('--dry-run', action='store_true', help='Print alert but do not send')
    args = parser.parse_args()

    # Default to yesterday (most recent complete data)
    check_date = args.date or (date.today() - timedelta(days=1)).isoformat()

    # Get webhook URL
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if not webhook_url and not args.dry_run:
        print("Warning: SLACK_WEBHOOK_URL not set, using dry-run mode")
        args.dry_run = True

    # Get stats
    print(f"Checking BDL data quality for {check_date}...")
    stats = get_bdl_quality_stats(check_date)

    if stats is None:
        print(f"No games on {check_date}, skipping")
        return

    print(f"Results: {stats['bdl_coverage_pct']}% coverage, {stats['mismatch_pct']}% mismatches")

    # Determine if we need to alert
    blocks = None
    color = None

    if stats['mismatch_pct'] < IMPROVEMENT_THRESHOLD and stats['bdl_coverage_pct'] > COVERAGE_THRESHOLD:
        # Good news - quality improved!
        print("BDL data quality has improved!")
        blocks, color = build_improvement_alert(stats)
    elif stats['mismatch_pct'] > MISMATCH_THRESHOLD or stats['bdl_coverage_pct'] < COVERAGE_THRESHOLD:
        # Poor quality - send warning
        print("BDL data quality is still poor")
        blocks, color = build_poor_quality_alert(stats)
    else:
        # Mediocre - no alert needed
        print("BDL data quality is mediocre - no alert needed")
        return

    if blocks:
        if args.dry_run:
            print("\n[DRY RUN] Would send alert:")
            print(json.dumps(blocks, indent=2))
        else:
            print("Sending Slack alert...")
            send_slack_alert(webhook_url, blocks, color)
            print("Alert sent!")


if __name__ == '__main__':
    main()
