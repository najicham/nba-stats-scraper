"""
Backfill Progress Tracker

Tracks backfill progress and sends email reports at milestones (25%, 50%, 75%, 100%).
Designed to be used as a context manager during backfill operations.

Usage:
    from shared.alerts.backfill_progress_tracker import BackfillProgressTracker

    with BackfillProgressTracker(
        season='2023-24',
        phase='Phase 3 Analytics',
        total_dates=175
    ) as tracker:
        for date in dates_to_process:
            try:
                process_date(date)
                tracker.mark_complete(date, success=True)
            except Exception as e:
                tracker.mark_complete(date, success=False, error=str(e))

    # Final report sent automatically on exit

Version: 1.0
Created: 2025-11-30
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class BackfillProgressTracker:
    """
    Track backfill progress and send email reports at milestones.

    Features:
    - Sends progress reports at 25%, 50%, 75% milestones
    - Sends final summary on completion
    - Tracks successful, partial, and failed dates
    - Estimates time remaining
    - Integrates with AWS SES email alerts
    """

    def __init__(
        self,
        season: str,
        phase: str,
        total_dates: int,
        milestones: List[int] = None,
        send_emails: bool = True
    ):
        """
        Initialize progress tracker.

        Args:
            season: Season being backfilled (e.g., "2023-24")
            phase: Phase name (e.g., "Phase 3 Analytics")
            total_dates: Total number of dates to process
            milestones: Percentage milestones to send reports (default: [25, 50, 75, 100])
            send_emails: If False, log only (no emails)
        """
        self.season = season
        self.phase = phase
        self.total_dates = total_dates
        self.milestones = milestones or [25, 50, 75, 100]
        self.send_emails = send_emails

        # Progress tracking
        self.completed_dates = 0
        self.successful = 0
        self.partial = 0
        self.failed = 0
        self.failed_dates: List[str] = []
        self.alerts_suppressed = 0

        # Milestone tracking
        self.last_milestone = 0

        # Timing
        self.start_time = datetime.now(timezone.utc)
        self.last_progress_time = self.start_time

    def __enter__(self):
        """Enter context manager."""
        logger.info(
            f"Starting backfill tracking: {self.season} {self.phase} "
            f"({self.total_dates} dates)"
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager - send final report."""
        self._send_final_report()
        return False  # Don't suppress exceptions

    def mark_complete(
        self,
        date: str,
        success: bool = True,
        partial: bool = False,
        error: Optional[str] = None
    ):
        """
        Mark a date as processed.

        Args:
            date: Date that was processed (YYYY-MM-DD)
            success: If True, date was fully successful
            partial: If True, date had partial success
            error: Error message if failed
        """
        self.completed_dates += 1
        self.last_progress_time = datetime.now(timezone.utc)

        if success and not partial:
            self.successful += 1
        elif partial:
            self.partial += 1
        else:
            self.failed += 1
            self.failed_dates.append(date)
            if error:
                logger.warning(f"Backfill failed for {date}: {error}")

        # Check for milestone
        self._check_milestone()

    def suppress_alert(self):
        """Record that an alert was suppressed (for summary)."""
        self.alerts_suppressed += 1

    def _check_milestone(self):
        """Check if we've hit a milestone and send report."""
        if self.total_dates == 0:
            return

        progress_pct = (self.completed_dates / self.total_dates) * 100

        for milestone in self.milestones:
            if milestone > self.last_milestone and progress_pct >= milestone:
                self.last_milestone = milestone
                if milestone < 100:  # Don't send 100% milestone here - handled by __exit__
                    self._send_progress_report()
                break

    def _send_progress_report(self):
        """Send progress report email."""
        if not self.send_emails:
            logger.info(f"Milestone {self.last_milestone}% reached (emails disabled)")
            return

        try:
            from shared.utils.email_alerting_ses import EmailAlerterSES

            progress_data = self._build_progress_data()

            alerter = EmailAlerterSES()
            success = alerter.send_backfill_progress_report(progress_data)

            if success:
                logger.info(f"📧 Backfill progress report sent ({self.last_milestone}%)")
            else:
                logger.warning(f"Failed to send backfill progress report")

        except ImportError as e:
            logger.warning(f"Email alerter not available: {e}")
        except Exception as e:
            logger.error(f"Error sending progress report: {e}")

    def _send_final_report(self):
        """Send final completion report."""
        # Log final stats
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds() / 60
        logger.info(
            f"Backfill complete: {self.season} {self.phase}\n"
            f"  Total: {self.completed_dates}/{self.total_dates}\n"
            f"  Successful: {self.successful}\n"
            f"  Partial: {self.partial}\n"
            f"  Failed: {self.failed}\n"
            f"  Duration: {elapsed:.1f} minutes\n"
            f"  Alerts suppressed: {self.alerts_suppressed}"
        )

        if not self.send_emails:
            return

        try:
            from shared.utils.email_alerting_ses import EmailAlerterSES

            progress_data = self._build_progress_data()
            progress_data['is_final'] = True

            alerter = EmailAlerterSES()
            success = alerter.send_backfill_progress_report(progress_data)

            if success:
                logger.info(f"📧 Final backfill report sent")
            else:
                logger.warning(f"Failed to send final backfill report")

        except ImportError as e:
            logger.warning(f"Email alerter not available: {e}")
        except Exception as e:
            logger.error(f"Error sending final report: {e}")

    def _build_progress_data(self) -> Dict:
        """Build progress data dictionary for email."""
        elapsed = (self.last_progress_time - self.start_time).total_seconds() / 60
        remaining_dates = self.total_dates - self.completed_dates

        # Estimate remaining time
        if self.completed_dates > 0:
            rate_per_minute = self.completed_dates / elapsed if elapsed > 0 else 0
            estimated_remaining = remaining_dates / rate_per_minute if rate_per_minute > 0 else 0
        else:
            estimated_remaining = 0

        return {
            'season': self.season,
            'phase': self.phase,
            'completed_dates': self.completed_dates,
            'total_dates': self.total_dates,
            'successful': self.successful,
            'partial': self.partial,
            'failed': self.failed,
            'failed_dates': self.failed_dates[-10:],  # Last 10 failures
            'estimated_remaining_minutes': int(estimated_remaining),
            'alerts_suppressed': self.alerts_suppressed
        }

    def get_progress(self) -> Dict:
        """Get current progress as dictionary."""
        return self._build_progress_data()


# Convenience function for simple usage
def track_backfill(
    season: str,
    phase: str,
    total_dates: int,
    send_emails: bool = True
) -> BackfillProgressTracker:
    """
    Create a backfill progress tracker.

    Args:
        season: Season being backfilled
        phase: Phase name
        total_dates: Total dates to process
        send_emails: If True, send milestone emails

    Returns:
        BackfillProgressTracker context manager

    Example:
        with track_backfill('2023-24', 'Phase 3', 175) as tracker:
            for date in dates:
                process_date(date)
                tracker.mark_complete(date, success=True)
    """
    return BackfillProgressTracker(
        season=season,
        phase=phase,
        total_dates=total_dates,
        send_emails=send_emails
    )
