#!/usr/bin/env python3
"""
Path: data_processors/analytics/upcoming_player_game_context/loaders/__init__.py

Loader modules for upcoming player game context processor.

This package contains data extraction classes that were moved out of the main
processor file to improve maintainability and reduce file size.

Exports:
    PlayerDataLoader: Handles player extraction (daily/backfill modes)
    GameDataLoader: Handles game data extraction (schedule, boxscores, betting, etc.)
"""

from .player_loaders import PlayerDataLoader
from .game_data_loaders import GameDataLoader

__all__ = [
    'PlayerDataLoader',
    'GameDataLoader',
]
