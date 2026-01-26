#!/usr/bin/env python3
"""
Input validation utilities for security hardening.

This module provides validation functions to prevent injection attacks
and ensure data integrity across the application.

Created: 2026-01-19 (Week 0 Security - Issue #4)
"""

import re
from datetime import datetime, date
from typing import Optional, List


# Allowlist of valid GCP project IDs
VALID_PROJECT_IDS = [
    'nba-props-platform',
    'nba-props-dev',
    'nba-props-staging',
]


class ValidationError(ValueError):
    """Raised when input validation fails."""
    pass


def validate_game_date(game_date: str, allow_future: bool = True) -> str:
    """
    Validate and normalize a game date string.

    Args:
        game_date: Date string in YYYY-MM-DD format
        allow_future: If True, allow future dates. If False, only allow past/today.

    Returns:
        str: Normalized date string (YYYY-MM-DD)

    Raises:
        ValidationError: If date format is invalid or date is out of acceptable range

    Examples:
        >>> validate_game_date('2026-01-19')
        '2026-01-19'
        >>> validate_game_date('2026-13-01')  # Invalid month
        ValidationError: Invalid date format
        >>> validate_game_date("2026-01-19' OR '1'='1")  # SQL injection attempt
        ValidationError: Invalid date format
    """
    if not isinstance(game_date, str):
        raise ValidationError(f"Game date must be a string, got {type(game_date)}")

    # Check format: YYYY-MM-DD (strict regex)
    date_pattern = r'^(\d{4})-(\d{2})-(\d{2})$'
    match = re.match(date_pattern, game_date)

    if not match:
        raise ValidationError(
            f"Invalid date format: '{game_date}'. Expected YYYY-MM-DD"
        )

    year, month, day = match.groups()

    # Validate date components and create date object
    try:
        parsed_date = date(int(year), int(month), int(day))
    except ValueError as e:
        raise ValidationError(f"Invalid date: {e}")

    # Check year range (reasonable bounds for NBA data)
    if not (1946 <= parsed_date.year <= 2100):
        raise ValidationError(
            f"Date year out of range: {parsed_date.year}. "
            "Expected 1946-2100 (NBA inception to reasonable future)"
        )

    # Check if future dates are allowed
    if not allow_future and parsed_date > date.today():
        raise ValidationError(
            f"Future dates not allowed: {game_date} is after today"
        )

    # Return normalized format
    return parsed_date.isoformat()


def validate_project_id(project_id: str, allowlist: Optional[List[str]] = None) -> str:
    """
    Validate GCP project ID against an allowlist.

    Args:
        project_id: GCP project ID to validate
        allowlist: Optional list of valid project IDs. Defaults to VALID_PROJECT_IDS.

    Returns:
        str: The validated project ID

    Raises:
        ValidationError: If project ID is not in the allowlist

    Examples:
        >>> validate_project_id('nba-props-platform')
        'nba-props-platform'
        >>> validate_project_id('malicious-project')
        ValidationError: Invalid project_id
    """
    if not isinstance(project_id, str):
        raise ValidationError(
            f"Project ID must be a string, got {type(project_id)}"
        )

    if allowlist is None:
        allowlist = VALID_PROJECT_IDS

    if project_id not in allowlist:
        raise ValidationError(
            f"Invalid project_id: '{project_id}'. "
            f"Must be one of: {', '.join(allowlist)}"
        )

    return project_id


def validate_team_abbr(team_abbr: str) -> str:
    """
    Validate NBA team abbreviation format.

    Args:
        team_abbr: Team abbreviation (e.g., 'LAL', 'BOS')

    Returns:
        str: Uppercased team abbreviation

    Raises:
        ValidationError: If format is invalid

    Examples:
        >>> validate_team_abbr('LAL')
        'LAL'
        >>> validate_team_abbr('lal')
        'LAL'
        >>> validate_team_abbr('INVALID123')
        ValidationError: Invalid team abbreviation
    """
    if not isinstance(team_abbr, str):
        raise ValidationError(
            f"Team abbreviation must be a string, got {type(team_abbr)}"
        )

    # NBA team abbreviations are 2-3 uppercase letters
    team_pattern = r'^[A-Z]{2,3}$'
    normalized = team_abbr.upper()

    if not re.match(team_pattern, normalized):
        raise ValidationError(
            f"Invalid team abbreviation: '{team_abbr}'. "
            "Expected 2-3 uppercase letters"
        )

    return normalized


def validate_game_id(game_id: str, format_type: str = 'nba') -> str:
    """
    Validate game ID format.

    Args:
        game_id: Game ID to validate
        format_type: Format type ('nba' for 0021500001, 'bdl' for 20260119_LAL_BOS)

    Returns:
        str: Validated game ID

    Raises:
        ValidationError: If format is invalid

    Examples:
        >>> validate_game_id('0021500001', 'nba')
        '0021500001'
        >>> validate_game_id('20260119_LAL_BOS', 'bdl')
        '20260119_LAL_BOS'
    """
    if not isinstance(game_id, str):
        raise ValidationError(f"Game ID must be a string, got {type(game_id)}")

    if format_type == 'nba':
        # NBA.com format: 10 digits (e.g., 0021500001)
        if not re.match(r'^\d{10}$', game_id):
            raise ValidationError(
                f"Invalid NBA game ID: '{game_id}'. Expected 10 digits"
            )
    elif format_type == 'bdl':
        # BallerDontLie format: YYYYMMDD_AWAY_HOME
        if not re.match(r'^\d{8}_[A-Z]{2,3}_[A-Z]{2,3}$', game_id):
            raise ValidationError(
                f"Invalid BDL game ID: '{game_id}'. "
                "Expected format: YYYYMMDD_AWAY_HOME"
            )
    else:
        raise ValidationError(f"Unknown game ID format type: '{format_type}'")

    return game_id


def validate_player_lookup(player_lookup: str) -> str:
    """
    Validate player lookup string format.

    Args:
        player_lookup: Player lookup string (normalized name format)

    Returns:
        str: Validated player lookup

    Raises:
        ValidationError: If format is invalid

    Examples:
        >>> validate_player_lookup('lebron_james')
        'lebron_james'
        >>> validate_player_lookup("lebron'; DROP TABLE players; --")
        ValidationError: Invalid player lookup
    """
    if not isinstance(player_lookup, str):
        raise ValidationError(
            f"Player lookup must be a string, got {type(player_lookup)}"
        )

    # Player lookups should be lowercase alphanumeric with underscores/hyphens
    # and optional dots (for suffixes like jr., iii)
    player_pattern = r'^[a-z0-9_.-]+$'

    if not re.match(player_pattern, player_lookup.lower()):
        raise ValidationError(
            f"Invalid player lookup: '{player_lookup}'. "
            "Expected lowercase letters, numbers, underscores, hyphens, and dots only"
        )

    return player_lookup.lower()


# Convenience validation for common date ranges
def validate_date_range(start_date: str, end_date: str) -> tuple[str, str]:
    """
    Validate a date range.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        tuple: (validated_start_date, validated_end_date)

    Raises:
        ValidationError: If dates are invalid or range is backwards
    """
    start = validate_game_date(start_date)
    end = validate_game_date(end_date)

    start_obj = date.fromisoformat(start)
    end_obj = date.fromisoformat(end)

    if start_obj > end_obj:
        raise ValidationError(
            f"Invalid date range: start_date ({start}) is after end_date ({end})"
        )

    return start, end
