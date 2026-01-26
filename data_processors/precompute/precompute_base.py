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
