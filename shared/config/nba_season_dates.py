"""
NBA Season Key Dates Configuration
Provides season boundaries for data processing
"""

from datetime import date
from typing import Optional

# Season start dates (opening night)
SEASON_START_DATES = {
    2024: date(2024, 10, 22),  # 2024-25 season
    2023: date(2023, 10, 24),  # 2023-24 season
    2022: date(2022, 10, 18),  # 2022-23 season
    # Add more as needed
}

# Default if not in dict (typically late October)
DEFAULT_SEASON_START_MONTH = 10
DEFAULT_SEASON_START_DAY = 22


def get_season_start_date(season_year: int) -> date:
    """
    Get season start date for a given season year.
    
    Args:
        season_year: Year season starts (e.g., 2024 for 2024-25 season)
        
    Returns:
        Season opening night date
    """
    if season_year in SEASON_START_DATES:
        return SEASON_START_DATES[season_year]
    
    # Default to late October
    return date(season_year, DEFAULT_SEASON_START_MONTH, DEFAULT_SEASON_START_DAY)


def is_early_season(analysis_date: date, season_year: int, days_threshold: int = 14) -> bool:
    """
    Check if analysis date is in early season period.
    
    Args:
        analysis_date: Date being analyzed
        season_year: Season year
        days_threshold: Days to consider "early" (default 14)
        
    Returns:
        True if within first N days of season
    """
    season_start = get_season_start_date(season_year)
    days_since_start = (analysis_date - season_start).days
    return days_since_start < days_threshold


def get_season_year_from_date(game_date: date) -> int:
    """
    Determine season year from game date.
    Season starts in October, so Oct-Dec are same year, Jan-Sep are previous year.
    
    Args:
        game_date: Date of game
        
    Returns:
        Season year (e.g., 2024 for 2024-25 season)
    """
    if game_date.month >= 10:
        return game_date.year
    else:
        return game_date.year - 1
