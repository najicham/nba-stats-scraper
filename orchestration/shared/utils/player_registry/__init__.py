#!/usr/bin/env python3
"""
File: shared/utils/player_registry/__init__.py

NBA Player Registry System

Provides read-only access to the authoritative NBA players registry.
Used by downstream processors for player identification and validation.

Main Classes:
    RegistryReader - Read-only registry access with caching
    UniversalPlayerIDResolver - Create/resolve universal player IDs (write side)

Exceptions:
    PlayerNotFoundError - Player not in registry
    MultipleRecordsError - Player on multiple teams (need team filter)
    AmbiguousNameError - Multiple players match search
    RegistryConnectionError - BigQuery connection failed

Example:
    from shared.utils.player_registry import RegistryReader, PlayerNotFoundError
    
    # Initialize with caching
    registry = RegistryReader(
        source_name='player_game_summary',
        cache_ttl_seconds=300
    )
    
    # Set context for unresolved tracking
    registry.set_default_context(season='2024-25')
    
    # Get universal ID (strict mode)
    try:
        uid = registry.get_universal_id('lebronjames')
    except PlayerNotFoundError:
        # Handle missing player
        pass
    
    # Get universal ID (lenient mode)
    uid = registry.get_universal_id('unknownplayer', required=False)
    if uid is None:
        # Player not found, but no exception raised
        pass
    
    # Batch operations
    player_list = ['lebronjames', 'stephencurry', 'kevindurant']
    uids = registry.get_universal_ids_batch(player_list)
    
    # Flush unresolved players at end of run
    registry.flush_unresolved_players()
"""

from .reader import RegistryReader
from .resolver import UniversalPlayerIDResolver
from .exceptions import (
    RegistryError,
    PlayerNotFoundError,
    MultipleRecordsError,
    AmbiguousNameError,
    RegistryConnectionError
)

__all__ = [
    'RegistryReader',
    'UniversalPlayerIDResolver',
    'RegistryError',
    'PlayerNotFoundError',
    'MultipleRecordsError',
    'AmbiguousNameError',
    'RegistryConnectionError'
]

__version__ = '1.0.0'