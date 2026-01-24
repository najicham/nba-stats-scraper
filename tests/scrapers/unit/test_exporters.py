"""
Unit tests for scrapers/exporters.py

Tests the exporter functionality including:
- BaseExporter interface
- GCSExporter
- FileExporter
- PrintExporter
- _prepare_data_for_export helper

Path: tests/scrapers/unit/test_exporters.py
Created: 2026-01-24
"""

import pytest
import json
import os
from unittest.mock import Mock, patch, MagicMock
from io import StringIO

from scrapers.exporters import (
    BaseExporter,
    GCSExporter,
    FileExporter,
    PrintExporter,
    EXPORTER_REGISTRY,
    _prepare_data_for_export,
)


# ============================================================================
# TEST _prepare_data_for_export HELPER
# ============================================================================

class TestPrepareDataForExport:
    """Test the _prepare_data_for_export helper function."""

    def test_binary_data_preserved(self):
        """Binary data should be returned as-is."""
        binary_data = b'\x00\x01\x02\x03PDF content here'
        payload, is_binary = _prepare_data_for_export(binary_data, {})

        assert payload == binary_data
        assert is_binary is True

    def test_dict_data_serialized(self):
        """Dict data should be JSON serialized."""
        dict_data = {"key": "value", "count": 42}
        payload, is_binary = _prepare_data_for_export(dict_data, {})

        assert is_binary is False
        assert json.loads(payload) == dict_data

    def test_list_data_serialized(self):
        """List data should be JSON serialized."""
        list_data = [1, 2, 3, {"nested": "value"}]
        payload, is_binary = _prepare_data_for_export(list_data, {})

        assert is_binary is False
        assert json.loads(payload) == list_data

    def test_string_data_preserved(self):
        """String data should be returned as string."""
        string_data = "raw text content"
        payload, is_binary = _prepare_data_for_export(string_data, {})

        assert payload == string_data
        assert is_binary is False

    def test_pretty_print_option(self):
        """Pretty print should add indentation."""
        dict_data = {"key": "value"}

        # Without pretty print
        payload_compact, _ = _prepare_data_for_export(dict_data, {})

        # With pretty print
        payload_pretty, _ = _prepare_data_for_export(dict_data, {"pretty_print": True})

        # Pretty print should have more characters (newlines, spaces)
        assert len(payload_pretty) > len(payload_compact)
        assert '\n' in payload_pretty


# ============================================================================
# TEST BASE EXPORTER
# ============================================================================

class TestBaseExporter:
    """Test the BaseExporter abstract class."""

    def test_run_not_implemented(self):
        """BaseExporter.run should raise NotImplementedError."""
        exporter = BaseExporter()

        with pytest.raises(NotImplementedError) as exc_info:
            exporter.run({}, {}, {})

        assert "must implement" in str(exc_info.value)


# ============================================================================
# TEST FILE EXPORTER
# ============================================================================

class TestFileExporter:
    """Test the FileExporter class."""

    def test_write_json_data(self, tmp_path):
        """Should write JSON data to file."""
        exporter = FileExporter()
        data = {"test": "data", "count": 123}
        config = {"filename": str(tmp_path / "output.json")}
        opts = {}

        exporter.run(data, config, opts)

        # Verify file was created and contains correct data
        with open(config["filename"], "r") as f:
            written_data = json.load(f)

        assert written_data == data

    def test_write_binary_data(self, tmp_path):
        """Should write binary data to file."""
        exporter = FileExporter()
        data = b'\x00\x01\x02PDF binary content'
        config = {"filename": str(tmp_path / "output.pdf")}
        opts = {}

        exporter.run(data, config, opts)

        # Verify file was created with binary content
        with open(config["filename"], "rb") as f:
            written_data = f.read()

        assert written_data == data

    def test_filename_interpolation(self, tmp_path):
        """Should interpolate opts into filename."""
        exporter = FileExporter()
        data = {"test": "data"}
        config = {"filename": str(tmp_path / "data_%(game_date)s.json")}
        opts = {"game_date": "2026-01-20"}

        exporter.run(data, config, opts)

        expected_file = tmp_path / "data_2026-01-20.json"
        assert expected_file.exists()

    def test_default_filename(self, tmp_path):
        """Should use default filename if not specified."""
        exporter = FileExporter()
        data = {"test": "data"}

        with patch('builtins.open', MagicMock()) as mock_open:
            mock_open.return_value.__enter__ = MagicMock()
            mock_open.return_value.__exit__ = MagicMock()

            exporter.run(data, {}, {})

            # Default filename should be /tmp/default.json
            mock_open.assert_called_once()
            call_args = mock_open.call_args[0]
            assert call_args[0] == "/tmp/default.json"


# ============================================================================
# TEST GCS EXPORTER
# ============================================================================

