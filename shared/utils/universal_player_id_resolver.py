#!/usr/bin/env python3
"""
File: shared/utils/universal_player_id_resolver.py

Universal Player ID Resolver Utility

Provides universal player ID resolution for different processor types:
- Registry Processor: Can create new universal IDs for new players
- Other Processors: Lookup existing universal IDs only

Usage Examples:
    # Registry processor (can create new IDs)
    resolver = UniversalPlayerIDResolver(bq_client, project_id)
    universal_id = resolver.resolve_or_create_universal_id("kjmartin")
    
    # Game processors (lookup existing only)
    universal_id = resolver.lookup_universal_id("kjmartin")  # Exception if not found
    universal_id = resolver.lookup_universal_id_safe("kjmartin")  # None if not found
"""

import logging
from typing import Dict, Optional
from collections import defaultdict
from google.cloud import bigquery
import pandas as pd

logger = logging.getLogger(__name__)


class PlayerNotFoundError(Exception):
    """Raised when a player's universal ID cannot be found in registry."""
    pass


class UniversalPlayerIDResolver:
    """
    Utility for resolving player_lookup to universal_player_id.
    
    Handles different use cases:
    - Registry processor: Can create new universal IDs
    - Other processors: Lookup existing universal IDs only
    """
    
    def __init__(self, bq_client: bigquery.Client, project_id: str, test_mode: bool = False):
        self.bq_client = bq_client
        self.project_id = project_id
        
        # Table names
        self.registry_table = 'nba_reference.nba_players_registry'
        self.aliases_table = 'nba_reference.player_aliases'
        
        # Caching for performance
        self.universal_id_cache = {}  # canonical_name -> universal_id
        self.canonical_cache = {}     # player_lookup -> canonical_name
        self.lookup_cache = {}        # player_lookup -> universal_id (for direct lookups)
        
        logger.info(f"Initialized UniversalPlayerIDResolver for project: {project_id}")
    
    # ====================
    # PUBLIC API METHODS
    # ====================
    
    def resolve_or_create_universal_id(self, player_lookup: str) -> str:
        """
        Get universal ID for player, creating if needed (for registry processor).
        
        Args:
            player_lookup: Normalized player name
            
        Returns:
            Universal player ID (existing or newly created)
            
        Used by: Registry processor for new player processing
        """
        logger.debug(f"Resolving/creating universal ID for: {player_lookup}")
        
        # Step 1: Resolve to canonical name
        canonical_name = self.get_canonical_player_name(player_lookup)
        
        # Step 2: Find existing universal ID
        universal_id = self.find_existing_universal_id(canonical_name)
        
        # Step 3: Generate new ID if needed
        if not universal_id:
            universal_id = self.generate_new_universal_id(canonical_name)
            logger.info(f"Generated new universal ID: {universal_id} for canonical player: {canonical_name}")
        else:
            logger.debug(f"Found existing universal ID: {universal_id} for canonical player: {canonical_name}")
        
        return universal_id
    
    def lookup_universal_id(self, player_lookup: str) -> str:
        """
        Lookup existing universal ID (for game processors).
        
        Args:
            player_lookup: Normalized player name
            
        Returns:
            Universal player ID
            
        Raises:
            PlayerNotFoundError: If player not found in registry
            
        Used by: Game processors that expect players to already exist
        """
        logger.debug(f"Looking up universal ID for: {player_lookup}")
        
        # Check direct lookup cache first
        if player_lookup in self.lookup_cache:
            return self.lookup_cache[player_lookup]
        
        # Query registry directly for this player_lookup
        query = f"""
        SELECT universal_player_id
        FROM `{self.project_id}.{self.registry_table}`
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
                universal_id = results.iloc[0]['universal_player_id']
                
                # Cache the result
                self.lookup_cache[player_lookup] = universal_id
                logger.debug(f"Found universal ID: {universal_id} for player: {player_lookup}")
                return universal_id
            else:
                # Player not found - check if it might be resolvable via aliases
                canonical_name = self.get_canonical_player_name(player_lookup)
                if canonical_name != player_lookup:
                    # Try looking up by canonical name
                    canonical_universal_id = self.find_existing_universal_id(canonical_name)
                    if canonical_universal_id:
                        self.lookup_cache[player_lookup] = canonical_universal_id
                        logger.debug(f"Found universal ID via canonical resolution: {canonical_universal_id}")
                        return canonical_universal_id
                
                # Still not found
                error_msg = f"Player not found in registry: {player_lookup}"
                logger.error(error_msg)
                raise PlayerNotFoundError(error_msg)
                
        except Exception as e:
            if isinstance(e, PlayerNotFoundError):
                raise e
            logger.error(f"Error looking up universal ID for {player_lookup}: {e}")
            raise PlayerNotFoundError(f"Database error looking up player: {player_lookup}")
    
    def lookup_universal_id_safe(self, player_lookup: str) -> Optional[str]:
        """
        Safe lookup that returns None instead of raising exception.
        
        Args:
            player_lookup: Normalized player name
            
        Returns:
            Universal player ID or None if not found
            
        Used by: Processors that can handle missing players gracefully
        """
        try:
            return self.lookup_universal_id(player_lookup)
        except PlayerNotFoundError:
            logger.warning(f"Player not found (safe lookup): {player_lookup}")
            return None
    
    def bulk_lookup_universal_ids(self, player_lookups: list) -> Dict[str, str]:
        """
        Efficient bulk lookup for multiple players.
        
        Args:
            player_lookups: List of normalized player names
            
        Returns:
            Dictionary mapping player_lookup -> universal_player_id
            
        Raises:
            PlayerNotFoundError: If any players not found
        """
        logger.debug(f"Bulk lookup for {len(player_lookups)} players")
        
        # Filter out cached results
        uncached_lookups = [p for p in player_lookups if p not in self.lookup_cache]
        result = {p: self.lookup_cache[p] for p in player_lookups if p in self.lookup_cache}
        
        if uncached_lookups:
            # Bulk query for uncached players
            placeholders = ', '.join([f"'{lookup}'" for lookup in uncached_lookups])
            query = f"""
            SELECT player_lookup, universal_player_id
            FROM `{self.project_id}.{self.registry_table}`
            WHERE player_lookup IN ({placeholders})
            AND universal_player_id IS NOT NULL
            """
            
            try:
                results = self.bq_client.query(query).to_dataframe()
                
                # Cache and add to result
                for _, row in results.iterrows():
                    player_lookup = row['player_lookup']
                    universal_id = row['universal_player_id']
                    self.lookup_cache[player_lookup] = universal_id
                    result[player_lookup] = universal_id
                
                # Check for missing players
                missing_players = set(uncached_lookups) - set(result.keys())
                if missing_players:
                    error_msg = f"Players not found in registry: {list(missing_players)}"
                    logger.error(error_msg)
                    raise PlayerNotFoundError(error_msg)
                    
            except Exception as e:
                if isinstance(e, PlayerNotFoundError):
                    raise e
                logger.error(f"Error in bulk lookup: {e}")
                raise PlayerNotFoundError(f"Database error in bulk lookup")
        
        logger.debug(f"Bulk lookup complete: {len(result)} players resolved")
        return result
    
    # ====================
    # INTERNAL METHODS
    # ====================
    
    def get_canonical_player_name(self, player_lookup: str) -> str:
        """Resolve player_lookup to canonical name using aliases."""
        # Check cache first
        if player_lookup in self.canonical_cache:
            return self.canonical_cache[player_lookup]
        
        # Query aliases table to resolve to canonical name
        alias_query = f"""
        SELECT nba_canonical_lookup
        FROM `{self.project_id}.{self.aliases_table}`
        WHERE alias_lookup = @player_lookup
        AND is_active = TRUE
        LIMIT 1
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup)
        ])
        
        try:
            results = self.bq_client.query(alias_query, job_config=job_config).to_dataframe()
            
            if not results.empty:
                canonical_name = results.iloc[0]['nba_canonical_lookup']
                logger.debug(f"Resolved {player_lookup} → {canonical_name} via aliases")
            else:
                # No alias found, player_lookup is canonical
                canonical_name = player_lookup
            
            # Cache the result
            self.canonical_cache[player_lookup] = canonical_name
            return canonical_name
            
        except Exception as e:
            logger.warning(f"Error resolving canonical name for {player_lookup}: {e}")
            return player_lookup  # Fallback to original name
    
    def find_existing_universal_id(self, canonical_name: str) -> Optional[str]:
        """Find existing universal_player_id for a canonical player."""
        # Check cache first
        if canonical_name in self.universal_id_cache:
            return self.universal_id_cache[canonical_name]
        
        # Query registry for existing universal ID
        lookup_query = f"""
        WITH canonical_lookups AS (
            -- Get all player_lookup values that resolve to this canonical name
            SELECT DISTINCT alias_lookup as player_lookup
            FROM `{self.project_id}.{self.aliases_table}`
            WHERE nba_canonical_lookup = @canonical_name
            AND is_active = TRUE
            
            UNION DISTINCT
            
            -- Include the canonical name itself
            SELECT @canonical_name as player_lookup
        )
        SELECT DISTINCT universal_player_id
        FROM `{self.project_id}.{self.registry_table}` r
        JOIN canonical_lookups cl ON r.player_lookup = cl.player_lookup
        WHERE r.universal_player_id IS NOT NULL
        LIMIT 1
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("canonical_name", "STRING", canonical_name)
        ])
        
        try:
            results = self.bq_client.query(lookup_query, job_config=job_config).to_dataframe()
            
            if not results.empty:
                universal_id = results.iloc[0]['universal_player_id']
                logger.debug(f"Found existing universal ID for {canonical_name}: {universal_id}")
                
                # Cache the result
                self.universal_id_cache[canonical_name] = universal_id
                return universal_id
            else:
                logger.debug(f"No existing universal ID found for canonical player: {canonical_name}")
                return None
                
        except Exception as e:
            logger.warning(f"Error finding universal ID for {canonical_name}: {e}")
            return None
    
    def generate_new_universal_id(self, canonical_name: str) -> str:
        """Generate a new universal player ID."""
        # Query to find the highest existing counter for this canonical name
        counter_query = f"""
        SELECT universal_player_id
        FROM `{self.project_id}.{self.registry_table}`
        WHERE universal_player_id LIKE @pattern
        ORDER BY universal_player_id DESC
        LIMIT 1
        """
        
        pattern = f"{canonical_name}_%"
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("pattern", "STRING", pattern)
        ])
        
        try:
            results = self.bq_client.query(counter_query, job_config=job_config).to_dataframe()
            
            if not results.empty:
                # Extract counter from existing ID like "lebronjames_001"
                existing_id = results.iloc[0]['universal_player_id']
                try:
                    counter = int(existing_id.split('_')[-1]) + 1
                except (ValueError, IndexError):
                    counter = 2  # Start from 2 if we can't parse existing
            else:
                counter = 1  # First ID for this player
            
            new_id = f"{canonical_name}_{counter:03d}"
            logger.info(f"Generated new universal ID: {new_id}")
            
            # Cache the new ID
            self.universal_id_cache[canonical_name] = new_id
            return new_id
            
        except Exception as e:
            logger.warning(f"Error generating universal ID for {canonical_name}: {e}")
            # Fallback to simple counter
            fallback_id = f"{canonical_name}_001"
            self.universal_id_cache[canonical_name] = fallback_id
            return fallback_id
    
    def clear_cache(self):
        """Clear all caches (useful for testing or after bulk operations)."""
        self.universal_id_cache.clear()
        self.canonical_cache.clear()
        self.lookup_cache.clear()
        logger.debug("Cleared all caches")
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics for monitoring."""
        return {
            'universal_id_cache_size': len(self.universal_id_cache),
            'canonical_cache_size': len(self.canonical_cache),
            'lookup_cache_size': len(self.lookup_cache)
        }


# Convenience function for one-off lookups
def lookup_universal_player_id(player_lookup: str, bq_client: bigquery.Client, project_id: str) -> str:
    """
    Simple function for one-off universal ID lookups.
    
    Args:
        player_lookup: Player name to lookup
        bq_client: BigQuery client
        project_id: GCP project ID
        
    Returns:
        Universal player ID
        
    Raises:
        PlayerNotFoundError: If player not found
    """
    resolver = UniversalPlayerIDResolver(bq_client, project_id)
    return resolver.lookup_universal_id(player_lookup)
