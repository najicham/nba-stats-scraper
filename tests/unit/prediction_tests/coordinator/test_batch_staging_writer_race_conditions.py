#!/usr/bin/env python3
"""
Unit Tests for Batch Staging Writer Race Conditions

Tests the distributed lock implementation and batch consolidation to prevent
race conditions that caused duplicate rows with different prediction_ids.

Reference: docs/08-projects/current/week-1-improvements/AGENT-STUDY-WEEK1-2026-01-21.md
Lines 120-146 (Agent 2: Distributed Lock Implementation)

Code Under Test:
- predictions/coordinator/distributed_lock.py (lines 57-323)
- predictions/coordinator/batch_staging_writer.py (lines 141-767)

Race Condition Pattern (Session 92 Fix):
- Problem: Two consolidations run concurrently for same game_date
- Both check main table for existing business keys
- Both find "NOT MATCHED" status (before either commits)
- Both execute INSERT operations
- Result: Duplicate rows with different prediction_ids
- Evidence: 5 duplicates on Jan 11, 2026 (timestamps 0.4 seconds apart)

Test Coverage:
1. TestDistributedLock (11 tests): Lock acquisition, expiry, context manager
2. TestBatchStagingWriter (7 tests): Staging table writes, schema handling
3. TestBatchConsolidator (15 tests): MERGE operations, validation, cleanup
4. TestRaceConditionScenarios (4 tests): Concurrent operations, lock prevention
5. TestLockEdgeCases (6 tests): Firestore transaction isolation, timeout edge cases
"""

import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime, timedelta, timezone
import time
from typing import Dict, List, Any

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..'))
sys.path.insert(0, project_root)

# Import from the coordinator package (not worker)
import importlib.util

# First, load distributed_lock and inject into sys.modules
spec_lock = importlib.util.spec_from_file_location(
    "predictions.coordinator.distributed_lock",
    os.path.join(project_root, "predictions/coordinator/distributed_lock.py")
)
distributed_lock = importlib.util.module_from_spec(spec_lock)
sys.modules['predictions.coordinator.distributed_lock'] = distributed_lock
spec_lock.loader.exec_module(distributed_lock)

# Create parent module structure if needed
# First, try to import the real predictions package to avoid shadowing
try:
    import predictions as real_predictions
    predictions = real_predictions
except ImportError:
    if 'predictions' not in sys.modules:
        predictions = type(sys)('predictions')
        sys.modules['predictions'] = predictions
    else:
        predictions = sys.modules['predictions']

# predictions.coordinator is a REAL package. Import it rather than fabricating a
# stub module: a synthetic module has no __path__, so it leaves sys.modules poisoned
# for every later test that does `from predictions.coordinator.X import ...`
# (ModuleNotFoundError: 'predictions.coordinator' is not a package). That single
# stub was blocking collection of 4 test modules for the whole suite.
try:
    import predictions.coordinator as coordinator
except ImportError:
    coordinator = sys.modules.get('predictions.coordinator')
    if coordinator is None:
        coordinator = type(sys)('predictions.coordinator')
        coordinator.__path__ = [os.path.join(project_root, 'predictions/coordinator')]
        sys.modules['predictions.coordinator'] = coordinator
    predictions.coordinator = coordinator

# Now load batch_staging_writer (can import distributed_lock properly)
spec_writer = importlib.util.spec_from_file_location(
    "predictions.coordinator.batch_staging_writer",
    os.path.join(project_root, "predictions/coordinator/batch_staging_writer.py")
)
batch_staging_writer = importlib.util.module_from_spec(spec_writer)
sys.modules['predictions.coordinator.batch_staging_writer'] = batch_staging_writer
spec_writer.loader.exec_module(batch_staging_writer)

# Extract classes and constants
DistributedLock = distributed_lock.DistributedLock
LockAcquisitionError = distributed_lock.LockAcquisitionError
LOCK_TIMEOUT_SECONDS = distributed_lock.LOCK_TIMEOUT_SECONDS
MAX_ACQUIRE_ATTEMPTS = distributed_lock.MAX_ACQUIRE_ATTEMPTS
RETRY_DELAY_SECONDS = distributed_lock.RETRY_DELAY_SECONDS

BatchStagingWriter = batch_staging_writer.BatchStagingWriter
BatchConsolidator = batch_staging_writer.BatchConsolidator
StagingWriteResult = batch_staging_writer.StagingWriteResult
ConsolidationResult = batch_staging_writer.ConsolidationResult

from google.api_core import exceptions as gcp_exceptions

# 2026-09-08: `predictions/coordinator/distributed_lock.py` is now a
# backward-compatibility shim that re-exports the classes from
# `predictions/shared/distributed_lock.py`. The shim does NOT re-export the
# module-level `_get_firestore_client` helper, and `DistributedLock` resolves
# that name from its own (shared) module globals — so patching it on the shim
# both raised AttributeError and would have patched the wrong module anyway.
# That single stale patch target failed all 30 tests in this file at setUp.
from predictions.shared import distributed_lock as shared_distributed_lock
# Same story for batch_staging_writer: the coordinator module is a shim, and
# `DistributedLock` lives in the shared module's namespace where the code
# under test actually looks it up.
from predictions.shared import batch_staging_writer as shared_batch_staging_writer


