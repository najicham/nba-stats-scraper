#!/usr/bin/env python3
"""
MLB Player ID Resolver

Creates and resolves universal player IDs for consistent player identification
across all MLB data sources.

Features:
- Universal ID format: {normalized_name}_{sequence} (e.g., loganwebb_001)
- Separate tracking for pitchers vs batters
- Collision detection for players with same normalized name
- Bulk operations for batch processing

Usage:
    from shared.utils.mlb_player_registry import MLBPlayerIDResolver

    resolver = MLBPlayerIDResolver(bq_client, project_id)

    # Single player
    uid = resolver.resolve_or_create('loganwebb', player_type='pitcher')

    # Batch processing
    pitchers = ['loganwebb', 'gerritcole', 'corbinburnes']
    uid_map = resolver.bulk_resolve_or_create(pitchers, player_type='pitcher')

Created: 2026-01-13
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Set

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class MLBPlayerIDResolver:
    """
    Resolves and creates universal player IDs for MLB players.

    Handles name variations and ensures consistent identification across
    multiple data sources (Statcast, Odds API, BDL, etc.).
    """

    def __init__(
        self,
        bq_client: bigquery.Client,
        project_id: str,
        test_mode: bool = False
    ):
        """
        Initialize MLB player ID resolver.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
            test_mode: Use test tables (for development)
        """
        self.bq_client = bq_client
        self.project_id = project_id

        # Table names
        if test_mode:
            self.registry_table = f"{project_id}.mlb_reference.mlb_players_registry_test"
            self.alias_table = f"{project_id}.mlb_reference.mlb_player_aliases_test"
        else:
            self.registry_table = f"{project_id}.mlb_reference.mlb_players_registry"
            self.alias_table = f"{project_id}.mlb_reference.mlb_player_aliases"

        # Performance tracking
        self.stats = {
            'lookups_performed': 0,
            'new_ids_created': 0,
            'cache_hits': 0,
            'alias_resolutions': 0
        }

        # In-memory cache
        self._id_cache: Dict[str, str] = {}  # player_lookup -> universal_id

        logger.info(f"Initialized MLBPlayerIDResolver (test_mode={test_mode})")

    def resolve_or_create(
        self,
        player_lookup: str,
        player_type: str = None,
        player_name: str = None,
        team_abbr: str = None
    ) -> str:
        """
        Resolve or create universal player ID.

        Args:
            player_lookup: Normalized player name for lookup
            player_type: 'pitcher' or 'batter' (optional but recommended)
            player_name: Display name (optional)
            team_abbr: Team abbreviation (optional)

        Returns:
            Universal player ID (e.g., "loganwebb_001")
        """
        self.stats['lookups_performed'] += 1

        # Check cache first
        cache_key = f"{player_lookup}_{player_type or 'any'}"
        if cache_key in self._id_cache:
            self.stats['cache_hits'] += 1
            return self._id_cache[cache_key]

        # Query for existing universal ID
        existing_id = self._lookup_existing_id(player_lookup, player_type)
        if existing_id:
            self._id_cache[cache_key] = existing_id
            return existing_id

        # Check alias table
        canonical_lookup = self._resolve_via_alias(player_lookup)
        if canonical_lookup and canonical_lookup != player_lookup:
            canonical_id = self._lookup_existing_id(canonical_lookup, player_type)
            if canonical_id:
                self.stats['alias_resolutions'] += 1
                self._id_cache[cache_key] = canonical_id
                return canonical_id

        # Create new universal ID
        new_id = self._create_new_id(
            player_lookup=player_lookup,
            player_type=player_type,
            player_name=player_name,
            team_abbr=team_abbr
        )
        self.stats['new_ids_created'] += 1
        self._id_cache[cache_key] = new_id

        return new_id

    def bulk_resolve_or_create(
        self,
        player_lookups: List[str],
        player_type: str = None
    ) -> Dict[str, str]:
        """
        Resolve or create universal IDs for a batch of players.

        Args:
            player_lookups: List of normalized player names
            player_type: 'pitcher' or 'batter' (optional)

        Returns:
            Dict mapping player_lookup -> universal_player_id
        """
        if not player_lookups:
            return {}

        logger.info(f"Bulk resolving {len(player_lookups)} MLB player IDs")
        start_time = datetime.now()

        # Step 1: Get existing IDs
        existing = self._bulk_lookup_existing_ids(player_lookups, player_type)

        # Step 2: Find missing players
        missing = [p for p in player_lookups if p not in existing]

        # Step 3: Try alias resolution for missing
        if missing:
            alias_resolved = self._bulk_resolve_aliases(missing)
            existing.update(alias_resolved)
            missing = [p for p in missing if p not in existing]

        # Step 4: Create new IDs for remaining
        if missing:
            new_ids = self._bulk_create_new_ids(missing, player_type)
            existing.update(new_ids)

        # Update cache
        for lookup, uid in existing.items():
            cache_key = f"{lookup}_{player_type or 'any'}"
            self._id_cache[cache_key] = uid

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Bulk resolution complete in {duration:.3f}s")

        return existing

    def _lookup_existing_id(
        self,
        player_lookup: str,
        player_type: str = None
    ) -> Optional[str]:
        """Look up existing universal ID for a player."""
        type_filter = ""
        if player_type:
            type_filter = f"AND player_type = '{player_type.upper()}'"

        query = f"""
        SELECT universal_player_id
        FROM `{self.registry_table}`
        WHERE player_lookup = @player_lookup
        {type_filter}
        AND universal_player_id IS NOT NULL
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
            logger.warning(f"Error looking up ID for {player_lookup}: {e}")
            return None

    def _bulk_lookup_existing_ids(
        self,
        player_lookups: List[str],
        player_type: str = None
    ) -> Dict[str, str]:
        """Bulk lookup existing universal IDs."""
        if not player_lookups:
            return {}

        type_filter = ""
        if player_type:
            type_filter = f"AND player_type = '{player_type.upper()}'"

        query = f"""
        SELECT DISTINCT player_lookup, universal_player_id
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
            logger.error(f"Error in bulk lookup: {e}")
            return {}

    def _resolve_via_alias(self, player_lookup: str) -> Optional[str]:
        """Resolve player via alias table."""
        query = f"""
        SELECT canonical_lookup
        FROM `{self.alias_table}`
        WHERE alias_lookup = @alias_lookup
        AND is_active = TRUE
        LIMIT 1
        """

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("alias_lookup", "STRING", player_lookup)
        ])

        try:
            results = list(self.bq_client.query(query, job_config=job_config).result())
            if results:
                return results[0].canonical_lookup
            return None
        except Exception as e:
            logger.debug(f"Alias lookup failed for {player_lookup}: {e}")
            return None

    def _bulk_resolve_aliases(self, player_lookups: List[str]) -> Dict[str, str]:
        """Bulk resolve via alias table."""
        if not player_lookups:
            return {}

        query = f"""
        SELECT a.alias_lookup, r.universal_player_id
        FROM `{self.alias_table}` a
        JOIN `{self.registry_table}` r ON a.canonical_lookup = r.player_lookup
        WHERE a.alias_lookup IN UNNEST(@player_lookups)
        AND a.is_active = TRUE
        AND r.universal_player_id IS NOT NULL
        """

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups)
        ])

        try:
            results = self.bq_client.query(query, job_config=job_config).result()
            mappings = {row.alias_lookup: row.universal_player_id for row in results}
            if mappings:
                self.stats['alias_resolutions'] += len(mappings)
            return mappings
        except Exception as e:
            logger.debug(f"Bulk alias resolution failed: {e}")
            return {}

    def _create_new_id(
        self,
        player_lookup: str,
        player_type: str = None,
        player_name: str = None,
        team_abbr: str = None
    ) -> str:
        """Create a new universal ID and insert into registry."""
        # Generate unique ID
        universal_id = self._generate_universal_id(player_lookup)

        # Insert into registry
        row = {
            'player_lookup': player_lookup,
            'universal_player_id': universal_id,
            'player_full_name': player_name or player_lookup,
            'player_type': (player_type or 'UNKNOWN').upper(),
            'team_abbr': team_abbr or '',
            'season_year': datetime.now().year,
            'source_priority': 'auto_created',
            'created_at': datetime.utcnow().isoformat(),
            'processed_at': datetime.utcnow().isoformat(),
        }

        try:
            errors = self.bq_client.insert_rows_json(self.registry_table, [row])
            if errors:
                logger.warning(f"Error inserting new player: {errors}")
        except Exception as e:
            logger.warning(f"Failed to insert new player {player_lookup}: {e}")

        return universal_id

    def _bulk_create_new_ids(
        self,
        player_lookups: List[str],
        player_type: str = None
    ) -> Dict[str, str]:
        """Bulk create new universal IDs."""
        if not player_lookups:
            return {}

        mappings = {}
        rows = []
        now = datetime.utcnow().isoformat()

        for player_lookup in player_lookups:
            universal_id = self._generate_universal_id(player_lookup)
            mappings[player_lookup] = universal_id

            rows.append({
                'player_lookup': player_lookup,
                'universal_player_id': universal_id,
                'player_full_name': player_lookup,
                'player_type': (player_type or 'UNKNOWN').upper(),
                'team_abbr': '',
                'season_year': datetime.now().year,
                'source_priority': 'auto_created',
                'created_at': now,
                'processed_at': now,
            })

        try:
            errors = self.bq_client.insert_rows_json(self.registry_table, rows)
            if errors:
                logger.warning(f"Errors inserting {len(errors)} players")
        except Exception as e:
            logger.error(f"Failed bulk insert: {e}")

        self.stats['new_ids_created'] += len(mappings)
        return mappings

    def _generate_universal_id(self, player_lookup: str) -> str:
        """Generate unique universal ID with collision detection."""
        # Clean for ID generation
        base_id = player_lookup.lower().replace(' ', '').replace('.', '').replace("'", '')

        # Find existing IDs with this base
        existing = self._find_existing_ids_with_base(base_id)

        if not existing:
            return f"{base_id}_001"

        # Find highest sequence
        max_seq = 0
        for uid in existing:
            try:
                parts = uid.split('_')
                if len(parts) >= 2:
                    seq = int(parts[-1])
                    max_seq = max(max_seq, seq)
            except (ValueError, IndexError):
                continue

        return f"{base_id}_{max_seq + 1:03d}"

    def _find_existing_ids_with_base(self, base_id: str) -> List[str]:
        """Find all existing IDs starting with base."""
        query = f"""
        SELECT DISTINCT universal_player_id
        FROM `{self.registry_table}`
        WHERE universal_player_id LIKE @pattern
        """

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("pattern", "STRING", f"{base_id}_%")
        ])

        try:
            results = list(self.bq_client.query(query, job_config=job_config).result())
            return [r.universal_player_id for r in results]
        except Exception as e:
            logger.debug(f"Error finding existing IDs: {e}")
            return []

    def get_stats(self) -> Dict:
        """Get resolution statistics."""
        return {
            **self.stats,
            'cache_size': len(self._id_cache)
        }

    def clear_cache(self):
        """Clear in-memory cache."""
        self._id_cache.clear()
        logger.info("MLB player ID cache cleared")
