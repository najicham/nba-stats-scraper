#!/usr/bin/env python3
"""
File: shared/utils/player_name_resolver.py

Centralized NBA Player Name Resolution System

This module provides the core name resolution functionality for consistent 
player identification across all data sources (NBA.com, Ball Don't Lie API, 
ESPN, etc.). It integrates with BigQuery-based name resolution tables.

Key Features:
- Production alias resolution using BigQuery lookup tables
- Player registry validation
- Unresolved name queue management
- Team abbreviation mapping integration
- Comprehensive logging and confidence scoring
"""

import logging
import os
import uuid
from datetime import datetime, date
from typing import Dict, List, Tuple, Optional, Union
from collections import defaultdict
import pandas as pd
from google.cloud import bigquery

# Import shared utilities
from .player_name_normalizer import normalize_name_for_lookup, extract_suffix
from .nba_team_mapper import get_nba_tricode, get_nba_tricode_fuzzy

logger = logging.getLogger(__name__)


class PlayerNameResolver:
    """
    Centralized NBA player name resolution system.
    
    Provides consistent player name resolution across all data sources using
    BigQuery-backed alias tables, player registry, and manual review queue.
    """
    
    def __init__(self, project_id: str = None):
        """Initialize the name resolver with BigQuery client."""
        self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        
        # Team mapping for Basketball Reference compatibility
        self.team_mapping = {
            'BKN': 'BRK',  # Brooklyn Nets
            'PHX': 'PHO',  # Phoenix Suns  
            'CHA': 'CHO',  # Charlotte Hornets
        }
        
        # Cache for performance
        self._alias_cache = {}
        self._registry_cache = {}
        self._cache_expiry = None
        
        logger.info(f"Initialized PlayerNameResolver for project: {self.project_id}")
    
    def resolve_to_nba_name(self, input_name: str) -> str:
        """
        Convert any player name to NBA.com canonical form.
        
        This is the primary production resolution function. It checks the alias
        table for known mappings and returns the canonical NBA name.
        
        Args:
            input_name: Raw player name from any source
            
        Returns:
            NBA.com canonical name or original name if no resolution found
            
        Examples:
            >>> resolver.resolve_to_nba_name("Kenyon Martin Jr.")
            'KJ Martin'
            >>> resolver.resolve_to_nba_name("Unknown Player")
            'Unknown Player'
        """
        if not input_name:
            return input_name
        
        # Normalize input using shared normalizer
        normalized_input = normalize_name_for_lookup(input_name)
        
        try:
            # Check alias table for known mappings
            query = """
                SELECT nba_canonical_display 
                FROM `{project}.nba_reference.player_aliases` 
                WHERE alias_lookup = @normalized_name AND is_active = TRUE
                LIMIT 1
            """.format(project=self.project_id)
            
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("normalized_name", "STRING", normalized_input)
                ]
            )
            
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            if not results.empty:
                resolved_name = results.iloc[0]['nba_canonical_display']
                logger.debug(f"Resolved '{input_name}' -> '{resolved_name}' via alias table")
                return resolved_name
            
            # No alias found - return original name
            logger.debug(f"No alias found for '{input_name}', returning original")
            return input_name
            
        except Exception as e:
            logger.error(f"Error resolving name '{input_name}': {e}")
            return input_name
    
    def is_valid_nba_player(self, player_name: str, season: str = None, team: str = None) -> bool:
        """
        Check if player name exists in NBA players registry.
        
        Args:
            player_name: Player name to validate (will be normalized)
            season: Optional season filter ("2023-24")
            team: Optional team filter ("LAL")
            
        Returns:
            Boolean indicating if player is in registry
        """
        if not player_name:
            return False
        
        normalized = normalize_name_for_lookup(player_name)
        
        try:
            query = """
                SELECT COUNT(*) as count
                FROM `{project}.nba_reference.nba_players_registry` 
                WHERE player_lookup = @normalized_name
            """.format(project=self.project_id)
            
            query_params = [
                bigquery.ScalarQueryParameter("normalized_name", "STRING", normalized)
            ]
            
            if season:
                query += " AND season = @season"
                query_params.append(bigquery.ScalarQueryParameter("season", "STRING", season))
            
            if team:
                query += " AND team_abbr = @team"
                query_params.append(bigquery.ScalarQueryParameter("team", "STRING", team))
            
            job_config = bigquery.QueryJobConfig(query_parameters=query_params)
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            return results.iloc[0]['count'] > 0
            
        except Exception as e:
            logger.error(f"Error validating player '{player_name}': {e}")
            return False
    
    def handle_player_name(self, input_name: str, source: str, game_context: Dict) -> Optional[str]:
        """
        Complete name resolution with fallback to manual review queue.
        
        This is the main entry point for processors that need comprehensive
        name resolution with automatic fallback handling.
        
        Args:
            input_name: Raw player name
            source: Data source ('bdl', 'espn', etc.)
            game_context: Dict with season, team, game_date, game_id
            
        Returns:
            Resolved NBA name or None if needs manual review
        """
        if not input_name:
            return None
        
        # Step 1: Try alias resolution
        resolved_name = self.resolve_to_nba_name(input_name)
        
        # Step 2: Validate against registry
        season = game_context.get('season')
        team = game_context.get('team')
        
        if self.is_valid_nba_player(resolved_name, season, team):
            return resolved_name
        
        # Step 3: No resolution found - add to manual review queue
        self.add_to_unresolved_queue(
            source=source,
            original_name=input_name,
            game_context=game_context
        )
        
        logger.warning(f"Player '{input_name}' from {source} needs manual review")
        return None  # Signals manual review needed
    
    def add_to_unresolved_queue(self, source: str, original_name: str, game_context: Dict):
        """Add unresolved player name to manual review queue."""
        if not original_name:
            return
        
        normalized_lookup = normalize_name_for_lookup(original_name)
        current_date = date.today()
        
        try:
            # Check if already exists
            check_query = """
                SELECT normalized_lookup, occurrences, example_games
                FROM `{project}.nba_reference.unresolved_player_names`
                WHERE source = @source AND normalized_lookup = @normalized_lookup
            """.format(project=self.project_id)
            
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("source", "STRING", source),
                    bigquery.ScalarQueryParameter("normalized_lookup", "STRING", normalized_lookup)
                ]
            )
            
            existing = self.bq_client.query(check_query, job_config=job_config).to_dataframe()
            
            if not existing.empty:
                # Update existing record
                current_games = existing.iloc[0]['example_games'] or []
                game_id = game_context.get('game_id')
                
                if game_id and game_id not in current_games:
                    current_games.append(game_id)
                    current_games = current_games[:5]  # Keep only 5 examples
                
                update_query = """
                    UPDATE `{project}.nba_reference.unresolved_player_names`
                    SET 
                        occurrences = occurrences + 1,
                        last_seen_date = @current_date,
                        example_games = @example_games,
                        updated_date = @current_date
                    WHERE source = @source AND normalized_lookup = @normalized_lookup
                """.format(project=self.project_id)
                
                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("source", "STRING", source),
                        bigquery.ScalarQueryParameter("normalized_lookup", "STRING", normalized_lookup),
                        bigquery.ScalarQueryParameter("current_date", "DATE", current_date),
                        bigquery.ArrayQueryParameter("example_games", "STRING", current_games)
                    ]
                )
                
                self.bq_client.query(update_query, job_config=job_config).result()
                logger.debug(f"Updated unresolved name: {original_name} (now {existing.iloc[0]['occurrences'] + 1} occurrences)")
                
            else:
                # Insert new record
                insert_data = [{
                    'source': source,
                    'original_name': original_name,
                    'normalized_lookup': normalized_lookup,
                    'first_seen_date': current_date.isoformat(),
                    'last_seen_date': current_date.isoformat(),
                    'team_abbr': game_context.get('team'),
                    'season': game_context.get('season'),
                    'occurrences': 1,
                    'example_games': [game_context.get('game_id')] if game_context.get('game_id') else [],
                    'status': 'pending',
                    'created_date': current_date.isoformat(),
                    'updated_date': current_date.isoformat()
                }]
                
                table_id = f"{self.project_id}.nba_reference.unresolved_player_names"
                errors = self.bq_client.insert_rows_json(table_id, insert_data)
                
                if errors:
                    logger.error(f"Failed to insert unresolved name: {errors}")
                else:
                    logger.info(f"Added new unresolved name: {original_name} from {source}")
                    
        except Exception as e:
            logger.error(f"Error adding to unresolved queue: {e}")
    
    def create_alias_mapping(self, alias_name: str, canonical_name: str, alias_type: str, 
                           alias_source: str, notes: str = None, created_by: str = 'manual') -> bool:
        """
        Create a new alias mapping in the production alias table.
        
        Args:
            alias_name: The alias/variation name
            canonical_name: The NBA.com canonical name
            alias_type: Type of alias ('suffix_difference', 'nickname', 'source_variation')
            alias_source: Source of the alias ('bdl', 'espn', etc.)
            notes: Optional notes about the mapping
            created_by: Who created this mapping
            
        Returns:
            Boolean indicating success
        """
        try:
            alias_lookup = normalize_name_for_lookup(alias_name)
            canonical_lookup = normalize_name_for_lookup(canonical_name)
            current_date = date.today()
            
            insert_data = [{
                'alias_lookup': alias_lookup,
                'nba_canonical_lookup': canonical_lookup,
                'alias_display': alias_name,
                'nba_canonical_display': canonical_name,
                'alias_type': alias_type,
                'alias_source': alias_source,
                'is_active': True,
                'notes': notes,
                'created_by': created_by,
                'created_date': current_date.isoformat(),
                'updated_at': datetime.now().isoformat()
            }]
            
            table_id = f"{self.project_id}.nba_reference.player_aliases"
            errors = self.bq_client.insert_rows_json(table_id, insert_data)
            
            if errors:
                logger.error(f"Failed to create alias mapping: {errors}")
                return False
            else:
                logger.info(f"Created alias mapping: '{alias_name}' -> '{canonical_name}'")
                return True
                
        except Exception as e:
            logger.error(f"Error creating alias mapping: {e}")
            return False
    
    def get_unresolved_names(self, limit: int = 50, source: str = None) -> pd.DataFrame:
        """
        Get pending unresolved names for manual review.
        
        Args:
            limit: Maximum number of records to return
            source: Optional source filter
            
        Returns:
            DataFrame with unresolved names prioritized by occurrence count
        """
        try:
            query = """
                SELECT 
                    source,
                    original_name,
                    normalized_lookup,
                    team_abbr,
                    season,
                    occurrences,
                    first_seen_date,
                    last_seen_date,
                    example_games
                FROM `{project}.nba_reference.unresolved_player_names`
                WHERE status = 'pending'
            """.format(project=self.project_id)
            
            query_params = []
            
            if source:
                query += " AND source = @source"
                query_params.append(bigquery.ScalarQueryParameter("source", "STRING", source))
            
            query += " ORDER BY occurrences DESC, first_seen_date ASC LIMIT @limit"
            query_params.append(bigquery.ScalarQueryParameter("limit", "INT64", limit))
            
            job_config = bigquery.QueryJobConfig(query_parameters=query_params)
            return self.bq_client.query(query, job_config=job_config).to_dataframe()
            
        except Exception as e:
            logger.error(f"Error getting unresolved names: {e}")
            return pd.DataFrame()
    
    def mark_unresolved_as_resolved(self, source: str, original_name: str, 
                                  resolved_to: str, resolution_type: str, 
                                  notes: str = None, reviewed_by: str = 'manual') -> bool:
        """
        Mark an unresolved name as resolved and optionally create alias mapping.
        
        Args:
            source: Source of the unresolved name
            original_name: Original unresolved name
            resolved_to: What it resolves to
            resolution_type: 'create_alias', 'add_to_registry', 'typo', 'ignored'
            notes: Optional resolution notes
            reviewed_by: Who resolved it
            
        Returns:
            Boolean indicating success
        """
        try:
            normalized_lookup = normalize_name_for_lookup(original_name)
            current_date = date.today()
            
            update_query = """
                UPDATE `{project}.nba_reference.unresolved_player_names`
                SET 
                    status = 'resolved',
                    resolution_type = @resolution_type,
                    resolved_to_name = @resolved_to,
                    notes = @notes,
                    reviewed_by = @reviewed_by,
                    reviewed_date = @current_date,
                    updated_date = @current_date
                WHERE source = @source AND normalized_lookup = @normalized_lookup
            """.format(project=self.project_id)
            
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("source", "STRING", source),
                    bigquery.ScalarQueryParameter("normalized_lookup", "STRING", normalized_lookup),
                    bigquery.ScalarQueryParameter("resolution_type", "STRING", resolution_type),
                    bigquery.ScalarQueryParameter("resolved_to", "STRING", resolved_to),
                    bigquery.ScalarQueryParameter("notes", "STRING", notes),
                    bigquery.ScalarQueryParameter("reviewed_by", "STRING", reviewed_by),
                    bigquery.ScalarQueryParameter("current_date", "DATE", current_date)
                ]
            )
            
            result = self.bq_client.query(update_query, job_config=job_config).result()
            
            if result.num_dml_affected_rows > 0:
                logger.info(f"Marked '{original_name}' as resolved to '{resolved_to}'")
                return True
            else:
                logger.warning(f"No records updated for '{original_name}' from {source}")
                return False
                
        except Exception as e:
            logger.error(f"Error marking as resolved: {e}")
            return False
    
    def add_player_to_registry(self, player_name: str, team_abbr: str, season: str,
                             games_played: int = 0, jersey_number: int = None,
                             position: str = None, created_by: str = 'manual') -> bool:
        """
        Add a new player to the NBA players registry.
        
        Args:
            player_name: Official NBA player name
            team_abbr: Team abbreviation
            season: Season string ("2023-24")
            games_played: Number of games played
            jersey_number: Jersey number
            position: Position
            created_by: Who added the player
            
        Returns:
            Boolean indicating success
        """
        try:
            player_lookup = normalize_name_for_lookup(player_name)
            current_date = date.today()
            
            insert_data = [{
                'player_name': player_name,
                'player_lookup': player_lookup,
                'team_abbr': team_abbr,
                'season': season,
                'games_played': games_played,
                'jersey_number': jersey_number,
                'position': position,
                'source_priority': 'manual_entry',
                'confidence_score': 1.0,
                'created_date': current_date.isoformat(),
                'updated_date': current_date.isoformat(),
                'created_by': created_by
            }]
            
            table_id = f"{self.project_id}.nba_reference.nba_players_registry"
            errors = self.bq_client.insert_rows_json(table_id, insert_data)
            
            if errors:
                logger.error(f"Failed to add player to registry: {errors}")
                return False
            else:
                logger.info(f"Added player to registry: {player_name} ({team_abbr}, {season})")
                return True
                
        except Exception as e:
            logger.error(f"Error adding player to registry: {e}")
            return False
    
    # Legacy compatibility methods from existing gamebook processor
    def normalize_name(self, name: str) -> str:
        """Alias for normalize_name_for_lookup for backward compatibility."""
        return normalize_name_for_lookup(name)
    
    def handle_suffix_names(self, name: str) -> str:
        """Alias for extract_suffix()[0] for backward compatibility."""
        base_name, _ = extract_suffix(name)
        return base_name
    
    def map_team_to_br_code(self, team_abbr: str) -> str:
        """Map NBA.com team abbreviations to Basketball Reference codes."""
        if not team_abbr:
            return ""
        return self.team_mapping.get(team_abbr, team_abbr)


# Singleton instance for easy import and use
_default_resolver = None

def get_default_resolver() -> PlayerNameResolver:
    """Get the default singleton resolver instance."""
    global _default_resolver
    if _default_resolver is None:
        _default_resolver = PlayerNameResolver()
    return _default_resolver


# Convenience functions for common operations
def resolve_player_name(input_name: str) -> str:
    """Convenience function for simple name resolution."""
    return get_default_resolver().resolve_to_nba_name(input_name)


def validate_player(player_name: str, season: str = None, team: str = None) -> bool:
    """Convenience function for player validation."""
    return get_default_resolver().is_valid_nba_player(player_name, season, team)


def handle_player_resolution(input_name: str, source: str, game_context: Dict) -> Optional[str]:
    """Convenience function for complete player resolution with fallback."""
    return get_default_resolver().handle_player_name(input_name, source, game_context)