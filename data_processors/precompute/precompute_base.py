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

Version: 2.1 (with run history logging)
Updated: November 2025
"""

import json
import logging
import os
import uuid
from datetime import datetime, date, timezone, timedelta
from typing import Dict, List, Optional
from google.cloud import bigquery
import sentry_sdk

# Import notification system
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Import run history mixin
from shared.processors.mixins import RunHistoryMixin

# Import completeness checker and DependencyError for defensive checks
from shared.utils.completeness_checker import CompletenessChecker, DependencyError

# Import unified publishing
from shared.publishers.unified_pubsub_publisher import UnifiedPubSubPublisher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger("precompute_base")


class PrecomputeProcessorBase(RunHistoryMixin):
    """
    Base class for Phase 4 precompute processors.

    Phase 4 processors depend on Phase 3 (Analytics) and other Phase 4 processors.
    This base class provides dependency checking, source tracking, and validation.

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

    # BigQuery settings
    dataset_id: str = "nba_precompute"
    table_name: str = ""  # Child classes must set
    processing_strategy: str = "MERGE_UPDATE"  # Default for precompute

    # Time tracking
    time_markers: Dict = {}

    # Run history settings (from RunHistoryMixin)
    PHASE: str = 'phase_4_precompute'
    OUTPUT_TABLE: str = ''  # Set to table_name in run()
    OUTPUT_DATASET: str = 'nba_precompute'
    
    def __init__(self):
        """Initialize precompute processor."""
        self.opts = {}
        self.raw_data = None
        self.validated_data = {}
        self.transformed_data = {}
        self.stats = {}

        # Source metadata tracking
        self.source_metadata = {}
        self.data_completeness_pct = 100.0
        self.dependency_check_passed = True
        self.upstream_data_age_hours = 0.0
        self.missing_dependencies_list = []

        # Quality issue tracking
        self.quality_issues = []

        # Generate run_id
        self.run_id = str(uuid.uuid4())[:8]
        self.stats["run_id"] = self.run_id

        # GCP clients
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)

        # Correlation tracking (for tracing through pipeline)
        self.correlation_id = None
        self.parent_processor = None
        self.trigger_message_id = None

        # Selective processing (v1.1 feature - inherited from Phase 3)
        self.entities_changed = []  # List of entity IDs that changed
        self.is_incremental_run = False  # True if processing only changed entities
        
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

            self._run_defensive_checks(analysis_date, strict_mode)

            # Check dependencies BEFORE extracting
            self.mark_time("dependency_check")
            dep_check = self.check_dependencies(self.opts['analysis_date'])
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
                error_msg = f"Missing critical dependencies: {dep_check['missing']}"
                logger.error(error_msg)
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
                raise ValueError(error_msg)

            if not dep_check['all_fresh']:
                logger.warning(f"Stale upstream data detected: {dep_check['stale']}")
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

            return True

        except Exception as e:
            logger.error("PrecomputeProcessorBase Error: %s", e, exc_info=True)
            sentry_sdk.capture_exception(e)

            # Send notification for failure
            try:
                notify_error(
                    title=f"Precompute Processor Failed: {self.__class__.__name__}",
                    message=f"Precompute calculation failed: {str(e)}",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'error_type': type(e).__name__,
                        'step': self._get_current_step(),
                        'analysis_date': str(opts.get('analysis_date')),
                        'table': self.table_name,
                        'stats': self.stats
                    },
                    processor_name=self.__class__.__name__
                )
                self.set_alert_sent('error')
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            # Log failed processing run
            self.log_processing_run(success=False, error=str(e))

            if self.save_on_error:
                self._save_partial_data(e)

            self.report_error(e)

            # Record failed run to history
            self.record_run_complete(
                status='failed',
                error=e,
                summary=self.stats
            )

            return False

        finally:
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
    
    def _get_current_step(self) -> str:
        """Helper to determine current processing step for error context."""
        if not self.bq_client:
            return "initialization"
        elif not self.raw_data:
            return "extract"
        elif not self.transformed_data:
            return "calculate"
        else:
            return "save"
    
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
            analysis_date: Date to check dependencies for
            
        Returns:
            dict: {
                'all_critical_present': bool,
                'all_fresh': bool,
                'missing': List[str],
                'stale': List[str],
                'details': Dict[str, Dict]
            }
        """
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
            else:
                raise ValueError(f"Unknown check_type: {check_type}")
            
            # Execute query
            result = list(self.bq_client.query(query).result())
            
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
            
            # Calculate age
            if last_updated:
                age_hours = (datetime.utcnow() - last_updated).total_seconds() / 3600
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
            
        except Exception as e:
            error_msg = f"Error checking {table_name}: {str(e)}"
            logger.error(error_msg)
            return False, {
                'exists': False,
                'error': error_msg
            }
    
    def track_source_usage(self, dep_check: dict) -> None:
        """
        Record what sources were actually used during processing.
        Builds source_metadata dict for storage in BigQuery.
        """
        self.source_metadata = {}
        completeness_values = []
        age_values = []
        missing_deps = []
        
        for table_name, dep_result in dep_check['details'].items():
            if not dep_result.get('exists', False):
                missing_deps.append(table_name)
                continue
            
            # Calculate completeness percentage
            row_count = dep_result.get('row_count', 0)
            expected = dep_result.get('expected_count_min', 1)
            completeness = (row_count / expected * 100) if expected > 0 else 100
            completeness = min(completeness, 100)  # Cap at 100%
            
            completeness_values.append(completeness)
            
            if dep_result.get('age_hours') is not None:
                age_values.append(dep_result['age_hours'])
            
            # Store metadata
            self.source_metadata[table_name] = {
                'last_updated': dep_result.get('last_updated'),
                'rows_found': row_count,
                'rows_expected': expected,
                'completeness_pct': round(completeness, 2),
                'age_hours': dep_result.get('age_hours')
            }
        
        # Calculate overall metrics
        if completeness_values:
            self.data_completeness_pct = round(
                sum(completeness_values) / len(completeness_values), 2
            )
        else:
            self.data_completeness_pct = 0.0
        
        if age_values:
            self.upstream_data_age_hours = round(max(age_values), 2)
        else:
            self.upstream_data_age_hours = 0.0
        
        self.dependency_check_passed = dep_check['all_critical_present']
        self.missing_dependencies_list = missing_deps
        
        logger.info(f"Source metadata tracked: completeness={self.data_completeness_pct}%, "
                   f"max_age={self.upstream_data_age_hours}h")
    
    def _format_missing_deps(self) -> Optional[str]:
        """Format missing dependencies for database storage."""
        if not self.missing_dependencies_list:
            return None
        return ", ".join(self.missing_dependencies_list)

    # =========================================================================
    # Defensive Checks (Upstream Status + Gap Detection)
    # =========================================================================

    @property
    def is_backfill_mode(self) -> bool:
        """
        Detect if we're in backfill mode.

        Backfill mode indicators:
        - backfill_mode=True in opts
        - skip_downstream_trigger=True (implies backfill)

        Returns:
            bool: True if in backfill mode
        """
        return (
            self.opts.get('backfill_mode', False) or
            self.opts.get('skip_downstream_trigger', False)
        )

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

        logger.info("🛡️  Running defensive checks...")

        try:
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
            self.project_id = self.opts.get("project_id", "nba-props-platform")
            self.bq_client = bigquery.Client(project=self.project_id)
        except Exception as e:
            logger.error(f"Failed to initialize BigQuery client: {e}")
            try:
                notify_error(
                    title=f"Precompute Processor Client Initialization Failed: {self.__class__.__name__}",
                    message="Unable to initialize BigQuery client",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'project_id': self.opts.get('project_id', 'nba-props-platform'),
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
    
    def save_precompute(self) -> None:
        """
        Save to precompute BigQuery table using batch INSERT.
        Uses NDJSON load job with schema enforcement.
        """
        if not self.transformed_data:
            logger.warning("No transformed data to save")
            try:
                notify_warning(
                    title=f"Precompute Processor No Data to Save: {self.__class__.__name__}",
                    message="No precompute data calculated to save",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'raw_data_exists': self.raw_data is not None,
                        'analysis_date': str(self.opts.get('analysis_date'))
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return
            
        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
        
        # Handle different data types
        if isinstance(self.transformed_data, list):
            rows = self.transformed_data
        elif isinstance(self.transformed_data, dict):
            rows = [self.transformed_data]
        else:
            error_msg = f"Unexpected data type: {type(self.transformed_data)}"
            try:
                notify_error(
                    title=f"Precompute Processor Data Type Error: {self.__class__.__name__}",
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
        
        # Apply processing strategy - delete existing data first
        if self.processing_strategy == 'MERGE_UPDATE':
            try:
                self._delete_existing_data_batch(rows)
            except Exception as e:
                if "streaming buffer" not in str(e).lower():
                    logger.error(f"Delete failed with non-streaming error: {e}")
                    raise
        
        # Use batch INSERT via BigQuery load job
        logger.info(f"Inserting {len(rows)} rows to {table_id} using batch INSERT")
        
        try:
            import io
            
            # Get target table schema
            try:
                table = self.bq_client.get_table(table_id)
                table_schema = table.schema
                logger.info(f"Using schema with {len(table_schema)} fields")
            except Exception as schema_e:
                logger.warning(f"Could not get table schema: {schema_e}")
                table_schema = None
            
            # Convert to NDJSON
            ndjson_data = "\n".join(json.dumps(row) for row in rows)
            ndjson_bytes = ndjson_data.encode('utf-8')
            
            # Configure load job
            job_config = bigquery.LoadJobConfig(
                schema=table_schema,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                autodetect=False,
                schema_update_options=None
            )
            
            # Load to target table
            load_job = self.bq_client.load_table_from_file(
                io.BytesIO(ndjson_bytes),
                table_id,
                job_config=job_config
            )
            
            # Wait for completion
            try:
                load_job.result()
                logger.info(f"✅ Successfully loaded {len(rows)} rows")
                self.stats["rows_processed"] = len(rows)
                
            except Exception as load_e:
                if "streaming buffer" in str(load_e).lower():
                    logger.warning(f"⚠️ Load blocked by streaming buffer - {len(rows)} rows skipped")
                    logger.info("Records will be processed on next run")
                    self.stats["rows_skipped"] = len(rows)
                    self.stats["rows_processed"] = 0
                    return
                else:
                    raise load_e
            
        except Exception as e:
            error_msg = f"Batch insert failed: {str(e)}"
            logger.error(error_msg)
            try:
                notify_error(
                    title=f"Precompute Processor Batch Insert Failed: {self.__class__.__name__}",
                    message=f"Failed to batch insert {len(rows)} precompute rows",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': table_id,
                        'rows_attempted': len(rows),
                        'error_type': type(e).__name__,
                        'error': str(e),
                        'analysis_date': str(self.opts.get('analysis_date'))
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

    def _delete_existing_data_batch(self, rows: List[Dict]) -> None:
        """Delete existing data using batch DELETE query."""
        if not rows:
            return
            
        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
        
        # Get analysis_date from opts or first row
        analysis_date = self.opts.get('analysis_date')
        
        if analysis_date:
            delete_query = f"""
            DELETE FROM `{table_id}`
            WHERE analysis_date = '{analysis_date}'
            """
            
            logger.info(f"Deleting existing data for {analysis_date}")
            
            try:
                delete_job = self.bq_client.query(delete_query)
                delete_job.result()
                
                if delete_job.num_dml_affected_rows is not None:
                    logger.info(f"✅ Deleted {delete_job.num_dml_affected_rows} existing rows")
                else:
                    logger.info(f"✅ Delete completed for {analysis_date}")
                    
            except Exception as e:
                if "streaming buffer" in str(e).lower():
                    logger.warning("⚠️ Delete blocked by streaming buffer")
                    logger.info("Duplicates will be cleaned up on next run")
                    return
                else:
                    raise e
    
    # =========================================================================
    # Quality Tracking
    # =========================================================================
    
    def log_quality_issue(self, issue_type: str, severity: str, identifier: str,
                         details: Dict):
        """
        Log data quality issues for review.
        Enhanced with notifications for high-severity issues.
        Uses batch loading to avoid streaming buffer issues.
        """
        issue_record = {
            'issue_id': str(uuid.uuid4()),
            'processor_name': self.__class__.__name__,
            'run_id': self.run_id,
            'issue_type': issue_type,
            'severity': severity,
            'identifier': identifier,
            'issue_description': json.dumps(details),
            'resolved': False,
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        # Track locally
        self.quality_issues.append(issue_record)

        try:
            table_id = f"{self.project_id}.nba_processing.precompute_data_issues"

            # Use batch loading via load_table_from_json
            job_config = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                autodetect=True
            )
            load_job = self.bq_client.load_table_from_json(
                [issue_record],
                table_id,
                job_config=job_config
            )
            load_job.result()  # Wait for completion
            
            # Send notification for high-severity issues
            if severity in ['CRITICAL', 'HIGH']:
                try:
                    notify_func = notify_error if severity == 'CRITICAL' else notify_warning
                    notify_func(
                        title=f"Precompute Data Quality Issue: {self.__class__.__name__}",
                        message=f"{severity} severity {issue_type} detected for {identifier}",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'issue_type': issue_type,
                            'severity': severity,
                            'identifier': identifier,
                            'issue_details': details,
                            'table': self.table_name
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                    
        except Exception as e:
            logger.warning(f"Failed to log quality issue: {e}")
    
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
            load_job.result()  # Wait for completion
        except Exception as e:
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

        except Exception as e:
            logger.warning(f"Failed to publish completion message: {e}")
            # Don't fail the whole processor if Pub/Sub publishing fails

    # =========================================================================
    # Time Tracking
    # =========================================================================
    
    def mark_time(self, label: str) -> str:
        """Mark time."""
        now = datetime.now()
        if label not in self.time_markers:
            self.time_markers[label] = {
                "start": now,
                "last": now
            }
            return "0.0"
        else:
            last_time = self.time_markers[label]["last"]
            delta = (now - last_time).total_seconds()
            self.time_markers[label]["last"] = now
            return f"{delta:.1f}"
    
    def get_elapsed_seconds(self, label: str) -> float:
        """Get elapsed seconds."""
        if label not in self.time_markers:
            return 0.0
        start_time = self.time_markers[label]["start"]
        now_time = datetime.now()
        return (now_time - start_time).total_seconds()
    
    def step_info(self, step_name: str, message: str, extra: Optional[Dict] = None) -> None:
        """Log structured step."""
        if extra is None:
            extra = {}
        extra.update({
            "run_id": self.run_id,
            "step": step_name,
        })
        logger.info(f"PRECOMPUTE_STEP {message}", extra=extra)
    
    # =========================================================================
    # Error Handling
    # =========================================================================
    
    def report_error(self, exc: Exception) -> None:
        """Report error to Sentry."""
        sentry_sdk.capture_exception(exc)
    
    def _save_partial_data(self, exc: Exception) -> None:
        """Save partial data on error for debugging."""
        try:
            debug_file = f"/tmp/precompute_debug_{self.run_id}.json"
            debug_data = {
                "error": str(exc),
                "opts": self.opts,
                "raw_data_sample": str(self.raw_data)[:1000] if self.raw_data is not None else None,
                "transformed_data_sample": str(self.transformed_data)[:1000] if self.transformed_data else None,
                "source_metadata": self.source_metadata,
                "dependency_check_passed": self.dependency_check_passed
            }
            with open(debug_file, "w") as f:
                json.dump(debug_data, f, indent=2)
            logger.info(f"Saved debug data to {debug_file}")
        except Exception as save_exc:
            logger.warning(f"Failed to save debug data: {save_exc}")
    
    def build_source_tracking_fields(self) -> dict:
        """
        Build dict of all source tracking fields for output records.
        Extracts from self.source_metadata populated by track_source_usage().
        
        Returns:
            Dict with source_* fields per v4.0 spec (3 fields per source)
        """
        fields = {}
        
        # Per-source fields (populated by track_source_usage)
        for table_name, config in self.get_dependencies().items():
            prefix = config['field_prefix']
            metadata = self.source_metadata.get(table_name, {})
            
            fields[f'{prefix}_last_updated'] = metadata.get('last_updated')
            fields[f'{prefix}_rows_found'] = metadata.get('rows_found')
            fields[f'{prefix}_completeness_pct'] = metadata.get('completeness_pct')
        
        # Optional early season fields
        if hasattr(self, 'early_season_flag') and self.early_season_flag:
            fields['early_season_flag'] = True
            fields['insufficient_data_reason'] = getattr(self, 'insufficient_data_reason', None)
        else:
            fields['early_season_flag'] = None
            fields['insufficient_data_reason'] = None
        
        return fields

    def _calculate_expected_count(self, config: dict, dep_result: dict) -> int:
        """
        Calculate expected row count based on check_type.
        
        Args:
            config: Dependency configuration
            dep_result: Results from dependency check
            
        Returns:
            Expected number of rows
        """
        check_type = config.get('check_type', 'existence')
        
        if check_type == 'per_team_game_count':
            # Expected = min_games_required × number of teams
            teams_with_data = dep_result.get('teams_found', 30)
            min_games = config.get('min_games_required', 15)
            return min_games * teams_with_data
            
        elif check_type == 'lookback':
            # Use configured expected count or estimate
            return config.get('expected_count_min', 100)
            
        elif check_type == 'date_match':
            # Expect one record per entity (e.g., 30 teams)
            return config.get('expected_count_min', 30)
            
        elif check_type == 'existence':
            return config.get('expected_count_min', 1)
        
        else:
            # Unknown check type - use configured minimum
            return config.get('expected_count_min', 1)

    # Update track_source_usage() to store per-source attributes
    def track_source_usage(self, dep_check: dict) -> None:
        """
        Record what sources were used. 
        Populates self.source_metadata dict AND per-source attributes.
        """
        self.source_metadata = {}
        completeness_values = []
        age_values = []
        missing_deps = []
        
        for table_name, dep_result in dep_check['details'].items():
            config = self.get_dependencies()[table_name]
            prefix = config.get('field_prefix', table_name.split('.')[-1])
            
            if not dep_result.get('exists', False):
                missing_deps.append(table_name)
                # Set attributes to None for missing sources
                setattr(self, f'{prefix}_last_updated', None)
                setattr(self, f'{prefix}_rows_found', None)
                setattr(self, f'{prefix}_completeness_pct', None)
                continue
            
            # Calculate completeness
            row_count = dep_result.get('row_count', 0)
            expected = self._calculate_expected_count(config, dep_result)
            completeness = (row_count / expected * 100) if expected > 0 else 100
            completeness = min(completeness, 100.0)
            
            completeness_values.append(completeness)
            
            if dep_result.get('age_hours') is not None:
                age_values.append(dep_result['age_hours'])
            
            # Store in metadata dict
            self.source_metadata[table_name] = {
                'last_updated': dep_result.get('last_updated'),
                'rows_found': row_count,
                'rows_expected': expected,
                'completeness_pct': round(completeness, 2),
                'age_hours': dep_result.get('age_hours')
            }
            
            # ALSO store as attributes for easy access
            setattr(self, f'{prefix}_last_updated', dep_result.get('last_updated'))
            setattr(self, f'{prefix}_rows_found', row_count)
            setattr(self, f'{prefix}_completeness_pct', round(completeness, 2))
        
        # Calculate overall metrics (keep existing logic)
        if completeness_values:
            self.data_completeness_pct = round(
                sum(completeness_values) / len(completeness_values), 2
            )
        else:
            self.data_completeness_pct = 0.0
        
        if age_values:
            self.upstream_data_age_hours = round(max(age_values), 2)
        else:
            self.upstream_data_age_hours = 0.0
        
        self.dependency_check_passed = dep_check['all_critical_present']
        self.missing_dependencies_list = missing_deps
        
        logger.info(f"Source tracking complete: completeness={self.data_completeness_pct}%, "
                f"max_age={self.upstream_data_age_hours}h")
        