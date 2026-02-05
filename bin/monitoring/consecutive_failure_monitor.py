#!/usr/bin/env python3
"""
Consecutive Failure Monitor

Detects scrapers or processors with multiple consecutive failures.
This addresses the Dec 27 - Jan 21 incident where 148 consecutive
scraper failures went undetected.

Usage:
    python bin/monitoring/consecutive_failure_monitor.py
    python bin/monitoring/consecutive_failure_monitor.py --threshold 5 --alert

Session: 125 (2026-02-04)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.cloud import bigquery

# Thresholds
DEFAULT_FAILURE_THRESHOLD = 5  # Alert after 5 consecutive failures
CRITICAL_THRESHOLD = 10  # Critical after 10 consecutive failures


def get_bq_client():
    """Get BigQuery client."""
    return bigquery.Client(project='nba-props-platform')


def check_scraper_consecutive_failures(threshold: int = DEFAULT_FAILURE_THRESHOLD) -> dict:
    """
    Check for scrapers with consecutive failures.

    Uses processor_run_history or workflow_executions to detect patterns.
    """
    client = get_bq_client()

    # Query for recent scraper/processor runs with failure detection
    query = """
    WITH recent_runs AS (
        SELECT
            processor_name,
            data_date,
            status,
            started_at,
            error_message,
            LAG(status) OVER (PARTITION BY processor_name ORDER BY started_at) as prev_status,
            LAG(status, 2) OVER (PARTITION BY processor_name ORDER BY started_at) as prev_status_2,
            LAG(status, 3) OVER (PARTITION BY processor_name ORDER BY started_at) as prev_status_3,
            LAG(status, 4) OVER (PARTITION BY processor_name ORDER BY started_at) as prev_status_4,
            ROW_NUMBER() OVER (PARTITION BY processor_name ORDER BY started_at DESC) as run_order
        FROM nba_orchestration.processor_run_history
        WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    ),
    failure_counts AS (
        SELECT
            processor_name,
            COUNT(*) as total_runs,
            COUNTIF(status = 'failed' OR status = 'error') as failed_runs,
            MAX(CASE WHEN status = 'success' AND run_order <= 10 THEN started_at END) as last_success,
            MAX(CASE WHEN (status = 'failed' OR status = 'error') AND run_order <= 10 THEN error_message END) as last_error
        FROM recent_runs
        WHERE run_order <= 20  -- Look at last 20 runs
        GROUP BY processor_name
    ),
    consecutive_failures AS (
        SELECT
            processor_name,
            data_date,
            status,
            started_at,
            CASE
                WHEN status IN ('failed', 'error')
                    AND (prev_status IN ('failed', 'error') OR prev_status IS NULL)
                    AND (prev_status_2 IN ('failed', 'error') OR prev_status_2 IS NULL)
                    AND (prev_status_3 IN ('failed', 'error') OR prev_status_3 IS NULL)
                    AND (prev_status_4 IN ('failed', 'error') OR prev_status_4 IS NULL)
                THEN 5
                WHEN status IN ('failed', 'error')
                    AND (prev_status IN ('failed', 'error') OR prev_status IS NULL)
                    AND (prev_status_2 IN ('failed', 'error') OR prev_status_2 IS NULL)
                    AND (prev_status_3 IN ('failed', 'error') OR prev_status_3 IS NULL)
                THEN 4
                WHEN status IN ('failed', 'error')
                    AND (prev_status IN ('failed', 'error') OR prev_status IS NULL)
                    AND (prev_status_2 IN ('failed', 'error') OR prev_status_2 IS NULL)
                THEN 3
                WHEN status IN ('failed', 'error')
                    AND (prev_status IN ('failed', 'error') OR prev_status IS NULL)
                THEN 2
                WHEN status IN ('failed', 'error')
                THEN 1
                ELSE 0
            END as consecutive_failures
        FROM recent_runs
        WHERE run_order = 1  -- Most recent run only
    )
    SELECT
        cf.processor_name,
        cf.consecutive_failures,
        cf.status as current_status,
        cf.started_at as last_run,
        fc.total_runs,
        fc.failed_runs,
        fc.last_success,
        fc.last_error
    FROM consecutive_failures cf
    JOIN failure_counts fc ON cf.processor_name = fc.processor_name
    WHERE cf.consecutive_failures >= 2  -- At least 2 consecutive failures
    ORDER BY cf.consecutive_failures DESC
    """

    try:
        results = client.query(query).result()

        failing_processors = []
        critical_processors = []

        for row in results:
            processor_info = {
                'processor_name': row.processor_name,
                'consecutive_failures': row.consecutive_failures,
                'current_status': row.current_status,
                'last_run': row.last_run.isoformat() if row.last_run else None,
                'total_runs': row.total_runs,
                'failed_runs': row.failed_runs,
                'last_success': row.last_success.isoformat() if row.last_success else None,
                'last_error': row.last_error
            }

            if row.consecutive_failures >= CRITICAL_THRESHOLD:
                critical_processors.append(processor_info)
            elif row.consecutive_failures >= threshold:
                failing_processors.append(processor_info)

        # Determine status
        if critical_processors:
            status = 'CRITICAL'
            message = f'{len(critical_processors)} processors have {CRITICAL_THRESHOLD}+ consecutive failures'
        elif failing_processors:
            status = 'WARNING'
            message = f'{len(failing_processors)} processors have {threshold}+ consecutive failures'
        else:
            status = 'OK'
            message = f'No processors have {threshold}+ consecutive failures'

        return {
            'status': status,
            'message': message,
            'failing_processors': failing_processors,
            'critical_processors': critical_processors,
            'threshold': threshold,
            'checked_at': datetime.utcnow().isoformat()
        }

    except Exception as e:
        # Table may not exist or be empty
        return {
            'status': 'UNKNOWN',
            'message': f'Could not check processor history: {e}',
            'failing_processors': [],
            'critical_processors': [],
            'threshold': threshold,
            'checked_at': datetime.utcnow().isoformat()
        }


def check_data_freshness() -> dict:
    """
    Check if critical data sources have been updated recently.
    A stale data source indicates potential scraper issues.
    """
    client = get_bq_client()

    query = """
    WITH freshness AS (
        SELECT
            'bdl_player_boxscores' as source,
            MAX(game_date) as latest_date,
            DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_stale
        FROM nba_raw.bdl_player_boxscores

        UNION ALL

        SELECT
            'nbac_gamebook_player_boxscores',
            MAX(game_date),
            DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY)
        FROM nba_raw.nbac_gamebook_player_boxscores

        UNION ALL

        SELECT
            'player_game_summary',
            MAX(game_date),
            DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY)
        FROM nba_analytics.player_game_summary

        UNION ALL

        SELECT
            'player_daily_cache',
            MAX(cache_date),
            DATE_DIFF(CURRENT_DATE(), MAX(cache_date), DAY)
        FROM nba_precompute.player_daily_cache

        UNION ALL

        SELECT
            'player_prop_predictions',
            MAX(game_date),
            DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY)
        FROM nba_predictions.player_prop_predictions
    )
    SELECT
        source,
        latest_date,
        days_stale,
        CASE
            WHEN days_stale > 3 THEN 'CRITICAL'
            WHEN days_stale > 1 THEN 'WARNING'
            ELSE 'OK'
        END as status
    FROM freshness
    ORDER BY days_stale DESC
    """

    results = client.query(query).result()

    stale_sources = []
    critical_sources = []

    for row in results:
        source_info = {
            'source': row.source,
            'latest_date': str(row.latest_date),
            'days_stale': row.days_stale,
            'status': row.status
        }

        if row.status == 'CRITICAL':
            critical_sources.append(source_info)
        elif row.status == 'WARNING':
            stale_sources.append(source_info)

    if critical_sources:
        status = 'CRITICAL'
        message = f'{len(critical_sources)} data sources are critically stale (>3 days)'
    elif stale_sources:
        status = 'WARNING'
        message = f'{len(stale_sources)} data sources are stale (>1 day)'
    else:
        status = 'OK'
        message = 'All data sources are fresh'

    return {
        'status': status,
        'message': message,
        'stale_sources': stale_sources,
        'critical_sources': critical_sources
    }


def send_slack_alert(result: dict, freshness_result: dict):
    """Send alert to Slack."""
    try:
        import requests

        webhook_url = os.environ.get('SLACK_WEBHOOK_URL_ERROR')
        if not webhook_url:
            print("Warning: SLACK_WEBHOOK_URL_ERROR not set, skipping alert")
            return

        # Build message
        if result['status'] == 'CRITICAL' or freshness_result['status'] == 'CRITICAL':
            emoji = ":rotating_light:"
            color = "#FF0000"
        elif result['status'] == 'WARNING' or freshness_result['status'] == 'WARNING':
            emoji = ":warning:"
            color = "#FFA500"
        else:
            return  # No alert needed

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} Consecutive Failure Alert"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Processor Status:* {result['status']}\n*Message:* {result['message']}"
                }
            }
        ]

        # Add critical processors
        if result['critical_processors']:
            proc_text = "\n".join([
                f"• {p['processor_name']}: {p['consecutive_failures']} failures (last error: {p['last_error'][:50] if p['last_error'] else 'N/A'}...)"
                for p in result['critical_processors'][:3]
            ])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Critical Processors ({CRITICAL_THRESHOLD}+ failures):*\n{proc_text}"
                }
            })

        # Add warning processors
        if result['failing_processors']:
            proc_text = "\n".join([
                f"• {p['processor_name']}: {p['consecutive_failures']} failures"
                for p in result['failing_processors'][:3]
            ])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Warning Processors ({result['threshold']}+ failures):*\n{proc_text}"
                }
            })

        # Add freshness issues
        if freshness_result['critical_sources']:
            source_text = "\n".join([
                f"• {s['source']}: {s['days_stale']} days stale (latest: {s['latest_date']})"
                for s in freshness_result['critical_sources']
            ])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Stale Data Sources:*\n{source_text}"
                }
            })

        payload = {
            "blocks": blocks,
            "attachments": [{
                "color": color,
                "text": "Run `python bin/monitoring/consecutive_failure_monitor.py` for details"
            }]
        }

        response = requests.post(webhook_url, json=payload)
        response.raise_for_status()
        print(f"Alert sent to Slack")

    except Exception as e:
        print(f"Failed to send Slack alert: {e}")


def store_result(result: dict, freshness_result: dict):
    """Store validation result in BigQuery."""
    client = get_bq_client()

    row = {
        'run_timestamp': datetime.utcnow().isoformat(),
        'check_type': 'consecutive_failures',
        'status': result['status'],
        'message': result['message'],
        'threshold': result['threshold'],
        'failing_count': len(result['failing_processors']),
        'critical_count': len(result['critical_processors']),
        'stale_sources': len(freshness_result.get('critical_sources', [])),
        'details': json.dumps({
            'failing_processors': result['failing_processors'],
            'critical_processors': result['critical_processors'],
            'stale_sources': freshness_result.get('critical_sources', [])
        })
    }

    table_id = 'nba-props-platform.nba_orchestration.validation_runs'

    try:
        errors = client.insert_rows_json(table_id, [row])
        if errors:
            print(f"Warning: Failed to store result: {errors}")
        else:
            print(f"Result stored in {table_id}")
    except Exception as e:
        print(f"Note: Could not store result: {e}")


def main():
    parser = argparse.ArgumentParser(description='Check for consecutive processor failures')
    parser.add_argument('--threshold', type=int, default=DEFAULT_FAILURE_THRESHOLD,
                        help=f'Alert after N consecutive failures (default: {DEFAULT_FAILURE_THRESHOLD})')
    parser.add_argument('--alert', action='store_true', help='Send Slack alert if issues found')
    parser.add_argument('--store', action='store_true', help='Store result in BigQuery')
    parser.add_argument('--json', action='store_true', help='Output JSON format')
    args = parser.parse_args()

    print(f"Checking for processors with {args.threshold}+ consecutive failures...")
    print("=" * 60)

    # Check processor failures
    result = check_scraper_consecutive_failures(args.threshold)

    # Check data freshness
    freshness_result = check_data_freshness()

    if args.json:
        combined = {**result, 'freshness': freshness_result}
        print(json.dumps(combined, indent=2))
    else:
        # Print processor results
        print(f"\nProcessor Status: {result['status']}")
        print(f"Message: {result['message']}")

        if result['critical_processors']:
            print(f"\n🔴 CRITICAL ({len(result['critical_processors'])} processors):")
            for proc in result['critical_processors']:
                print(f"  - {proc['processor_name']}: {proc['consecutive_failures']} consecutive failures")
                if proc['last_success']:
                    print(f"    Last success: {proc['last_success']}")
                if proc['last_error']:
                    print(f"    Last error: {proc['last_error'][:100]}...")

        if result['failing_processors']:
            print(f"\n🟡 WARNING ({len(result['failing_processors'])} processors):")
            for proc in result['failing_processors']:
                print(f"  - {proc['processor_name']}: {proc['consecutive_failures']} consecutive failures")

        # Print freshness results
        print(f"\nData Freshness: {freshness_result['status']}")
        print(f"Message: {freshness_result['message']}")

        if freshness_result['critical_sources']:
            print(f"\n🔴 CRITICALLY STALE SOURCES:")
            for source in freshness_result['critical_sources']:
                print(f"  - {source['source']}: {source['days_stale']} days stale (latest: {source['latest_date']})")

        if freshness_result['stale_sources']:
            print(f"\n🟡 STALE SOURCES:")
            for source in freshness_result['stale_sources']:
                print(f"  - {source['source']}: {source['days_stale']} days stale")

    # Send alert if requested
    if args.alert and (result['status'] != 'OK' or freshness_result['status'] != 'OK'):
        send_slack_alert(result, freshness_result)

    # Store result if requested
    if args.store:
        store_result(result, freshness_result)

    # Exit code
    if result['status'] == 'CRITICAL' or freshness_result['status'] == 'CRITICAL':
        sys.exit(2)
    elif result['status'] == 'WARNING' or freshness_result['status'] == 'WARNING':
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