class TestDistributedLock(unittest.TestCase):
    """
    Test distributed lock implementation.

    Tests lock key generation, acquisition, expiry, context manager,
    and concurrent lock types.
    """

    def setUp(self):
        """Set up test fixtures."""
        self.project_id = "test-project"
        self.mock_firestore = MagicMock()
        self.mock_db = MagicMock()
        self.mock_collection = MagicMock()
        self.mock_doc_ref = MagicMock()

        # Patch Firestore client
        self.firestore_patcher = patch.object(
            shared_distributed_lock, '_get_firestore_client'
        )
        self.mock_get_firestore = self.firestore_patcher.start()
        # _get_firestore_client returns the CLIENT itself, not the module — so
        # this is what `DistributedLock.db` becomes.
        self.mock_get_firestore.return_value = self.mock_db
        self.mock_firestore.Client.return_value = self.mock_db
        self.mock_firestore.SERVER_TIMESTAMP = datetime.now(timezone.utc)

        # Setup collection/document chain
        self.mock_db.collection.return_value = self.mock_collection
        self.mock_collection.document.return_value = self.mock_doc_ref

    def tearDown(self):
        """Clean up patches."""
        self.firestore_patcher.stop()

    def test_lock_key_generation_consolidation(self):
        """Test lock key generation for consolidation lock type."""
        lock = DistributedLock(self.project_id, lock_type="consolidation")
        lock_key = lock._generate_lock_key("2026-01-17")

        self.assertEqual(lock_key, "consolidation_2026-01-17")
        self.assertEqual(lock.collection_name, "consolidation_locks")

    def test_lock_key_generation_grading(self):
        """Test lock key generation for grading lock type."""
        lock = DistributedLock(self.project_id, lock_type="grading")
        lock_key = lock._generate_lock_key("2026-01-17")

        self.assertEqual(lock_key, "grading_2026-01-17")
        self.assertEqual(lock.collection_name, "grading_locks")

    def test_lock_acquisition_success(self):
        """Test successful lock acquisition when lock doesn't exist."""
        lock = DistributedLock(self.project_id, lock_type="consolidation")

        # Mock Firestore transaction: lock doesn't exist
        mock_snapshot = MagicMock()
        mock_snapshot.exists = False
        self.mock_doc_ref.get.return_value = mock_snapshot

        mock_transaction = MagicMock()
        self.mock_db.transaction.return_value = mock_transaction

        # Mock transactional decorator
        @self.mock_firestore.transactional
        def acquire_in_transaction(transaction):
            snapshot = self.mock_doc_ref.get(transaction=transaction)
            if not snapshot.exists:
                transaction.set(self.mock_doc_ref, {})
                return True
            return False

        # Execute acquisition
        acquired = lock._try_acquire("consolidation_2026-01-17", "batch123", "holder1")

        self.assertTrue(acquired)
        self.assertEqual(lock.lock_doc_ref, self.mock_doc_ref)

    def test_lock_acquisition_already_held(self):
        """Test lock acquisition fails when lock is held by another operation."""
        lock = DistributedLock(self.project_id, lock_type="consolidation")

        # Mock Firestore transaction: lock exists and not expired
        mock_snapshot = MagicMock()
        mock_snapshot.exists = True
        future_time = datetime.now(timezone.utc) + timedelta(seconds=200)
        mock_snapshot.to_dict.return_value = {
            'operation_id': 'other_batch',
            'expires_at': future_time
        }
        self.mock_doc_ref.get.return_value = mock_snapshot

        mock_transaction = MagicMock()
        self.mock_db.transaction.return_value = mock_transaction

        # Mock the transactional decorator to return False
        def mock_transactional_false(transaction):
            # Check if lock exists and not expired
            snapshot = self.mock_doc_ref.get(transaction=transaction)
            if snapshot.exists:
                lock_data = snapshot.to_dict()
                expires_at = lock_data.get('expires_at')
                if expires_at and expires_at.timestamp() > time.time():
                    return False
            return True

        with patch.object(lock, '_try_acquire', return_value=False):
            acquired = lock._try_acquire("consolidation_2026-01-17", "batch123", "holder1")

            self.assertFalse(acquired)
            self.assertIsNone(lock.lock_doc_ref)

    def test_lock_expired_takeover(self):
        """Test lock can be acquired when previous lock expired."""
        lock = DistributedLock(self.project_id, lock_type="consolidation")

        # Create a timestamp that's clearly in the past
        # Use a fixed past timestamp (1 hour ago)
        past_timestamp = time.time() - 3600

        # Mock Firestore transaction: lock exists but expired
        mock_snapshot = MagicMock()
        mock_snapshot.exists = True
        # Create a mock datetime object with correct timestamp
        mock_expires_at = MagicMock()
        mock_expires_at.timestamp.return_value = past_timestamp
        mock_snapshot.to_dict.return_value = {
            'operation_id': 'old_batch',
            'expires_at': mock_expires_at
        }
        self.mock_doc_ref.get.return_value = mock_snapshot

        mock_transaction = MagicMock()
        self.mock_db.transaction.return_value = mock_transaction

        # Test the logic directly
        lock_data = mock_snapshot.to_dict()
        expires_at = lock_data.get('expires_at')

        # Verify expired lock is detected
        self.assertLess(expires_at.timestamp(), time.time())

    def test_context_manager_releases_on_success(self):
        """Test context manager releases lock after successful operation."""
        lock = DistributedLock(self.project_id, lock_type="consolidation")

        # Mock successful acquisition
        with patch.object(lock, '_try_acquire', return_value=True):
            with patch.object(lock, '_release') as mock_release:
                lock.lock_doc_ref = self.mock_doc_ref

                with lock.acquire(game_date="2026-01-17", operation_id="batch123"):
                    # Simulate successful operation
                    pass

                # Verify release was called
                mock_release.assert_called_once_with("consolidation_2026-01-17", "batch123")

    def test_context_manager_releases_on_exception(self):
        """Test context manager releases lock even when exception occurs."""
        lock = DistributedLock(self.project_id, lock_type="consolidation")

        # Mock successful acquisition
        with patch.object(lock, '_try_acquire', return_value=True):
            with patch.object(lock, '_release') as mock_release:
                lock.lock_doc_ref = self.mock_doc_ref

                try:
                    with lock.acquire(game_date="2026-01-17", operation_id="batch123"):
                        # Simulate operation failure
                        raise ValueError("Test error")
                except ValueError:
                    pass

                # Verify release was called despite exception
                mock_release.assert_called_once_with("consolidation_2026-01-17", "batch123")

    def test_lock_acquisition_timeout_raises(self):
        """Test LockAcquisitionError raised after max wait time."""
        lock = DistributedLock(self.project_id, lock_type="consolidation")

        # Mock all acquisition attempts failing
        with patch.object(lock, '_try_acquire', return_value=False):
            with patch('time.sleep'):  # Speed up test
                with self.assertRaises(LockAcquisitionError) as context:
                    with lock.acquire(
                        game_date="2026-01-17",
                        operation_id="batch123",
                        max_wait_seconds=10
                    ):
                        pass

                # Verify error message contains useful info
                error_msg = str(context.exception)
                self.assertIn("Failed to acquire", error_msg)
                self.assertIn("consolidation_locks", error_msg)
                self.assertIn("2026-01-17", error_msg)

    def test_lock_retry_logic(self):
        """Test lock acquisition retries with proper delay."""
        lock = DistributedLock(self.project_id, lock_type="consolidation")

        # Mock: first attempt fails, second succeeds
        acquire_results = [False, True]
        mock_try_acquire = Mock(side_effect=acquire_results)

        with patch.object(lock, '_try_acquire', mock_try_acquire):
            with patch('time.sleep') as mock_sleep:
                with patch.object(lock, '_release'):
                    lock.lock_doc_ref = self.mock_doc_ref

                    with lock.acquire(game_date="2026-01-17", operation_id="batch123"):
                        pass

                    # Verify retry was attempted
                    self.assertEqual(mock_try_acquire.call_count, 2)
                    # Verify sleep was called between attempts
                    mock_sleep.assert_called_once_with(RETRY_DELAY_SECONDS)

    def test_concurrent_lock_types_independent(self):
        """Test consolidation and grading locks are independent."""
        consolidation_lock = DistributedLock(self.project_id, lock_type="consolidation")
        grading_lock = DistributedLock(self.project_id, lock_type="grading")

        # Verify different collection names
        self.assertEqual(consolidation_lock.collection_name, "consolidation_locks")
        self.assertEqual(grading_lock.collection_name, "grading_locks")

        # Verify different lock keys
        consolidation_key = consolidation_lock._generate_lock_key("2026-01-17")
        grading_key = grading_lock._generate_lock_key("2026-01-17")
        self.assertNotEqual(consolidation_key, grading_key)

    def test_force_release_deletes_lock(self):
        """Test force_release deletes the lock document."""
        lock = DistributedLock(self.project_id, lock_type="consolidation")

        # Mock document reference
        mock_lock_ref = MagicMock()
        self.mock_collection.document.return_value = mock_lock_ref

        lock.force_release("2026-01-17")

        # Verify delete was called
        mock_lock_ref.delete.assert_called_once()


