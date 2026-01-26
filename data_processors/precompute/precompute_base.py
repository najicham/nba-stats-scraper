"""
File: data_processors/precompute/precompute_base.py

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


class PrecomputeProcessorBase(PrecomputeMetadataOpsMixin, FailureTrackingMixin, BigQuerySaveOpsMixin, DependencyMixin, QualityMixin, TransformProcessorBase, SoftDependencyMixin, RunHistoryMixin):
    """
    Base class for Phase 4 precompute processors.

    Phase 4 processors depend on Phase 3 (Analytics) and other Phase 4 processors.
    This base class provides dependency checking, source tracking, and validation.

    Soft Dependencies (added after Jan 23 incident):
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
        """Initialize precompute processor."""
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

    def run(self, opts: Optional[Dict] = None) -> bool:
        """
        Main entry point - matches AnalyticsProcessorBase.run() pattern.
        Returns True on success, False on failure.
        Enhanced with run history logging.
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
                        }
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

            # Record successful run to history
            self.record_run_complete(
                status='success',
                records_processed=self.stats.get('rows_processed', 0),
                records_created=self.stats.get('rows_processed', 0),
                summary=self.stats
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

            # Always run finalize, even on error
            try:
                self.finalize()
            except Exception as finalize_ex:
                logger.warning(f"Error in finalize(): {finalize_ex}")

    def finalize(self) -> None:
        """
        Cleanup hook that runs regardless of success/failure.
        Child classes override this for cleanup operations.
        Base implementation does nothing.
        """
        pass

    # Note: _get_current_step() is inherited from TransformProcessorBase

    # =========================================================================
    # Dependency Checking System
    # =========================================================================
    
    def get_dependencies(self) -> dict:
        """
        Define required upstream tables and their constraints.
        Must be implemented by subclasses.
        
        Returns:
            dict: {
                'table_name': {
                    'description': str,           # Human-readable description
                    'date_field': str,            # Field to check for date
                    'check_type': str,            # 'date_match', 'lookback', 'existence'
                    'expected_count_min': int,    # Minimum acceptable rows
                    'max_age_hours': int,         # Maximum data staleness (hours)
                    'critical': bool,             # Fail if missing?
                    'lookback_games': int,        # (optional) For rolling windows
                    'wait_for_processor': str     # (optional) Phase 4 processor dependency
                }
            }
        
        Example:
            return {
                'nba_analytics.team_defense_game_summary': {
                    'description': 'Team defensive stats from last 15 games',
                    'date_field': 'game_date',
                    'check_type': 'lookback',
                    'lookback_games': 15,
                    'expected_count_min': 20,
                    'max_age_hours': 24,
                    'critical': True
                }
            }
        """
        raise NotImplementedError("Child classes must implement get_dependencies()")
    
    def check_dependencies(self, analysis_date: date) -> dict:
        """
        Check if required upstream data exists and is fresh enough.

        Args:
            analysis_date: Date to check dependencies for (can be string or date)

        Returns:
            dict: {
                'all_critical_present': bool,
                'all_fresh': bool,
                'missing': List[str],
                'stale': List[str],
                'details': Dict[str, Dict]
            }
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
        Check if table has data for the given date.
        
        Returns:
            (exists: bool, details: dict)
        """
        check_type = config.get('check_type', 'date_match')
        date_field = config.get('date_field', 'game_date')
        
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
        """Format missing dependencies for database storage."""
        if not self.missing_dependencies_list:
            return None
        return ", ".join(self.missing_dependencies_list)

    # =========================================================================
    # Backfill mode methods inherited from BackfillModeMixin
    # - is_backfill_mode (property)
    # - _validate_and_normalize_backfill_flags()
    def _run_defensive_checks(self, analysis_date: date, strict_mode: bool) -> None:
        """
        Run defensive checks to prevent processing with incomplete upstream data.

        Defensive checks validate that upstream Phase 3 (and Phase 4) processors
        completed successfully and that there are no gaps in the lookback window.

        Only runs when:
        - strict_mode=True (default)
        - is_backfill_mode=False (checks bypassed during backfills)

        Checks:
        1. Upstream processor status: Did upstream Phase 3 processor succeed yesterday?
        2. Gap detection: Any missing dates in the lookback window?

        Args:
            analysis_date: Date being processed
            strict_mode: Whether to enforce defensive checks (default: True)

        Raises:
            DependencyError: If defensive checks fail

        Configuration Required (in child classes):
            - upstream_processor_name: Name of upstream Phase 3 processor (e.g., 'PlayerGameSummaryProcessor')
            - upstream_table: Upstream Phase 3 table (e.g., 'nba_analytics.player_game_summary')
            - lookback_days: Number of days to check for gaps (e.g., 10)
        """
        # Skip defensive checks in backfill mode
        if self.is_backfill_mode:
            logger.info("⏭️  BACKFILL MODE: Skipping defensive checks")
            return

        # Skip if strict mode disabled
        if not strict_mode:
            logger.info("⏭️  STRICT MODE DISABLED: Skipping defensive checks")
            return

        # Use soft dependency checking if enabled (added after Jan 23 incident)
        # This allows proceeding with degraded data if coverage > threshold
        if self.use_soft_dependencies and SOFT_DEPS_AVAILABLE:
            logger.info(f"🔄 Using SOFT DEPENDENCY checking (threshold: {self.soft_dependency_threshold:.0%})")
            dep_result = self.check_soft_dependencies(analysis_date)

            if dep_result['should_proceed']:
                if dep_result['degraded']:
                    logger.warning(f"⚠️  Proceeding with DEGRADED dependencies:")
                    for warning in dep_result['warnings']:
                        logger.warning(f"    - {warning}")
                    # Record degraded state for monitoring
                    self.dependency_check_passed = True
                    self.data_completeness_pct = min(dep_result['coverage'].values()) * 100 if dep_result['coverage'] else 100.0
                else:
                    logger.info("✅ All soft dependencies met")
                    self.dependency_check_passed = True
                return  # Dependencies OK (possibly degraded), continue processing
            else:
                # Soft dependencies not met
                logger.error(f"❌ Soft dependencies not met:")
                for error in dep_result['errors']:
                    logger.error(f"    - {error}")
                self.dependency_check_passed = False
                raise DependencyError(f"Soft dependencies not met: {'; '.join(dep_result['errors'])}")

        logger.info("🛡️  Running defensive checks...")

        try:
            # Ensure analysis_date is a date object, not a string
            if isinstance(analysis_date, str):
                analysis_date = datetime.strptime(analysis_date, '%Y-%m-%d').date()

            # Initialize completeness checker
            checker = CompletenessChecker(self.bq_client, self.project_id)

            # DEFENSE 1: Check upstream Phase 3 processor status
            # Check if yesterday's Phase 3 processor succeeded
            # (Phase 4 typically runs day-of, so check day-before)
            if hasattr(self, 'upstream_processor_name') and self.upstream_processor_name:
                yesterday = analysis_date - timedelta(days=1)

                logger.info(f"  Checking upstream processor: {self.upstream_processor_name} for {yesterday}")

                status = checker.check_upstream_processor_status(
                    processor_name=self.upstream_processor_name,
                    data_date=yesterday
                )

                if not status['safe_to_process']:
                    error_msg = f"⚠️ Upstream processor {self.upstream_processor_name} failed for {yesterday}"
                    logger.error(error_msg)

                    # Send alert with recovery details
                    try:
                        notify_error(
                            title=f"Precompute BLOCKED: Upstream Failure - {self.__class__.__name__}",
                            message=error_msg,
                            details={
                                'processor': self.__class__.__name__,
                                'run_id': self.run_id,
                                'blocked_date': str(analysis_date),
                                'missing_upstream_date': str(yesterday),
                                'upstream_processor': self.upstream_processor_name,
                                'upstream_error': status['error_message'],
                                'upstream_run_id': status.get('run_id'),
                                'resolution': f"Fix {self.upstream_processor_name} for {yesterday} first",
                                'table': self.table_name
                            },
                            processor_name=self.__class__.__name__
                        )
                        self.set_alert_sent('error')
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")

                    raise DependencyError(
                        f"Upstream {self.upstream_processor_name} failed for {yesterday}. "
                        f"Error: {status['error_message']}"
                    )

            # DEFENSE 2: Check for gaps in upstream data range
            # Check Phase 3 table for missing dates in lookback window
            if hasattr(self, 'upstream_table') and hasattr(self, 'lookback_days'):
                lookback_start = analysis_date - timedelta(days=self.lookback_days)

                logger.info(f"  Checking for gaps in {self.upstream_table} from {lookback_start} to {analysis_date}")

                gaps = checker.check_date_range_completeness(
                    table=self.upstream_table,
                    date_column='game_date',
                    start_date=lookback_start,
                    end_date=analysis_date
                )

                if gaps['has_gaps']:
                    error_msg = f"⚠️ {gaps['gap_count']} gaps in {self.upstream_table} lookback window"
                    logger.error(error_msg)

                    # Send alert with recovery details
                    try:
                        notify_error(
                            title=f"Precompute BLOCKED: Data Gaps - {self.__class__.__name__}",
                            message=error_msg,
                            details={
                                'processor': self.__class__.__name__,
                                'run_id': self.run_id,
                                'analysis_date': str(analysis_date),
                                'lookback_window': f"{lookback_start} to {analysis_date}",
                                'missing_dates': [str(d) for d in gaps['missing_dates'][:10]],  # Show first 10
                                'gap_count': gaps['gap_count'],
                                'coverage_pct': gaps['coverage_pct'],
                                'upstream_table': self.upstream_table,
                                'resolution': 'Backfill missing dates in upstream table before proceeding',
                                'table': self.table_name
                            },
                            processor_name=self.__class__.__name__
                        )
                        self.set_alert_sent('error')
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")

                    raise DependencyError(
                        f"{gaps['gap_count']} gaps detected in historical data "
                        f"({lookback_start} to {analysis_date}). "
                        f"Missing dates: {gaps['missing_dates'][:5]}"
                    )

            logger.info("✅ Defensive checks passed - safe to process")

        except DependencyError:
            # Re-raise DependencyError (already logged/alerted)
            raise
        except Exception as e:
            # Log but don't fail on defensive check errors (defensive checks are themselves optional)
            logger.warning(f"Defensive checks encountered error (non-blocking): {e}")

    # =========================================================================
    # Options Management
    # =========================================================================
    
    def set_opts(self, opts: Dict) -> None:
        """Set options."""
        self.opts = opts
        self.opts["run_id"] = self.run_id
        
    def validate_opts(self) -> None:
        """Validate required options."""
        for required_opt in self.required_opts:
            if required_opt not in self.opts:
                error_msg = f"Missing required option [{required_opt}]"
                
                try:
                    notify_error(
                        title=f"Precompute Processor Configuration Error: {self.__class__.__name__}",
                        message=f"Missing required option: {required_opt}",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'missing_option': required_opt,
                            'required_opts': self.required_opts,
                            'provided_opts': list(self.opts.keys())
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                raise ValueError(error_msg)
    
    def set_additional_opts(self) -> None:
        """Add additional options - child classes override and call super()."""
        if "timestamp" not in self.opts:
            self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    def validate_additional_opts(self) -> None:
        """Validate additional options - child classes override."""
        pass
    
    def init_clients(self) -> None:
        """Initialize GCP clients with error notification."""
        try:
            from shared.config.gcp_config import get_project_id
            self.project_id = self.opts.get("project_id") or get_project_id()
            self.bq_client = get_bigquery_client(project_id=self.project_id)
        except GoogleAPIError as e:
            logger.error(f"Failed to initialize BigQuery client: {e}")
            try:
                from shared.config.gcp_config import get_project_id as get_proj
                notify_error(
                    title=f"Precompute Processor Client Initialization Failed: {self.__class__.__name__}",
                    message="Unable to initialize BigQuery client",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'project_id': self.opts.get('project_id') or get_proj(),
                        'error_type': type(e).__name__,
                        'error': str(e)
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
    
    # =========================================================================
    # Abstract Methods (Child Classes Must Implement)
    # =========================================================================
    
    def extract_raw_data(self) -> None:
        """
        Extract data from analytics BigQuery tables.
        Child classes must implement.
        
        Note: Dependency checking happens BEFORE this is called.
        """
        raise NotImplementedError("Child classes must implement extract_raw_data()")
    
    def validate_extracted_data(self) -> None:
        """Validate extracted data - child classes override."""
        if self.raw_data is None or (hasattr(self.raw_data, 'empty') and self.raw_data.empty):
            try:
                notify_warning(
                    title=f"Precompute Processor No Data Extracted: {self.__class__.__name__}",
                    message="No data extracted from analytics tables",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'analysis_date': str(self.opts.get('analysis_date'))
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise ValueError("No data extracted")
    
    def calculate_precompute(self) -> None:
        """
        Calculate precompute metrics and include source metadata.
        Child classes must implement.
        
        Must populate self.transformed_data with records that include:
        - Business logic fields
        - source_tables_used (from self.source_metadata)
        - data_completeness_pct
        - missing_dependencies
        - dependency_check_passed
        - dependency_check_timestamp
        - upstream_data_age_hours
        """
        raise NotImplementedError("Child classes must implement calculate_precompute()")

    # =========================================================================
    # Save to BigQuery
    # =========================================================================
    # BigQuery save operations extracted to operations/bigquery_save_ops.py
    # - save_precompute()
    # - _save_with_proper_merge()
    # - _delete_existing_data_batch()

    # Quality methods inherited from QualityMixin
    # - _check_for_duplicates_post_save()
    # - log_quality_issue()

    # =========================================================================
    # Logging & Monitoring
    # =========================================================================
    
    def log_processing_run(self, success: bool, error: str = None) -> None:
        """
        Log processing run to monitoring table.
        Uses batch loading to avoid streaming buffer issues.
        """
        run_record = {
            'processor_name': self.__class__.__name__,
            'run_id': self.run_id,
            'run_date': datetime.now(timezone.utc).isoformat(),
            'success': success,
            'analysis_date': str(self.opts.get('analysis_date')),
            'records_processed': self.stats.get('rows_processed', 0),
            'duration_seconds': float(self.stats.get('total_runtime', 0.0)),
            'dependency_check_passed': self.dependency_check_passed,
            'data_completeness_pct': float(self.data_completeness_pct) if self.data_completeness_pct is not None else None,
            'upstream_data_age_hours': float(self.upstream_data_age_hours) if self.upstream_data_age_hours is not None else None,
            'errors_json': json.dumps([error] if error else []),
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        try:
            table_id = f"{self.project_id}.nba_processing.precompute_processor_runs"

            # Use batch loading via load_table_from_json
            job_config = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                autodetect=True
            )
            load_job = self.bq_client.load_table_from_json(
                [run_record],
                table_id,
                job_config=job_config
            )
            load_job.result(timeout=60)  # Wait for completion
        except GoogleAPIError as e:
            logger.warning(f"Failed to log processing run: {e}")
    
    def post_process(self) -> None:
        """Post-processing - log summary stats and publish completion message."""
        summary = {
            "run_id": self.run_id,
            "processor": self.__class__.__name__,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "total_runtime": self.stats.get("total_runtime", 0),
            "dependency_check_passed": self.dependency_check_passed,
            "data_completeness_pct": self.data_completeness_pct,
            "upstream_data_age_hours": self.upstream_data_age_hours
        }

        # Merge precompute stats
        precompute_stats = self.get_precompute_stats()
        if isinstance(precompute_stats, dict):
            summary.update(precompute_stats)

        logger.info("PRECOMPUTE_STATS %s", json.dumps(summary))

        # Publish completion message to trigger Phase 5 (if target table is set)
        # Can be disabled with skip_downstream_trigger flag for backfills
        if self.opts.get('skip_downstream_trigger', False):
            logger.info(
                f"⏸️  Skipping downstream trigger (backfill mode) - "
                f"Phase 5 will not be auto-triggered for {self.table_name}"
            )
        elif self.table_name:
            # R-004: Verify write success before publishing completion
            if hasattr(self, 'write_success') and not self.write_success:
                logger.warning(
                    f"⚠️ Publishing completion with success=False due to write failure "
                    f"(rows_skipped={self.stats.get('rows_skipped', 0)})"
                )
                self._publish_completion_message(
                    success=False,
                    error=f"Write failures detected: {self.stats.get('rows_skipped', 0)} rows skipped"
                )
            else:
                self._publish_completion_message(success=True)
    
    def get_precompute_stats(self) -> Dict:
        """Get precompute stats - child classes override."""
        return {}

    def _publish_completion_message(self, success: bool, error: str = None) -> None:
        """
        Publish unified completion message to nba-phase4-precompute-complete topic.
        This triggers Phase 5 prediction processors that depend on this precompute table.

        Uses UnifiedPubSubPublisher for consistent message format across all phases.

        Args:
            success: Whether processing completed successfully
            error: Optional error message if failed
        """
        try:
            # Use unified publisher
            publisher = UnifiedPubSubPublisher(project_id=self.project_id)

            # Get the analysis date
            analysis_date = self.opts.get('analysis_date')
            if isinstance(analysis_date, date):
                analysis_date = analysis_date.strftime('%Y-%m-%d')

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
                execution_id=self.run_id,
                correlation_id=self.correlation_id or self.run_id,
                game_date=str(analysis_date),
                output_table=self.table_name,
                output_dataset=self.dataset_id,
                status=status,
                record_count=self.stats.get('rows_processed', 0),
                records_failed=0,
                parent_processor=self.parent_processor,
                trigger_source=self.opts.get('trigger_source', 'manual'),
                trigger_message_id=self.trigger_message_id,
                duration_seconds=duration_seconds,
                error_message=error,
                error_type=type(error).__name__ if error else None,
                metadata={
                    # Precompute-specific metadata
                    'dependency_check_passed': self.dependency_check_passed,
                    'data_completeness_pct': self.data_completeness_pct,
                    'upstream_data_age_hours': self.upstream_data_age_hours,
                    'missing_dependencies': self.missing_dependencies_list,

                    # Selective processing (inherited from Phase 3)
                    'is_incremental': self.is_incremental_run,
                    'entities_changed': self.entities_changed if self.is_incremental_run else [],

                    # Standard stats
                    'extract_time': self.stats.get('extract_time'),
                    'calculate_time': self.stats.get('calculate_time'),
                    'save_time': self.stats.get('save_time')
                },
                skip_downstream=self.opts.get('skip_downstream_trigger', False)
            )

            if message_id:
                logger.info(
                    f"✅ Published unified completion message to nba-phase4-precompute-complete "
                    f"(message_id: {message_id}, correlation_id: {self.correlation_id})"
                )
            else:
                logger.info("⏸️  Skipped publishing (backfill mode or skip_downstream_trigger=True)")

        except GoogleAPIError as e:
            logger.warning(f"Failed to publish completion message: {e}")
            # R-008: Add monitoring for Pub/Sub failures
            # Don't fail the whole processor, but send alert for visibility
            try:
                notify_warning(
                    title=f"R-008: Pub/Sub Publish Failed - {self.__class__.__name__}",
                    message=f"Failed to publish Phase 4 completion message. Downstream phases may not trigger.",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'topic': 'nba-phase4-precompute-complete',
                        'table': self.table_name,
                        'analysis_date': str(self.opts.get('analysis_date')),
                        'error_type': type(e).__name__,
                        'error': str(e)
                    }
                )
            except Exception as notify_err:
                logger.debug(f"Could not send Pub/Sub failure notification: {notify_err}")

    # Note: Time Tracking (mark_time, get_elapsed_seconds) and Error Handling
    # (step_info, report_error, _save_partial_data) methods are inherited from
    # TransformProcessorBase

    # Failure tracking operations extracted to operations/failure_tracking.py
    # - classify_recorded_failures()
    # - save_failures_to_bq()

    def _quick_upstream_existence_check(self, analysis_date: date) -> List[str]:
        """
        Quick existence check for critical Phase 4 upstream dependencies.

        This is a SAFETY check that runs even in backfill mode to catch cases
        where upstream data is completely missing (e.g., Dec 4, 2021 TDZA gap).

        Unlike the full dependency check, this only verifies:
        - At least 1 record exists in each critical Phase 4 upstream table
        - Takes ~1 second instead of 60+ seconds

        Returns:
            List of missing table names (empty if all exist)
        """
        missing_tables = []

        # Get Phase 4 dependencies from PHASE_4_SOURCES config
        # Note: Not all processors have PHASE_4_SOURCES (e.g., TDZA/PSZA read from Phase 3)
        phase_4_deps = []
        if hasattr(self, 'PHASE_4_SOURCES'):
            for source, is_relevant in self.PHASE_4_SOURCES.items():
                if is_relevant and source in ['player_shot_zone_analysis', 'team_defense_zone_analysis']:
                    phase_4_deps.append(source)

        if not phase_4_deps:
            # No Phase 4 deps to check (e.g., TDZA/PSZA don't depend on other Phase 4)
            return []

        # Map table names to their date column
        table_date_columns = {
            'player_shot_zone_analysis': 'analysis_date',
            'team_defense_zone_analysis': 'analysis_date',
            'player_daily_cache': 'cache_date',
        }

        for table_name in phase_4_deps:
            date_col = table_date_columns.get(table_name, 'analysis_date')
            try:
                query = f"""
                SELECT COUNT(*) as cnt
                FROM `{self.project_id}.nba_precompute.{table_name}`
                WHERE {date_col} = '{analysis_date}'
                """
                result = self.bq_client.query(query).to_dataframe()
                count = result['cnt'].iloc[0] if not result.empty else 0

                if count == 0:
                    missing_tables.append(table_name)
                    logger.warning(f"⚠️  BACKFILL SAFETY: {table_name} has 0 records for {analysis_date}")
                else:
                    logger.debug(f"✓ {table_name} has {count} records for {analysis_date}")

            except Exception as e:
                logger.warning(f"Error checking {table_name}: {e}")
                # Don't fail on error - just log it

        return missing_tables

    def _record_date_level_failure(self, category: str, reason: str, can_retry: bool = True) -> None:
        """
        Record a date-level failure to the precompute_failures table.

        Use this when an entire date fails (e.g., missing dependencies),
        rather than individual player failures.

        This enables visibility into WHY no records exist for a date:
        - MISSING_DEPENDENCY: Upstream data not available (standardized singular form)
        - MINIMUM_THRESHOLD_NOT_MET: Too few upstream records (expected during early season)
        - PROCESSING_ERROR: Actual error during processing (needs investigation)

        Args:
            category: Failure category (MISSING_DEPENDENCY, MINIMUM_THRESHOLD_NOT_MET, etc.)
            reason: Detailed reason string
            can_retry: Whether reprocessing might succeed (True if deps will be populated)
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

            # Get table reference for schema
            table_ref = self.bq_client.get_table(table_id)

            # Use batch loading instead of streaming inserts
            # This avoids the 90-minute streaming buffer that blocks DML operations
            # See docs/05-development/guides/bigquery-best-practices.md
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json([failure_record], table_id, job_config=job_config)
            load_job.result(timeout=60)

            if load_job.errors:
                logger.warning(f"Error recording date-level failure: {load_job.errors}")
            else:
                logger.info(f"Recorded date-level failure: {category} - {reason[:50]}...")

        except GoogleAPIError as e:
            logger.warning(f"Failed to record date-level failure: {e}")

    # Metadata operations extracted to operations/metadata_ops.py
    # - build_source_tracking_fields()
    # - _calculate_expected_count()
    # - track_source_usage()
