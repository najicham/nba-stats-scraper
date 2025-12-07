#!/usr/bin/env python3
"""
Cache AI resolution decisions to avoid repeated API calls.

This module provides caching for AI resolution decisions, enabling:
- Cost savings by not re-resolving the same names
- Consistency (same name always resolves the same way)
- Audit trail for all AI decisions
"""

import os
import json
import logging
from typing import Optional, Dict, List
from google.cloud import bigquery
from datetime import datetime
from dataclasses import asdict

from .ai_resolver import AIResolution

logger = logging.getLogger(__name__)


class ResolutionCache:
    """
    Cache and retrieve AI resolution decisions.

    Example:
        cache = ResolutionCache()

        # Check if cached
        cached = cache.get_cached('marcusmorris')
        if cached:
            print(f"Using cached decision: {cached.resolution_type}")
        else:
            # Resolve with AI and cache
            resolution = resolver.resolve_single(context)
            cache.cache_resolution(resolution, context_dict)
    """

    # Table may not exist yet, so we'll create it on first use
    TABLE_SCHEMA = [
        bigquery.SchemaField("cache_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("unresolved_lookup", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("resolved_to", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("resolution_type", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("confidence", "FLOAT64", mode="REQUIRED"),
        bigquery.SchemaField("reasoning", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("team_abbr", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("season", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("candidates_provided", "STRING", mode="REPEATED"),
        bigquery.SchemaField("context_json", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("ai_model", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("api_call_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("input_tokens", "INT64", mode="NULLABLE"),
        bigquery.SchemaField("output_tokens", "INT64", mode="NULLABLE"),
        bigquery.SchemaField("cost_usd", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("used_count", "INT64", mode="NULLABLE"),
        bigquery.SchemaField("last_used_at", "TIMESTAMP", mode="NULLABLE"),
    ]

    def __init__(self, project_id: str = None):
        """
        Initialize resolution cache.

        Args:
            project_id: GCP project ID (defaults to GCP_PROJECT_ID env var)
        """
        self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.client = bigquery.Client(project=self.project_id)
        self.table_id = f"{self.project_id}.nba_reference.ai_resolution_cache"

        # Ensure table exists
        self._ensure_table_exists()

        logger.info(f"Initialized ResolutionCache for table {self.table_id}")

    def _ensure_table_exists(self):
        """Create the cache table if it doesn't exist."""
        try:
            self.client.get_table(self.table_id)
        except Exception:
            logger.info(f"Creating cache table: {self.table_id}")
            table = bigquery.Table(self.table_id, schema=self.TABLE_SCHEMA)
            self.client.create_table(table, exists_ok=True)

    def get_cached(self, unresolved_lookup: str) -> Optional[AIResolution]:
        """
        Get cached resolution for a name.

        Args:
            unresolved_lookup: The normalized lookup name

        Returns:
            AIResolution if cached, None otherwise
        """
        query = f"""
        SELECT *
        FROM `{self.table_id}`
        WHERE unresolved_lookup = @lookup
        LIMIT 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("lookup", "STRING", unresolved_lookup)
            ]
        )

        try:
            results = list(self.client.query(query, job_config=job_config).result())

            if not results:
                return None

            row = results[0]

            # Increment usage count asynchronously
            self._increment_usage(unresolved_lookup)

            return AIResolution(
                unresolved_lookup=row.unresolved_lookup,
                resolution_type=row.resolution_type,
                canonical_lookup=row.resolved_to,
                confidence=row.confidence,
                reasoning=row.reasoning,
                ai_model=row.ai_model,
                api_call_id=row.api_call_id or 'cached',
                input_tokens=0,  # Not relevant for cached
                output_tokens=0
            )
        except Exception as e:
            logger.warning(f"Error getting cached resolution for {unresolved_lookup}: {e}")
            return None

    def cache_resolution(self, resolution: AIResolution, context: Dict) -> bool:
        """
        Cache a new resolution decision.

        Args:
            resolution: The AIResolution to cache
            context: Additional context (team_abbr, season, candidates, etc.)

        Returns:
            True if cached successfully
        """
        row = {
            'cache_id': f"{resolution.unresolved_lookup}_{resolution.api_call_id}",
            'unresolved_lookup': resolution.unresolved_lookup,
            'resolved_to': resolution.canonical_lookup,
            'resolution_type': resolution.resolution_type,
            'confidence': resolution.confidence,
            'reasoning': resolution.reasoning,
            'team_abbr': context.get('team_abbr'),
            'season': context.get('season'),
            'candidates_provided': context.get('candidates', []),
            'context_json': json.dumps(context) if context else None,
            'ai_model': resolution.ai_model,
            'api_call_id': resolution.api_call_id,
            'input_tokens': resolution.input_tokens,
            'output_tokens': resolution.output_tokens,
            'cost_usd': self._calculate_cost(resolution),
            'created_at': datetime.utcnow().isoformat(),
            'used_count': 0,
            'last_used_at': None
        }

        try:
            errors = self.client.insert_rows_json(self.table_id, [row])

            if errors:
                logger.error(f"Error caching resolution: {errors}")
                return False

            logger.debug(f"Cached resolution for {resolution.unresolved_lookup}")
            return True

        except Exception as e:
            logger.error(f"Failed to cache resolution: {e}")
            return False

    def _increment_usage(self, unresolved_lookup: str):
        """Increment the usage count for a cached entry."""
        query = f"""
        UPDATE `{self.table_id}`
        SET
            used_count = IFNULL(used_count, 0) + 1,
            last_used_at = CURRENT_TIMESTAMP()
        WHERE unresolved_lookup = @lookup
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("lookup", "STRING", unresolved_lookup)
            ]
        )

        try:
            self.client.query(query, job_config=job_config).result()
        except Exception as e:
            logger.warning(f"Failed to increment usage for {unresolved_lookup}: {e}")

    def _calculate_cost(self, resolution: AIResolution) -> float:
        """
        Calculate API cost based on token usage.

        Based on Claude Haiku pricing (as of Dec 2024):
        - Input: $0.25 / 1M tokens
        - Output: $1.25 / 1M tokens
        """
        input_cost = resolution.input_tokens * (0.25 / 1_000_000)
        output_cost = resolution.output_tokens * (1.25 / 1_000_000)
        return input_cost + output_cost

    def get_stats(self) -> Dict:
        """Get cache statistics."""
        query = f"""
        SELECT
            COUNT(*) as total_entries,
            SUM(used_count) as total_cache_hits,
            AVG(confidence) as avg_confidence,
            SUM(cost_usd) as total_cost,
            COUNTIF(resolution_type = 'MATCH') as matches,
            COUNTIF(resolution_type = 'NEW_PLAYER') as new_players,
            COUNTIF(resolution_type = 'DATA_ERROR') as data_errors
        FROM `{self.table_id}`
        """

        try:
            results = list(self.client.query(query).result())
            if not results:
                return {}

            row = results[0]
            return {
                'total_entries': row.total_entries or 0,
                'total_cache_hits': row.total_cache_hits or 0,
                'avg_confidence': row.avg_confidence or 0,
                'total_cost': row.total_cost or 0,
                'by_type': {
                    'MATCH': row.matches or 0,
                    'NEW_PLAYER': row.new_players or 0,
                    'DATA_ERROR': row.data_errors or 0
                }
            }
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {}

    def clear_cache(self, before_date: str = None) -> int:
        """
        Clear cache entries.

        Args:
            before_date: Only clear entries created before this date (YYYY-MM-DD)

        Returns:
            Number of entries deleted
        """
        if before_date:
            query = f"""
            DELETE FROM `{self.table_id}`
            WHERE DATE(created_at) < @before_date
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("before_date", "DATE", before_date)
                ]
            )
        else:
            query = f"DELETE FROM `{self.table_id}` WHERE TRUE"
            job_config = bigquery.QueryJobConfig()

        try:
            job = self.client.query(query, job_config=job_config)
            job.result()
            deleted = job.num_dml_affected_rows or 0
            logger.info(f"Cleared {deleted} cache entries")
            return deleted
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return 0
