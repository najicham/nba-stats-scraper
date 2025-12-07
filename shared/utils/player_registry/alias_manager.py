#!/usr/bin/env python3
"""
Manage player aliases in BigQuery.

This module provides CRUD operations for the player_aliases table.
"""

import os
import logging
from typing import List, Dict, Optional
from google.cloud import bigquery
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class AliasRecord:
    """Represents a player alias."""
    alias_lookup: str
    nba_canonical_lookup: str
    alias_display: str
    nba_canonical_display: str
    alias_type: str  # 'suffix_difference', 'encoding', 'nickname', 'ai_resolved', etc.
    alias_source: str  # 'manual', 'ai_resolver', 'fuzzy_matcher', etc.
    confidence: float = 1.0
    ai_model: Optional[str] = None
    resolution_id: Optional[str] = None
    notes: Optional[str] = None


class AliasManager:
    """
    Create and manage player aliases.

    Example:
        manager = AliasManager()

        # Create single alias
        alias = AliasRecord(
            alias_lookup='marcusmorris',
            nba_canonical_lookup='marcusmorrissr',
            alias_display='Marcus Morris',
            nba_canonical_display='Marcus Morris Sr.',
            alias_type='suffix_difference',
            alias_source='ai_resolver',
            confidence=0.98
        )
        manager.create_alias(alias)

        # Bulk create
        manager.bulk_create_aliases([alias1, alias2, ...])
    """

    def __init__(self, project_id: str = None):
        """
        Initialize alias manager.

        Args:
            project_id: GCP project ID (defaults to GCP_PROJECT_ID env var)
        """
        self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.client = bigquery.Client(project=self.project_id)
        self.table_id = f"{self.project_id}.nba_reference.player_aliases"

        logger.info(f"Initialized AliasManager for table {self.table_id}")

    def create_alias(self, alias: AliasRecord) -> bool:
        """
        Create a single alias.

        Args:
            alias: AliasRecord to create

        Returns:
            True if created successfully
        """
        return self.bulk_create_aliases([alias]) == 1

    def bulk_create_aliases(self, aliases: List[AliasRecord]) -> int:
        """
        Create multiple aliases efficiently using MERGE to avoid duplicates.

        Args:
            aliases: List of AliasRecord objects

        Returns:
            Number of aliases successfully created
        """
        if not aliases:
            return 0

        # Prepare rows for insertion
        rows = []
        current_time = datetime.utcnow().isoformat()

        for alias in aliases:
            rows.append({
                'alias_lookup': alias.alias_lookup,
                'nba_canonical_lookup': alias.nba_canonical_lookup,
                'alias_display': alias.alias_display,
                'nba_canonical_display': alias.nba_canonical_display,
                'alias_type': alias.alias_type,
                'alias_source': alias.alias_source,
                'is_active': True,
                'notes': alias.notes,
                'created_by': 'ai_resolver',
                'created_at': current_time,
                'processed_at': current_time
            })

        # Use INSERT with check for existing
        # First check which aliases already exist
        existing = self._get_existing_aliases([a.alias_lookup for a in aliases])
        new_rows = [r for r in rows if r['alias_lookup'] not in existing]

        if not new_rows:
            logger.info("All aliases already exist, nothing to create")
            return 0

        try:
            errors = self.client.insert_rows_json(self.table_id, new_rows)

            if errors:
                logger.error(f"Errors inserting aliases: {errors}")
                return len(new_rows) - len(errors)

            logger.info(f"Created {len(new_rows)} aliases")
            return len(new_rows)

        except Exception as e:
            logger.error(f"Failed to create aliases: {e}")
            return 0

    def _get_existing_aliases(self, alias_lookups: List[str]) -> set:
        """Get set of alias_lookups that already exist."""
        if not alias_lookups:
            return set()

        query = f"""
        SELECT alias_lookup
        FROM `{self.table_id}`
        WHERE alias_lookup IN UNNEST(@lookups)
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("lookups", "STRING", alias_lookups)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result()
            return {row.alias_lookup for row in results}
        except Exception as e:
            logger.warning(f"Error checking existing aliases: {e}")
            return set()

    def get_alias(self, alias_lookup: str) -> Optional[AliasRecord]:
        """
        Get alias by lookup.

        Args:
            alias_lookup: The alias lookup name

        Returns:
            AliasRecord if found, None otherwise
        """
        query = f"""
        SELECT *
        FROM `{self.table_id}`
        WHERE alias_lookup = @lookup
        AND is_active = TRUE
        LIMIT 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("lookup", "STRING", alias_lookup)
            ]
        )

        try:
            results = list(self.client.query(query, job_config=job_config).result())

            if not results:
                return None

            row = results[0]
            return AliasRecord(
                alias_lookup=row.alias_lookup,
                nba_canonical_lookup=row.nba_canonical_lookup,
                alias_display=row.alias_display,
                nba_canonical_display=row.nba_canonical_display,
                alias_type=row.alias_type,
                alias_source=row.alias_source,
                confidence=getattr(row, 'confidence', 1.0) or 1.0,
                ai_model=getattr(row, 'ai_model', None),
                resolution_id=getattr(row, 'resolution_id', None),
                notes=row.notes
            )
        except Exception as e:
            logger.error(f"Error getting alias {alias_lookup}: {e}")
            return None

    def deactivate_alias(self, alias_lookup: str, reason: str) -> bool:
        """
        Soft-delete an alias by setting is_active=False.

        Args:
            alias_lookup: The alias to deactivate
            reason: Reason for deactivation

        Returns:
            True if deactivated successfully
        """
        query = f"""
        UPDATE `{self.table_id}`
        SET
            is_active = FALSE,
            notes = CONCAT(IFNULL(notes, ''), ' | Deactivated: ', @reason),
            processed_at = CURRENT_TIMESTAMP()
        WHERE alias_lookup = @lookup
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("lookup", "STRING", alias_lookup),
                bigquery.ScalarQueryParameter("reason", "STRING", reason)
            ]
        )

        try:
            job = self.client.query(query, job_config=job_config)
            job.result()
            logger.info(f"Deactivated alias: {alias_lookup} (reason: {reason})")
            return True
        except Exception as e:
            logger.error(f"Failed to deactivate alias {alias_lookup}: {e}")
            return False

    def get_all_active_aliases(self) -> List[AliasRecord]:
        """Get all active aliases."""
        query = f"""
        SELECT *
        FROM `{self.table_id}`
        WHERE is_active = TRUE
        ORDER BY alias_lookup
        """

        try:
            results = self.client.query(query).result()

            aliases = []
            for row in results:
                aliases.append(AliasRecord(
                    alias_lookup=row.alias_lookup,
                    nba_canonical_lookup=row.nba_canonical_lookup,
                    alias_display=row.alias_display,
                    nba_canonical_display=row.nba_canonical_display,
                    alias_type=row.alias_type,
                    alias_source=row.alias_source,
                    confidence=getattr(row, 'confidence', 1.0) or 1.0,
                    ai_model=getattr(row, 'ai_model', None),
                    resolution_id=getattr(row, 'resolution_id', None),
                    notes=row.notes
                ))

            return aliases
        except Exception as e:
            logger.error(f"Error getting all aliases: {e}")
            return []

    def get_alias_stats(self) -> Dict:
        """Get statistics about aliases."""
        query = f"""
        SELECT
            COUNT(*) as total,
            COUNTIF(is_active) as active,
            COUNTIF(NOT is_active) as inactive
        FROM `{self.table_id}`
        """

        query2 = f"""
        SELECT
            alias_type,
            COUNT(*) as count
        FROM `{self.table_id}`
        WHERE is_active = TRUE
        GROUP BY alias_type
        ORDER BY count DESC
        """

        try:
            result1 = list(self.client.query(query).result())[0]
            result2 = list(self.client.query(query2).result())

            by_type = {row.alias_type: row.count for row in result2}

            return {
                'total': result1.total,
                'active': result1.active,
                'inactive': result1.inactive,
                'by_type': by_type
            }
        except Exception as e:
            logger.error(f"Error getting alias stats: {e}")
            return {'total': 0, 'active': 0, 'inactive': 0, 'by_type': {}}
