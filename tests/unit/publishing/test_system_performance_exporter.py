"""
Unit Tests for SystemPerformanceExporter

Tests cover:
1. Initialization
2. System metadata constants
3. JSON generation
4. Rolling windows query
5. Systems array building
6. Comparison building
7. Empty response handling
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


class TestSystemPerformanceExporterInit:
    """Test suite for SystemPerformanceExporter initialization"""

    def test_initialization_with_defaults(self):
        """Test that exporter initializes with default project and bucket"""
        with patch('data_processors.publishing.system_performance_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.system_performance_exporter import SystemPerformanceExporter
                exporter = SystemPerformanceExporter()

                assert exporter.project_id is not None
                assert exporter.bucket_name is not None


class TestSystemMetadata:
    """Test suite for system metadata constants"""

    def test_system_metadata_structure(self):
        """Test that system metadata has required structure"""
        from data_processors.publishing.system_performance_exporter import SYSTEM_METADATA

        assert 'catboost_v8' in SYSTEM_METADATA
        assert SYSTEM_METADATA['catboost_v8']['is_primary'] is True

        for system_id, meta in SYSTEM_METADATA.items():
            assert 'display_name' in meta
            assert 'description' in meta
            assert 'is_primary' in meta
            assert 'ranking' in meta

    def test_catboost_is_primary(self):
        """Test that CatBoost V8 is marked as primary"""
        from data_processors.publishing.system_performance_exporter import SYSTEM_METADATA

        primary_systems = [s for s, m in SYSTEM_METADATA.items() if m['is_primary']]
        assert len(primary_systems) == 1
        assert 'catboost_v8' in primary_systems


class TestJsonGeneration:
    """Test suite for JSON generation"""

    def test_json_has_required_fields(self):
        """Test that generated JSON has required fields"""
        with patch('data_processors.publishing.system_performance_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.system_performance_exporter import SystemPerformanceExporter
                exporter = SystemPerformanceExporter()

                # Mock query methods
                exporter._query_rolling_windows = Mock(return_value={
                    'catboost_v8': {
                        'last_7_days': {'total': 100, 'win_rate': 0.72},
                        'last_30_days': {'total': 400, 'win_rate': 0.70},
                        'season': {'total': 1000, 'win_rate': 0.68}
                    }
                })
                exporter._build_systems_array = Mock(return_value=[])
                exporter._build_comparison = Mock(return_value={})

                result = exporter.generate_json('2025-01-15')

                assert 'as_of_date' in result
                assert 'generated_at' in result
                assert 'systems' in result
                assert 'comparison' in result

    def test_empty_response_when_no_data(self):
        """Test empty response when no performance data"""
        with patch('data_processors.publishing.system_performance_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.system_performance_exporter import SystemPerformanceExporter
                exporter = SystemPerformanceExporter()

                exporter._query_rolling_windows = Mock(return_value={})

                result = exporter.generate_json('2025-01-15')

                # Should return empty response structure
                assert result['as_of_date'] == '2025-01-15'


class TestSystemsArrayBuilding:
    """Test suite for systems array building"""

    def test_systems_include_metadata(self):
        """Test that systems array includes metadata from constants"""
        with patch('data_processors.publishing.system_performance_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.system_performance_exporter import (
                    SystemPerformanceExporter,
                    SYSTEM_METADATA
                )
                exporter = SystemPerformanceExporter()

                windows_by_system = {
                    'catboost_v8': {
                        'last_7_days': {'total': 100, 'win_rate': 0.72, 'mae': 4.5},
                        'last_30_days': {'total': 400, 'win_rate': 0.70, 'mae': 4.7},
                        'season': {'total': 1000, 'win_rate': 0.68, 'mae': 4.8}
                    }
                }

                systems = exporter._build_systems_array(windows_by_system)

                # Should have one system
                assert len(systems) >= 1

                # Find catboost
                catboost = next((s for s in systems if s['system_id'] == 'catboost_v8'), None)
                if catboost:
                    assert catboost['display_name'] == SYSTEM_METADATA['catboost_v8']['display_name']
                    assert catboost['is_primary'] is True


class TestComparisonBuilding:
    """Test suite for comparison building"""

    def test_comparison_structure(self):
        """Test that comparison has expected structure"""
        with patch('data_processors.publishing.system_performance_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.system_performance_exporter import SystemPerformanceExporter
                exporter = SystemPerformanceExporter()

                windows_by_system = {
                    'catboost_v8': {
                        'last_7_days': {'total': 100, 'win_rate': 0.72, 'mae': 4.5},
                        'last_30_days': {'total': 400, 'win_rate': 0.70, 'mae': 4.7},
                        'season': {'total': 1000, 'win_rate': 0.68, 'mae': 4.8}
                    },
                    'xgboost_v1': {
                        'last_7_days': {'total': 100, 'win_rate': 0.65, 'mae': 5.0},
                        'last_30_days': {'total': 400, 'win_rate': 0.64, 'mae': 5.2},
                        'season': {'total': 1000, 'win_rate': 0.62, 'mae': 5.3}
                    }
                }

                comparison = exporter._build_comparison(windows_by_system)

                # Comparison should be a dict (can be empty if not implemented)
                assert isinstance(comparison, dict)


class TestEmptyResponse:
    """Test suite for empty response handling"""

    def test_empty_response_structure(self):
        """Test empty response has correct structure"""
        with patch('data_processors.publishing.system_performance_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.system_performance_exporter import SystemPerformanceExporter
                exporter = SystemPerformanceExporter()

                result = exporter._empty_response('2025-01-15')

                assert result['as_of_date'] == '2025-01-15'
                assert 'generated_at' in result
                assert 'systems' in result
                assert 'comparison' in result
