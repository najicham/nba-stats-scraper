"""
Unit tests for Pub/Sub Client Pool

Tests the connection pooling, topic/subscription creation, message publishing,
and error handling for Pub/Sub clients.

Usage:
    pytest tests/unit/clients/test_pubsub_client.py -v
"""

import pytest
import threading
import time
from unittest.mock import Mock, patch, MagicMock
from google.cloud import pubsub_v1


class TestPubSubPublisherPool:
    """Test Pub/Sub publisher client connection pooling."""

    @pytest.fixture(autouse=True)
    def cleanup_cache(self):
        """Clear client cache before and after each test."""
        from shared.clients import pubsub_pool
        pubsub_pool.clear_cache()
        yield
        pubsub_pool.clear_cache()

    @pytest.fixture
    def mock_publisher_client(self):
        """Create mock Pub/Sub publisher client."""
        mock_client = Mock(spec=pubsub_v1.PublisherClient)
        mock_client.topic_path = Mock(return_value="projects/test-project/topics/test-topic")
        mock_client.publish = Mock(return_value=MagicMock())
        mock_client.stop = Mock()
        return mock_client

    def test_get_pubsub_publisher_creates_new_client(self, mock_publisher_client):
        """Test that first call creates a new publisher client."""
        with patch('shared.clients.pubsub_pool.pubsub_v1.PublisherClient', return_value=mock_publisher_client):
            with patch('shared.clients.pubsub_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.pubsub_pool import get_pubsub_publisher, get_publisher_count

                assert get_publisher_count() == 0

                publisher = get_pubsub_publisher()

                assert publisher is mock_publisher_client
                assert get_publisher_count() == 1

    def test_get_pubsub_publisher_returns_cached_client(self, mock_publisher_client):
        """Test that subsequent calls return the same cached publisher."""
        with patch('shared.clients.pubsub_pool.pubsub_v1.PublisherClient', return_value=mock_publisher_client):
            with patch('shared.clients.pubsub_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.pubsub_pool import get_pubsub_publisher

                publisher1 = get_pubsub_publisher()
                publisher2 = get_pubsub_publisher()

                assert publisher1 is publisher2
                assert publisher1 is mock_publisher_client

    def test_get_pubsub_publisher_with_project_id(self, mock_publisher_client):
        """Test creating publisher with explicit project ID."""
        with patch('shared.clients.pubsub_pool.pubsub_v1.PublisherClient', return_value=mock_publisher_client) as mock_constructor:
            from shared.clients.pubsub_pool import get_pubsub_publisher

            publisher = get_pubsub_publisher(project_id="custom-project")

            mock_constructor.assert_called_once()
            assert publisher is mock_publisher_client

    def test_get_pubsub_publisher_caches_per_project(self):
        """Test that different projects get different cached publishers."""
        mock_client1 = Mock(spec=pubsub_v1.PublisherClient)
        mock_client2 = Mock(spec=pubsub_v1.PublisherClient)

        with patch('shared.clients.pubsub_pool.pubsub_v1.PublisherClient', side_effect=[mock_client1, mock_client2]):
            from shared.clients.pubsub_pool import get_pubsub_publisher, get_publisher_count

            publisher1 = get_pubsub_publisher(project_id="project-1")
            publisher2 = get_pubsub_publisher(project_id="project-2")
            publisher1_again = get_pubsub_publisher(project_id="project-1")

            assert publisher1 is mock_client1
            assert publisher2 is mock_client2
            assert publisher1_again is mock_client1
            assert get_publisher_count() == 2

    def test_publish_message(self, mock_publisher_client):
        """Test publishing a message with cached client."""
        future_mock = MagicMock()
        future_mock.result.return_value = "message-id-123"
        mock_publisher_client.publish.return_value = future_mock

        with patch('shared.clients.pubsub_pool.pubsub_v1.PublisherClient', return_value=mock_publisher_client):
            with patch('shared.clients.pubsub_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.pubsub_pool import get_pubsub_publisher

                publisher = get_pubsub_publisher()
                topic_path = publisher.topic_path("test-project", "test-topic")
                future = publisher.publish(topic_path, data=b"test message")
                message_id = future.result()

                assert message_id == "message-id-123"
                mock_publisher_client.publish.assert_called_once_with(
                    topic_path,
                    data=b"test message"
                )


class TestPubSubSubscriberPool:
    """Test Pub/Sub subscriber client connection pooling."""

    @pytest.fixture(autouse=True)
    def cleanup_cache(self):
        """Clear client cache before and after each test."""
        from shared.clients import pubsub_pool
        pubsub_pool.clear_cache()
        yield
        pubsub_pool.clear_cache()

    @pytest.fixture
    def mock_subscriber_client(self):
        """Create mock Pub/Sub subscriber client."""
        mock_client = Mock(spec=pubsub_v1.SubscriberClient)
        mock_client.subscription_path = Mock(return_value="projects/test-project/subscriptions/test-sub")
        mock_client.pull = Mock()
        mock_client.close = Mock()
        return mock_client

    def test_get_pubsub_subscriber_creates_new_client(self, mock_subscriber_client):
        """Test that first call creates a new subscriber client."""
        with patch('shared.clients.pubsub_pool.pubsub_v1.SubscriberClient', return_value=mock_subscriber_client):
            with patch('shared.clients.pubsub_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.pubsub_pool import get_pubsub_subscriber, get_subscriber_count

                assert get_subscriber_count() == 0

                subscriber = get_pubsub_subscriber()

                assert subscriber is mock_subscriber_client
                assert get_subscriber_count() == 1

    def test_get_pubsub_subscriber_returns_cached_client(self, mock_subscriber_client):
        """Test that subsequent calls return the same cached subscriber."""
        with patch('shared.clients.pubsub_pool.pubsub_v1.SubscriberClient', return_value=mock_subscriber_client):
            with patch('shared.clients.pubsub_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.pubsub_pool import get_pubsub_subscriber

                subscriber1 = get_pubsub_subscriber()
                subscriber2 = get_pubsub_subscriber()

                assert subscriber1 is subscriber2
                assert subscriber1 is mock_subscriber_client

    def test_get_pubsub_subscriber_caches_per_project(self):
        """Test that different projects get different cached subscribers."""
        mock_client1 = Mock(spec=pubsub_v1.SubscriberClient)
        mock_client2 = Mock(spec=pubsub_v1.SubscriberClient)

        with patch('shared.clients.pubsub_pool.pubsub_v1.SubscriberClient', side_effect=[mock_client1, mock_client2]):
            from shared.clients.pubsub_pool import get_pubsub_subscriber, get_subscriber_count

            subscriber1 = get_pubsub_subscriber(project_id="project-1")
            subscriber2 = get_pubsub_subscriber(project_id="project-2")
            subscriber1_again = get_pubsub_subscriber(project_id="project-1")

            assert subscriber1 is mock_client1
            assert subscriber2 is mock_client2
            assert subscriber1_again is mock_client1
            assert get_subscriber_count() == 2


class TestPubSubClientCleanup:
    """Test cleanup of Pub/Sub clients."""

    @pytest.fixture(autouse=True)
    def cleanup_cache(self):
        """Clear client cache before and after each test."""
        from shared.clients import pubsub_pool
        pubsub_pool.clear_cache()
        yield
        pubsub_pool.clear_cache()

    def test_close_all_clients(self):
        """Test closing all cached clients."""
        mock_publisher = Mock(spec=pubsub_v1.PublisherClient)
        mock_publisher.stop = Mock()
        mock_subscriber = Mock(spec=pubsub_v1.SubscriberClient)
        mock_subscriber.close = Mock()

        with patch('shared.clients.pubsub_pool.pubsub_v1.PublisherClient', return_value=mock_publisher):
            with patch('shared.clients.pubsub_pool.pubsub_v1.SubscriberClient', return_value=mock_subscriber):
                with patch('shared.clients.pubsub_pool._get_default_project_id', return_value="test-project"):
                    from shared.clients.pubsub_pool import (
                        get_pubsub_publisher,
                        get_pubsub_subscriber,
                        close_all_clients,
                        get_publisher_count,
                        get_subscriber_count
                    )

                    publisher = get_pubsub_publisher()
                    subscriber = get_pubsub_subscriber()

                    assert get_publisher_count() == 1
                    assert get_subscriber_count() == 1

                    close_all_clients()

                    assert get_publisher_count() == 0
                    assert get_subscriber_count() == 0
                    mock_subscriber.close.assert_called_once()

    def test_close_all_clients_handles_errors(self):
        """Test that close_all_clients handles errors gracefully."""
        mock_publisher = Mock(spec=pubsub_v1.PublisherClient)
        mock_publisher.stop = Mock(side_effect=Exception("Stop error"))
        mock_subscriber = Mock(spec=pubsub_v1.SubscriberClient)
        mock_subscriber.close = Mock(side_effect=Exception("Close error"))

        with patch('shared.clients.pubsub_pool.pubsub_v1.PublisherClient', return_value=mock_publisher):
            with patch('shared.clients.pubsub_pool.pubsub_v1.SubscriberClient', return_value=mock_subscriber):
                with patch('shared.clients.pubsub_pool._get_default_project_id', return_value="test-project"):
                    from shared.clients.pubsub_pool import (
                        get_pubsub_publisher,
                        get_pubsub_subscriber,
                        close_all_clients,
                        get_publisher_count,
                        get_subscriber_count
                    )

                    publisher = get_pubsub_publisher()
                    subscriber = get_pubsub_subscriber()

                    # Should not raise exception
                    close_all_clients()

                    assert get_publisher_count() == 0
                    assert get_subscriber_count() == 0


class TestPubSubThreadSafety:
    """Test thread safety of Pub/Sub client pools."""

    @pytest.fixture(autouse=True)
    def cleanup_cache(self):
        """Clear client cache before and after each test."""
        from shared.clients import pubsub_pool
        pubsub_pool.clear_cache()
        yield
        pubsub_pool.clear_cache()

    def test_get_pubsub_publisher_thread_safe(self):
        """Test that concurrent calls create only one publisher."""
        mock_publisher = Mock(spec=pubsub_v1.PublisherClient)
        creation_count = {"count": 0}
        lock = threading.Lock()

        def create_publisher_with_delay(*args, **kwargs):
            """Create publisher with artificial delay to simulate race condition."""
            with lock:
                creation_count["count"] += 1
            time.sleep(0.01)
            return mock_publisher

        with patch('shared.clients.pubsub_pool.pubsub_v1.PublisherClient', side_effect=create_publisher_with_delay):
            with patch('shared.clients.pubsub_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.pubsub_pool import get_pubsub_publisher

                threads = []
                results = []

                def get_publisher():
                    results.append(get_pubsub_publisher())

                for _ in range(10):
                    t = threading.Thread(target=get_publisher)
                    threads.append(t)
                    t.start()

                for t in threads:
                    t.join()

                # Only one publisher should have been created
                assert creation_count["count"] == 1

                # All threads should have received the same publisher
                assert len(results) == 10
                assert all(p is mock_publisher for p in results)

    def test_get_pubsub_subscriber_thread_safe(self):
        """Test that concurrent calls create only one subscriber."""
        mock_subscriber = Mock(spec=pubsub_v1.SubscriberClient)
        creation_count = {"count": 0}
        lock = threading.Lock()

        def create_subscriber_with_delay(*args, **kwargs):
            """Create subscriber with artificial delay to simulate race condition."""
            with lock:
                creation_count["count"] += 1
            time.sleep(0.01)
            return mock_subscriber

        with patch('shared.clients.pubsub_pool.pubsub_v1.SubscriberClient', side_effect=create_subscriber_with_delay):
            with patch('shared.clients.pubsub_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.pubsub_pool import get_pubsub_subscriber

                threads = []
                results = []

                def get_subscriber():
                    results.append(get_pubsub_subscriber())

                for _ in range(10):
                    t = threading.Thread(target=get_subscriber)
                    threads.append(t)
                    t.start()

                for t in threads:
                    t.join()

                # Only one subscriber should have been created
                assert creation_count["count"] == 1

                # All threads should have received the same subscriber
                assert len(results) == 10
                assert all(s is mock_subscriber for s in results)


class TestPubSubBackwardCompatibility:
    """Test backward compatibility features."""

    def test_publisher_client_class_available(self):
        """Test that PublisherClient is re-exported for backward compatibility."""
        from shared.clients.pubsub_pool import PublisherClient

        assert PublisherClient is pubsub_v1.PublisherClient

    def test_subscriber_client_class_available(self):
        """Test that SubscriberClient is re-exported for backward compatibility."""
        from shared.clients.pubsub_pool import SubscriberClient

        assert SubscriberClient is pubsub_v1.SubscriberClient


class TestPubSubIntegration:
    """Test integration with shared.clients module."""

    def test_import_from_shared_clients(self):
        """Test that clients can be imported from shared.clients."""
        from shared.clients import get_pubsub_publisher, get_pubsub_subscriber

        assert callable(get_pubsub_publisher)
        assert callable(get_pubsub_subscriber)

    def test_import_close_function(self):
        """Test that close function can be imported."""
        from shared.clients import close_all_pubsub_clients

        assert callable(close_all_pubsub_clients)

    def test_import_count_functions(self):
        """Test that count functions can be imported."""
        from shared.clients import get_pubsub_publisher_count, get_pubsub_subscriber_count

        assert callable(get_pubsub_publisher_count)
        assert callable(get_pubsub_subscriber_count)


class TestPubSubErrorHandling:
    """Test error handling in Pub/Sub operations."""

    @pytest.fixture(autouse=True)
    def cleanup_cache(self):
        """Clear client cache before and after each test."""
        from shared.clients import pubsub_pool
        pubsub_pool.clear_cache()
        yield
        pubsub_pool.clear_cache()

    def test_publish_error_handling(self):
        """Test that publishing errors are properly propagated."""
        mock_publisher = Mock(spec=pubsub_v1.PublisherClient)
        mock_publisher.topic_path = Mock(return_value="projects/test-project/topics/test-topic")
        mock_publisher.publish = Mock(side_effect=Exception("Publish failed"))

        with patch('shared.clients.pubsub_pool.pubsub_v1.PublisherClient', return_value=mock_publisher):
            with patch('shared.clients.pubsub_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.pubsub_pool import get_pubsub_publisher

                publisher = get_pubsub_publisher()
                topic_path = publisher.topic_path("test-project", "test-topic")

                with pytest.raises(Exception, match="Publish failed"):
                    publisher.publish(topic_path, data=b"test")

    def test_topic_path_formation(self):
        """Test that topic paths are correctly formed."""
        mock_publisher = Mock(spec=pubsub_v1.PublisherClient)
        mock_publisher.topic_path = pubsub_v1.PublisherClient.topic_path

        with patch('shared.clients.pubsub_pool.pubsub_v1.PublisherClient', return_value=mock_publisher):
            with patch('shared.clients.pubsub_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.pubsub_pool import get_pubsub_publisher

                publisher = get_pubsub_publisher()
                topic_path = publisher.topic_path("my-project", "my-topic")

                assert topic_path == "projects/my-project/topics/my-topic"

    def test_subscription_path_formation(self):
        """Test that subscription paths are correctly formed."""
        mock_subscriber = Mock(spec=pubsub_v1.SubscriberClient)
        mock_subscriber.subscription_path = pubsub_v1.SubscriberClient.subscription_path

        with patch('shared.clients.pubsub_pool.pubsub_v1.SubscriberClient', return_value=mock_subscriber):
            with patch('shared.clients.pubsub_pool._get_default_project_id', return_value="test-project"):
                from shared.clients.pubsub_pool import get_pubsub_subscriber

                subscriber = get_pubsub_subscriber()
                sub_path = subscriber.subscription_path("my-project", "my-subscription")

                assert sub_path == "projects/my-project/subscriptions/my-subscription"
