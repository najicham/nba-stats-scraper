#!/usr/bin/env python3
"""
File: shared/utils/player_registry/exceptions.py

Custom exceptions for NBA Player Registry operations.
"""


class RegistryError(Exception):
    """Base exception for registry operations."""
    pass


class PlayerNotFoundError(RegistryError):
    """Player does not exist in registry."""
    
    def __init__(self, player_lookup: str, message: str = None):
        self.player_lookup = player_lookup
        if message is None:
            message = f"Player '{player_lookup}' not found in registry"
        super().__init__(message)


class MultipleRecordsError(RegistryError):
    """Player has multiple records (e.g., traded mid-season)."""
    
    def __init__(self, player_lookup: str, teams: list, message: str = None):
        self.player_lookup = player_lookup
        self.teams = teams
        if message is None:
            message = (
                f"Player '{player_lookup}' has multiple records for teams: {teams}. "
                f"Specify team_abbr parameter."
            )
        super().__init__(message)


class AmbiguousNameError(RegistryError):
    """Multiple players match search criteria."""
    
    def __init__(self, name_pattern: str, matches: list, message: str = None):
        self.name_pattern = name_pattern
        self.matches = matches
        if message is None:
            message = (
                f"Multiple players match '{name_pattern}': {matches}. "
                f"Be more specific."
            )
        super().__init__(message)


class RegistryConnectionError(RegistryError):
    """Cannot connect to registry (BigQuery error)."""
    
    def __init__(self, original_error: Exception, message: str = None):
        self.original_error = original_error
        if message is None:
            message = f"Failed to connect to registry: {str(original_error)}"
        super().__init__(message)