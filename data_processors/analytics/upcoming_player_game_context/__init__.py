# upcoming_player_game_context/__init__.py
"""
Upcoming Player Game Context Processor.

Generates pre-game context for players with games scheduled.

Includes async version for improved BigQuery concurrency:
- UpcomingPlayerGameContextProcessor: Original sync implementation
- AsyncUpcomingPlayerGameContextProcessor: Async with concurrent queries
"""

from .upcoming_player_game_context_processor import UpcomingPlayerGameContextProcessor
from .async_upcoming_player_game_context_processor import AsyncUpcomingPlayerGameContextProcessor

__all__ = [
    'UpcomingPlayerGameContextProcessor',
    'AsyncUpcomingPlayerGameContextProcessor',
]
