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
from data_processors.analytics.mixins.dependency_mixin import DependencyMixin

# Import analytics operations
from data_processors.analytics.operations.bigquery_save_ops import BigQuerySaveOpsMixin
from data_processors.analytics.operations.failure_tracking import FailureTrackingMixin

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


class AnalyticsProcessorBase(FailureTrackingMixin, BigQuerySaveOpsMixin, DependencyMixin, MetadataMixin, QualityMixin, TransformProcessorBase, SoftDependencyMixin, RunHistoryMixin):
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

        # Define analysis_date early so it's available for all logging throughout the run
        # INCLUDING exception handlers. This MUST be outside the try block.
        # This prevents "cannot access local variable 'analysis_date'" errors.
        analysis_date = opts.get('end_date') or opts.get('start_date') if opts else None

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
            # Update analysis_date with validated data_date
            # (Initial definition is outside try block to ensure availability in exception handlers)
            analysis_date = data_date
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

                    # Structured logging for dependency failures (added 2026-01-27)
                    # Enables post-mortem analysis of which deps failed and why
                    logger.error("dependency_check_failed", extra={
                        "event": "dependency_check_failed",
                        "processor": self.processor_name,
                        "game_date": str(analysis_date),
                        "missing_critical": dep_check['missing'],
                        "stale_fail": dep_check.get('stale_fail', []),
                        "dependency_details": {
                            table: {
                                "status": details.get('status'),
                                "last_update": str(details.get('last_update', '')),
                                "expected_update": str(details.get('expected_update', '')),
                                "staleness_hours": details.get('staleness_hours'),
                                "is_critical": details.get('is_critical', True)
                            }
                            for table, details in dep_check.get('details', {}).items()
                            if details.get('status') != 'available'
                        }
                    })

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

                # Structured logging for processor start with dependency status (added 2026-01-27)
                # Enables diagnosis of "why did X run before Y?" by showing when deps became available
                # Note: analysis_date is defined earlier in run() to ensure availability in all code paths
                logger.info("processor_started", extra={
                    "event": "processor_started",
                    "processor": self.processor_name,
                    "game_date": str(analysis_date) if analysis_date else None,
                    "start_time": datetime.now(timezone.utc).isoformat(),
                    "dependencies_status": {
                        dep_table: {
                            "status": dep_check['details'][dep_table].get('status', 'unknown'),
                            "last_update": str(dep_check['details'][dep_table].get('last_update', '')),
                            "staleness_hours": dep_check['details'][dep_table].get('staleness_hours')
                        }
                        for dep_table in dep_check.get('details', {})
                    },
                    "dependency_check_seconds": dep_check_seconds,
                    "all_dependencies_ready": dep_check['all_critical_present']
                })
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
                    # Note: analysis_date is defined earlier in run() to ensure availability in all code paths
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
            # Note: analysis_date is defined earlier in run() to ensure availability in all code paths
            # ═══════════════════════════════════════════════════════════════

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

            # Structured logging for phase timing (added 2026-01-27)
            # Enables timing correlation across processors and phases
            logger.info("phase_timing", extra={
                "event": "phase_timing",
                "phase": "phase_3",
                "processor": self.processor_name,
                "game_date": str(analysis_date),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": total_seconds,
                "records_processed": self.stats.get('rows_processed', 0),
                "extract_time": extract_seconds,
                "transform_time": transform_seconds,
                "save_time": save_seconds,
                "is_incremental": self.stats.get('is_incremental', False),
                "entities_changed_count": self.stats.get('entities_changed_count', 0)
            })

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
    # Dependency checking methods extracted to mixins/dependency_mixin.py
    # - get_dependencies()
    # - check_dependencies()
    # - _check_table_data()

    
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

    def _deduplicate_records(self, records: List[Dict]) -> List[Dict]:
        """
        Deduplicate records by PRIMARY_KEY_FIELDS before saving.

        Keeps the record with the latest processed_at timestamp.
        This prevents duplicate records from being inserted when the same
        data is processed multiple times (e.g., streaming buffer conflicts).

        Args:
            records: List of record dictionaries to deduplicate

        Returns:
            Deduplicated list of records
        """
        if not records:
            return records

        # Check if PRIMARY_KEY_FIELDS is defined
        if not hasattr(self.__class__, 'PRIMARY_KEY_FIELDS'):
            logger.debug("PRIMARY_KEY_FIELDS not defined, skipping deduplication")
            return records

        primary_keys = self.__class__.PRIMARY_KEY_FIELDS
        if not primary_keys or len(primary_keys) == 0:
            logger.debug("PRIMARY_KEY_FIELDS is empty, skipping deduplication")
            return records

        # Group by primary key
        from collections import defaultdict
        grouped = defaultdict(list)

        for record in records:
            key = tuple(record.get(f) for f in primary_keys)
            grouped[key].append(record)

        # Keep latest by processed_at
        deduplicated = []
        duplicates_removed = 0

        for key, group in grouped.items():
            if len(group) > 1:
                duplicates_removed += len(group) - 1
                # Sort by processed_at descending, take first
                group.sort(key=lambda r: r.get('processed_at', ''), reverse=True)

            deduplicated.append(group[0])

        if duplicates_removed > 0:
            logger.warning(
                f"Pre-save deduplication: removed {duplicates_removed} duplicate records "
                f"(keys: {primary_keys})"
            )

        return deduplicated
    
    # =========================================================================
    # BigQuery save operations extracted to operations/bigquery_save_ops.py
    # - save_analytics()
    # - _save_with_proper_merge()
    # - _save_with_delete_insert()
    # - _delete_existing_data_batch()


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
            # Use batched writes to reduce quota usage by 100x
            # Batches ~100 runs into 1 load job instead of 1 run = 1 job
            from shared.utils.bigquery_batch_writer import get_batch_writer

            writer = get_batch_writer(
                table_id='nba_processing.analytics_processor_runs',
                project_id=self.project_id,
                batch_size=100,  # Batch 100 runs per write
                timeout_seconds=30.0  # Flush every 30 seconds
            )

            # Add record to batch (will auto-flush when full)
            writer.add_record(run_record)

            logger.debug(f"Queued analytics run: {run_record.get('processor_type')} - {run_record.get('status')}")

        except Exception as e:
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

    # Failure tracking operations extracted to operations/failure_tracking.py
    # - save_registry_failures()
    # - record_failure()
    # - classify_recorded_failures()
    # - save_failures_to_bq()

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