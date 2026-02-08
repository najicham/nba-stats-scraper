"""
File: data_processors/precompute/base/precompute_base.py

Base class for Phase 4 precompute processors that handles:
 - Dependency checking (upstream data validation)
 - Source metadata tracking (audit trail)
 - Querying analytics BigQuery tables
 - Calculating precompute metrics
 - Loading to precompute tables
 - Error handling and quality tracking
 - Multi-channel notifications (Email + Slack)
 - Run history logging (via RunHistoryMixin)
 - Matches AnalyticsProcessorBase patterns

Version: 3.0 (refactored with extracted mixins)
Updated: 2026-01-25 - Extracted mixins to base/mixins/
"""

import logging
import os
from datetime import date
from typing import Dict, List, Optional
import sentry_sdk

# Import BigQuery connection pooling
from shared.clients.bigquery_pool import get_bigquery_client

# Import run history mixin
from shared.processors.mixins import RunHistoryMixin

# Import shared transform processor base class
from shared.processors.base import TransformProcessorBase

# Import analytics mixins (shared functionality)
from data_processors.analytics.mixins.dependency_mixin import DependencyMixin

# Import precompute base mixins (extracted for modularity)
from data_processors.precompute.base.mixins import (
    QualityMixin,
    MetadataMixin,
    TemporalMixin,
    DependencyCheckingMixin,
    OrchestrationHelpersMixin,
)

# Import precompute mixins
from data_processors.precompute.mixins.defensive_check_mixin import DefensiveCheckMixin
from data_processors.precompute.mixins.backfill_mode_mixin import BackfillModeMixin

# Import precompute operations
from data_processors.precompute.operations.bigquery_save_ops import BigQuerySaveOpsMixin
from data_processors.precompute.operations.failure_tracking import FailureTrackingMixin
from data_processors.precompute.operations.metadata_ops import PrecomputeMetadataOpsMixin

# Import soft dependency mixin for graceful degradation
try:
    from shared.processors.mixins.soft_dependency_mixin import SoftDependencyMixin
except ImportError:
    SoftDependencyMixin = object  # Fallback to empty object

# Import unified publisher for Phase 4→5 completion messages
from shared.publishers.unified_pubsub_publisher import UnifiedPubSubPublisher

# Import sport configuration for multi-sport support
from shared.config.sport_config import get_precompute_dataset, get_project_id

logger = logging.getLogger("precompute_base")


def _categorize_failure(error: Exception, step: str, stats: dict = None) -> str:
    """Categorize processor failure for monitoring. Returns category string."""
    error_type = type(error).__name__
    error_msg = str(error).lower()

    if error_type == 'ValueError' and step == 'initialization':
        if 'missing required option' in error_msg or 'missing' in error_msg:
            return 'configuration_error'

    no_data_patterns = ['no data loaded', 'no data available', 'no games scheduled',
                       'no records found', 'file not found', 'no data to process',
                       'empty response', 'no results', 'off-season', 'off season']
    if any(pattern in error_msg for pattern in no_data_patterns):
        return 'no_data_available'

    if error_type in ['FileNotFoundError', 'NoDataAvailableError', 'NoDataAvailableSuccess']:
        return 'no_data_available'

    dependency_patterns = ['dependency', 'upstream', 'missing dependency',
                          'stale dependency', 'dependency check failed']
    if any(pattern in error_msg for pattern in dependency_patterns):
        return 'upstream_failure'

    if error_type in ['DependencyError', 'UpstreamDependencyError', 'DataTooStaleError']:
        return 'upstream_failure'

    if any(p in error_msg for p in ['timeout', 'timed out', 'deadline exceeded']):
        return 'timeout'

    if error_type in ['TimeoutError', 'DeadlineExceeded']:
        return 'timeout'

    if 'bigquery' in error_msg or error_type.startswith('Google'):
        if 'streaming buffer' in error_msg:
            return 'no_data_available'
        return 'processing_error'

    return 'processing_error'


