#!/usr/bin/env python3
"""
Tests for PropsAvailabilityValidator

Tests the props availability validator that alerts when games have missing
or insufficient betting lines.

Test Coverage:
- Zero props detection (CRITICAL alert)
- Player coverage validation (WARNING/CRITICAL thresholds)
- Bookmaker coverage tracking
- Props freshness checks
- Error handling for BigQuery failures
- Configuration loading

Created: 2026-01-25 (Validator Test Framework - Task #4)
"""

import pytest
import sys
import os
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, date, timedelta
from typing import List, Any

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../')))

from validation.validators.raw.props_availability_validator import PropsAvailabilityValidator
from validation.base_validator import ValidationResult


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_bq_client():
    """Mock BigQuery client with standard query interface."""
    mock_client = Mock()
    mock_query_job = Mock()
    mock_client.query.return_value = mock_query_job
    return mock_client


@pytest.fixture
def mock_config_path(tmp_path):
    """Create a temporary config file for testing."""
    config_file = tmp_path / "props_availability.yaml"
    config_content = """
processor:
  name: "props_availability"
  type: "raw"
  description: "Validates props availability for scheduled games"
  table: "nba_raw.odds_api_props"
  layers:
    - bigquery

bigquery_validations:
  enabled: true

remediation:
  scraper_backfill_template: "python scrapers/odds_api/odds_api_props.py --date {date} --force"

notifications:
  enabled: false
  channels: []
  severity_threshold: "warning"
"""
    config_file.write_text(config_content)
    return str(config_file)


@pytest.fixture
def validator(mock_config_path, mock_bq_client):
    """Create validator instance with mocked dependencies."""
    with patch('validation.base_validator.bigquery.Client', return_value=mock_bq_client):
        validator_instance = PropsAvailabilityValidator(mock_config_path)
        validator_instance.bq_client = mock_bq_client
        return validator_instance


def create_mock_row(**kwargs):
    """Helper to create mock BigQuery row objects."""
    mock_row = Mock()
    for key, value in kwargs.items():
        setattr(mock_row, key, value)
    return mock_row


# =============================================================================
# TEST: Zero Props Detection (CRITICAL)
# =============================================================================

