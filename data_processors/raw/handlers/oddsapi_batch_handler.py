"""
OddsAPI batch handler.

Processes OddsAPI game lines and player props in batch mode with Firestore locking
to prevent concurrent processing conflicts and reduce MERGE operations.

When multiple OddsAPI files arrive (typically 14 per scrape cycle from 7 games x 2 endpoints),
use Firestore lock to ensure only ONE processor runs the batch. This reduces MERGE operations
from 14 to 1-2, cutting processing time from 60+ minutes to <5 minutes.
"""

import logging
import re
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from google.api_core.exceptions import GoogleAPIError
from google.cloud.exceptions import Conflict as AlreadyExistsError

from shared.clients import get_firestore_client
from data_processors.raw.oddsapi.oddsapi_batch_processor import (
    OddsApiGameLinesBatchProcessor,
    OddsApiPropsBatchProcessor
)

# Timeout for OddsAPI batch processing (10 minutes)
# This prevents runaway batch jobs from exceeding the Firestore lock TTL (2 hours)
BATCH_PROCESSOR_TIMEOUT_SECONDS = 600


logger = logging.getLogger(__name__)


class OddsAPIBatchHandler:
    """Handles OddsAPI batch processing with Firestore locking and timeout protection."""

    def process_with_lock(
        self,
        file_path: str,
        bucket: str,
        project_id: str,
        execution_id: str
    ) -> dict:
        """
        Process OddsAPI file with Firestore locking and timeout protection.

        Args:
            file_path: GCS file path to odds file
            bucket: GCS bucket name
            project_id: GCP project ID
            execution_id: Execution ID for tracking

        Returns:
            Response dict with status and details
        """
        # Extract date from path: odds-api/game-lines/2026-01-14/{event-id}/timestamp.json
        date_match = re.search(r'odds-api/[^/]+/(\d{4}-\d{2}-\d{2})/', file_path)
        if not date_match:
            logger.warning(f"Could not extract date from OddsAPI path: {file_path}")
            return {
                "status": "error",
                "reason": "Could not extract date from path",
                "file": file_path
            }

        game_date = date_match.group(1)
        endpoint_type = 'game-lines' if 'game-lines' in file_path else 'player-props'
        lock_id = f"oddsapi_{endpoint_type}_batch_{game_date}"

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
                'expireAt': datetime.now(timezone.utc) + timedelta(hours=2)  # 2hr TTL
            }

            # Use create() which fails if document exists
            lock_ref.create(lock_data)

            # We got the lock - run batch processor for ALL files of this type/date
            logger.info(f"🔒 Acquired batch lock for OddsAPI {endpoint_type} {game_date}, running batch processor...")

            try:
                if endpoint_type == 'game-lines':
                    batch_processor = OddsApiGameLinesBatchProcessor()
                else:
                    batch_processor = OddsApiPropsBatchProcessor()

                # Execute batch processor with timeout to prevent runaway jobs
                # If processing exceeds timeout, we fail gracefully and update the lock
                batch_opts = {
                    'bucket': bucket,
                    'project_id': project_id,
                    'game_date': game_date
                }

                try:
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(batch_processor.run, batch_opts)
                        success = future.result(timeout=BATCH_PROCESSOR_TIMEOUT_SECONDS)
                except FuturesTimeoutError:
                    logger.error(
                        f"⏰ OddsAPI {endpoint_type} batch timed out after "
                        f"{BATCH_PROCESSOR_TIMEOUT_SECONDS}s for {game_date}"
                    )
                    lock_ref.update({
                        'status': 'timeout',
                        'completed_at': datetime.now(timezone.utc),
                        'error': f'Batch processing timed out after {BATCH_PROCESSOR_TIMEOUT_SECONDS} seconds'
                    })
                    return {
                        "status": "error",
                        "mode": "batch",
                        "endpoint": endpoint_type,
                        "date": game_date,
                        "error": "timeout",
                        "timeout_seconds": BATCH_PROCESSOR_TIMEOUT_SECONDS
                    }

                # Update lock with completion status
                lock_ref.update({
                    'status': 'complete' if success else 'failed',
                    'completed_at': datetime.now(timezone.utc),
                    'stats': batch_processor.get_processor_stats() if hasattr(batch_processor, 'get_processor_stats') else {}
                })

                if success:
                    logger.info(f"✅ OddsAPI {endpoint_type} batch complete for {game_date}")
                    return {
                        "status": "success",
                        "mode": "batch",
                        "endpoint": endpoint_type,
                        "date": game_date,
                        "stats": batch_processor.get_processor_stats() if hasattr(batch_processor, 'get_processor_stats') else {}
                    }
                else:
                    logger.error(f"❌ OddsAPI {endpoint_type} batch failed for {game_date}")
                    return {
                        "status": "error",
                        "mode": "batch",
                        "endpoint": endpoint_type,
                        "date": game_date
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
                logger.info(
                    f"🔓 OddsAPI {endpoint_type} batch for {game_date} "
                    f"already being processed by another instance, skipping"
                )
                return {
                    "status": "skipped",
                    "reason": "batch_already_processing",
                    "endpoint": endpoint_type,
                    "date": game_date
                }
            else:
                # Some other Firestore error - re-raise
                logger.warning(f"⚠️ Failed to acquire batch lock for OddsAPI {endpoint_type} {game_date}: {lock_error}")
                raise
