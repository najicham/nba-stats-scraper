#!/usr/bin/env python3
"""
Example: Backfill with digest email at the end.

Shows how to use AlertManager to suppress alerts during backfill,
then send a summary email at the end.
"""

from shared.alerts import get_alert_manager
from datetime import date, timedelta

def backfill_with_digest(start_date: str, end_date: str):
    """
    Backfill data with alert suppression and end-of-run digest.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
    """

    # Initialize AlertManager in backfill mode
    alert_mgr = get_alert_manager(backfill_mode=True)

    print(f"Starting backfill: {start_date} to {end_date}")
    print("Alerts will be suppressed and batched for end-of-run summary...")

    # Your backfill logic here
    current = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    success_count = 0
    error_count = 0

    while current <= end:
        try:
            # Process this date
            # processor.run({'date': str(current), 'skip_downstream_trigger': True})
            success_count += 1
        except Exception as e:
            error_count += 1
            # Errors are automatically batched by AlertManager

        current += timedelta(days=1)

    # END OF BACKFILL: Send digest email
    print("\nBackfill complete! Sending summary email...")

    # Get statistics before flushing
    stats = alert_mgr.get_alert_stats()

    # Send digest email
    alert_mgr.flush_batched_alerts()

    print(f"\n✅ Backfill complete!")
    print(f"   Success: {success_count}")
    print(f"   Errors: {error_count}")
    print(f"   Alert batches sent: {len(stats.get('batched_alerts', {}))}")


if __name__ == '__main__':
    # Example usage
    backfill_with_digest('2022-01-01', '2022-01-31')
