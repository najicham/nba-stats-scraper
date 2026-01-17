#!/usr/bin/env python3
"""
File: shared/utils/player_registry/resolver.py

Universal Player ID Resolver - Enhanced with Bulk Operations

Provides universal player ID resolution for handling name changes and ensuring
consistent player identification across all analytics tables.

Enhanced with bulk operations for improved performance during batch processing.

USAGE:
- Registry Processors (Write Side): Use this to create/resolve universal IDs
- Downstream Processors (Read Side): Use RegistryReader instead
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Set
import pandas as pd
from google.cloud import bigquery

logger = logging.getLogger(__name__)


class UniversalPlayerIDResolver:
    """
    Resolves and creates universal player IDs for consistent player identification.
    
    Handles name changes by maintaining immutable universal IDs that remain constant
    across name changes, team transfers, and seasons.
    
    Enhanced with bulk operations for batch processing performance.
    
    Example:
        resolver = UniversalPlayerIDResolver(bq_client, project_id)
        
        # Single player
        uid = resolver.resolve_or_create_universal_id('lebronjames')
        
        # Batch processing
        players = ['lebronjames', 'stephencurry', 'kevindurant']
        uid_map = resolver.bulk_resolve_or_create_universal_ids(players)
    """
    
    def __init__(self, bq_client: bigquery.Client, project_id: str, test_mode: bool = False):
        """
        Initialize universal player ID resolver.
        
        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
            test_mode: Use test tables (for development/testing)
        """
        self.bq_client = bq_client
        self.project_id = project_id
        
        # Table names
        if test_mode:
            timestamp_suffix = "FIXED2"
            self.registry_table = f"{project_id}.nba_reference.nba_players_registry_test_{timestamp_suffix}"
            self.alias_table = f"{project_id}.nba_reference.player_aliases_test_{timestamp_suffix}"
        else:
            self.registry_table = f"{project_id}.nba_reference.nba_players_registry"
            self.alias_table = f"{project_id}.nba_reference.player_aliases"
        
        # Performance tracking
        self.stats = {
            'lookups_performed': 0,
            'new_ids_created': 0,
            'cache_hits': 0,
            'alias_resolutions': 0
        }
        
        # Simple in-memory cache for batch operations
        self._id_cache = {}  # player_lookup -> universal_id
        self._cache_populated = False
        
        logger.info(f"Initialized UniversalPlayerIDResolver (test_mode={test_mode})")
    
    def resolve_or_create_universal_id(self, player_lookup: str) -> str:
        """
        Resolve or create universal player ID for a single player.
        
        Args:
            player_lookup: Normalized player name for lookup
            
        Returns:
            Universal player ID (e.g., "kjmartin_001")
        """
        self.stats['lookups_performed'] += 1
        
        # Check cache first
        if player_lookup in self._id_cache:
            self.stats['cache_hits'] += 1
            return self._id_cache[player_lookup]
        
        # Query for existing universal ID
        existing_id = self._lookup_existing_universal_id(player_lookup)
        if existing_id:
            self._id_cache[player_lookup] = existing_id
            return existing_id
        
        # Check for alias resolution
        canonical_lookup = self._resolve_via_alias(player_lookup)
        if canonical_lookup and canonical_lookup != player_lookup:
            canonical_id = self._lookup_existing_universal_id(canonical_lookup)
            if canonical_id:
                self.stats['alias_resolutions'] += 1
                self._id_cache[player_lookup] = canonical_id
                return canonical_id
        
        # Create new universal ID
        new_id = self._create_new_universal_id(player_lookup)
        self.stats['new_ids_created'] += 1
        self._id_cache[player_lookup] = new_id
        
        return new_id
    
    def bulk_resolve_or_create_universal_ids(self, player_lookups: List[str]) -> Dict[str, str]:
        """
        Resolve or create universal player IDs for a batch of players.
        
        Optimized for batch processing - uses fewer database queries than individual lookups.
        
        Args:
            player_lookups: List of normalized player names
            
        Returns:
            Dict mapping player_lookup -> universal_player_id
            
        Example:
            players = ['lebronjames', 'stephencurry', 'kevindurant']
            uid_map = resolver.bulk_resolve_or_create_universal_ids(players)
            # Returns: {'lebronjames': 'lebronjames_001', ...}
        """
        if not player_lookups:
            return {}
        
        logger.info(f"Bulk resolving universal IDs for {len(player_lookups)} players")
        bulk_start = datetime.now()
        
        # Step 1: Get all existing universal IDs in one query
        existing_mappings = self._bulk_lookup_existing_universal_ids(player_lookups)
        
        # Step 2: Find players without existing IDs
        missing_players = [lookup for lookup in player_lookups if lookup not in existing_mappings]
        
        # Step 3: Attempt alias resolution for missing players
        if missing_players:
            alias_mappings = self._bulk_resolve_via_aliases(missing_players)
            existing_mappings.update(alias_mappings)
            
            # Update missing players list
            missing_players = [lookup for lookup in missing_players if lookup not in existing_mappings]
        
        # Step 4: Create new universal IDs for remaining missing players
        if missing_players:
            new_mappings = self._bulk_create_new_universal_ids(missing_players)
            existing_mappings.update(new_mappings)
        
        # Update cache and stats
        self._id_cache.update(existing_mappings)
        self.stats['lookups_performed'] += len(player_lookups)
        self.stats['new_ids_created'] += len(missing_players) if missing_players else 0
        
        bulk_duration = (datetime.now() - bulk_start).total_seconds()
        logger.info(f"Bulk resolution completed in {bulk_duration:.3f}s: "
                   f"{len(existing_mappings)} IDs resolved, {len(missing_players) if missing_players else 0} created")
        
        return existing_mappings
    
    def _bulk_lookup_existing_universal_ids(self, player_lookups: List[str]) -> Dict[str, str]:
        """
        Get existing universal IDs for a batch of players in one query.
        
        IMPROVED: Uses UNNEST with array parameter instead of individual parameters
        for better performance and no parameter count limits.
        """
        if not player_lookups:
            return {}
        
        # Use UNNEST for efficient batch lookup
        query = f"""
        SELECT DISTINCT 
            player_lookup,
            universal_player_id
        FROM `{self.registry_table}`
        WHERE player_lookup IN UNNEST(@player_lookups)
        AND universal_player_id IS NOT NULL
        """
        
        # Single array parameter - more efficient than individual parameters
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            if results.empty:
                return {}
            
            # Convert to dict mapping
            mappings = dict(zip(results['player_lookup'], results['universal_player_id']))
            logger.info(f"Found {len(mappings)} existing universal IDs in registry")
            
            return mappings
            
        except Exception as e:
            logger.error(f"Error in bulk lookup of existing universal IDs: {e}")
            return {}
    
    def _bulk_resolve_via_aliases(self, player_lookups: List[str]) -> Dict[str, str]:
        """
        Attempt to resolve universal IDs via alias table for batch of players.
        
        IMPROVED: Uses UNNEST with array parameter instead of individual parameters.
        """
        if not player_lookups:
            return {}
        
        # Use UNNEST for efficient alias lookup
        query = f"""
        SELECT DISTINCT
            a.alias_lookup,
            r.universal_player_id
        FROM `{self.alias_table}` a
        JOIN `{self.registry_table}` r 
        ON a.nba_canonical_lookup = r.player_lookup
        WHERE a.alias_lookup IN UNNEST(@player_lookups)
        AND a.is_active = TRUE
        AND r.universal_player_id IS NOT NULL
        """
        
        # Single array parameter
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            if results.empty:
                return {}
            
            # Convert to dict mapping
            mappings = dict(zip(results['alias_lookup'], results['universal_player_id']))
            
            if mappings:
                logger.info(f"Resolved {len(mappings)} players via alias system")
                self.stats['alias_resolutions'] += len(mappings)
            
            return mappings
            
        except Exception as e:
            logger.error(f"Error in bulk alias resolution: {e}")
            return {}
    
    def _bulk_create_new_universal_ids(self, player_lookups: List[str]) -> Dict[str, str]:
        """
        Create new universal IDs for a batch of players.
        
        IMPROVED: Checks for collisions and increments sequence number if needed.
        """
        if not player_lookups:
            return {}
        
        logger.info(f"Creating {len(player_lookups)} new universal player IDs")
        
        # Generate new universal IDs with collision detection
        new_mappings = {}
        for player_lookup in player_lookups:
            new_id = self._generate_universal_id(player_lookup)
            new_mappings[player_lookup] = new_id
        
        return new_mappings
    
    def _lookup_existing_universal_id(self, player_lookup: str) -> Optional[str]:
        """Look up existing universal ID for a single player."""
        query = f"""
        SELECT DISTINCT universal_player_id
        FROM `{self.registry_table}`
        WHERE player_lookup = @player_lookup
        AND universal_player_id IS NOT NULL
        LIMIT 1
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            if not results.empty:
                return results.iloc[0]['universal_player_id']
            
            return None
            
        except Exception as e:
            logger.warning(f"Error looking up existing universal ID for {player_lookup}: {e}")
            return None
    
    def _resolve_via_alias(self, player_lookup: str) -> Optional[str]:
        """Attempt to resolve player via alias table."""
        query = f"""
        SELECT nba_canonical_lookup
        FROM `{self.alias_table}`
        WHERE alias_lookup = @alias_lookup
        AND is_active = TRUE
        LIMIT 1
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("alias_lookup", "STRING", player_lookup)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            if not results.empty:
                return results.iloc[0]['nba_canonical_lookup']
            
            return None
            
        except Exception as e:
            logger.warning(f"Error resolving alias for {player_lookup}: {e}")
            return None
    
    def _create_new_universal_id(self, player_lookup: str) -> str:
        """
        Create a new universal ID for a player.
        
        IMPROVED: Checks for existing IDs to avoid collisions and increments sequence.
        """
        return self._generate_universal_id(player_lookup)
    
    def _generate_universal_id(self, player_lookup: str) -> str:
        """
        Generate a universal player ID from player lookup.
        
        Format: {normalized_name}_{sequence_number}
        Example: kjmartin_001
        
        IMPROVED: Checks for collisions and finds next available sequence number.
        """
        # Clean the player lookup for ID generation
        base_id = player_lookup.lower().replace(' ', '').replace('.', '').replace("'", '')
        
        # Check for existing IDs with this base to find next sequence number
        existing_ids = self._find_existing_ids_with_base(base_id)
        
        if not existing_ids:
            # No collision, use 001
            return f"{base_id}_001"
        
        # Find highest sequence number
        max_sequence = 0
        for existing_id in existing_ids:
            try:
                # Extract sequence number from ID like "kjmartin_002"
                parts = existing_id.split('_')
                if len(parts) == 2:
                    sequence = int(parts[1])
                    max_sequence = max(max_sequence, sequence)
            except (ValueError, IndexError):
                continue
        
        # Use next sequence number
        next_sequence = max_sequence + 1
        new_id = f"{base_id}_{next_sequence:03d}"
        
        logger.info(f"Generated new universal ID with collision detection: {new_id}")
        return new_id
    
    def _find_existing_ids_with_base(self, base_id: str) -> List[str]:
        """
        Find all existing universal IDs that start with the given base.
        
        Used for collision detection when generating new IDs.
        """
        query = f"""
        SELECT DISTINCT universal_player_id
        FROM `{self.registry_table}`
        WHERE universal_player_id LIKE @pattern
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("pattern", "STRING", f"{base_id}_%")
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            if results.empty:
                return []
            
            return results['universal_player_id'].tolist()
            
        except Exception as e:
            logger.warning(f"Error checking for ID collisions: {e}")
            # Safe fallback - return empty list, will use _001
            return []
    
    def get_canonical_player_name(self, player_lookup: str) -> str:
        """
        Get the canonical player name for tracking purposes.
        
        Args:
            player_lookup: Normalized player name
            
        Returns:
            Canonical player name (currently same as player_lookup)
        """
        # For now, just return the player_lookup
        # In a more sophisticated system, this might resolve to the "official" name
        return player_lookup
    
    def lookup_universal_id(self, player_lookup: str) -> str:
        """
        Look up universal ID for existing players only.
        
        Raises exception if player not found (for use in analytics processors).
        
        Args:
            player_lookup: Normalized player name
            
        Returns:
            Universal player ID
            
        Raises:
            ValueError: If player not found in registry
        """
        universal_id = self._lookup_existing_universal_id(player_lookup)
        
        if not universal_id:
            raise ValueError(f"No universal ID found for player: {player_lookup}")
        
        return universal_id
    
    def lookup_universal_id_safe(self, player_lookup: str) -> Optional[str]:
        """
        Look up universal ID for existing players only.
        
        Returns None if player not found (safe version).
        
        Args:
            player_lookup: Normalized player name
            
        Returns:
            Universal player ID or None if not found
        """
        return self._lookup_existing_universal_id(player_lookup)
    
    def bulk_lookup_universal_ids(self, player_lookups: List[str]) -> Dict[str, Optional[str]]:
        """
        Look up universal IDs for existing players only (bulk version).
        
        Returns mapping with None values for players not found.
        
        Args:
            player_lookups: List of normalized player names
            
        Returns:
            Dict mapping player_lookup -> universal_player_id (or None if not found)
        """
        existing_mappings = self._bulk_lookup_existing_universal_ids(player_lookups)
        
        # Create result dict with None for missing players
        result = {}
        for lookup in player_lookups:
            result[lookup] = existing_mappings.get(lookup)
        
        return result
    
    def get_resolution_stats(self) -> Dict:
        """
        Get statistics about universal ID resolution performance.
        
        Returns:
            Dict containing resolution statistics
        """
        total_lookups = max(self.stats['lookups_performed'], 1)
        
        return {
            'total_lookups': self.stats['lookups_performed'],
            'new_ids_created': self.stats['new_ids_created'],
            'cache_hits': self.stats['cache_hits'],
            'alias_resolutions': self.stats['alias_resolutions'],
            'cache_hit_rate': (self.stats['cache_hits'] / total_lookups) * 100,
            'cache_size': len(self._id_cache)
        }
    
    def clear_cache(self):
        """Clear the in-memory cache."""
        cache_size = len(self._id_cache)
        self._id_cache.clear()
        self._cache_populated = False
        logger.info(f"Universal ID cache cleared ({cache_size} entries removed)")
    
    def reset_stats(self):
        """Reset performance statistics."""
        self.stats = {
            'lookups_performed': 0,
            'new_ids_created': 0,
            'cache_hits': 0,
            'alias_resolutions': 0
        }
        logger.info("Resolution statistics reset")