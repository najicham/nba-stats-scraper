"""
Shared backfill utilities.

Provides:
- BackfillCheckpoint: Progress persistence for long-running backfills
- get_game_dates_for_range: Schedule-aware date iteration for backfills
"""

from .checkpoint import BackfillCheckpoint
from .schedule_utils import get_game_dates_for_range

__all__ = ['BackfillCheckpoint', 'get_game_dates_for_range']
