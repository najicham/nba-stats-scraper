"""
MLB Early Exit Mixin

Provides early exit conditions to skip unnecessary processing for MLB.

Example:
    class MlbPitcherPropsProcessor(MlbEarlyExitMixin, ProcessorBase):
        ENABLE_NO_GAMES_CHECK = True
        ENABLE_OFFSEASON_CHECK = True
        ENABLE_ALL_STAR_CHECK = True

Exits early when:
- No MLB games scheduled
- MLB offseason (October-March)
- MLB All-Star break (mid-July)
- Too far in past (>90 days) unless backfill_mode=True

MLB Season Characteristics:
- Regular season: Late March/April to late September/early October
- All-Star break: Mid-July (typically 3-4 days)
- Offseason: October to March
"""

from typing import Dict
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)

# Import MLB schedule utilities
try:
    from shared.validation.context.mlb_schedule_context import (
        is_mlb_offseason,
        is_mlb_all_star_break,
        has_mlb_games_on_date,
        get_mlb_season_year,
    )
except ImportError:
    logger.warning("Could not import mlb_schedule_context, using fallback")

    def is_mlb_offseason(game_date: date) -> bool:
        """Fallback: October-March is offseason."""
        month = game_date.month
        return month < 4 or month > 9

    def is_mlb_all_star_break(game_date: date) -> bool:
        """Fallback: mid-July is All-Star break."""
        return game_date.month == 7 and 12 <= game_date.day <= 17

    def has_mlb_games_on_date(game_date: date, client=None) -> bool:
        """Fallback: assume games if not offseason/all-star."""
        if is_mlb_offseason(game_date):
            return False
        if is_mlb_all_star_break(game_date):
            return False
        return True

    def get_mlb_season_year(game_date: date) -> int:
        return game_date.year


class MlbEarlyExitMixin:
    """
    Mixin to add MLB-specific early exit pattern to processors.

    Provides date-based checks to skip unnecessary processing.
    """

    # Configuration flags - override in subclass
    ENABLE_NO_GAMES_CHECK = True
    ENABLE_OFFSEASON_CHECK = True
    ENABLE_ALL_STAR_CHECK = True
    ENABLE_HISTORICAL_DATE_CHECK = True

    # Historical cutoff (days)
    HISTORICAL_CUTOFF_DAYS = 90

    def run(self, opts: Dict) -> bool:
        """
        Enhanced run method with MLB early exit checks.

        Supports backfill_mode option to disable historical date check.
        """
        start_date = opts.get('start_date')
        end_date = opts.get('end_date')
        backfill_mode = opts.get('backfill_mode', False)

        # Use start_date for checks (or game_date for backward compat)
        check_date_str = start_date or opts.get('game_date')

        if not check_date_str:
            # No date to check, proceed normally
            return super().run(opts)

        # Parse date
        if isinstance(check_date_str, str):
            check_date = datetime.strptime(check_date_str, '%Y-%m-%d').date()
        else:
            check_date = check_date_str

        if backfill_mode:
            logger.info(f"MLB_BACKFILL_MODE: Historical date check disabled for {check_date}")

        # EARLY EXIT 1: Offseason check
        if self.ENABLE_OFFSEASON_CHECK:
            if is_mlb_offseason(check_date):
                logger.info(f"MLB: {check_date} is in offseason (Oct-Mar), skipping")
                self._log_mlb_skip('offseason')
                return True

        # EARLY EXIT 2: All-Star break check
        if self.ENABLE_ALL_STAR_CHECK:
            if is_mlb_all_star_break(check_date):
                logger.info(f"MLB: {check_date} is All-Star break, skipping")
                self._log_mlb_skip('all_star_break')
                return True

        # EARLY EXIT 3: No games scheduled
        if self.ENABLE_NO_GAMES_CHECK:
            client = getattr(self, 'bq_client', None)
            if not has_mlb_games_on_date(check_date, client):
                logger.info(f"MLB: No games scheduled on {check_date}, skipping")
                self._log_mlb_skip('no_games')
                return True

        # EARLY EXIT 4: Date too far in past (skip in backfill_mode)
        if self.ENABLE_HISTORICAL_DATE_CHECK and not backfill_mode:
            if self._is_too_historical_mlb(check_date):
                logger.info(f"MLB: {check_date} is too far in past, skipping")
                self._log_mlb_skip('too_historical')
                return True

        # Continue with normal processing
        return super().run(opts)

    def _is_too_historical_mlb(self, game_date: date) -> bool:
        """
        Check if date is too far in the past.

        Default cutoff is 90 days.
        """
        today = datetime.now().date()
        days_ago = (today - game_date).days
        is_too_old = days_ago > self.HISTORICAL_CUTOFF_DAYS

        if is_too_old:
            logger.debug(f"MLB: {game_date} is {days_ago} days ago (cutoff: {self.HISTORICAL_CUTOFF_DAYS})")

        return is_too_old

    def _log_mlb_skip(self, reason: str):
        """
        Log skip with reason.

        Writes to skip_reason column in processing tables for monitoring.
        """
        if hasattr(self, 'stats'):
            self.stats['skip_reason'] = f"mlb_{reason}"

        if hasattr(self, 'log_processing_run'):
            try:
                if not hasattr(self, 'stats'):
                    self.stats = {}
                if 'run_id' not in self.stats:
                    self.stats['run_id'] = getattr(self, 'run_id', 'unknown')

                self.log_processing_run(success=True, skip_reason=f"mlb_{reason}")
            except Exception as e:
                logger.warning(f"Failed to log MLB early exit: {e}")


class MlbScheduleAwareMixin:
    """
    Mixin that provides schedule context for MLB processors.

    Use this when you need full schedule context, not just early exit.

    Example:
        class MlbAnalyticsProcessor(MlbScheduleAwareMixin, ProcessorBase):
            def run(self, opts):
                context = self.get_mlb_schedule_context(opts.get('game_date'))
                if not context.is_valid_processing_date:
                    logger.info(f"Skipping: {context.skip_reason}")
                    return True
                # ... process games
    """

    def get_mlb_schedule_context(self, game_date_str: str):
        """Get full MLB schedule context for a date."""
        from shared.validation.context.mlb_schedule_context import get_mlb_schedule_context

        if isinstance(game_date_str, str):
            game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
        else:
            game_date = game_date_str

        client = getattr(self, 'bq_client', None)
        return get_mlb_schedule_context(game_date, client)
