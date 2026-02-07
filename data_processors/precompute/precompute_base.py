"""
Phase 4 Precompute Processor Base Class.

This module provides the abstract base class for Phase 4 precompute processors in the
NBA predictions pipeline. Phase 4 processors consume Phase 3 (Analytics) data and other
Phase 4 outputs to generate pre-aggregated metrics optimized for prediction.

Architecture Overview
---------------------
Phase 4 sits between Analytics (Phase 3) and Predictions (Phase 5):

    Phase 3 (Analytics) --> Phase 4 (Precompute) --> Phase 5 (Predictions)

Key responsibilities:
    - Dependency checking: Validate upstream data exists and is fresh
    - Source tracking: Record metadata for audit trail and debugging
    - Metrics calculation: Aggregate rolling windows, zone analysis, etc.
    - BigQuery persistence: MERGE/upsert to precompute tables
    - Failure tracking: Record entity-level failures for monitoring

Processing Lifecycle
-------------------
Each precompute processor follows this lifecycle:

    1. Dependency Check - Verify upstream tables have required data
    2. Extract - Query analytics BigQuery tables
    3. Validate - Check extracted data quality
    4. Calculate - Compute precompute metrics (abstract method)
    5. Save - MERGE to BigQuery precompute tables
    6. Log - Record run history and source metadata

Dependency Configuration
-----------------------
Child classes define dependencies via ``get_dependencies()``:

    def get_dependencies(self) -> dict:
        return {
            'nba_analytics.team_defense_game_summary': {
                'description': 'Team defensive stats',
                'date_field': 'game_date',
                'check_type': 'lookback',      # 'date_match', 'lookback', 'existence'
                'lookback_games': 15,
                'expected_count_min': 20,
                'max_age_hours': 24,
                'critical': True,              # Fail if missing?
                'field_prefix': 'tdgs'         # For source_* tracking fields
            }
        }

Soft Dependencies (Graceful Degradation)
---------------------------------------
Added after Jan 23 incident. When ``use_soft_dependencies = True``, processors can
proceed with degraded upstream data if coverage exceeds ``soft_dependency_threshold``
(default 80%). This prevents all-or-nothing blocking.

Implementing a Precompute Processor
-----------------------------------
Child classes must implement:

    - ``get_dependencies()`` - Define upstream table requirements
    - ``extract_raw_data()`` - Query upstream tables
    - ``calculate_precompute()`` - Transform data to output format

Optional overrides:
    - ``validate_extracted_data()`` - Custom validation logic
    - ``set_additional_opts()`` - Process additional options
    - ``finalize()`` - Cleanup after processing

Example::

    class TeamDefenseZoneAnalysisProcessor(PrecomputeProcessorBase):
        table_name = "team_defense_zone_analysis"
        PRIMARY_KEY_FIELDS = ['analysis_date', 'team_abbr']

        def get_dependencies(self):
            return {...}

        def extract_raw_data(self):
            # Query Phase 3 tables
            self.raw_data = self.bq_client.query(...).to_dataframe()

        def calculate_precompute(self):
            # Aggregate and transform
            self.transformed_data = [...]

Module Dependencies
------------------
This module integrates several mixins:
    - ``PrecomputeMetadataOpsMixin`` - Source tracking field generation
    - ``FailureTrackingMixin`` - Entity failure persistence
    - ``BigQuerySaveOpsMixin`` - MERGE/upsert operations
    - ``DefensiveCheckMixin`` - Upstream status validation
    - ``DependencyMixin`` - Dependency configuration
    - ``QualityMixin`` - Quality issue tracking
    - ``RunHistoryMixin`` - Run history logging

Version: 2.2 (with run history logging + multi-sport support)
Updated: November 2025
Updated: 2026-01-06 - Added multi-sport support via SportConfig
"""

import json
import logging
import os
import uuid
from datetime import datetime, date, timezone, timedelta
from typing import Dict, List, Optional
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded
import sentry_sdk

# Import retry utilities for resilient BigQuery operations
from shared.utils.retry_with_jitter import retry_with_jitter

# Import BigQuery connection pooling
from shared.clients.bigquery_pool import get_bigquery_client

# Import BigQuery batch writer for quota-efficient writes
from shared.utils.bigquery_batch_writer import get_batch_writer

# Import notification system
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Import run history mixin
from shared.processors.mixins import RunHistoryMixin

# Import shared transform processor base class
from shared.processors.base import TransformProcessorBase

# Import analytics mixins (shared functionality)
from data_processors.analytics.mixins.quality_mixin import QualityMixin
from data_processors.analytics.mixins.dependency_mixin import DependencyMixin

# Import precompute mixins
from data_processors.precompute.mixins.defensive_check_mixin import DefensiveCheckMixin

# Import precompute operations
from data_processors.precompute.operations.bigquery_save_ops import BigQuerySaveOpsMixin
from data_processors.precompute.operations.failure_tracking import FailureTrackingMixin
from data_processors.precompute.operations.metadata_ops import PrecomputeMetadataOpsMixin

# Import completeness checker and DependencyError for defensive checks
from shared.utils.completeness_checker import CompletenessChecker, DependencyError

# Import heartbeat system for stale processor detection (added after Jan 23 incident)
try:
    from shared.monitoring.processor_heartbeat import ProcessorHeartbeat
    HEARTBEAT_AVAILABLE = True
except ImportError:
    HEARTBEAT_AVAILABLE = False
    ProcessorHeartbeat = None

# Import pipeline logger for event tracking (added Jan 25 for resilience improvements)
try:
    from shared.utils.pipeline_logger import (
        log_processor_start,
        log_processor_complete,
        log_processor_error,
        mark_retry_succeeded,
        classify_error as classify_error_for_retry
    )
    PIPELINE_LOGGER_AVAILABLE = True
except ImportError:
    PIPELINE_LOGGER_AVAILABLE = False
    log_processor_start = None
    log_processor_complete = None
    log_processor_error = None
    mark_retry_succeeded = None
    classify_error_for_retry = None

# Import soft dependency mixin for graceful degradation (added after Jan 23 incident)
try:
    from shared.processors.mixins.soft_dependency_mixin import SoftDependencyMixin
    SOFT_DEPS_AVAILABLE = True
except ImportError:
    SOFT_DEPS_AVAILABLE = False
    SoftDependencyMixin = object  # Fallback to empty object