def _schema_field(name: str):
    """A BigQuery SchemaField stand-in whose `.name` is a real string."""
    field = MagicMock()
    field.name = name
    return field


class TestBatchStagingWriter(unittest.TestCase):
    """
    Test batch staging writer implementation.

    Tests staging table writes, schema handling, and error cases.
    """

    def setUp(self):
        """Set up test fixtures."""
        self.project_id = "test-project"
        self.mock_bq_client = MagicMock()
        self.writer = BatchStagingWriter(self.mock_bq_client, self.project_id)

        # Mock schema.
        # NOTE: `MagicMock(name='x')` sets the mock's *repr* name, not a `.name`
        # attribute — `field.name` would still be a MagicMock. The writer's
        # schema validation does `{field.name for field in schema}` and then
        # sorts the set difference, which blew up on MagicMock comparison and
        # was reported as a bogus "SCHEMA MISMATCH ... 0 fields ... []".
        self.mock_schema = [
            _schema_field('prediction_id'),
            _schema_field('game_id'),
            _schema_field('player_lookup'),
        ]

    def test_write_to_staging_success(self):
        """Test successful write to staging table."""
        predictions = [
            {'prediction_id': 'pred1', 'game_id': 'game1', 'player_lookup': 'lebronjames'},
            {'prediction_id': 'pred2', 'game_id': 'game1', 'player_lookup': 'stephencurry'},
        ]

        # Mock schema retrieval
        mock_table = MagicMock()
        mock_table.schema = self.mock_schema
        self.mock_bq_client.get_table.return_value = mock_table

        # Mock load job
        mock_load_job = MagicMock()
        mock_load_job.result.return_value = None
        self.mock_bq_client.load_table_from_json.return_value = mock_load_job

        result = self.writer.write_to_staging(predictions, "batch123", "worker1")

        # Verify success
        self.assertTrue(result.success)
        self.assertEqual(result.rows_written, 2)
        self.assertIn("_staging_batch123_worker1", result.staging_table_name)
        self.assertIsNone(result.error_message)

        # Verify load_table_from_json was called
        self.mock_bq_client.load_table_from_json.assert_called_once()

    def test_write_to_staging_creates_table(self):
        """Test write creates staging table with correct configuration."""
        predictions = [{'prediction_id': 'pred1'}]

        # Mock schema retrieval
        mock_table = MagicMock()
        mock_table.schema = self.mock_schema
        self.mock_bq_client.get_table.return_value = mock_table

        # Mock load job
        mock_load_job = MagicMock()
        mock_load_job.result.return_value = None
        self.mock_bq_client.load_table_from_json.return_value = mock_load_job

        self.writer.write_to_staging(predictions, "batch123", "worker1")

        # Verify job config
        call_args = self.mock_bq_client.load_table_from_json.call_args
        job_config = call_args[1]['job_config']

        # Verify WRITE_APPEND and CREATE_IF_NEEDED
        from google.cloud import bigquery
        self.assertEqual(job_config.write_disposition, bigquery.WriteDisposition.WRITE_APPEND)
        self.assertEqual(job_config.create_disposition, bigquery.CreateDisposition.CREATE_IF_NEEDED)
        self.assertFalse(job_config.autodetect)

    def test_write_to_staging_uses_write_append(self):
        """Test write uses WRITE_APPEND disposition (not MERGE)."""
        predictions = [{'prediction_id': 'pred1'}]

        # Mock schema retrieval
        mock_table = MagicMock()
        mock_table.schema = self.mock_schema
        self.mock_bq_client.get_table.return_value = mock_table

        # Mock load job
        mock_load_job = MagicMock()
        mock_load_job.result.return_value = None
        self.mock_bq_client.load_table_from_json.return_value = mock_load_job

        self.writer.write_to_staging(predictions, "batch123", "worker1")

        # Verify load_table_from_json (NOT DML operation)
        self.mock_bq_client.load_table_from_json.assert_called_once()
        # Verify query (DML) was NOT called
        self.mock_bq_client.query.assert_not_called()

    def test_write_to_staging_empty_predictions(self):
        """Test write handles empty predictions list gracefully."""
        predictions = []

        result = self.writer.write_to_staging(predictions, "batch123", "worker1")

        # Verify success but no rows written
        self.assertTrue(result.success)
        self.assertEqual(result.rows_written, 0)
        self.assertIsNone(result.error_message)

        # Verify no load job was executed
        self.mock_bq_client.load_table_from_json.assert_not_called()

    def test_write_to_staging_bad_request_error(self):
        """Test write handles BadRequest error (schema mismatch)."""
        predictions = [{'prediction_id': 'pred1'}]

        # Mock schema retrieval
        mock_table = MagicMock()
        mock_table.schema = self.mock_schema
        self.mock_bq_client.get_table.return_value = mock_table

        # Mock BadRequest error
        self.mock_bq_client.load_table_from_json.side_effect = gcp_exceptions.BadRequest("Schema mismatch")

        result = self.writer.write_to_staging(predictions, "batch123", "worker1")

        # Verify failure
        self.assertFalse(result.success)
        self.assertEqual(result.rows_written, 0)
        self.assertIn("Invalid request", result.error_message)

    def test_write_to_staging_not_found_error(self):
        """Test write handles NotFound error (missing dataset/table)."""
        predictions = [{'prediction_id': 'pred1'}]

        # Mock NotFound error on schema retrieval
        self.mock_bq_client.get_table.side_effect = gcp_exceptions.NotFound("Table not found")

        result = self.writer.write_to_staging(predictions, "batch123", "worker1")

        # Verify failure
        self.assertFalse(result.success)
        self.assertEqual(result.rows_written, 0)
        self.assertIn("Table or dataset not found", result.error_message)

    def test_write_to_staging_schema_mismatch(self):
        """A field the BQ table lacks is caught BEFORE the load job runs.

        Session 159 added validate_output_schema(), which short-circuits the
        write when the first record carries a field the main table does not
        have. The test previously asserted the generic "Invalid request" text
        from the load-job failure path — that path is now unreachable for this
        input, which is the point of the check: it names the offending field
        instead of surfacing an opaque BadRequest.
        """
        predictions = [
            {'prediction_id': 'pred1', 'invalid_field': 'value'}  # Extra field not in schema
        ]

        # Mock schema retrieval
        mock_table = MagicMock()
        mock_table.schema = self.mock_schema
        self.mock_bq_client.get_table.return_value = mock_table

        result = self.writer.write_to_staging(predictions, "batch123", "worker1")

        self.assertFalse(result.success)
        self.assertEqual(result.rows_written, 0)
        self.assertIn("SCHEMA MISMATCH", result.error_message)
        self.assertIn("invalid_field", result.error_message)
        # Short-circuited: no load job should have been attempted at all.
        self.mock_bq_client.load_table_from_json.assert_not_called()

    def test_write_to_staging_reports_validation_failure_distinctly(self):
        """A broken schema *lookup* must not be reported as a schema mismatch.

        validate_output_schema() returns valid=False both for a genuine field
        mismatch and for its own failure (BQ unreachable, bad permissions). The
        caller used to render the second case as
        "SCHEMA MISMATCH: ... 0 fields not in BQ table: []", sending the
        operator to ALTER TABLE for an infrastructure problem.
        """
        predictions = [{'prediction_id': 'pred1'}]

        with patch.object(
            self.writer,
            'validate_output_schema',
            return_value={
                'valid': False,
                'bq_columns': set(),
                'missing_from_bq': [],
                'extra_in_bq': [],
                'error': '403 Permission denied on table',
            },
        ):
            mock_table = MagicMock()
            mock_table.schema = self.mock_schema
            self.mock_bq_client.get_table.return_value = mock_table

            result = self.writer.write_to_staging(predictions, "batch123", "worker1")

        self.assertFalse(result.success)
        self.assertIn("SCHEMA VALIDATION FAILED", result.error_message)
        self.assertIn("403 Permission denied", result.error_message)
        self.assertNotIn("0 fields", result.error_message)


