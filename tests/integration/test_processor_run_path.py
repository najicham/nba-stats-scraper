"""
Integration tests for processor.run() path.

These tests ensure that:
1. All processors follow the ProcessorBase contract (transform_data takes no args)
2. The run() path works correctly (not just process_file())
3. ProcessorBase correctly orchestrates the processor lifecycle

This was added after the 2025-12-24 email flood incident where
NbacScheduleProcessor.transform_data() had wrong signature and
caused 600+ error emails.
"""

import inspect
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import json


class TestProcessorContractValidation:
    """
    Test that all processors follow the ProcessorBase contract.
    
    The contract requires:
    - transform_data() takes NO arguments (uses self.raw_data, self.opts)
    - transform_data() sets self.transformed_data
    - transform_data() returns None (not a value)
    """
    
    def get_all_processor_classes(self):
        """Dynamically import all processor classes from the registry."""
        from data_processors.raw.main_processor_service import PROCESSOR_REGISTRY
        return list(PROCESSOR_REGISTRY.values())
    
    def test_transform_data_signature_no_arguments(self):
        """
        CRITICAL: transform_data() must take no arguments besides self.
        
        This test would have caught the 2025-12-24 bug where
        NbacScheduleProcessor.transform_data(self, raw_data, file_path)
        had extra arguments that ProcessorBase.run() doesn't pass.
        """
        processor_classes = self.get_all_processor_classes()
        
        failures = []
        for processor_class in processor_classes:
            method = getattr(processor_class, 'transform_data', None)
            if method is None:
                continue
                
            sig = inspect.signature(method)
            params = list(sig.parameters.keys())
            
            # Should only have 'self' parameter
            if params != ['self']:
                failures.append(
                    f"{processor_class.__name__}.transform_data() has params {params}, "
                    f"expected only ['self']"
                )
        
        if failures:
            pytest.fail(
                f"Processors with wrong transform_data() signature:\n" +
                "\n".join(f"  - {f}" for f in failures)
            )
    
    def test_load_data_signature_no_arguments(self):
        """load_data() must take no arguments besides self."""
        processor_classes = self.get_all_processor_classes()
        
        failures = []
        for processor_class in processor_classes:
            method = getattr(processor_class, 'load_data', None)
            if method is None:
                continue
                
            sig = inspect.signature(method)
            params = list(sig.parameters.keys())
            
            if params != ['self']:
                failures.append(
                    f"{processor_class.__name__}.load_data() has params {params}, "
                    f"expected only ['self']"
                )
        
        if failures:
            pytest.fail(
                f"Processors with wrong load_data() signature:\n" +
                "\n".join(f"  - {f}" for f in failures)
            )


