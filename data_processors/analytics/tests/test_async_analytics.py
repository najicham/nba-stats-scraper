#!/usr/bin/env python3
"""
Test async analytics infrastructure.

This module tests the async analytics base class and orchestration utilities.
It uses mock queries to verify concurrent execution without requiring BigQuery.
"""

import asyncio
import logging
import time
import unittest
from datetime import datetime, timezone
from typing import Dict, List
from unittest.mock import MagicMock, patch

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestAsyncAnalyticsBase(unittest.TestCase):
    """Test AsyncAnalyticsProcessorBase functionality."""

    def test_async_analytics_base_import(self):
        """Test that AsyncAnalyticsProcessorBase can be imported."""
        from data_processors.analytics import AsyncAnalyticsProcessorBase
        self.assertIsNotNone(AsyncAnalyticsProcessorBase)

    def test_async_query_batch_import(self):
        """Test that AsyncQueryBatch can be imported."""
        from data_processors.analytics import AsyncQueryBatch
        self.assertIsNotNone(AsyncQueryBatch)

    def test_async_processor_inheritance(self):
        """Test AsyncUpcomingPlayerGameContextProcessor inheritance."""
        from data_processors.analytics.upcoming_player_game_context import (
            AsyncUpcomingPlayerGameContextProcessor,
            UpcomingPlayerGameContextProcessor,
        )
        from data_processors.analytics import AsyncAnalyticsProcessorBase

        # Verify inheritance
        self.assertTrue(
            issubclass(AsyncUpcomingPlayerGameContextProcessor, AsyncAnalyticsProcessorBase)
        )
        self.assertTrue(
            issubclass(AsyncUpcomingPlayerGameContextProcessor, UpcomingPlayerGameContextProcessor)
        )


class TestAsyncOrchestration(unittest.TestCase):
    """Test async orchestration utilities."""

    def test_is_async_processor(self):
        """Test is_async_processor detection."""
        from data_processors.analytics import is_async_processor
        from data_processors.analytics.upcoming_player_game_context import (
            UpcomingPlayerGameContextProcessor,
            AsyncUpcomingPlayerGameContextProcessor,
        )

        # Sync processor should return False
        self.assertFalse(is_async_processor(UpcomingPlayerGameContextProcessor))

        # Async processor should return True
        self.assertTrue(is_async_processor(AsyncUpcomingPlayerGameContextProcessor))

    def test_get_async_processor(self):
        """Test get_async_processor lookup."""
        from data_processors.analytics import get_async_processor
        from data_processors.analytics.upcoming_player_game_context import (
            UpcomingPlayerGameContextProcessor,
            AsyncUpcomingPlayerGameContextProcessor,
        )

        # Should find registered async version
        result = get_async_processor(UpcomingPlayerGameContextProcessor)
        self.assertEqual(result, AsyncUpcomingPlayerGameContextProcessor)

    def test_async_registry(self):
        """Test async processor registry."""
        from data_processors.analytics.async_orchestration import ASYNC_PROCESSOR_REGISTRY

        # UpcomingPlayerGameContextProcessor should be registered
        self.assertIn('UpcomingPlayerGameContextProcessor', ASYNC_PROCESSOR_REGISTRY)


class TestConcurrentQueryExecution(unittest.TestCase):
    """Test concurrent query execution patterns."""

    def test_async_gather_pattern(self):
        """Test that asyncio.gather works for concurrent tasks."""

        async def mock_query(name: str, delay: float) -> Dict:
            """Simulate a query with delay."""
            await asyncio.sleep(delay)
            return {'name': name, 'completed': True}

        async def run_concurrent_queries():
            """Run multiple queries concurrently."""
            start_time = time.time()

            # Run 5 queries concurrently, each taking 0.1s
            results = await asyncio.gather(
                mock_query('query1', 0.1),
                mock_query('query2', 0.1),
                mock_query('query3', 0.1),
                mock_query('query4', 0.1),
                mock_query('query5', 0.1),
            )

            elapsed = time.time() - start_time
            return results, elapsed

        # Run the test
        results, elapsed = asyncio.run(run_concurrent_queries())

        # Verify all queries completed
        self.assertEqual(len(results), 5)
        for result in results:
            self.assertTrue(result['completed'])

        # Verify concurrent execution (should take ~0.1s, not 0.5s)
        # Allow some overhead
        self.assertLess(elapsed, 0.3, f"Expected <0.3s, got {elapsed:.2f}s")
        logger.info(f"Concurrent queries completed in {elapsed:.2f}s")


class TestAsyncQueryBatch(unittest.TestCase):
    """Test AsyncQueryBatch helper class."""

    def test_batch_add_and_clear(self):
        """Test adding queries and clearing batch."""
        from data_processors.analytics import AsyncQueryBatch

        # Create mock processor
        mock_processor = MagicMock()
        batch = AsyncQueryBatch(mock_processor)

        # Add queries
        batch.add('query1', 'SELECT 1')
        batch.add('query2', 'SELECT 2', timeout=60)
        batch.add('query3', 'SELECT 3')

        # Verify queries added
        self.assertEqual(len(batch.queries), 3)
        self.assertEqual(len(batch.names), 3)
        self.assertIn('query1', batch.names)

        # Clear and verify
        batch.clear()
        self.assertEqual(len(batch.queries), 0)
        self.assertEqual(len(batch.names), 0)

    def test_batch_fluent_interface(self):
        """Test fluent interface (method chaining)."""
        from data_processors.analytics import AsyncQueryBatch

        mock_processor = MagicMock()
        batch = AsyncQueryBatch(mock_processor)

        # Fluent interface should work
        result = (batch
            .add('q1', 'SELECT 1')
            .add('q2', 'SELECT 2')
            .add('q3', 'SELECT 3'))

        self.assertIs(result, batch)
        self.assertEqual(len(batch.queries), 3)


if __name__ == '__main__':
    unittest.main()
