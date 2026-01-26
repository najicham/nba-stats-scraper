#!/usr/bin/env python3
"""
Path: data_processors/analytics/upcoming_player_game_context/calculators/game_utils.py

Game Utilities - Helper functions for game context processing.

This module provides utility functions for:
- Determining player's team
- Finding opponent team
- Extracting game time in local timezone
- Determining season phase
- Building source tracking fields
"""

import hashlib
import logging
from datetime import date, datetime
from typing import Dict, Optional
import pandas as pd

logger = logging.getLogger(__name__)


class GameUtils:
    """Utility functions for game context processing."""

    @staticmethod
    def determine_player_team(
        player_lookup: str,
        player_info: Dict,
        historical_boxscores: Dict
    ) -> Optional[str]:
        """
        Determine which team the player is on.

        Args:
            player_lookup: Player lookup key
            player_info: Player info dict (may contain team_abbr from gamebook)
            historical_boxscores: Dict of historical boxscore DataFrames

        Returns:
            Team abbreviation or None if not found
        """
        # First check player_info - gamebook already has team_abbr
        if player_info.get('team_abbr'):
            return player_info['team_abbr']

        # Fallback: Use most recent boxscore (for daily mode without gamebook)
        historical_data = historical_boxscores.get(player_lookup, pd.DataFrame())
        if not historical_data.empty:
            most_recent = historical_data.iloc[0]
            return most_recent.get('team_abbr')

        return None

    @staticmethod
    def get_opponent_team(team_abbr: str, game_info: Dict) -> str:
        """
        Get opponent team abbreviation.

        Args:
            team_abbr: Player's team abbreviation
            game_info: Game info dict with home_team_abbr and away_team_abbr

        Returns:
            Opponent team abbreviation
        """
        if team_abbr == game_info['home_team_abbr']:
            return game_info['away_team_abbr']
        else:
            return game_info['home_team_abbr']

    @staticmethod
    def extract_game_time(game_info: Dict) -> Optional[str]:
        """
        Extract game time in local arena timezone.

        Args:
            game_info: Game info dict with game_date_est and arena_timezone

        Returns:
            Formatted game time string (e.g., "7:30 PM ET") or None if error
        """
        try:
            from zoneinfo import ZoneInfo

            game_dt = game_info.get('game_date_est')
            if not game_dt:
                return None

            if isinstance(game_dt, str):
                game_dt = datetime.fromisoformat(game_dt.replace('Z', '+00:00'))
            elif not isinstance(game_dt, datetime):
                return None

            arena_tz_str = game_info.get('arena_timezone', 'America/New_York')
            if not arena_tz_str:
                arena_tz_str = 'America/New_York'

            try:
                arena_tz = ZoneInfo(arena_tz_str)
            except (KeyError, ValueError):
                arena_tz = ZoneInfo('America/New_York')

            if game_dt.tzinfo is None:
                eastern = ZoneInfo('America/New_York')
                game_dt = game_dt.replace(tzinfo=eastern)

            local_dt = game_dt.astimezone(arena_tz)

            tz_abbrev_map = {
                'America/New_York': 'ET',
                'America/Chicago': 'CT',
                'America/Denver': 'MT',
                'America/Los_Angeles': 'PT',
                'America/Phoenix': 'MST',
            }
            tz_abbr = tz_abbrev_map.get(arena_tz_str, local_dt.strftime('%Z'))

            return f"{local_dt.strftime('%I:%M %p').lstrip('0')} {tz_abbr}"

        except (ValueError, TypeError, AttributeError, KeyError) as e:
            logger.debug(f"Could not extract game time: {e}")
            return None

    @staticmethod
    def determine_season_phase(game_date: date) -> str:
        """
        Determine season phase based on date.

        Args:
            game_date: Game date

        Returns:
            Season phase: 'early', 'mid', 'late', or 'playoffs'
        """
        month = game_date.month

        if month in [10, 11]:
            return 'early'
        elif month in [12, 1, 2]:
            return 'mid'
        elif month in [3, 4]:
            return 'late'
        else:
            return 'playoffs'

    @staticmethod
    def build_source_tracking_fields(source_tracking: Dict) -> Dict:
        """
        Build source tracking fields for output record.

        Args:
            source_tracking: Dict with source tracking info (last_updated, rows_found)

        Returns:
            Dict with hash fields for each source
        """
        def compute_hash(source_key: str) -> Optional[str]:
            tracking = source_tracking.get(source_key, {})
            if not tracking.get('last_updated'):
                return None
            hash_input = f"{tracking.get('last_updated', '')}:{tracking.get('rows_found', 0)}"
            return hashlib.md5(hash_input.encode()).hexdigest()[:16]

        return {
            'source_boxscore_hash': compute_hash('boxscore'),
            'source_schedule_hash': compute_hash('schedule'),
            'source_props_hash': compute_hash('props'),
            'source_game_lines_hash': compute_hash('game_lines'),
        }
