#!/usr/bin/env python3
"""
Test script for email alert type detection

Demonstrates how different error messages are automatically categorized
into appropriate alert types with corresponding emojis, colors, and headings.

Usage:
    python test_email_alert_types.py
"""

from shared.utils.alert_types import detect_alert_type, get_alert_config, format_alert_heading


def test_alert_detection():
    """Test alert type detection with various error messages."""

    test_cases = [
        {
            'name': 'Zero Rows Saved',
            'error': '⚠️ Zero Rows Saved: Expected 33 rows but saved 0',
            'details': {'expected_rows': 33, 'actual_rows': 0}
        },
        {
            'name': 'Database Serialization Conflict',
            'error': '400 Could not serialize access to table nba_raw.br_rosters_current due to concurrent update',
            'details': {'table': 'br_rosters_current', 'retry_count': 3}
        },
        {
            'name': 'Service Crash',
            'error': 'Service crashed due to memory exhaustion',
            'details': {'exit_code': 137}
        },
        {
            'name': 'Slow Processing',
            'error': 'Processing taking longer than expected - 45 minutes elapsed',
            'details': {'duration_minutes': 45, 'threshold': 30}
        },
        {
            'name': 'Data Quality Issue',
            'error': 'Data quality degradation detected - missing required fields',
            'details': {'missing_fields': ['player_id', 'team_abbr']}
        },
        {
            'name': 'Stale Data',
            'error': 'Data has not been updated in 3 days',
            'details': {'last_update': '2026-12-29', 'days_stale': 3}
        },
        {
            'name': 'Pipeline Stall',
            'error': 'Pipeline stalled - no progress in 2 hours',
            'details': {'last_progress': '2026-01-02 12:00:00'}
        },
        {
            'name': 'High Unresolved Count',
            'error': 'High unresolved player count detected: 75 players',
            'details': {'unresolved_count': 75, 'threshold': 50}
        },
        {
            'name': 'Generic Processing Error',
            'error': 'Failed to process data',
            'details': {'file': 'game_data_20260102.json'}
        },
        {
            'name': 'Data Validation Anomaly',
            'error': 'Validation found unexpected pattern in team abbreviations',
            'details': {'pattern': 'XYZ team codes'}
        }
    ]

    print("=" * 80)
    print("EMAIL ALERT TYPE DETECTION TEST")
    print("=" * 80)
    print()

    for test in test_cases:
        # Detect alert type
        alert_type = detect_alert_type(test['error'], test['details'])
        config = get_alert_config(alert_type)
        heading = format_alert_heading(alert_type)

        print(f"Test Case: {test['name']}")
        print(f"  Error Message: {test['error'][:70]}...")
        print(f"  Detected Type: {alert_type}")
        print(f"  Alert Heading: {heading}")
        print(f"  Severity: {config['severity']}")
        print(f"  Color: {config['color']}")
        print(f"  Action: {config['action'][:60]}...")
        print()

    print("=" * 80)
    print("✅ Alert type detection test completed!")
    print("=" * 80)


if __name__ == "__main__":
    test_alert_detection()
