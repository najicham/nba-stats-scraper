#!/usr/bin/env python3
"""
MLB Registry Reader

Read-only access to the MLB player registry with caching.
Used by analytics processors and prediction systems.

Features:
- TTL-based caching for performance
- Strict and lenient lookup modes
- Bulk operations for batch processing
- Unresolved player tracking

Usage:
    from shared.utils.mlb_player_registry import MLBRegistryReader

    registry = MLBRegistryReader(
        source_name='pitcher_strikeouts_predictor',
        cache_ttl_seconds=300
    )

    # Strict mode (raises exception if not found)
    uid = registry.get_universal_id('loganwebb', player_type='pitcher')

    # Lenient mode (returns None if not found)
    uid = registry.get_universal_id('unknownplayer', required=False)

    # Batch lookup
    uids = registry.get_universal_ids_batch(['loganwebb', 'gerritcole'])

Created: 2026-01-13
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field

from google.cloud import bigquery

from .exceptions import MLBPlayerNotFoundError, MLBRegistryConnectionError

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cache entry with expiration."""
    value: str
    expires_at: datetime


@dataclass
class UnresolvedPlayer:
    """Tracks unresolved player lookups."""
    player_lookup: str
    player_type: str
    source: str
    first_seen: datetime = field(default_factory=datetime.utcnow)
    count: int = 1


