#!/usr/bin/env python3
"""
MLB Player Registry Exceptions

Custom exceptions for MLB player registry operations.

Created: 2026-01-13
"""


class MLBRegistryError(Exception):
    """Base exception for MLB registry errors."""

    def __init__(self, message: str, player_lookup: str = None):
        self.message = message
        self.player_lookup = player_lookup
        super().__init__(self.message)


class MLBPlayerNotFoundError(MLBRegistryError):
    """Raised when player is not found in registry."""

    def __init__(self, player_lookup: str, player_type: str = None):
        self.player_type = player_type
        message = f"Player not found in MLB registry: {player_lookup}"
        if player_type:
            message += f" (type: {player_type})"
        super().__init__(message, player_lookup)


class MLBMultiplePlayersError(MLBRegistryError):
    """Raised when multiple players match a lookup (ambiguous)."""

    def __init__(self, player_lookup: str, matches: list):
        self.matches = matches
        message = f"Multiple players match '{player_lookup}': {matches}"
        super().__init__(message, player_lookup)


class MLBRegistryConnectionError(MLBRegistryError):
    """Raised when registry connection fails."""

    def __init__(self, message: str, original_error: Exception = None):
        self.original_error = original_error
        super().__init__(message)
