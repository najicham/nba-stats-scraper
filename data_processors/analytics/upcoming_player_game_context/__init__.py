# upcoming_player_game_context/__init__.py
"""
Upcoming Player Game Context Processor.

Generates pre-game context for players with games scheduled.

REFACTORED: Main processor split into modules for maintainability:
- player_stats.py: Player fatigue and performance metrics
- team_context.py: Opponent metrics and variance calculations
- travel_context.py: Travel distance and timezone calculations
- betting_data.py: Prop lines, game lines, and public betting data

Includes async version for improved BigQuery concurrency:
- UpcomingPlayerGameContextProcessor: Original sync implementation
- AsyncUpcomingPlayerGameContextProcessor: Async with concurrent queries
"""

from .upcoming_player_game_context_processor import UpcomingPlayerGameContextProcessor
from .async_upcoming_player_game_context_processor import AsyncUpcomingPlayerGameContextProcessor

# Re-export extracted modules for convenience
from .player_stats import (
    calculate_fatigue_metrics,
    calculate_performance_metrics,
    calculate_prop_streaks,
    determine_sample_quality,
    parse_minutes
)

from .team_context import TeamContextCalculator
from .travel_context import TravelContextCalculator
from .betting_data import BettingDataExtractor

__all__ = [
    'UpcomingPlayerGameContextProcessor',
    'AsyncUpcomingPlayerGameContextProcessor',
    'TeamContextCalculator',
    'TravelContextCalculator',
    'BettingDataExtractor',
    'calculate_fatigue_metrics',
    'calculate_performance_metrics',
    'calculate_prop_streaks',
    'determine_sample_quality',
    'parse_minutes',
]
