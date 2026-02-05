#!/usr/bin/env python3
"""
Historical Completeness Monitor

Checks the last N days for data gaps that may have gone undetected.
This addresses the Dec 27 - Jan 21 incident where 26 days of missing data
went unnoticed because validation only checked current day.

Usage:
    python bin/monitoring/historical_completeness_monitor.py
    python bin/monitoring/historical_completeness_monitor.py --days 14 --alert

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
COMPLETENESS_THRESHOLD = 0.80  # 80% minimum
CRITICAL_THRESHOLD = 0.50  # Below 50% is critical
PLAYERS_PER_GAME = 25  # Expected players per team per game


def get_bq_client():
    """Get BigQuery client."""
    return bigquery.Client(project='nba-props-platform')


def check_historical_completeness(days_lookback: int = 14) -> dict:
    """
    Check completeness for the last N days.

    Returns:
        dict with:
            - gaps: list of dates with < threshold completeness
            - critical_gaps: list of dates with < critical threshold
            - summary: overall assessment
    """
    client = get_bq_client()

    query = f"""
    WITH schedule AS (
        SELECT
            game_date,
            COUNT(*) as scheduled_games
        FROM nba_reference.nba_schedule
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days_lookback} DAY)
            AND game_date < CURRENT_DATE()
            AND game_status = 3  -- Final games only
        GROUP BY game_date
    ),
    analytics AS (
        SELECT
            game_date,
            COUNT(*) as actual_records,
            COUNT(DISTINCT game_id) as actual_games,
            COUNTIF(minutes_played IS NOT NULL AND minutes_played > 0) as has_minutes,
            COUNTIF(usage_rate IS NOT NULL AND usage_rate > 0) as has_usage_rate
        FROM nba_analytics.player_game_summary
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days_lookback} DAY)
            AND game_date < CURRENT_DATE()
        GROUP BY game_date
    )
    SELECT
        s.game_date,
        s.scheduled_games,
        s.scheduled_games * {PLAYERS_PER_GAME * 2} as expected_records,
        COALESCE(a.actual_records, 0) as actual_records,
        COALESCE(a.actual_games, 0) as actual_games,
        COALESCE(a.has_minutes, 0) as has_minutes,
        COALESCE(a.has_usage_rate, 0) as has_usage_rate,
        ROUND(SAFE_DIVIDE(COALESCE(a.actual_records, 0), s.scheduled_games * {PLAYERS_PER_GAME * 2}) * 100, 1) as completeness_pct,
        ROUND(SAFE_DIVIDE(COALESCE(a.has_minutes, 0), COALESCE(a.actual_records, 1)) * 100, 1) as minutes_coverage_pct,
        ROUND(SAFE_DIVIDE(COALESCE(a.has_usage_rate, 0), COALESCE(a.actual_records, 1)) * 100, 1) as usage_rate_coverage_pct
    FROM schedule s
    LEFT JOIN analytics a ON s.game_date = a.game_date
    ORDER BY s.game_date DESC
    """

    results = client.query(query).result()

    gaps = []
    critical_gaps = []
    all_dates = []

    for row in results:
        date_info = {
            'game_date': str(row.game_date),
            'scheduled_games': row.scheduled_games,
            'expected_records': row.expected_records,
            'actual_records': row.actual_records,
            'completeness_pct': row.completeness_pct or 0,
            'minutes_coverage_pct': row.minutes_coverage_pct or 0,
            'usage_rate_coverage_pct': row.usage_rate_coverage_pct or 0
        }
        all_dates.append(date_info)

        completeness = (row.completeness_pct or 0) / 100

        if completeness < CRITICAL_THRESHOLD:
            critical_gaps.append(date_info)
        elif completeness < COMPLETENESS_THRESHOLD:
            gaps.append(date_info)

    # Determine overall status
    if critical_gaps:
        status = 'CRITICAL'
        message = f'{len(critical_gaps)} dates have <{CRITICAL_THRESHOLD*100}% completeness'
    elif gaps:
        status = 'WARNING'
        message = f'{len(gaps)} dates have <{COMPLETENESS_THRESHOLD*100}% completeness'
    else:
        status = 'OK'
        message = f'All {len(all_dates)} dates have >{COMPLETENESS_THRESHOLD*100}% completeness'

    return {
        'status': status,
        'message': message,
        'gaps': gaps,
        'critical_gaps': critical_gaps,
        'all_dates': all_dates,
        'lookback_days': days_lookback,
        'checked_at': datetime.utcnow().isoformat()
    }


def check_scraper_completeness(days_lookback: int = 14) -> dict:
    """
    Check scraper data completeness for raw tables.
    """
    client = get_bq_client()

    query = f"""
    WITH schedule AS (
        SELECT
            game_date,
            COUNT(*) as scheduled_games
        FROM nba_reference.nba_schedule
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days_lookback} DAY)
            AND game_date < CURRENT_DATE()
            AND game_status = 3
        GROUP BY game_date
    ),
    bdl_data AS (
        SELECT game_date, COUNT(DISTINCT game_id) as games
        FROM nba_raw.bdl_player_boxscores
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days_lookback} DAY)
        GROUP BY game_date
    ),
    nbac_data AS (
        SELECT game_date, COUNT(DISTINCT game_id) as games
        FROM nba_raw.nbac_gamebook_player_boxscores
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days_lookback} DAY)
        GROUP BY game_date
    )
    SELECT
        s.game_date,
        s.scheduled_games,
        COALESCE(b.games, 0) as bdl_games,
        COALESCE(n.games, 0) as nbac_games,
        ROUND(SAFE_DIVIDE(COALESCE(b.games, 0), s.scheduled_games) * 100, 1) as bdl_coverage_pct,
        ROUND(SAFE_DIVIDE(COALESCE(n.games, 0), s.scheduled_games) * 100, 1) as nbac_coverage_pct
    FROM schedule s
    LEFT JOIN bdl_data b ON s.game_date = b.game_date
    LEFT JOIN nbac_data n ON s.game_date = n.game_date
    ORDER BY s.game_date DESC
    """

    results = client.query(query).result()

    scraper_gaps = []
    for row in results:
        bdl_coverage = (row.bdl_coverage_pct or 0) / 100
        nbac_coverage = (row.nbac_coverage_pct or 0) / 100

        if bdl_coverage < COMPLETENESS_THRESHOLD or nbac_coverage < COMPLETENESS_THRESHOLD:
            scraper_gaps.append({
                'game_date': str(row.game_date),
                'scheduled_games': row.scheduled_games,
                'bdl_games': row.bdl_games,
                'nbac_games': row.nbac_games,
                'bdl_coverage_pct': row.bdl_coverage_pct or 0,
                'nbac_coverage_pct': row.nbac_coverage_pct or 0
            })

    return {
        'status': 'WARNING' if scraper_gaps else 'OK',
        'gaps': scraper_gaps,
        'gap_count': len(scraper_gaps)
    }


def send_slack_alert(result: dict, scraper_result: dict):
    """Send alert to Slack if gaps detected."""
    try:
        import requests

        webhook_url = os.environ.get('SLACK_WEBHOOK_URL_ERROR')
        if not webhook_url:
            print("Warning: SLACK_WEBHOOK_URL_ERROR not set, skipping alert")
            return

        # Build message
        if result['status'] == 'CRITICAL':
            emoji = ":rotating_light:"
            color = "#FF0000"
        elif result['status'] == 'WARNING':
            emoji = ":warning:"
            color = "#FFA500"
        else:
            return  # No alert needed

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} Historical Completeness Alert"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Status:* {result['status']}\n*Message:* {result['message']}\n*Lookback:* {result['lookback_days']} days"
                }
            }
        ]

        # Add critical gaps
        if result['critical_gaps']:
            gap_text = "\n".join([
                f"• {g['game_date']}: {g['completeness_pct']}% ({g['actual_records']}/{g['expected_records']} records)"
                for g in result['critical_gaps'][:5]
            ])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Critical Gaps (<{CRITICAL_THRESHOLD*100}%):*\n{gap_text}"
                }
            })

        # Add warning gaps
        if result['gaps']:
            gap_text = "\n".join([
                f"• {g['game_date']}: {g['completeness_pct']}%"
                for g in result['gaps'][:5]
            ])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Warning Gaps (<{COMPLETENESS_THRESHOLD*100}%):*\n{gap_text}"
                }
            })

        # Add scraper gaps
        if scraper_result['gaps']:
            gap_text = "\n".join([
                f"• {g['game_date']}: BDL {g['bdl_coverage_pct']}%, NBAC {g['nbac_coverage_pct']}%"
                for g in scraper_result['gaps'][:3]
            ])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Scraper Gaps:*\n{gap_text}"
                }
            })

        payload = {
            "blocks": blocks,
            "attachments": [{
                "color": color,
                "text": f"Run `python bin/monitoring/historical_completeness_monitor.py --days {result['lookback_days']}` for details"
            }]
        }

        response = requests.post(webhook_url, json=payload)
        response.raise_for_status()
        print(f"Alert sent to Slack")

    except Exception as e:
        print(f"Failed to send Slack alert: {e}")


def store_result(result: dict, scraper_result: dict):
    """Store validation result in BigQuery for trend analysis."""
    client = get_bq_client()

    row = {
        'run_timestamp': datetime.utcnow().isoformat(),
        'check_type': 'historical_completeness',
        'status': result['status'],
        'message': result['message'],
        'lookback_days': result['lookback_days'],
        'gap_count': len(result['gaps']),
        'critical_gap_count': len(result['critical_gaps']),
        'scraper_gap_count': scraper_result['gap_count'],
        'details': json.dumps({
            'gaps': result['gaps'],
            'critical_gaps': result['critical_gaps'],
            'scraper_gaps': scraper_result['gaps']
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
        # Table may not exist yet
        print(f"Note: Could not store result (table may not exist): {e}")


def main():
    parser = argparse.ArgumentParser(description='Check historical data completeness')
    parser.add_argument('--days', type=int, default=14, help='Days to look back (default: 14)')
    parser.add_argument('--alert', action='store_true', help='Send Slack alert if gaps found')
    parser.add_argument('--store', action='store_true', help='Store result in BigQuery')
    parser.add_argument('--json', action='store_true', help='Output JSON format')
    args = parser.parse_args()

    print(f"Checking historical completeness for last {args.days} days...")
    print("=" * 60)

    # Check analytics completeness
    result = check_historical_completeness(args.days)

    # Check scraper completeness
    scraper_result = check_scraper_completeness(args.days)

    if args.json:
        combined = {**result, 'scraper_gaps': scraper_result}
        print(json.dumps(combined, indent=2))
    else:
        # Print summary
        print(f"\nStatus: {result['status']}")
        print(f"Message: {result['message']}")
        print(f"\nAnalytics Completeness:")
        print("-" * 60)

        for date_info in result['all_dates']:
            status_emoji = "✅" if date_info['completeness_pct'] >= COMPLETENESS_THRESHOLD * 100 else "❌"
            print(f"  {date_info['game_date']}: {status_emoji} {date_info['completeness_pct']}% "
                  f"({date_info['actual_records']}/{date_info['expected_records']} records)")

        if result['critical_gaps']:
            print(f"\n🔴 CRITICAL GAPS ({len(result['critical_gaps'])} dates):")
            for gap in result['critical_gaps']:
                print(f"  - {gap['game_date']}: {gap['completeness_pct']}%")

        if result['gaps']:
            print(f"\n🟡 WARNING GAPS ({len(result['gaps'])} dates):")
            for gap in result['gaps']:
                print(f"  - {gap['game_date']}: {gap['completeness_pct']}%")

        if scraper_result['gaps']:
            print(f"\n📡 SCRAPER GAPS ({scraper_result['gap_count']} dates):")
            for gap in scraper_result['gaps']:
                print(f"  - {gap['game_date']}: BDL {gap['bdl_coverage_pct']}%, NBAC {gap['nbac_coverage_pct']}%")

    # Send alert if requested and gaps found
    if args.alert and (result['gaps'] or result['critical_gaps']):
        send_slack_alert(result, scraper_result)

    # Store result if requested
    if args.store:
        store_result(result, scraper_result)

    # Exit with appropriate code
    if result['status'] == 'CRITICAL':
        sys.exit(2)
    elif result['status'] == 'WARNING':
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
