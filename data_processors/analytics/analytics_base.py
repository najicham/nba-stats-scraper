"""
Path: analytics_processors/analytics_base.py

Base class for Phase 3 analytics processors that handles:
 - Dependency checking (upstream Phase 2 data validation)
 - Source metadata tracking (audit trail per v4.0 guide)
 - Querying raw BigQuery tables
 - Calculating analytics metrics
 - Loading to analytics tables
 - Error handling and quality tracking
 - Multi-channel notifications (Email + Slack)
 - Run history logging (via RunHistoryMixin)

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
from google.cloud import pubsub_v1
from google.api_core.exceptions import GoogleAPIError, NotFound, BadRequest, ServiceUnavailable, DeadlineExceeded
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

# Import completeness checking for defensive checks
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

# Import failure categorization
from data_processors.analytics.operations.failure_handler import categorize_failure

# Import analytics mixins
from data_processors.analytics.mixins.quality_mixin import QualityMixin
from data_processors.analytics.mixins.metadata_mixin import MetadataMixin

# Import unified publishing and change detection
from shared.publishers.unified_pubsub_publisher import UnifiedPubSubPublisher
from shared.change_detection.change_detector import ChangeDetector

# Import sport configuration for multi-sport support
from shared.config.sport_config import (
    get_analytics_dataset,
    get_raw_dataset,
    get_project_id,
    get_current_sport,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger("analytics_base")


class AnalyticsProcessorBase(MetadataMixin, QualityMixin, TransformProcessorBase, SoftDependencyMixin, RunHistoryMixin):
    """
    Base class for Phase 3 analytics processors with full dependency tracking.

    Phase 3 processors depend on Phase 2 (Raw) tables.
    This base class provides dependency checking, source tracking, and validation.

    Soft Dependencies (added after Jan 23 incident):
    - Set use_soft_dependencies = True in child class to enable graceful degradation
    - Processors will proceed if coverage > 80% instead of all-or-nothing

    Lifecycle:
      1) Check dependencies (are upstream Phase 2 tables ready?)
      2) Extract data from raw BigQuery tables
      3) Validate extracted data
      4) Calculate analytics
      5) Load to analytics BigQuery tables
      6) Log processing run with source metadata

    Run History:
      Automatically logs runs to processor_run_history table via RunHistoryMixin.
    """

    # Class-level configs
    required_opts: List[str] = ['start_date', 'end_date']
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
    processing_strategy: str = "MERGE_UPDATE"  # Default for analytics

    # Run history settings (from RunHistoryMixin)
    PHASE: str = 'phase_3_analytics'
    STEP_PREFIX: str = 'ANALYTICS_STEP'  # For structured logging
    DEBUG_FILE_PREFIX: str = 'analytics_debug'  # For debug file naming
    OUTPUT_TABLE: str = ''  # Set to table_name in run()
    OUTPUT_DATASET: str = None  # Will be set from sport_config in __init__
    
    def __init__(self):
        """Initialize analytics processor."""
        # Initialize base class (sets opts, raw_data, validated_data, transformed_data,
        # stats, time_markers, source_metadata, quality_issues, failed_entities, run_id,
        # correlation_id, parent_processor, trigger_message_id, entities_changed,
        # is_incremental_run, heartbeat, and stubs for project_id/bq_client)
        super().__init__()

        # GCP clients - override parent stubs with actual clients
        self.project_id = os.environ.get('GCP_PROJECT_ID', get_project_id())
        self.bq_client = get_bigquery_client(project_id=self.project_id)

        # Set dataset from sport_config if not overridden by child class
        if self.dataset_id is None:
            self.dataset_id = get_analytics_dataset()
        if self.OUTPUT_DATASET is None:
            self.OUTPUT_DATASET = get_analytics_dataset()

        # Change detection (v1.1 feature)
        self.change_detector = None  # Initialized if child class provides get_change_detector()

        # Registry failure tracking (v3.0 feature - for name resolution reprocessing)
        # Child processors populate this list when registry lookup fails
        # Each entry: {player_lookup, game_date, team_abbr, season, game_id}
        self.registry_failures = []

        # Completeness checker for DNP classification
        self.completeness_checker = None

    # Note: The following methods are inherited from TransformProcessorBase:
    # - is_backfill_mode (property)
    # - get_prefixed_dataset()
    # - get_output_dataset()
    # - _execute_query_with_retry()
    # - _sanitize_row_for_json()
    # - _send_notification()
    # - mark_time() / get_elapsed_seconds()
    # - step_info()
    # - report_error()
    # - _save_partial_data()
    # - _get_current_step()
    # - processor_name (property)

    def run(self, opts: Optional[Dict] = None) -> bool:
        """
        Main entry point - returns True on success, False on failure.
        Enhanced with run history logging.
        """
        if opts is None:
            opts = {}

        # Track dependency check results for run history
        dep_check_results = None

        try:
            # Re-init but preserve run_id
            saved_run_id = self.run_id
            self.__init__()
            self.run_id = saved_run_id
            self.stats["run_id"] = saved_run_id

            self.mark_time("total")
            self.step_info("start", "Analytics processor run starting", extra={"opts": opts})

            # Setup
            self.set_opts(opts)
            self.validate_opts()
            self.set_additional_opts()
            self.validate_additional_opts()
            self.init_clients()

            # Extract correlation tracking info from upstream message
            self.correlation_id = opts.get('correlation_id') or self.run_id
            self.parent_processor = opts.get('parent_processor')
            self.trigger_message_id = opts.get('trigger_message_id')

            # Start run history tracking
            self.OUTPUT_TABLE = self.table_name
            self.OUTPUT_DATASET = self.dataset_id
            data_date = opts.get('end_date') or opts.get('start_date')
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
                        phase='phase_3',
                        processor_name=self.processor_name,
                        game_date=str(data_date) if data_date else str(opts.get('start_date')),
                        correlation_id=self.correlation_id,
                        trigger_source=opts.get('trigger_source', 'scheduled')
                    )
                except Exception as log_ex:
                    logger.warning(f"Failed to log processor start: {log_ex}")

            # Check dependencies BEFORE extracting (if processor defines them)
            # In backfill mode, skip dependency checks entirely for performance
            # Pre-flight checks already verify data exists before backfill starts
            if hasattr(self, 'get_dependencies') and callable(self.get_dependencies):
                if self.is_backfill_mode:
                    # Skip expensive BQ queries - all failures are bypassed anyway
                    logger.info("⏭️  BACKFILL MODE: Skipping dependency BQ checks (pre-flight already verified)")
                    dep_check = {
                        'all_critical_present': True,
                        'all_fresh': True,
                        'has_stale_fail': False,
                        'has_stale_warn': False,
                        'missing': [],
                        'stale_fail': [],
                        'stale_warn': [],
                        'details': {}
                    }
                    dep_check_results = dep_check
                    dep_check_seconds = 0  # Used in logging below
                    self.stats["dependency_check_time"] = 0
                    self.set_dependency_results(
                        dependencies=[],
                        all_passed=True,
                        missing=[],
                        stale=[]
                    )
                else:
                    self.mark_time("dependency_check")
                    dep_check = self.check_dependencies(
                        self.opts['start_date'],
                        self.opts['end_date']
                    )
                    dep_check_results = dep_check
                    dep_check_seconds = self.get_elapsed_seconds("dependency_check")
                    self.stats["dependency_check_time"] = dep_check_seconds

                    # Record dependency results for run history
                    self.set_dependency_results(
                        dependencies=[
                            {'table': k, **v} for k, v in dep_check.get('details', {}).items()
                        ],
                        all_passed=dep_check['all_critical_present'],
                        missing=dep_check.get('missing', []),
                        stale=dep_check.get('stale_fail', []) + dep_check.get('stale_warn', [])
                    )

                # Handle critical dependency failures
                if not dep_check['all_critical_present']:
                    error_msg = f"Missing critical dependencies: {dep_check['missing']}"

                    # In backfill mode, warn but allow processing to continue
                    # The processor can handle missing data gracefully in extract_raw_data()
                    if self.is_backfill_mode:
                        logger.warning(f"BACKFILL_MODE: {error_msg} - continuing anyway")
                        logger.info("BACKFILL_MODE: Processor will handle missing data in extract_raw_data()")
                    else:
                        logger.error(error_msg)
                        self._send_notification(
                            notify_error,
                            title=f"Analytics Processor: Missing Dependencies - {self.__class__.__name__}",
                            message=error_msg,
                            details={
                                'processor': self.__class__.__name__,
                                'run_id': self.run_id,
                                'date_range': f"{self.opts['start_date']} to {self.opts['end_date']}",
                                'missing': dep_check['missing'],
                                'stale_fail': dep_check.get('stale_fail', []),
                                'dependency_details': dep_check['details']
                            },
                            processor_name=self.__class__.__name__
                        )
                        self.set_alert_sent('error')
                        raise ValueError(error_msg)

                # Handle stale data FAIL threshold (skip in backfill mode)
                if dep_check.get('has_stale_fail') and not self.is_backfill_mode:
                    error_msg = f"Stale dependencies (FAIL threshold): {dep_check['stale_fail']}"
                    self._send_notification(
                        notify_error,
                        title=f"Analytics Processor: Stale Data - {self.__class__.__name__}",
                        message=error_msg,
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'date_range': f"{self.opts['start_date']} to {self.opts['end_date']}",
                            'stale_sources': dep_check['stale_fail']
                        },
                        processor_name=self.__class__.__name__
                    )
                    self.set_alert_sent('error')
                    raise ValueError(error_msg)
                elif dep_check.get('has_stale_fail') and self.is_backfill_mode:
                    logger.info(f"BACKFILL_MODE: Ignoring stale data check - {dep_check['stale_fail']}")

                # Warn about stale data (WARN threshold only)
                if dep_check.get('has_stale_warn'):
                    logger.warning(f"Stale upstream data detected: {dep_check['stale_warn']}")
                    self._send_notification(
                        notify_warning,
                        title=f"Analytics Processor: Stale Data Warning - {self.__class__.__name__}",
                        message=f"Some sources are stale: {dep_check['stale_warn']}",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'date_range': f"{self.opts['start_date']} to {self.opts['end_date']}",
                            'stale_sources': dep_check['stale_warn']
                        }
                    )
                    self.set_alert_sent('warning')

                # Track source metadata from dependency check
                self.track_source_usage(dep_check)

                self.step_info("dependency_check_complete",
                              f"Dependencies validated in {dep_check_seconds:.1f}s")
            else:
                logger.info("No dependency checking configured for this processor")

            # ═══════════════════════════════════════════════════════════════
            # DEFENSIVE CHECKS: Upstream Status + Gap Detection
            # ═══════════════════════════════════════════════════════════════
            # Enabled by strict_mode flag (default: enabled for production)
            # Checks for:
            #   1. Upstream processor failures (prevents processing with failed deps)
            #   2. Gaps in historical data (prevents processing with incomplete windows)
            # ═══════════════════════════════════════════════════════════════
            strict_mode = self.opts.get('strict_mode', True)  # Default: enabled

            if strict_mode and not self.is_backfill_mode:
                logger.info("🔒 STRICT MODE: Running defensive checks...")

                try:
                    # Initialize completeness checker
                    checker = CompletenessChecker(self.bq_client, self.project_id)

                    # DEFENSE 1: Check if yesterday's upstream processor succeeded
                    # (Prevents cascade failure scenario where Monday fails, Tuesday runs anyway)
                    analysis_date = self.opts.get('end_date') or self.opts.get('start_date')
                    if analysis_date and hasattr(self, 'upstream_processor_name'):
                        yesterday = analysis_date - timedelta(days=1) if isinstance(analysis_date, date) else None

                        if yesterday:
                            status = checker.check_upstream_processor_status(
                                processor_name=self.upstream_processor_name,
                                data_date=yesterday
                            )

                            if not status['safe_to_process']:
                                error_msg = f"⚠️ Upstream processor {self.upstream_processor_name} failed for {yesterday}"
                                logger.error(error_msg)
                                self._send_notification(
                                    notify_error,
                                    title=f"Analytics BLOCKED: Upstream Failure - {self.__class__.__name__}",
                                    message=error_msg,
                                    details={
                                        'processor': self.__class__.__name__,
                                        'run_id': self.run_id,
                                        'blocked_date': str(analysis_date),
                                        'missing_upstream_date': str(yesterday),
                                        'upstream_processor': self.upstream_processor_name,
                                        'upstream_error': status['error_message'],
                                        'upstream_run_id': status['run_id'],
                                        'resolution': f'Fix {self.upstream_processor_name} for {yesterday} first'
                                    },
                                    processor_name=self.__class__.__name__
                                )
                                self.set_alert_sent('error')
                                raise DependencyError(
                                    f"Upstream {self.upstream_processor_name} failed for {yesterday}",
                                    details=status
                                )

                    # DEFENSE 2: Check for gaps in upstream data range
                    # (Prevents processing with missing dates in lookback window)
                    if hasattr(self, 'upstream_table') and hasattr(self, 'lookback_days'):
                        lookback_start = analysis_date - timedelta(days=self.lookback_days)

                        gaps = checker.check_date_range_completeness(
                            table=self.upstream_table,
                            date_column='game_date',
                            start_date=lookback_start,
                            end_date=analysis_date
                        )

                        if gaps['has_gaps']:
                            error_msg = f"⚠️ {gaps['gap_count']} gaps in {self.upstream_table} lookback window"
                            logger.error(error_msg)
                            self._send_notification(
                                notify_error,
                                title=f"Analytics BLOCKED: Data Gaps - {self.__class__.__name__}",
                                message=error_msg,
                                details={
                                    'processor': self.__class__.__name__,
                                    'run_id': self.run_id,
                                    'analysis_date': str(analysis_date),
                                    'lookback_window': f"{lookback_start} to {analysis_date}",
                                    'missing_dates': [str(d) for d in gaps['missing_dates']],
                                    'gap_count': gaps['gap_count'],
                                    'coverage_pct': gaps['coverage_pct'],
                                    'resolution': 'Backfill missing dates first'
                                },
                                processor_name=self.__class__.__name__
                            )
                            self.set_alert_sent('error')
                            raise DependencyError(
                                f"{gaps['gap_count']} gaps in historical data",
                                details=gaps
                            )

                    logger.info("✅ Defensive checks passed - safe to process")

                except DependencyError:
                    # Re-raise DependencyError (already logged/alerted)
                    raise
                except Exception as e:
                    # Log but don't fail on defensive check errors
                    logger.warning(f"Defensive checks failed (non-blocking): {e}")

            elif self.is_backfill_mode:
                logger.info("⏭️  BACKFILL MODE: Skipping defensive checks")
            elif not strict_mode:
                logger.info("⏭️  STRICT MODE DISABLED: Skipping defensive checks")

            # ═══════════════════════════════════════════════════════════════
            # CHANGE DETECTION (v1.1 Feature)
            # ═══════════════════════════════════════════════════════════════
            # Detects which entities changed since last processing
            # Enables 99%+ efficiency gain for mid-day updates
            # Falls back to full batch if change detection fails
            # ═══════════════════════════════════════════════════════════════
            analysis_date = self.opts.get('end_date') or self.opts.get('start_date')

            # Check if entities_changed was passed from upstream (orchestrator)
            if opts.get('entities_changed'):
                self.entities_changed = opts['entities_changed']
                self.is_incremental_run = True
                logger.info(
                    f"🎯 INCREMENTAL RUN: Processing {len(self.entities_changed)} changed entities "
                    f"(from upstream message)"
                )
                self.stats['entities_changed_count'] = len(self.entities_changed)
                self.stats['is_incremental'] = True

            # Otherwise, run change detection if processor supports it
            elif hasattr(self, 'get_change_detector') and callable(self.get_change_detector):
                try:
                    self.mark_time("change_detection")

                    # Get change detector from child class
                    self.change_detector = self.get_change_detector()

                    if self.change_detector and analysis_date:
                        # Run change detection query
                        self.entities_changed = self.change_detector.detect_changes(
                            game_date=analysis_date
                        )

                        # Get statistics
                        change_stats = self.change_detector.get_change_stats(
                            game_date=analysis_date,
                            changed_entities=self.entities_changed
                        )

                        # If some entities changed (not all, not none), use incremental mode
                        if 0 < len(self.entities_changed) < change_stats['entities_total']:
                            self.is_incremental_run = True
                            logger.info(
                                f"🎯 INCREMENTAL RUN: {len(self.entities_changed)}/{change_stats['entities_total']} entities changed "
                                f"({change_stats['efficiency_gain_pct']:.1f}% efficiency gain)"
                            )
                            self.stats['entities_changed_count'] = len(self.entities_changed)
                            self.stats['entities_total'] = change_stats['entities_total']
                            self.stats['efficiency_gain_pct'] = change_stats['efficiency_gain_pct']
                            self.stats['is_incremental'] = True
                        else:
                            # All changed or none changed - process full batch
                            logger.info(
                                f"📊 FULL BATCH: {len(self.entities_changed)}/{change_stats['entities_total']} entities changed "
                                f"(processing all)"
                            )
                            self.entities_changed = []
                            self.is_incremental_run = False
                            self.stats['is_incremental'] = False

                        change_detect_seconds = self.get_elapsed_seconds("change_detection")
                        self.stats["change_detection_time"] = change_detect_seconds
                        logger.info(f"Change detection completed in {change_detect_seconds:.2f}s")

                except Exception as e:
                    # Don't fail on change detection errors - fall back to full batch
                    logger.warning(f"Change detection failed (non-fatal): {e}, falling back to full batch")
                    self.entities_changed = []
                    self.is_incremental_run = False
                    self.stats['change_detection_error'] = str(e)
                    self.stats['is_incremental'] = False

            else:
                # No change detection configured - always full batch
                logger.debug("No change detection configured, running full batch")
                self.stats['is_incremental'] = False

            # Extract from raw tables
            self.mark_time("extract")
            self.extract_raw_data()
            extract_seconds = self.get_elapsed_seconds("extract")
            self.stats["extract_time"] = extract_seconds
            self.step_info("extract_complete", f"Data extracted in {extract_seconds:.1f}s")

            # Validate
            if self.validate_on_extract:
                self.validate_extracted_data()

            # Transform/calculate analytics
            self.mark_time("transform")
            self.calculate_analytics()
            transform_seconds = self.get_elapsed_seconds("transform")
            self.stats["transform_time"] = transform_seconds

            # Save to analytics tables
            self.mark_time("save")
            self.save_analytics()
            save_seconds = self.get_elapsed_seconds("save")
            self.stats["save_time"] = save_seconds

            # Complete
            total_seconds = self.get_elapsed_seconds("total")
            self.stats["total_runtime"] = total_seconds
            self.step_info("finish",
                          f"Analytics processor completed in {total_seconds:.1f}s")

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
                    data_date = opts.get('end_date') or opts.get('start_date')
                    log_processor_complete(
                        phase='phase_3',
                        processor_name=self.processor_name,
                        game_date=str(data_date) if data_date else None,
                        duration_seconds=total_seconds,
                        records_processed=self.stats.get('rows_processed', 0),
                        correlation_id=self.correlation_id,
                        parent_event_id=getattr(self, '_pipeline_event_id', None)
                    )
                    # Clear any pending retry entries for this processor
                    mark_retry_succeeded(
                        phase='phase_3',
                        processor_name=self.processor_name,
                        game_date=str(data_date) if data_date else None
                    )
                except Exception as log_ex:
                    logger.warning(f"Failed to log processor complete: {log_ex}")

            return True

        except Exception as e:
            logger.error("AnalyticsProcessorBase Error: %s", e, exc_info=True)
            sentry_sdk.capture_exception(e)

            # Categorize the failure for monitoring/alerting
            current_step = self._get_current_step()
            failure_category = categorize_failure(e, current_step, self.stats)
            logger.info(f"Failure categorized as: {failure_category} (step={current_step})")

            # Send notification for failure (suppressed in backfill mode)
            # Skip notification for expected failures (no_data_available)
            try:
                should_alert = failure_category in ['processing_error', 'configuration_error', 'timeout']

                if should_alert:
                    self._send_notification(
                        notify_error,
                        title=f"Analytics Processor Failed: {self.__class__.__name__}",
                        message=f"Analytics calculation failed: {str(e)}",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'error_type': type(e).__name__,
                            'failure_category': failure_category,
                            'step': current_step,
                            'date_range': f"{opts.get('start_date')} to {opts.get('end_date')}",
                            'table': self.table_name,
                            'stats': self.stats
                        },
                        processor_name=self.__class__.__name__
                    )
                    self.set_alert_sent('error')
                else:
                    logger.info(f"Skipping alert for expected failure: {failure_category}")
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            # Log failed processing run
            self.log_processing_run(success=False, error=str(e))

            # Publish failure message (if target table is set)
            if self.table_name:
                self._publish_completion_message(success=False, error=str(e))

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
                    data_date = opts.get('end_date') or opts.get('start_date')
                    error_type_for_retry = classify_error_for_retry(e) if classify_error_for_retry else 'transient'

                    # Only queue for retry if it's a real error (not no_data_available)
                    if failure_category in ['processing_error', 'timeout', 'upstream_failure']:
                        import traceback
                        log_processor_error(
                            phase='phase_3',
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
        Base implementation saves any recorded failures to BigQuery.
        """
        # Save any failures that were recorded during processing
        try:
            if self.failed_entities:
                self.save_failures_to_bq()
        except Exception as e:
            logger.warning(f"Error saving failures in finalize(): {e}")

    # Note: _get_current_step() is inherited from TransformProcessorBase

    # =========================================================================
    # Dependency Checking System (Phase 3 - Date Range Pattern)
    # =========================================================================
    
    def get_dependencies(self) -> dict:
        """
        Define required upstream Phase 2 tables and their constraints.
        Child classes can optionally implement this.
        
        Returns:
            dict: {
                'table_name': {
                    'field_prefix': str,          # Prefix for source tracking fields
                    'description': str,           # Human-readable description
                    'date_field': str,            # Field to check for date
                    'check_type': str,            # 'date_range', 'existence'
                    'expected_count_min': int,    # Minimum acceptable rows
                    'max_age_hours_warn': int,    # Warning threshold (hours)
                    'max_age_hours_fail': int,    # Failure threshold (hours)
                    'critical': bool              # Fail if missing?
                }
            }
        
        Example:
            return {
                'nba_raw.nbac_team_boxscore': {
                    'field_prefix': 'source_nbac_boxscore',
                    'description': 'Team box score statistics',
                    'date_field': 'game_date',
                    'check_type': 'date_range',
                    'expected_count_min': 20,  # ~10 games × 2 teams
                    'max_age_hours_warn': 24,
                    'max_age_hours_fail': 72,
                    'critical': True
                }
            }
        """
        # Default: no dependencies (for backwards compatibility)
        return {}
    
    def check_dependencies(self, start_date: str, end_date: str) -> dict:
        """
        Check if required upstream Phase 2 data exists and is fresh enough.
        
        Adapted from PrecomputeProcessorBase for Phase 3 date range pattern.
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            
        Returns:
            dict: {
                'all_critical_present': bool,
                'all_fresh': bool,
                'has_stale_fail': bool,
                'has_stale_warn': bool,
                'missing': List[str],
                'stale_fail': List[str],
                'stale_warn': List[str],
                'details': Dict[str, Dict]
            }
        """
        dependencies = self.get_dependencies()
        
        # If no dependencies defined, return success
        if not dependencies:
            return {
                'all_critical_present': True,
                'all_fresh': True,
                'has_stale_fail': False,
                'has_stale_warn': False,
                'missing': [],
                'stale_fail': [],
                'stale_warn': [],
                'details': {}
            }
        
        results = {
            'all_critical_present': True,
            'all_fresh': True,
            'has_stale_fail': False,
            'has_stale_warn': False,
            'missing': [],
            'stale_fail': [],
            'stale_warn': [],
            'details': {}
        }
        
        for table_name, config in dependencies.items():
            logger.info(f"Checking dependency: {table_name}")
            
            # Check existence and metadata
            exists, details = self._check_table_data(
                table_name=table_name,
                start_date=start_date,
                end_date=end_date,
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
                max_age_warn = config.get('max_age_hours_warn', 24)
                max_age_fail = config.get('max_age_hours_fail', 72)
                
                if details['age_hours'] > max_age_fail:
                    results['all_fresh'] = False
                    results['has_stale_fail'] = True
                    stale_msg = (f"{table_name}: {details['age_hours']:.1f}h old "
                               f"(max: {max_age_fail}h)")
                    results['stale_fail'].append(stale_msg)
                    logger.error(f"Stale dependency (FAIL threshold): {stale_msg}")
                    
                elif details['age_hours'] > max_age_warn:
                    results['has_stale_warn'] = True
                    stale_msg = (f"{table_name}: {details['age_hours']:.1f}h old "
                               f"(warn: {max_age_warn}h)")
                    results['stale_warn'].append(stale_msg)
                    logger.warning(f"Stale dependency (WARN threshold): {stale_msg}")
            
            results['details'][table_name] = details
        
        logger.info(f"Dependency check complete: "
                   f"critical_present={results['all_critical_present']}, "
                   f"fresh={results['all_fresh']}")
        
        return results
    
    def _check_table_data(self, table_name: str, start_date: str, end_date: str,
                          config: dict) -> tuple:
        """
        Check if table has data for the given date range.

        Adapted from PrecomputeProcessorBase for Phase 3 date ranges.
        Enhanced with data_hash tracking for smart idempotency integration.

        Returns:
            (exists: bool, details: dict)
        """
        check_type = config.get('check_type', 'date_range')
        date_field = config.get('date_field', 'game_date')

        try:
            # Check if source table has data_hash column (Phase 2 smart idempotency)
            hash_field = "data_hash"  # Standard field name from SmartIdempotencyMixin

            if check_type == 'date_range':
                # Check for records in date range (most common for Phase 3)
                # Include data_hash if available (for smart idempotency tracking)
                query = f"""
                SELECT
                    COUNT(*) as row_count,
                    MAX(processed_at) as last_updated,
                    ARRAY_AGG({hash_field} IGNORE NULLS ORDER BY processed_at DESC LIMIT 1)[SAFE_OFFSET(0)] as representative_hash
                FROM `{self.project_id}.{table_name}`
                WHERE {date_field} BETWEEN '{start_date}' AND '{end_date}'
                """

            elif check_type == 'date_match':
                # Check for records on exact date (end_date is the target date)
                # Used for sources that should have data for the specific processing date
                query = f"""
                SELECT
                    COUNT(*) as row_count,
                    MAX(processed_at) as last_updated,
                    ARRAY_AGG({hash_field} IGNORE NULLS ORDER BY processed_at DESC LIMIT 1)[SAFE_OFFSET(0)] as representative_hash
                FROM `{self.project_id}.{table_name}`
                WHERE {date_field} = '{end_date}'
                """

            elif check_type == 'lookback_days':
                # Check for records in a lookback window from end_date
                # Used for historical data sources (e.g., player boxscores for last 30 days)
                lookback = config.get('lookback_days', 30)
                # Calculate lookback start date (datetime/timedelta already imported at module level)
                if isinstance(end_date, str):
                    end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
                else:
                    end_dt = end_date
                lookback_start = (end_dt - timedelta(days=lookback)).strftime('%Y-%m-%d')
                query = f"""
                SELECT
                    COUNT(*) as row_count,
                    MAX(processed_at) as last_updated,
                    ARRAY_AGG({hash_field} IGNORE NULLS ORDER BY processed_at DESC LIMIT 1)[SAFE_OFFSET(0)] as representative_hash
                FROM `{self.project_id}.{table_name}`
                WHERE {date_field} BETWEEN '{lookback_start}' AND '{end_date}'
                """

            elif check_type == 'existence':
                # Just check if any data exists (for reference tables)
                query = f"""
                SELECT
                    COUNT(*) as row_count,
                    MAX(processed_at) as last_updated,
                    ARRAY_AGG({hash_field} IGNORE NULLS ORDER BY processed_at DESC LIMIT 1)[SAFE_OFFSET(0)] as representative_hash
                FROM `{self.project_id}.{table_name}`
                LIMIT 1
                """

            else:
                raise ValueError(f"Unknown check_type: {check_type}")

            # Execute query
            result = list(self.bq_client.query(query).result(timeout=60))

            if not result:
                return False, {
                    'exists': False,
                    'row_count': 0,
                    'age_hours': None,
                    'last_updated': None,
                    'data_hash': None,
                    'error': 'No query results'
                }

            row = result[0]
            row_count = row.row_count
            last_updated = row.last_updated
            data_hash = row.representative_hash if hasattr(row, 'representative_hash') else None

            # Calculate age
            if last_updated:
                # Handle both timezone-aware and naive datetimes
                now_utc = datetime.now(timezone.utc)
                if last_updated.tzinfo is None:
                    # If last_updated is naive, assume UTC
                    age_hours = (now_utc.replace(tzinfo=None) - last_updated).total_seconds() / 3600
                else:
                    # Both are timezone-aware
                    age_hours = (now_utc - last_updated).total_seconds() / 3600
            else:
                age_hours = None

            # Determine if data exists - LENIENT CHECK
            # Data "exists" if ANY rows are present (row_count > 0)
            # This prevents false negatives that block the pipeline
            # The expected_count_min is used for warnings, not blocking
            expected_min = config.get('expected_count_min', 1)
            exists = row_count > 0  # LENIENT: any data = exists

            # Check if data is "sufficient" (meets expected threshold)
            sufficient = row_count >= expected_min

            # Log warning if data exists but is below expected threshold
            if exists and not sufficient and not self.is_backfill_mode:
                logger.warning(
                    f"{table_name}: Data exists ({row_count} rows) but below "
                    f"expected minimum ({expected_min}). Proceeding anyway."
                )

            details = {
                'exists': exists,
                'sufficient': sufficient,
                'row_count': row_count,
                'expected_count_min': expected_min,
                'age_hours': round(age_hours, 2) if age_hours else None,
                'last_updated': last_updated.isoformat() if last_updated else None,
                'data_hash': data_hash  # Representative hash from source data
            }

            logger.debug(f"{table_name}: {details}")

            return exists, details

        except GoogleAPIError as e:
            error_msg = f"Error checking {table_name}: {str(e)}"
            logger.error(error_msg)
            return False, {
                'exists': False,
                'data_hash': None,
                'error': error_msg
            }
    
    # Metadata tracking methods extracted to mixins/metadata_mixin.py
    # - track_source_usage()
    # - build_source_tracking_fields()
    # - get_previous_source_hashes()
    # - should_skip_processing()
    # - find_backfill_candidates()

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
                    self._send_notification(
                        notify_error,
                        title=f"Analytics Processor Configuration Error: {self.__class__.__name__}",
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
                self._send_notification(
                    notify_error,
                    title=f"Analytics Processor Client Initialization Failed: {self.__class__.__name__}",
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
        Extract raw data from source BigQuery tables for analytics processing.

        Subclasses must implement this method to:
        1. Query upstream tables (boxscores, play-by-play, etc.)
        2. Store results in self.raw_data (typically a pandas DataFrame)
        3. Handle the date range from self.opts['start_date'] to self.opts['end_date']

        This method is called AFTER dependency checking passes, so all required
        upstream tables should have data available.

        Example:
            def extract_raw_data(self) -> None:
                query = '''
                    SELECT player_id, game_date, points, rebounds, assists
                    FROM `{project}.{dataset}.bdl_boxscores`
                    WHERE game_date BETWEEN @start_date AND @end_date
                '''.format(project=self.project_id, dataset=self.raw_dataset)

                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter('start_date', 'DATE', self.opts['start_date']),
                        bigquery.ScalarQueryParameter('end_date', 'DATE', self.opts['end_date']),
                    ]
                )
                self.raw_data = self.bq_client.query(query, job_config=job_config).to_dataframe()
        """
        raise NotImplementedError("Child classes must implement extract_raw_data()")
    
    def validate_extracted_data(self) -> None:
        """Validate extracted data - child classes override."""
        if self.raw_data is None or (hasattr(self.raw_data, 'empty') and self.raw_data.empty):
            try:
                self._send_notification(
                    notify_warning,
                    title=f"Analytics Processor No Data Extracted: {self.__class__.__name__}",
                    message="No data extracted from raw tables",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'date_range': f"{self.opts.get('start_date')} to {self.opts.get('end_date')}"
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise ValueError("No data extracted")
    
    def calculate_analytics(self) -> None:
        """
        Calculate analytics metrics from extracted raw data.

        Subclasses must implement this method to:
        1. Process self.raw_data (typically a pandas DataFrame)
        2. Calculate derived metrics (rolling averages, rates, trends, etc.)
        3. Store results in self.transformed_data as List[Dict]
        4. Include source tracking via self.build_source_tracking_fields()

        Each record should include both business fields and source tracking:
        - Business fields: player_id, game_date, points_per_game, etc.
        - Source tracking: processed_at, run_id, data_version, etc.

        Example:
            def calculate_analytics(self) -> None:
                results = []
                for player_id, group in self.raw_data.groupby('player_id'):
                    avg_pts = group['points'].rolling(window=5).mean().iloc[-1]
                    results.append({
                        'player_id': player_id,
                        'game_date': self.opts['end_date'],
                        'points_5_game_avg': avg_pts,
                        **self.build_source_tracking_fields()
                    })
                self.transformed_data = results
        """
        raise NotImplementedError("Child classes must implement calculate_analytics()")
    
    # =========================================================================
    # Save to BigQuery
    # =========================================================================
    
    def save_analytics(self) -> None:
        """
        Save calculated analytics to BigQuery using batch loading.

        Converts self.transformed_data to NDJSON format and loads to the
        target table specified by self.table_name in the analytics dataset.

        Uses batch loading (load_table_from_file) instead of streaming inserts
        for better reliability and to avoid streaming buffer conflicts.

        The method handles:
        - Schema enforcement from target table
        - Retry logic for serialization conflicts
        - Graceful handling of streaming buffer conflicts
        - Statistics tracking (rows_inserted)

        Raises:
            Exception: On BigQuery load failures after retries
        """
        if not self.transformed_data:
            logger.warning("No transformed data to save")
            try:
                self._send_notification(
                    notify_warning,
                    title=f"Analytics Processor No Data to Save: {self.__class__.__name__}",
                    message="No analytics data calculated to save",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'raw_data_exists': self.raw_data is not None,
                        'date_range': f"{self.opts.get('start_date')} to {self.opts.get('end_date')}"
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return

        table_id = f"{self.project_id}.{self.get_output_dataset()}.{self.table_name}"

        # Handle different data types
        if isinstance(self.transformed_data, list):
            rows = self.transformed_data
        elif isinstance(self.transformed_data, dict):
            rows = [self.transformed_data]
        else:
            error_msg = f"Unexpected data type: {type(self.transformed_data)}"
            try:
                self._send_notification(
                    notify_error,
                    title=f"Analytics Processor Data Type Error: {self.__class__.__name__}",
                    message=error_msg,
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'data_type': str(type(self.transformed_data)),
                        'expected_types': ['list', 'dict']
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise ValueError(error_msg)
        
        if not rows:
            logger.warning("No rows to insert")
            return

        # Get target table schema (needed for both MERGE and INSERT strategies)
        try:
            table = self.bq_client.get_table(table_id)
            table_schema = table.schema
            logger.info(f"Using schema with {len(table_schema)} fields")
        except (GoogleAPIError, NotFound) as schema_e:
            logger.warning(f"Could not get table schema: {schema_e}")
            table_schema = None

        # Apply processing strategy
        if self.processing_strategy == 'MERGE_UPDATE':
            # Use proper SQL MERGE (prevents duplicates, no streaming buffer issues)
            self._save_with_proper_merge(rows, table_id, table_schema)

            # Check for duplicates after successful merge
            self._check_for_duplicates_post_save()
            return  # MERGE handles everything, we're done

        # For non-MERGE strategies, use batch INSERT via BigQuery load job
        logger.info(f"Inserting {len(rows)} rows to {table_id} using batch INSERT")

        try:
            import io
            
            # Sanitize and convert to NDJSON
            sanitized_rows = []
            for i, row in enumerate(rows):
                try:
                    sanitized = self._sanitize_row_for_json(row)
                    # Validate JSON serialization
                    json.dumps(sanitized)
                    sanitized_rows.append(sanitized)
                except (TypeError, ValueError) as e:
                    logger.warning(f"Skipping row {i} due to JSON error: {e}")
                    continue

            if not sanitized_rows:
                logger.warning("No valid rows after sanitization")
                return

            ndjson_data = "\n".join(json.dumps(row) for row in sanitized_rows)
            ndjson_bytes = ndjson_data.encode('utf-8')
            logger.info(f"Sanitized {len(sanitized_rows)}/{len(rows)} rows for JSON")
            
            # Configure load job
            job_config = bigquery.LoadJobConfig(
                schema=table_schema,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                autodetect=(table_schema is None),  # Auto-detect schema on first run when table doesn't exist
                schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION]  # Allow adding new fields (Session 107 metrics)
            )
            
            # Load to target table
            load_job = self.bq_client.load_table_from_file(
                io.BytesIO(ndjson_bytes),
                table_id,
                job_config=job_config
            )
            
            # Wait for completion
            try:
                load_job.result(timeout=300)
                logger.info(f"✅ Successfully loaded {len(sanitized_rows)} rows")
                self.stats["rows_processed"] = len(sanitized_rows)

                # Check for duplicates after successful save
                self._check_for_duplicates_post_save()

            except Exception as load_e:
                if "streaming buffer" in str(load_e).lower():
                    logger.warning(f"⚠️ Load blocked by streaming buffer - {len(rows)} rows skipped")
                    logger.info("Records will be processed on next run")
                    self.stats["rows_skipped"] = len(rows)
                    self.stats["rows_processed"] = 0
                    return
                else:
                    # Log detailed error info from BigQuery load job
                    if hasattr(load_job, 'errors') and load_job.errors:
                        logger.error(f"BigQuery load job errors ({len(load_job.errors)} total):")
                        for i, error in enumerate(load_job.errors[:10]):  # Log first 10
                            logger.error(f"  Error {i+1}: {error}")
                    # Log sample of problematic rows
                    if sanitized_rows and len(sanitized_rows) > 0:
                        logger.error(f"Sample row keys: {list(sanitized_rows[0].keys())}")
                        # Log first row for debugging
                        try:
                            sample_row = {k: (v if not isinstance(v, str) or len(str(v)) < 100 else str(v)[:100]+'...') for k, v in sanitized_rows[0].items()}
                            logger.error(f"Sample row (truncated): {json.dumps(sample_row, default=str)}")
                        except Exception as sample_e:
                            logger.error(f"Could not log sample row: {sample_e}")
                    raise load_e
            
        except Exception as e:
            error_msg = f"Batch insert failed: {str(e)}"
            logger.error(error_msg)
            try:
                self._send_notification(
                    notify_error,
                    title=f"Analytics Processor Batch Insert Failed: {self.__class__.__name__}",
                    message=f"Failed to batch insert {len(rows)} analytics rows",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': table_id,
                        'rows_attempted': len(rows),
                        'error_type': type(e).__name__,
                        'error': str(e),
                        'date_range': f"{self.opts.get('start_date')} to {self.opts.get('end_date')}"
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

    def _save_with_proper_merge(self, rows: List[Dict], table_id: str, table_schema) -> None:
        """
        Save data using proper SQL MERGE statement with comprehensive validation.

        This method:
        1. Validates all inputs before proceeding
        2. Loads data into a temporary table
        3. Executes a SQL MERGE statement to upsert records
        4. Falls back to DELETE+INSERT if MERGE fails
        5. Cleans up the temporary table

        Advantages:
        - Single atomic operation (no streaming buffer issues)
        - No duplicates created
        - Proper upsert semantics
        - Automatic fallback on failure

        Updated: 2026-01-15 Session 56 - Added comprehensive validation and auto-fallback
        """
        import io
        import uuid

        # ============================================
        # VALIDATION PHASE - Fail fast with clear errors
        # ============================================

        if not rows:
            logger.warning("No rows to merge")
            return

        # Check if PRIMARY_KEY_FIELDS is defined
        if not hasattr(self.__class__, 'PRIMARY_KEY_FIELDS'):
            logger.warning(f"PRIMARY_KEY_FIELDS not defined for {self.__class__.__name__} - using DELETE + INSERT")
            self._save_with_delete_insert(rows, table_id, table_schema)
            return

        primary_keys = self.__class__.PRIMARY_KEY_FIELDS
        if not primary_keys or len(primary_keys) == 0:
            logger.warning(f"PRIMARY_KEY_FIELDS is empty - using DELETE + INSERT")
            self._save_with_delete_insert(rows, table_id, table_schema)
            return

        # ============================================
        # SANITIZATION PHASE
        # ============================================

        sanitized_rows = []
        for i, row in enumerate(rows):
            try:
                sanitized = self._sanitize_row_for_json(row)
                json.dumps(sanitized)  # Validate JSON serialization
                sanitized_rows.append(sanitized)
            except (TypeError, ValueError) as e:
                logger.warning(f"Skipping row {i} due to JSON error: {e}")
                continue

        if not sanitized_rows:
            logger.warning("No valid rows after sanitization")
            return

        # ============================================
        # FIELD ANALYSIS PHASE
        # ============================================

        # Get all field names from schema or fallback to row keys
        if table_schema and len(table_schema) > 0:
            schema_fields = [field.name for field in table_schema]
            # Also include fields from data that might not be in schema yet (Session 107 metrics)
            data_fields = list(sanitized_rows[0].keys()) if sanitized_rows else []
            # Merge: schema fields first, then any new fields from data
            all_fields = schema_fields + [f for f in data_fields if f not in schema_fields]
            logger.debug(f"Using {len(schema_fields)} schema fields + {len(all_fields) - len(schema_fields)} new data fields = {len(all_fields)} total")
        else:
            # Fallback: use keys from first row
            all_fields = list(sanitized_rows[0].keys()) if sanitized_rows else []
            logger.warning(f"No schema provided, using {len(all_fields)} fields from row keys")

        # CRITICAL VALIDATION: Ensure we have fields
        if not all_fields:
            logger.error("CRITICAL: No fields found in schema or row data - falling back to DELETE + INSERT")
            self._save_with_delete_insert(rows, table_id, table_schema)
            return

        # Validate primary keys exist in all_fields
        missing_pks = [pk for pk in primary_keys if pk not in all_fields]
        if missing_pks:
            logger.error(f"CRITICAL: Primary keys {missing_pks} not in fields - falling back to DELETE + INSERT")
            self._save_with_delete_insert(rows, table_id, table_schema)
            return

        # Fields to update (all except primary keys)
        update_fields = [f for f in all_fields if f not in primary_keys]

        # ============================================
        # QUERY CONSTRUCTION PHASE
        # ============================================

        def quote_identifier(name: str) -> str:
            """Safely quote BigQuery identifier."""
            if name is None:
                return '`NULL`'
            return f"`{str(name).replace('`', '')}`"

        # Build ON clause
        on_clause = ' AND '.join([
            f"target.{quote_identifier(key)} = source.{quote_identifier(key)}"
            for key in primary_keys
        ])

        # CRITICAL: Handle empty update_fields gracefully
        if not update_fields:
            logger.warning("No non-key fields to update - using no-op MERGE")
            update_set = f"{quote_identifier(primary_keys[0])} = source.{quote_identifier(primary_keys[0])}"
        else:
            update_set = ', '.join([
                f"{quote_identifier(f)} = source.{quote_identifier(f)}"
                for f in update_fields
            ])

        # CRITICAL VALIDATION: Ensure update_set is not empty
        if not update_set or len(update_set.strip()) == 0:
            logger.error(f"CRITICAL: update_set is empty! primary_keys={primary_keys}, update_fields={update_fields}")
            logger.error("Falling back to DELETE + INSERT")
            self._save_with_delete_insert(rows, table_id, table_schema)
            return

        # Build INSERT clause
        insert_fields = ', '.join([quote_identifier(f) for f in all_fields])
        insert_values = ', '.join([f"source.{quote_identifier(f)}" for f in all_fields])

        # Partition by clause for deduplication
        primary_keys_partition = ', '.join(primary_keys)

        # Build partition filter for BigQuery optimization
        partition_prefix = ""
        if 'game_date' in all_fields and sanitized_rows:
            game_dates = sorted(set(
                str(row.get('game_date')) for row in sanitized_rows
                if row.get('game_date') is not None
            ))
            if game_dates:
                if len(game_dates) == 1:
                    partition_prefix = f"target.game_date = DATE('{game_dates[0]}') AND "
                else:
                    # Build proper IN clause: DATE('2026-01-13'), DATE('2026-01-14')
                    dates_list = [f"DATE('{d}')" for d in game_dates]
                    partition_prefix = f"target.game_date IN ({', '.join(dates_list)}) AND "
                logger.debug(f"Adding partition filter for {len(game_dates)} dates")

        # ============================================
        # TEMP TABLE PHASE
        # ============================================

        temp_table_name = f"{self.table_name}_temp_{uuid.uuid4().hex[:8]}"
        temp_table_id = f"{self.project_id}.{self.get_output_dataset()}.{temp_table_name}"

        logger.info(f"Using SQL MERGE with temp table: {temp_table_name}")
        logger.info(f"MERGE config: {len(sanitized_rows)} rows, {len(all_fields)} fields, {len(update_fields)} update fields")

        merge_query = None  # Define for error logging

        try:
            # Load data into temp table
            ndjson_data = "\n".join(json.dumps(row) for row in sanitized_rows)
            ndjson_bytes = ndjson_data.encode('utf-8')

            job_config = bigquery.LoadJobConfig(
                schema=table_schema,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                autodetect=(table_schema is None),
                # Note: schema_update_options not compatible with WRITE_TRUNCATE on non-partitioned tables
                # Temp table doesn't need schema updates - it's recreated each time
            )

            load_job = self.bq_client.load_table_from_file(
                io.BytesIO(ndjson_bytes),
                temp_table_id,
                job_config=job_config
            )
            load_job.result(timeout=300)
            logger.info(f"✅ Loaded {len(sanitized_rows)} rows into temp table")

            # ============================================
            # MERGE EXECUTION PHASE
            # ============================================

            merge_query = f"""
            MERGE `{table_id}` AS target
            USING (
                SELECT * EXCEPT(__row_num) FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY {primary_keys_partition}
                        ORDER BY processed_at DESC
                    ) as __row_num
                    FROM `{temp_table_id}`
                ) WHERE __row_num = 1
            ) AS source
            ON {partition_prefix}{on_clause}
            WHEN MATCHED THEN
                UPDATE SET {update_set}
            WHEN NOT MATCHED THEN
                INSERT ({insert_fields})
                VALUES ({insert_values})
            """

            # ALWAYS log key details at INFO level for debugging
            logger.info(f"Executing MERGE on primary keys: {', '.join(primary_keys)}")
            logger.info(f"MERGE DEBUG - update_set ({len(update_set)} chars): '{update_set[:100]}...'")

            merge_job = self.bq_client.query(merge_query)
            merge_result = merge_job.result(timeout=300)

            # Get stats
            affected = merge_job.num_dml_affected_rows or 0
            logger.info(f"✅ MERGE completed: {affected} rows affected")
            self.stats["rows_processed"] = len(sanitized_rows)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"MERGE failed: {error_msg}")

            # Log the full query for debugging
            if merge_query:
                logger.error(f"Failed MERGE query:\n{merge_query}")

            # Auto-fallback: If syntax error, use DELETE+INSERT
            if "syntax error" in error_msg.lower() or "400" in error_msg:
                logger.warning("MERGE syntax error detected - falling back to DELETE + INSERT")

                # Notify operators about MERGE fallback (added 2026-01-24)
                # This was previously a silent fallback that could mask data issues
                try:
                    notify_warning(
                        title=f"MERGE Fallback: {self.__class__.__name__}",
                        message=f"MERGE failed with syntax error, falling back to DELETE + INSERT",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': getattr(self, 'run_id', 'unknown'),
                            'table': table_id,
                            'error': error_msg[:500],  # Truncate long errors
                            'rows_affected': len(rows),
                            'strategy': 'DELETE + INSERT (fallback)',
                            'remediation': 'Check MERGE query syntax. This is not critical but may indicate schema issues.',
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send MERGE fallback notification: {notify_ex}")

                try:
                    self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                except Exception as cleanup_e:
                    logger.debug(f"Could not delete temp table during fallback: {cleanup_e}")
                self._save_with_delete_insert(rows, table_id, table_schema)
                return

            raise

        finally:
            # Always clean up temp table
            try:
                self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                logger.debug(f"Cleaned up temp table: {temp_table_name}")
            except Exception as cleanup_e:
                logger.warning(f"Could not clean up temp table: {cleanup_e}")

    def _save_with_delete_insert(self, rows: List[Dict], table_id: str, table_schema) -> None:
        """
        Save rows using DELETE + INSERT strategy (simpler, more reliable fallback).

        This method:
        1. Deletes existing records for the game_dates in the data
        2. Inserts new records via batch load

        Benefits:
        - Simpler SQL, fewer edge cases
        - Works reliably when MERGE fails
        - Still prevents duplicates (via DELETE first)

        Drawbacks:
        - Not fully atomic (small window between DELETE and INSERT)
        - Deletes ALL records for the dates, even unchanged ones

        Added: 2026-01-15 Session 56 - Fallback for MERGE failures
        """
        import io

        if not rows:
            logger.warning("No rows for DELETE + INSERT")
            return

        logger.info(f"Using DELETE + INSERT strategy for {len(rows)} rows")

        # Sanitize rows
        sanitized_rows = []
        for i, row in enumerate(rows):
            try:
                sanitized = self._sanitize_row_for_json(row)
                json.dumps(sanitized)
                sanitized_rows.append(sanitized)
            except (TypeError, ValueError) as e:
                logger.warning(f"Skipping row {i} due to JSON error: {e}")
                continue

        if not sanitized_rows:
            logger.warning("No valid rows after sanitization")
            return

        # Extract game_dates for DELETE
        game_dates = sorted(set(
            str(row.get('game_date')) for row in sanitized_rows
            if row.get('game_date') is not None
        ))

        if game_dates:
            # Step 1: DELETE existing records for these dates
            # Use parameterized query to prevent SQL injection
            if len(game_dates) == 1:
                delete_query = f"DELETE FROM `{table_id}` WHERE game_date = @game_date"
                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("game_date", "DATE", game_dates[0]),
                    ]
                )
            else:
                delete_query = f"DELETE FROM `{table_id}` WHERE game_date IN UNNEST(@game_dates)"
                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ArrayQueryParameter("game_dates", "DATE", game_dates),
                    ]
                )

            try:
                logger.info(f"Deleting existing records for {len(game_dates)} date(s)")
                delete_job = self.bq_client.query(delete_query, job_config=job_config)
                delete_job.result(timeout=300)
                deleted = delete_job.num_dml_affected_rows or 0
                logger.info(f"✅ Deleted {deleted} existing rows")
            except Exception as e:
                error_str = str(e).lower()
                if "not found" in error_str or "404" in error_str:
                    logger.info("Table doesn't exist yet - will be created on INSERT")
                elif "streaming buffer" in error_str:
                    logger.warning("Delete blocked by streaming buffer - proceeding with INSERT")
                else:
                    logger.error(f"DELETE failed: {e}")
                    raise

        # Step 2: INSERT new records using batch load
        ndjson_data = "\n".join(json.dumps(row) for row in sanitized_rows)
        ndjson_bytes = ndjson_data.encode('utf-8')

        job_config = bigquery.LoadJobConfig(
            schema=table_schema,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            autodetect=(table_schema is None),
            schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION]  # Allow adding new fields (Session 107 metrics)
        )

        try:
            logger.info(f"Inserting {len(sanitized_rows)} rows")
            load_job = self.bq_client.load_table_from_file(
                io.BytesIO(ndjson_bytes),
                table_id,
                job_config=job_config
            )
            load_job.result(timeout=300)
            logger.info(f"✅ INSERT completed: {len(sanitized_rows)} rows inserted")
            self.stats["rows_processed"] = len(sanitized_rows)
        except Exception as e:
            logger.error(f"INSERT failed: {e}")
            raise

    def _delete_existing_data_batch(self, rows: List[Dict]) -> None:
        """
        Delete existing data using batch DELETE query.

        DEPRECATED: Use _save_with_proper_merge() instead.
        This method is kept for backwards compatibility.
        """
        if not rows:
            return

        table_id = f"{self.project_id}.{self.get_output_dataset()}.{self.table_name}"

        # Get date range from opts
        start_date = self.opts.get('start_date')
        end_date = self.opts.get('end_date')
        
        if start_date and end_date:
            delete_query = f"""
            DELETE FROM `{table_id}`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            """
            
            logger.info(f"Deleting existing data for {start_date} to {end_date}")
            
            try:
                delete_job = self.bq_client.query(delete_query)
                delete_job.result(timeout=300)
                
                if delete_job.num_dml_affected_rows is not None:
                    logger.info(f"✅ Deleted {delete_job.num_dml_affected_rows} existing rows")
                else:
                    logger.info(f"✅ Delete completed for date range")
                    
            except Exception as e:
                error_str = str(e).lower()
                if "streaming buffer" in error_str:
                    logger.warning("⚠️ Delete blocked by streaming buffer")
                    logger.info("Duplicates will be cleaned up on next run")
                    return
                elif "not found" in error_str or "404" in error_str:
                    logger.info("✅ Table doesn't exist yet (first run) - will be created during INSERT")
                    return
                else:
                    raise e

    # Quality methods extracted to mixins/quality_mixin.py
    # - _check_for_duplicates_post_save()
    # - log_quality_issue()

    # =========================================================================
    # Logging & Monitoring
    # =========================================================================
    
    def log_processing_run(self, success: bool, error: str = None, skip_reason: str = None) -> None:
        """
        Log processing run to monitoring table.
        Uses batch loading to avoid streaming buffer issues.

        Args:
            success: Whether the processing run succeeded
            error: Optional error message if failed
            skip_reason: Optional reason if processing was skipped (early exit)
        """
        run_record = {
            'processor_name': self.__class__.__name__,
            'run_id': self.run_id,
            'run_date': datetime.now(timezone.utc).isoformat(),
            'success': success,
            'date_range_start': self.opts.get('start_date'),
            'date_range_end': self.opts.get('end_date'),
            'records_processed': self.stats.get('rows_processed', 0),
            'duration_seconds': float(self.stats.get('total_runtime', 0.0)),
            'errors_json': json.dumps([error] if error else []),
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        # Track skip reason if provided (early exit scenarios)
        if skip_reason:
            self.stats['skip_reason'] = skip_reason
            run_record['skip_reason'] = skip_reason

        try:
            table_id = f"{self.project_id}.nba_processing.analytics_processor_runs"

            # Get table reference for schema
            table_ref = self.bq_client.get_table(table_id)

            # Use batch loading instead of streaming inserts
            # This avoids the 90-minute streaming buffer that blocks DML operations
            # See: docs/05-development/guides/bigquery-best-practices.md
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
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
        }

        # Merge analytics stats
        analytics_stats = self.get_analytics_stats()
        if isinstance(analytics_stats, dict):
            summary.update(analytics_stats)

        logger.info("ANALYTICS_STATS %s", json.dumps(summary))

        # Publish completion message to trigger Phase 4 (if target table is set)
        # Can be disabled with skip_downstream_trigger flag for backfills
        if self.opts.get('skip_downstream_trigger', False):
            logger.info(
                f"⏸️  Skipping downstream trigger (backfill mode) - "
                f"Phase 4 will not be auto-triggered for {self.table_name}"
            )
        elif self.table_name:
            self._publish_completion_message(success=True)
    
    def get_analytics_stats(self) -> Dict:
        """Get analytics stats - child classes override."""
        return {}

    def save_registry_failures(self) -> None:
        """
        Save registry failure records to BigQuery for reprocessing workflow.

        This enables tracking of players who couldn't be found in the registry
        during Phase 3 processing. The table supports a full lifecycle:
        - PENDING: created_at set, waiting for alias
        - RESOLVED: resolved_at set (by resolve_unresolved_batch.py)
        - REPROCESSED: reprocessed_at set (by reprocess_resolved.py)

        Each child processor should populate self.registry_failures with dicts containing:
        - player_lookup: raw name that failed lookup
        - game_date: when the player played
        - team_abbr: team context (optional)
        - season: season string (optional)
        - game_id: specific game ID (optional)
        """
        if not self.registry_failures:
            return

        try:
            table_id = f"{self.project_id}.nba_processing.registry_failures"

            # Deduplicate by (player_lookup, game_date) - keep first occurrence
            seen = set()
            unique_failures = []
            for failure in self.registry_failures:
                key = (failure.get('player_lookup'), str(failure.get('game_date')))
                if key not in seen:
                    seen.add(key)
                    unique_failures.append(failure)

            failure_records = []
            for failure in unique_failures:
                # Convert game_date to string if needed
                game_date = failure.get('game_date')
                if hasattr(game_date, 'isoformat'):
                    game_date_str = game_date.isoformat()
                else:
                    game_date_str = str(game_date)

                failure_records.append({
                    'player_lookup': failure.get('player_lookup', 'unknown'),
                    'game_date': game_date_str,
                    'processor_name': self.__class__.__name__,
                    'team_abbr': failure.get('team_abbr'),
                    'season': failure.get('season'),
                    'game_id': failure.get('game_id'),
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'resolved_at': None,
                    'reprocessed_at': None,
                    'occurrence_count': 1,
                    'run_id': self.run_id
                })

            # Insert in batches of 500 to avoid hitting limits
            # Use batch loading to avoid streaming buffer issues
            # See: docs/05-development/guides/bigquery-best-practices.md
            batch_size = 500
            for i in range(0, len(failure_records), batch_size):
                batch = failure_records[i:i + batch_size]

                # Get table reference for schema
                table_ref = self.bq_client.get_table(table_id)

                # Use batch loading instead of streaming inserts
                # This avoids the 90-minute streaming buffer that blocks DML operations
                job_config = bigquery.LoadJobConfig(
                    schema=table_ref.schema,
                    autodetect=False,
                    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                    ignore_unknown_values=True
                )

                load_job = self.bq_client.load_table_from_json(batch, table_id, job_config=job_config)
                load_job.result(timeout=300)

                if load_job.errors:
                    logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")

            logger.info(f"📊 Saved {len(failure_records)} registry failures to registry_failures table")

            # Store in stats for reporting
            self.stats['registry_failures_count'] = len(failure_records)
            self.stats['registry_failures_players'] = len(set(f.get('player_lookup') for f in unique_failures))

        except GoogleAPIError as e:
            logger.warning(f"Failed to save registry failure records: {e}")

    def record_failure(
        self,
        entity_id: str,
        entity_type: str,
        category: str,
        reason: str,
        can_retry: bool = False,
        **kwargs
    ) -> None:
        """
        Record an entity failure for later saving to analytics_failures table.

        Phase 3 equivalent of precompute_base.py's failure tracking.

        Args:
            entity_id: Player lookup, team abbr, or game_id
            entity_type: 'PLAYER', 'TEAM', or 'GAME'
            category: Failure category (e.g., 'MISSING_DATA', 'PROCESSING_ERROR')
            reason: Human-readable description
            can_retry: Whether reprocessing might succeed
            **kwargs: Optional enhanced fields:
                - failure_type: 'PLAYER_DNP', 'DATA_GAP', 'MIXED', 'UNKNOWN'
                - is_correctable: bool
                - expected_count: int
                - actual_count: int
                - missing_game_ids: List[str]

        Example:
            self.record_failure(
                entity_id='zachlavine',
                entity_type='PLAYER',
                category='INCOMPLETE_DATA',
                reason='Missing 2 games in lookback window',
                can_retry=True,
                failure_type='PLAYER_DNP',
                is_correctable=False,
                expected_count=5,
                actual_count=3
            )
        """
        failure = {
            'entity_id': entity_id,
            'entity_type': entity_type,
            'category': category,
            'reason': reason,
            'can_retry': can_retry
        }

        # Add optional enhanced fields
        for key in ['failure_type', 'is_correctable', 'expected_count', 'actual_count',
                    'missing_game_ids', 'raw_data_checked']:
            if key in kwargs:
                failure[key] = kwargs[key]

        self.failed_entities.append(failure)

    def classify_recorded_failures(self, analysis_date=None) -> int:
        """
        Enrich INCOMPLETE_DATA failures with DNP vs DATA_GAP classification.

        This method should be called after processing but before save_failures_to_bq().
        It queries expected vs actual game dates for each failed player entity and
        determines if the failure is due to:
        - PLAYER_DNP: Player didn't play (expected, not correctable)
        - DATA_GAP: Player played but data is missing (correctable)
        - MIXED: Some games DNP, some gaps
        - INSUFFICIENT_HISTORY: Early season, not enough games yet

        Only processes INCOMPLETE_DATA failures for player entities.
        Team-based failures are skipped since teams always play their games.

        Args:
            analysis_date: Date being analyzed. If None, uses self.opts['end_date'] or 'start_date'

        Returns:
            int: Number of failures that were classified

        Example:
            # In processor, after recording failures:
            num_classified = self.classify_recorded_failures()
            logger.info(f"Classified {num_classified} failures")
            self.save_failures_to_bq()
        """
        if not self.failed_entities:
            return 0

        # Get analysis date
        if analysis_date is None:
            analysis_date = self.opts.get('end_date') or self.opts.get('start_date')
        if hasattr(analysis_date, 'isoformat'):
            pass  # Already a date object
        elif isinstance(analysis_date, str):
            from datetime import datetime as dt
            analysis_date = dt.strptime(analysis_date, '%Y-%m-%d').date()

        if not analysis_date:
            logger.warning("classify_recorded_failures: No analysis_date available")
            return 0

        # Check if this is a player-based processor (not team-based)
        processor_name = self.__class__.__name__
        is_player_processor = any(x in processor_name.lower() for x in [
            'player', 'pgs', 'upgc', 'upcoming'
        ])

        if not is_player_processor:
            logger.debug(f"Skipping failure classification for non-player processor: {processor_name}")
            return 0

        # Find INCOMPLETE_DATA failures that need classification
        failures_to_classify = []
        for i, failure in enumerate(self.failed_entities):
            if failure.get('category') == 'INCOMPLETE_DATA':
                if 'failure_type' not in failure:  # Not already classified
                    failures_to_classify.append((i, failure))

        if not failures_to_classify:
            return 0

        try:
            # Get completeness checker
            if not hasattr(self, 'completeness_checker') or self.completeness_checker is None:
                from shared.utils.completeness_checker import CompletenessChecker
                self.completeness_checker = CompletenessChecker(self.bq_client, self.project_id)

            # Batch get game dates for all failed players
            player_lookups = [f.get('entity_id') for _, f in failures_to_classify if f.get('entity_id')]

            if not player_lookups:
                return 0

            # Get expected and actual game dates for all failed players
            game_dates_batch = self.completeness_checker.get_player_game_dates_batch(
                player_lookups=player_lookups,
                analysis_date=analysis_date,
                lookback_days=14  # Standard L14 lookback
            )

            classified_count = 0
            for idx, failure in failures_to_classify:
                entity_id = failure.get('entity_id')
                if not entity_id:
                    continue

                # Normalize to match batch results
                from shared.utils.player_name_normalizer import normalize_name_for_lookup
                normalized_id = normalize_name_for_lookup(entity_id)

                game_dates = game_dates_batch.get(normalized_id, {})
                if game_dates.get('error'):
                    continue

                expected_games = game_dates.get('expected_games', [])
                actual_games = game_dates.get('actual_games', [])

                if not expected_games:
                    # Can't classify without expected games
                    continue

                # Classify the failure
                classification = self.completeness_checker.classify_failure(
                    player_lookup=entity_id,
                    analysis_date=analysis_date,
                    expected_games=expected_games,
                    actual_games=actual_games,
                    check_raw_data=True
                )

                # Update the failure record with classification data
                self.failed_entities[idx].update({
                    'failure_type': classification['failure_type'],
                    'is_correctable': classification['is_correctable'],
                    'expected_count': classification['expected_count'],
                    'actual_count': classification['actual_count'],
                    'missing_dates': classification['missing_dates'],
                    'raw_data_checked': classification['raw_data_checked']
                })
                classified_count += 1

            logger.info(
                f"Classified {classified_count}/{len(failures_to_classify)} "
                f"INCOMPLETE_DATA failures for {processor_name}"
            )
            return classified_count

        except GoogleAPIError as e:
            logger.warning(f"Error classifying failures: {e}")
            return 0

    def save_failures_to_bq(self) -> None:
        """
        Save failed entity records to analytics_failures BigQuery table.

        This method is called at the end of processing (in finalize() or manually)
        to persist any failures that were recorded during processing.

        Schema matches nba_processing.analytics_failures:
            - processor_name, run_id, analysis_date, entity_id, entity_type
            - failure_category, failure_reason, can_retry
            - failure_type, is_correctable (enhanced tracking)
            - expected_record_count, actual_record_count, missing_game_ids
            - resolution_status, created_at
        """
        if not self.failed_entities:
            return

        # Auto-classify INCOMPLETE_DATA failures before saving
        # This adds DNP vs DATA_GAP classification for player processors
        try:
            self.classify_recorded_failures()
        except Exception as classify_e:
            logger.warning(f"Could not classify failures (continuing anyway): {classify_e}")

        try:
            table_id = f"{self.project_id}.nba_processing.analytics_failures"
            analysis_date = self.opts.get('end_date') or self.opts.get('start_date')

            # Convert analysis_date to string if needed
            if hasattr(analysis_date, 'isoformat'):
                date_str = analysis_date.isoformat()
            else:
                date_str = str(analysis_date)

            failure_records = []
            for failure in self.failed_entities:
                # Build base record
                record = {
                    'processor_name': self.__class__.__name__,
                    'run_id': self.run_id,
                    'analysis_date': date_str,
                    'entity_id': failure.get('entity_id', 'unknown'),
                    'entity_type': failure.get('entity_type', 'UNKNOWN'),
                    'failure_category': failure.get('category', 'UNKNOWN'),
                    'failure_reason': str(failure.get('reason', ''))[:1000],
                    'can_retry': failure.get('can_retry', False),
                    'created_at': datetime.now(timezone.utc).isoformat()
                }

                # Add enhanced failure tracking fields (if provided)
                if 'failure_type' in failure:
                    record['failure_type'] = failure['failure_type']
                if 'is_correctable' in failure:
                    record['is_correctable'] = failure['is_correctable']
                if 'expected_count' in failure:
                    record['expected_record_count'] = failure['expected_count']
                if 'actual_count' in failure:
                    record['actual_record_count'] = failure['actual_count']
                if 'missing_game_ids' in failure:
                    missing = failure['missing_game_ids']
                    if isinstance(missing, list):
                        record['missing_game_ids'] = json.dumps(missing)
                    else:
                        record['missing_game_ids'] = str(missing)

                # Resolution tracking - default to UNRESOLVED
                record['resolution_status'] = failure.get('resolution_status', 'UNRESOLVED')

                failure_records.append(record)

            # Insert in batches of 500
            # Use batch loading to avoid streaming buffer issues
            # See: docs/05-development/guides/bigquery-best-practices.md
            batch_size = 500
            for i in range(0, len(failure_records), batch_size):
                batch = failure_records[i:i + batch_size]

                # Get table reference for schema
                table_ref = self.bq_client.get_table(table_id)

                # Use batch loading instead of streaming inserts
                # This avoids the 90-minute streaming buffer that blocks DML operations
                job_config = bigquery.LoadJobConfig(
                    schema=table_ref.schema,
                    autodetect=False,
                    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                    ignore_unknown_values=True
                )

                load_job = self.bq_client.load_table_from_json(batch, table_id, job_config=job_config)
                load_job.result(timeout=300)

                if load_job.errors:
                    logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")

            logger.info(f"📊 Saved {len(failure_records)} failures to analytics_failures table")

            # Store in stats
            self.stats['failures_recorded'] = len(failure_records)

        except GoogleAPIError as e:
            logger.warning(f"Failed to save failure records to BQ: {e}")

    def _publish_completion_message(self, success: bool, error: str = None) -> None:
        """
        Publish unified completion message to nba-phase3-analytics-complete topic.
        This triggers Phase 4 precompute processors that depend on this analytics table.

        Uses UnifiedPubSubPublisher for consistent message format across all phases.

        Args:
            success: Whether processing completed successfully
            error: Optional error message if failed
        """
        try:
            # Use unified publisher
            publisher = UnifiedPubSubPublisher(project_id=self.project_id)

            # Get the analysis date (use end_date for single-date processing)
            analysis_date = self.opts.get('end_date')
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
                topic='nba-phase3-analytics-complete',
                processor_name=self.__class__.__name__,
                phase='phase_3_analytics',
                execution_id=self.run_id,
                correlation_id=self.correlation_id or self.run_id,
                game_date=str(analysis_date),
                output_table=self.table_name,
                output_dataset=self.dataset_id,
                status=status,
                record_count=self.stats.get('rows_processed', 0),
                records_failed=0,  # Could track partial failures
                parent_processor=self.parent_processor,
                trigger_source=self.opts.get('trigger_source', 'manual'),
                trigger_message_id=self.trigger_message_id,
                duration_seconds=duration_seconds,
                error_message=error,
                error_type=type(error).__name__ if error else None,
                metadata={
                    # Analytics-specific metadata
                    'is_incremental': self.stats.get('is_incremental', False),
                    'entities_changed_count': self.stats.get('entities_changed_count'),
                    'entities_total': self.stats.get('entities_total'),
                    'efficiency_gain_pct': self.stats.get('efficiency_gain_pct'),
                    'change_detection_time': self.stats.get('change_detection_time'),

                    # Pass changed entities to downstream (Phase 4)
                    'entities_changed': self.entities_changed if self.is_incremental_run else [],

                    # Standard stats
                    'extract_time': self.stats.get('extract_time'),
                    'transform_time': self.stats.get('transform_time'),
                    'save_time': self.stats.get('save_time')
                },
                skip_downstream=self.opts.get('skip_downstream_trigger', False)
            )

            if message_id:
                logger.info(
                    f"✅ Published unified completion message to nba-phase3-analytics-complete "
                    f"(message_id: {message_id}, correlation_id: {self.correlation_id})"
                )
            else:
                logger.info("⏸️  Skipped publishing (backfill mode or skip_downstream_trigger=True)")

        except GoogleAPIError as e:
            logger.warning(f"Failed to publish completion message: {e}")
            # Don't fail the whole processor if Pub/Sub publishing fails

    # Note: Time Tracking (mark_time, get_elapsed_seconds) and Error Handling
    # (step_info, report_error, _save_partial_data) methods are inherited from
    # TransformProcessorBase