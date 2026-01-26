# ============================================================================
# FILE: shared/utils/schedule/models.py
# ============================================================================
"""
NBA Schedule Data Models.

Contains data classes and enums for schedule-related objects.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class GameType(Enum):
    """Enum for game type filtering."""
    ALL = "all"                          # All games including preseason and All-Star
    REGULAR_PLAYOFF = "regular_playoff"  # Regular season + playoffs (no preseason/All-Star)
    PLAYOFF_ONLY = "playoff_only"        # Only playoff and play-in games
    REGULAR_ONLY = "regular_only"        # Only regular season games


@dataclass
class NBAGame:
    """Standardized NBA game data structure."""
    game_id: str
    game_code: str
    game_date: str  # YYYY-MM-DD format
    away_team: str  # Team code (e.g., 'LAL')
    home_team: str  # Team code (e.g., 'GSW')
    away_team_full: str  # Full name (e.g., 'Los Angeles Lakers')
    home_team_full: str  # Full name (e.g., 'Golden State Warriors')
    game_status: int
    completed: bool
    game_label: str
    game_sub_label: str
    week_name: str
    week_number: int
    game_type: str  # 'regular_season', 'playoff', 'play_in', 'all_star_special', 'preseason'
    commence_time: str  # ISO format
    season_year: int
    
    @property
    def matchup(self) -> str:
        """Return matchup string (e.g., 'LAL@GSW')."""
        return f"{self.away_team}@{self.home_team}"
    
    @property
    def is_playoff(self) -> bool:
        """Check if game is playoff or play-in."""
        return self.game_type in ['playoff', 'play_in']
    
    @property
    def is_regular_season(self) -> bool:
        """Check if game is regular season."""
        return self.game_type == 'regular_season'
    
    def to_dict(self) -> dict:
        """Convert to dictionary for BigQuery loading."""
        return {
            'game_id': self.game_id,
            'game_code': self.game_code,
            'game_date': self.game_date,
            'away_team': self.away_team,
            'home_team': self.home_team,
            'away_team_full': self.away_team_full,
            'home_team_full': self.home_team_full,
            'game_status': self.game_status,
            'completed': self.completed,
            'game_label': self.game_label,
            'game_sub_label': self.game_sub_label,
            'week_name': self.week_name,
            'week_number': self.week_number,
            'game_type': self.game_type,
            'commence_time': self.commence_time,
            'season_year': self.season_year,
            'matchup': self.matchup
        }