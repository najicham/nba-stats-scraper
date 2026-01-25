# shared/utils/__init__.py
"""
Shared utilities for NBA analytics platform - MINIMAL VERSION for Cloud Functions

This version only imports utilities that don't have heavy dependencies.
For specific utilities, import directly from the module:
    from shared.utils.phase_execution_logger import log_phase_execution
"""

# Only import lightweight utilities that don't cascade dependencies
# Game ID conversion utilities (no external dependencies)
from .game_id_converter import (
    GameIdConverter,
    get_game_id_converter,
    to_standard_game_id,
    parse_game_id,
    is_standard_game_id
)

# Environment validation utilities (no external dependencies)
from .env_validation import (
    validate_required_env_vars,
    get_required_env_var,
    MissingEnvironmentVariablesError
)

__all__ = [
    # Game ID converter
    "GameIdConverter",
    "get_game_id_converter",
    "to_standard_game_id",
    "parse_game_id",
    "is_standard_game_id",
    # Environment validation
    "validate_required_env_vars",
    "get_required_env_var",
    "MissingEnvironmentVariablesError",
]
