"""
Test suite for BatchStateManager dual-write atomicity fix

Critical P0 Test: Verify transactional dual-write prevents data corruption

This test validates that the dual-write fix correctly uses Firestore transactions
to ensure both array write and subcollection write happen atomically.

Author: Claude Code
Date: January 25, 2026
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


class TestDualWriteAtomicityIntegration:
    """
    Integration test for dual-write atomicity

    Tests the actual code execution path with minimal mocking
    to verify the transaction is used correctly.
    """

    @patch('predictions.coordinator.batch_state_manager._get_firestore')
    @patch('predictions.coordinator.batch_state_manager._get_firestore_helpers')
    def test_dual_write_creates_transaction(self, mock_helpers, mock_get_firestore):
        """
        CRITICAL: Verify that dual-write mode creates and uses a transaction

        This is the core fix - the transaction ensures both writes happen atomically.
        """
        # Import here to avoid module-level import issues
        import sys
        import os

        # Add path for imports
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

        # Mock Firestore module
        mock_firestore_module = Mock()
        mock_get_firestore.return_value = mock_firestore_module

        # Mock helpers
        mock_array_union = Mock()
        mock_increment = Mock()
        mock_server_timestamp = Mock()
        mock_helpers.return_value = (mock_array_union, mock_increment, mock_server_timestamp)

        # Track transaction usage
        transaction_used = {'value': False}

        def transactional_decorator(func):
            """Mock @firestore.transactional decorator"""
            def wrapper(transaction):
                transaction_used['value'] = True
                return func(transaction)
            return wrapper

        mock_firestore_module.transactional = transactional_decorator

        # Mock Firestore client
        mock_client = Mock()
        mock_transaction = Mock()
        mock_client.transaction.return_value = mock_transaction

        # Mock document references
        mock_doc_ref = Mock()
        mock_completion_ref = Mock()
        mock_collection_ref = Mock()
        mock_collection_ref.document.return_value = mock_completion_ref
        mock_doc_ref.collection.return_value = mock_collection_ref

        mock_collection = Mock()
        mock_collection.document.return_value = mock_doc_ref
        mock_client.collection.return_value = mock_collection

        # Mock document read (for batch completion check)
        mock_snapshot = Mock()
        mock_snapshot.exists = True
        mock_snapshot.to_dict.return_value = {
            'expected_players': 10,
            'completed_players': ['player-1'],
            'completed_count': 1
        }
        mock_doc_ref.get.return_value = mock_snapshot

        # Create manager with mocked client
        with patch('shared.clients.get_firestore_client') as mock_get_client:
            mock_get_client.return_value = mock_client

            # Set environment variables for dual-write mode
            os.environ['ENABLE_SUBCOLLECTION_COMPLETIONS'] = 'true'
            os.environ['DUAL_WRITE_MODE'] = 'true'
            os.environ['USE_SUBCOLLECTION_READS'] = 'false'

            from predictions.coordinator.batch_state_manager import BatchStateManager

            manager = BatchStateManager(project_id='test-project')

            # Execute dual-write
            manager.record_completion(
                batch_id='test-batch',
                player_lookup='player-1',
                predictions_count=5
            )

            # CRITICAL ASSERTION: Transaction must be used
            assert transaction_used['value'], \
                "Dual-write MUST use transaction to prevent data corruption!"

            # Verify transaction was created
            mock_client.transaction.assert_called()

    @patch('predictions.coordinator.batch_state_manager._get_firestore')
    @patch('predictions.coordinator.batch_state_manager._get_firestore_helpers')
    def test_dual_write_calls_transaction_update_and_set(
        self,
        mock_helpers,
        mock_get_firestore
    ):
        """
        Verify transaction.update() and transaction.set() are called

        Both array write (update) and subcollection write (set) must happen
        within the transaction.
        """
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

        # Mock Firestore module
        mock_firestore_module = Mock()
        mock_get_firestore.return_value = mock_firestore_module

        # Mock helpers
        mock_array_union = Mock()
        mock_increment = Mock()
        mock_server_timestamp = Mock()
        mock_helpers.return_value = (mock_array_union, mock_increment, mock_server_timestamp)

        # Track transaction calls
        transaction_calls = {
            'update': [],
            'set': []
        }

        def transactional_decorator(func):
            """Mock @firestore.transactional decorator"""
            def wrapper(transaction):
                # Execute the function with our mock transaction
                return func(transaction)
            return wrapper

        mock_firestore_module.transactional = transactional_decorator

        # Mock Firestore client
        mock_client = Mock()
        mock_transaction = Mock()

        # Track transaction.update() calls
        def track_update(*args, **kwargs):
            transaction_calls['update'].append((args, kwargs))

        # Track transaction.set() calls
        def track_set(*args, **kwargs):
            transaction_calls['set'].append((args, kwargs))

        mock_transaction.update.side_effect = track_update
        mock_transaction.set.side_effect = track_set

        mock_client.transaction.return_value = mock_transaction

        # Mock document references
        mock_doc_ref = Mock()
        mock_completion_ref = Mock()
        mock_collection_ref = Mock()
        mock_collection_ref.document.return_value = mock_completion_ref
        mock_doc_ref.collection.return_value = mock_collection_ref

        mock_collection = Mock()
        mock_collection.document.return_value = mock_doc_ref
        mock_client.collection.return_value = mock_collection

        # Mock document read
        mock_snapshot = Mock()
        mock_snapshot.exists = True
        mock_snapshot.to_dict.return_value = {
            'expected_players': 10,
            'completed_players': ['player-1'],
            'completed_count': 1
        }
        mock_doc_ref.get.return_value = mock_snapshot

        # Create manager
        with patch('shared.clients.get_firestore_client') as mock_get_client:
            mock_get_client.return_value = mock_client

            import os
            os.environ['ENABLE_SUBCOLLECTION_COMPLETIONS'] = 'true'
            os.environ['DUAL_WRITE_MODE'] = 'true'
            os.environ['USE_SUBCOLLECTION_READS'] = 'false'

            from predictions.coordinator.batch_state_manager import BatchStateManager

            manager = BatchStateManager(project_id='test-project')

            # Execute dual-write
            manager.record_completion(
                batch_id='test-batch',
                player_lookup='player-1',
                predictions_count=5
            )

            # CRITICAL ASSERTIONS:
            # 1. transaction.update() must be called (for array write and counters)
            assert len(transaction_calls['update']) > 0, \
                "transaction.update() must be called for array write!"

            # 2. transaction.set() must be called (for subcollection write)
            assert len(transaction_calls['set']) > 0, \
                "transaction.set() must be called for subcollection write!"

            print(f"✓ Transaction calls verified:")
            print(f"  - update() called {len(transaction_calls['update'])} times")
            print(f"  - set() called {len(transaction_calls['set'])} times")


class TestCodeAnalysis:
    """
    Static code analysis tests

    These tests examine the code structure to verify the fix is implemented correctly.
    """

    def test_dual_write_method_exists(self):
        """Verify the new transactional dual-write method exists"""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

        from predictions.coordinator.batch_state_manager import BatchStateManager

        # Verify the new transactional method exists
        assert hasattr(BatchStateManager, '_record_completion_dual_write_transactional'), \
            "Missing _record_completion_dual_write_transactional method!"

        # Get the method
        method = getattr(BatchStateManager, '_record_completion_dual_write_transactional')

        # Verify it's a callable method
        assert callable(method), \
            "_record_completion_dual_write_transactional must be callable!"

    def test_dual_write_method_signature(self):
        """Verify the transactional dual-write method has correct signature"""
        import sys
        import os
        import inspect
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

        from predictions.coordinator.batch_state_manager import BatchStateManager

        method = getattr(BatchStateManager, '_record_completion_dual_write_transactional')

        # Get method signature
        sig = inspect.signature(method)
        params = list(sig.parameters.keys())

        # Verify required parameters
        assert 'self' in params, "Method must have 'self' parameter"
        assert 'batch_id' in params, "Method must have 'batch_id' parameter"
        assert 'player_lookup' in params, "Method must have 'player_lookup' parameter"
        assert 'predictions_count' in params, "Method must have 'predictions_count' parameter"

    def test_record_completion_calls_transactional_method(self):
        """Verify record_completion calls the transactional dual-write method"""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

        # Read the source code
        import inspect
        from predictions.coordinator.batch_state_manager import BatchStateManager

        # Get source code of record_completion
        source = inspect.getsource(BatchStateManager.record_completion)

        # Verify it calls the transactional method in dual-write mode
        assert '_record_completion_dual_write_transactional' in source, \
            "record_completion must call _record_completion_dual_write_transactional in dual-write mode!"

        print("✓ record_completion correctly calls transactional dual-write method")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
