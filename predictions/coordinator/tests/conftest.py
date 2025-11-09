# predictions/coordinator/tests/conftest.py

"""
Pytest configuration and shared fixtures for coordinator tests

Provides mock BigQuery clients, Pub/Sub publishers, and sample data
for testing coordinator components without external dependencies.
"""

import pytest
from datetime import date, datetime
from unittest.mock import Mock, MagicMock
import sys
import os

# Add project root and predictions to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Also add predictions directory to path so we can import coordinator modules
predictions_path = os.path.join(project_root, 'predictions')
if predictions_path not in sys.path:
    sys.path.insert(0, predictions_path)


@pytest.fixture
def mock_bigquery_client():
    """Mock BigQuery client for testing"""
    client = MagicMock()
    client.project = 'test-project'
    return client


@pytest.fixture
def mock_pubsub_publisher():
    """Mock Pub/Sub publisher for testing"""
    publisher = MagicMock()
    
    # Mock topic_path method
    publisher.topic_path.return_value = 'projects/test-project/topics/test-topic'
    
    # Mock publish method returns future
    mock_future = MagicMock()
    mock_future.result.return_value = 'message-id-123'
    publisher.publish.return_value = mock_future
    
    return publisher


@pytest.fixture
def sample_game_date():
    """Sample game date for testing"""
    return date(2025, 11, 8)


@pytest.fixture
def sample_players():
    """Sample player data from BigQuery query"""
    return [
        {
            'player_lookup': 'lebron-james',
            'universal_player_id': 'player_001',
            'game_id': '20251108_LAL_GSW',
            'game_date': date(2025, 11, 8),
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'GSW',
            'is_home': True,
            'days_rest': 1,
            'back_to_back': False,
            'projected_minutes': 35.0,
            'is_active': True,
            'injury_status': None,
            'position': 'SF'
        },
        {
            'player_lookup': 'stephen-curry',
            'universal_player_id': 'player_002',
            'game_id': '20251108_LAL_GSW',
            'game_date': date(2025, 11, 8),
            'team_abbr': 'GSW',
            'opponent_team_abbr': 'LAL',
            'is_home': False,
            'days_rest': 2,
            'back_to_back': False,
            'projected_minutes': 36.0,
            'is_active': True,
            'injury_status': None,
            'position': 'PG'
        },
        {
            'player_lookup': 'anthony-davis',
            'universal_player_id': 'player_003',
            'game_id': '20251108_LAL_GSW',
            'game_date': date(2025, 11, 8),
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'GSW',
            'is_home': True,
            'days_rest': 1,
            'back_to_back': False,
            'projected_minutes': 34.0,
            'is_active': True,
            'injury_status': None,
            'position': 'PF'
        }
    ]


@pytest.fixture
def sample_summary_stats():
    """Sample summary statistics for a game date"""
    return {
        'game_date': '2025-11-08',
        'total_games': 15,
        'total_players': 450,
        'teams_playing': 30,
        'avg_projected_minutes': 28.5,
        'min_projected_minutes': 10.0,
        'max_projected_minutes': 38.0,
        'players_by_position': {
            'PG': 90,
            'SG': 90,
            'SF': 90,
            'PF': 90,
            'C': 90
        }
    }


@pytest.fixture
def sample_completion_event():
    """Sample completion event from worker"""
    return {
        'player_lookup': 'lebron-james',
        'game_date': '2025-11-08',
        'predictions_generated': 5,
        'timestamp': '2025-11-08T10:30:00.123Z',
        'worker_instance': 'worker-001'
    }


@pytest.fixture
def sample_prediction_request():
    """Sample prediction request message"""
    return {
        'player_lookup': 'lebron-james',
        'game_date': '2025-11-08',
        'game_id': '20251108_LAL_GSW',
        'line_values': [25.5],
        'team_abbr': 'LAL',
        'opponent_team_abbr': 'GSW',
        'is_home': True,
        'projected_minutes': 35.0,
        'position': 'SF'
    }


def create_mock_bigquery_row(**kwargs):
    """
    Create a mock BigQuery row object
    
    Args:
        **kwargs: Field name and value pairs
    
    Returns:
        Mock object with attributes matching kwargs
    """
    row = Mock()
    for key, value in kwargs.items():
        setattr(row, key, value)
    return row
