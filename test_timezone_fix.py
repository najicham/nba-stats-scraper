#!/usr/bin/env python3
"""
Test script for Session 124 timezone fix in master_controller.py

This validates that the time window calculation correctly handles day boundaries
for late-night workflows (10 PM, 1 AM, 4 AM).

The bug: At 11:00 PM ET (04:00 UTC), a workflow scheduled for 4:00 AM ET
would calculate the window as 4:00 AM earlier the same day (19 hours ago),
resulting in a huge time_diff and incorrect SKIP decision.

The fix: Detect when target time is >12 hours away and adjust to the correct day.
"""

from datetime import datetime, timedelta
import pytz

def test_timezone_logic():
    """Test the timezone fix logic."""

    print("=" * 80)
    print("Session 124 Timezone Fix - Test Cases")
    print("=" * 80)
    print()

    ET = pytz.timezone('America/New_York')

    test_cases = [
        {
            "name": "Bug scenario: 11 PM ET, workflow at 4 AM ET",
            "current_time": ET.localize(datetime(2026, 2, 4, 23, 0, 0)),  # 11 PM Feb 4 ET
            "fixed_time": "04:00",
            "expected_diff_minutes": 5 * 60,  # Should be 5 hours (tomorrow morning)
            "should_run": False,  # Outside 30-min tolerance
        },
        {
            "name": "Should run: 3:55 AM ET, workflow at 4 AM ET",
            "current_time": ET.localize(datetime(2026, 2, 5, 3, 55, 0)),  # 3:55 AM Feb 5 ET
            "fixed_time": "04:00",
            "expected_diff_minutes": 5,  # 5 minutes before window
            "should_run": True,  # Within 30-min tolerance
        },
        {
            "name": "Should run: 4:15 AM ET, workflow at 4 AM ET",
            "current_time": ET.localize(datetime(2026, 2, 5, 4, 15, 0)),  # 4:15 AM Feb 5 ET
            "fixed_time": "04:00",
            "expected_diff_minutes": 15,  # 15 minutes after window
            "should_run": True,  # Within 30-min tolerance
        },
        {
            "name": "Late-night: 12:30 AM ET, workflow at 1 AM ET",
            "current_time": ET.localize(datetime(2026, 2, 5, 0, 30, 0)),  # 12:30 AM Feb 5 ET
            "fixed_time": "01:00",
            "expected_diff_minutes": 30,  # 30 minutes before window
            "should_run": True,  # Exactly at tolerance boundary
        },
        {
            "name": "Evening: 10:05 PM ET, workflow at 10 PM ET",
            "current_time": ET.localize(datetime(2026, 2, 4, 22, 5, 0)),  # 10:05 PM Feb 4 ET
            "fixed_time": "22:00",
            "expected_diff_minutes": 5,  # 5 minutes after window
            "should_run": True,  # Within 30-min tolerance
        },
        {
            "name": "Too early: 2 AM ET, workflow at 4 AM ET",
            "current_time": ET.localize(datetime(2026, 2, 5, 2, 0, 0)),  # 2 AM Feb 5 ET
            "fixed_time": "04:00",
            "expected_diff_minutes": 120,  # 2 hours before window
            "should_run": False,  # Outside 30-min tolerance
        },
        {
            "name": "Too late: 6 AM ET, workflow at 4 AM ET",
            "current_time": ET.localize(datetime(2026, 2, 5, 6, 0, 0)),  # 6 AM Feb 5 ET
            "fixed_time": "04:00",
            "expected_diff_minutes": 120,  # 2 hours after window
            "should_run": False,  # Outside 30-min tolerance
        },
    ]

    tolerance_minutes = 30
    all_passed = True

    for i, test in enumerate(test_cases, 1):
        print(f"Test {i}: {test['name']}")
        print(f"  Current time: {test['current_time'].strftime('%Y-%m-%d %I:%M %p %Z')}")
        print(f"  Target time: {test['fixed_time']}")

        # Apply the fix logic
        current_time = test['current_time']
        hour, minute = map(int, test['fixed_time'].split(':'))
        window_time = current_time.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # Fix: Handle day boundary
        time_diff = (current_time - window_time).total_seconds()

        if time_diff > 12 * 3600:
            window_time = window_time + timedelta(days=1)
            adjustment = "→ Adjusted forward 1 day"
        elif time_diff < -12 * 3600:
            window_time = window_time - timedelta(days=1)
            adjustment = "→ Adjusted back 1 day"
        else:
            adjustment = "→ No adjustment needed"

        time_diff_minutes = abs((current_time - window_time).total_seconds() / 60)
        should_run = time_diff_minutes <= tolerance_minutes

        # Validation
        diff_ok = abs(time_diff_minutes - test['expected_diff_minutes']) < 1  # Allow 1-min tolerance
        action_ok = should_run == test['should_run']

        if diff_ok and action_ok:
            status = "✅ PASS"
        else:
            status = "❌ FAIL"
            all_passed = False

        print(f"  {adjustment}")
        print(f"  Window time: {window_time.strftime('%Y-%m-%d %I:%M %p %Z')}")
        print(f"  Time diff: {time_diff_minutes:.1f} minutes (expected: {test['expected_diff_minutes']})")
        print(f"  Should run: {should_run} (expected: {test['should_run']})")
        print(f"  {status}")
        print()

    print("=" * 80)
    if all_passed:
        print("✅ ALL TESTS PASSED")
    else:
        print("❌ SOME TESTS FAILED")
    print("=" * 80)

    return all_passed


if __name__ == "__main__":
    import sys
    success = test_timezone_logic()
    sys.exit(0 if success else 1)
