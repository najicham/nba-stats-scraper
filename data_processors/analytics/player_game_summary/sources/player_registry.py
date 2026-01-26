"""
Player Registry Handler for Player Game Summary

Wrapper around RegistryReader for universal player ID integration.

Extracted from: player_game_summary_processor.py::calculate_analytics()
"""

import logging
from typing import Dict, List, Optional
import pandas as pd
from shared.utils.player_registry import RegistryReader, PlayerNotFoundError

logger = logging.getLogger(__name__)


class PlayerRegistryHandler:
    """
    Handle universal player ID lookups with batch processing and failure tracking.

    Manages:
    - Batch lookup for efficiency
    - Registry failure tracking
    - Season context setting
    - Statistics tracking
    """

    def __init__(self, source_name: str = 'player_game_summary', cache_ttl_seconds: int = 300):
        """
        Initialize player registry handler.

        Args:
            source_name: Name of source processor
            cache_ttl_seconds: Cache TTL in seconds
        """
        self.registry = RegistryReader(
            source_name=source_name,
            cache_ttl_seconds=cache_ttl_seconds
        )

        self.registry_stats = {
            'players_found': 0,
            'players_not_found': 0,
            'records_skipped': 0
        }

        self.registry_failures: List[Dict] = []

    def batch_lookup_universal_ids(
        self,
        player_lookups: List[str],
        season_year: Optional[int] = None
    ) -> Dict[str, str]:
        """
        Batch lookup universal player IDs.

        Args:
            player_lookups: List of player lookup strings
            season_year: Season year (e.g., 2024 for 2024-25 season)

        Returns:
            Dictionary mapping player_lookup to universal_player_id
        """
        # Set season context if provided
        if season_year:
            season_str = f"{season_year}-{str(season_year + 1)[-2:]}"
            self.registry.set_default_context(season=season_str)
            logger.info(f"Registry context: {season_str}")

        logger.info(f"Batch lookup for {len(player_lookups)} players")

        # Skip logging unresolved players here - we'll log them during game processing
        # with full context (game_id, game_date, etc.)
        uid_map = self.registry.get_universal_ids_batch(
            player_lookups,
            skip_unresolved_logging=True
        )

        self.registry_stats['players_found'] = len(uid_map)
        self.registry_stats['players_not_found'] = len(player_lookups) - len(uid_map)

        logger.info(
            f"Registry: {self.registry_stats['players_found']} found, "
            f"{self.registry_stats['players_not_found']} not found"
        )

        return uid_map

    def track_registry_failure(
        self,
        player_lookup: str,
        game_date: pd.Timestamp,
        team_abbr: Optional[str] = None,
        season_year: Optional[int] = None,
        game_id: Optional[str] = None
    ) -> None:
        """
        Track a registry lookup failure for observability.

        Args:
            player_lookup: Player lookup string
            game_date: Game date
            team_abbr: Team abbreviation
            season_year: Season year
            game_id: Game ID
        """
        self.registry_failures.append({
            'player_lookup': player_lookup,
            'game_date': game_date,
            'team_abbr': team_abbr,
            'season': f"{int(season_year)}-{str(int(season_year) + 1)[-2:]}" if season_year else None,
            'game_id': game_id
        })

        self.registry_stats['records_skipped'] += 1

    def log_unresolved_player(
        self,
        player_lookup: str,
        game_context: Dict
    ) -> None:
        """
        Log an unresolved player with game context.

        Args:
            player_lookup: Player lookup string
            game_context: Dictionary with game context (game_id, game_date, etc.)
        """
        self.registry._log_unresolved_player(player_lookup, game_context)

    def get_stats(self) -> Dict:
        """
        Get registry statistics.

        Returns:
            Dictionary with registry stats
        """
        return {
            'registry_players_found': self.registry_stats['players_found'],
            'registry_players_not_found': self.registry_stats['players_not_found'],
            'registry_records_skipped': self.registry_stats['records_skipped'],
            'registry_failures_count': len(self.registry_failures)
        }

    def get_failures(self) -> List[Dict]:
        """
        Get registry failures list.

        Returns:
            List of registry failure records
        """
        return self.registry_failures
