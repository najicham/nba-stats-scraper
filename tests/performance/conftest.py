# tests/performance/conftest.py
"""
Pytest configuration for performance tests.

Provides shared fixtures for benchmarking scrapers, processors,
predictions, and exporters.
"""

import sys
import os
import pytest
from datetime import date, datetime, timezone
from unittest.mock import Mock, MagicMock
from typing import Dict, List, Any
import pandas as pd

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


# =============================================================================
# Scraper Fixtures
# =============================================================================

@pytest.fixture
def mock_http_response():
    """Mock HTTP response with realistic JSON payload."""
    response = Mock()
    response.status_code = 200
    response.headers = {'Content-Type': 'application/json'}
    response.content = b'{"resultSets": [{"rowSet": [[1, 2, 3]], "headers": ["a", "b", "c"]}]}'
    response.json.return_value = {
        "resultSets": [{"rowSet": [[1, 2, 3]], "headers": ["a", "b", "c"]}]
    }
    response.text = '{"resultSets": [{"rowSet": [[1, 2, 3]], "headers": ["a", "b", "c"]}]}'
    return response


@pytest.fixture
def mock_session(mock_http_response):
    """Mock HTTP session that returns mock responses."""
    session = Mock()
    session.get.return_value = mock_http_response
    session.post.return_value = mock_http_response
    return session


@pytest.fixture
def sample_scraper_opts():
    """Standard scraper options for benchmarking."""
    return {
        'gamedate': '2025-01-15',
        'season': '2024-25',
        'sport': 'nba',
        'debug': False
    }


# =============================================================================
# Processor Fixtures
# =============================================================================

@pytest.fixture
def mock_bq_client():
    """Mock BigQuery client for processor tests."""
    client = Mock()

    # Empty result by default
    mock_result = Mock()
    mock_result.to_dataframe.return_value = pd.DataFrame()
    mock_result.result.return_value = []
    client.query.return_value = mock_result

    return client


@pytest.fixture
def sample_player_rows():
    """Generate sample player rows for batch processing tests."""
    teams = ['LAL', 'GSW', 'BOS', 'MIA', 'PHX', 'DAL', 'MIL', 'DEN', 'PHI', 'BRK']

    def generate(count: int) -> List[Dict[str, Any]]:
        rows = []
        for i in range(count):
            rows.append({
                'player_lookup': f'player-{i}',
                'universal_player_id': f'player_{i:03d}_001',
                'game_id': f'game_{i // 15:03d}',
                'game_date': date(2025, 1, 15),
                'opponent_team_abbr': teams[i % len(teams)],
                'team_abbr': teams[(i + 1) % len(teams)],
                'is_home': i % 2 == 0,
                'days_rest': (i % 4),
                'points': 15 + (i % 20),
                'assists': 3 + (i % 8),
                'rebounds': 5 + (i % 10),
                'minutes_played': 25 + (i % 15)
            })
        return rows

    return generate


@pytest.fixture
def sample_game_rows():
    """Generate sample game rows for processor tests."""
    def generate(count: int) -> List[Dict[str, Any]]:
        rows = []
        for i in range(count):
            rows.append({
                'game_id': f'0022400{i:03d}',
                'game_date': f'2025-01-{(i % 28) + 1:02d}',
                'home_team': 'LAL',
                'away_team': 'GSW',
                'home_score': 100 + (i % 20),
                'away_score': 95 + (i % 25),
                'status': 'Final'
            })
        return rows

    return generate


# =============================================================================
# Prediction Fixtures
# =============================================================================

@pytest.fixture
def sample_features():
    """Generate sample feature dictionaries for prediction tests."""
    def generate(count: int) -> List[Dict[str, Any]]:
        features_list = []
        for i in range(count):
            features_list.append({
                'feature_count': 25,
                'feature_version': 'v1_baseline_25',
                'data_source': 'mock',
                'features_array': [
                    20.5 + (i % 10),   # points_avg_last_5
                    22.3 + (i % 8),    # points_avg_last_10
                    24.1 + (i % 6),    # points_avg_season
                    3.2 + (i % 3),     # points_std_last_10
                    2 + (i % 4),       # games_in_last_7_days
                    45.0 + (i % 20),   # fatigue_score
                    0.5,               # rest_advantage
                    0.8,               # injury_risk
                    1.2,               # recent_trend
                    85.0,              # feature_quality_score
                    12.0,              # minutes_change
                    5.0,               # pct_free_throw
                    3.5,               # team_win_pct
                    110.0,             # team_off_rating
                    98.5,              # opponent_def_rating
                    1,                 # is_home
                    0,                 # back_to_back
                    0,                 # injury_flag
                    0.45,              # paint_rate
                    0.25,              # mid_range_rate
                    0.20,              # three_pt_rate
                    0.10,              # assisted_rate
                    102.0,             # pace
                    112.5,             # usage_rate
                    0.58               # true_shooting_pct
                ],
                'player_lookup': f'player-{i}',
                'game_date': date(2025, 1, 15),
                'points_avg_last_5': 20.5 + (i % 10),
                'points_avg_last_10': 22.3 + (i % 8),
                'points_avg_season': 24.1 + (i % 6),
                'points_std_last_10': 3.2 + (i % 3),
                'games_played_last_7_days': 2 + (i % 4),
                'fatigue_score': 45.0 + (i % 20)
            })
        return features_list

    return generate


@pytest.fixture
def sample_prop_lines():
    """Generate sample prop lines for prediction tests."""
    def generate(count: int) -> List[float]:
        return [20.5 + (i % 15) for i in range(count)]

    return generate


# =============================================================================
# Export Fixtures
# =============================================================================

@pytest.fixture
def mock_gcs_client():
    """Mock GCS client for export tests."""
    client = Mock()
    bucket = Mock()
    blob = Mock()

    client.bucket.return_value = bucket
    bucket.blob.return_value = blob
    blob.upload_from_string.return_value = None
    blob.patch.return_value = None

    return client


@pytest.fixture
def sample_export_data():
    """Generate sample data for export timing tests."""
    def generate(player_count: int, games_per_player: int = 10) -> Dict[str, Any]:
        players = []
        for i in range(player_count):
            player = {
                'player_lookup': f'player-{i}',
                'player_name': f'Player {i}',
                'team_abbr': 'LAL',
                'games': []
            }
            for j in range(games_per_player):
                player['games'].append({
                    'game_date': f'2025-01-{(j % 28) + 1:02d}',
                    'points': 20 + (j % 15),
                    'assists': 5 + (j % 8),
                    'rebounds': 7 + (j % 10)
                })
            players.append(player)

        return {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'version': 'v1',
            'player_count': player_count,
            'players': players
        }

    return generate


# =============================================================================
# Benchmark Configuration
# =============================================================================

@pytest.fixture
def benchmark_config():
    """Configuration for benchmark tests."""
    return {
        'small_batch': 50,
        'medium_batch': 200,
        'large_batch': 500,
        'xlarge_batch': 1000,
        'warmup_rounds': 3,
        'min_rounds': 5
    }
