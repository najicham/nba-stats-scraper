# File: processors/espn/__init__.py
# Description: Package initialization for ESPN processors
"""
ESPN data processors.
"""

from .espn_boxscore_processor import EspnBoxscoreProcessor
from .espn_team_roster_processor import EspnTeamRosterProcessor
from .espn_scoreboard_processor import EspnScoreboardProcessor


__all__ = [
  'EspnBoxscoreProcessor',
  'EspnTeamRosterProcessor',
  'EspnScoreboardProcessor',
]