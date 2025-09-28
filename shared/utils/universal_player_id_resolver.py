#!/usr/bin/env python3
"""
File: shared/utils/universal_player_id_resolver.py

Universal Player ID Resolver - Enhanced with Bulk Operations

Provides universal player ID resolution for handling name changes and ensuring
consistent player identification across all analytics tables.

Enhanced with bulk operations for improved performance during batch processing.
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
    """
    
    def __init__(self, bq_client: bigquery.Client, project_id: str):
        self.bq_client = bq_client
        self.project_id = project_id
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
        """Get existing universal IDs for a batch of players in one query."""
        if not player_lookups:
            return {}
        
        # Create parameterized query for batch lookup
        placeholders = ','.join([f'@player_{i}' for i in range(len(player_lookups))])
        query = f"""
        SELECT DISTINCT 
            player_lookup,
            universal_player_id
        FROM `{self.registry_table}`
        WHERE player_lookup IN ({placeholders})
        AND universal_player_id IS NOT NULL
        """
        
        # Create query parameters
        query_params = [
            bigquery.ScalarQueryParameter(f"player_{i}", "STRING", lookup)
            for i, lookup in enumerate(player_lookups)
        ]
        
        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        
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
        """Attempt to resolve universal IDs via alias table for batch of players."""
        if not player_lookups:
            return {}
        
        # Create parameterized query for alias resolution
        placeholders = ','.join([f'@alias_{i}' for i in range(len(player_lookups))])
        query = f"""
        SELECT DISTINCT
            a.alias_lookup,
            r.universal_player_id
        FROM `{self.alias_table}` a
        JOIN `{self.registry_table}` r 
        ON a.nba_canonical_lookup = r.player_lookup
        WHERE a.alias_lookup IN ({placeholders})
        AND a.is_active = TRUE
        AND r.universal_player_id IS NOT NULL
        """
        
        # Create query parameters
        query_params = [
            bigquery.ScalarQueryParameter(f"alias_{i}", "STRING", lookup)
            for i, lookup in enumerate(player_lookups)
        ]
        
        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        
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
        """Create new universal IDs for a batch of players."""
        if not player_lookups:
            return {}
        
        logger.info(f"Creating {len(player_lookups)} new universal player IDs")
        
        # Generate new universal IDs
        new_mappings = {}
        for player_lookup in player_lookups:
            new_id = self._generate_universal_id(player_lookup)
            new_mappings[player_lookup] = new_id
        
        # Here you would typically insert these into a universal ID table
        # For now, we'll just return the mappings
        # In a full implementation, you might have a dedicated universal_player_ids table
        
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
        """Create a new universal ID for a player."""
        return self._generate_universal_id(player_lookup)
    
    def _generate_universal_id(self, player_lookup: str) -> str:
        """
        Generate a universal player ID from player lookup.
        
        Format: {normalized_name}_{sequence_number}
        Example: kjmartin_001
        """
        # Clean the player lookup for ID generation
        base_id = player_lookup.lower().replace(' ', '').replace('.', '').replace("'", '')
        
        # For now, use simple sequence numbering
        # In production, you might check for existing IDs to avoid collisions
        sequence = "001"
        
        return f"{base_id}_{sequence}"
    
    def get_canonical_player_name(self, player_lookup: str) -> str:
        """Get the canonical player name for tracking purposes."""
        # For now, just return the player_lookup
        # In a more sophisticated system, this might resolve to the "official" name
        return player_lookup
    
    def lookup_universal_id(self, player_lookup: str) -> str:
        """
        Look up universal ID for existing players only.
        
        Raises exception if player not found (for use in analytics processors).
        """
        universal_id = self._lookup_existing_universal_id(player_lookup)
        
        if not universal_id:
            raise ValueError(f"No universal ID found for player: {player_lookup}")
        
        return universal_id
    
    def lookup_universal_id_safe(self, player_lookup: str) -> Optional[str]:
        """
        Look up universal ID for existing players only.
        
        Returns None if player not found (safe version).
        """
        return self._lookup_existing_universal_id(player_lookup)
    
    def bulk_lookup_universal_ids(self, player_lookups: List[str]) -> Dict[str, Optional[str]]:
        """
        Look up universal IDs for existing players only (bulk version).
        
        Returns mapping with None values for players not found.
        """
        existing_mappings = self._bulk_lookup_existing_universal_ids(player_lookups)
        
        # Create result dict with None for missing players
        result = {}
        for lookup in player_lookups:
            result[lookup] = existing_mappings.get(lookup)
        
        return result
    
    def get_resolution_stats(self) -> Dict:
        """Get statistics about universal ID resolution performance."""
        return {
            'total_lookups': self.stats['lookups_performed'],
            'new_ids_created': self.stats['new_ids_created'],
            'cache_hits': self.stats['cache_hits'],
            'alias_resolutions': self.stats['alias_resolutions'],
            'cache_hit_rate': (self.stats['cache_hits'] / max(self.stats['lookups_performed'], 1)) * 100,
            'cache_size': len(self._id_cache)
        }
    
    def clear_cache(self):
        """Clear the in-memory cache."""
        self._id_cache.clear()
        self._cache_populated = False
        logger.info("Universal ID cache cleared")