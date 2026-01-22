"""
NBA Season Utilities

Helper functions for determining NBA season year dynamically.

NBA Season Logic:
- A season spans October of year X to June of year X+1
- The season_year is the starting year (X)
- Example: 2025-26 season has season_year = 2025

Created: January 22, 2026
"""

from datetime import date, datetime
from typing import Optional


def get_current_season_year(reference_date: Optional[date] = None) -> int:
    """
    Get the current NBA season year.

    Args:
        reference_date: Date to calculate for (defaults to today)

    Returns:
        Season year (e.g., 2025 for the 2025-26 season)

    Examples:
        - January 2026 -> 2025 (still in 2025-26 season)
        - October 2026 -> 2026 (new 2026-27 season started)
        - July 2026 -> 2025 (offseason, but last season was 2025-26)
    """
    if reference_date is None:
        reference_date = date.today()

    # NBA season typically starts in mid-October
    # If we're in October or later, it's the current year's season
    # If we're before October, it's the previous year's season
    if reference_date.month >= 10:
        return reference_date.year
    else:
        return reference_date.year - 1


def get_season_year_sql() -> str:
    """
    Get SQL expression for dynamic season year calculation.

    Returns:
        BigQuery SQL expression that calculates current season year
    """
    return """
    CASE
      WHEN EXTRACT(MONTH FROM CURRENT_DATE()) >= 10
      THEN EXTRACT(YEAR FROM CURRENT_DATE())
      ELSE EXTRACT(YEAR FROM CURRENT_DATE()) - 1
    END
    """


def get_season_year_for_date_sql() -> str:
    """
    Get SQL expression for season year based on a game_date column.

    Returns:
        BigQuery SQL expression that calculates season year for a given date
    """
    return """
    CASE
      WHEN EXTRACT(MONTH FROM game_date) >= 10
      THEN EXTRACT(YEAR FROM game_date)
      ELSE EXTRACT(YEAR FROM game_date) - 1
    END
    """


# Exports
__all__ = [
    'get_current_season_year',
    'get_season_year_sql',
    'get_season_year_for_date_sql',
]