class TestProcessorRunPath:
    """
    Test that processor.run(opts) works correctly.
    
    The run() path is used by main_processor_service when handling
    Pub/Sub messages. This is different from process_file() which
    is used by backfills.
    """
    
    @pytest.fixture
    def mock_gcs_client(self):
        """Mock GCS client that returns test data."""
        with patch('google.cloud.storage.Client') as mock:
            # Setup mock bucket and blob
            mock_bucket = MagicMock()
            mock_blob = MagicMock()
            mock_blob.exists.return_value = True
            mock_blob.download_as_string.return_value = json.dumps({
                "test": "data",
                "games": [{"game_id": "001", "status": "Final"}]
            }).encode()
            mock_bucket.blob.return_value = mock_blob
            mock.return_value.bucket.return_value = mock_bucket
            yield mock
    
    @pytest.fixture
    def mock_bq_client(self):
        """Mock BigQuery client."""
        with patch('google.cloud.bigquery.Client') as mock:
            # Mock table schema
            mock_table = MagicMock()
            mock_table.schema = []
            mock.return_value.get_table.return_value = mock_table
            
            # Mock load job
            mock_job = MagicMock()
            mock_job.result.return_value = None
            mock.return_value.load_table_from_file.return_value = mock_job
            
            yield mock
    
    @pytest.fixture
    def mock_pubsub(self):
        """Mock Pub/Sub publisher."""
        with patch('google.cloud.pubsub_v1.PublisherClient') as mock:
            mock.return_value.publish.return_value.result.return_value = 'msg-123'
            yield mock
    
    def test_run_calls_transform_data_without_arguments(
        self, mock_gcs_client, mock_bq_client, mock_pubsub
    ):
        """
        Verify that ProcessorBase.run() calls transform_data() without arguments.
        
        This is the core test that would have caught the 2025-12-24 bug.
        """
        from data_processors.raw.processor_base import ProcessorBase
        
        # Create a test processor that tracks how transform_data was called
        class TestProcessor(ProcessorBase):
            table_name = "test_table"
            transform_data_called_with_args = None
            
            def load_data(self):
                self.raw_data = {"test": "data"}
            
            def transform_data(self):
                # Record that we were called correctly (no args)
                self.transform_data_called_with_args = True
                self.transformed_data = [{"row": 1}]
        
        processor = TestProcessor()
        
        # Mock the run history methods
        with patch.object(processor, 'check_already_processed', return_value=False):
            with patch.object(processor, 'start_run_tracking'):
                with patch.object(processor, 'record_run_complete'):
                    with patch.object(processor, '_publish_completion_event'):
                        result = processor.run({
                            'bucket': 'test-bucket',
                            'file_path': 'test/path.json'
                        })
        
        assert result is True, "Processor should complete successfully"
        assert processor.transform_data_called_with_args is True, \
            "transform_data() should have been called"
        assert processor.transformed_data == [{"row": 1}], \
            "transformed_data should be set"
    
    def test_run_fails_if_transform_data_requires_arguments(self):
        """
        Verify that a processor with wrong signature fails during run().
        
        This simulates the 2025-12-24 bug.
        """
        from data_processors.raw.processor_base import ProcessorBase
        
        # Create a BROKEN processor (wrong signature)
        class BrokenProcessor(ProcessorBase):
            table_name = "test_table"
            
            def load_data(self):
                self.raw_data = {"test": "data"}
            
            def transform_data(self, raw_data, file_path):  # WRONG! Takes args
                self.transformed_data = [{"row": 1}]
        
        processor = BrokenProcessor()
        
        # This should fail because ProcessorBase calls transform_data()
        # without arguments
        with patch.object(processor, 'check_already_processed', return_value=False):
            with patch.object(processor, 'start_run_tracking'):
                with patch.object(processor, 'record_run_complete'):
                    result = processor.run({
                        'bucket': 'test-bucket',
                        'file_path': 'test/path.json'
                    })
        
        # Should fail (return False) due to TypeError
        assert result is False, \
            "Processor with wrong transform_data signature should fail"


class TestScheduleProcessorIntegration:
    """
    Specific tests for NbacScheduleProcessor after the 2025-12-24 fix.
    """
    
    def test_schedule_processor_transform_data_signature(self):
        """Verify NbacScheduleProcessor.transform_data() has correct signature."""
        from data_processors.raw.nbacom.nbac_schedule_processor import NbacScheduleProcessor
        
        sig = inspect.signature(NbacScheduleProcessor.transform_data)
        params = list(sig.parameters.keys())
        
        assert params == ['self'], \
            f"NbacScheduleProcessor.transform_data() should only have 'self' parameter, got {params}"
    
    def test_schedule_processor_uses_self_raw_data(self):
        """Verify transform_data uses self.raw_data, not arguments."""
        from data_processors.raw.nbacom.nbac_schedule_processor import NbacScheduleProcessor
        
        # Get source code of transform_data
        source = inspect.getsource(NbacScheduleProcessor.transform_data)
        
        # Should reference self.raw_data
        assert 'self.raw_data' in source or 'raw_data = self.raw_data' in source, \
            "transform_data should use self.raw_data"
        
        # Should reference self.opts for file_path
        assert "self.opts" in source, \
            "transform_data should use self.opts for file_path"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
