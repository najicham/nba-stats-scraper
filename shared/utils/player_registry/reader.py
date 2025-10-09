#!/usr/bin/env python3
"""
File: shared/utils/player_registry/reader.py

Read-only access to NBA Players Registry.

Provides safe, cached access to player registry data for downstream processors.
Supports batch operations, context tracking, and unresolved player management.
"""

import os
import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
import time

from google.cloud import bigquery

from .exceptions import (
    PlayerNotFoundError,
    MultipleRecordsError,
    AmbiguousNameError,
    RegistryConnectionError
)

try:
    from shared.utils.notification_system import (
        NotificationRouter,
        NotificationLevel,
        NotificationType
    )
    NOTIFICATIONS_AVAILABLE = True
except ImportError:
    NOTIFICATIONS_AVAILABLE = False
    logging.warning("Notification system not available")


logger = logging.getLogger(__name__)


class RegistryReader:
    """
    Read-only access to NBA Players Registry.
    
    Provides efficient, cached access to player identification and metadata.
    Tracks unresolved players for manual review.
    
    Example:
        registry = RegistryReader(
            source_name='player_game_summary',
            cache_ttl_seconds=300
        )
        registry.set_default_context(season='2024-25')
        
        uid = registry.get_universal_id('lebronjames')
        player = registry.get_player('lebronjames', season='2024-25')
        
        registry.flush_unresolved_players()
    """
    
    # Maximum batch size for bulk operations
    MAX_BATCH_SIZE = 100
    
    def __init__(self, 
                 project_id: str = None,
                 bq_client: bigquery.Client = None,
                 source_name: str = 'unknown',
                 cache_ttl_seconds: int = 0,
                 auto_flush: bool = False,
                 test_mode: bool = False):
        """
        Initialize registry reader.
        
        Args:
            project_id: GCP project ID (defaults to environment variable)
            bq_client: Optional BigQuery client (creates one if not provided)
            source_name: Processor name for unresolved player tracking
            cache_ttl_seconds: Cache time-to-live in seconds (0 = no caching)
            auto_flush: Auto-flush unresolved players on destruction
            test_mode: Use test tables (for development)
        """
        # BigQuery setup
        if bq_client is not None:
            self.bq_client = bq_client
            self.project_id = project_id or bq_client.project
        else:
            self.bq_client = bigquery.Client(project=project_id)
            self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
        # Table names
        if test_mode:
            timestamp_suffix = "FIXED2"
            self.registry_table = f'{self.project_id}.nba_reference.nba_players_registry_test_{timestamp_suffix}'
            self.unresolved_table = f'{self.project_id}.nba_reference.unresolved_player_names_test_{timestamp_suffix}'
        else:
            self.registry_table = f'{self.project_id}.nba_reference.nba_players_registry'
            self.unresolved_table = f'{self.project_id}.nba_reference.unresolved_player_names'
        
        # Configuration
        self.source_name = source_name
        self.cache_ttl_seconds = cache_ttl_seconds
        self.auto_flush = auto_flush
        
        # Cache storage: {cache_key: (data, timestamp)}
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        
        # Default context for unresolved player tracking
        self._default_context: Dict[str, Any] = {}
        
        # Unresolved player queue: {player_lookup: context_list}
        self._unresolved_queue: Dict[str, List[Dict]] = defaultdict(list)
        
        logger.info(
            f"Initialized RegistryReader for source '{source_name}' "
            f"(cache_ttl={cache_ttl_seconds}s, auto_flush={auto_flush})"
        )
    
    # =========================================================================
    # CONTEXT MANAGEMENT
    # =========================================================================
    
    def set_default_context(self, **context):
        """
        Set default context for unresolved player tracking.
        
        Context is merged with per-call context when logging unresolved players.
        
        Args:
            **context: Context fields (season, team_abbr, etc.)
            
        Example:
            registry.set_default_context(season='2024-25', team_abbr='LAL')
        """
        self._default_context.update(context)
        logger.debug(f"Updated default context: {self._default_context}")
    
    def _merge_context(self, call_context: Dict = None) -> Dict:
        """Merge default context with call-specific context."""
        merged = self._default_context.copy()
        if call_context:
            merged.update(call_context)
        return merged
    
    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================
    
    def _get_from_cache(self, cache_key: str) -> Optional[Any]:
        """Get value from cache if valid."""
        if self.cache_ttl_seconds == 0:
            return None
        
        if cache_key not in self._cache:
            self._cache_misses += 1
            return None
        
        data, timestamp = self._cache[cache_key]
        age = time.time() - timestamp
        
        if age > self.cache_ttl_seconds:
            # Expired
            del self._cache[cache_key]
            self._cache_misses += 1
            return None
        
        self._cache_hits += 1
        return data
    
    def _put_in_cache(self, cache_key: str, data: Any):
        """Put value in cache."""
        if self.cache_ttl_seconds > 0:
            self._cache[cache_key] = (data, time.time())
    
    def clear_cache(self):
        """Clear entire cache."""
        self._cache.clear()
        logger.info("Cache cleared")
    
    def clear_cache_for_player(self, player_lookup: str):
        """Clear cache entries for specific player."""
        keys_to_delete = [k for k in self._cache.keys() if player_lookup in k]
        for key in keys_to_delete:
            del self._cache[key]
        logger.debug(f"Cleared {len(keys_to_delete)} cache entries for {player_lookup}")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        total = self._cache_hits + self._cache_misses
        hit_rate = self._cache_hits / total if total > 0 else 0
        
        return {
            'hits': self._cache_hits,
            'misses': self._cache_misses,
            'hit_rate': hit_rate,
            'cache_size': len(self._cache),
            'ttl_seconds': self.cache_ttl_seconds
        }
    
    # =========================================================================
    # CORE REGISTRY QUERIES
    # =========================================================================
    
    def get_universal_id(self, 
                        player_lookup: str,
                        required: bool = True,
                        context: Dict = None) -> Optional[str]:
        """
        Get universal player ID for a player lookup name.
        
        Args:
            player_lookup: Normalized player name (e.g., 'lebronjames')
            required: If True, raise exception on not found. If False, return None.
            context: Additional context for unresolved tracking (merged with defaults)
            
        Returns:
            Universal player ID (e.g., 'lebronjames_001') or None if not found and not required
            
        Raises:
            PlayerNotFoundError: If player not found and required=True
            RegistryConnectionError: If BigQuery connection fails
            
        Example:
            # Strict mode (raises exception)
            uid = registry.get_universal_id('lebronjames')
            
            # Lenient mode (returns None)
            uid = registry.get_universal_id('unknownplayer', required=False)
            if uid is None:
                # Handle missing player
        """
        cache_key = f"uid:{player_lookup}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        query = f"""
        SELECT DISTINCT universal_player_id
        FROM `{self.registry_table}`
        WHERE player_lookup = @player_lookup
        LIMIT 1
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            if results.empty:
                # Player not found
                self._log_unresolved_player(player_lookup, context)
                
                if required:
                    raise PlayerNotFoundError(player_lookup)
                return None
            
            universal_id = results.iloc[0]['universal_player_id']
            self._put_in_cache(cache_key, universal_id)
            return universal_id
            
        except PlayerNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error querying universal ID for {player_lookup}: {e}")
            raise RegistryConnectionError(e)
    
    def get_player(self,
                  player_lookup: str,
                  season: str = None,
                  team_abbr: str = None,
                  required: bool = True,
                  context: Dict = None) -> Optional[Dict]:
        """
        Get complete player record.
        
        Args:
            player_lookup: Normalized player name
            season: Season filter (e.g., '2024-25'). If None, returns most recent.
            team_abbr: Team filter (for players on multiple teams in same season)
            required: If True, raise exception on not found
            context: Additional context for unresolved tracking
            
        Returns:
            Player record dictionary or None if not found and not required
            
        Raises:
            PlayerNotFoundError: If player not found and required=True
            MultipleRecordsError: If multiple teams and no team_abbr filter
            RegistryConnectionError: If BigQuery connection fails
            
        Example:
            # Most recent record
            player = registry.get_player('lebronjames')
            
            # Specific season
            player = registry.get_player('lebronjames', season='2024-25')
            
            # Traded player (need team filter)
            player = registry.get_player('jamesharden', season='2023-24', team_abbr='LAC')
        """
        cache_key = f"player:{player_lookup}:{season}:{team_abbr}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        query = f"""
        SELECT 
            universal_player_id,
            player_name,
            player_lookup,
            team_abbr,
            season,
            games_played,
            first_game_date,
            last_game_date,
            jersey_number,
            position,
            source_priority,
            confidence_score,
            last_processor,
            processed_at
        FROM `{self.registry_table}`
        WHERE player_lookup = @player_lookup
        """
        
        query_params = [
            bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup)
        ]
        
        if season:
            query += " AND season = @season"
            query_params.append(bigquery.ScalarQueryParameter("season", "STRING", season))
        
        if team_abbr:
            query += " AND team_abbr = @team_abbr"
            query_params.append(bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr))
        
        if not season:
            # Get most recent if no season specified
            query += " ORDER BY season DESC, processed_at DESC LIMIT 1"
        
        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            if results.empty:
                self._log_unresolved_player(player_lookup, context)
                if required:
                    raise PlayerNotFoundError(player_lookup)
                return None
            
            # Check for multiple teams in same season
            if len(results) > 1 and not team_abbr:
                teams = results['team_abbr'].unique().tolist()
                raise MultipleRecordsError(player_lookup, teams)
            
            # Convert to dict
            record = results.iloc[0].to_dict()
            
            # Convert timestamps/dates
            for key, value in record.items():
                if hasattr(value, 'to_pydatetime'):
                    record[key] = value.to_pydatetime()
                elif hasattr(value, 'date'):
                    record[key] = value.date()
            
            self._put_in_cache(cache_key, record)
            return record
            
        except (PlayerNotFoundError, MultipleRecordsError):
            raise
        except Exception as e:
            logger.error(f"Error querying player {player_lookup}: {e}")
            raise RegistryConnectionError(e)
    
    def get_current_team(self,
                        player_lookup: str,
                        season: str,
                        required: bool = True,
                        context: Dict = None) -> Optional[str]:
        """
        Get player's current team based on most recent activity.
        
        For players on multiple teams in same season, returns team with
        most recent activity (game or roster update).
        
        Args:
            player_lookup: Normalized player name
            season: Season string
            required: If True, raise exception on not found
            context: Additional context for unresolved tracking
            
        Returns:
            Team abbreviation or None if not found and not required
            
        Raises:
            PlayerNotFoundError: If player not found and required=True
            RegistryConnectionError: If BigQuery connection fails
        """
        cache_key = f"current_team:{player_lookup}:{season}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        query = f"""
        SELECT team_abbr
        FROM `{self.registry_table}`
        WHERE player_lookup = @player_lookup
          AND season = @season
        ORDER BY 
            GREATEST(
                COALESCE(last_gamebook_activity_date, DATE '1900-01-01'),
                COALESCE(last_roster_activity_date, DATE '1900-01-01')
            ) DESC
        LIMIT 1
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
            bigquery.ScalarQueryParameter("season", "STRING", season)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            if results.empty:
                self._log_unresolved_player(player_lookup, context)
                if required:
                    raise PlayerNotFoundError(player_lookup)
                return None
            
            team_abbr = results.iloc[0]['team_abbr']
            self._put_in_cache(cache_key, team_abbr)
            return team_abbr
            
        except PlayerNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error querying current team for {player_lookup}: {e}")
            raise RegistryConnectionError(e)
    
    def player_exists(self,
                     player_lookup: str,
                     season: str = None) -> bool:
        """
        Check if player exists in registry.
        
        Args:
            player_lookup: Normalized player name
            season: Optional season filter
            
        Returns:
            True if player exists, False otherwise
        """
        try:
            self.get_universal_id(player_lookup, required=False)
            return True
        except Exception:
            return False
    
    # =========================================================================
    # BATCH OPERATIONS
    # =========================================================================
    
    def get_universal_ids_batch(self,
                                player_lookups: List[str],
                                context: Dict = None) -> Dict[str, str]:
        """
        Get universal IDs for multiple players in one query.
        
        Large batches are automatically chunked to MAX_BATCH_SIZE.
        
        Args:
            player_lookups: List of normalized player names
            context: Additional context for unresolved tracking
            
        Returns:
            Dictionary mapping player_lookup → universal_player_id
            Only includes players found in registry (missing players logged as unresolved)
            
        Example:
            players = ['lebronjames', 'stephencurry', 'kevindurant']
            ids = registry.get_universal_ids_batch(players)
            # Returns: {'lebronjames': 'lebronjames_001', ...}
            
            # Check for missing
            for player in players:
                if player not in ids:
                    print(f"Missing: {player}")
        """
        if not player_lookups:
            return {}
        
        # Check cache first
        result = {}
        uncached_lookups = []
        
        for lookup in player_lookups:
            cache_key = f"uid:{lookup}"
            cached = self._get_from_cache(cache_key)
            if cached is not None:
                result[lookup] = cached
            else:
                uncached_lookups.append(lookup)
        
        if not uncached_lookups:
            return result
        
        # Chunk if needed
        chunks = [uncached_lookups[i:i + self.MAX_BATCH_SIZE] 
                 for i in range(0, len(uncached_lookups), self.MAX_BATCH_SIZE)]
        
        for chunk in chunks:
            query = f"""
            SELECT DISTINCT 
                player_lookup,
                universal_player_id
            FROM `{self.registry_table}`
            WHERE player_lookup IN UNNEST(@player_lookups)
            """
            
            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", chunk)
            ])
            
            try:
                results = self.bq_client.query(query, job_config=job_config).to_dataframe()
                
                # Add found players to result
                for _, row in results.iterrows():
                    lookup = row['player_lookup']
                    uid = row['universal_player_id']
                    result[lookup] = uid
                    self._put_in_cache(f"uid:{lookup}", uid)
                
                # Log missing players as unresolved
                found_lookups = set(results['player_lookup'].tolist())
                missing_lookups = set(chunk) - found_lookups
                for lookup in missing_lookups:
                    self._log_unresolved_player(lookup, context)
                
            except Exception as e:
                logger.error(f"Error in batch universal ID query: {e}")
                raise RegistryConnectionError(e)
        
        return result
    
    def get_players_batch(self,
                         player_lookups: List[str],
                         season: str,
                         context: Dict = None) -> Dict[str, Dict]:
        """
        Get complete records for multiple players.
        
        Args:
            player_lookups: List of normalized player names
            season: Season filter
            context: Additional context for unresolved tracking
            
        Returns:
            Dictionary mapping player_lookup → player record
            Only includes players found in registry
        """
        if not player_lookups:
            return {}
        
        # Chunk if needed
        chunks = [player_lookups[i:i + self.MAX_BATCH_SIZE] 
                 for i in range(0, len(player_lookups), self.MAX_BATCH_SIZE)]
        
        result = {}
        
        for chunk in chunks:
            query = f"""
            SELECT 
                universal_player_id,
                player_name,
                player_lookup,
                team_abbr,
                season,
                games_played,
                first_game_date,
                last_game_date,
                jersey_number,
                position,
                source_priority,
                confidence_score,
                last_processor,
                processed_at
            FROM `{self.registry_table}`
            WHERE player_lookup IN UNNEST(@player_lookups)
              AND season = @season
            """
            
            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", chunk),
                bigquery.ScalarQueryParameter("season", "STRING", season)
            ])
            
            try:
                results = self.bq_client.query(query, job_config=job_config).to_dataframe()
                
                for _, row in results.iterrows():
                    lookup = row['player_lookup']
                    record = row.to_dict()
                    
                    # Convert timestamps/dates
                    for key, value in record.items():
                        if hasattr(value, 'to_pydatetime'):
                            record[key] = value.to_pydatetime()
                        elif hasattr(value, 'date'):
                            record[key] = value.date()
                    
                    result[lookup] = record
                
                # Log missing players
                found_lookups = set(results['player_lookup'].tolist())
                missing_lookups = set(chunk) - found_lookups
                for lookup in missing_lookups:
                    self._log_unresolved_player(lookup, context)
                
            except Exception as e:
                logger.error(f"Error in batch player query: {e}")
                raise RegistryConnectionError(e)
        
        return result
    
    # =========================================================================
    # TEAM QUERIES
    # =========================================================================
    
    def get_team_roster(self, team_abbr: str, season: str) -> List[Dict]:
        """
        Get all players on a team for a season.
        
        Args:
            team_abbr: Team abbreviation (e.g., 'LAL')
            season: Season string
            
        Returns:
            List of player records
        """
        cache_key = f"roster:{team_abbr}:{season}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        query = f"""
        SELECT 
            universal_player_id,
            player_name,
            player_lookup,
            team_abbr,
            season,
            games_played,
            jersey_number,
            position
        FROM `{self.registry_table}`
        WHERE team_abbr = @team_abbr
          AND season = @season
        ORDER BY player_name
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
            bigquery.ScalarQueryParameter("season", "STRING", season)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            roster = results.to_dict('records')
            self._put_in_cache(cache_key, roster)
            return roster
            
        except Exception as e:
            logger.error(f"Error querying team roster for {team_abbr}: {e}")
            raise RegistryConnectionError(e)
    
    def get_active_teams(self, season: str) -> List[str]:
        """
        Get all teams with players in registry for a season.
        
        Args:
            season: Season string
            
        Returns:
            List of team abbreviations
        """
        cache_key = f"active_teams:{season}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        query = f"""
        SELECT DISTINCT team_abbr
        FROM `{self.registry_table}`
        WHERE season = @season
        ORDER BY team_abbr
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season", "STRING", season)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            teams = results['team_abbr'].tolist()
            self._put_in_cache(cache_key, teams)
            return teams
            
        except Exception as e:
            logger.error(f"Error querying active teams: {e}")
            raise RegistryConnectionError(e)
    
    # =========================================================================
    # SEARCH AND LOOKUP
    # =========================================================================
    
    def search_players(self,
                      name_pattern: str,
                      season: str = None,
                      limit: int = 10) -> List[Dict]:
        """
        Search for players by name pattern.
        
        Args:
            name_pattern: Search pattern (case-insensitive)
            season: Optional season filter
            limit: Maximum results
            
        Returns:
            List of matching player records
        """
        query = f"""
        SELECT DISTINCT
            universal_player_id,
            player_name,
            player_lookup,
            team_abbr,
            season,
            games_played
        FROM `{self.registry_table}`
        WHERE LOWER(player_name) LIKE @pattern
        """
        
        query_params = [
            bigquery.ScalarQueryParameter("pattern", "STRING", f"%{name_pattern.lower()}%")
        ]
        
        if season:
            query += " AND season = @season"
            query_params.append(bigquery.ScalarQueryParameter("season", "STRING", season))
        
        query += f" ORDER BY player_name LIMIT {limit}"
        
        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            return results.to_dict('records')
            
        except Exception as e:
            logger.error(f"Error searching players with pattern '{name_pattern}': {e}")
            raise RegistryConnectionError(e)
    
    def lookup_by_display_name(self,
                               display_name: str,
                               season: str = None) -> str:
        """
        Convert display name to player_lookup.
        
        Args:
            display_name: Display name (e.g., "LeBron James")
            season: Optional season filter
            
        Returns:
            Normalized player_lookup
            
        Raises:
            PlayerNotFoundError: If no match found
            AmbiguousNameError: If multiple matches
        """
        results = self.search_players(display_name, season=season, limit=5)
        
        # Exact match on player_name
        exact_matches = [r for r in results if r['player_name'].lower() == display_name.lower()]
        
        if len(exact_matches) == 1:
            return exact_matches[0]['player_lookup']
        elif len(exact_matches) > 1:
            names = [r['player_name'] for r in exact_matches]
            raise AmbiguousNameError(display_name, names)
        elif len(results) == 1:
            return results[0]['player_lookup']
        elif len(results) > 1:
            names = [r['player_name'] for r in results]
            raise AmbiguousNameError(display_name, names)
        else:
            raise PlayerNotFoundError(display_name)
    
    # =========================================================================
    # VALIDATION
    # =========================================================================
    
    def validate_player_team(self,
                            player_lookup: str,
                            team_abbr: str,
                            season: str) -> bool:
        """
        Check if player was on specific team in season.
        
        Args:
            player_lookup: Normalized player name
            team_abbr: Team abbreviation
            season: Season string
            
        Returns:
            True if player was on team in season
        """
        query = f"""
        SELECT COUNT(*) as count
        FROM `{self.registry_table}`
        WHERE player_lookup = @player_lookup
          AND team_abbr = @team_abbr
          AND season = @season
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
            bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
            bigquery.ScalarQueryParameter("season", "STRING", season)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            return results.iloc[0]['count'] > 0
            
        except Exception as e:
            logger.error(f"Error validating player-team: {e}")
            return False
    
    # =========================================================================
    # UNRESOLVED PLAYER TRACKING
    # =========================================================================
    
    def _log_unresolved_player(self, player_lookup: str, context: Dict = None):
        """Add player to internal unresolved queue."""
        merged_context = self._merge_context(context)
        self._unresolved_queue[player_lookup].append({
            'timestamp': datetime.now(),
            **merged_context
        })
        logger.debug(f"Logged unresolved player: {player_lookup}")
    
    def flush_unresolved_players(self):
        """
        Write accumulated unresolved players to BigQuery.
        
        Automatically deduplicates and aggregates multiple occurrences
        of the same player within the run.
        """
        if not self._unresolved_queue:
            logger.debug("No unresolved players to flush")
            return
        
        records = []
        current_datetime = datetime.now()
        current_date = current_datetime.date()
        
        for player_lookup, contexts in self._unresolved_queue.items():
            # Aggregate contexts
            occurrences = len(contexts)
            
            # Get unique game IDs if present
            game_ids = []
            for ctx in contexts:
                game_id = ctx.get('game_id')
                if game_id and game_id not in game_ids:
                    game_ids.append(game_id)
            
            # Get most common team/season
            teams = [ctx.get('team_abbr') for ctx in contexts if ctx.get('team_abbr')]
            team_abbr = max(set(teams), key=teams.count) if teams else None
            
            seasons = [ctx.get('season') for ctx in contexts if ctx.get('season')]
            season = max(set(seasons), key=seasons.count) if seasons else None
            
            record = {
                'source': self.source_name,
                'original_name': player_lookup,  # We don't have display name
                'normalized_lookup': player_lookup,
                'first_seen_date': current_date,
                'last_seen_date': current_date,
                'team_abbr': team_abbr,
                'season': season,
                'occurrences': occurrences,
                'example_games': game_ids[:10],  # Limit to 10 examples
                'status': 'pending',
                'resolution_type': None,
                'resolved_to_name': None,
                'notes': f"Player not found in registry during {self.source_name} processing",
                'reviewed_by': None,
                'reviewed_at': None,
                'created_at': current_datetime,
                'processed_at': current_datetime
            }
            records.append(record)
        
        # Write to BigQuery
        try:
            table_id = self.unresolved_table
            errors = self.bq_client.insert_rows_json(table_id, records)
            
            if errors:
                logger.error(f"Errors writing unresolved players: {errors}")
            else:
                logger.info(f"Flushed {len(records)} unresolved players to BigQuery")
            
            # Send notification if above threshold
            threshold = int(os.environ.get('EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD', '50'))
            if len(records) > threshold and NOTIFICATIONS_AVAILABLE:
                try:
                    router = NotificationRouter()
                    router.send_notification(
                        level=NotificationLevel.WARNING,
                        notification_type=NotificationType.UNRESOLVED_PLAYERS,
                        title=f"High Unresolved Player Count - {self.source_name}",
                        message=f"{len(records)} unresolved players detected",
                        details={
                            'source': self.source_name,
                            'count': len(records),
                            'threshold': threshold,
                            'players': list(self._unresolved_queue.keys())[:20]
                        },
                        processor_name=self.source_name
                    )
                except Exception as e:
                    logger.warning(f"Failed to send notification: {e}")
            
            # Clear queue after successful flush
            self._unresolved_queue.clear()
            
        except Exception as e:
            logger.error(f"Failed to flush unresolved players: {e}")
            # Don't raise - this is non-critical
    
    # =========================================================================
    # CONTEXT MANAGER SUPPORT
    # =========================================================================
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - auto-flush if configured."""
        if self.auto_flush:
            self.flush_unresolved_players()
        return False
    
    def __del__(self):
        """Destructor - warn if unflushed data."""
        if self._unresolved_queue and not self.auto_flush:
            logger.warning(
                f"RegistryReader destroyed with {len(self._unresolved_queue)} "
                f"unflushed unresolved players. Call flush_unresolved_players() "
                f"or use auto_flush=True."
            )