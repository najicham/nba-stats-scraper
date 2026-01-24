"""
Pytest configuration and fixtures for ML tests.

Provides common fixtures for:
- Mock models
- Sample feature data
- Mock BigQuery client
- Sample predictions

Path: tests/ml/conftest.py
Created: 2026-01-24
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, date
import numpy as np


# ============================================================================
# MOCK MODEL FIXTURES
# ============================================================================

@pytest.fixture
def mock_catboost_model():
    """Mock CatBoost model for testing."""
    model = Mock()
    model.predict.return_value = np.array([25.5, 30.2, 18.7])
    model.get_feature_importance.return_value = np.array([0.1, 0.2, 0.3, 0.4])
    return model


@pytest.fixture
def mock_xgboost_model():
    """Mock XGBoost model for testing."""
    model = Mock()
    model.predict.return_value = np.array([24.8, 31.0, 19.2])
    return model


@pytest.fixture
def mock_model_wrapper():
    """Mock ModelWrapper for testing."""
    wrapper = Mock()
    wrapper.model_id = 'test_model_v1'
    wrapper.feature_count = 50
    wrapper.predict.return_value = np.array([25.0, 28.0, 22.0])
    return wrapper


# ============================================================================
# SAMPLE DATA FIXTURES
# ============================================================================

@pytest.fixture
def sample_features():
    """Sample feature array for testing."""
    # 3 players, 50 features each
    return np.random.randn(3, 50)


@pytest.fixture
def sample_feature_names():
    """Sample feature names for testing."""
    return [
        'pts_avg_5g', 'pts_avg_10g', 'pts_avg_season',
        'min_avg_5g', 'min_avg_10g', 'usage_rate',
        'home_away', 'rest_days', 'opp_def_rating',
        'pace', 'ts_pct', 'ast_pct'
    ] + [f'feature_{i}' for i in range(38)]  # 50 total


@pytest.fixture
def sample_predictions():
    """Sample predictions for testing."""
    return [
        {'player_id': 'p001', 'prop_type': 'points', 'prediction': 25.5, 'line': 24.5},
        {'player_id': 'p002', 'prop_type': 'points', 'prediction': 30.2, 'line': 29.5},
        {'player_id': 'p003', 'prop_type': 'points', 'prediction': 18.7, 'line': 19.5},
    ]


@pytest.fixture
def sample_actuals():
    """Sample actual results for testing."""
    return [
        {'player_id': 'p001', 'prop_type': 'points', 'actual': 28},
        {'player_id': 'p002', 'prop_type': 'points', 'actual': 32},
        {'player_id': 'p003', 'prop_type': 'points', 'actual': 15},
    ]


# ============================================================================
# MODEL INFO FIXTURES
# ============================================================================

@pytest.fixture
def sample_model_info():
    """Sample ModelInfo for testing."""
    from dataclasses import dataclass
    from typing import Optional, List

    @dataclass
    class MockModelInfo:
        model_id: str
        model_type: str
        model_path: str
        model_format: str
        feature_count: int
        feature_list: Optional[List[str]] = None

    return MockModelInfo(
        model_id='catboost_v8',
        model_type='catboost',
        model_path='/tmp/models/catboost_v8.cbm',
        model_format='cbm',
        feature_count=50
    )


# ============================================================================
# MOCK CLIENT FIXTURES
# ============================================================================

@pytest.fixture
def mock_bq_client():
    """Mock BigQuery client for testing."""
    client = Mock()
    client.project = 'test-project'

    query_job = Mock()
    query_job.result.return_value = []
    client.query.return_value = query_job

    return client


@pytest.fixture
def mock_gcs_client():
    """Mock GCS client for testing."""
    client = Mock()
    bucket = Mock()
    blob = Mock()
    blob.download_to_filename = Mock()
    bucket.blob.return_value = blob
    client.bucket.return_value = bucket
    return client


# ============================================================================
# EXPERIMENT FIXTURES
# ============================================================================

@pytest.fixture
def sample_experiment_config():
    """Sample experiment configuration."""
    return {
        'experiment_id': 'exp_001',
        'model_type': 'catboost',
        'features': ['pts_avg_5g', 'pts_avg_10g', 'min_avg_5g'],
        'hyperparameters': {
            'learning_rate': 0.1,
            'depth': 6,
            'iterations': 1000
        },
        'train_dates': ['2024-10-01', '2025-01-15'],
        'test_dates': ['2025-01-16', '2025-01-20']
    }


@pytest.fixture
def sample_experiment_results():
    """Sample experiment results."""
    return {
        'experiment_id': 'exp_001',
        'accuracy': 0.58,
        'mae': 4.2,
        'rmse': 5.8,
        'over_accuracy': 0.56,
        'under_accuracy': 0.60,
        'roi': 0.03,
        'games_evaluated': 500
    }


# ============================================================================
# BETTING ACCURACY FIXTURES
# ============================================================================

@pytest.fixture
def sample_betting_results():
    """Sample betting results for accuracy calculation."""
    return [
        {'prediction': 'over', 'actual': 'over', 'stake': 100, 'odds': -110, 'payout': 190.91},
        {'prediction': 'over', 'actual': 'under', 'stake': 100, 'odds': -110, 'payout': 0},
        {'prediction': 'under', 'actual': 'under', 'stake': 100, 'odds': -110, 'payout': 190.91},
        {'prediction': 'under', 'actual': 'over', 'stake': 100, 'odds': -110, 'payout': 0},
    ]