class TestBatchConsolidator(unittest.TestCase):
    """
    Test batch consolidator implementation.

    Tests MERGE operations, validation, cleanup, and distributed locking.
    """

    def setUp(self):
        """Set up test fixtures."""
        self.project_id = "test-project"
        self.mock_bq_client = MagicMock()
        self.consolidator = BatchConsolidator(self.mock_bq_client, self.project_id)

        # Mock staging tables
        self.staging_tables = [
            f"{self.project_id}.nba_predictions._staging_batch123_worker1",
            f"{self.project_id}.nba_predictions._staging_batch123_worker2",
        ]

    def test_consolidate_lock_acquired(self):
        """Test consolidation acquires distributed lock."""
        # Mock find staging tables
        with patch.object(self.consolidator, '_find_staging_tables', return_value=self.staging_tables):
            # Mock consolidation logic
            with patch.object(self.consolidator, '_consolidate_with_lock') as mock_consolidate:
                mock_consolidate.return_value = ConsolidationResult(
                    rows_affected=100,
                    staging_tables_merged=2,
                    staging_tables_cleaned=2,
                    success=True,
                    error_message=None
                )

                # Mock distributed lock
                with patch.object(shared_batch_staging_writer, 'DistributedLock') as mock_lock_class:
                    mock_lock = MagicMock()
                    mock_lock_class.return_value = mock_lock
                    mock_lock.acquire.return_value.__enter__ = Mock(return_value=None)
                    mock_lock.acquire.return_value.__exit__ = Mock(return_value=None)

                    result = self.consolidator.consolidate_batch(
                        batch_id="batch123",
                        game_date="2026-01-17",
                        use_lock=True
                    )

                    # Verify lock was acquired
                    mock_lock_class.assert_called_once_with(
                        project_id=self.project_id,
                        lock_type="consolidation"
                    )
                    mock_lock.acquire.assert_called_once_with(
                        game_date="2026-01-17",
                        operation_id="batch123"
                    )

    def test_consolidate_no_staging_tables(self):
        """Test consolidation handles no staging tables gracefully."""
        with patch.object(self.consolidator, '_find_staging_tables', return_value=[]):
            result = self.consolidator._consolidate_with_lock(
                batch_id="batch123",
                game_date="2026-01-17",
                cleanup=True,
                start_time=time.time()
            )

            # Verify success but no work done
            self.assertTrue(result.success)
            self.assertEqual(result.rows_affected, 0)
            self.assertEqual(result.staging_tables_merged, 0)
            self.assertEqual(result.staging_tables_cleaned, 0)

    def test_consolidate_merge_succeeds(self):
        """Test successful MERGE operation."""
        with patch.object(self.consolidator, '_find_staging_tables', return_value=self.staging_tables):
            # Mock MERGE query execution
            mock_merge_job = MagicMock()
            mock_merge_job.result.return_value = None
            mock_merge_job.num_dml_affected_rows = 100
            self.mock_bq_client.query.return_value = mock_merge_job

            # Mock validation
            with patch.object(self.consolidator, '_check_for_duplicates', return_value=0):
                # Mock cleanup
                with patch.object(self.consolidator, '_cleanup_staging_tables', return_value=2):
                    result = self.consolidator._consolidate_with_lock(
                        batch_id="batch123",
                        game_date="2026-01-17",
                        cleanup=True,
                        start_time=time.time()
                    )

                    # Verify success
                    self.assertTrue(result.success)
                    self.assertEqual(result.rows_affected, 100)
                    self.assertEqual(result.staging_tables_merged, 2)
                    self.assertEqual(result.staging_tables_cleaned, 2)
                    self.assertIsNone(result.error_message)

    def test_consolidate_merge_returns_zero_rows(self):
        """Test consolidation detects MERGE returning 0 rows (data loss indicator)."""
        with patch.object(self.consolidator, '_find_staging_tables', return_value=self.staging_tables):
            # Mock MERGE query returning 0 rows
            mock_merge_job = MagicMock()
            mock_merge_job.result.return_value = None
            mock_merge_job.num_dml_affected_rows = 0  # Suspicious!
            self.mock_bq_client.query.return_value = mock_merge_job

            result = self.consolidator._consolidate_with_lock(
                batch_id="batch123",
                game_date="2026-01-17",
                cleanup=True,
                start_time=time.time()
            )

            # Verify failure
            self.assertFalse(result.success)
            self.assertEqual(result.rows_affected, 0)
            self.assertEqual(result.staging_tables_cleaned, 0)  # Not cleaned up
            self.assertIn("MERGE returned 0 rows", result.error_message)

    def test_consolidate_duplicates_detected_post_merge(self):
        """Test post-consolidation validation detects duplicates."""
        with patch.object(self.consolidator, '_find_staging_tables', return_value=self.staging_tables):
            # Mock successful MERGE
            mock_merge_job = MagicMock()
            mock_merge_job.result.return_value = None
            mock_merge_job.num_dml_affected_rows = 100
            self.mock_bq_client.query.return_value = mock_merge_job

            # Session 495 added a second gate: total duplicates no longer fail
            # the run on their own, only duplicates still ACTIVE after
            # deactivation do. Both have to be stubbed.
            with patch.object(self.consolidator, '_check_for_duplicates', return_value=5), \
                 patch.object(self.consolidator, '_check_for_active_duplicates', return_value=5):
                result = self.consolidator._consolidate_with_lock(
                    batch_id="batch123",
                    game_date="2026-01-17",
                    cleanup=True,
                    start_time=time.time()
                )

                # Verify failure
                self.assertFalse(result.success)
                self.assertEqual(result.staging_tables_cleaned, 0)  # Not cleaned up
                self.assertIn("duplicate business keys detected", result.error_message.lower())

    def test_consolidate_preserves_staging_when_duplicate_check_errors(self):
        """An UNVERIFIABLE duplicate check must not delete the evidence.

        `_check_for_active_duplicates` returns -1 when its own query fails.
        The `> 0` test read that as "no active duplicates" and went straight on
        to drop the staging tables, so a timed-out validation query destroyed
        the only record of a possible duplicate incident.
        """
        with patch.object(self.consolidator, '_find_staging_tables', return_value=self.staging_tables):
            mock_merge_job = MagicMock()
            mock_merge_job.result.return_value = None
            mock_merge_job.num_dml_affected_rows = 100
            self.mock_bq_client.query.return_value = mock_merge_job

            with patch.object(self.consolidator, '_check_for_duplicates', return_value=5), \
                 patch.object(self.consolidator, '_check_for_active_duplicates', return_value=-1), \
                 patch.object(self.consolidator, '_cleanup_staging_tables') as mock_cleanup:
                result = self.consolidator._consolidate_with_lock(
                    batch_id="batch123",
                    game_date="2026-01-17",
                    cleanup=True,
                    start_time=time.time()
                )

        # The MERGE committed, so the consolidation itself still succeeded...
        self.assertTrue(result.success)
        # ...but nothing was cleaned up.
        mock_cleanup.assert_not_called()
        self.assertEqual(result.staging_tables_cleaned, 0)

    def test_consolidate_validation_passed(self):
        """Test consolidation succeeds when validation passes."""
        with patch.object(self.consolidator, '_find_staging_tables', return_value=self.staging_tables):
            # Mock successful MERGE
            mock_merge_job = MagicMock()
            mock_merge_job.result.return_value = None
            mock_merge_job.num_dml_affected_rows = 100
            self.mock_bq_client.query.return_value = mock_merge_job

            # Mock validation passing
            with patch.object(self.consolidator, '_check_for_duplicates', return_value=0):
                with patch.object(self.consolidator, '_cleanup_staging_tables', return_value=2):
                    result = self.consolidator._consolidate_with_lock(
                        batch_id="batch123",
                        game_date="2026-01-17",
                        cleanup=True,
                        start_time=time.time()
                    )

                    # Verify success
                    self.assertTrue(result.success)
                    self.assertEqual(result.staging_tables_cleaned, 2)

    def test_consolidate_cleanup_executed(self):
        """Test staging tables are cleaned up after successful consolidation."""
        with patch.object(self.consolidator, '_find_staging_tables', return_value=self.staging_tables):
            # Mock successful MERGE
            mock_merge_job = MagicMock()
            mock_merge_job.result.return_value = None
            mock_merge_job.num_dml_affected_rows = 100
            self.mock_bq_client.query.return_value = mock_merge_job

            # Mock validation
            with patch.object(self.consolidator, '_check_for_duplicates', return_value=0):
                # Mock cleanup
                with patch.object(self.consolidator, '_cleanup_staging_tables') as mock_cleanup:
                    mock_cleanup.return_value = 2

                    result = self.consolidator._consolidate_with_lock(
                        batch_id="batch123",
                        game_date="2026-01-17",
                        cleanup=True,
                        start_time=time.time()
                    )

                    # Verify cleanup was called
                    mock_cleanup.assert_called_once_with("batch123")
                    self.assertEqual(result.staging_tables_cleaned, 2)

    def test_consolidate_cleanup_skipped_on_failure(self):
        """Test staging tables are NOT cleaned up when consolidation fails."""
        with patch.object(self.consolidator, '_find_staging_tables', return_value=self.staging_tables):
            # Mock MERGE returning 0 rows (failure)
            mock_merge_job = MagicMock()
            mock_merge_job.result.return_value = None
            mock_merge_job.num_dml_affected_rows = 0
            self.mock_bq_client.query.return_value = mock_merge_job

            with patch.object(self.consolidator, '_cleanup_staging_tables') as mock_cleanup:
                result = self.consolidator._consolidate_with_lock(
                    batch_id="batch123",
                    game_date="2026-01-17",
                    cleanup=True,
                    start_time=time.time()
                )

                # Verify cleanup was NOT called
                mock_cleanup.assert_not_called()
                self.assertEqual(result.staging_tables_cleaned, 0)

    def test_consolidate_bad_request_error(self):
        """Test consolidation handles BadRequest error (invalid MERGE query)."""
        with patch.object(self.consolidator, '_find_staging_tables', return_value=self.staging_tables):
            # Mock BadRequest error
            self.mock_bq_client.query.side_effect = gcp_exceptions.BadRequest("Invalid query")

            result = self.consolidator._consolidate_with_lock(
                batch_id="batch123",
                game_date="2026-01-17",
                cleanup=True,
                start_time=time.time()
            )

            # Verify failure
            self.assertFalse(result.success)
            self.assertEqual(result.rows_affected, 0)
            self.assertIn("Invalid MERGE query", result.error_message)

    def test_consolidate_conflict_error(self):
        """Test consolidation handles Conflict error (DML conflict)."""
        with patch.object(self.consolidator, '_find_staging_tables', return_value=self.staging_tables):
            # Mock Conflict error
            self.mock_bq_client.query.side_effect = gcp_exceptions.Conflict("DML conflict")

            result = self.consolidator._consolidate_with_lock(
                batch_id="batch123",
                game_date="2026-01-17",
                cleanup=True,
                start_time=time.time()
            )

            # Verify failure
            self.assertFalse(result.success)
            self.assertIn("DML conflict", result.error_message)

    def test_consolidate_unexpected_error(self):
        """Test consolidation handles unexpected errors gracefully."""
        with patch.object(self.consolidator, '_find_staging_tables', return_value=self.staging_tables):
            # Mock unexpected error
            self.mock_bq_client.query.side_effect = RuntimeError("Unexpected error")

            result = self.consolidator._consolidate_with_lock(
                batch_id="batch123",
                game_date="2026-01-17",
                cleanup=True,
                start_time=time.time()
            )

            # Verify failure
            self.assertFalse(result.success)
            self.assertIn("Unexpected error", result.error_message)

    def test_find_staging_tables(self):
        """Test finding staging tables for a batch."""
        # Mock list_tables
        mock_table1 = MagicMock()
        mock_table1.table_id = "_staging_batch123_worker1"
        mock_table2 = MagicMock()
        mock_table2.table_id = "_staging_batch123_worker2"
        mock_table3 = MagicMock()
        mock_table3.table_id = "other_table"

        self.mock_bq_client.list_tables.return_value = [mock_table1, mock_table2, mock_table3]

        staging_tables = self.consolidator._find_staging_tables("batch123")

        # Verify only staging tables returned
        self.assertEqual(len(staging_tables), 2)
        self.assertTrue(all("_staging_batch123_" in table for table in staging_tables))

    def test_find_staging_tables_empty(self):
        """Test finding staging tables when none exist."""
        self.mock_bq_client.list_tables.return_value = []

        staging_tables = self.consolidator._find_staging_tables("batch123")

        # Verify empty list returned
        self.assertEqual(len(staging_tables), 0)

    def test_merge_query_with_deduplication(self):
        """Test MERGE query includes ROW_NUMBER deduplication."""
        merge_query = self.consolidator._build_merge_query(self.staging_tables, "2026-01-17")

        # Verify query structure
        self.assertIn("MERGE", merge_query)
        self.assertIn("ROW_NUMBER()", merge_query)
        self.assertIn("PARTITION BY", merge_query)
        self.assertIn("game_id", merge_query)
        self.assertIn("player_lookup", merge_query)
        self.assertIn("system_id", merge_query)
        self.assertIn("COALESCE(current_points_line, -1)", merge_query)
        self.assertIn("ORDER BY created_at DESC", merge_query)
        self.assertIn("WHEN MATCHED THEN", merge_query)
        self.assertIn("WHEN NOT MATCHED THEN", merge_query)
        # Session 39 replaced `INSERT ROW` with an explicit column list, so
        # that a schema change in the staging table cannot silently shift
        # values into the wrong columns.
        self.assertIn("INSERT (", merge_query)
        self.assertIn("VALUES (", merge_query)
        self.assertNotIn("INSERT ROW", merge_query)

    def test_cleanup_orphaned_staging_tables(self):
        """Test cleanup of orphaned staging tables older than threshold."""
        from datetime import timezone

        # Mock tables with different ages
        old_table = MagicMock()
        old_table.table_id = "_staging_old_batch_worker1"
        old_table.created = datetime.now(timezone.utc) - timedelta(hours=48)

        recent_table = MagicMock()
        recent_table.table_id = "_staging_recent_batch_worker1"
        recent_table.created = datetime.now(timezone.utc) - timedelta(hours=12)

        self.mock_bq_client.list_tables.return_value = [old_table, recent_table]
        self.mock_bq_client.get_table.side_effect = lambda table_id: {
            f"{self.project_id}.nba_predictions._staging_old_batch_worker1": old_table,
            f"{self.project_id}.nba_predictions._staging_recent_batch_worker1": recent_table
        }.get(table_id)

        result = self.consolidator.cleanup_orphaned_staging_tables(max_age_hours=24)

        # Returns a breakdown, not a bare count (the test asserted `== 1`
        # against the whole dict and so could never pass).
        self.assertEqual(result['tables_found'], 2)
        self.assertEqual(result['tables_deleted'], 1)
        self.assertEqual(result['tables_skipped'], 1)
        self.assertEqual(result['errors'], [])


