"""
NBA Season Key Dates Configuration

Provides season boundaries for data processing.
Uses schedule service for dynamic season dates with hardcoded fallback.
"""

from datetime import date, datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Fallback season start dates (used if schedule service unavailable)
# These are sourced from schedule database and updated periodically
FALLBACK_SEASON_START_DATES = {
    2024: date(2024, 10, 22),  # 2024-25 season (from schedule DB 2025-11-27)
    2023: date(2023, 10, 24),  # 2023-24 season (from schedule DB 2025-11-27)
    2022: date(2022, 10, 18),  # 2022-23 season (from schedule DB 2025-11-27)
    2021: date(2021, 10, 19),  # 2021-22 season - EPOCH (from schedule DB 2025-11-27)
}

# Default if not in dict (typically late October)
DEFAULT_SEASON_START_MONTH = 10
DEFAULT_SEASON_START_DAY = 22

# Lazy-loaded schedule service (initialized on first use)
_schedule_service = None


def _get_schedule_service():
    """Lazy-load schedule service to avoid circular imports."""
    global _schedule_service
    if _schedule_service is None:
        try:
            from orchestration.shared.utils.schedule.service import NBAScheduleService
            _schedule_service = NBAScheduleService()
            logger.debug("NBAScheduleService initialized for season dates")
        except Exception as e:
            logger.warning("Could not initialize schedule service: %s (using fallback dates)", e)
            _schedule_service = False  # Mark as failed to avoid retries
    return _schedule_service if _schedule_service is not False else None


def get_season_start_date(season_year: int, use_schedule_service: bool = True) -> date:
    """
    Get season start date for a given season year.

    Uses schedule service (database + GCS) for dynamic dates with fallback to hardcoded dates.

    Args:
        season_year: Year season starts (e.g., 2024 for 2024-25 season)
        use_schedule_service: If True, try schedule service first (default: True)

    Returns:
        Season opening night date (date object)

    Example:
        >>> get_season_start_date(2024)
        datetime.date(2024, 10, 22)
        >>> get_season_start_date(2023)
        datetime.date(2023, 10, 24)
    """
    # Try schedule service first (dynamic dates from database/GCS)
    if use_schedule_service:
        schedule_service = _get_schedule_service()
        if schedule_service:
            try:
                date_str = schedule_service.get_season_start_date(season_year)
                if date_str:
                    season_start = datetime.strptime(date_str, '%Y-%m-%d').date()
                    logger.debug("Season %d starts: %s (from schedule service)", season_year, season_start)
                    return season_start
            except Exception as e:
                logger.warning("Schedule service failed for season %d: %s (using fallback)", season_year, e)

    # Fallback to hardcoded dates
    if season_year in FALLBACK_SEASON_START_DATES:
        season_start = FALLBACK_SEASON_START_DATES[season_year]
        logger.debug("Season %d starts: %s (from fallback)", season_year, season_start)
        return season_start

    # Ultimate fallback: estimate based on typical season start
    estimated_start = date(season_year, DEFAULT_SEASON_START_MONTH, DEFAULT_SEASON_START_DAY)
    logger.warning(
        "Season %d not in schedule service or fallback - estimating: %s",
        season_year, estimated_start
    )
    return estimated_start


def is_early_season(analysis_date: date, season_year: int, days_threshold: int = 14) -> bool:
    """
    Check if analysis date is in early season period.

    Uses deterministic date-based check (first N days of regular season).
    Default 14 days provides ~7 games per team for L5/L7d windows.

    Args:
        analysis_date: Date being analyzed
        season_year: Season year
        days_threshold: Days to consider "early" (default 14, from BOOTSTRAP_DAYS)

    Returns:
        True if within first N days of season

    Example:
        >>> is_early_season(date(2023, 10, 24), 2023, days_threshold=14)
        True  # Day 0 (opening night)
        >>> is_early_season(date(2023, 11, 6), 2023, days_threshold=14)
        True  # Day 13
        >>> is_early_season(date(2023, 11, 7), 2023, days_threshold=14)
        False  # Day 14 - regular processing starts
    """
    season_start = get_season_start_date(season_year)
    days_since_start = (analysis_date - season_start).days

    # Check if within early season window
    # Note: days_since_start can be negative if analysis_date is before season start
    is_early = 0 <= days_since_start < days_threshold

    if is_early:
        logger.debug(
            "Early season detected: %s is day %d of season %d (threshold: %d days)",
            analysis_date, days_since_start, season_year, days_threshold
        )

    return is_early


def get_season_year_from_date(game_date: date) -> int:
    """
    Determine season year from game date.

    NBA seasons run from October (year N) to June (year N+1).
    Season starts in October, so Oct-Dec are same year, Jan-Sep are previous year.

    Args:
        game_date: Date of game

    Returns:
        Season year (e.g., 2024 for 2024-25 season)

    Example:
        >>> get_season_year_from_date(date(2024, 10, 22))  # Opening night
        2024
        >>> get_season_year_from_date(date(2025, 1, 15))   # Mid-season
        2024  # Still 2024-25 season
        >>> get_season_year_from_date(date(2025, 6, 15))   # Finals
        2024  # Still 2024-25 season
    """
    if game_date.month >= 10:
        return game_date.year
    else:
        return game_date.year - 1