# Failure categorization (inlined to avoid cross-package dependency issues in Cloud Run)
def _categorize_failure(error: Exception, step: str, stats: dict = None) -> str:
    """
    Categorize a processor failure for monitoring and alerting.

    This function determines whether a failure is expected (no_data_available)
    or a real error (processing_error), enabling alert filtering to reduce
    noise by 90%+.

    Args:
        error: The exception that caused the failure
        step: Current processing step (initialization, load, transform, save)
        stats: Optional processor stats dict

    Returns:
        str: Failure category
            - 'no_data_available': Expected - no data to process
            - 'upstream_failure': Dependency failed or missing
            - 'processing_error': Real error in processing logic
            - 'timeout': Operation timed out
            - 'configuration_error': Missing required options
            - 'unknown': Unclassified error
    """
    error_type = type(error).__name__
    error_msg = str(error).lower()

    # Configuration errors
    if error_type == 'ValueError' and step == 'initialization':
        if 'missing required option' in error_msg or 'missing' in error_msg:
            return 'configuration_error'

    # No data available scenarios (EXPECTED - don't alert)
    no_data_patterns = [
        'no data loaded',
        'no data available',
        'no games scheduled',
        'no records found',
        'file not found',
        'no data to process',
        'empty response',
        'no results',
        'off-season',
        'off season',
    ]
    if any(pattern in error_msg for pattern in no_data_patterns):
        return 'no_data_available'

    if error_type in ['FileNotFoundError', 'NoDataAvailableError', 'NoDataAvailableSuccess']:
        return 'no_data_available'

    # Upstream/dependency failures
    dependency_patterns = [
        'dependency',
        'upstream',
        'missing dependency',
        'stale dependency',
        'dependency check failed',
    ]
    if any(pattern in error_msg for pattern in dependency_patterns):
        return 'upstream_failure'

    if error_type in ['DependencyError', 'UpstreamDependencyError', 'DataTooStaleError']:
        return 'upstream_failure'

    # Timeout errors
    timeout_patterns = [
        'timeout',
        'timed out',
        'deadline exceeded',
    ]
    if any(pattern in error_msg for pattern in timeout_patterns):
        return 'timeout'

    if error_type in ['TimeoutError', 'DeadlineExceeded']:
        return 'timeout'

    # BigQuery-specific errors
    if 'bigquery' in error_msg or error_type.startswith('Google'):
        if 'streaming buffer' in error_msg:
            return 'no_data_available'  # Transient, will self-heal
        return 'processing_error'

    # Default: real processing error (ALERT!)
    return 'processing_error'


# Import unified publishing
from shared.publishers.unified_pubsub_publisher import UnifiedPubSubPublisher

# Import season date utilities for early season detection
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date