class PrecomputeProcessorBase(
    OrchestrationHelpersMixin,
    DependencyCheckingMixin,
    TemporalMixin,
    MetadataMixin,
    QualityMixin,
    PrecomputeMetadataOpsMixin,
    FailureTrackingMixin,
    BigQuerySaveOpsMixin,
    DefensiveCheckMixin,
    BackfillModeMixin,
    DependencyMixin,
    TransformProcessorBase,
    SoftDependencyMixin,
    RunHistoryMixin
):
    """
    Base class for Phase 4 precompute processors.

    Phase 4 processors depend on Phase 3 (Analytics) and other Phase 4 processors.
    This base class provides dependency checking, source tracking, and validation.

    Soft Dependencies:
    - Set use_soft_dependencies = True in child class to enable graceful degradation
    - Processors will proceed if coverage > 80% instead of all-or-nothing

    Lifecycle:
      1) Check dependencies (are upstream tables ready?)
      2) Extract data from analytics BigQuery tables
      3) Validate extracted data
      4) Calculate precompute metrics
      5) Load to precompute BigQuery tables
      6) Log processing run with source metadata

    Run History:
      Automatically logs runs to processor_run_history table via RunHistoryMixin.
    """

    # Class-level configs
    required_opts: List[str] = ['analysis_date']
    additional_opts: List[str] = []

    # Processing settings
    validate_on_extract: bool = True
    save_on_error: bool = True

    # Soft dependency settings
    use_soft_dependencies: bool = False  # Override in child class to enable
    soft_dependency_threshold: float = 0.80  # Minimum coverage to proceed (80%)

    # BigQuery settings - uses sport_config for multi-sport support
    dataset_id: str = None  # Will be set from sport_config in __init__
    table_name: str = ""  # Child classes must set
    date_column: str = "analysis_date"  # Column name for date partitioning
    processing_strategy: str = "MERGE_UPDATE"  # Default for precompute

    # Run history settings (from RunHistoryMixin)
    PHASE: str = 'phase_4_precompute'
    STEP_PREFIX: str = 'PRECOMPUTE_STEP'
    DEBUG_FILE_PREFIX: str = 'precompute_debug'
    OUTPUT_TABLE: str = ''  # Set to table_name in run()
    OUTPUT_DATASET: str = None  # Will be set from sport_config in __init__

    def __init__(self):
        """Initialize precompute processor."""
        super().__init__()

        # Initialize run history tracking from mixin
        self._init_run_history()

        # Precompute-specific source metadata tracking
        self.data_completeness_pct = 100.0
        self.dependency_check_passed = True
        self.upstream_data_age_hours = 0.0
        self.missing_dependencies_list = []

        # Write success tracking
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

        # Cached dependency check result
        self.dep_check = None

    def run(self, opts: Optional[Dict] = None) -> bool:
        """
        Main entry point - orchestrates preprocessing workflow.

        Returns:
            True on success, False on failure.
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

            # Normalize analysis_date early (from TemporalMixin)
            self._normalize_analysis_date()

            self._validate_and_normalize_backfill_flags()
            self.set_additional_opts()
            self.validate_additional_opts()
            self.init_clients()

            # Extract correlation tracking info
            self.correlation_id = opts.get('correlation_id') or self.run_id
            self.parent_processor = opts.get('parent_processor')
            self.trigger_message_id = opts.get('trigger_message_id')

            # Extract entities_changed for selective processing
            self.entities_changed = opts.get('entities_changed', [])
            if self.entities_changed:
                self.is_incremental_run = True
                logger.info(
                    f"INCREMENTAL RUN: Received {len(self.entities_changed)} changed entities"
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

            # Start heartbeat for stale processor detection
            self._start_heartbeat(data_date)

            # Log processor start to pipeline_event_log
            self._log_pipeline_start(data_date, opts)

            # Defensive checks: Upstream status + gap detection
            strict_mode = opts.get('strict_mode', True)
            analysis_date = opts.get('analysis_date')
            self._run_defensive_checks(analysis_date, strict_mode)

            # Check dependencies BEFORE extracting
            self.mark_time("dependency_check")
            skip_dep_check = opts.get('skip_dependency_check', False)

            if self.is_backfill_mode or skip_dep_check:
                self._handle_backfill_dependency_check(analysis_date, skip_dep_check)
            else:
                self.dep_check = self.check_dependencies(analysis_date)

                # Session 159: Retry with backoff when critical dependencies are missing.
                # Phase 4 cascade failures happen when Phase 3 isn't done yet (timing).
                # Instead of failing immediately, wait and retry up to 3 times.
                max_dep_retries = int(opts.get('dependency_retries', 3))
                dep_retry_base_seconds = int(opts.get('dependency_retry_base_seconds', 60))

                dep_retry_count = 0
                while (not self.dep_check['all_critical_present']
                       and not self.dep_check.get('is_early_season')
                       and dep_retry_count < max_dep_retries):
                    dep_retry_count += 1
                    wait_seconds = dep_retry_base_seconds * dep_retry_count  # 60s, 120s, 180s
                    missing = self.dep_check.get('missing', [])
                    logger.warning(
                        f"Missing critical dependencies: {missing}. "
                        f"Retry {dep_retry_count}/{max_dep_retries} in {wait_seconds}s..."
                    )
                    import time as _time
                    _time.sleep(wait_seconds)
                    self.dep_check = self.check_dependencies(analysis_date)

                if dep_retry_count > 0 and self.dep_check['all_critical_present']:
                    logger.info(
                        f"Dependencies resolved after {dep_retry_count} retries"
                    )

            dep_check_seconds = self.get_elapsed_seconds("dependency_check")
            self.stats["dependency_check_time"] = dep_check_seconds

            # Record dependency results for run history
            self.set_dependency_results(
                dependencies=[
                    {'table': k, **v} for k, v in self.dep_check.get('details', {}).items()
                ],
                all_passed=self.dep_check['all_critical_present'],
                missing=self.dep_check.get('missing', []),
                stale=self.dep_check.get('stale', [])
            )

            # Handle missing dependencies or early season
            if not self.dep_check['all_critical_present']:
                return self._handle_missing_dependencies()

            # Handle stale data warnings
            if not self.dep_check['all_fresh'] and not self.is_backfill_mode:
                self._warn_stale_data()

            # Track source metadata (from MetadataMixin)
            self.track_source_usage(self.dep_check)

            self.step_info("dependency_check_complete",
                          f"Dependencies validated in {dep_check_seconds:.1f}s")

            # Extract from analytics tables
            self.mark_time("extract")
            self.extract_raw_data()
            extract_seconds = self.get_elapsed_seconds("extract")
            self.stats["extract_time"] = extract_seconds
            self.step_info("extract_complete", f"Data extracted in {extract_seconds:.1f}s")

            # Check if early season skip was triggered
            if self.stats.get('processing_decision') == 'skipped_early_season':
                return self._complete_early_season_skip()

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
            self.step_info("finish", f"Precompute processor completed in {total_seconds:.1f}s")

            # Log processing run
            self.log_processing_run(success=True)
            self.post_process()

            # Record successful run to history
            self.record_run_complete(
                status='success',
                records_processed=self.stats.get('rows_processed', 0),
                records_created=self.stats.get('rows_processed', 0),
                summary=self.stats
            )

            # Log processor completion
            self._log_pipeline_complete(data_date, total_seconds)

            # Publish completion message to trigger Phase 5
            self._publish_completion_message(success=True)

            return True

        except Exception as e:
            logger.error("PrecomputeProcessorBase Error: %s", e, exc_info=True)
            sentry_sdk.capture_exception(e)

            # Categorize the failure
            current_step = self._get_current_step()
            failure_category = _categorize_failure(e, current_step, self.stats)

            # Send notification for real errors (skip expected failures)
            self._handle_failure_notification(e, failure_category, current_step, opts)

            # Log failed processing run
            self.log_processing_run(success=False, error=str(e))

            if self.save_on_error:
                self._save_partial_data(e)

            self.report_error(e)

            # Record failed run to history
            self.record_run_complete(
                status='failed',
                error=e,
                summary=self.stats,
                failure_category=failure_category
            )

            # Log processor error for retry
            self._log_pipeline_error(e, failure_category, opts)

            return False

        finally:
            # Stop heartbeat
            if self.heartbeat:
                try:
                    self.heartbeat.stop()
                except Exception as hb_ex:
                    logger.warning(f"Error stopping heartbeat: {hb_ex}")

            # Always run finalize
            try:
                self.finalize()
            except Exception as finalize_ex:
                logger.warning(f"Error in finalize(): {finalize_ex}")

    def finalize(self) -> None:
        """
        Cleanup hook that runs regardless of success/failure.
        Child classes override this for cleanup operations.
        """
        pass

    # =========================================================================
    # Dependency Checking System
    # =========================================================================

    def get_dependencies(self) -> dict:
        """
        Define required upstream tables and their constraints.
        Must be implemented by subclasses.

        Returns:
            dict: Dependency configuration
        """
        raise NotImplementedError("Child classes must implement get_dependencies()")

    def check_dependencies(self, analysis_date: date) -> dict:
        """
        Check if required upstream data exists and is fresh enough.

        Args:
            analysis_date: Date to check dependencies for

        Returns:
            dict: Dependency check results
        """
        if isinstance(analysis_date, str):
            analysis_date = self._parse_date_string(analysis_date)

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

            exists, details = self._check_table_data(
                table_name=table_name,
                analysis_date=analysis_date,
                config=config
            )

            if not exists:
                if config.get('critical', True):
                    results['all_critical_present'] = False
                    results['missing'].append(table_name)
                    logger.error(f"Missing critical dependency: {table_name}")
                else:
                    logger.warning(f"Missing optional dependency: {table_name}")

            if exists and details.get('age_hours') is not None:
                max_age = config.get('max_age_hours', 24)
                if details['age_hours'] > max_age:
                    results['all_fresh'] = False
                    stale_msg = f"{table_name}: {details['age_hours']:.1f}h old (max: {max_age}h)"
                    results['stale'].append(stale_msg)
                    logger.warning(f"Stale dependency: {stale_msg}")

            results['details'][table_name] = details

        # Check for early season (from TemporalMixin)
        self._check_early_season(analysis_date, results)

        return results

    # Helper methods moved to OrchestrationHelpersMixin:
    # - _handle_backfill_dependency_check()
    # - _handle_missing_dependencies()
    # - _warn_stale_data()
    # - _complete_early_season_skip()
    # - _start_heartbeat()
    # - _log_pipeline_start()
    # - _log_pipeline_complete()
    # - _handle_failure_notification()
    # - _log_pipeline_error()

    # =========================================================================
    # Abstract Method Implementations (Required by TransformProcessorBase)
    # =========================================================================

    def set_opts(self, opts: Dict) -> None:
        """Set processing options."""
        self.opts = opts
        self.opts["run_id"] = self.run_id

    def validate_opts(self) -> None:
        """Validate required options are present."""
        for required_opt in self.required_opts:
            if required_opt not in self.opts:
                raise ValueError(f"Missing required option: {required_opt}")

    def set_additional_opts(self) -> None:
        """Set additional options derived from main opts."""
        if "timestamp" not in self.opts:
            from datetime import datetime, timezone
            self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    def validate_additional_opts(self) -> None:
        """Validate additional options - child classes override if needed."""
        pass

    def init_clients(self) -> None:
        """Initialize GCP clients (BigQuery, Firestore, etc.)."""
        from shared.config.gcp_config import get_project_id
        self.project_id = self.opts.get("project_id") or get_project_id()
        self.bq_client = get_bigquery_client(project_id=self.project_id)

    def validate_extracted_data(self) -> None:
        """Validate extracted data - child classes override if needed."""
        if self.raw_data is None or (hasattr(self.raw_data, '__len__') and len(self.raw_data) == 0):
            raise ValueError("No data extracted")

    def log_processing_run(self, success: bool, error: str = None) -> None:
        """
        Log processing run to processor_run_history table.
        Run history is tracked via RunHistoryMixin.start_run_tracking()
        which is called in run() method.
        """
        # Run history logging is handled by RunHistoryMixin via start_run_tracking()
        # and is automatically recorded in the run() method
        pass

    def post_process(self) -> None:
        """
        Post-processing hook called after successful processing.
        Child classes override to publish completion messages, etc.
        """
        pass

    def _publish_completion_message(self, success: bool, error: str = None) -> None:
        """
        Publish unified completion message to nba-phase4-precompute-complete topic.
        This triggers Phase 5 prediction processors that depend on precompute data.

        Uses UnifiedPubSubPublisher for consistent message format across all phases.

        Args:
            success: Whether processing completed successfully
            error: Optional error message if failed
        """
        try:
            # Skip publishing in backfill mode to prevent triggering downstream
            if getattr(self, 'is_backfill', False) or self.opts.get('is_backfill', False):
                logger.info("⏸️  Skipping Phase 4 completion publish (backfill mode)")
                return

            # Skip if downstream trigger disabled
            if self.opts.get('skip_downstream_trigger', False):
                logger.info("⏸️  Skipping Phase 4 completion publish (skip_downstream_trigger=True)")
                return

            publisher = UnifiedPubSubPublisher(project_id=self.project_id)

            # Get the data date
            data_date = self.opts.get('data_date') or self.opts.get('end_date')
            if isinstance(data_date, date):
                data_date = data_date.strftime('%Y-%m-%d')

            # Determine status
            if success:
                status = 'success'
            elif error:
                status = 'failed'
            else:
                status = 'no_data'

            # Calculate duration
            duration_seconds = self.stats.get('total_runtime', 0)

            # Publish unified message
            message_id = publisher.publish_completion(
                topic='nba-phase4-precompute-complete',
                processor_name=self.__class__.__name__,
                phase='phase_4_precompute',
                execution_id=getattr(self, 'run_id', None) or self.correlation_id,
                correlation_id=self.correlation_id,
                game_date=str(data_date) if data_date else None,
                output_table=self.table_name,
                output_dataset=self.dataset_id,
                status=status,
                record_count=self.stats.get('rows_processed', 0),
                records_failed=0,
                parent_processor=getattr(self, 'parent_processor', None),
                trigger_source=self.opts.get('trigger_source', 'manual'),
                trigger_message_id=getattr(self, 'trigger_message_id', None),
                duration_seconds=duration_seconds,
                error_message=error,
                error_type=type(error).__name__ if error else None,
                metadata={
                    'total_runtime': duration_seconds,
                    'rows_processed': self.stats.get('rows_processed', 0),
                    'rows_skipped': self.stats.get('rows_skipped', 0),
                },
                skip_downstream=self.opts.get('skip_downstream_trigger', False)
            )

            if message_id:
                logger.info(
                    f"✅ Published Phase 4 completion message to nba-phase4-precompute-complete "
                    f"(message_id: {message_id}, correlation_id: {self.correlation_id})"
                )
            else:
                logger.info("⏸️  Skipped Phase 4 completion publish (publish returned None)")

        except Exception as e:
            # Don't fail the processor if publishing fails
            logger.warning(f"Failed to publish Phase 4 completion message: {e}", exc_info=True)
