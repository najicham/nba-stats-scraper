"""
Schedule-aware utilities for backfill jobs.

Provides functions to get game dates for backfills instead of iterating
through all calendar days blindly.
"""

import logging
from datetime import date, datetime
from typing import List, Optional

from google.cloud import bigquery

logger = logging.getLogger(__name__)


def get_game_dates_for_range(
    start_date: date,
    end_date: date,
    game_type=None  # Kept for backward compatibility, not used with BQ approach
) -> List[date]:
    """
    Get list of dates with NBA games in the given range.

    Queries BigQuery nba_reference.nba_schedule directly for reliable
    coverage across all seasons (2021+). GCS schedule files only exist
    for recent seasons.

    Args:
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
        game_type: Unused, kept for backward compatibility

    Returns:
        List of date objects where games were played, sorted chronologically
    """
    logger.info(f"Fetching game dates from {start_date} to {end_date} via BigQuery")

    client = bigquery.Client()
    query = f"""
        SELECT DISTINCT game_date
        FROM `nba-props-platform.nba_reference.nba_schedule`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
          AND game_status = 3  -- Final games only
        ORDER BY game_date
    """

    try:
        results = client.query(query).result()
        game_dates = [row.game_date for row in results]

        total_calendar_days = (end_date - start_date).days + 1
        skipped_days = total_calendar_days - len(game_dates)

        logger.info(
            f"Found {len(game_dates)} game dates out of {total_calendar_days} "
            f"calendar days (skipping {skipped_days} off-days)"
        )

        return game_dates

    except Exception as e:
        logger.error(f"Failed to fetch game dates from BigQuery: {e}")
        logger.info("Falling back to NBAScheduleService GCS reader...")
        return _get_game_dates_gcs_fallback(start_date, end_date)


def _get_game_dates_gcs_fallback(start_date: date, end_date: date) -> List[date]:
    """Fallback to GCS schedule reader if BigQuery is unavailable."""
    from shared.utils.schedule import NBAScheduleService
    from shared.utils.schedule.models import GameType

    start_season = _get_season_for_date(start_date)
    end_season = _get_season_for_date(end_date)
    seasons = list(range(start_season, end_season + 1))

    schedule = NBAScheduleService.from_gcs_only()
    game_date_info = schedule.get_all_game_dates(
        seasons=seasons,
        game_type=GameType.REGULAR_PLAYOFF,
        start_date=str(start_date),
        end_date=str(end_date)
    )

    game_dates = []
    for info in game_date_info:
        game_date = datetime.strptime(info['date'], '%Y-%m-%d').date()
        game_dates.append(game_date)

    return sorted(set(game_dates))


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
