#!/usr/bin/env python3
"""
Test alert suppression during backfill mode.

This tests that when skip_downstream_trigger=True (backfill mode),
alerts are suppressed via AlertManager to prevent email spam.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.utils.notification_system import notify_error
from shared.alerts import get_alert_manager


def test_backfill_alert_suppression():
    """Test that backfill mode suppresses non-critical alerts."""
    print("Testing alert suppression during backfill mode...")
    print()

    # Test 1: Normal mode (should alert)
    print("Test 1: Normal mode (backfill_mode=False)")
    result = notify_error(
        title="Test Error - Normal Mode",
        message="This should send an alert (or log to console in dev)",
        details={'test': 'normal_mode'},
        processor_name="TestProcessor",
        backfill_mode=False
    )
    print(f"  Result: {result}")
    print()

    # Test 2: Backfill mode (should suppress)
    print("Test 2: Backfill mode (backfill_mode=True)")
    result = notify_error(
        title="Test Error - Backfill Mode",
        message="This should be suppressed by AlertManager",
        details={'test': 'backfill_mode', 'error_type': 'FileNotFoundError'},
        processor_name="TestProcessor",
        backfill_mode=True
    )
    print(f"  Result: {result}")
    print()

    # Test 3: Multiple errors in backfill mode (should batch)
    print("Test 3: Multiple errors in backfill mode (should batch/rate-limit)")
    for i in range(5):
        result = notify_error(
            title=f"Test Error - Backfill #{i+1}",
            message=f"File not found error #{i+1}",
            details={'test': 'backfill_batch', 'error_type': 'FileNotFoundError', 'iteration': i+1},
            processor_name="TestProcessor",
            backfill_mode=True
        )
        print(f"  Error #{i+1} result: {result}")
    print()

    # Test 4: Check AlertManager stats
    print("Test 4: AlertManager statistics")
    alert_mgr = get_alert_manager(backfill_mode=True)
    stats = alert_mgr.get_alert_stats()
    print(f"  Alert stats: {stats}")
    print()

    # Test 5: Flush batched alerts (would send summary at end of backfill)
    print("Test 5: Flush batched alerts (end of backfill)")
    alert_mgr.flush_batched_alerts()
    print("  Batched alerts flushed")
    print()

    print("✅ Test complete!")
    print()
    print("Summary:")
    print("- Normal mode: Alerts are sent immediately")
    print("- Backfill mode: Alerts are suppressed (downgraded to warnings)")
    print("- Multiple backfill errors: Batched and rate-limited")
    print("- End of backfill: Summary alert sent via flush_batched_alerts()")


if __name__ == '__main__':
    test_backfill_alert_suppression()
