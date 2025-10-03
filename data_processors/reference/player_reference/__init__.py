# File: data_processors/reference/player_reference/__init__.py
# Description: Package initialization for NBA Reference Data processors
"""
NBA Reference Data processors for foundational lookup tables and player name resolution.
"""
from .roster_registry_processor import RosterRegistryProcessor

__all__ = ['RosterRegistryProcessor']
__version__ = '1.0.0'
__author__ = 'NBA Props Platform'
__description__ = 'NBA reference data infrastructure processors'
