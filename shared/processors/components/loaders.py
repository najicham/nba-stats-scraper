"""
Data loader components for the composable processor framework.

Loaders are responsible for fetching data from various sources:
- BigQuery tables
- GCS files
- External APIs

Key features:
- Automatic retry with exponential backoff
- Fallback chain support
- Source metadata tracking
- Caching for expensive queries

Version: 1.0
Created: 2026-01-23
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union

import pandas as pd
from google.api_core.exceptions import GoogleAPIError

from .base import DataLoader, ComponentContext

logger = logging.getLogger(__name__)


@dataclass
class QueryTemplate:
    """
    Template for a parameterized BigQuery query.

    Supports named placeholders that are filled from context:
    - {start_date}: From context.start_date
    - {end_date}: From context.end_date
    - {project_id}: From context.project_id
    - {custom_param}: From context.options['custom_param']
    """
    sql: str
    description: str = ''


class BigQueryLoader(DataLoader):
    """
    Load data from BigQuery using a SQL query.

    Features:
    - Parameterized queries with date substitution
    - Automatic retry on transient errors
    - Query result caching option
    - Source metadata tracking

    Example:
        loader = BigQueryLoader(
            query='''
                SELECT * FROM `{project_id}.nba_raw.player_stats`
                WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            ''',
            source_name='player_stats',
        )
    """

    def __init__(
        self,
        query: Union[str, QueryTemplate],
        source_name: str,
        description: str = '',
        timeout_seconds: int = 120,
        max_retries: int = 3,
        name: Optional[str] = None,
    ):
        """
        Initialize BigQuery loader.

        Args:
            query: SQL query string or QueryTemplate
            source_name: Name for source tracking
            description: Human-readable description
            timeout_seconds: Query timeout
            max_retries: Number of retry attempts
            name: Optional component name
        """
        super().__init__(name=name)

        if isinstance(query, QueryTemplate):
            self.query_template = query.sql
            self.description = query.description or description
        else:
            self.query_template = query
            self.description = description

        self.source_name = source_name
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def load(self, context: ComponentContext) -> pd.DataFrame:
        """
        Load data from BigQuery.

        Args:
            context: Processing context with dates and BQ client

        Returns:
            DataFrame with query results
        """
        # Build query by substituting parameters
        query = self._build_query(context)

        logger.debug(f"Executing BigQuery query for {self.source_name}")

        try:
            # Execute query with retries
            df = self._execute_with_retry(context.bq_client, query)

            # Track source metadata
            context.add_source(self.source_name, {
                'rows_loaded': len(df),
                'loaded_at': datetime.now(timezone.utc).isoformat(),
                'description': self.description,
            })

            logger.info(f"Loaded {len(df)} rows from {self.source_name}")
            return df

        except Exception as e:
            logger.error(f"Failed to load from {self.source_name}: {e}", exc_info=True)
            raise

    def _build_query(self, context: ComponentContext) -> str:
        """Build query by substituting parameters."""
        query = self.query_template

        # Standard substitutions
        substitutions = {
            'start_date': context.start_date,
            'end_date': context.end_date,
            'project_id': context.project_id,
        }

        # Add any custom options
        substitutions.update(context.options)

        # Perform substitution
        for key, value in substitutions.items():
            query = query.replace('{' + key + '}', str(value))

        return query

    def _execute_with_retry(
        self,
        client,
        query: str,
    ) -> pd.DataFrame:
        """Execute query with retry on transient errors."""
        import time

        last_error = None
        for attempt in range(self.max_retries):
            try:
                job = client.query(query)
                result = job.result(timeout=self.timeout_seconds)
                return result.to_dataframe()

            except GoogleAPIError as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(
                        f"Query failed (attempt {attempt + 1}/{self.max_retries}), "
                        f"retrying in {wait_time}s: {e}"
                    )
                    time.sleep(wait_time)
                else:
                    raise

        raise last_error

    def validate_config(self) -> List[str]:
        """Validate loader configuration."""
        errors = []

        if not self.query_template:
            errors.append(f"{self.name}: Query template is required")
        if not self.source_name:
            errors.append(f"{self.name}: Source name is required")

        # Check for required placeholders
        if '{start_date}' not in self.query_template:
            logger.warning(f"{self.name}: Query doesn't use start_date placeholder")
        if '{end_date}' not in self.query_template:
            logger.warning(f"{self.name}: Query doesn't use end_date placeholder")

        return errors


@dataclass
class FallbackSource:
    """Configuration for a source in a fallback chain."""
    name: str
    loader: Callable[['ComponentContext'], pd.DataFrame]
    quality_tier: str = 'gold'
    quality_score: float = 100.0
    is_reconstruction: bool = False


class FallbackLoader(DataLoader):
    """
    Load data with automatic fallback to alternative sources.

    Tries sources in order until one succeeds. Tracks which source was used
    and adjusts quality accordingly.

    Example:
        loader = FallbackLoader(
            sources=[
                FallbackSource(
                    name='primary',
                    loader=lambda ctx: primary_loader.load(ctx),
                    quality_tier='gold',
                ),
                FallbackSource(
                    name='backup',
                    loader=lambda ctx: backup_loader.load(ctx),
                    quality_tier='silver',
                ),
            ],
            on_all_fail='skip',  # or 'error', 'placeholder'
        )
    """

    def __init__(
        self,
        sources: List[FallbackSource],
        on_all_fail: str = 'error',
        name: Optional[str] = None,
    ):
        """
        Initialize fallback loader.

        Args:
            sources: Ordered list of fallback sources to try
            on_all_fail: Action when all sources fail ('error', 'skip', 'placeholder')
            name: Optional component name
        """
        super().__init__(name=name)
        self.sources = sources
        self.on_all_fail = on_all_fail

        # Track which source was used
        self.source_used: Optional[str] = None
        self.quality_tier: str = 'unknown'
        self.quality_score: float = 0.0

    def load(self, context: ComponentContext) -> pd.DataFrame:
        """
        Load data, falling back through sources as needed.

        Args:
            context: Processing context

        Returns:
            DataFrame from first successful source
        """
        sources_tried = []

        for source in self.sources:
            sources_tried.append(source.name)
            logger.debug(f"Trying source: {source.name}")

            try:
                df = source.loader(context)

                if df is not None and not df.empty:
                    # Success!
                    self.source_used = source.name
                    self.quality_tier = source.quality_tier
                    self.quality_score = source.quality_score

                    context.add_source(source.name, {
                        'rows_loaded': len(df),
                        'quality_tier': source.quality_tier,
                        'quality_score': source.quality_score,
                        'is_reconstruction': source.is_reconstruction,
                        'fallback_position': sources_tried.index(source.name),
                    })

                    if len(sources_tried) > 1:
                        logger.warning(
                            f"Used fallback source '{source.name}' after "
                            f"trying: {sources_tried[:-1]}"
                        )

                    return df

            except Exception as e:
                logger.warning(f"Source '{source.name}' failed: {e}")
                continue

        # All sources failed
        logger.error(f"All sources failed: {sources_tried}", exc_info=True)

        if self.on_all_fail == 'error':
            raise ValueError(f"All data sources failed: {sources_tried}")
        elif self.on_all_fail == 'skip':
            return pd.DataFrame()
        elif self.on_all_fail == 'placeholder':
            self.source_used = 'placeholder'
            self.quality_tier = 'unusable'
            self.quality_score = 0.0
            return pd.DataFrame()
        else:
            raise ValueError(f"Unknown on_all_fail action: {self.on_all_fail}")

    def validate_config(self) -> List[str]:
        """Validate loader configuration."""
        errors = []

        if not self.sources:
            errors.append(f"{self.name}: At least one source is required")

        if self.on_all_fail not in ('error', 'skip', 'placeholder'):
            errors.append(
                f"{self.name}: on_all_fail must be 'error', 'skip', or 'placeholder'"
            )

        return errors


class CachedLoader(DataLoader):
    """
    Wrapper that caches loader results to avoid redundant queries.

    Useful for expensive queries that might be called multiple times
    during processing (e.g., lookup tables).

    Example:
        loader = CachedLoader(
            inner_loader=BigQueryLoader(...),
            cache_key='team_mapping_{start_date}',
            ttl_seconds=300,
        )
    """

    # Class-level cache (shared across instances)
    _cache: Dict[str, Dict[str, Any]] = {}

    def __init__(
        self,
        inner_loader: DataLoader,
        cache_key: str,
        ttl_seconds: int = 300,
        name: Optional[str] = None,
    ):
        """
        Initialize cached loader.

        Args:
            inner_loader: The loader to wrap
            cache_key: Key template for caching (can use {start_date}, etc.)
            ttl_seconds: Cache time-to-live
            name: Optional component name
        """
        super().__init__(name=name)
        self.inner_loader = inner_loader
        self.cache_key_template = cache_key
        self.ttl_seconds = ttl_seconds

    def load(self, context: ComponentContext) -> pd.DataFrame:
        """
        Load data, using cache if available.

        Args:
            context: Processing context

        Returns:
            DataFrame (from cache or fresh query)
        """
        import time

        # Build cache key
        cache_key = self.cache_key_template.format(
            start_date=context.start_date,
            end_date=context.end_date,
            project_id=context.project_id,
        )

        # Check cache
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            age = time.time() - cached['timestamp']

            if age < self.ttl_seconds:
                logger.debug(f"Cache hit for {cache_key} (age: {age:.1f}s)")
                return cached['data'].copy()
            else:
                logger.debug(f"Cache expired for {cache_key} (age: {age:.1f}s)")
                del self._cache[cache_key]

        # Load fresh data
        df = self.inner_loader.load(context)

        # Store in cache
        self._cache[cache_key] = {
            'data': df.copy(),
            'timestamp': time.time(),
        }

        logger.debug(f"Cached {len(df)} rows for {cache_key}")
        return df

    def validate_config(self) -> List[str]:
        """Validate loader configuration."""
        errors = self.inner_loader.validate_config()

        if not self.cache_key_template:
            errors.append(f"{self.name}: Cache key template is required")

        return errors

    @classmethod
    def clear_cache(cls):
        """Clear all cached data."""
        cls._cache.clear()
        logger.info("Loader cache cleared")