class MLBRegistryReader:
    """
    Read-only access to MLB player registry.

    Provides cached lookups for universal player IDs with support for
    both strict and lenient modes.
    """

    def __init__(
        self,
        source_name: str,
        cache_ttl_seconds: int = 300,
        project_id: str = None,
        test_mode: bool = False
    ):
        """
        Initialize MLB registry reader.

        Args:
            source_name: Name of the calling processor/system
            cache_ttl_seconds: Cache TTL in seconds (default 5 minutes)
            project_id: GCP project ID (default from env)
            test_mode: Use test tables
        """
        self.source_name = source_name
        self.cache_ttl_seconds = cache_ttl_seconds
        self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

        # Table names
        if test_mode:
            self.registry_table = f"{self.project_id}.mlb_reference.mlb_players_registry_test"
        else:
            self.registry_table = f"{self.project_id}.mlb_reference.mlb_players_registry"

        # Initialize BigQuery client
        try:
            self.bq_client = bigquery.Client(project=self.project_id)
        except Exception as e:
            raise MLBRegistryConnectionError(f"Failed to connect to BigQuery: {e}", e)

        # Caches
        self._id_cache: Dict[str, CacheEntry] = {}
        self._full_cache_loaded = False
        self._full_cache_expires: Optional[datetime] = None

        # Track unresolved players
        self._unresolved: Dict[str, UnresolvedPlayer] = {}

        # Stats
        self.stats = {
            'lookups': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'not_found': 0
        }

        logger.info(f"Initialized MLBRegistryReader for {source_name}")

    def get_universal_id(
        self,
        player_lookup: str,
        player_type: str = None,
        required: bool = True
    ) -> Optional[str]:
        """
        Get universal player ID.

        Args:
            player_lookup: Normalized player name
            player_type: 'pitcher' or 'batter' (optional)
            required: If True, raises exception when not found

        Returns:
            Universal player ID or None (if required=False)

        Raises:
            MLBPlayerNotFoundError: If required=True and player not found
        """
        self.stats['lookups'] += 1

        # Check cache
        cache_key = f"{player_lookup}_{player_type or 'any'}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            self.stats['cache_hits'] += 1
            return cached

        self.stats['cache_misses'] += 1

        # Query registry
        universal_id = self._lookup_from_registry(player_lookup, player_type)

        if universal_id:
            self._add_to_cache(cache_key, universal_id)
            return universal_id

        # Not found
        self.stats['not_found'] += 1
        self._track_unresolved(player_lookup, player_type or 'unknown')

        if required:
            raise MLBPlayerNotFoundError(player_lookup, player_type)

        return None

    def get_universal_ids_batch(
        self,
        player_lookups: List[str],
        player_type: str = None,
        required: bool = False
    ) -> Dict[str, Optional[str]]:
        """
        Batch lookup universal IDs.

        Args:
            player_lookups: List of normalized player names
            player_type: 'pitcher' or 'batter' (optional)
            required: If True, raises exception for any not found

        Returns:
            Dict mapping player_lookup -> universal_id (or None)
        """
        if not player_lookups:
            return {}

        results = {}
        to_query = []

        # Check cache first
        for lookup in player_lookups:
            cache_key = f"{lookup}_{player_type or 'any'}"
            cached = self._get_from_cache(cache_key)
            if cached is not None:
                results[lookup] = cached
                self.stats['cache_hits'] += 1
            else:
                to_query.append(lookup)
                self.stats['cache_misses'] += 1

        # Query remaining
        if to_query:
            queried = self._bulk_lookup_from_registry(to_query, player_type)

            for lookup in to_query:
                uid = queried.get(lookup)
                results[lookup] = uid

                if uid:
                    cache_key = f"{lookup}_{player_type or 'any'}"
                    self._add_to_cache(cache_key, uid)
                else:
                    self.stats['not_found'] += 1
                    self._track_unresolved(lookup, player_type or 'unknown')

                    if required:
                        raise MLBPlayerNotFoundError(lookup, player_type)

        self.stats['lookups'] += len(player_lookups)
        return results

    def _get_from_cache(self, key: str) -> Optional[str]:
        """Get value from cache if not expired."""
        if key in self._id_cache:
            entry = self._id_cache[key]
            if datetime.utcnow() < entry.expires_at:
                return entry.value
            else:
                del self._id_cache[key]
        return None

    def _add_to_cache(self, key: str, value: str) -> None:
        """Add value to cache with TTL."""
        expires_at = datetime.utcnow() + timedelta(seconds=self.cache_ttl_seconds)
        self._id_cache[key] = CacheEntry(value=value, expires_at=expires_at)

    def _lookup_from_registry(
        self,
        player_lookup: str,
        player_type: str = None
    ) -> Optional[str]:
        """Query registry for universal ID."""
        type_filter = ""
        if player_type:
            type_filter = f"AND player_type = '{player_type.upper()}'"

        query = f"""
        SELECT universal_player_id
        FROM `{self.registry_table}`
        WHERE player_lookup = @player_lookup
        {type_filter}
        AND universal_player_id IS NOT NULL
        ORDER BY processed_at DESC
        LIMIT 1
        """

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup)
        ])

        try:
            results = list(self.bq_client.query(query, job_config=job_config).result())
            if results:
                return results[0].universal_player_id
            return None
        except Exception as e:
            logger.error(f"Registry lookup failed for {player_lookup}: {e}", exc_info=True)
            return None

    def _bulk_lookup_from_registry(
        self,
        player_lookups: List[str],
        player_type: str = None
    ) -> Dict[str, str]:
        """Bulk query registry for universal IDs."""
        if not player_lookups:
            return {}

        type_filter = ""
        if player_type:
            type_filter = f"AND player_type = '{player_type.upper()}'"

        query = f"""
        SELECT player_lookup, universal_player_id
        FROM `{self.registry_table}`
        WHERE player_lookup IN UNNEST(@player_lookups)
        {type_filter}
        AND universal_player_id IS NOT NULL
        """

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups)
        ])

        try:
            results = self.bq_client.query(query, job_config=job_config).result()
            return {row.player_lookup: row.universal_player_id for row in results}
        except Exception as e:
            logger.error(f"Bulk registry lookup failed: {e}", exc_info=True)
            return {}

    def _track_unresolved(self, player_lookup: str, player_type: str) -> None:
        """Track unresolved player for later review."""
        key = f"{player_lookup}_{player_type}"
        if key in self._unresolved:
            self._unresolved[key].count += 1
        else:
            self._unresolved[key] = UnresolvedPlayer(
                player_lookup=player_lookup,
                player_type=player_type,
                source=self.source_name
            )

    def get_unresolved_players(self) -> List[UnresolvedPlayer]:
        """Get list of unresolved players."""
        return list(self._unresolved.values())

    def flush_unresolved_to_bigquery(self) -> int:
        """
        Flush unresolved players to BigQuery for review.

        Returns:
            Number of records flushed
        """
        if not self._unresolved:
            return 0

        # TODO: Implement BigQuery insert for unresolved tracking
        # For now, just log them
        logger.warning(f"Unresolved MLB players ({len(self._unresolved)}):")
        for player in self._unresolved.values():
            logger.warning(f"  {player.player_lookup} ({player.player_type}): {player.count} occurrences")

        count = len(self._unresolved)
        self._unresolved.clear()
        return count

    def preload_cache(self, player_type: str = None) -> int:
        """
        Preload entire registry into cache.

        Args:
            player_type: Optionally filter by type

        Returns:
            Number of players cached
        """
        type_filter = ""
        if player_type:
            type_filter = f"WHERE player_type = '{player_type.upper()}'"

        query = f"""
        SELECT player_lookup, universal_player_id, player_type
        FROM `{self.registry_table}`
        {type_filter}
        """

        try:
            results = list(self.bq_client.query(query).result())

            for row in results:
                cache_key = f"{row.player_lookup}_{row.player_type.lower()}"
                self._add_to_cache(cache_key, row.universal_player_id)

                # Also cache with 'any' type
                cache_key_any = f"{row.player_lookup}_any"
                if cache_key_any not in self._id_cache:
                    self._add_to_cache(cache_key_any, row.universal_player_id)

            logger.info(f"Preloaded {len(results)} MLB players into cache")
            return len(results)

        except Exception as e:
            logger.error(f"Failed to preload cache: {e}", exc_info=True)
            return 0

    def clear_cache(self) -> None:
        """Clear the cache."""
        self._id_cache.clear()
        logger.info("MLB registry cache cleared")

    def get_stats(self) -> Dict:
        """Get reader statistics."""
        hit_rate = 0
        if self.stats['lookups'] > 0:
            hit_rate = self.stats['cache_hits'] / self.stats['lookups'] * 100

        return {
            **self.stats,
            'cache_size': len(self._id_cache),
            'cache_hit_rate': round(hit_rate, 1),
            'unresolved_count': len(self._unresolved)
        }
