"""Data aggregators for player daily cache.

This package contains aggregators that process data from 4 upstream sources:
1. StatsAggregator: player_game_summary (recent performance metrics)
2. TeamAggregator: team_offense_game_summary (team context)
3. ContextAggregator: upcoming_player_game_context (fatigue metrics)
4. ShotZoneAggregator: player_shot_zone_analysis (shot tendencies)
"""

from .stats_aggregator import StatsAggregator
from .team_aggregator import TeamAggregator
from .context_aggregator import ContextAggregator
from .shot_zone_aggregator import ShotZoneAggregator

__all__ = [
    'StatsAggregator',
    'TeamAggregator',
    'ContextAggregator',
    'ShotZoneAggregator',
]