class TestGCSExporter:
    """Test the GCSExporter class."""

    @patch.object(GCSExporter, '_create_gcs_client')
    def test_upload_json_data(self, mock_create_client):
        """Should upload JSON data to GCS."""
        # Setup mocks
        mock_blob = Mock()
        mock_bucket = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = Mock()
        mock_client.bucket.return_value = mock_bucket
        mock_create_client.return_value = mock_client

        exporter = GCSExporter()
        data = {"test": "data"}
        config = {"bucket": "test-bucket", "key": "path/to/file.json"}
        opts = {}

        result = exporter.run(data, config, opts)

        # Verify upload was called
        mock_bucket.blob.assert_called_with("path/to/file.json")
        mock_blob.upload_from_string.assert_called_once()

        # Verify return value
        assert result["bucket"] == "test-bucket"
        assert result["path"] == "path/to/file.json"
        assert "gcs_path" in result

    @patch.object(GCSExporter, '_create_gcs_client')
    def test_upload_binary_data(self, mock_create_client):
        """Should upload binary data to GCS with correct content type."""
        mock_blob = Mock()
        mock_bucket = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = Mock()
        mock_client.bucket.return_value = mock_bucket
        mock_create_client.return_value = mock_client

        exporter = GCSExporter()
        data = b'%PDF-1.4 binary content'
        config = {"bucket": "test-bucket", "key": "path/to/file.pdf"}
        opts = {}

        exporter.run(data, config, opts)

        # Verify binary upload with PDF content type
        mock_blob.upload_from_string.assert_called_once()
        call_kwargs = mock_blob.upload_from_string.call_args[1]
        assert call_kwargs["content_type"] == "application/pdf"

    @patch.object(GCSExporter, '_create_gcs_client')
    def test_key_interpolation(self, mock_create_client):
        """Should interpolate opts into GCS key."""
        mock_blob = Mock()
        mock_bucket = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = Mock()
        mock_client.bucket.return_value = mock_bucket
        mock_create_client.return_value = mock_client

        exporter = GCSExporter()
        data = {"test": "data"}
        config = {
            "bucket": "test-bucket",
            "key": "games/%(game_date)s/data.json"
        }
        opts = {"game_date": "2026-01-20"}

        result = exporter.run(data, config, opts)

        assert result["path"] == "games/2026-01-20/data.json"

    @patch.dict(os.environ, {"GCS_BUCKET_RAW": "env-bucket"})
    @patch.object(GCSExporter, '_create_gcs_client')
    def test_default_bucket_from_env(self, mock_create_client):
        """Should use GCS_BUCKET_RAW env var as default bucket."""
        mock_blob = Mock()
        mock_bucket = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = Mock()
        mock_client.bucket.return_value = mock_bucket
        mock_create_client.return_value = mock_client

        exporter = GCSExporter()
        data = {"test": "data"}
        config = {"key": "test.json"}  # No bucket specified
        opts = {}

        result = exporter.run(data, config, opts)

        mock_client.bucket.assert_called_with("env-bucket")


# ============================================================================
# TEST PRINT EXPORTER
# ============================================================================

class TestPrintExporter:
    """Test the PrintExporter class."""

    def test_print_json_data(self, capsys):
        """Should print JSON data to stdout."""
        exporter = PrintExporter()
        data = {"key": "value"}

        exporter.run(data, {}, {})

        captured = capsys.readouterr()
        assert "key" in captured.out
        assert "value" in captured.out

    def test_print_binary_data(self, capsys):
        """Should print binary data info (not raw bytes)."""
        exporter = PrintExporter()
        data = b'\x00\x01\x02' * 100

        exporter.run(data, {}, {})

        captured = capsys.readouterr()
        assert "Binary data" in captured.out
        assert "300 bytes" in captured.out


# ============================================================================
# TEST EXPORTER REGISTRY
# ============================================================================

class TestExporterRegistry:
    """Test the EXPORTER_REGISTRY."""

    def test_registry_contains_expected_types(self):
        """Registry should contain gcs, file, and print exporters."""
        assert "gcs" in EXPORTER_REGISTRY
        assert "file" in EXPORTER_REGISTRY
        assert "print" in EXPORTER_REGISTRY

    def test_registry_values_are_classes(self):
        """Registry values should be exporter classes."""
        assert EXPORTER_REGISTRY["gcs"] == GCSExporter
        assert EXPORTER_REGISTRY["file"] == FileExporter
        assert EXPORTER_REGISTRY["print"] == PrintExporter

    def test_registry_instantiation(self):
        """Should be able to instantiate exporters from registry."""
        for exporter_type, exporter_class in EXPORTER_REGISTRY.items():
            instance = exporter_class()
            assert isinstance(instance, BaseExporter)


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestExporterIntegration:
    """Integration tests for exporters."""

    def test_file_export_roundtrip(self, tmp_path):
        """Should be able to export and read back data."""
        exporter = FileExporter()

        # Test data
        original_data = {
            "games": [
                {"id": 1, "home": "LAL", "away": "BOS"},
                {"id": 2, "home": "GSW", "away": "MIA"},
            ],
            "scraped_at": "2026-01-20T10:30:00Z"
        }

        output_file = str(tmp_path / "games.json")
        config = {"filename": output_file}

        # Export
        exporter.run(original_data, config, {})

        # Read back
        with open(output_file, "r") as f:
            recovered_data = json.load(f)

        assert recovered_data == original_data

    def test_export_with_pretty_print(self, tmp_path):
        """Pretty print should produce readable JSON."""
        exporter = FileExporter()

        data = {"key": "value", "nested": {"a": 1, "b": 2}}
        output_file = str(tmp_path / "pretty.json")
        config = {"filename": output_file, "pretty_print": True}

        exporter.run(data, config, {})

        with open(output_file, "r") as f:
            content = f.read()

        # Pretty printed JSON should have newlines
        assert '\n' in content
        # Should still be valid JSON
        assert json.loads(content) == data
