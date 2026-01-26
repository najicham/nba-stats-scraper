"""
Pytest configuration and fixtures for BallDontLie scraper tests.

Provides shared fixtures for:
- Mock API keys
- Sample API responses
- Common test utilities

Path: tests/scrapers/balldontlie/conftest.py
Created: 2026-01-25
"""

import pytest
import os
from datetime import date


# ============================================================================
# API KEY FIXTURES
# ============================================================================

@pytest.fixture
def mock_bdl_api_key():
    """Mock BallDontLie API key for testing."""
    return "test_bdl_api_key_12345"


@pytest.fixture
def mock_env_with_api_key(mock_bdl_api_key):
    """Mock environment with BDL API key."""
    original_value = os.environ.get('BDL_API_KEY')
    os.environ['BDL_API_KEY'] = mock_bdl_api_key
    yield mock_bdl_api_key

    # Cleanup
    if original_value is not None:
        os.environ['BDL_API_KEY'] = original_value
    else:
        os.environ.pop('BDL_API_KEY', None)


# ============================================================================
# DATE FIXTURES
# ============================================================================

@pytest.fixture
def sample_game_date():
    """Sample game date for testing."""
    return "2025-01-20"


@pytest.fixture
def sample_season():
    """Sample season for testing."""
    return 2024


# ============================================================================
# PLAYER FIXTURES
# ============================================================================

@pytest.fixture
def sample_player_ids():
    """Sample player IDs for testing."""
    return {
        "lebron": 237,
        "davis": 115,
        "curry": 140,
        "durant": 145,
        "harden": 200
    }


@pytest.fixture
def sample_player_names():
    """Sample player names for testing."""
    return {
        237: {"first_name": "LeBron", "last_name": "James"},
        115: {"first_name": "Anthony", "last_name": "Davis"},
        140: {"first_name": "Stephen", "last_name": "Curry"},
        145: {"first_name": "Kevin", "last_name": "Durant"},
        200: {"first_name": "James", "last_name": "Harden"}
    }


# ============================================================================
# TEAM FIXTURES
# ============================================================================

@pytest.fixture
def sample_team_data():
    """Sample team data for testing."""
    return {
        "LAL": {
            "id": 14,
            "conference": "West",
            "division": "Pacific",
            "city": "Los Angeles",
            "name": "Lakers",
            "full_name": "Los Angeles Lakers",
            "abbreviation": "LAL"
        },
        "BOS": {
            "id": 2,
            "conference": "East",
            "division": "Atlantic",
            "city": "Boston",
            "name": "Celtics",
            "full_name": "Boston Celtics",
            "abbreviation": "BOS"
        }
    }


# ============================================================================
# API RESPONSE UTILITIES
# ============================================================================

@pytest.fixture
def create_box_score_entry():
    """Factory fixture to create box score entries."""
    def _create(
        player_id,
        game_id,
        date,
        points=20,
        rebounds=8,
        assists=5,
        team_abbr="LAL"
    ):
        return {
            "id": game_id * 1000 + player_id,
            "player": {
                "id": player_id,
                "first_name": "Test",
                "last_name": "Player"
            },
            "team": {
                "id": 14,
                "abbreviation": team_abbr
            },
            "game": {
                "id": game_id,
                "date": date,
                "home_team": {"abbreviation": "LAL"},
                "visitor_team": {"abbreviation": "BOS"}
            },
            "pts": points,
            "reb": rebounds,
            "ast": assists,
            "min": "30:00"
        }

    return _create


@pytest.fixture
def create_player_average_entry():
    """Factory fixture to create player average entries."""
    def _create(
        player_id,
        season=2024,
        points=25.0,
        rebounds=8.0,
        assists=7.0
    ):
        return {
            "player_id": player_id,
            "season": season,
            "games_played": 50,
            "points": points,
            "rebounds": rebounds,
            "assists": assists,
            "field_goal_percentage": 0.500,
            "three_point_percentage": 0.350,
            "free_throw_percentage": 0.800
        }

    return _create


@pytest.fixture
def create_player_detail_entry():
    """Factory fixture to create player detail entries."""
    def _create(
        player_id,
        first_name="Test",
        last_name="Player",
        team_abbr="LAL",
        position="F"
    ):
        return {
            "id": player_id,
            "first_name": first_name,
            "last_name": last_name,
            "position": position,
            "height": "6-8",
            "weight": "240",
            "jersey_number": "23",
            "country": "USA",
            "draft_year": 2020,
            "draft_round": 1,
            "draft_number": 10,
            "team": {
                "id": 14,
                "abbreviation": team_abbr,
                "full_name": f"Team {team_abbr}"
            }
        }

    return _create


# ============================================================================
# MOCK NOTIFICATION FIXTURES
# ============================================================================

@pytest.fixture
def mock_notifications():
    """Mock notification functions."""
    from unittest.mock import patch

    with patch('scrapers.balldontlie.bdl_box_scores.notify_info') as mock_info, \
         patch('scrapers.balldontlie.bdl_box_scores.notify_warning') as mock_warning, \
         patch('scrapers.balldontlie.bdl_box_scores.notify_error') as mock_error:

        yield {
            'info': mock_info,
            'warning': mock_warning,
            'error': mock_error
        }


# ============================================================================
# MOCK AVAILABILITY LOGGER FIXTURES
# ============================================================================

@pytest.fixture
def mock_availability_loggers():
    """Mock availability logging functions."""
    from unittest.mock import patch

    with patch('scrapers.balldontlie.bdl_box_scores.log_bdl_game_availability') as mock_bdl, \
         patch('scrapers.balldontlie.bdl_box_scores.log_scraper_availability') as mock_scraper:

        yield {
            'bdl': mock_bdl,
            'scraper': mock_scraper
        }


# ============================================================================
# VALIDATION HELPERS
# ============================================================================

@pytest.fixture
def validate_box_score_schema():
    """Validator for box score output schema."""
    def _validate(data):
        """Validate box score data structure."""
        required_fields = ["date", "timestamp", "rowCount", "boxScores"]

        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

        assert isinstance(data["date"], str)
        assert isinstance(data["timestamp"], str)
        assert isinstance(data["rowCount"], int)
        assert isinstance(data["boxScores"], list)

        return True

    return _validate


@pytest.fixture
def validate_player_averages_schema():
    """Validator for player averages output schema."""
    def _validate(data):
        """Validate player averages data structure."""
        required_fields = [
            "ident", "timestamp", "season", "category",
            "seasonType", "statType", "rowCount", "playerAverages"
        ]

        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

        assert isinstance(data["season"], int)
        assert isinstance(data["rowCount"], int)
        assert isinstance(data["playerAverages"], list)

        return True

    return _validate


@pytest.fixture
def validate_player_detail_schema():
    """Validator for player detail output schema."""
    def _validate(data):
        """Validate player detail data structure."""
        required_fields = ["playerId", "timestamp", "player"]

        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

        assert isinstance(data["timestamp"], str)
        assert isinstance(data["player"], dict)

        # Validate player object
        player = data["player"]
        player_required = ["id", "first_name", "last_name"]

        for field in player_required:
            assert field in player, f"Missing required player field: {field}"

        return True

    return _validate
