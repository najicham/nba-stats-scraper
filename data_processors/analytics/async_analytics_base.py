"""
Path: data_processors/analytics/async_analytics_base.py

Async Base class for Phase 3 analytics processors.

This module provides async support for analytics processors that need to make
multiple concurrent BigQuery queries or external API calls. It extends the
synchronous AnalyticsProcessorBase with async capabilities.

Key Features:
- Async BigQuery query execution with connection pooling
- Concurrent data extraction from multiple sources
- Backward compatibility with synchronous processors
- Graceful fallback to sync execution

Usage:
    class MyAsyncProcessor(AsyncAnalyticsProcessorBase):
        async def extract_raw_data_async(self):
            # Run multiple queries concurrently
            results = await asyncio.gather(
                self.execute_query_async(query1),
                self.execute_query_async(query2),
                self.execute_query_async(query3),
            )
            ...

Version: 1.0
Created: January 2026
"""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from typing import Any, Callable, Dict, List, Optional, TypeVar

from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError, ServiceUnavailable, DeadlineExceeded

from data_processors.analytics.analytics_base import AnalyticsProcessorBase

logger = logging.getLogger(__name__)

T = TypeVar('T')


class AsyncAnalyticsProcessorBase(AnalyticsProcessorBase):
    """
    Async-capable base class for Phase 3 analytics processors.

    Extends AnalyticsProcessorBase with async query execution and concurrent
    data extraction capabilities. Processors can override async methods for
    better concurrency, or continue using sync methods for compatibility.

    Async Pattern:
        The processor uses a hybrid approach:
        - Main orchestration remains synchronous (run() method)
        - Data extraction can use async methods for concurrent queries
        - ThreadPoolExecutor bridges sync BigQuery client to async code

    Configuration:
        ASYNC_MAX_CONCURRENT_QUERIES: Max concurrent BigQuery queries (default: 5)
        ASYNC_QUERY_TIMEOUT: Timeout per query in seconds (default: 300)
    """

    # Async configuration
    ASYNC_MAX_CONCURRENT_QUERIES: int = 5
    ASYNC_QUERY_TIMEOUT: int = 300  # 5 minutes per query

    def __init__(self):
        super().__init__()
        # Thread pool for bridging sync BigQuery client to async
        self._executor: Optional[ThreadPoolExecutor] = None
        # Semaphore to limit concurrent queries
        self._query_semaphore: Optional[asyncio.Semaphore] = None

    def _get_executor(self) -> ThreadPoolExecutor:
        """Get or create the thread pool executor."""
        if self._executor is None:
            max_workers = int(os.environ.get(
                'ASYNC_BQ_WORKERS',
                self.ASYNC_MAX_CONCURRENT_QUERIES
            ))
            self._executor = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix='async_bq'
            )
            logger.debug(f"Created ThreadPoolExecutor with {max_workers} workers")
        return self._executor

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Get or create the query semaphore."""
        if self._query_semaphore is None:
            self._query_semaphore = asyncio.Semaphore(
                self.ASYNC_MAX_CONCURRENT_QUERIES
            )
        return self._query_semaphore

    async def execute_query_async(
        self,
        query: str,
        job_config: Optional[bigquery.QueryJobConfig] = None,
        timeout: Optional[int] = None
    ) -> List[Dict]:
        """
        Execute a BigQuery query asynchronously.

        Uses a thread pool to run the synchronous BigQuery client in a
        non-blocking way. Respects the concurrency limit via semaphore.

        Args:
            query: SQL query to execute
            job_config: Optional BigQuery job configuration
            timeout: Query timeout in seconds (default: ASYNC_QUERY_TIMEOUT)

        Returns:
            List of result rows as dictionaries

        Raises:
            GoogleAPIError: If the query fails
            asyncio.TimeoutError: If the query times out
        """
        timeout = timeout or self.ASYNC_QUERY_TIMEOUT
        semaphore = self._get_semaphore()
        executor = self._get_executor()

        async with semaphore:
            loop = asyncio.get_event_loop()

            def run_query():
                """Synchronous query execution in thread pool."""
                if job_config:
                    job = self.bq_client.query(query, job_config=job_config)
                else:
                    job = self.bq_client.query(query)
                results = job.result(timeout=timeout)
                return [dict(row) for row in results]

            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(executor, run_query),
                    timeout=timeout + 30  # Extra buffer for executor overhead
                )
                return result
            except asyncio.TimeoutError:
                logger.error(f"Query timed out after {timeout}s")
                raise
            except (GoogleAPIError, ServiceUnavailable, DeadlineExceeded) as e:
                logger.error(f"BigQuery error in async query: {e}")
                raise

    async def execute_queries_concurrently(
        self,
        queries: List[Dict[str, Any]],
        return_exceptions: bool = False
    ) -> List[Any]:
        """
        Execute multiple BigQuery queries concurrently.

        Args:
            queries: List of query specifications, each containing:
                - 'query': SQL query string
                - 'job_config': Optional QueryJobConfig
                - 'timeout': Optional timeout override
                - 'name': Optional name for logging
            return_exceptions: If True, exceptions are returned instead of raised

        Returns:
            List of results in the same order as input queries.
            If return_exceptions=True, failed queries return the exception.

        Example:
            results = await self.execute_queries_concurrently([
                {'query': query1, 'name': 'schedule'},
                {'query': query2, 'name': 'boxscores'},
                {'query': query3, 'name': 'props', 'timeout': 60},
            ])
        """
        async def run_single_query(spec: Dict) -> Any:
            query = spec['query']
            job_config = spec.get('job_config')
            timeout = spec.get('timeout')
            name = spec.get('name', 'unnamed')

            start_time = datetime.now(timezone.utc)
            try:
                result = await self.execute_query_async(query, job_config, timeout)
                elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                logger.debug(f"Query '{name}' completed in {elapsed:.2f}s ({len(result)} rows)")
                return result
            except Exception as e:
                elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                logger.error(f"Query '{name}' failed after {elapsed:.2f}s: {e}")
                raise

        tasks = [run_single_query(spec) for spec in queries]
        return await asyncio.gather(*tasks, return_exceptions=return_exceptions)

    async def run_async_with_timeout(
        self,
        coro: Callable[[], T],
        timeout: int,
        description: str = "operation"
    ) -> T:
        """
        Run an async coroutine with a timeout.

        Args:
            coro: Coroutine to execute
            timeout: Timeout in seconds
            description: Description for logging

        Returns:
            Result of the coroutine

        Raises:
            asyncio.TimeoutError: If the operation times out
        """
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(f"Async {description} timed out after {timeout}s")
            raise

    def run_async(self, coro):
        """
        Run an async coroutine from synchronous code.

        This method bridges the gap between the synchronous run() orchestration
        and async data extraction methods. It handles event loop creation and
        cleanup.

        Args:
            coro: Coroutine to execute

        Returns:
            Result of the coroutine
        """
        # Check if we're already in an async context
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context - create a task
            # This shouldn't happen in normal operation
            logger.warning("run_async called from async context - using nested event loop")
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
        except RuntimeError:
            # No running loop - create one
            return asyncio.run(coro)

    def extract_raw_data(self) -> None:
        """
        Override base class to support async extraction.

        Checks if the subclass implements extract_raw_data_async and calls it
        using the async bridge. Otherwise, falls back to synchronous extraction.
        """
        if hasattr(self, 'extract_raw_data_async') and callable(self.extract_raw_data_async):
            logger.info("Using async data extraction")
            self.run_async(self.extract_raw_data_async())
        else:
            # Fall back to synchronous (child class should override)
            logger.debug("No async extraction defined - using sync")
            super().extract_raw_data()

    async def extract_raw_data_async(self) -> None:
        """
        Async data extraction - override in child classes.

        Child classes should override this method to implement concurrent
        data extraction from multiple sources.

        Example:
            async def extract_raw_data_async(self):
                # Run multiple extractions concurrently
                await asyncio.gather(
                    self._extract_schedule_async(),
                    self._extract_boxscores_async(),
                    self._extract_props_async(),
                )
        """
        raise NotImplementedError(
            "Subclass must implement extract_raw_data_async() or extract_raw_data()"
        )

    def finalize(self) -> None:
        """
        Cleanup hook - ensures thread pool is shut down.
        """
        super().finalize()

        # Shutdown the executor if it was created
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=True, cancel_futures=False)
                logger.debug("ThreadPoolExecutor shut down successfully")
            except Exception as e:
                logger.warning(f"Error shutting down executor: {e}")
            finally:
                self._executor = None

        # Reset semaphore
        self._query_semaphore = None


class AsyncQueryBatch:
    """
    Helper class for building and executing batched async queries.

    Provides a fluent interface for building concurrent query batches
    with result mapping.

    Example:
        batch = AsyncQueryBatch(processor)
        batch.add('schedule', schedule_query)
        batch.add('boxscores', boxscores_query, timeout=120)
        batch.add('props', props_query, job_config=config)

        results = await batch.execute()
        schedule_data = results['schedule']
        boxscores_data = results['boxscores']
    """

    def __init__(self, processor: AsyncAnalyticsProcessorBase):
        self.processor = processor
        self.queries: List[Dict[str, Any]] = []
        self.names: List[str] = []

    def add(
        self,
        name: str,
        query: str,
        job_config: Optional[bigquery.QueryJobConfig] = None,
        timeout: Optional[int] = None
    ) -> 'AsyncQueryBatch':
        """Add a query to the batch."""
        self.queries.append({
            'query': query,
            'job_config': job_config,
            'timeout': timeout,
            'name': name
        })
        self.names.append(name)
        return self

    async def execute(self, return_exceptions: bool = False) -> Dict[str, Any]:
        """
        Execute all queries concurrently and return results by name.

        Args:
            return_exceptions: If True, failed queries have exception as value

        Returns:
            Dict mapping query names to results
        """
        results = await self.processor.execute_queries_concurrently(
            self.queries,
            return_exceptions=return_exceptions
        )
        return dict(zip(self.names, results))

    def clear(self) -> None:
        """Clear all queries from the batch."""
        self.queries.clear()
        self.names.clear()
