# Path: tests/processors/analytics/team_defense_game_summary/conftest.py

"""
Pytest configuration for Team Defense Game Summary Processor v2.0 tests.

Mocks Google Cloud dependencies and provides shared fixtures.
This allows tests to run without full Google Cloud SDK installation.

Directory: tests/processors/analytics/team_defense_game_summary/
"""

import sys
from unittest.mock import MagicMock, Mock
from datetime import datetime, date, timezone
import pandas as pd

# =============================================================================
# COMPREHENSIVE GOOGLE CLOUD MOCKING (MUST BE FIRST!)
# =============================================================================

class MockGoogleModule(MagicMock):
    """
    Mock Google module that allows submodule imports dynamically.
    
    This handles cases like:
    - from google.cloud import bigquery
    - from google.auth import default
    - from google.cloud.exceptions import NotFound
    """
    def __getattr__(self, name):
        # Return a new mock for any attribute access
        return MagicMock()

# Create base mock for 'google' package
mock_google = MockGoogleModule()
sys.modules['google'] = mock_google

# Mock all google.* submodules that might be imported
google_modules = [
    'google.auth',
    'google.auth.credentials',
    'google.auth.transport',
    'google.auth.transport.requests',
    'google.oauth2',
    'google.oauth2.service_account',
    'google.cloud',
    'google.cloud.bigquery',
    'google.cloud.exceptions',
    'google.cloud.pubsub_v1',
    'google.cloud.logging',
    'google.cloud.storage',
    'google.api_core',
    'google.api_core.exceptions',
]

for module_name in google_modules:
    sys.modules[module_name] = MagicMock()

# Create mock exception classes that can be raised/caught
# These must inherit from BaseException to work in except clauses
class MockNotFound(Exception):
    """Mock NotFound exception."""
    pass

class MockBadRequest(Exception):
    """Mock BadRequest exception."""
    pass

class MockGoogleAPIError(Exception):
    """Mock GoogleAPIError exception."""
    pass

class MockConflict(Exception):
    """Mock Conflict exception."""
    pass

mock_exceptions = MagicMock()
mock_exceptions.NotFound = MockNotFound
mock_exceptions.BadRequest = MockBadRequest
mock_exceptions.GoogleAPIError = MockGoogleAPIError
mock_exceptions.Conflict = MockConflict
sys.modules['google.cloud.exceptions'] = mock_exceptions

# Also add to google.api_core.exceptions for analytics_base.py compatibility
mock_api_core_exceptions = MagicMock()
mock_api_core_exceptions.GoogleAPIError = MockGoogleAPIError
mock_api_core_exceptions.NotFound = MockNotFound
sys.modules['google.api_core.exceptions'] = mock_api_core_exceptions

# Mock google.auth.default to return mock credentials
mock_auth = MagicMock()
mock_auth.default = MagicMock(return_value=(MagicMock(), 'test-project'))
sys.modules['google.auth'] = mock_auth

# =============================================================================
# PYTEST CONFIGURATION
# =============================================================================

import pytest


def pytest_configure(config):
    """Configure pytest with custom markers and settings."""
    config.addinivalue_line(
        "markers",
        "unit: mark test as a unit test (fast, isolated)"
    )
    config.addinivalue_line(
        "markers",
        "integration: mark test as an integration test (slower, end-to-end)"
    )
    config.addinivalue_line(
        "markers",
        "validation: mark test as a validation test (requires real BigQuery)"
    )
    config.addinivalue_line(
        "markers",
        "slow: mark test as slow (> 1 second)"
    )


# =============================================================================
# SHARED FIXTURES - PROJECT/DATE
# =============================================================================

@pytest.fixture(scope='session')
def test_project_id():
    """Test GCP project ID."""
    return 'test-project'


@pytest.fixture(scope='session')
def test_date_range():
    """Standard test date range."""
    return {
        'start_date': '2025-01-15',
        'end_date': '2025-01-15'
    }


# =============================================================================
# SHARED FIXTURES - PROCESSOR
# =============================================================================

