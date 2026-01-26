"""
ESPN roster batch handler.

Processes ESPN roster files in batch mode with Firestore locking
to prevent concurrent processing conflicts.
"""

import logging
import re
from datetime import datetime, timezone, timedelta

from google.api_core.exceptions import GoogleAPIError
from google.cloud.exceptions import Conflict as AlreadyExistsError

from shared.clients import get_firestore_client
from data_processors.raw.espn.espn_roster_batch_processor import EspnRosterBatchProcessor


logger = logging.getLogger(__name__)


class ESPNBatchHandler:
    """Handles ESPN roster batch processing with Firestore locking."""

    def process_backfill(self, normalized_message: dict, project_id: str) -> dict:
        """
        Process ESPN roster batch from scraper backfill trigger.

        Args:
            normalized_message: Normalized Pub/Sub message
            project_id: GCP project ID

        Returns:
            Response dict with status, mode, date, and stats
        """
        metadata = normalized_message.get('_metadata', {})
        roster_date = metadata.get('date', 'unknown')

        logger.info(f"📦 ESPN roster backfill batch trigger for date={roster_date}")

        processor = EspnRosterBatchProcessor()
        opts = {
            'bucket': normalized_message.get('bucket', 'nba-scraped-data'),
            'project_id': project_id,
            'metadata': metadata,
            'execution_id': normalized_message.get('_execution_id'),
            'workflow': normalized_message.get('_workflow', 'backfill')
        }

        success = processor.run(opts)

        if success:
            logger.info(f"✅ ESPN roster batch complete for {roster_date}")
            return {
                "status": "success",
                "mode": "batch_backfill",
                "date": roster_date,
                "stats": processor.get_processor_stats()
            }
        else:
            logger.error(f"❌ ESPN roster batch failed for {roster_date}")
            return {
                "status": "error",
                "mode": "batch_backfill",
                "date": roster_date
            }

    def process_folder(self, file_path: str, bucket: str, project_id: str) -> dict:
        """
        Process ESPN roster folder path.

        Args:
            file_path: GCS file path ending with /
            bucket: GCS bucket name
            project_id: GCP project ID

        Returns:
            Response dict with status, mode, date, and stats
        """
        logger.info(f"🔄 ESPN roster folder detected, using batch processor...")

        # Extract date from folder path: espn/rosters/2025-12-28/
        date_match = re.search(r'espn/rosters/(\d{4}-\d{2}-\d{2})/', file_path)
        if not date_match:
            logger.warning(f"Could not extract date from ESPN roster folder path: {file_path}")
            return {
                "status": "skipped",
                "reason": "Could not extract date",
                "mode": "batch_folder"
            }

        roster_date = date_match.group(1)

        batch_processor = EspnRosterBatchProcessor()
        success = batch_processor.run({
            'bucket': bucket,
            'project_id': project_id,
            'metadata': {'date': roster_date}
        })

        stats = batch_processor.get_processor_stats()

        if success:
            logger.info(f"✅ ESPN roster folder batch complete for {roster_date}: {stats}")
            return {
                "status": "success",
                "mode": "batch_folder",
                "date": roster_date,
                "stats": stats
            }
        else:
            logger.error(f"❌ ESPN roster folder batch failed for {roster_date}")
            return {
                "status": "error",
                "mode": "batch_folder",
                "date": roster_date,
                "stats": stats
            }

    def process_with_lock(
        self,
        file_path: str,
        bucket: str,
        project_id: str,
        execution_id: str
    ) -> dict:
        """
        Process ESPN roster file with Firestore locking.

        Instead of processing each team file individually (30 concurrent writes),
        use a Firestore lock to ensure only ONE processor runs the batch.
        This eliminates BigQuery serialization conflicts.

        Args:
            file_path: GCS file path to roster file
            bucket: GCS bucket name
            project_id: GCP project ID
            execution_id: Execution ID for tracking

        Returns:
            Response dict with status and details
        """
        # Extract date from path: espn/rosters/2026-01-08/team_GS/timestamp.json
        date_match = re.search(r'espn/rosters/(\d{4}-\d{2}-\d{2})/', file_path)
        if not date_match:
            # If we can't extract date, this shouldn't happen, but return error
            logger.warning(f"Could not extract date from ESPN roster path: {file_path}")
            return {
                "status": "error",
                "reason": "Could not extract date from path",
                "file": file_path
            }

        roster_date = date_match.group(1)
        lock_id = f"espn_roster_batch_{roster_date}"

        try:
            # Initialize Firestore client via pool
            db = get_firestore_client()
            lock_ref = db.collection('batch_processing_locks').document(lock_id)

            # Try to create lock document (atomic operation)
            # If document already exists, this will raise an exception
            lock_data = {
                'status': 'processing',
                'started_at': datetime.now(timezone.utc),
                'trigger_file': file_path,
                'execution_id': execution_id,
                'expireAt': datetime.now(timezone.utc) + timedelta(minutes=30)  # 30 min TTL
            }

            # Use create() which fails if document exists
            lock_ref.create(lock_data)

            # We got the lock - run batch processor for ALL teams
            logger.info(f"🔒 Acquired batch lock for ESPN rosters {roster_date}, running batch processor...")

            try:
                batch_processor = EspnRosterBatchProcessor()
                success = batch_processor.run({
                    'bucket': bucket,
                    'project_id': project_id,
                    'metadata': {'date': roster_date}
                })

                # Update lock with completion status
                lock_ref.update({
                    'status': 'complete' if success else 'failed',
                    'completed_at': datetime.now(timezone.utc),
                    'stats': batch_processor.get_processor_stats()
                })

                if success:
                    logger.info(f"✅ ESPN roster batch complete for {roster_date}")
                    return {
                        "status": "success",
                        "mode": "batch",
                        "date": roster_date,
                        "stats": batch_processor.get_processor_stats()
                    }
                else:
                    logger.error(f"❌ ESPN roster batch failed for {roster_date}")
                    return {
                        "status": "error",
                        "mode": "batch",
                        "date": roster_date
                    }

            except Exception as batch_error:
                # Update lock with error status
                lock_ref.update({
                    'status': 'error',
                    'completed_at': datetime.now(timezone.utc),
                    'error': str(batch_error)
                })
                raise

        except (AlreadyExistsError, GoogleAPIError) as lock_error:
            # Check if it's an "already exists" error (another processor got the lock)
            error_str = str(lock_error)
            if 'already exists' in error_str.lower() or 'ALREADY_EXISTS' in error_str or isinstance(lock_error, AlreadyExistsError):
                logger.info(f"🔓 ESPN roster batch for {roster_date} already being processed by another instance, skipping")
                return {
                    "status": "skipped",
                    "reason": "batch_already_processing",
                    "date": roster_date
                }
            else:
                # Some other Firestore error - re-raise
                logger.warning(f"⚠️ Failed to acquire batch lock for {roster_date}: {lock_error}")
                raise
