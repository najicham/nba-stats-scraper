#!/usr/bin/env python3
"""
MLB Player Registry System

Provides authoritative player identification and resolution for MLB data.
Handles both pitchers and batters with unified ID management.

Main Classes:
    MLBRegistryReader - Read-only registry access with caching
    MLBPlayerIDResolver - Create/resolve universal player IDs (write side)

Exceptions:
    MLBPlayerNotFoundError - Player not in registry
    MLBRegistryError - General registry error

Key Features:
- Unified player IDs across data sources (Statcast, Odds API, BDL)
- Separate tracking for pitchers and batters
- Name normalization and alias resolution
- Bulk operations for batch processing

Example:
    from shared.utils.mlb_player_registry import MLBRegistryReader, MLBPlayerNotFoundError

    # Initialize with caching
    registry = MLBRegistryReader(
        source_name='pitcher_strikeouts_predictor',
        cache_ttl_seconds=300
    )

    # Get universal ID (strict mode)
    try:
        uid = registry.get_universal_id('loganwebb', player_type='pitcher')
    except MLBPlayerNotFoundError:
        # Handle missing player
        pass

    # Get universal ID (lenient mode)
    uid = registry.get_universal_id('unknownplayer', required=False)

    # Batch operations
    pitchers = ['loganwebb', 'gerritcole', 'corbinburnes']
    uids = registry.get_universal_ids_batch(pitchers, player_type='pitcher')

Created: 2026-01-13
"""

from .resolver import MLBPlayerIDResolver
from .reader import MLBRegistryReader
from .exceptions import (
    MLBRegistryError,
    MLBPlayerNotFoundError,
    MLBMultiplePlayersError,
    MLBRegistryConnectionError
)

__all__ = [
    'MLBRegistryReader',
    'MLBPlayerIDResolver',
    'MLBRegistryError',
    'MLBPlayerNotFoundError',
    'MLBMultiplePlayersError',
    'MLBRegistryConnectionError'
]

__version__ = '1.0.0'
