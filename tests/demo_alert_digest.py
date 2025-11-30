#!/usr/bin/env python3
"""
Demo: Compare alert digest options

Run this to see the difference between:
1. Complete silence
2. Manual digest
3. Auto-digest context manager
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.alerts import get_alert_manager
from shared.utils.notification_system import notify_error


def simulate_backfill_errors(backfill_mode=True, num_errors=10):
    """Simulate errors during backfill."""
    for i in range(num_errors):
        notify_error(
            title=f"Backfill Error #{i+1}",
            message=f"File not found for date 2022-01-{i+1:02d}",
            details={
                'date': f'2022-01-{i+1:02d}',
                'error_type': 'FileNotFoundError',
                'processor': 'TestProcessor'
            },
            processor_name='TestProcessor',
            backfill_mode=backfill_mode
        )


def option1_complete_silence():
    """Option 1: No emails during or after backfill."""
    print("\n" + "="*60)
    print("OPTION 1: COMPLETE SILENCE")
    print("="*60)

    # Simulate backfill
    print("Running backfill with 10 errors...")
    simulate_backfill_errors(backfill_mode=True, num_errors=10)

    print("✅ Backfill complete")
    print("📧 Emails sent: 0")
    print("   - No spam during backfill ✅")
    print("   - No summary at end ❌")


def option2_manual_digest():
    """Option 2: Manual digest at end."""
    print("\n" + "="*60)
    print("OPTION 2: MANUAL DIGEST (RECOMMENDED)")
    print("="*60)

    # Get alert manager
    alert_mgr = get_alert_manager(backfill_mode=True, reset=True)

    # Simulate backfill
    print("Running backfill with 10 errors...")
    simulate_backfill_errors(backfill_mode=True, num_errors=10)

    print("✅ Backfill complete")

    # Check stats
    stats = alert_mgr.get_alert_stats()
    print(f"📊 Alert stats: {stats}")

    # Send digest
    print("\n📧 Sending digest email...")
    alert_mgr.flush_batched_alerts()

    print("✅ Digest sent!")
    print("   - No spam during backfill ✅")
    print("   - ONE summary email at end ✅")


def option3_auto_digest():
    """Option 3: Auto-digest with context manager."""
    print("\n" + "="*60)
    print("OPTION 3: AUTO-DIGEST CONTEXT MANAGER")
    print("="*60)

    print("Running backfill with 10 errors (using context manager)...")

    # Use context manager (auto-flush on exit)
    with get_alert_manager(backfill_mode=True, auto_flush_on_exit=True, reset=True):
        simulate_backfill_errors(backfill_mode=True, num_errors=10)
        print("✅ Backfill complete")
        # Digest automatically sent when exiting 'with' block

    print("📧 Digest automatically sent on exit!")
    print("   - No spam during backfill ✅")
    print("   - ONE summary email at end (automatic) ✅")


def main():
    """Run all three options for comparison."""
    print("\n" + "="*60)
    print("ALERT DIGEST OPTIONS DEMO")
    print("="*60)
    print("\nSimulating backfills with 10 errors each...")
    print("(In production, errors would be real FileNotFoundError, etc.)")

    # Option 1
    option1_complete_silence()

    # Option 2
    option2_manual_digest()

    # Option 3
    option3_auto_digest()

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print("\nOption 1 (Silence):")
    print("  - Simple, no code changes")
    print("  - No confirmation backfill finished")
    print("  - Best for: Test runs, watching logs live")

    print("\nOption 2 (Manual Digest): ⭐ RECOMMENDED")
    print("  - Two lines: get manager, flush at end")
    print("  - See error breakdown and patterns")
    print("  - Best for: Production backfills")

    print("\nOption 3 (Auto Digest):")
    print("  - Context manager (with statement)")
    print("  - Foolproof - can't forget to flush")
    print("  - Best for: Automated scripts")

    print("\n" + "="*60)


if __name__ == '__main__':
    main()
