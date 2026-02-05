#!/usr/bin/env python3
"""
Analyze Self-Healing Patterns (Session 135)

Query and analyze healing events to identify root causes and prevent recurrence.

Usage:
    # Last 24 hours summary
    python bin/monitoring/analyze_healing_patterns.py

    # Specific time range
    python bin/monitoring/analyze_healing_patterns.py --start "2026-02-05 00:00" --end "2026-02-05 23:59"

    # Specific healing type
    python bin/monitoring/analyze_healing_patterns.py --type batch_cleanup

    # Export to CSV
    python bin/monitoring/analyze_healing_patterns.py --export healing_report.csv

Created: 2026-02-05
"""

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

# Add shared to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from google.cloud import bigquery
from shared.utils.healing_tracker import HealingTracker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "nba-props-platform")


def get_healing_events(
    client: bigquery.Client,
    start_time: datetime,
    end_time: datetime,
    healing_type: str = None
) -> List[Dict[str, Any]]:
    """Get healing events from BigQuery."""
    query = f"""
    SELECT
        healing_id,
        timestamp,
        healing_type,
        trigger_reason,
        action_taken,
        before_state,
        after_state,
        success,
        metadata
    FROM `{PROJECT_ID}.nba_orchestration.healing_events`
    WHERE timestamp >= @start_time
      AND timestamp <= @end_time
    """

    if healing_type:
        query += "  AND healing_type = @healing_type\n"

    query += "ORDER BY timestamp DESC"

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_time", "TIMESTAMP", start_time),
            bigquery.ScalarQueryParameter("end_time", "TIMESTAMP", end_time),
        ]
    )

    if healing_type:
        job_config.query_parameters.append(
            bigquery.ScalarQueryParameter("healing_type", "STRING", healing_type)
        )

    result = list(client.query(query, job_config=job_config).result())

    events = []
    for row in result:
        events.append({
            'healing_id': row.healing_id,
            'timestamp': row.timestamp,
            'healing_type': row.healing_type,
            'trigger_reason': row.trigger_reason,
            'action_taken': row.action_taken,
            'before_state': row.before_state,
            'after_state': row.after_state,
            'success': row.success,
            'metadata': row.metadata
        })

    return events


def analyze_patterns(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze healing events for patterns."""
    if not events:
        return {
            'total_events': 0,
            'by_type': {},
            'success_rate': 0,
            'common_triggers': []
        }

    # Group by type
    by_type = {}
    all_triggers = []

    for event in events:
        h_type = event['healing_type']
        if h_type not in by_type:
            by_type[h_type] = {
                'count': 0,
                'successful': 0,
                'failed': 0,
                'triggers': []
            }

        by_type[h_type]['count'] += 1
        if event['success']:
            by_type[h_type]['successful'] += 1
        else:
            by_type[h_type]['failed'] += 1

        by_type[h_type]['triggers'].append(event['trigger_reason'])
        all_triggers.append(event['trigger_reason'])

    # Calculate success rate per type
    for h_type, data in by_type.items():
        data['success_rate'] = data['successful'] / data['count'] if data['count'] > 0 else 0

    # Find most common triggers
    trigger_counts = {}
    for trigger in all_triggers:
        trigger_counts[trigger] = trigger_counts.get(trigger, 0) + 1

    common_triggers = sorted(
        trigger_counts.items(),
        key=lambda x: x[1],
        reverse=True
    )[:5]

    total = len(events)
    successful = sum(1 for e in events if e['success'])

    return {
        'total_events': total,
        'successful': successful,
        'failed': total - successful,
        'success_rate': successful / total if total > 0 else 0,
        'by_type': by_type,
        'common_triggers': common_triggers
    }


def print_summary(analysis: Dict[str, Any], start_time: datetime, end_time: datetime) -> None:
    """Print human-readable summary."""
    print("\n" + "="*80)
    print("HEALING PATTERN ANALYSIS")
    print("="*80)
    print(f"\nTime Range: {start_time.strftime('%Y-%m-%d %H:%M')} - {end_time.strftime('%Y-%m-%d %H:%M')}")
    print(f"\nTotal Healing Events: {analysis['total_events']}")

    if analysis['total_events'] == 0:
        print("\n✅ No healing events - system healthy!")
        return

    print(f"Overall Success Rate: {analysis['success_rate']:.1%}")
    print(f"  ✅ Successful: {analysis['successful']}")
    print(f"  ❌ Failed: {analysis['failed']}")

    print("\n" + "-"*80)
    print("BREAKDOWN BY HEALING TYPE")
    print("-"*80)

    for h_type, data in sorted(analysis['by_type'].items(), key=lambda x: x[1]['count'], reverse=True):
        print(f"\n{h_type.upper()}:")
        print(f"  Total: {data['count']}")
        print(f"  Success Rate: {data['success_rate']:.1%} ({data['successful']}/{data['count']})")
        print(f"  Failed: {data['failed']}")

    print("\n" + "-"*80)
    print("TOP 5 ROOT CAUSES")
    print("-"*80)

    for trigger, count in analysis['common_triggers']:
        print(f"\n{count}x: {trigger}")

    print("\n" + "-"*80)
    print("RECOMMENDATIONS")
    print("-"*80)

    # Generate recommendations based on patterns
    if analysis['success_rate'] < 0.8:
        print("\n⚠️  Low success rate (<80%) - investigate failed healing attempts")

    high_freq_types = [
        h_type for h_type, data in analysis['by_type'].items()
        if data['count'] >= 10
    ]
    if high_freq_types:
        print(f"\n⚠️  High-frequency healing types: {', '.join(high_freq_types)}")
        print("   Consider implementing preventive fixes for root causes")

    print("\n" + "="*80 + "\n")


def export_to_csv(events: List[Dict[str, Any]], filename: str) -> None:
    """Export events to CSV."""
    if not events:
        logger.info("No events to export")
        return

    with open(filename, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'healing_id', 'timestamp', 'healing_type', 'trigger_reason',
            'action_taken', 'success', 'metadata'
        ])
        writer.writeheader()

        for event in events:
            writer.writerow({
                'healing_id': event['healing_id'],
                'timestamp': event['timestamp'].isoformat() if event['timestamp'] else '',
                'healing_type': event['healing_type'],
                'trigger_reason': event['trigger_reason'],
                'action_taken': event['action_taken'],
                'success': event['success'],
                'metadata': event['metadata']
            })

    logger.info(f"Exported {len(events)} events to {filename}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Analyze self-healing patterns')
    parser.add_argument(
        '--start',
        help='Start time (YYYY-MM-DD HH:MM)',
        default=(datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
    )
    parser.add_argument(
        '--end',
        help='End time (YYYY-MM-DD HH:MM)',
        default=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
    )
    parser.add_argument(
        '--type',
        help='Filter by healing type (e.g., batch_cleanup)',
        default=None
    )
    parser.add_argument(
        '--export',
        help='Export to CSV file',
        default=None
    )

    args = parser.parse_args()

    # Parse times
    start_time = datetime.strptime(args.start, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
    end_time = datetime.strptime(args.end, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)

    client = bigquery.Client(project=PROJECT_ID)

    # Get events
    logger.info(f"Querying healing events from {start_time} to {end_time}")
    events = get_healing_events(client, start_time, end_time, args.type)

    # Analyze
    analysis = analyze_patterns(events)

    # Print summary
    print_summary(analysis, start_time, end_time)

    # Export if requested
    if args.export:
        export_to_csv(events, args.export)

    return 0


if __name__ == "__main__":
    sys.exit(main())
