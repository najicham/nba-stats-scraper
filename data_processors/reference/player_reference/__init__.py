# File: processors/nba_reference/__init__.py
# Description: Package initialization for NBA Reference Data processors
"""
NBA Reference Data processors for foundational lookup tables and player name resolution.

This package contains processors that maintain reference data infrastructure:
- NBA Players Registry: Authoritative player validation from gamebook data
- Player Name Resolution: Alias mappings for consistent cross-source identification
- Manual Review Tools: CLI and workflow support for name resolution

These are foundational processors that other data processors depend on for
consistent player identification across all NBA data sources.
"""

from .nba_players_registry_processor import NbaPlayersRegistryProcessor

__all__ = ['NbaPlayersRegistryProcessor']

# Version info
__version__ = '1.0.0'
__author__ = 'NBA Props Platform'
__description__ = 'NBA reference data infrastructure processors'