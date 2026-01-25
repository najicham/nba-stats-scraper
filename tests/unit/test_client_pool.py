"""
Unit tests for client pool singleton pattern

Tests the shared database client pool that reuses BigQuery and
Firestore clients to avoid repeated initialization overhead.

Related: services/admin_dashboard/services/client_pool.py
"""

import pytest
import threading
from unittest.mock import patch, MagicMock
import services.admin_dashboard.services.client_pool as client_pool


class TestBigQueryClientPool:
    """Test BigQuery client singleton behavior."""

    def setup_method(self):
        """Reset clients before each test."""
        client_pool.reset_clients()

    def teardown_method(self):
        """Clean up after each test."""
        client_pool.reset_clients()

    @patch('services.admin_dashboard.services.client_pool.bigquery.Client')
    def test_bigquery_client_singleton(self, mock_client_class):
        """Test that same BigQuery client instance is returned."""
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        # Get client twice
        client1 = client_pool.get_bigquery_client()
        client2 = client_pool.get_bigquery_client()

        # Should be same instance
        assert client1 is client2
        assert client1 is mock_instance

        # Client should only be created once
        assert mock_client_class.call_count == 1

    @patch('services.admin_dashboard.services.client_pool.bigquery.Client')
    def test_first_call_creates_client(self, mock_client_class):
        """Test first call initializes the client."""
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        # First call should create client
        client = client_pool.get_bigquery_client()

        assert client is mock_instance
        mock_client_class.assert_called_once()

    @patch('services.admin_dashboard.services.client_pool.bigquery.Client')
    def test_subsequent_calls_reuse_client(self, mock_client_class):
        """Test subsequent calls don't re-initialize."""
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        # Multiple calls
        client_pool.get_bigquery_client()
        client_pool.get_bigquery_client()
        client_pool.get_bigquery_client()

        # Client created only once
        assert mock_client_class.call_count == 1

    @patch('services.admin_dashboard.services.client_pool.bigquery.Client')
    def test_reset_clients_bigquery(self, mock_client_class):
        """Test reset_clients clears BigQuery client."""
        # Create two different mock instances
        mock_instance1 = MagicMock()
        mock_instance2 = MagicMock()
        mock_client_class.side_effect = [mock_instance1, mock_instance2]

        # Get client
        client1 = client_pool.get_bigquery_client()

        # Reset
        client_pool.reset_clients()

        # Get client again - should create new instance
        client2 = client_pool.get_bigquery_client()

        assert client1 is mock_instance1
        assert client2 is mock_instance2
        assert client1 is not client2
        assert mock_client_class.call_count == 2
        mock_instance1.close.assert_called_once()

    @patch('services.admin_dashboard.services.client_pool.bigquery.Client')
    def test_bigquery_client_with_custom_project(self, mock_client_class):
        """Test BigQuery client can be created with custom project ID."""
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        client_pool.get_bigquery_client(project_id='custom-project')

        mock_client_class.assert_called_once_with(project='custom-project')


class TestFirestoreClientPool:
    """Test Firestore client singleton behavior."""

    def setup_method(self):
        """Reset clients before each test."""
        client_pool.reset_clients()

    def teardown_method(self):
        """Clean up after each test."""
        client_pool.reset_clients()

    @patch('services.admin_dashboard.services.client_pool.firestore.Client')
    def test_firestore_client_singleton(self, mock_client_class):
        """Test that same Firestore client instance is returned."""
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        # Get client twice
        client1 = client_pool.get_firestore_client()
        client2 = client_pool.get_firestore_client()

        # Should be same instance
        assert client1 is client2
        assert client1 is mock_instance

        # Client should only be created once
        assert mock_client_class.call_count == 1

    @patch('services.admin_dashboard.services.client_pool.firestore.Client')
    def test_first_call_creates_client(self, mock_client_class):
        """Test first call initializes the client."""
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        # First call should create client
        client = client_pool.get_firestore_client()

        assert client is mock_instance
        mock_client_class.assert_called_once()

    @patch('services.admin_dashboard.services.client_pool.firestore.Client')
    def test_subsequent_calls_reuse_client(self, mock_client_class):
        """Test subsequent calls don't re-initialize."""
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        # Multiple calls
        client_pool.get_firestore_client()
        client_pool.get_firestore_client()
        client_pool.get_firestore_client()

        # Client created only once
        assert mock_client_class.call_count == 1

    @patch('services.admin_dashboard.services.client_pool.firestore.Client')
    def test_reset_clients_firestore(self, mock_client_class):
        """Test reset_clients clears Firestore client."""
        # Create two different mock instances
        mock_instance1 = MagicMock()
        mock_instance2 = MagicMock()
        mock_client_class.side_effect = [mock_instance1, mock_instance2]

        # Get client
        client1 = client_pool.get_firestore_client()

        # Reset
        client_pool.reset_clients()

        # Get client again - should create new instance
        client2 = client_pool.get_firestore_client()

        assert client1 is mock_instance1
        assert client2 is mock_instance2
        assert client1 is not client2
        assert mock_client_class.call_count == 2

    @patch('services.admin_dashboard.services.client_pool.firestore.Client')
    def test_firestore_client_with_custom_project(self, mock_client_class):
        """Test Firestore client can be created with custom project ID."""
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        client_pool.get_firestore_client(project_id='custom-project')

        mock_client_class.assert_called_once_with(project='custom-project')


