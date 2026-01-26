"""
Basketball Reference roster batch handler.

Processes Basketball Reference roster files in batch mode with Firestore locking
to prevent concurrent processing conflicts.
"""

import logging
import re
from datetime import datetime, timezone, timedelta

from google.api_core.exceptions import GoogleAPIError
from google.cloud.exceptions import Conflict as AlreadyExistsError

from shared.clients import get_firestore_client
from data_processors.raw.basketball_ref.br_roster_batch_processor import BasketballRefRosterBatchProcessor


logger = logging.getLogger(__name__)


class BRBatchHandler:
    """Handles Basketball Reference roster batch processing with Firestore locking."""

    def process_backfill(self, normalized_message: dict, project_id: str) -> dict:
        """
        Process BR roster batch from scraper backfill trigger.

        Args:
            normalized_message: Normalized Pub/Sub message
            project_id: GCP project ID

        Returns:
            Response dict with status, mode, season, and stats
        """
        metadata = normalized_message.get('_metadata', {})
        season = metadata.get('season', 'unknown')

        logger.info(f"📦 BR roster backfill batch trigger for season={season}")

        processor = BasketballRefRosterBatchProcessor()
        opts = {
            'bucket': normalized_message.get('bucket', 'nba-scraped-data'),
            'project_id': project_id,
            'metadata': metadata,
            'execution_id': normalized_message.get('_execution_id'),
            'workflow': normalized_message.get('_workflow', 'backfill')
        }

        success = processor.run(opts)

        if success:
            logger.info(f"✅ BR roster batch complete for season {season}")
            return {
                "status": "success",
                "mode": "batch_backfill",
                "season": season,
                "stats": processor.get_processor_stats() if hasattr(processor, 'get_processor_stats') else {}
            }
        else:
            logger.error(f"❌ BR roster batch failed for season {season}")
            return {
                "status": "error",
                "mode": "batch_backfill",
                "season": season
            }

    def process_with_lock(
        self,
        file_path: str,
        bucket: str,
        project_id: str,
        execution_id: str
    ) -> dict:
        """
        Process BR roster file with Firestore locking.

        Same pattern as ESPN rosters: use Firestore lock to ensure only ONE
        processor runs the batch. This eliminates BigQuery "Too many DML
        statements" errors caused by 30+ concurrent writes.

        Args:
            file_path: GCS file path to roster file
            bucket: GCS bucket name
            project_id: GCP project ID
            execution_id: Execution ID for tracking

        Returns:
            Response dict with status and details
        """
        # Extract season from path: basketball-ref/season-rosters/2024-25/LAL/timestamp.json
        season_match = re.search(r'basketball-ref/season-rosters/(\d{4}-\d{2})/', file_path)
        if not season_match:
            logger.warning(f"Could not extract season from BR roster path: {file_path}")
            return {
                "status": "error",
                "reason": "Could not extract season from path",
                "file": file_path
            }

        season = season_match.group(1)
        lock_id = f"br_roster_batch_{season}"

        try:
            # Initialize Firestore client via pool
            db = get_firestore_client()
            lock_ref = db.collection('batch_processing_locks').document(lock_id)

            # Try to create lock document (atomic operation)
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
            logger.info(f"🔒 Acquired batch lock for BR rosters season {season}, running batch processor...")

            try:
                batch_processor = BasketballRefRosterBatchProcessor()
                success = batch_processor.run({
                    'bucket': bucket,
                    'project_id': project_id,
                    'metadata': {'season': season}
                })

                # Update lock with completion status
                lock_ref.update({
                    'status': 'complete' if success else 'failed',
                    'completed_at': datetime.now(timezone.utc),
                    'stats': batch_processor.get_processor_stats() if hasattr(batch_processor, 'get_processor_stats') else {}
                })

                if success:
                    logger.info(f"✅ BR roster batch complete for season {season}")
                    return {
                        "status": "success",
                        "mode": "batch",
                        "season": season,
                        "stats": batch_processor.get_processor_stats() if hasattr(batch_processor, 'get_processor_stats') else {}
                    }
                else:
                    logger.error(f"❌ BR roster batch failed for season {season}")
                    return {
                        "status": "error",
                        "mode": "batch",
                        "season": season
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
                logger.info(f"🔓 BR roster batch for season {season} already being processed by another instance, skipping")
                return {
                    "status": "skipped",
                    "reason": "batch_already_processing",
                    "season": season
                }
            else:
                # Some other Firestore error - re-raise
                logger.warning(f"⚠️ Failed to acquire batch lock for BR rosters {season}: {lock_error}")
                raise
