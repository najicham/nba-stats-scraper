"""
File: data_processors/precompute/mixins/defensive_check_mixin.py

Mixin for defensive checks that prevent processing with incomplete upstream data.

This mixin provides:
- _run_defensive_checks(): Validates upstream Phase 3 (and Phase 4) processors completed
  successfully and checks for gaps in the lookback window
- _quick_upstream_existence_check(): Quick existence check for critical Phase 4 dependencies
  that runs even in backfill mode

Version: 1.0
Created: 2026-01-25
"""

import logging
from datetime import datetime, date, timedelta
from typing import List, Dict
from google.cloud import bigquery

from shared.utils.completeness_checker import CompletenessChecker, DependencyError
from shared.utils.notification_system import notify_error

# Import soft dependency mixin for graceful degradation (added after Jan 23 incident)
try:
    from shared.processors.mixins.soft_dependency_mixin import SoftDependencyMixin
    SOFT_DEPS_AVAILABLE = True
except ImportError:
    SOFT_DEPS_AVAILABLE = False
    SoftDependencyMixin = object  # Fallback to empty object

logger = logging.getLogger(__name__)


class DefensiveCheckMixin:
    """
    Mixin for defensive checks that prevent processing with incomplete upstream data.

    Required Dependencies (must be provided by the class using this mixin):
    - self.opts: Processing options dict
    - self.completeness_checker: CompletenessChecker instance (optional, created if needed)
    - self.get_dependencies(): Method returning dependency config dict
    - self.bq_client: BigQuery client instance
    - self.project_id: GCP project ID string
    - self.is_backfill_mode: Property indicating backfill mode
    - self.__class__.__name__: Processor name string
    - self.run_id: Unique run identifier string
    - self.table_name: Target table name string
    - self.set_alert_sent(alert_type): Method to mark alert as sent
    - self.use_soft_dependencies: Boolean flag for soft dependency checking (optional)
    - self.soft_dependency_threshold: Float threshold for soft dependency checking (optional)
    - self.check_soft_dependencies(date): Method for soft dependency checking (optional)
    - self.dependency_check_passed: Boolean flag for dependency check status (optional)
    - self.data_completeness_pct: Float for data completeness percentage (optional)
    - self.upstream_processor_name: Name of upstream Phase 3 processor (optional)
    - self.upstream_table: Upstream Phase 3 table name (optional)
    - self.lookback_days: Number of days to check for gaps (optional)
    - self.PHASE_4_SOURCES: Dict of Phase 4 sources (optional, for quick check)
    """

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
        if hasattr(self, 'use_soft_dependencies') and self.use_soft_dependencies and SOFT_DEPS_AVAILABLE:
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