@pytest.fixture
def mock_processor():
    """
    Create a mock processor instance for integration tests.

    Returns processor with mocked BigQuery client and pre-configured options.
    """
    from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import (
        TeamDefenseGameSummaryProcessor
    )

    processor = TeamDefenseGameSummaryProcessor()

    # Mock BigQuery client with proper iterable returns
    processor.bq_client = Mock()
    processor.bq_client.project = 'test-project'
    processor.project_id = 'test-project'

    # Make query().result() return an empty iterable by default
    mock_query_result = Mock()
    mock_query_result.result.return_value = []  # Return empty iterable
    mock_query_result.to_dataframe.return_value = pd.DataFrame()
    processor.bq_client.query.return_value = mock_query_result

    # Create proper dependency check result (must be a dict with specific keys)
    dependency_check_success = {
        'all_critical_present': True,
        'missing': [],
        'stale_fail': [],
        'details': {  # Changed from 'dependency_details' to 'details'
            'nba_raw.nbac_team_boxscore': {
                'exists': True,
                'row_count': 10,
                'age_hours': 2,
                'last_updated': datetime(2024, 10, 21, 23, 0, 0)
            },
            'nba_raw.nbac_gamebook_player_stats': {
                'exists': True,
                'row_count': 50,
                'age_hours': 2,
                'last_updated': datetime(2024, 10, 21, 23, 0, 0)
            },
            'nba_raw.bdl_player_boxscores': {
                'exists': True,
                'row_count': 50,
                'age_hours': 2,
                'last_updated': datetime(2024, 10, 21, 23, 0, 0)
            }
        }
    }

    # Mock base class methods
    processor.log_quality_issue = Mock()
    processor.save_analytics = Mock()
    processor.log_processing_run = Mock()
    processor.validate_extracted_data = Mock()
    processor.check_dependencies = Mock(return_value=dependency_check_success)
    processor.track_source_usage = Mock()  # ADD: Mock this to avoid KeyError

    # Mock early exit mixin methods to avoid BQ calls and date checks
    processor._has_games_scheduled = Mock(return_value=True)
    processor._get_existing_data_count = Mock(return_value=0)
    processor._is_too_historical = Mock(return_value=False)  # Don't skip historical dates
    processor._is_offseason = Mock(return_value=False)  # Not offseason

    # Add required processor attributes
    # Note: processor_name is a read-only property returning __class__.__name__
    processor.run_id = 'test-run-id'

    # Set default options
    processor.opts = {
        'start_date': '2024-10-21',
        'end_date': '2024-10-21'
    }

    # Initialize stats dict
    processor.stats = {
        'extract_time': 0.5,
        'transform_time': 0.3,
        'total_runtime': 1.0
    }

    return processor


# =============================================================================
# SHARED FIXTURES - DEPENDENCY CHECK RESULTS
# =============================================================================

@pytest.fixture
def dependency_check_result_success():
    """Mock successful dependency check result."""
    return pd.DataFrame([{
        'table_name': 'nba_raw.nbac_team_boxscore',
        'record_count': 10,
        'latest_date': date(2024, 10, 21),
        'last_updated': datetime(2024, 10, 21, 23, 0, 0),
        'hours_since_update': 2
    }])


@pytest.fixture
def dependency_check_result_missing():
    """Mock dependency check result with missing data."""
    return pd.DataFrame([{
        'table_name': 'nba_raw.nbac_team_boxscore',
        'record_count': 0,  # Missing data
        'latest_date': None,
        'last_updated': None,
        'hours_since_update': None
    }])


# =============================================================================
# SHARED FIXTURES - SAMPLE DATA
# =============================================================================

