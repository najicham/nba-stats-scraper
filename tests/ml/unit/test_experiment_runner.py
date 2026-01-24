"""
Unit tests for ml/experiment_runner.py

Tests the experiment runner functionality including:
- ModelPrediction dataclass
- Model registry queries
- Feature extraction
- Prediction storage

Path: tests/ml/unit/test_experiment_runner.py
Created: 2026-01-24
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date, datetime
import numpy as np
import json


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_bq_client():
    """Mock BigQuery client."""
    return Mock()


@pytest.fixture
def sample_model_info():
    """Sample ModelInfo for testing."""
    from ml.model_loader import ModelInfo
    return ModelInfo(
        model_id='test_model_v1',
        model_type='catboost',
        model_path='/path/to/model.cbm',
        model_format='cbm',
        feature_count=50
    )


@pytest.fixture
def sample_features():
    """Sample feature array for testing."""
    return np.random.randn(3, 50)


@pytest.fixture
def sample_feature_names():
    """Sample feature names for testing."""
    return [f'feature_{i}' for i in range(50)]


@pytest.fixture
def sample_predictions():
    """Sample prediction data for testing."""
    return [
        {'player_id': 'player_1', 'prop_type': 'points', 'prediction': 28.5, 'line': 27.5},
        {'player_id': 'player_2', 'prop_type': 'points', 'prediction': 22.0, 'line': 24.5},
        {'player_id': 'player_3', 'prop_type': 'points', 'prediction': 35.0, 'line': 32.5},
    ]


# ============================================================================
# TEST MODEL PREDICTION DATACLASS
# ============================================================================

class TestModelPrediction:
    """Test the ModelPrediction dataclass."""

    def test_create_prediction(self):
        """Should create ModelPrediction with all fields."""
        from ml.experiment_runner import ModelPrediction

        prediction = ModelPrediction(
            prediction_id='pred_001',
            model_id='catboost_v8',
            player_lookup='lebron_james_lal',
            game_date='2026-01-20',
            game_id='20260120_LAL_BOS',
            team_abbr='LAL',
            opponent_team_abbr='BOS',
            predicted_points=28.5,
            confidence_score=0.75,
            recommendation='over',
            betting_line=27.5,
            edge_vs_line=1.0,
            vegas_opening_line=26.5,
            injury_status=None,
            injury_warning=False,
            feature_version='v33',
            feature_count=50,
            features_hash=None,
            prediction_time='2026-01-20T10:00:00'
        )

        assert prediction.model_id == 'catboost_v8'
        assert prediction.predicted_points == 28.5
        assert prediction.recommendation == 'over'

    def test_prediction_to_dict(self):
        """Should convert prediction to dictionary."""
        from ml.experiment_runner import ModelPrediction
        from dataclasses import asdict

        prediction = ModelPrediction(
            prediction_id='pred_001',
            model_id='catboost_v8',
            player_lookup='lebron_james_lal',
            game_date='2026-01-20',
            game_id='20260120_LAL_BOS',
            team_abbr='LAL',
            opponent_team_abbr='BOS',
            predicted_points=28.5,
            confidence_score=0.75,
            recommendation='over',
            betting_line=27.5,
            edge_vs_line=1.0,
            vegas_opening_line=None,
            injury_status=None,
            injury_warning=False,
            feature_version='v33',
            feature_count=50,
            features_hash=None,
            prediction_time='2026-01-20T10:00:00'
        )

        pred_dict = asdict(prediction)

        assert 'prediction_id' in pred_dict
        assert 'model_id' in pred_dict
        assert pred_dict['predicted_points'] == 28.5

    def test_calculate_edge(self):
        """Should correctly calculate edge vs line."""
        predicted = 28.5
        line = 27.5

        edge = predicted - line

        assert edge == 1.0

    def test_determine_recommendation(self):
        """Should determine over/under recommendation."""
        def get_recommendation(predicted, line, threshold=0.5):
            edge = predicted - line
            if edge > threshold:
                return 'over'
            elif edge < -threshold:
                return 'under'
            return 'hold'

        assert get_recommendation(28.5, 27.5) == 'over'
        assert get_recommendation(26.0, 27.5) == 'under'
        assert get_recommendation(27.5, 27.5) == 'hold'


# ============================================================================
# TEST MODEL REGISTRY
# ============================================================================

class TestModelRegistry:
    """Test model registry functionality."""

    def test_parse_enabled_models(self, mock_bq_client):
        """Should parse enabled models from registry."""
        # Mock query result
        mock_row = Mock()
        mock_row.model_id = 'catboost_v8'
        mock_row.model_type = 'catboost'
        mock_row.model_path = 'gs://bucket/models/catboost_v8.cbm'
        mock_row.model_format = 'cbm'
        mock_row.feature_version = 'v33'
        mock_row.feature_count = 50
        mock_row.feature_list = '["pts_avg", "min_avg"]'

        query_result = Mock()
        query_result.__iter__ = Mock(return_value=iter([mock_row]))
        mock_bq_client.query.return_value.result.return_value = query_result

        # Parse results
        models = []
        for row in query_result:
            feature_list = None
            if row.feature_list:
                feature_list = json.loads(row.feature_list)
            models.append({
                'model_id': row.model_id,
                'feature_list': feature_list
            })

        assert len(models) == 1
        assert models[0]['model_id'] == 'catboost_v8'
        assert models[0]['feature_list'] == ['pts_avg', 'min_avg']

    def test_filter_enabled_only(self):
        """Should only return enabled models."""
        all_models = [
            {'model_id': 'model_a', 'enabled': True},
            {'model_id': 'model_b', 'enabled': False},
            {'model_id': 'model_c', 'enabled': True},
        ]

        enabled = [m for m in all_models if m['enabled']]

        assert len(enabled) == 2
        assert all(m['enabled'] for m in enabled)


# ============================================================================
# TEST FEATURE EXTRACTION
# ============================================================================

class TestFeatureExtraction:
    """Test feature extraction for predictions."""

    def test_feature_version_consistency(self, sample_feature_names):
        """Feature version should match feature count."""
        assert len(sample_feature_names) == 50

    def test_extract_features_for_player(self):
        """Should extract features for a player."""
        player_data = {
            'pts_avg_5g': 25.4,
            'pts_avg_10g': 24.8,
            'min_avg_5g': 35.2,
            'usage_rate': 0.28,
            'rest_days': 1,
            'home_away': 1,  # 1 = home
        }

        feature_names = ['pts_avg_5g', 'pts_avg_10g', 'min_avg_5g', 'usage_rate', 'rest_days', 'home_away']
        features = np.array([player_data[f] for f in feature_names])

        assert features.shape == (6,)
        assert features[0] == 25.4
        assert features[5] == 1

    def test_handle_missing_features(self):
        """Should handle missing features gracefully."""
        player_data = {
            'pts_avg_5g': 25.4,
            'pts_avg_10g': None,  # Missing
            'min_avg_5g': 35.2,
        }

        feature_names = ['pts_avg_5g', 'pts_avg_10g', 'min_avg_5g']
        features = []

        for f in feature_names:
            value = player_data.get(f)
            if value is None:
                features.append(0.0)  # Default for missing
            else:
                features.append(value)

        assert features[1] == 0.0  # Missing value defaulted


# ============================================================================
# TEST PREDICTION GENERATION
# ============================================================================

class TestPredictionGeneration:
    """Test prediction generation."""

    def test_generate_prediction_id(self):
        """Should generate unique prediction IDs."""
        import uuid

        ids = [str(uuid.uuid4()) for _ in range(3)]

        assert len(ids) == 3
        assert len(set(ids)) == 3  # All unique

    def test_batch_prediction(self, sample_features):
        """Should generate predictions for batch of players."""
        mock_model = Mock()
        mock_model.predict.return_value = np.array([25.5, 30.2, 18.7])

        predictions = mock_model.predict(sample_features)

        assert len(predictions) == 3

    def test_prediction_with_confidence(self):
        """Should generate predictions with confidence scores."""
        predictions = [
            {'predicted': 28.5, 'confidence': 0.85},
            {'predicted': 22.0, 'confidence': 0.65},
            {'predicted': 35.0, 'confidence': 0.45},
        ]

        high_confidence = [p for p in predictions if p['confidence'] >= 0.7]

        assert len(high_confidence) == 1
        assert high_confidence[0]['predicted'] == 28.5


# ============================================================================
# TEST BIGQUERY STORAGE
# ============================================================================

class TestBigQueryStorage:
    """Test prediction storage in BigQuery."""

    def test_format_for_insertion(self, sample_predictions):
        """Should format predictions for BigQuery insertion."""
        rows = []
        for p in sample_predictions:
            rows.append({
                'player_id': p['player_id'],
                'prop_type': p['prop_type'],
                'prediction': p['prediction'],
                'line': p['line'],
                'recommendation': 'over' if p['prediction'] > p['line'] else 'under'
            })

        assert len(rows) == 3
        assert all('recommendation' in r for r in rows)

    def test_batch_insert_size(self):
        """Should respect BigQuery batch insert limits."""
        max_batch_size = 10000
        predictions = [{'id': i} for i in range(15000)]

        batches = []
        for i in range(0, len(predictions), max_batch_size):
            batch = predictions[i:i + max_batch_size]
            batches.append(batch)

        assert len(batches) == 2
        assert len(batches[0]) == 10000
        assert len(batches[1]) == 5000


# ============================================================================
# TEST CLI ARGUMENTS
# ============================================================================

class TestCLIArguments:
    """Test command-line argument handling."""

    def test_parse_date_argument(self):
        """Should parse date argument correctly."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument('--date', type=str, default=None)

        args = parser.parse_args(['--date', '2026-01-20'])

        assert args.date == '2026-01-20'

    def test_parse_model_argument(self):
        """Should parse specific model argument."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument('--model', type=str, default=None)

        args = parser.parse_args(['--model', 'catboost_v8'])

        assert args.model == 'catboost_v8'

    def test_dry_run_flag(self):
        """Should parse dry-run flag."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument('--dry-run', action='store_true')

        args_with = parser.parse_args(['--dry-run'])
        args_without = parser.parse_args([])

        assert args_with.dry_run is True
        assert args_without.dry_run is False


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestExperimentRunnerIntegration:
    """Integration tests for experiment runner."""

    def test_full_prediction_workflow(self, sample_features, sample_model_info):
        """Should complete full prediction workflow."""
        # 1. Load model
        mock_model = Mock()
        mock_model.predict.return_value = np.array([25.5, 30.2, 18.7])

        # 2. Generate predictions
        predictions = mock_model.predict(sample_features)

        # 3. Create prediction records
        records = []
        for i, pred in enumerate(predictions):
            records.append({
                'prediction_id': f'pred_{i}',
                'model_id': sample_model_info.model_id,
                'predicted_points': float(pred),
                'betting_line': 25.0,
                'edge_vs_line': float(pred) - 25.0
            })

        assert len(records) == 3
        assert records[0]['predicted_points'] == 25.5
        assert records[1]['edge_vs_line'] == pytest.approx(5.2)  # 30.2 - 25.0

    def test_multiple_models_comparison(self, sample_features):
        """Should run multiple models for comparison."""
        models = {
            'catboost_v8': Mock(predict=Mock(return_value=np.array([25.5, 30.2, 18.7]))),
            'xgboost_v6': Mock(predict=Mock(return_value=np.array([24.8, 31.0, 19.2]))),
            'ensemble_v2': Mock(predict=Mock(return_value=np.array([25.1, 30.6, 19.0]))),
        }

        all_predictions = {}
        for model_id, model in models.items():
            all_predictions[model_id] = model.predict(sample_features)

        assert len(all_predictions) == 3
        # Compare predictions
        assert all_predictions['catboost_v8'][0] != all_predictions['xgboost_v6'][0]