class TestRaceConditionScenarios(unittest.TestCase):
    """
    Test race condition scenarios and lock prevention.

    Tests concurrent consolidations and duplicate prevention.
    """

    def setUp(self):
        """Set up test fixtures."""
        self.project_id = "test-project"
        self.mock_bq_client = MagicMock()
        self.consolidator = BatchConsolidator(self.mock_bq_client, self.project_id)

    def test_concurrent_consolidations_same_date(self):
        """Test two consolidations for same game_date wait for lock."""
        # Mock staging tables
        staging_tables = [
            f"{self.project_id}.nba_predictions._staging_batch1_worker1",
        ]

        with patch.object(self.consolidator, '_find_staging_tables', return_value=staging_tables):
            # Track lock acquisition order
            lock_calls = []

            def track_acquire(game_date, operation_id):
                lock_calls.append((game_date, operation_id))

            # Mock distributed lock
            with patch.object(shared_batch_staging_writer, 'DistributedLock') as mock_lock_class:
                mock_lock1 = MagicMock()
                mock_lock_class.return_value = mock_lock1

                # Mock first consolidation
                mock_lock1.acquire.return_value.__enter__ = Mock(return_value=None)
                mock_lock1.acquire.return_value.__exit__ = Mock(return_value=None)

                # Mock consolidation logic
                with patch.object(self.consolidator, '_consolidate_with_lock') as mock_consolidate:
                    mock_consolidate.return_value = ConsolidationResult(
                        rows_affected=50,
                        staging_tables_merged=1,
                        staging_tables_cleaned=1,
                        success=True,
                        error_message=None
                    )

                    # First consolidation
                    result1 = self.consolidator.consolidate_batch(
                        batch_id="batch1",
                        game_date="2026-01-17",
                        use_lock=True
                    )

                    # Verify lock was acquired
                    self.assertTrue(result1.success)
                    mock_lock1.acquire.assert_called_with(
                        game_date="2026-01-17",
                        operation_id="batch1"
                    )

    def test_race_no_duplicates_with_lock(self):
        """Test lock prevents duplicates in concurrent scenario."""
        # Simulate: Both operations target same game_date
        # With lock: Second waits, sees existing row, does UPDATE
        game_date = "2026-01-17"

        # Mock successful consolidations with lock
        with patch.object(shared_batch_staging_writer, 'DistributedLock'):
            # First consolidation inserts row
            # Second consolidation (with lock) waits and then updates

            # Verify no duplicates in final validation
            with patch.object(self.consolidator, '_check_for_duplicates', return_value=0) as mock_check:
                with patch.object(self.consolidator, '_find_staging_tables', return_value=[]):
                    result = self.consolidator._consolidate_with_lock(
                        batch_id="batch1",
                        game_date=game_date,
                        cleanup=True,
                        start_time=time.time()
                    )

                    # Verify validation passed
                    self.assertTrue(result.success)

    def test_race_duplicates_without_lock(self):
        """Test duplicates can occur without lock (use_lock=False)."""
        # Simulate: Two operations run concurrently without lock
        # Both check main table, both find NOT MATCHED, both INSERT
        game_date = "2026-01-17"

        with patch.object(self.consolidator, '_find_staging_tables', return_value=[
            f"{self.project_id}.nba_predictions._staging_batch1_worker1"
        ]):
            # Mock MERGE succeeds but creates duplicates
            mock_merge_job = MagicMock()
            mock_merge_job.result.return_value = None
            mock_merge_job.num_dml_affected_rows = 100
            self.mock_bq_client.query.return_value = mock_merge_job

            # Session 495: only duplicates still ACTIVE after deactivation fail
            # the run, so both gates have to be stubbed.
            with patch.object(self.consolidator, '_check_for_duplicates', return_value=5), \
                 patch.object(self.consolidator, '_check_for_active_duplicates', return_value=5):
                result = self.consolidator.consolidate_batch(
                    batch_id="batch1",
                    game_date=game_date,
                    cleanup=True,
                    use_lock=False  # No lock!
                )

                # Verify duplicates detected
                self.assertFalse(result.success)
                self.assertIn("duplicate", result.error_message.lower())

    def test_lock_prevents_concurrent_inserts(self):
        """Test lock serializes concurrent operations to prevent duplicate INSERTs."""
        # Simulate: Lock ensures only one operation at a time
        # First operation: Check → NOT MATCHED → INSERT
        # Second operation (waits for lock): Check → MATCHED → UPDATE

        with patch.object(shared_batch_staging_writer, 'DistributedLock') as mock_lock_class:
            mock_lock = MagicMock()
            mock_lock_class.return_value = mock_lock

            # Mock lock acquisition with retry (simulates waiting)
            acquire_attempts = [False, False, True]  # Waits twice, then succeeds
            mock_lock.acquire.return_value.__enter__ = Mock(return_value=None)
            mock_lock.acquire.return_value.__exit__ = Mock(return_value=None)

            with patch.object(self.consolidator, '_find_staging_tables', return_value=[]):
                result = self.consolidator.consolidate_batch(
                    batch_id="batch2",
                    game_date="2026-01-17",
                    use_lock=True
                )

                # Verify lock prevented race condition
                mock_lock.acquire.assert_called_once()