def test_zero_props_games_detected(validator, mock_bq_client):
    """Test that validator detects games with zero betting lines."""
    # Setup: Mock query to return games with no props
    mock_results = [
        create_mock_row(
            game_id='0022500647',
            game_date=date(2026, 1, 24),
            home_team_tricode='CHI',
            away_team_tricode='BOS',
            game_time_et=datetime(2026, 1, 24, 19, 0),
            game_status_text='Scheduled',
            bookmakers_found='None'
        ),
        create_mock_row(
            game_id='0022500649',
            game_date=date(2026, 1, 24),
            home_team_tricode='UTA',
            away_team_tricode='MIA',
            game_time_et=datetime(2026, 1, 24, 21, 0),
            game_status_text='Scheduled',
            bookmakers_found='None'
        )
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_zero_props_games('2026-01-24', '2026-01-24')

    # Assert
    assert len(validator.results) > 0
    result = validator.results[-1]

    assert result.check_name == "zero_props_games"
    assert result.passed is False
    assert result.severity == "critical"
    assert result.affected_count == 2
    assert "BOS @ CHI" in str(result.affected_items)
    assert "MIA @ UTA" in str(result.affected_items)
    assert "ZERO betting lines" in result.message


def test_zero_props_all_games_have_props(validator, mock_bq_client):
    """Test that validator passes when all games have props."""
    # Setup: Mock query to return no games (all have props)
    mock_bq_client.query.return_value.result.return_value = []

    # Execute validation
    validator._validate_zero_props_games('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is True
    assert result.severity == "info"
    assert result.affected_count == 0
    assert "All scheduled games have betting lines" in result.message


def test_zero_props_handles_query_error(validator, mock_bq_client):
    """Test that validator handles BigQuery errors gracefully."""
    # Setup: Mock query to raise exception
    mock_bq_client.query.side_effect = Exception("BigQuery connection timeout")

    # Execute validation
    validator._validate_zero_props_games('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.severity == "error"
    assert "Validation failed" in result.message
    assert "BigQuery connection timeout" in result.message


# =============================================================================
# TEST: Player Coverage Validation
# =============================================================================

def test_player_coverage_critical_threshold(validator, mock_bq_client):
    """Test detection of games with < 3 players (CRITICAL)."""
    # Setup: Mock query to return games with insufficient players
    mock_results = [
        create_mock_row(
            game_id='0022500647',
            game_date=date(2026, 1, 24),
            home_team_tricode='CHI',
            away_team_tricode='BOS',
            game_time_et=datetime(2026, 1, 24, 19, 0),
            game_status_text='Scheduled',
            player_count=2,  # CRITICAL: < 3 players
            bookmaker_count=1,
            bookmakers='DraftKings',
            sample_players=['Jayson Tatum', 'Jaylen Brown']
        )
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_player_coverage('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.severity == "critical"
    assert result.affected_count == 1
    assert "< 3 players" in result.message


def test_player_coverage_warning_threshold(validator, mock_bq_client):
    """Test detection of games with < 8 players but >= 3 (WARNING)."""
    # Setup: Mock query to return games with low but not critical coverage
    mock_results = [
        create_mock_row(
            game_id='0022500644',
            game_date=date(2026, 1, 24),
            home_team_tricode='MIN',
            away_team_tricode='GSW',
            game_time_et=datetime(2026, 1, 24, 20, 0),
            game_status_text='Scheduled',
            player_count=5,  # WARNING: >= 3 but < 8
            bookmaker_count=2,
            bookmakers='DraftKings, FanDuel',
            sample_players=['Stephen Curry', 'Klay Thompson', 'Anthony Edwards']
        )
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_player_coverage('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.severity == "warning"
    assert result.affected_count == 1
    assert "< 8 players" in result.message


def test_player_coverage_adequate(validator, mock_bq_client):
    """Test that validator passes when all games have adequate coverage."""
    # Setup: Mock query to return no games (all have >= 8 players)
    mock_bq_client.query.return_value.result.return_value = []

    # Execute validation
    validator._validate_player_coverage('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is True
    assert result.severity == "info"
    assert result.affected_count == 0
    assert "adequate player props coverage" in result.message


# =============================================================================
# TEST: Bookmaker Coverage
# =============================================================================

def test_bookmaker_coverage_multiple_sources(validator, mock_bq_client):
    """Test bookmaker coverage tracking with multiple sources."""
    # Setup: Mock query to return bookmaker statistics
    mock_results = [
        create_mock_row(
            bookmaker='DraftKings',
            games_covered=7,
            players_covered=150,
            total_props=450,
            earliest_scrape=datetime(2026, 1, 24, 10, 0),
            latest_scrape=datetime(2026, 1, 24, 18, 30)
        ),
        create_mock_row(
            bookmaker='FanDuel',
            games_covered=7,
            players_covered=145,
            total_props=435,
            earliest_scrape=datetime(2026, 1, 24, 10, 5),
            latest_scrape=datetime(2026, 1, 24, 18, 25)
        )
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_bookmaker_coverage('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is True
    assert result.severity == "info"
    assert result.affected_count == 2
    assert "DraftKings" in str(result.affected_items)
    assert "FanDuel" in str(result.affected_items)


def test_bookmaker_coverage_no_data(validator, mock_bq_client):
    """Test bookmaker coverage when no bookmakers have data."""
    # Setup: Mock query to return no bookmaker data
    mock_bq_client.query.return_value.result.return_value = []

    # Execute validation
    validator._validate_bookmaker_coverage('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert "No bookmaker data found" in result.message


# =============================================================================
# TEST: Props Freshness
# =============================================================================

def test_props_freshness_stale_data(validator, mock_bq_client):
    """Test detection of stale props data (> 6 hours old)."""
    # Setup: Mock query to return games with stale props
    mock_results = [
        create_mock_row(
            game_id='0022500647',
            game_date=date(2026, 1, 24),
            home_team_tricode='CHI',
            away_team_tricode='BOS',
            hours_old=8.5,  # Stale: > 6 hours
            latest_scrape=datetime(2026, 1, 24, 10, 0)
        )
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_props_freshness('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.affected_count == 1
    assert "props data >6 hours old" in result.message


def test_props_freshness_fresh_data(validator, mock_bq_client):
    """Test that validator passes when all props are fresh."""
    # Setup: Mock query to return no stale games
    mock_bq_client.query.return_value.result.return_value = []

    # Execute validation
    validator._validate_props_freshness('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is True
    assert "All props data is fresh" in result.message


# =============================================================================
# TEST: Integration Tests
# =============================================================================

def test_validator_initialization(mock_config_path):
    """Test that validator initializes correctly with config."""
    with patch('validation.base_validator.bigquery.Client'):
        validator = PropsAvailabilityValidator(mock_config_path)

        assert validator is not None
        assert validator.CRITICAL_PLAYER_THRESHOLD == 3
        assert validator.WARNING_PLAYER_THRESHOLD == 8


def test_run_custom_validations_all_checks(validator, mock_bq_client):
    """Test that all custom validation checks are executed."""
    # Setup: Mock all queries to return empty results (passing state)
    mock_bq_client.query.return_value.result.return_value = []

    # Execute all custom validations
    validator._run_custom_validations('2026-01-24', '2026-01-24', season_year=2025)

    # Assert: All 4 checks should have been executed
    assert len(validator.results) >= 4

    check_names = [r.check_name for r in validator.results]
    assert 'zero_props_games' in check_names
    assert 'player_props_coverage' in check_names
    assert 'bookmaker_coverage' in check_names
    assert 'props_freshness' in check_names


def test_validator_execution_duration_tracked(validator, mock_bq_client):
    """Test that execution duration is tracked for each check."""
    # Setup: Mock query to return empty results
    mock_bq_client.query.return_value.result.return_value = []

    # Execute validation
    validator._validate_zero_props_games('2026-01-24', '2026-01-24')

    # Assert: Execution duration should be tracked
    result = validator.results[-1]
    assert hasattr(result, 'execution_duration')
    assert result.execution_duration is not None
    assert result.execution_duration >= 0


def test_validator_query_captured(validator, mock_bq_client):
    """Test that SQL queries are captured in validation results."""
    # Setup: Mock query to return empty results
    mock_bq_client.query.return_value.result.return_value = []

    # Execute validation
    validator._validate_zero_props_games('2026-01-24', '2026-01-24')

    # Assert: Query should be captured
    result = validator.results[-1]
    assert result.query_used is not None
    assert 'SELECT' in result.query_used
    assert 'scheduled_games' in result.query_used


# =============================================================================
# TEST: Edge Cases
# =============================================================================

def test_validator_handles_missing_game_time(validator, mock_bq_client):
    """Test that validator handles games with missing game time."""
    # Setup: Mock query with None game_time_et
    mock_results = [
        create_mock_row(
            game_id='0022500647',
            game_date=date(2026, 1, 24),
            home_team_tricode='CHI',
            away_team_tricode='BOS',
            game_time_et=None,  # Missing game time
            game_status_text='Scheduled',
            bookmakers_found='None'
        )
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation (should not crash)
    validator._validate_zero_props_games('2026-01-24', '2026-01-24')

    # Assert: Should handle None gracefully
    result = validator.results[-1]
    assert result.passed is False
    assert 'TBD' in str(result.affected_items)  # Should show 'TBD' for missing time


def test_validator_handles_empty_sample_players(validator, mock_bq_client):
    """Test that validator handles games with no sample players."""
    # Setup: Mock query with None sample_players
    mock_results = [
        create_mock_row(
            game_id='0022500647',
            game_date=date(2026, 1, 24),
            home_team_tricode='CHI',
            away_team_tricode='BOS',
            game_time_et=datetime(2026, 1, 24, 19, 0),
            game_status_text='Scheduled',
            player_count=0,
            bookmaker_count=0,
            bookmakers='None',
            sample_players=None  # No sample players
        )
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation (should not crash)
    validator._validate_player_coverage('2026-01-24', '2026-01-24')

    # Assert: Should handle None gracefully
    result = validator.results[-1]
    assert result.passed is False


# =============================================================================
# TEST: Remediation Recommendations
# =============================================================================

def test_validator_provides_remediation_for_zero_props(validator, mock_bq_client):
    """Test that validator provides actionable remediation steps."""
    # Setup: Mock query to return games with no props
    mock_results = [
        create_mock_row(
            game_id='0022500647',
            game_date=date(2026, 1, 24),
            home_team_tricode='CHI',
            away_team_tricode='BOS',
            game_time_et=datetime(2026, 1, 24, 19, 0),
            game_status_text='Scheduled',
            bookmakers_found='None'
        )
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_zero_props_games('2026-01-24', '2026-01-24')

    # Assert: Should include remediation steps
    result = validator.results[-1]
    assert len(result.remediation) > 0
    remediation_text = ' '.join(result.remediation)
    assert 'Immediate Actions' in remediation_text
    assert 'Possible Causes' in remediation_text
    assert 'Investigation Commands' in remediation_text


# =============================================================================
# PYTEST MARKERS
# =============================================================================

pytestmark = pytest.mark.unit
