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

# Import notification system for infrastructure failures
from .notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Import AI resolution cache for cached decision lookup
from .player_registry.resolution_cache import ResolutionCache

logger = logging.getLogger(__name__)


class PlayerNameResolver:
    """
    Centralized NBA player name resolution system.
    
    Provides consistent player name resolution across all data sources using
    BigQuery-backed alias tables, player registry, and manual review queue.
    """
    
    def __init__(self, project_id: str = None):
        """Initialize the name resolver with BigQuery client."""
        from shared.config.gcp_config import get_project_id
        self.project_id = project_id or get_project_id()
        
        try:
            self.bq_client = bigquery.Client(project=self.project_id)
        except Exception as e:
            logger.error(f"Failed to initialize BigQuery client for PlayerNameResolver: {e}", exc_info=True)
            try:
                notify_error(
                    title="Player Name Resolver: BigQuery Initialization Failed",
                    message="Unable to initialize BigQuery client for name resolution",
                    details={
                        'component': 'PlayerNameResolver',
                        'project_id': self.project_id,
                        'error_type': type(e).__name__,
                        'error': str(e),
                        'impact': 'Player name resolution will fail across all processors'
                    },
                    processor_name="Player Name Resolver"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
        
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

        # Track consecutive infrastructure failures
        self._consecutive_failures = 0
        self._failure_threshold = 5

        # Initialize AI resolution cache for cached decision lookup
        # This allows using prior AI decisions without making new API calls
        try:
            self._resolution_cache = ResolutionCache(project_id=self.project_id)
            self._use_resolution_cache = True
        except Exception as e:
            logger.warning(f"Failed to initialize ResolutionCache, cache lookup disabled: {e}")
            self._resolution_cache = None
            self._use_resolution_cache = False

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
            
            # Reset failure counter on success
            self._consecutive_failures = 0
            
            if not results.empty:
                resolved_name = results.iloc[0]['nba_canonical_display']
                logger.debug(f"Resolved '{input_name}' -> '{resolved_name}' via alias table")
                return resolved_name
            
            # No alias found - return original name (this is normal, not an error)
            logger.debug(f"No alias found for '{input_name}', returning original")
            return input_name
            
        except Exception as e:
            logger.error(f"Error resolving name '{input_name}': {e}", exc_info=True)
            
            # Track consecutive failures for infrastructure issues
            self._consecutive_failures += 1
            
            # Only notify on repeated infrastructure failures
            if self._consecutive_failures >= self._failure_threshold:
                try:
                    notify_error(
                        title="Player Name Resolver: Alias Table Query Failures",
                        message=f"Alias table queries failing repeatedly ({self._consecutive_failures} consecutive failures)",
                        details={
                            'component': 'PlayerNameResolver',
                            'operation': 'resolve_to_nba_name',
                            'consecutive_failures': self._consecutive_failures,
                            'error_type': type(e).__name__,
                            'error': str(e),
                            'impact': 'Player name resolution degraded across all processors'
                        },
                        processor_name="Player Name Resolver"
                    )
                    # Reset counter after notifying
                    self._consecutive_failures = 0
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            return input_name

    def resolve_names_batch(self, input_names: List[str], batch_size: int = 50) -> Dict[str, str]:
        """
        Convert multiple player names to NBA.com canonical form in batches.

        Week 1 P0-6: Batch resolution for performance (50x faster than sequential).
        Uses IN UNNEST query pattern to resolve multiple names in single query.

        Args:
            input_names: List of raw player names from any source
            batch_size: Number of names to process per query (default: 50)

        Returns:
            Dictionary mapping input_name → resolved_nba_name
            Returns original name if no resolution found

        Examples:
            >>> names = ["Kenyon Martin Jr.", "LeBron James", "Unknown Player"]
            >>> results = resolver.resolve_names_batch(names)
            >>> results["Kenyon Martin Jr."]
            'KJ Martin'
            >>> results["Unknown Player"]
            'Unknown Player'

        Performance:
            - Sequential: 50 names = 50 queries = 4-5 seconds
            - Batched: 50 names = 1 query = 0.5-1 second
            - Improvement: 5x faster, 50x fewer API calls
        """
        if not input_names:
            return {}

        # Remove duplicates while preserving order
        unique_names = list(dict.fromkeys(input_names))

        # Build mapping of normalized → original names
        normalized_to_original = {}
        for name in unique_names:
            if name:
                normalized = normalize_name_for_lookup(name)
                normalized_to_original[normalized] = name

        normalized_names = list(normalized_to_original.keys())

        # Result dictionary: original_name → resolved_name
        result = {name: name for name in unique_names}  # Default to original

        # Process in chunks of batch_size
        chunks = [normalized_names[i:i + batch_size]
                 for i in range(0, len(normalized_names), batch_size)]

        for chunk in chunks:
            try:
                # Batch query using IN UNNEST pattern (proven from reader.py)
                query = """
                    SELECT
                        alias_lookup,
                        nba_canonical_display
                    FROM `{project}.nba_reference.player_aliases`
                    WHERE alias_lookup IN UNNEST(@normalized_names)
                      AND is_active = TRUE
                """.format(project=self.project_id)

                job_config = bigquery.QueryJobConfig(query_parameters=[
                    bigquery.ArrayQueryParameter("normalized_names", "STRING", chunk)
                ])

                results = self.bq_client.query(query, job_config=job_config).to_dataframe()

                # Reset failure counter on success
                self._consecutive_failures = 0

                # Map resolved names back to original inputs
                for _, row in results.iterrows():
                    normalized = row['alias_lookup']
                    resolved = row['nba_canonical_display']
                    original = normalized_to_original[normalized]
                    result[original] = resolved
                    logger.debug(f"Batch resolved '{original}' -> '{resolved}'")

                resolved_count = len(results)
                logger.info(f"Batch resolved {resolved_count}/{len(chunk)} names in chunk")

            except Exception as e:
                logger.error(f"Error in batch name resolution: {e}", exc_info=True)

                # Track consecutive failures
                self._consecutive_failures += 1

                if self._consecutive_failures >= self._failure_threshold:
                    try:
                        notify_error(
                            title="Player Name Resolver: Batch Query Failures",
                            message=f"Batch queries failing repeatedly ({self._consecutive_failures} consecutive failures)",
                            details={
                                'component': 'PlayerNameResolver',
                                'operation': 'resolve_names_batch',
                                'batch_size': len(chunk),
                                'consecutive_failures': self._consecutive_failures,
                                'error_type': type(e).__name__,
                                'error': str(e),
                                'impact': 'Batch name resolution degraded, falling back to sequential'
                            },
                            processor_name="Player Name Resolver"
                        )
                        self._consecutive_failures = 0
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")

                # On error, chunk defaults to original names (already set)
                continue

        return result

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
            # Don't notify for individual validation failures - this is expected
            # Calling processor should handle this
            logger.error(f"Error validating player '{player_name}': {e}", exc_info=True)
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

        # Step 3: Check AI resolution cache for prior decisions
        # This uses cached AI decisions without making new API calls
        if self._use_resolution_cache and self._resolution_cache:
            normalized_lookup = normalize_name_for_lookup(input_name)
            try:
                cached_resolution = self._resolution_cache.get_cached(normalized_lookup)
                if cached_resolution:
                    if cached_resolution.resolution_type == 'MATCH':
                        # Found a cached MATCH decision - auto-create alias and return
                        canonical_lookup = cached_resolution.canonical_lookup
                        if canonical_lookup:
                            # Get the display name for the canonical player
                            canonical_display = self._get_canonical_display_name(canonical_lookup)
                            if canonical_display:
                                # Create alias for future fast lookups
                                alias_created = self.create_alias_mapping(
                                    alias_name=input_name,
                                    canonical_name=canonical_display,
                                    alias_type='ai_resolved',
                                    alias_source=source,
                                    notes=f"Auto-created from cached AI resolution: {cached_resolution.reasoning}",
                                    created_by='ai_cache_lookup'
                                )
                                if not alias_created:
                                    logger.warning(f"Failed to create alias for '{input_name}' -> '{canonical_display}', but returning cached resolution")
                                else:
                                    logger.info(f"Used cached AI resolution: '{input_name}' -> '{canonical_display}'")
                                # Return resolved name even if alias creation failed
                                # The cached AI decision is still valid
                                return canonical_display
                    elif cached_resolution.resolution_type == 'DATA_ERROR':
                        # Known bad name - don't re-add to unresolved queue
                        logger.debug(f"Cached DATA_ERROR for '{input_name}': {cached_resolution.reasoning}")
                        return None
                    # NEW_PLAYER and other types fall through to unresolved queue
                    # as they may need manual review or roster updates
            except Exception as e:
                logger.debug(f"Cache lookup failed for '{input_name}': {e}")
                # Continue to unresolved queue on cache lookup errors

        # Step 4: No resolution found - add to manual review queue
        # (This is normal operation, not an error - don't notify here)
        self.add_to_unresolved_queue(
            source=source,
            original_name=input_name,
            game_context=game_context
        )

        logger.warning(f"Player '{input_name}' from {source} needs manual review")
        return None  # Signals manual review needed
    
    def _get_canonical_display_name(self, canonical_lookup: str) -> Optional[str]:
        """
        Get the display name for a player from their normalized lookup.

        Args:
            canonical_lookup: Normalized player lookup (e.g., 'leblonjames')

        Returns:
            Display name (e.g., 'LeBron James') or None if not found
        """
        try:
            query = """
                SELECT player_name
                FROM `{project}.nba_reference.nba_players_registry`
                WHERE player_lookup = @lookup
                LIMIT 1
            """.format(project=self.project_id)

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("lookup", "STRING", canonical_lookup)
                ]
            )

            results = self.bq_client.query(query, job_config=job_config).to_dataframe()

            if not results.empty:
                return results.iloc[0]['player_name']

            return None

        except Exception as e:
            logger.debug(f"Error getting display name for '{canonical_lookup}': {e}")
            return None

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
                
                self.bq_client.query(update_query, job_config=job_config).result(timeout=60)
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

                # Get table reference for schema
                table_ref = self.bq_client.get_table(table_id)

                # Use batch loading instead of streaming inserts
                # This avoids the 90-minute streaming buffer that blocks DML operations
                # See: docs/05-development/guides/bigquery-best-practices.md
                job_config = bigquery.LoadJobConfig(
                    schema=table_ref.schema,
                    autodetect=False,
                    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                    ignore_unknown_values=True
                )

                load_job = self.bq_client.load_table_from_json(insert_data, table_id, job_config=job_config)
                load_job.result(timeout=60)

                errors = load_job.errors

                if errors:
                    logger.error(f"Failed to insert unresolved name: {errors}", exc_info=True)
                    # Only notify on insert failures - these indicate infrastructure issues
                    try:
                        notify_error(
                            title="Player Name Resolver: Unresolved Queue Insert Failed",
                            message=f"Unable to add unresolved player name to queue: {original_name}",
                            details={
                                'component': 'PlayerNameResolver',
                                'operation': 'add_to_unresolved_queue',
                                'player_name': original_name,
                                'source': source,
                                'errors': errors,
                                'impact': 'Manual review queue may be incomplete'
                            },
                            processor_name="Player Name Resolver"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                else:
                    logger.info(f"Added new unresolved name: {original_name} from {source}")
                    
        except Exception as e:
            logger.error(f"Error adding to unresolved queue: {e}", exc_info=True)
            # Notify on critical queue management failures
            try:
                notify_error(
                    title="Player Name Resolver: Unresolved Queue Error",
                    message=f"Failed to manage unresolved player queue: {str(e)}",
                    details={
                        'component': 'PlayerNameResolver',
                        'operation': 'add_to_unresolved_queue',
                        'player_name': original_name,
                        'source': source,
                        'error_type': type(e).__name__,
                        'error': str(e),
                        'impact': 'Manual review queue may be incomplete'
                    },
                    processor_name="Player Name Resolver"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
    
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

            # Get table reference for schema
            table_ref = self.bq_client.get_table(table_id)

            # Use batch loading instead of streaming inserts
            # This avoids the 90-minute streaming buffer that blocks DML operations
            # See: docs/05-development/guides/bigquery-best-practices.md
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(insert_data, table_id, job_config=job_config)
            load_job.result(timeout=60)

            errors = load_job.errors

            if errors:
                logger.error(f"Failed to create alias mapping: {errors}", exc_info=True)
                # Notify on alias creation failures - these affect future resolution
                try:
                    notify_error(
                        title="Player Name Resolver: Alias Creation Failed",
                        message=f"Unable to create alias mapping: {alias_name} → {canonical_name}",
                        details={
                            'component': 'PlayerNameResolver',
                            'operation': 'create_alias_mapping',
                            'alias_name': alias_name,
                            'canonical_name': canonical_name,
                            'alias_type': alias_type,
                            'errors': errors,
                            'impact': 'Name resolution will not work for this player'
                        },
                        processor_name="Player Name Resolver"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                return False
            else:
                logger.info(f"Created alias mapping: '{alias_name}' -> '{canonical_name}'")
                return True
                
        except Exception as e:
            logger.error(f"Error creating alias mapping: {e}", exc_info=True)
            try:
                notify_error(
                    title="Player Name Resolver: Alias Creation Error",
                    message=f"Error creating alias mapping: {str(e)}",
                    details={
                        'component': 'PlayerNameResolver',
                        'operation': 'create_alias_mapping',
                        'alias_name': alias_name,
                        'canonical_name': canonical_name,
                        'error_type': type(e).__name__,
                        'error': str(e)
                    },
                    processor_name="Player Name Resolver"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
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
            result_df = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            # Check if unresolved queue is getting large (potential issue)
            if not result_df.empty:
                total_unresolved = result_df['occurrences'].sum()
                if total_unresolved > 500:  # Threshold for warning
                    try:
                        notify_warning(
                            title="Player Name Resolver: Large Unresolved Queue",
                            message=f"Unresolved player name queue has {len(result_df)} entries with {total_unresolved} total occurrences",
                            details={
                                'component': 'PlayerNameResolver',
                                'operation': 'get_unresolved_names',
                                'unresolved_count': len(result_df),
                                'total_occurrences': int(total_unresolved),
                                'action': 'Review and resolve pending player names'
                            }
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
            
            return result_df
            
        except Exception as e:
            logger.error(f"Error getting unresolved names: {e}", exc_info=True)
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
            
            result = self.bq_client.query(update_query, job_config=job_config).result(timeout=60)
            
            if result.num_dml_affected_rows > 0:
                logger.info(f"Marked '{original_name}' as resolved to '{resolved_to}'")
                return True
            else:
                logger.warning(f"No records updated for '{original_name}' from {source}")
                return False
                
        except Exception as e:
            logger.error(f"Error marking as resolved: {e}", exc_info=True)
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

            # Get table reference for schema
            table_ref = self.bq_client.get_table(table_id)

            # Use batch loading instead of streaming inserts
            # This avoids the 90-minute streaming buffer that blocks DML operations
            # See: docs/05-development/guides/bigquery-best-practices.md
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(insert_data, table_id, job_config=job_config)
            load_job.result(timeout=60)

            errors = load_job.errors

            if errors:
                logger.error(f"Failed to add player to registry: {errors}", exc_info=True)
                return False
            else:
                logger.info(f"Added player to registry: {player_name} ({team_abbr}, {season})")
                return True
                
        except Exception as e:
            logger.error(f"Error adding player to registry: {e}", exc_info=True)
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