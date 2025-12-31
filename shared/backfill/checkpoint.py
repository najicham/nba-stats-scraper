"""
Backfill Checkpoint Manager

Provides progress persistence for long-running backfills.
Saves checkpoint state to local files so backfills can resume after interruption.

v2.0: Added atomic writes and file locking for robustness

Usage:
    checkpoint = BackfillCheckpoint(
        job_name='team_defense_zone_analysis',
        start_date=date(2021, 10, 19),
        end_date=date(2025, 6, 22)
    )

    # Check if we should resume
    if checkpoint.exists() and not args.no_resume:
        resume_date = checkpoint.get_resume_date()
        print(f"Resuming from {resume_date}")

    # During processing, save progress
    checkpoint.mark_date_complete(current_date)
    checkpoint.mark_date_failed(current_date, error="Some error")

    # Get final summary
    summary = checkpoint.get_summary()
"""

import json
import logging
import os
import fcntl
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Default checkpoint directory
DEFAULT_CHECKPOINT_DIR = '/tmp/backfill_checkpoints'


class BackfillCheckpoint:
    """
    Manages checkpoint state for backfill jobs.

    Features:
    - Saves progress to local JSON file
    - Tracks successful/failed dates
    - Supports resume from last successful date
    - Auto-creates checkpoint directory
    """

    def __init__(
        self,
        job_name: str,
        start_date: date,
        end_date: date,
        checkpoint_dir: str = DEFAULT_CHECKPOINT_DIR
    ):
        """
        Initialize checkpoint manager.

        Args:
            job_name: Name of the backfill job (e.g., 'team_defense_zone_analysis')
            start_date: Start date of the backfill range
            end_date: End date of the backfill range
            checkpoint_dir: Directory to store checkpoint files
        """
        self.job_name = job_name
        self.start_date = start_date
        self.end_date = end_date
        self.checkpoint_dir = Path(checkpoint_dir)

        # Create checkpoint directory if it doesn't exist
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # Checkpoint filename includes date range for uniqueness
        filename = f"{job_name}_{start_date.isoformat()}_{end_date.isoformat()}.json"
        self.checkpoint_path = self.checkpoint_dir / filename

        # State
        self._state = None

    def _get_default_state(self) -> Dict:
        """Get default checkpoint state."""
        return {
            'job_name': self.job_name,
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'created_at': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'last_successful_date': None,
            'successful_dates': [],
            'failed_dates': [],
            'skipped_dates': [],  # Bootstrap dates
            'stats': {
                'total_days': (self.end_date - self.start_date).days + 1,
                'processed': 0,
                'successful': 0,
                'failed': 0,
                'skipped': 0
            }
        }

    def _load_state(self) -> Dict:
        """
        Load state from checkpoint file with validation.

        v2.0: Added file locking for safe concurrent reads and
        schema validation to detect corruption.
        """
        if self._state is not None:
            return self._state

        if self.checkpoint_path.exists():
            lock_path = self.checkpoint_path.with_suffix('.lock')
            try:
                # Use shared lock for reading (allows concurrent reads)
                with open(lock_path, 'w') as lock_file:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
                    try:
                        with open(self.checkpoint_path, 'r') as f:
                            self._state = json.load(f)
                    finally:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

                # v2.0: Validate loaded state
                if self._validate_state(self._state):
                    logger.info(f"Loaded valid checkpoint from {self.checkpoint_path}")
                    return self._state
                else:
                    logger.warning(f"Checkpoint validation failed. Starting fresh.")
                    self._state = None

            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load checkpoint: {e}. Starting fresh.")

        self._state = self._get_default_state()
        return self._state

    def _validate_state(self, state: Dict) -> bool:
        """
        Validate checkpoint state schema.

        v2.0: Ensures checkpoint isn't corrupted.
        """
        required_fields = ['job_name', 'start_date', 'end_date', 'successful_dates', 'failed_dates']
        try:
            # Check required fields exist
            for field in required_fields:
                if field not in state:
                    logger.warning(f"Checkpoint missing required field: {field}")
                    return False

            # Check lists are actually lists
            if not isinstance(state.get('successful_dates', []), list):
                logger.warning("successful_dates is not a list")
                return False
            if not isinstance(state.get('failed_dates', []), list):
                logger.warning("failed_dates is not a list")
                return False

            # Check for duplicates between success and failed
            success_set = set(state.get('successful_dates', []))
            failed_set = set(state.get('failed_dates', []))
            if success_set & failed_set:
                logger.warning("Date appears in both successful and failed lists")
                return False

            return True
        except Exception as e:
            logger.warning(f"Checkpoint validation error: {e}")
            return False

    def _save_state(self):
        """
        Save state to checkpoint file using atomic write pattern.

        v2.0: Uses write-then-rename for atomicity and file locking
        to prevent corruption from concurrent access.
        """
        if self._state is None:
            return

        self._state['last_updated'] = datetime.now().isoformat()

        # v2.0: Use atomic write pattern (write to temp, then rename)
        # This prevents corruption if process crashes mid-write
        try:
            # Create temp file in same directory (for atomic rename)
            temp_path = self.checkpoint_path.with_suffix('.tmp')
            lock_path = self.checkpoint_path.with_suffix('.lock')

            # Acquire file lock to prevent concurrent writes
            with open(lock_path, 'w') as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    # Write to temp file
                    with open(temp_path, 'w') as f:
                        json.dump(self._state, f, indent=2, default=str)
                        f.flush()
                        os.fsync(f.fileno())  # Ensure data is written to disk

                    # Atomic rename (POSIX guarantees atomicity)
                    temp_path.rename(self.checkpoint_path)
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

        except IOError as e:
            logger.error(f"Failed to save checkpoint: {e}")
            # Clean up temp file if it exists
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except (FileNotFoundError, OSError) as e:
                    logger.debug(f"Could not delete temp checkpoint file: {e}")

    def exists(self) -> bool:
        """Check if checkpoint file exists."""
        return self.checkpoint_path.exists()

    def get_resume_date(self) -> Optional[date]:
        """
        Get the date to resume from.

        Returns the day after the last successful date, or start_date if no progress.
        """
        state = self._load_state()

        last_success = state.get('last_successful_date')
        if last_success:
            last_date = datetime.strptime(last_success, '%Y-%m-%d').date()
            resume_date = last_date + timedelta(days=1)

            # Don't resume past end date
            if resume_date > self.end_date:
                return None  # Backfill complete

            return resume_date

        return self.start_date

    def should_skip_date(self, check_date: date) -> bool:
        """
        Check if a date should be skipped (already processed successfully).
        """
        state = self._load_state()
        date_str = check_date.isoformat()

        return date_str in state.get('successful_dates', [])

    def mark_date_complete(self, completed_date: date):
        """Mark a date as successfully processed."""
        state = self._load_state()
        date_str = completed_date.isoformat()

        if date_str not in state['successful_dates']:
            state['successful_dates'].append(date_str)
            state['stats']['successful'] += 1

        state['stats']['processed'] = len(state['successful_dates']) + len(state['failed_dates']) + len(state['skipped_dates'])

        # Update last successful date
        current_last = state.get('last_successful_date')
        if current_last is None or completed_date.isoformat() > current_last:
            state['last_successful_date'] = date_str

        # Remove from failed if it was there (retry success)
        if date_str in state['failed_dates']:
            state['failed_dates'].remove(date_str)
            state['stats']['failed'] -= 1

        self._save_state()

    def mark_date_failed(self, failed_date: date, error: str = None):
        """Mark a date as failed."""
        state = self._load_state()
        date_str = failed_date.isoformat()

        if date_str not in state['failed_dates']:
            state['failed_dates'].append(date_str)
            state['stats']['failed'] += 1

        state['stats']['processed'] = len(state['successful_dates']) + len(state['failed_dates']) + len(state['skipped_dates'])

        self._save_state()

    def mark_date_skipped(self, skipped_date: date, reason: str = 'bootstrap'):
        """Mark a date as skipped (e.g., bootstrap period)."""
        state = self._load_state()
        date_str = skipped_date.isoformat()

        if date_str not in state['skipped_dates']:
            state['skipped_dates'].append(date_str)
            state['stats']['skipped'] += 1

        state['stats']['processed'] = len(state['successful_dates']) + len(state['failed_dates']) + len(state['skipped_dates'])

        self._save_state()

    def get_failed_dates(self) -> List[date]:
        """Get list of failed dates for retry."""
        state = self._load_state()
        return [
            datetime.strptime(d, '%Y-%m-%d').date()
            for d in state.get('failed_dates', [])
        ]

    def get_summary(self) -> Dict:
        """Get checkpoint summary."""
        state = self._load_state()

        return {
            'job_name': state['job_name'],
            'date_range': f"{state['start_date']} to {state['end_date']}",
            'last_successful_date': state.get('last_successful_date'),
            'stats': state['stats'],
            'failed_dates_count': len(state.get('failed_dates', [])),
            'checkpoint_file': str(self.checkpoint_path)
        }

    def clear(self):
        """Clear checkpoint (start fresh)."""
        if self.checkpoint_path.exists():
            self.checkpoint_path.unlink()
            logger.info(f"Cleared checkpoint: {self.checkpoint_path}")

        self._state = None

    def print_status(self):
        """Print current checkpoint status."""
        summary = self.get_summary()
        stats = summary['stats']

        print(f"\n{'='*60}")
        print(f"CHECKPOINT STATUS: {summary['job_name']}")
        print(f"{'='*60}")
        print(f"  Date range: {summary['date_range']}")
        print(f"  Total days: {stats['total_days']}")
        print(f"  Processed:  {stats['processed']}")
        print(f"    - Successful: {stats['successful']}")
        print(f"    - Failed:     {stats['failed']}")
        print(f"    - Skipped:    {stats['skipped']}")

        if summary['last_successful_date']:
            print(f"  Last success: {summary['last_successful_date']}")

        resume_date = self.get_resume_date()
        if resume_date:
            remaining = (self.end_date - resume_date).days + 1
            print(f"  Resume from: {resume_date} ({remaining} days remaining)")
        else:
            print(f"  Status: COMPLETE")

        print(f"  Checkpoint file: {summary['checkpoint_file']}")
        print(f"{'='*60}\n")
