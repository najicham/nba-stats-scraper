"""
Validation Context Module

Provides context about a date being validated:
- Schedule context (games, teams, bootstrap status)
- Player universe (who should be processed)
- Time context (expected run times for live monitoring)
"""

from shared.validation.context.schedule_context import (
    ScheduleContext,
    GameInfo,
    get_schedule_context,
)
from shared.validation.context.player_universe import (
    PlayerUniverse,
    get_player_universe,
)

__all__ = [
    'ScheduleContext',
    'GameInfo',
    'get_schedule_context',
    'PlayerUniverse',
    'get_player_universe',
]