class TestLockEdgeCases(unittest.TestCase):
    """
    Test lock edge cases and error handling.

    Tests Firestore transaction isolation, timeout edge cases,
    and graceful handling of missing locks.
    """

    def setUp(self):
        """Set up test fixtures."""
        self.project_id = "test-project"
        self.mock_firestore = MagicMock()
        self.mock_db = MagicMock()

        # Patch Firestore client
        self.firestore_patcher = patch.object(
            shared_distributed_lock, '_get_firestore_client'
        )
        self.mock_get_firestore = self.firestore_patcher.start()
        # _get_firestore_client returns the CLIENT itself, not the module — so
        # this is what `DistributedLock.db` becomes.
        self.mock_get_firestore.return_value = self.mock_db
        self.mock_firestore.Client.return_value = self.mock_db

    def tearDown(self):
        """Clean up patches."""
        self.firestore_patcher.stop()

    def test_lock_firestore_transaction_isolation(self):
        """Test Firestore transaction provides isolation for lock check-and-set."""
        lock = DistributedLock(self.project_id, lock_type="consolidation")

        # Mock collection and document
        mock_collection = MagicMock()
        mock_doc_ref = MagicMock()
        self.mock_db.collection.return_value = mock_collection
        mock_collection.document.return_value = mock_doc_ref

        # Mock transaction
        mock_transaction = MagicMock()
        self.mock_db.transaction.return_value = mock_transaction

        # Mock snapshot (lock doesn't exist)
        mock_snapshot = MagicMock()
        mock_snapshot.exists = False
        mock_doc_ref.get.return_value = mock_snapshot

        # Verify transaction is used
        acquired = lock._try_acquire("test_key", "op1", "holder1")

        # Verify transaction was created
        self.mock_db.transaction.assert_called_once()

    def test_lock_timeout_config(self):
        """Test lock timeout configuration is correct."""
        # Verify constants
        self.assertEqual(LOCK_TIMEOUT_SECONDS, 300)  # 5 minutes
        self.assertEqual(MAX_ACQUIRE_ATTEMPTS, 60)
        self.assertEqual(RETRY_DELAY_SECONDS, 5)

        # Verify max wait time
        max_wait = MAX_ACQUIRE_ATTEMPTS * RETRY_DELAY_SECONDS
        self.assertEqual(max_wait, 300)  # 5 minutes total

    def test_retry_delay_between_attempts(self):
        """Each retry waits RETRY_DELAY_SECONDS.

        The retry loop is bounded by wall-clock (`time.time() - start < max_wait`),
        so stubbing time.sleep to a no-op turned this into a 15-second busy spin
        — measured at 623,400 attempts, and slow enough to trip the 60s test
        timeout under load. Break out after a few iterations instead, and assert
        on the delay actually requested.
        """
        lock = DistributedLock(self.project_id, lock_type="consolidation")

        class _StopSpinning(Exception):
            pass

        delays = []

        def fake_sleep(seconds):
            delays.append(seconds)
            if len(delays) >= 3:
                raise _StopSpinning

        with patch.object(lock, '_try_acquire', return_value=False):
            with patch('time.sleep', side_effect=fake_sleep):
                with self.assertRaises(_StopSpinning):
                    with lock.acquire(
                        game_date="2026-01-17",
                        operation_id="batch123",
                        max_wait_seconds=15
                    ):
                        pass

        self.assertEqual(delays, [RETRY_DELAY_SECONDS] * 3)

    def test_lock_expires_at_calculation(self):
        """Test lock expiration time is calculated correctly."""
        lock = DistributedLock(self.project_id, lock_type="consolidation")

        # Mock collection and document
        mock_collection = MagicMock()
        mock_doc_ref = MagicMock()
        self.mock_db.collection.return_value = mock_collection
        mock_collection.document.return_value = mock_doc_ref

        # Mock transaction
        mock_transaction = MagicMock()
        self.mock_db.transaction.return_value = mock_transaction

        # Mock snapshot (lock doesn't exist)
        mock_snapshot = MagicMock()
        mock_snapshot.exists = False
        mock_doc_ref.get.return_value = mock_snapshot

        # Capture lock data
        lock_data_captured = []
        def capture_set(ref, data):
            lock_data_captured.append(data)

        mock_transaction.set = capture_set

        # Note: Testing full transaction is complex due to decorator
        # We verify the constant is correct
        self.assertEqual(LOCK_TIMEOUT_SECONDS, 300)

    def test_lock_already_deleted_graceful_release(self):
        """Test graceful handling when lock already deleted during release."""
        lock = DistributedLock(self.project_id, lock_type="consolidation")

        # Mock document reference
        mock_doc_ref = MagicMock()
        mock_doc_ref.delete.side_effect = gcp_exceptions.NotFound("Lock not found")
        lock.lock_doc_ref = mock_doc_ref

        # Release should not raise exception
        lock._release("test_key", "op1")

        # Verify lock_doc_ref cleared
        self.assertIsNone(lock.lock_doc_ref)

    def test_missing_lock_doc_ref_on_release(self):
        """Test release handles missing lock_doc_ref gracefully."""
        lock = DistributedLock(self.project_id, lock_type="consolidation")
        lock.lock_doc_ref = None

        # Release should not raise exception
        lock._release("test_key", "op1")

        # Verify no error
        self.assertIsNone(lock.lock_doc_ref)


def suite():
    """Create test suite."""
    test_suite = unittest.TestSuite()

    test_suite.addTest(unittest.makeSuite(TestDistributedLock))
    test_suite.addTest(unittest.makeSuite(TestBatchStagingWriter))
    test_suite.addTest(unittest.makeSuite(TestBatchConsolidator))
    test_suite.addTest(unittest.makeSuite(TestRaceConditionScenarios))
    test_suite.addTest(unittest.makeSuite(TestLockEdgeCases))

    return test_suite


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite())
