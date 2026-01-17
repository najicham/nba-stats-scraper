# ============================================================================
# FILE: shared/utils/schedule/__init__.py
# ============================================================================
"""
NBA Schedule Module - Schedule reading and querying utilities.

This module provides centralized access to NBA schedule data with automatic
optimization using BigQuery when available, falling back to GCS.

Main Classes:
    NBAScheduleService: Primary interface for schedule queries
    NBAGame: Rich game data object
    GameType: Enum for game type filtering

Usage:
    from shared.utils.schedule import NBAScheduleService, GameType
    
    # Default: Database-first with GCS fallback (fast queries)
    schedule = NBAScheduleService()
    has_games = schedule.has_games_on_date('2024-01-15')
    
    # Explicit GCS-only mode (for backfills)
    schedule = NBAScheduleService.from_gcs_only()
    games = schedule.get_games_for_date('2024-01-15')
"""

from .service import NBAScheduleService
from .models import NBAGame, GameType
from .database_reader import ScheduleDatabaseReader
from .gcs_reader import ScheduleGCSReader

__all__ = [
    'NBAScheduleService',
    'NBAGame', 
    'GameType',
    'ScheduleDatabaseReader',
    'ScheduleGCSReader'
]

__version__ = '1.0.0'