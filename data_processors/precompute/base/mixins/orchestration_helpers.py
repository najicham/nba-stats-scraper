"""
Orchestration helper methods for precompute processors.

Provides helper methods for the run() orchestration flow, including
backfill handling, notification, logging, and error handling.

Version: 1.0
Created: 2026-01-25
"""

import logging
import traceback
from typing import Optional

logger = logging.getLogger(__name__)


class OrchestrationHelpersMixin:
    """
    Orchestration helper methods for precompute processors.

    Provides helper methods used during the run() orchestration flow
    to keep the main run() method clean and focused.

    Requires from base class:
    - self.dep_check: Dependency check results dict
    - self.is_backfill_mode: bool
    - self.stats: Statistics dict
    - self.opts: Processing options dict
    - self.run_id: Current run ID
    - self.processor_name: Processor name
    - self.correlation_id: Correlation ID
    - self.heartbeat: Heartbeat instance (optional)
    - self.__class__.__name__: Processor class name
    - Various methods: _record_date_level_failure, _quick_upstream_existence_check,
      record_run_complete, set_alert_sent, etc.
    """

    def _handle_backfill_dependency_check(self, analysis_date, skip_dep_check: bool) -> None:
        """
        Handle dependency checking in backfill mode.

        Args:
            analysis_date: Date to check
            skip_dep_check: Whether full dependency check is skipped
        """
        missing_upstream = self._quick_upstream_existence_check(analysis_date)
        if missing_upstream:
            error_msg = f"BACKFILL SAFETY: Critical upstream data missing: {missing_upstream}"
            logger.error(error_msg)
            self._record_date_level_failure(
                category='MISSING_UPSTREAM_IN_BACKFILL',
                reason=f"Missing upstream tables: {', '.join(missing_upstream)}",
                can_retry=True
            )
            raise ValueError(error_msg)

        mode_msg = "SAME-DAY MODE" if skip_dep_check else "BACKFILL MODE"
        logger.info(f"{mode_msg}: Skipping full dependency check (quick existence check passed)")

        self.dep_check = {
            'all_critical_present': True,
            'all_fresh': True,
            'missing': [],
            'stale': [],
            'details': {},
            'skipped_in_backfill': True
        }

    def _handle_missing_dependencies(self) -> bool:
        """
        Handle missing dependencies (early season or error).

        Returns:
            bool: True if early season (success), raises ValueError otherwise
        """
        # Import here to avoid circular dependencies
        from shared.utils.notification_system import notify_error

        if self.dep_check.get('is_early_season'):
            logger.info("Early season detected - returning success (no data expected)")
            self.stats['processing_decision'] = 'skipped_early_season'
            self.stats['processing_decision_reason'] = self.dep_check.get('early_season_reason')
            self.record_run_complete(
                status='success',
                records_processed=0,
                records_created=0,
                summary=self.stats
            )
            return True

        error_msg = f"Missing critical dependencies: {self.dep_check['missing']}"
        logger.error(error_msg)

        self._record_date_level_failure(
            category='MISSING_DEPENDENCIES',
            reason=f"Missing: {', '.join(self.dep_check['missing'])}",
            can_retry=True
        )

        if not self.is_backfill_mode:
            notify_error(
                title=f"Precompute Processor: Missing Dependencies - {self.__class__.__name__}",
                message=error_msg,
                details={
                    'processor': self.__class__.__name__,
                    'run_id': self.run_id,
                    'analysis_date': str(self.opts['analysis_date']),
                    'missing': self.dep_check['missing'],
                    'dependency_details': self.dep_check['details']
                },
                processor_name=self.__class__.__name__
            )
            self.set_alert_sent('error')

        raise ValueError(error_msg)

    def _warn_stale_data(self) -> None:
        """Warn about stale upstream data."""
        from shared.utils.notification_system import notify_warning

        logger.warning(f"Stale upstream data detected: {self.dep_check['stale']}")
        notify_warning(
            title=f"Precompute Processor: Stale Data - {self.__class__.__name__}",
            message=f"Upstream data is stale: {self.dep_check['stale']}",
            details={
                'processor': self.__class__.__name__,
                'run_id': self.run_id,
                'analysis_date': str(self.opts['analysis_date']),
                'stale_sources': self.dep_check['stale']
            }
        )
        self.set_alert_sent('warning')

    def _complete_early_season_skip(self) -> bool:
        """
        Complete processing for early season skip.

        Returns:
            bool: True (success)
        """
        logger.info("Early season period - skipping validate/calculate/save steps")
        self.record_run_complete(
            status='success',
            records_processed=0,
            records_created=0,
            summary=self.stats
        )
        return True

    def _start_heartbeat(self, data_date) -> None:
        """Start heartbeat monitoring."""
        try:
            from shared.monitoring.processor_heartbeat import ProcessorHeartbeat

            self.heartbeat = ProcessorHeartbeat(
                processor_name=self.processor_name,
                run_id=self.run_id,
                data_date=str(data_date) if data_date else None
            )
            self.heartbeat.start()
        except (ImportError, RuntimeError, OSError, ValueError) as e:
            logger.warning(f"Failed to start heartbeat: {e}")
            self.heartbeat = None

    def _log_pipeline_start(self, data_date, opts: dict) -> None:
        """Log processor start to pipeline event log."""
        try:
            from shared.utils.pipeline_logger import log_processor_start

            self._pipeline_event_id = log_processor_start(
                phase='phase_4',
                processor_name=self.processor_name,
                game_date=str(data_date) if data_date else str(opts.get('analysis_date')),
                correlation_id=self.correlation_id,
                trigger_source=opts.get('trigger_source', 'scheduled')
            )
        except (ImportError, Exception) as log_ex:
            logger.warning(f"Failed to log processor start: {log_ex}")
            self._pipeline_event_id = None

    def _log_pipeline_complete(self, data_date, total_seconds: float) -> None:
        """Log processor completion to pipeline event log."""
        try:
            from shared.utils.pipeline_logger import log_processor_complete, mark_retry_succeeded

            log_processor_complete(
                phase='phase_4',
                processor_name=self.processor_name,
                game_date=str(data_date) if data_date else None,
                duration_seconds=total_seconds,
                records_processed=self.stats.get('rows_processed', 0),
                correlation_id=self.correlation_id,
                parent_event_id=getattr(self, '_pipeline_event_id', None)
            )
            mark_retry_succeeded(
                phase='phase_4',
                processor_name=self.processor_name,
                game_date=str(data_date) if data_date else None
            )
        except (ImportError, Exception) as log_ex:
            logger.warning(f"Failed to log processor complete: {log_ex}")

    def _handle_failure_notification(self, error: Exception, failure_category: str,
                                     current_step: str, opts: dict) -> None:
        """Handle failure notification based on category."""
        from shared.utils.notification_system import notify_error

        should_alert = failure_category in ['processing_error', 'configuration_error', 'timeout']

        if not self.is_backfill_mode and should_alert:
            try:
                notify_error(
                    title=f"Precompute Processor Failed: {self.__class__.__name__}",
                    message=f"Precompute calculation failed: {str(error)}",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'error_type': type(error).__name__,
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

    def _log_pipeline_error(self, error: Exception, failure_category: str, opts: dict) -> None:
        """Log processor error to pipeline event log for retry."""
        if failure_category not in ['processing_error', 'timeout', 'upstream_failure']:
            return

        try:
            from shared.utils.pipeline_logger import log_processor_error, classify_error

            data_date = opts.get('analysis_date')
            error_type = classify_error(error)

            log_processor_error(
                phase='phase_4',
                processor_name=self.processor_name,
                game_date=str(data_date) if data_date else None,
                error_message=str(error),
                error_type=error_type,
                stack_trace=traceback.format_exc(),
                correlation_id=self.correlation_id,
                parent_event_id=getattr(self, '_pipeline_event_id', None)
            )
        except (ImportError, Exception) as log_ex:
            logger.warning(f"Failed to log processor error: {log_ex}")