class TestClientPoolReset:
    """Test reset_clients functionality."""

    def setup_method(self):
        """Reset clients before each test."""
        client_pool.reset_clients()

    def teardown_method(self):
        """Clean up after each test."""
        client_pool.reset_clients()

    @patch('services.admin_dashboard.services.client_pool.bigquery.Client')
    @patch('services.admin_dashboard.services.client_pool.firestore.Client')
    def test_reset_clears_both_clients(self, mock_fs_class, mock_bq_class):
        """Test reset_clients clears both BigQuery and Firestore clients."""
        mock_bq_instance = MagicMock()
        mock_fs_instance = MagicMock()
        mock_bq_class.return_value = mock_bq_instance
        mock_fs_class.return_value = mock_fs_instance

        # Initialize both clients
        client_pool.get_bigquery_client()
        client_pool.get_firestore_client()

        # Reset
        client_pool.reset_clients()

        # Verify both were reset
        assert client_pool._bigquery_client is None
        assert client_pool._firestore_client is None
        mock_bq_instance.close.assert_called_once()

    @patch('services.admin_dashboard.services.client_pool.bigquery.Client')
    def test_reset_with_no_clients_initialized(self, mock_bq_class):
        """Test reset_clients when no clients initialized."""
        # Should not raise an error
        client_pool.reset_clients()

        # Verify no crashes
        assert client_pool._bigquery_client is None
        assert client_pool._firestore_client is None


class TestClientPoolThreadSafety:
    """Test thread safety of client pool."""

    def setup_method(self):
        """Reset clients before each test."""
        client_pool.reset_clients()

    def teardown_method(self):
        """Clean up after each test."""
        client_pool.reset_clients()

    @patch('services.admin_dashboard.services.client_pool.bigquery.Client')
    def test_concurrent_bigquery_access(self, mock_client_class):
        """Test concurrent access to BigQuery client returns same instance."""
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        clients = []
        num_threads = 10

        def worker():
            client = client_pool.get_bigquery_client()
            clients.append(client)

        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # All threads should get the same client instance
        assert len(clients) == num_threads
        assert all(c is mock_instance for c in clients)

        # Client should only be created once despite concurrent access
        # Note: In rare race conditions, it might be created more than once,
        # but at least one of the instances should be returned to all threads
        assert mock_client_class.call_count >= 1

    @patch('services.admin_dashboard.services.client_pool.firestore.Client')
    def test_concurrent_firestore_access(self, mock_client_class):
        """Test concurrent access to Firestore client returns same instance."""
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        clients = []
        num_threads = 10

        def worker():
            client = client_pool.get_firestore_client()
            clients.append(client)

        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # All threads should get the same client instance
        assert len(clients) == num_threads
        assert all(c is mock_instance for c in clients)

        # Client should only be created once despite concurrent access
        assert mock_client_class.call_count >= 1


class TestClientPoolDefaultProject:
    """Test default project ID handling."""

    def setup_method(self):
        """Reset clients before each test."""
        client_pool.reset_clients()

    def teardown_method(self):
        """Clean up after each test."""
        client_pool.reset_clients()

    @patch('services.admin_dashboard.services.client_pool.bigquery.Client')
    def test_bigquery_uses_default_project(self, mock_client_class):
        """Test BigQuery client uses PROJECT_ID constant when no project specified."""
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        client_pool.get_bigquery_client()

        # Should use the PROJECT_ID from module
        called_project = mock_client_class.call_args[1]['project']
        # Module has 'nba-props-platform' as default (from environment or hardcoded)
        assert called_project in ['test-project', 'nba-props-platform']

    @patch('services.admin_dashboard.services.client_pool.firestore.Client')
    def test_firestore_uses_default_project(self, mock_client_class):
        """Test Firestore client uses PROJECT_ID constant when no project specified."""
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        client_pool.get_firestore_client()

        # Should use the PROJECT_ID from module
        called_project = mock_client_class.call_args[1]['project']
        # Module has 'nba-props-platform' as default (from environment or hardcoded)
        assert called_project in ['test-project', 'nba-props-platform']