# Import sport configuration for multi-sport support
from shared.config.sport_config import (
    get_precompute_dataset,
    get_analytics_dataset,
    get_project_id,
    get_current_sport,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger("precompute_base")


class PrecomputeProcessorBase(
    PrecomputeMetadataOpsMixin,
    FailureTrackingMixin,
    BigQuerySaveOpsMixin,
    DefensiveCheckMixin,
    DependencyMixin,
    QualityMixin,
    TransformProcessorBase,
    SoftDependencyMixin,
    RunHistoryMixin
):
    """
    Abstract base class for Phase 4 precompute processors.

    This class provides the complete processing lifecycle for precompute operations,
    including dependency validation, data extraction, transformation, and persistence.
    Child classes implement domain-specific calculation logic.

    Inheritance Hierarchy:
        PrecomputeProcessorBase inherits from multiple mixins that provide:

        - ``PrecomputeMetadataOpsMixin``: Source tracking fields (source_*_last_updated)
        - ``FailureTrackingMixin``: Entity-level failure recording
        - ``BigQuerySaveOpsMixin``: MERGE/upsert to BigQuery
        - ``DefensiveCheckMixin``: Upstream processor status validation
        - ``DependencyMixin``: Dependency configuration management
        - ``QualityMixin``: Quality issue tracking
        - ``TransformProcessorBase``: Core processor infrastructure
        - ``SoftDependencyMixin``: Graceful degradation support
        - ``RunHistoryMixin``: Run history logging

    Processing Lifecycle:
        The ``run()`` method orchestrates:

        1. **Dependency Check** - Validate upstream data via ``check_dependencies()``
        2. **Extract** - Call ``extract_raw_data()`` (abstract)
        3. **Validate** - Call ``validate_extracted_data()`` if enabled
        4. **Calculate** - Call ``calculate_precompute()`` (abstract)
        5. **Save** - Call ``save_precompute()`` to persist results
        6. **Log** - Record run history via ``RunHistoryMixin``

    Soft Dependencies:
        Added after Jan 23 incident to prevent all-or-nothing failures.
        When ``use_soft_dependencies = True``:

        - Processor proceeds if upstream coverage > ``soft_dependency_threshold`` (80%)
        - Degraded state is logged for monitoring
        - Prevents cascading failures in the pipeline

    Class Attributes:
        required_opts (List[str]): Options that must be provided (default: ['analysis_date'])
        additional_opts (List[str]): Optional extra options
        validate_on_extract (bool): Run validation after extract (default: True)
        save_on_error (bool): Attempt partial save on error (default: True)
        use_soft_dependencies (bool): Enable graceful degradation (default: False)
        soft_dependency_threshold (float): Minimum coverage to proceed (default: 0.80)
        dataset_id (str): BigQuery dataset (from sport_config if None)
        table_name (str): Target table name (child classes must set)
        date_column (str): Column for date partitioning (default: 'analysis_date')
        processing_strategy (str): Save strategy (default: 'MERGE_UPDATE')
        PHASE (str): Phase identifier for run history (default: 'phase_4_precompute')
        PRIMARY_KEY_FIELDS (List[str]): Fields for MERGE ON clause (child must define)

    Example:
        Implementing a precompute processor::

            class PlayerCompositeFactorsProcessor(PrecomputeProcessorBase):
                table_name = "player_composite_factors"
                PRIMARY_KEY_FIELDS = ['analysis_date', 'player_lookup']

                def get_dependencies(self):
                    return {
                        'nba_precompute.player_shot_zone_analysis': {
                            'description': 'Player zone metrics',
                            'date_field': 'analysis_date',
                            'check_type': 'date_match',
                            'expected_count_min': 300,
                            'max_age_hours': 24,
                            'critical': True,
                            'field_prefix': 'psza'
                        }
                    }

                def extract_raw_data(self):
                    query = '''SELECT * FROM nba_precompute.player_shot_zone_analysis
                               WHERE analysis_date = @date'''
                    self.raw_data = self.bq_client.query(query, ...).to_dataframe()

                def calculate_precompute(self):
                    # Transform raw_data to output format
                    self.transformed_data = [...]

    Run History:
        Automatically logs runs to ``processor_run_history`` table via RunHistoryMixin.
        Tracks: start time, duration, records processed, status, errors.

    See Also:
        - ``AnalyticsProcessorBase``: Similar base for Phase 3 processors
        - ``get_dependencies()``: How to configure upstream requirements
        - ``check_dependencies()``: Dependency validation logic
    """

    # Class-level configs
    required_opts: List[str] = ['analysis_date']
    additional_opts: List[str] = []

    # Processing settings
    validate_on_extract: bool = True
    save_on_error: bool = True

    # Soft dependency settings (added after Jan 23 incident)
    # When enabled, processor can proceed with degraded upstream data if coverage > threshold
    use_soft_dependencies: bool = False  # Override in child class to enable
    soft_dependency_threshold: float = 0.80  # Minimum coverage to proceed (80%)

    # BigQuery settings - now uses sport_config for multi-sport support
    dataset_id: str = None  # Will be set from sport_config in __init__
    table_name: str = ""  # Child classes must set
    date_column: str = "analysis_date"  # Column name for date partitioning (can override in child)
    processing_strategy: str = "MERGE_UPDATE"  # Default for precompute

    # Run history settings (from RunHistoryMixin)
    PHASE: str = 'phase_4_precompute'
    STEP_PREFIX: str = 'PRECOMPUTE_STEP'  # For structured logging
    DEBUG_FILE_PREFIX: str = 'precompute_debug'  # For debug file naming
    OUTPUT_TABLE: str = ''  # Set to table_name in run()
    OUTPUT_DATASET: str = None  # Will be set from sport_config in __init__
    
    def __init__(self):
        """
        Initialize precompute processor with GCP clients and tracking state.

        Sets up:
            - BigQuery client with connection pooling
            - Project ID from environment or sport_config
            - Dataset IDs for input/output tables
            - Source metadata tracking attributes
            - Dependency check state
            - Write success tracking for R-004 compliance

        Inherited Initialization:
            The parent ``TransformProcessorBase.__init__()`` sets:
            - opts, raw_data, validated_data, transformed_data
            - stats, time_markers, source_metadata, quality_issues
            - failed_entities, run_id, correlation_id
            - parent_processor, trigger_message_id
            - entities_changed, is_incremental_run, heartbeat
        """
        # Initialize base class (sets opts, raw_data, validated_data, transformed_data,
        # stats, time_markers, source_metadata, quality_issues, failed_entities, run_id,
        # correlation_id, parent_processor, trigger_message_id, entities_changed,
        # is_incremental_run, heartbeat, and stubs for project_id/bq_client)
        super().__init__()

        # Initialize run history tracking from mixin
        self._init_run_history()

        # Precompute-specific source metadata tracking
        self.data_completeness_pct = 100.0
        self.dependency_check_passed = True
        self.upstream_data_age_hours = 0.0
        self.missing_dependencies_list = []

        # Write success tracking (R-004: verify writes before publishing completion)
        # Set to False on write failures to prevent incorrect success messages
        self.write_success = True

        # GCP clients - specify location for regional dataset consistency
        bq_location = os.environ.get('BQ_LOCATION', 'us-west2')
        self.project_id = os.environ.get('GCP_PROJECT_ID', get_project_id())
        self.bq_client = get_bigquery_client(project_id=self.project_id, location=bq_location)

        # Set dataset from sport_config if not overridden by child class
        if self.dataset_id is None:
            self.dataset_id = get_precompute_dataset()
        if self.OUTPUT_DATASET is None:
            self.OUTPUT_DATASET = get_precompute_dataset()

        # Cached dependency check result (set in run(), used by extract_raw_data())
        self.dep_check = None

        # Distributed locking (Session 117b - prevent concurrent processing)
        self._processing_lock_id = None
        self._firestore_client = None

    def _get_firestore_client(self):
        """Lazy initialize Firestore client for distributed locking."""
        if self._firestore_client is None:
            from google.cloud import firestore
            self._firestore_client = firestore.Client(project=self.project_id)
        return self._firestore_client

    def acquire_processing_lock(self, game_date: str) -> bool:
        """
        Acquire distributed lock for processing a date.

        Session 117b: Added to prevent concurrent processing that causes
        MERGE failures and duplicate records.

        Args:
            game_date: Date being processed (YYYY-MM-DD format)

        Returns:
            True if lock acquired, False if another instance holds the lock
        """
        from google.cloud import firestore

        db = self._get_firestore_client()
        lock_id = f"{self.processor_name}_{game_date}"
        lock_ref = db.collection('processing_locks').document(lock_id)

        @firestore.transactional
        def try_acquire(transaction):
            lock_doc = lock_ref.get(transaction=transaction)

            if lock_doc.exists:
                lock_data = lock_doc.to_dict()
                acquired_at = lock_data.get('acquired_at')

                # Lock expired (older than 10 minutes)?
                if acquired_at and acquired_at < datetime.now(timezone.utc) - timedelta(minutes=10):
                    # Stale lock, acquire it
                    transaction.update(lock_ref, {
                        'acquired_at': firestore.SERVER_TIMESTAMP,
                        'execution_id': self.run_id,
                        'instance': os.environ.get('K_REVISION', 'local'),
                        'processor': self.processor_name
                    })
                    logging.info(f"Acquired stale lock for {game_date} (expired)")
                    return True
                else:
                    # Active lock held by another instance
                    logging.warning(
                        f"Cannot acquire lock for {game_date} - held by "
                        f"instance {lock_data.get('instance')} execution {lock_data.get('execution_id')}"
                    )
                    return False
            else:
                # No lock exists, create it
                transaction.set(lock_ref, {
                    'acquired_at': firestore.SERVER_TIMESTAMP,
                    'execution_id': self.run_id,
                    'instance': os.environ.get('K_REVISION', 'local'),
                    'processor': self.processor_name
                })
                logging.info(f"Acquired new lock for {game_date}")
                return True

        transaction = db.transaction()
        acquired = try_acquire(transaction)

        if acquired:
            self._processing_lock_id = lock_id

        return acquired

    def release_processing_lock(self):
        """
        Release distributed lock.

        Session 117b: Should be called in finally block to ensure cleanup.
        """
        if self._processing_lock_id is None:
            return

        try:
            db = self._get_firestore_client()
            db.collection('processing_locks').document(self._processing_lock_id).delete()
            logging.info(f"Released lock {self._processing_lock_id}")
        except Exception as e:
            logging.warning(f"Failed to release lock {self._processing_lock_id}: {e}")
        finally:
            self._processing_lock_id = None

    def run(self, opts: Optional[Dict] = None) -> bool:
        """
        Execute the complete precompute processing lifecycle.

        This is the main entry point for all precompute processors. It orchestrates
        the full processing lifecycle: dependency checking, extraction, validation,
        calculation, and persistence.

        Args:
            opts: Processing options dictionary. Required keys:
                - ``analysis_date`` (str or date): Date to process
                Optional keys:
                - ``skip_dependency_check`` (bool): Skip dependency validation
                - ``strict_mode`` (bool): Enable defensive checks (default: True)
                - ``correlation_id`` (str): For distributed tracing
                - ``parent_processor`` (str): Upstream processor name
                - ``trigger_message_id`` (str): Pub/Sub message ID
                - ``trigger_source`` (str): 'scheduled', 'manual', etc.
                - ``entities_changed`` (List[str]): For incremental processing
                - ``backfill`` (bool): Enable backfill mode (relaxed checks)

        Returns:
            bool: True if processing completed successfully, False on failure.

        Processing Steps:
            1. Re-initialize state (preserving run_id)
            2. Validate required options
            3. Run defensive checks (upstream status, gap detection)
            4. Check dependencies via ``check_dependencies()``
            5. Extract data via ``extract_raw_data()``
            6. Validate via ``validate_extracted_data()`` (if enabled)
            7. Calculate via ``calculate_precompute()``
            8. Save via ``save_precompute()``
            9. Log run history

        Error Handling:
            - Failures are logged to Sentry and run history
            - Notifications sent for real errors (not expected failures)
            - Partial data saved if ``save_on_error=True``
            - Failure category determines alerting behavior

        Early Exit Conditions:
            - Missing critical dependencies: Returns False (or True if early season)
            - No data to process: Returns True (expected condition)
            - Soft dependency degraded: Continues with warning

        Example:
            >>> processor = TeamDefenseZoneAnalysisProcessor()
            >>> success = processor.run({'analysis_date': '2026-01-15'})
            >>> print(f"Processed: {processor.stats.get('rows_processed', 0)} rows")
        """
        if opts is None:
            opts = {}

        try:
            # Re-init but preserve run_id
            saved_run_id = self.run_id
            self.__init__()
            self.run_id = saved_run_id
            self.stats["run_id"] = saved_run_id

            self.mark_time("total")
            self.step_info("start", "Precompute processor run starting", extra={"opts": opts})

            # Setup
            self.set_opts(opts)
            self.validate_opts()

            # Convert analysis_date string to date object early (before set_additional_opts)
            # This ensures all processors receive a proper date object, not a string
            if 'analysis_date' in self.opts and isinstance(self.opts['analysis_date'], str):
                self.opts['analysis_date'] = date.fromisoformat(self.opts['analysis_date'])

            self._validate_and_normalize_backfill_flags()  # Validate backfill flags early
            self.set_additional_opts()
            self.validate_additional_opts()
            self.init_clients()

            # Extract correlation tracking info from upstream message
            self.correlation_id = opts.get('correlation_id') or self.run_id
            self.parent_processor = opts.get('parent_processor')
            self.trigger_message_id = opts.get('trigger_message_id')

            # Extract entities_changed for selective processing (from Phase 3 orchestrator)
            self.entities_changed = opts.get('entities_changed', [])
            if self.entities_changed:
                self.is_incremental_run = True
                logger.info(
                    f"🎯 INCREMENTAL RUN: Received {len(self.entities_changed)} changed entities from upstream"
                )

            # Start run history tracking
            self.OUTPUT_TABLE = self.table_name
            self.OUTPUT_DATASET = self.dataset_id
            data_date = opts.get('analysis_date')
            self.start_run_tracking(
                data_date=data_date,
                trigger_source=opts.get('trigger_source', 'manual'),
                trigger_message_id=self.trigger_message_id,
                parent_processor=self.parent_processor
            )

            # Start heartbeat for stale processor detection (added after Jan 23 incident)
            # This enables 15-minute detection of stuck processors vs 4-hour timeout
            if HEARTBEAT_AVAILABLE:
                try:
                    self.heartbeat = ProcessorHeartbeat(
                        processor_name=self.processor_name,
                        run_id=self.run_id,
                        data_date=str(data_date) if data_date else None
                    )
                    self.heartbeat.start()
                    logger.debug(f"💓 Heartbeat started for {self.processor_name}")
                except (RuntimeError, OSError, ValueError) as e:
                    logger.warning(f"Failed to start heartbeat: {e}")
                    self.heartbeat = None

            # Log processor start to pipeline_event_log (added Jan 25 for resilience)
            self._pipeline_event_id = None
            if PIPELINE_LOGGER_AVAILABLE:
                try:
                    self._pipeline_event_id = log_processor_start(
                        phase='phase_4',
                        processor_name=self.processor_name,
                        game_date=str(data_date) if data_date else str(opts.get('analysis_date')),
                        correlation_id=self.correlation_id,
                        trigger_source=opts.get('trigger_source', 'scheduled')
                    )
                except Exception as log_ex:
                    logger.warning(f"Failed to log processor start: {log_ex}")

            # Session 117b: Acquire distributed lock to prevent concurrent processing
            # This prevents the duplicate record issues found in Session 116
            if not self.acquire_processing_lock(str(data_date)):
                logger.warning(
                    f"🔒 Cannot acquire processing lock for {data_date} - another instance is processing. "
                    f"This prevents concurrent processing duplicates (Session 116 prevention)."
                )
                # Mark run as skipped in run history
                if hasattr(self, 'complete_run_tracking'):
                    self.complete_run_tracking(
                        status='skipped',
                        status_message='Concurrent processing lock held by another instance',
                        records_processed=0,
                        records_created=0
                    )
                return True  # Return success to avoid retry loops
            logger.info(f"🔓 Acquired processing lock for {data_date}")

            # ═══════════════════════════════════════════════════════════════
            # DEFENSIVE CHECKS: Upstream Status + Gap Detection
            # ═══════════════════════════════════════════════════════════════
            # Enabled by strict_mode flag (default: enabled for production)
            # Checks for:
            #   1. Upstream processor failures (prevents processing with failed deps)
            #   2. Gaps in historical data (prevents processing with incomplete windows)
            # ═══════════════════════════════════════════════════════════════
            strict_mode = opts.get('strict_mode', True)  # Default: enabled
            analysis_date = opts.get('analysis_date')

            # Convert string to date object if needed
            if isinstance(analysis_date, str):
                analysis_date = date.fromisoformat(analysis_date)
                opts['analysis_date'] = analysis_date  # Update opts with date object

            self._run_defensive_checks(analysis_date, strict_mode)

            # Check dependencies BEFORE extracting
            # Cache result as self.dep_check for use in extract_raw_data()
            self.mark_time("dependency_check")

            # Skip dependency check in backfill mode OR if explicitly requested
            # BUT do a quick existence check to catch completely missing upstream data
            skip_dep_check = opts.get('skip_dependency_check', False)
            if self.is_backfill_mode or skip_dep_check:
                if skip_dep_check and not self.is_backfill_mode:
                    logger.info("⏭️  SKIP DEPENDENCY CHECK: Same-day prediction mode")
                # SAFETY: Quick existence check for critical Phase 4 dependencies
                # This catches cases like Dec 4, 2021 where TDZA was skipped between batches
                missing_upstream = self._quick_upstream_existence_check(analysis_date)
                if missing_upstream:
                    error_msg = f"⛔ BACKFILL SAFETY: Critical upstream data missing for {analysis_date}: {missing_upstream}"
                    logger.error(error_msg)
                    # Record this as a proper failure so it shows in validation
                    self._record_date_level_failure(
                        category='MISSING_UPSTREAM_IN_BACKFILL',
                        reason=f"Missing upstream tables: {', '.join(missing_upstream)}",
                        can_retry=True
                    )
                    raise ValueError(error_msg)

                if skip_dep_check and not self.is_backfill_mode:
                    logger.info("⏭️  SAME-DAY MODE: Skipping full dependency check (quick existence check passed)")
                else:
                    logger.info("⏭️  BACKFILL MODE: Skipping full dependency check (quick existence check passed)")
                self.dep_check = {
                    'all_critical_present': True,
                    'all_fresh': True,  # Don't care about freshness for historical data
                    'missing': [],
                    'stale': [],
                    'details': {},
                    'skipped_in_backfill': True
                }
            else:
                self.dep_check = self.check_dependencies(self.opts['analysis_date'])

            dep_check = self.dep_check  # Local reference for backward compatibility
            dep_check_seconds = self.get_elapsed_seconds("dependency_check")
            self.stats["dependency_check_time"] = dep_check_seconds

            # Record dependency results for run history
            self.set_dependency_results(
                dependencies=[
                    {'table': k, **v} for k, v in dep_check.get('details', {}).items()
                ],
                all_passed=dep_check['all_critical_present'],
                missing=dep_check.get('missing', []),
                stale=dep_check.get('stale', [])
            )

            if not dep_check['all_critical_present']:
                # Check if this is early season - if so, return success instead of failing
                if dep_check.get('is_early_season'):
                    logger.info(f"⏭️  Early season detected with missing dependencies - returning success (no data expected)")
                    self.stats['processing_decision'] = 'skipped_early_season'
                    self.stats['processing_decision_reason'] = dep_check.get('early_season_reason', 'early_season_missing_deps')
                    self.record_run_complete(
                        status='success',
                        records_processed=0,
                        records_created=0,
                        summary=self.stats
                    )
                    return True

                error_msg = f"Missing critical dependencies: {dep_check['missing']}"
                logger.error(error_msg)

                # Record date-level failure for observability
                # This allows validation to see WHY no records exist for this date
                self._record_date_level_failure(
                    category='MISSING_DEPENDENCIES',
                    reason=f"Missing: {', '.join(dep_check['missing'])}",
                    can_retry=True  # Can retry once dependencies are populated
                )

                # Skip notifications in backfill mode to avoid spamming
                if not self.is_backfill_mode:
                    notify_error(
                        title=f"Precompute Processor: Missing Dependencies - {self.__class__.__name__}",
                        message=error_msg,
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'analysis_date': str(self.opts['analysis_date']),
                            'missing': dep_check['missing'],
                            'stale': dep_check['stale'],
                            'dependency_details': dep_check['details']
                        },
                        processor_name=self.__class__.__name__
                    )
                    self.set_alert_sent('error')
                else:
                    logger.info(f"⏭️  BACKFILL MODE: Skipping notification for missing dependencies")
                raise ValueError(error_msg)

            if not dep_check['all_fresh']:
                logger.warning(f"Stale upstream data detected: {dep_check['stale']}")
                # Skip stale data warnings in backfill mode (expected during historical processing)
                if not self.is_backfill_mode:
                    notify_warning(
                        title=f"Precompute Processor: Stale Data - {self.__class__.__name__}",
                        message=f"Upstream data is stale: {dep_check['stale']}",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'analysis_date': str(self.opts['analysis_date']),
                            'stale_sources': dep_check['stale']
                        },
                        processor_name=self.__class__.__name__
                    )
                    self.set_alert_sent('warning')

            # Track source metadata from dependency check
            self.track_source_usage(dep_check)

            self.step_info("dependency_check_complete",
                          f"Dependencies validated in {dep_check_seconds:.1f}s")

            # Extract from analytics tables
            self.mark_time("extract")
            self.extract_raw_data()
            extract_seconds = self.get_elapsed_seconds("extract")
            self.stats["extract_time"] = extract_seconds
            self.step_info("extract_complete", f"Data extracted in {extract_seconds:.1f}s")

            # Check if early season skip was triggered - return success without further processing
            if self.stats.get('processing_decision') == 'skipped_early_season':
                logger.info(f"⏭️  Early season period - skipping validate/calculate/save steps")
                self.record_run_complete(
                    status='success',
                    records_processed=0,
                    records_created=0,
                    summary=self.stats
                )
                return True

            # Validate
            if self.validate_on_extract:
                self.validate_extracted_data()

            # Calculate precompute metrics
            self.mark_time("calculate")
            self.calculate_precompute()
            calculate_seconds = self.get_elapsed_seconds("calculate")
            self.stats["calculate_time"] = calculate_seconds

            # Save to precompute tables
            self.mark_time("save")
            self.save_precompute()
            save_seconds = self.get_elapsed_seconds("save")
            self.stats["save_time"] = save_seconds

            # Complete
            total_seconds = self.get_elapsed_seconds("total")
            self.stats["total_runtime"] = total_seconds
            self.step_info("finish",
                          f"Precompute processor completed in {total_seconds:.1f}s")

            # Log processing run
            self.log_processing_run(success=True)
            self.post_process()

            # Build timing breakdown for performance analysis (Session 143)
            _timing_breakdown = {
                'total_runtime': self.stats.get('total_runtime'),
                'extract_time': self.stats.get('extract_time'),
                'calculate_time': self.stats.get('calculate_time'),
                'save_time': self.stats.get('save_time'),
                'dependency_check_time': self.stats.get('dependency_check_time'),
            }
            # Include custom timing from processors (e.g., ML Feature Store's _timing dict)
            if hasattr(self, '_timing') and self._timing:
                _timing_breakdown['detail'] = self._timing
            # Remove None values
            _timing_breakdown = {k: v for k, v in _timing_breakdown.items() if v is not None}

            # Record successful run to history
            self.record_run_complete(
                status='success',
                records_processed=self.stats.get('rows_processed', 0),
                records_created=self.stats.get('rows_processed', 0),
                summary=self.stats,
                timing_breakdown=_timing_breakdown
            )

            # Log processor completion to pipeline_event_log (added Jan 25)
            if PIPELINE_LOGGER_AVAILABLE:
                try:
                    data_date = opts.get('analysis_date')
                    log_processor_complete(
                        phase='phase_4',
                        processor_name=self.processor_name,
                        game_date=str(data_date) if data_date else None,
                        duration_seconds=total_seconds,
                        records_processed=self.stats.get('rows_processed', 0),
                        correlation_id=self.correlation_id,
                        parent_event_id=getattr(self, '_pipeline_event_id', None)
                    )
                    # Clear any pending retry entries for this processor
                    mark_retry_succeeded(
                        phase='phase_4',
                        processor_name=self.processor_name,
                        game_date=str(data_date) if data_date else None
                    )
                except Exception as log_ex:
                    logger.warning(f"Failed to log processor complete: {log_ex}")

            return True

        except Exception as e:
            logger.error("PrecomputeProcessorBase Error: %s", e, exc_info=True)
            sentry_sdk.capture_exception(e)

            # Categorize the failure for monitoring/alerting
            current_step = self._get_current_step()
            failure_category = _categorize_failure(e, current_step, self.stats)
            logger.info(f"Failure categorized as: {failure_category} (step={current_step})")

            # Send notification for failure (skip in backfill mode to avoid spam)
            # Also skip notification for expected failures (no_data_available)
            should_alert = failure_category in ['processing_error', 'configuration_error', 'timeout']

            if not self.is_backfill_mode and should_alert:
                try:
                    notify_error(
                        title=f"Precompute Processor Failed: {self.__class__.__name__}",
                        message=f"Precompute calculation failed: {str(e)}",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'error_type': type(e).__name__,
                            'failure_category': failure_category,
                            'step': current_step,
                            'analysis_date': str(opts.get('analysis_date')),
                            'table': self.table_name,
                            'stats': self.stats
                        },
                        processor_name=self.__class__.__name__
                    )
                    self.set_alert_sent('error')
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            elif not should_alert:
                logger.info(f"Skipping alert for expected failure: {failure_category}")

            # Log failed processing run
            self.log_processing_run(success=False, error=str(e))

            if self.save_on_error:
                self._save_partial_data(e)

            self.report_error(e)

            # Record failed run to history with failure category
            self.record_run_complete(
                status='failed',
                error=e,
                summary=self.stats,
                failure_category=failure_category
            )

            # Log processor error to pipeline_event_log (added Jan 25)
            # Only log transient errors to retry queue, not expected failures
            if PIPELINE_LOGGER_AVAILABLE:
                try:
                    data_date = opts.get('analysis_date')
                    error_type_for_retry = classify_error_for_retry(e) if classify_error_for_retry else 'transient'

                    # Only queue for retry if it's a real error (not no_data_available)
                    if failure_category in ['processing_error', 'timeout', 'upstream_failure']:
                        import traceback
                        log_processor_error(
                            phase='phase_4',
                            processor_name=self.processor_name,
                            game_date=str(data_date) if data_date else None,
                            error_message=str(e),
                            error_type=error_type_for_retry,
                            stack_trace=traceback.format_exc(),
                            correlation_id=self.correlation_id,
                            parent_event_id=getattr(self, '_pipeline_event_id', None)
                        )
                except Exception as log_ex:
                    logger.warning(f"Failed to log processor error: {log_ex}")

            return False

        finally:
            # Stop heartbeat regardless of success/failure
            if self.heartbeat:
                try:
                    self.heartbeat.stop()
                    logger.debug(f"💓 Heartbeat stopped for {self.processor_name}")
                except Exception as hb_ex:
                    logger.warning(f"Error stopping heartbeat: {hb_ex}")

            # Session 117b: Release distributed lock (always, even on failure)
            try:
                self.release_processing_lock()
            except Exception as lock_ex:
                logger.warning(f"Error releasing processing lock: {lock_ex}")

            # Always run finalize, even on error
            try:
                self.finalize()
            except Exception as finalize_ex:
                logger.warning(f"Error in finalize(): {finalize_ex}")

    def finalize(self) -> None:
        """
        Cleanup hook called after processing completes.

        This method runs in the ``finally`` block of ``run()``, regardless of
        whether processing succeeded or failed. Use it for cleanup operations
        like closing connections or flushing buffers.

        Override in child classes to add custom cleanup logic. Always call
        ``super().finalize()`` to maintain the chain.

        Example:
            >>> def finalize(self):
            ...     # Flush any buffered failure records
            ...     self.save_failures_to_bq()
            ...     super().finalize()
        """
        pass

    # Note: _get_current_step() is inherited from TransformProcessorBase

    # =========================================================================
    # Dependency Checking System
    # =========================================================================
    
    def get_dependencies(self) -> dict:
        """
        Define required upstream tables and their validation constraints.

        This abstract method must be implemented by all child classes. It declares
        which upstream tables are required, how to validate their completeness,
        and the acceptable staleness thresholds.

        Returns:
            dict: Dependency configuration keyed by fully-qualified table name.
                Each entry contains:

                - ``description`` (str): Human-readable description
                - ``date_field`` (str): Column to check for date filtering
                - ``check_type`` (str): Validation strategy:
                    - ``'date_match'``: Exact date match required
                    - ``'lookback'``: Rolling window (last N games)
                    - ``'existence'``: Any data exists
                    - ``'per_player_game_count'``: Per-entity game counts
                - ``expected_count_min`` (int): Minimum required rows
                - ``max_age_hours`` (int): Maximum acceptable data age
                - ``critical`` (bool): If True, fail on missing. If False, warn only.
                - ``field_prefix`` (str): Prefix for source tracking fields
                    (e.g., 'tdgs' -> 'source_tdgs_last_updated')
                - ``lookback_games`` (int, optional): For 'lookback' check_type
                - ``wait_for_processor`` (str, optional): Name of Phase 4 processor
                    that must complete first

        Example:
            Team Defense Zone Analysis processor depends on Phase 3 data::

                def get_dependencies(self):
                    return {
                        'nba_analytics.team_defense_game_summary': {
                            'description': 'Team defensive stats from last 15 games',
                            'date_field': 'game_date',
                            'check_type': 'lookback',
                            'lookback_games': 15,
                            'expected_count_min': 20,
                            'max_age_hours': 24,
                            'critical': True,
                            'field_prefix': 'tdgs'
                        }
                    }

            ML Feature Store depends on other Phase 4 processors::

                def get_dependencies(self):
                    return {
                        'nba_precompute.player_shot_zone_analysis': {
                            'description': 'Player zone analysis',
                            'date_field': 'analysis_date',
                            'check_type': 'date_match',
                            'expected_count_min': 300,
                            'max_age_hours': 4,
                            'critical': True,
                            'field_prefix': 'psza',
                            'wait_for_processor': 'PlayerShotZoneAnalysisProcessor'
                        },
                        'nba_precompute.team_defense_zone_analysis': {
                            'description': 'Team defense analysis',
                            'date_field': 'analysis_date',
                            'check_type': 'date_match',
                            'expected_count_min': 25,
                            'max_age_hours': 4,
                            'critical': True,
                            'field_prefix': 'tdza'
                        }
                    }

        Raises:
            NotImplementedError: Must be implemented by child classes.

        See Also:
            - ``check_dependencies()``: Validates these configurations
            - ``track_source_usage()``: Records metadata from dependency check
        """
        raise NotImplementedError("Child classes must implement get_dependencies()")
    
    def check_dependencies(self, analysis_date: date) -> dict:
        """
        Validate that upstream data exists and meets freshness requirements.

        Iterates through dependencies defined by ``get_dependencies()`` and checks
        each table for existence, row counts, and data freshness. Results inform
        whether processing should proceed.

        Args:
            analysis_date: Date to check dependencies for. Accepts date object or
                ISO format string (YYYY-MM-DD).

        Returns:
            dict: Dependency check results with keys:
                - ``all_critical_present`` (bool): All critical deps have data
                - ``all_fresh`` (bool): No deps exceed max_age_hours
                - ``missing`` (List[str]): Table names with missing/insufficient data
                - ``stale`` (List[str]): Table names exceeding freshness threshold
                - ``details`` (Dict[str, Dict]): Per-table check results:
                    - ``exists`` (bool): Has minimum required rows
                    - ``row_count`` (int): Actual row count found
                    - ``expected_count_min`` (int): Required minimum
                    - ``age_hours`` (float): Hours since last update
                    - ``last_updated`` (str): ISO timestamp of last update
                - ``is_early_season`` (bool, optional): True if in bootstrap period
                - ``early_season_reason`` (str, optional): Explanation

        Early Season Handling:
            During the first 14 days of an NBA season (bootstrap period), missing
            dependencies are expected. The result includes ``is_early_season=True``
            which allows ``run()`` to return success instead of failing.

        Example:
            >>> dep_check = processor.check_dependencies(date(2026, 1, 15))
            >>> if not dep_check['all_critical_present']:
            ...     print(f"Missing: {dep_check['missing']}")
            >>> if not dep_check['all_fresh']:
            ...     print(f"Stale: {dep_check['stale']}")

        See Also:
            - ``get_dependencies()``: Defines what to check
            - ``_check_table_data()``: Individual table validation
        """
        # Ensure analysis_date is a date object, not a string
        if isinstance(analysis_date, str):
            analysis_date = datetime.strptime(analysis_date, '%Y-%m-%d').date()

        dependencies = self.get_dependencies()
        
        results = {
            'all_critical_present': True,
            'all_fresh': True,
            'missing': [],
            'stale': [],
            'details': {}
        }
        
        for table_name, config in dependencies.items():
            logger.info(f"Checking dependency: {table_name}")
            
            # Check existence and metadata
            exists, details = self._check_table_data(
                table_name=table_name,
                analysis_date=analysis_date,
                config=config
            )
            
            # Check if missing
            if not exists:
                if config.get('critical', True):
                    results['all_critical_present'] = False
                    results['missing'].append(table_name)
                    logger.error(f"Missing critical dependency: {table_name}")
                else:
                    logger.warning(f"Missing optional dependency: {table_name}")
            
            # Check freshness (if exists)
            if exists and details.get('age_hours') is not None:
                max_age = config.get('max_age_hours', 24)
                if details['age_hours'] > max_age:
                    results['all_fresh'] = False
                    stale_msg = (f"{table_name}: {details['age_hours']:.1f}h old "
                               f"(max: {max_age}h)")
                    results['stale'].append(stale_msg)
                    logger.warning(f"Stale dependency: {stale_msg}")
            
            results['details'][table_name] = details

        # Check if this is early season (first 14 days) - processors may skip during this period
        # This flag helps run() return success instead of failing on missing deps during bootstrap
        try:
            season_year = get_season_year_from_date(analysis_date)
            early_season = is_early_season(analysis_date, season_year, days_threshold=14)
            if early_season:
                results['is_early_season'] = True
                results['early_season_reason'] = f'bootstrap_period_first_14_days_of_season_{season_year}'
        except Exception as e:
            logger.debug(f"Could not determine early season status: {e}")

        logger.info(f"Dependency check complete: "
                   f"critical_present={results['all_critical_present']}, "
                   f"fresh={results['all_fresh']}")

        return results
    
    def _check_table_data(self, table_name: str, analysis_date: date,
                          config: dict) -> tuple:
        """
        Check if a specific upstream table has sufficient data.

        Executes a BigQuery query based on the ``check_type`` configuration to
        validate data existence, row counts, and freshness.

        Args:
            table_name: Fully-qualified BigQuery table name
                (e.g., 'nba_analytics.team_defense_game_summary').
            analysis_date: Date to check data for.
            config: Dependency configuration from ``get_dependencies()``.
                Required keys: ``check_type``, ``date_field``.
                Optional keys: ``lookback_games``, ``expected_count_min``,
                ``entity_field``, ``min_games_required``.

        Returns:
            tuple: (exists, details) where:
                - ``exists`` (bool): True if row_count >= expected_count_min
                - ``details`` (dict): Check results:
                    - ``exists`` (bool): Same as return value
                    - ``row_count`` (int): Rows found
                    - ``expected_count_min`` (int): Minimum required
                    - ``age_hours`` (float or None): Hours since last update
                    - ``last_updated`` (str or None): ISO timestamp
                    - ``error`` (str, optional): Error message if check failed

        Check Types:
            - ``date_match``: COUNT(*) WHERE date_field = analysis_date
            - ``lookback``: COUNT(*) for last N games (by date)
            - ``existence``: COUNT(*) LIMIT 1 (any data exists)
            - ``per_player_game_count``: COUNT by entity over date range
        """
        check_type = config.get('check_type', 'date_match')
        date_field = config.get('date_field', 'game_date')

        # Validate project_id before constructing BigQuery queries
        if not hasattr(self, 'project_id') or not self.project_id:
            logger.warning(f"project_id not initialized - cannot check table data for {table_name}")
            return False, {
                'exists': False,
                'row_count': 0,
                'age_hours': None,
                'last_updated': None,
                'error': 'project_id not initialized'
            }

        try:
            if check_type == 'date_match':
                # Check for exact date match
                query = f"""
                SELECT 
                    COUNT(*) as row_count,
                    MAX(processed_at) as last_updated
                FROM `{self.project_id}.{table_name}`
                WHERE {date_field} = '{analysis_date}'
                """
                
            elif check_type == 'lookback':
                # Check for rolling window (e.g., last 15 games)
                lookback_games = config.get('lookback_games', 10)
                # Approximate: lookback_games * 30 teams (for team data)
                # or lookback_games * 450 players (for player data)
                limit = lookback_games * 100  # Conservative estimate
                
                query = f"""
                SELECT 
                    COUNT(*) as row_count,
                    MAX(processed_at) as last_updated
                FROM (
                    SELECT * 
                    FROM `{self.project_id}.{table_name}`
                    WHERE {date_field} <= '{analysis_date}'
                    ORDER BY {date_field} DESC
                    LIMIT {limit}
                )
                """
                
            elif check_type == 'existence':
                # Just check if any data exists
                query = f"""
                SELECT
                    COUNT(*) as row_count,
                    MAX(processed_at) as last_updated
                FROM `{self.project_id}.{table_name}`
                LIMIT 1
                """
            elif check_type == 'per_player_game_count':
                # Check for player-level game counts (used by player_shot_zone_analysis)
                # Simplified check: just verify data exists for the date range
                entity_field = config.get('entity_field', 'player_lookup')
                min_games = config.get('min_games_required', 10)
                lookback_days = min_games * 2  # Approximate days for min_games
                query = f"""
                SELECT
                    COUNT(*) as row_count,
                    COUNT(DISTINCT {entity_field}) as players_found,
                    MAX(processed_at) as last_updated
                FROM `{self.project_id}.{table_name}`
                WHERE {date_field} >= DATE_SUB('{analysis_date}', INTERVAL {lookback_days} DAY)
                  AND {date_field} <= '{analysis_date}'
                """
            else:
                raise ValueError(f"Unknown check_type: {check_type}")

            # Execute query with timeout
            # Use shorter timeout in backfill mode to fail fast on connectivity issues
            query_timeout = 60 if self.is_backfill_mode else 300  # 60s for backfill, 5min otherwise
            query_job = self.bq_client.query(query)
            result = list(query_job.result(timeout=query_timeout))
            
            if not result:
                return False, {
                    'exists': False,
                    'row_count': 0,
                    'age_hours': None,
                    'last_updated': None,
                    'error': 'No query results'
                }
            
            row = result[0]
            row_count = row.row_count
            last_updated = row.last_updated

            # Calculate age using timezone-aware datetime
            # BQ returns tz-aware timestamps, so use datetime.now(timezone.utc) for comparison
            if last_updated:
                # Ensure last_updated is timezone-aware (add UTC if naive)
                if last_updated.tzinfo is None:
                    last_updated = last_updated.replace(tzinfo=timezone.utc)
                age_hours = (datetime.now(timezone.utc) - last_updated).total_seconds() / 3600
            else:
                age_hours = None
            
            # Determine if exists based on minimum count
            expected_min = config.get('expected_count_min', 1)
            exists = row_count >= expected_min
            
            details = {
                'exists': exists,
                'row_count': row_count,
                'expected_count_min': expected_min,
                'age_hours': round(age_hours, 2) if age_hours else None,
                'last_updated': last_updated.isoformat() if last_updated else None
            }
            
            logger.debug(f"{table_name}: {details}")
            
            return exists, details

        except GoogleAPIError as e:
            error_msg = f"Error checking {table_name}: {str(e)}"
            logger.error(error_msg)
            return False, {
                'exists': False,
                'error': error_msg
            }
    def _format_missing_deps(self) -> Optional[str]:
        """
        Format missing dependencies list as comma-separated string.

        Used when recording processing failures to database. Converts the
        ``missing_dependencies_list`` attribute to a storage-friendly format.

        Returns:
            Optional[str]: Comma-separated table names, or None if no missing deps.

        Example:
            >>> processor.missing_dependencies_list = ['table_a', 'table_b']
            >>> processor._format_missing_deps()
            'table_a, table_b'
        """
        if not self.missing_dependencies_list:
            return None
        return ", ".join(self.missing_dependencies_list)

    # =========================================================================
    # Backfill mode methods inherited from BackfillModeMixin
    # - is_backfill_mode (property)
    # - _validate_and_normalize_backfill_flags()


    def _record_date_level_failure(self, category: str, reason: str, can_retry: bool = True) -> None:
        """
        Record a date-level processing failure to BigQuery.

        Use this method when an entire date fails to process (e.g., missing dependencies),
        as opposed to individual entity failures. This creates visibility into why no
        records exist for a particular date, enabling targeted backfills.

        Args:
            category: Failure category. Standard values:
                - ``'MISSING_DEPENDENCY'``: Upstream data not available
                - ``'MINIMUM_THRESHOLD_NOT_MET'``: Too few upstream records
                - ``'MISSING_UPSTREAM_IN_BACKFILL'``: Phase 4 deps missing in backfill
                - ``'PROCESSING_ERROR'``: Actual error during processing
            reason: Detailed explanation of the failure (max 1000 chars).
            can_retry: Whether reprocessing might succeed later.
                Set True if dependencies will be populated.

        Side Effects:
            Writes a record to ``nba_processing.precompute_failures`` with:
            - ``entity_id``: 'DATE_LEVEL' (marker for date-level failures)
            - ``processor_name``: This processor's class name
            - ``analysis_date``: Date that failed
            - ``failure_category``: Standardized category
            - ``failure_reason``: Detailed reason
            - ``can_retry``: Retry eligibility flag

        Note:
            Uses ``BigQueryBatchWriter`` for quota-efficient writes.
            Category 'MISSING_DEPENDENCIES' is auto-normalized to singular form.
        """
        try:
            table_id = f"{self.project_id}.nba_processing.precompute_failures"
            analysis_date = self.opts.get('analysis_date')

            # Convert date to string for BQ DATE type
            if hasattr(analysis_date, 'isoformat'):
                date_str = analysis_date.isoformat()
            else:
                date_str = str(analysis_date)

            # Standardize category naming (singular form)
            if category == 'MISSING_DEPENDENCIES':
                category = 'MISSING_DEPENDENCY'

            failure_record = {
                'processor_name': self.__class__.__name__,
                'run_id': self.run_id,
                'analysis_date': date_str,
                'entity_id': 'DATE_LEVEL',  # Special marker for date-level failures
                'failure_category': category,
                'failure_reason': str(reason)[:1000],
                'can_retry': can_retry,
                'created_at': datetime.now(timezone.utc).isoformat()
            }

            # Use BigQueryBatchWriter for quota-efficient writes
            # This uses streaming inserts to bypass load job quota limits
            # See docs/05-development/guides/bigquery-best-practices.md
            writer = get_batch_writer(table_id)
            writer.add_record(failure_record)

            logger.info(f"Recorded date-level failure: {category} - {reason[:50]}...")

        except GoogleAPIError as e:
            logger.warning(f"Failed to record date-level failure: {e}")

    # Metadata operations extracted to operations/metadata_ops.py
    # - build_source_tracking_fields()
    # - _calculate_expected_count()
    # - track_source_usage()
