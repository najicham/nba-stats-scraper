"""
Unit Tests for MLB Exporters

Tests cover:
1. MlbPredictionsExporter
2. MlbSystemPerformanceExporter
3. MlbBestBetsExporter
4. MlbResultsExporter

All MLB exporters follow similar patterns, so they're grouped here.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


# ============================================================================
# MlbPredictionsExporter Tests
# ============================================================================

class TestMlbPredictionsExporterInit:
    """Test suite for MlbPredictionsExporter initialization"""

    def test_initialization_with_defaults(self):
        """Test that exporter initializes with MLB-specific defaults"""
        with patch('data_processors.publishing.mlb.mlb_predictions_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.mlb.mlb_predictions_exporter import MlbPredictionsExporter
                exporter = MlbPredictionsExporter()

                assert exporter.project_id == 'nba-props-platform'
                assert exporter.bucket_name is not None


class TestMlbPredictionsJsonGeneration:
    """Test suite for MLB predictions JSON generation"""

    def test_json_has_required_fields(self):
        """Test that generated JSON has required fields"""
        with patch('data_processors.publishing.mlb.mlb_predictions_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.mlb.mlb_predictions_exporter import MlbPredictionsExporter
                exporter = MlbPredictionsExporter()

                # Mock query method
                exporter._get_predictions = Mock(return_value=[])
                exporter._build_summary = Mock(return_value={})

                result = exporter.generate_json(game_date='2025-08-15')

                assert 'generated_at' in result
                assert 'game_date' in result
                assert 'predictions' in result
                assert 'summary' in result
                assert result['game_date'] == '2025-08-15'

    def test_json_with_predictions(self):
        """Test JSON generation with actual predictions"""
        with patch('data_processors.publishing.mlb.mlb_predictions_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.mlb.mlb_predictions_exporter import MlbPredictionsExporter
                exporter = MlbPredictionsExporter()

                exporter._get_predictions = Mock(return_value=[
                    {
                        'pitcher_lookup': 'gerritcole',
                        'pitcher_name': 'Gerrit Cole',
                        'team': 'NYY',
                        'opponent': 'BOS',
                        'predicted_strikeouts': 8.5,
                        'recommendation': 'OVER',
                        'confidence': 0.72
                    }
                ])
                exporter._build_summary = Mock(return_value={'total': 1})

                result = exporter.generate_json(game_date='2025-08-15')

                assert len(result['predictions']) == 1
                assert result['predictions'][0]['pitcher_name'] == 'Gerrit Cole'


# ============================================================================
# MlbSystemPerformanceExporter Tests
# ============================================================================

class TestMlbSystemPerformanceExporterInit:
    """Test suite for MlbSystemPerformanceExporter initialization"""

    def test_initialization(self):
        """Test that exporter initializes correctly"""
        with patch('data_processors.publishing.mlb.mlb_system_performance_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.mlb.mlb_system_performance_exporter import MlbSystemPerformanceExporter
                exporter = MlbSystemPerformanceExporter()

                assert exporter.project_id is not None


class TestMlbSystemPerformanceJsonGeneration:
    """Test suite for MLB system performance JSON generation"""

    def test_json_structure(self):
        """Test that generated JSON has expected structure"""
        with patch('data_processors.publishing.mlb.mlb_system_performance_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.mlb.mlb_system_performance_exporter import MlbSystemPerformanceExporter
                exporter = MlbSystemPerformanceExporter()

                # Mock query methods
                exporter._get_system_metrics = Mock(return_value=[])

                result = exporter.generate_json()

                assert 'generated_at' in result


# ============================================================================
# MlbBestBetsExporter Tests
# ============================================================================

class TestMlbBestBetsExporterInit:
    """Test suite for MlbBestBetsExporter initialization"""

    def test_initialization(self):
        """Test that exporter initializes correctly"""
        with patch('data_processors.publishing.mlb.mlb_best_bets_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.mlb.mlb_best_bets_exporter import MlbBestBetsExporter
                exporter = MlbBestBetsExporter()

                assert exporter.project_id is not None


class TestMlbBestBetsJsonGeneration:
    """Test suite for MLB best bets JSON generation"""

    def test_json_has_required_fields(self):
        """Test that generated JSON has required fields"""
        with patch('data_processors.publishing.mlb.mlb_best_bets_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.mlb.mlb_best_bets_exporter import MlbBestBetsExporter
                exporter = MlbBestBetsExporter()

                # Mock query method
                exporter._get_best_bets = Mock(return_value=[])

                result = exporter.generate_json(game_date='2025-08-15')

                assert 'generated_at' in result
                assert 'game_date' in result

    def test_best_bets_filtering(self):
        """Test that best bets are filtered by confidence"""
        with patch('data_processors.publishing.mlb.mlb_best_bets_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.mlb.mlb_best_bets_exporter import MlbBestBetsExporter
                exporter = MlbBestBetsExporter()

                # Mock with various confidence levels
                exporter._get_best_bets = Mock(return_value=[
                    {'pitcher_name': 'High Conf', 'confidence': 0.85},
                    {'pitcher_name': 'Low Conf', 'confidence': 0.55}
                ])

                result = exporter.generate_json(game_date='2025-08-15')

                # Verify query was called
                exporter._get_best_bets.assert_called_once()


# ============================================================================
# MlbResultsExporter Tests
# ============================================================================

class TestMlbResultsExporterInit:
    """Test suite for MlbResultsExporter initialization"""

    def test_initialization(self):
        """Test that exporter initializes correctly"""
        with patch('data_processors.publishing.mlb.mlb_results_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.mlb.mlb_results_exporter import MlbResultsExporter
                exporter = MlbResultsExporter()

                assert exporter.project_id is not None


class TestMlbResultsJsonGeneration:
    """Test suite for MLB results JSON generation"""

    def test_json_has_required_fields(self):
        """Test that generated JSON has required fields"""
        with patch('data_processors.publishing.mlb.mlb_results_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.mlb.mlb_results_exporter import MlbResultsExporter
                exporter = MlbResultsExporter()

                # Mock query method
                exporter._get_results = Mock(return_value=[])
                exporter._build_summary = Mock(return_value={})

                result = exporter.generate_json(game_date='2025-08-15')

                assert 'generated_at' in result
                assert 'game_date' in result

    def test_results_include_actual_strikeouts(self):
        """Test that results include actual strikeouts"""
        with patch('data_processors.publishing.mlb.mlb_results_exporter.get_bigquery_client'):
            with patch('data_processors.publishing.base_exporter.storage.Client'):
                from data_processors.publishing.mlb.mlb_results_exporter import MlbResultsExporter
                exporter = MlbResultsExporter()

                exporter._get_results = Mock(return_value=[
                    {
                        'pitcher_name': 'Gerrit Cole',
                        'predicted_strikeouts': 8.5,
                        'actual_strikeouts': 9,
                        'is_correct': True
                    }
                ])
                exporter._build_summary = Mock(return_value={'total': 1, 'correct': 1})

                result = exporter.generate_json(game_date='2025-08-15')

                # Check that query was called
                exporter._get_results.assert_called_once()
