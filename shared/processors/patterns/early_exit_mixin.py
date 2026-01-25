"""
Pattern #3: Early Exit Mixin

Provides early exit conditions to skip unnecessary processing.

Example:
    class PlayerGameSummaryProcessor(EarlyExitMixin, AnalyticsProcessorBase):
        ENABLE_NO_GAMES_CHECK = True
        ENABLE_OFFSEASON_CHECK = True
        ENABLE_HISTORICAL_DATE_CHECK = True

Exits early when:
- No games scheduled
- Offseason (July-September)
- Too far in past (>90 days)

Backfill Mode:
    When opts['backfill_mode'] = True, the historical date check is disabled.
    This allows processing of dates older than 90 days during backfills.

    Example:
        processor.run({
            'start_date': '2021-10-19',
            'backfill_mode': True  # Disables historical check
        })
"""

from typing import Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class EarlyExitMixin:
    """
    Mixin to add early exit pattern to processors.

    Provides date-based checks to skip unnecessary processing.
    """

    # Configuration flags - override in subclass
    ENABLE_NO_GAMES_CHECK = True
    ENABLE_OFFSEASON_CHECK = True
    ENABLE_HISTORICAL_DATE_CHECK = True
    ENABLE_GAMES_FINISHED_CHECK = False  # NEW: Skip if games not finished (opt-in)

    # Season configuration
    SEASON_START_MONTH = 10  # October
    SEASON_END_MONTH = 6     # June

    def run(self, opts: Dict) -> bool:
        """
        Enhanced run method with early exit checks.

        Supports backfill_mode option to disable historical date check.
        """
        start_date = opts.get('start_date')
        end_date = opts.get('end_date')
        backfill_mode = opts.get('backfill_mode', False)

        # Use start_date for checks (or game_date for backward compat)
        check_date = start_date or opts.get('game_date')

        if not check_date:
            # No date to check, proceed normally
            return super().run(opts)

        if backfill_mode:
            logger.info(f"BACKFILL_MODE: Historical date check disabled for {check_date}")

        # EARLY EXIT 1: No games scheduled
        if self.ENABLE_NO_GAMES_CHECK:
            if not self._has_games_scheduled(check_date):
                logger.info(f"No games scheduled on {check_date}, skipping")
                self._log_skip('no_games')
                return True

        # EARLY EXIT 1.5: Games not finished yet (NEW)
        if self.ENABLE_GAMES_FINISHED_CHECK:
            if not self._are_games_finished(check_date):
                logger.info(f"Games on {check_date} not finished yet, skipping to prevent retry storm")
                self._log_skip('games_not_finished')
                return True

        # EARLY EXIT 2: Offseason
        if self.ENABLE_OFFSEASON_CHECK:
            if self._is_offseason(check_date):
                logger.info(f"{check_date} is in offseason, skipping")
                self._log_skip('offseason')
                return True

        # EARLY EXIT 3: Date too far in past (skip in backfill_mode)
        if self.ENABLE_HISTORICAL_DATE_CHECK and not backfill_mode:
            if self._is_too_historical(check_date):
                logger.info(f"{check_date} is too far in past, skipping")
                self._log_skip('too_historical')
                return True

        # Continue with normal processing
        return super().run(opts)

    def _has_games_scheduled(self, game_date: str) -> bool:
        """
        Quick check if any games are scheduled.

        This is the most common early exit - saves 30-40% of invocations.
        """
        # Need BigQuery client from parent class
        if not hasattr(self, 'bq_client'):
            logger.warning("No bq_client available, cannot check games schedule")
            return True  # Fail open

        if not hasattr(self, 'project_id'):
            logger.warning("No project_id available, cannot check games schedule")
            return True  # Fail open

        query = f"""
        SELECT COUNT(*) as cnt
        FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
        WHERE game_date = '{game_date}'
          AND game_status IN (1, 3)
        """

        try:
            result = list(self.bq_client.query(query).result(timeout=60))
            count = int(result[0].cnt) if result else 0

            logger.debug(f"Games scheduled on {game_date}: {count}")
            return count > 0

        except Exception as e:
            logger.error(f"Error checking game schedule: {e}", exc_info=True)
            # Fail open - proceed with processing
            return True

    def _are_games_finished(self, game_date: str) -> bool:
        """
        Check if all games for the date are finished.

        Prevents retry storms by skipping processing attempts for games
        that are scheduled but not yet played.

        game_status values:
        - 1: Scheduled (not started)
        - 2: In Progress
        - 3: Final (completed)

        Returns:
            True if all games are finished (status=3)
            False if any games are scheduled/in-progress
        """
        # Need BigQuery client from parent class
        if not hasattr(self, 'bq_client'):
            logger.warning("No bq_client available, cannot check games status")
            return True  # Fail open - proceed with processing

        if not hasattr(self, 'project_id'):
            logger.warning("No project_id available, cannot check games status")
            return True  # Fail open - proceed with processing

        query = f"""
        SELECT
            COUNT(*) as total_games,
            COUNTIF(game_status = 3) as finished_games,
            COUNTIF(game_status IN (1, 2)) as unfinished_games
        FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
        WHERE game_date = '{game_date}'
        """

        try:
            result = list(self.bq_client.query(query).result(timeout=60))
            if not result:
                # No games scheduled - allow processing to continue
                return True

            row = result[0]
            total_games = int(row.total_games)
            finished_games = int(row.finished_games)
            unfinished_games = int(row.unfinished_games)

            if total_games == 0:
                # No games scheduled - allow processing
                logger.debug(f"No games scheduled on {game_date}")
                return True

            if unfinished_games > 0:
                # Some games not finished yet
                logger.info(
                    f"{game_date}: {unfinished_games}/{total_games} games not finished yet "
                    f"(finished: {finished_games})"
                )
                return False

            # All games finished
            logger.debug(f"All {total_games} games finished on {game_date}")
            return True

        except Exception as e:
            logger.error(f"Error checking games finished status: {e}", exc_info=True)
            # Fail open - proceed with processing
            return True

    def _is_offseason(self, game_date: str) -> bool:
        """
        Check if date is in offseason.

        NBA season runs October-June typically.
        Offseason is July, August, September.
        """
        game_datetime = datetime.strptime(game_date, '%Y-%m-%d')
        month = game_datetime.month

        # Offseason: July-September
        is_offseason = month in [7, 8, 9]

        if is_offseason:
            logger.debug(f"{game_date} (month {month}) is in offseason")

        return is_offseason

    def _is_too_historical(self, game_date: str, cutoff_days: int = 90) -> bool:
        """
        Check if date is too far in the past.

        Useful to prevent reprocessing very old data unnecessarily.
        Default cutoff is 90 days.
        """
        game_datetime = datetime.strptime(game_date, '%Y-%m-%d')
        today = datetime.now()

        days_ago = (today - game_datetime).days
        is_too_old = days_ago > cutoff_days

        if is_too_old:
            logger.debug(f"{game_date} is {days_ago} days ago (cutoff: {cutoff_days})")

        return is_too_old

    def _log_skip(self, reason: str):
        """
        Log skip with reason.

        Writes to skip_reason column in processing tables for monitoring.
        """
        if hasattr(self, 'stats'):
            self.stats['skip_reason'] = reason

        if hasattr(self, 'log_processing_run'):
            try:
                # Ensure we have required fields
                if not hasattr(self, 'stats'):
                    self.stats = {}
                if 'run_id' not in self.stats:
                    self.stats['run_id'] = getattr(self, 'run_id', 'unknown')

                # Log the skip
                self.log_processing_run(success=True, skip_reason=reason)
            except Exception as e:
                logger.warning(f"Failed to log early exit: {e}")
