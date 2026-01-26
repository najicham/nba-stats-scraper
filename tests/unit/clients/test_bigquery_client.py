"""
Unit tests for BigQuery Client Pool

Tests the connection pooling, client factory pattern, and error handling
for BigQuery clients.

Usage:
    pytest tests/unit/clients/test_bigquery_client.py -v
"""

import pytest
import threading
import time
from unittest.mock import Mock, patch, MagicMock
from google.cloud import bigquery


class TestBigQueryClientPool:
    """Test BigQuery client connection pooling."""

    @pytest.fixture(autouse=True)
    def cleanup_cache(self):
        """Clear client cache before and after each test."""
        from shared.clients import bigquery_pool
        bigquery_pool.clear_cache()
        yield
        bigquery_pool.clear_cache()

    @pytest.fixture
    def mock_bigquery_client(self):
        """Create mock BigQuery client."""
        mock_client = Mock(spec=bigquery.Client)
        mock_client.project = "test-project"
        mock_client.close = Mock()
        return mock_client

    def test_get_bigquery_client_creates_new_client(self, mock_bigquery_client):
        """Test that first call creates a new client."""
        with patch('shared.clients.bigquery_pool.bigquery.Client', return_value=mock_bigquery_client):
            with patch('shared.clients.bigquery_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.bigquery_pool import get_bigquery_client, get_client_count

                assert get_client_count() == 0

                client = get_bigquery_client()

                assert client is mock_bigquery_client
                assert get_client_count() == 1

    def test_get_bigquery_client_returns_cached_client(self, mock_bigquery_client):
        """Test that subsequent calls return the same cached client."""
        with patch('shared.clients.bigquery_pool.bigquery.Client', return_value=mock_bigquery_client):
            with patch('shared.clients.bigquery_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.bigquery_pool import get_bigquery_client

                client1 = get_bigquery_client()
                client2 = get_bigquery_client()

                assert client1 is client2
                assert client1 is mock_bigquery_client

    def test_get_bigquery_client_with_project_id(self, mock_bigquery_client):
        """Test creating client with explicit project ID."""
        with patch('shared.clients.bigquery_pool.bigquery.Client', return_value=mock_bigquery_client) as mock_constructor:
            from shared.clients.bigquery_pool import get_bigquery_client

            client = get_bigquery_client(project_id="custom-project")

            mock_constructor.assert_called_once_with(project="custom-project")
            assert client is mock_bigquery_client

    def test_get_bigquery_client_with_location(self, mock_bigquery_client):
        """Test creating client with explicit location."""
        with patch('shared.clients.bigquery_pool.bigquery.Client', return_value=mock_bigquery_client) as mock_constructor:
            with patch('shared.clients.bigquery_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.bigquery_pool import get_bigquery_client

                client = get_bigquery_client(location="us-west2")

                mock_constructor.assert_called_once_with(project="test-project", location="us-west2")
                assert client is mock_bigquery_client

    def test_get_bigquery_client_caches_per_project(self):
        """Test that different projects get different cached clients."""
        mock_client1 = Mock(spec=bigquery.Client)
        mock_client2 = Mock(spec=bigquery.Client)

        with patch('shared.clients.bigquery_pool.bigquery.Client', side_effect=[mock_client1, mock_client2]):
            from shared.clients.bigquery_pool import get_bigquery_client, get_client_count

            client1 = get_bigquery_client(project_id="project-1")
            client2 = get_bigquery_client(project_id="project-2")
            client1_again = get_bigquery_client(project_id="project-1")

            assert client1 is mock_client1
            assert client2 is mock_client2
            assert client1_again is mock_client1
            assert get_client_count() == 2

    def test_get_bigquery_client_caches_per_location(self):
        """Test that different locations for same project get different cached clients."""
        mock_client1 = Mock(spec=bigquery.Client)
        mock_client2 = Mock(spec=bigquery.Client)

        with patch('shared.clients.bigquery_pool.bigquery.Client', side_effect=[mock_client1, mock_client2]):
            with patch('shared.clients.bigquery_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.bigquery_pool import get_bigquery_client, get_client_count

                client1 = get_bigquery_client()  # No location
                client2 = get_bigquery_client(location="us-west2")
                client1_again = get_bigquery_client()

                assert client1 is mock_client1
                assert client2 is mock_client2
                assert client1_again is mock_client1
                assert get_client_count() == 2

    def test_close_all_clients(self, mock_bigquery_client):
        """Test closing all cached clients."""
        with patch('shared.clients.bigquery_pool.bigquery.Client', return_value=mock_bigquery_client):
            with patch('shared.clients.bigquery_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.bigquery_pool import get_bigquery_client, close_all_clients, get_client_count

                client = get_bigquery_client()
                assert get_client_count() == 1

                close_all_clients()

                assert get_client_count() == 0
                mock_bigquery_client.close.assert_called_once()

    def test_close_all_clients_handles_errors(self):
        """Test that close_all_clients handles errors gracefully."""
        mock_client = Mock(spec=bigquery.Client)
        mock_client.close.side_effect = Exception("Close error")

        with patch('shared.clients.bigquery_pool.bigquery.Client', return_value=mock_client):
            with patch('shared.clients.bigquery_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.bigquery_pool import get_bigquery_client, close_all_clients, get_client_count

                client = get_bigquery_client()
                assert get_client_count() == 1

                # Should not raise exception
                close_all_clients()

                assert get_client_count() == 0

    def test_clear_cache(self, mock_bigquery_client):
        """Test clearing cache without closing clients."""
        with patch('shared.clients.bigquery_pool.bigquery.Client', return_value=mock_bigquery_client):
            with patch('shared.clients.bigquery_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.bigquery_pool import get_bigquery_client, clear_cache, get_client_count

                client = get_bigquery_client()
                assert get_client_count() == 1

                clear_cache()

                assert get_client_count() == 0
                mock_bigquery_client.close.assert_not_called()


class TestBigQueryClientThreadSafety:
    """Test thread safety of BigQuery client pool."""

    @pytest.fixture(autouse=True)
    def cleanup_cache(self):
        """Clear client cache before and after each test."""
        from shared.clients import bigquery_pool
        bigquery_pool.clear_cache()
        yield
        bigquery_pool.clear_cache()

    def test_get_bigquery_client_thread_safe(self):
        """Test that concurrent calls create only one client."""
        mock_client = Mock(spec=bigquery.Client)
        mock_client.project = "test-project"
        creation_count = {"count": 0}
        lock = threading.Lock()

        def create_client_with_delay(*args, **kwargs):
            """Create client with artificial delay to simulate race condition."""
            with lock:
                creation_count["count"] += 1
            time.sleep(0.01)  # Simulate creation delay
            return mock_client

        with patch('shared.clients.bigquery_pool.bigquery.Client', side_effect=create_client_with_delay):
            with patch('shared.clients.bigquery_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.bigquery_pool import get_bigquery_client

                # Create 10 threads that all try to get client simultaneously
                threads = []
                results = []

                def get_client():
                    results.append(get_bigquery_client())

                for _ in range(10):
                    t = threading.Thread(target=get_client)
                    threads.append(t)
                    t.start()

                for t in threads:
                    t.join()

                # Only one client should have been created
                assert creation_count["count"] == 1

                # All threads should have received the same client
                assert len(results) == 10
                assert all(c is mock_client for c in results)

    def test_multiple_projects_thread_safe(self):
        """Test that concurrent calls for different projects work correctly."""
        mock_client1 = Mock(spec=bigquery.Client)
        mock_client2 = Mock(spec=bigquery.Client)
        clients = {"project-1": mock_client1, "project-2": mock_client2}

        def create_client(*args, **kwargs):
            project = kwargs.get("project", "test-project")
            return clients.get(project, Mock(spec=bigquery.Client))

        with patch('shared.clients.bigquery_pool.bigquery.Client', side_effect=create_client):
            from shared.clients.bigquery_pool import get_bigquery_client, get_client_count

            results = {"project-1": [], "project-2": []}

            def get_client(project_id):
                client = get_bigquery_client(project_id=project_id)
                results[project_id].append(client)

            threads = []
            for _ in range(5):
                for project_id in ["project-1", "project-2"]:
                    t = threading.Thread(target=get_client, args=(project_id,))
                    threads.append(t)
                    t.start()

            for t in threads:
                t.join()

            # Should have exactly 2 clients cached
            assert get_client_count() == 2

            # All project-1 calls should get same client
            assert len(results["project-1"]) == 5
            assert all(c is mock_client1 for c in results["project-1"])

            # All project-2 calls should get same client
            assert len(results["project-2"]) == 5
            assert all(c is mock_client2 for c in results["project-2"])


class TestBigQueryClientBackwardCompatibility:
    """Test backward compatibility features."""

    def test_get_client_deprecated_function(self):
        """Test deprecated get_client() function."""
        mock_client = Mock(spec=bigquery.Client)

        with patch('shared.clients.bigquery_pool.bigquery.Client', return_value=mock_client):
            with patch('shared.clients.bigquery_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.bigquery_pool import get_client

                with pytest.warns(DeprecationWarning, match="get_client.*deprecated"):
                    client = get_client("test-project")

                assert client is mock_client

    def test_client_class_available(self):
        """Test that bigquery.Client is re-exported for backward compatibility."""
        from shared.clients.bigquery_pool import Client

        assert Client is bigquery.Client


class TestBigQueryClientPerformance:
    """Test performance characteristics of client pool."""

    @pytest.fixture(autouse=True)
    def cleanup_cache(self):
        """Clear client cache before and after each test."""
        from shared.clients import bigquery_pool
        bigquery_pool.clear_cache()
        yield
        bigquery_pool.clear_cache()

    def test_cached_client_faster_than_new_client(self):
        """Test that cached client retrieval is faster than creation."""
        mock_client = Mock(spec=bigquery.Client)

        def slow_create(*args, **kwargs):
            time.sleep(0.05)  # Simulate slow client creation
            return mock_client

        with patch('shared.clients.bigquery_pool.bigquery.Client', side_effect=slow_create):
            with patch('shared.clients.bigquery_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.bigquery_pool import get_bigquery_client

                # First call - slow
                start = time.time()
                client1 = get_bigquery_client()
                first_call_time = time.time() - start

                # Second call - fast (cached)
                start = time.time()
                client2 = get_bigquery_client()
                second_call_time = time.time() - start

                assert client1 is client2
                # Cached call should be at least 10x faster
                assert second_call_time < first_call_time / 10


class TestBigQueryClientIntegration:
    """Test integration with shared.clients module."""

    def test_import_from_shared_clients(self):
        """Test that client can be imported from shared.clients."""
        from shared.clients import get_bigquery_client

        assert callable(get_bigquery_client)

    def test_import_close_function(self):
        """Test that close function can be imported."""
        from shared.clients import close_all_bigquery_clients

        assert callable(close_all_bigquery_clients)

    def test_import_count_function(self):
        """Test that count function can be imported."""
        from shared.clients import get_bigquery_client_count

        assert callable(get_bigquery_client_count)