@pytest.fixture
def sample_raw_extracted_data():
    """
    Sample raw extracted data for testing.
    
    This represents the merged output from:
    - _extract_opponent_offense (opponent's offensive stats)
    - _extract_defensive_actions (defensive player stats aggregated)
    """
    return pd.DataFrame([
        {
            # Core identifiers
            'game_id': '20241021LAL_GSW',
            'game_date': date(2024, 10, 21),
            'season_year': 2024,
            'nba_game_id': '0022400123',
            
            # Defensive perspective
            'defending_team_abbr': 'LAL',
            'opponent_team_abbr': 'GSW',
            'home_game': True,
            
            # Opponent offensive stats (= LAL's defensive stats)
            'points_allowed': 112,
            'opp_fg_makes': 42,
            'opp_fg_attempts': 90,
            'opp_fg_pct': 0.467,
            'opp_three_pt_makes': 14,
            'opp_three_pt_attempts': 38,
            'opp_three_pt_pct': 0.368,
            'opp_ft_makes': 14,
            'opp_ft_attempts': 18,
            'opp_ft_pct': 0.778,
            'opp_rebounds': 46,
            'opp_offensive_rebounds': 10,
            'opp_defensive_rebounds': 36,
            'opp_assists': 26,
            
            # Defensive actions (forced by LAL)
            'turnovers_forced': 13,
            'fouls_committed': 19,
            'steals': 8,
            'blocks_total': 5,
            'defensive_rebounds': 36,
            
            # Blocks by zone (currently NULL - need play-by-play)
            'blocks_paint': 0,
            'blocks_mid_range': 0,
            'blocks_three_pt': 0,
            
            # Advanced defensive metrics
            'defensive_rating': 109.8,
            'opponent_pace': 98.5,
            'opponent_ts_pct': 0.565,
            'possessions': 102,
            
            # Game result (from LAL perspective)
            'win_flag': True,
            'margin_of_victory': 6,
            'overtime_periods': 0,
            
            # Shot zones (currently NULL - need play-by-play)
            'opp_paint_attempts': None,
            'opp_paint_makes': None,
            'opp_mid_range_attempts': None,
            'opp_mid_range_makes': None,
            'points_in_paint_allowed': None,
            'second_chance_points_allowed': None,
            
            # Team situation (currently NULL - need injury data)
            'players_inactive': 0,
            'starters_inactive': 0,
            
            # Referee (currently NULL)
            'referee_crew_id': None,
            
            # Data quality
            'data_quality_tier': 'high',
            'primary_source_used': 'nbac_team_boxscore+nbac_gamebook',
            'defensive_actions_source': 'nbac_gamebook',
            
            # Source timestamps
            'opponent_data_processed_at': datetime(2024, 10, 21, 23, 0, 0),
            'defensive_actions_processed_at': datetime(2024, 10, 21, 23, 0, 0)
        },
        {
            # Second game (GSW defense)
            'game_id': '20241021LAL_GSW',
            'game_date': date(2024, 10, 21),
            'season_year': 2024,
            'nba_game_id': '0022400123',
            
            'defending_team_abbr': 'GSW',
            'opponent_team_abbr': 'LAL',
            'home_game': False,
            
            'points_allowed': 118,
            'opp_fg_makes': 45,
            'opp_fg_attempts': 92,
            'opp_fg_pct': 0.489,
            'opp_three_pt_makes': 15,
            'opp_three_pt_attempts': 40,
            'opp_three_pt_pct': 0.375,
            'opp_ft_makes': 13,
            'opp_ft_attempts': 16,
            'opp_ft_pct': 0.813,
            'opp_rebounds': 48,
            'opp_offensive_rebounds': 12,
            'opp_defensive_rebounds': 36,
            'opp_assists': 28,
            
            'turnovers_forced': 11,
            'fouls_committed': 17,
            'steals': 7,
            'blocks_total': 4,
            'defensive_rebounds': 36,
            'blocks_paint': 0,
            'blocks_mid_range': 0,
            'blocks_three_pt': 0,
            
            'defensive_rating': 115.7,
            'opponent_pace': 98.5,
            'opponent_ts_pct': 0.592,
            'possessions': 102,
            
            'win_flag': False,
            'margin_of_victory': -6,
            'overtime_periods': 0,
            
            'opp_paint_attempts': None,
            'opp_paint_makes': None,
            'opp_mid_range_attempts': None,
            'opp_mid_range_makes': None,
            'points_in_paint_allowed': None,
            'second_chance_points_allowed': None,
            
            'players_inactive': 0,
            'starters_inactive': 0,
            'referee_crew_id': None,
            
            'data_quality_tier': 'high',
            'primary_source_used': 'nbac_team_boxscore+nbac_gamebook',
            'defensive_actions_source': 'nbac_gamebook',
            
            'opponent_data_processed_at': datetime(2024, 10, 21, 23, 0, 0),
            'defensive_actions_processed_at': datetime(2024, 10, 21, 23, 0, 0)
        }
    ])


@pytest.fixture
def sample_team_boxscore():
    """Sample team boxscore data (Phase 2 raw)."""
    return pd.DataFrame([
        {
            'game_id': '20250115_LAL_BOS',
            'game_date': date(2025, 1, 15),
            'season_year': 2024,
            'nba_game_id': '0022400500',
            'team_abbr': 'LAL',
            'is_home': False,
            'points': 108,
            'fg_made': 40,
            'fg_attempted': 88,
            'fg_percentage': 0.455,
            'three_pt_made': 12,
            'three_pt_attempted': 35,
            'three_pt_percentage': 0.343,
            'ft_made': 16,
            'ft_attempted': 20,
            'ft_percentage': 0.800,
            'total_rebounds': 45,
            'offensive_rebounds': 10,
            'defensive_rebounds': 35,
            'assists': 24,
            'turnovers': 14,
            'steals': 8,
            'blocks': 5,
            'personal_fouls': 18,
            'plus_minus': -7,
            'processed_at': datetime(2025, 1, 15, 23, 0, 0)
        },
        {
            'game_id': '20250115_LAL_BOS',
            'game_date': date(2025, 1, 15),
            'season_year': 2024,
            'nba_game_id': '0022400500',
            'team_abbr': 'BOS',
            'is_home': True,
            'points': 115,
            'fg_made': 42,
            'fg_attempted': 85,
            'fg_percentage': 0.494,
            'three_pt_made': 15,
            'three_pt_attempted': 38,
            'three_pt_percentage': 0.395,
            'ft_made': 16,
            'ft_attempted': 18,
            'ft_percentage': 0.889,
            'total_rebounds': 48,
            'offensive_rebounds': 12,
            'defensive_rebounds': 36,
            'assists': 28,
            'turnovers': 12,
            'steals': 7,
            'blocks': 6,
            'personal_fouls': 20,
            'plus_minus': 7,
            'processed_at': datetime(2025, 1, 15, 23, 0, 0)
        }
    ])