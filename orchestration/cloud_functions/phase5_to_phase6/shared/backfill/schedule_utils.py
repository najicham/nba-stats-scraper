"""
Schedule-aware utilities for backfill jobs.

Provides functions to get game dates for backfills instead of iterating
through all calendar days blindly.
"""

import logging
from datetime import date, datetime
from typing import List, Optional

from orchestration.shared.utils.schedule import NBAScheduleService
from orchestration.shared.utils.schedule.models import GameType

logger = logging.getLogger(__name__)


def get_game_dates_for_range(
    start_date: date,
    end_date: date,
    game_type: GameType = GameType.REGULAR_PLAYOFF
) -> List[date]:
    """
    Get list of dates with NBA games in the given range.

    Uses GCS schedule data as source of truth - no database dependency.
    Automatically skips dates with no games (Thanksgiving, off-days, etc.)

    Args:
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
        game_type: Type of games to include (default: regular season + playoffs)

    Returns:
        List of date objects where games were played, sorted chronologically

    Example:
        >>> from shared.backfill.schedule_utils import get_game_dates_for_range
        >>> from datetime import date
        >>> dates = get_game_dates_for_range(date(2021, 11, 15), date(2021, 11, 30))
        >>> len(dates)  # 15 game days (skips Nov 25 Thanksgiving)
        15
    """
    # Determine which seasons we need to query
    start_season = _get_season_for_date(start_date)
    end_season = _get_season_for_date(end_date)
    seasons = list(range(start_season, end_season + 1))

    logger.info(f"Fetching game dates from {start_date} to {end_date} (seasons: {seasons})")

    # Use GCS-only mode - no database dependency
    schedule = NBAScheduleService.from_gcs_only()

    # Get all game dates for the seasons
    game_date_info = schedule.get_all_game_dates(
        seasons=seasons,
        game_type=game_type,
        start_date=str(start_date),
        end_date=str(end_date)
    )

    # Extract just the dates
    game_dates = []
    for info in game_date_info:
        game_date = datetime.strptime(info['date'], '%Y-%m-%d').date()
        game_dates.append(game_date)

    # Sort and dedupe (should already be sorted but be safe)
    game_dates = sorted(set(game_dates))

    total_calendar_days = (end_date - start_date).days + 1
    skipped_days = total_calendar_days - len(game_dates)

    logger.info(f"Found {len(game_dates)} game dates out of {total_calendar_days} calendar days (skipping {skipped_days} off-days)")

    return game_dates


def _get_season_for_date(date_obj: date) -> int:
    """
    Determine which NBA season a date belongs to.

    NBA seasons run from October (year N) to June (year N+1).

    Args:
        date_obj: Date to check

    Returns:
        Season year (e.g., 2024 for 2024-25 season)
    """
    # NBA season starts in October
    if date_obj.month >= 10:
        return date_obj.year
    else:
        return date_obj.year - 1
