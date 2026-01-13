"""
ESPN Roster Batch Processor
===========================
Processes all 30 teams for a date in a single batch operation.
Triggered by batch completion message from scraper backfill.

Benefits:
- 96.7% quota reduction (30 DELETEs + INSERTs → 1 batch operation)
- 100% eliminates concurrent write conflicts
- Uses parallel loading + batch DELETE pattern from existing processor

Validation:
- Requires >= 29 teams (97%) to be processed - rejects incomplete batches
- Added Session 26 to fail fast on incomplete scrapes that would corrupt downstream data

This processor is triggered when receiving a message with:
    metadata.trigger_type = 'batch_processing'
    metadata.scraper_type = 'espn_roster'
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from google.cloud import bigquery, storage

from data_processors.raw.espn.espn_team_roster_processor import (
    EspnTeamRosterProcessor,
    discover_latest_files_per_team,
    batch_process_rosters
)

logger = logging.getLogger(__name__)


class EspnRosterBatchProcessor:
    """
    Batch processor for ESPN rosters.

    Wraps the existing batch_process_rosters() function to work with
    the Pub/Sub trigger system.

    Validation:
        Rejects batches with fewer than MIN_TEAMS_THRESHOLD teams (29/30 = 97%)
        to prevent incomplete roster data from corrupting downstream predictions.
    """

    # Minimum teams required - matches scraper threshold (Session 26)
    MIN_TEAMS_THRESHOLD = 29

    def __init__(self):
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bucket = 'nba-scraped-data'
        self.stats = {
            'teams_loaded': 0,
            'players_loaded': 0,
            'players_unresolved': 0,
            'errors': 0
        }

    def run(self, opts: Dict) -> bool:
        """
        Run batch processing for ESPN rosters.

        Args:
            opts: Dictionary with:
                - bucket: GCS bucket name
                - project_id: GCP project ID
                - metadata: Dict with trigger info including date

        Returns:
            True if successful, False otherwise
        """
        try:
            # Extract options
            bucket = opts.get('bucket', self.bucket)
            project_id = opts.get('project_id', self.project_id)
            metadata = opts.get('metadata', {})

            # Get date from metadata or use today
            date = metadata.get('date')
            if not date:
                date = datetime.now(timezone.utc).strftime('%Y-%m-%d')

            logger.info(f"📦 ESPN Roster Batch Processor starting for date={date}")
            logger.info(f"   Metadata: {metadata}")

            # Use existing batch_process_rosters function
            teams_processed, total_players, total_unresolved, errors = batch_process_rosters(
                bucket=bucket,
                date=date,
                project_id=project_id,
                team=None  # Process all teams
            )

            # Update stats
            self.stats['teams_loaded'] = teams_processed
            self.stats['players_loaded'] = total_players
            self.stats['players_unresolved'] = total_unresolved
            self.stats['errors'] = errors

            # VALIDATION: Reject incomplete batches (Session 26)
            # This prevents partial roster data from corrupting downstream predictions
            if teams_processed < self.MIN_TEAMS_THRESHOLD:
                logger.error(
                    f"❌ ESPN Roster Batch REJECTED: Only {teams_processed}/{self.MIN_TEAMS_THRESHOLD} "
                    f"teams processed (threshold: {self.MIN_TEAMS_THRESHOLD}). "
                    f"Incomplete roster data would corrupt predictions."
                )
                # Send alert for incomplete batch
                try:
                    from shared.utils.notification_system import notify_error
                    notify_error(
                        title="ESPN Roster Batch Rejected - Incomplete",
                        message=f"Only {teams_processed}/30 teams processed (min: {self.MIN_TEAMS_THRESHOLD})",
                        details={
                            'date': date,
                            'teams_processed': teams_processed,
                            'min_threshold': self.MIN_TEAMS_THRESHOLD,
                            'total_players': total_players,
                            'errors': errors,
                        },
                        processor_name="ESPN Roster Batch Processor"
                    )
                except Exception as alert_err:
                    logger.warning(f"Failed to send incomplete batch alert: {alert_err}")
                return False

            # Log results
            if errors == 0:
                logger.info(f"✅ ESPN Roster Batch complete: {teams_processed} teams, "
                           f"{total_players} players, {total_unresolved} unresolved")
                return True
            else:
                logger.warning(f"⚠️ ESPN Roster Batch completed with {errors} errors: "
                              f"{teams_processed} teams, {total_players} players")
                return errors < teams_processed  # Partial success if most teams worked

        except Exception as e:
            logger.error(f"❌ ESPN Roster Batch processing failed: {e}", exc_info=True)
            self.stats['errors'] += 1
            return False

    def get_processor_stats(self) -> Dict:
        """Return processor statistics."""
        return self.stats
