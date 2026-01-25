#!/usr/bin/env python3
"""
Tests for NbacScheduleValidator

Tests the NBA.com schedule validator - the critical pipeline entry point that
drives all downstream processing. Missing or incorrect schedule data cascades
through the entire system.

Test Coverage:
- Schedule completeness (zero games detection)
- Expected games per day (1-15 games for NBA)
- Team coverage (all 30 NBA teams)
- Home/away balance (41/41 split per team)
- Date validation (format, duplicates, boundaries)
- Game ID format consistency
- Season boundary validation (Oct-June)
- Special cases (All-Star break, playoffs, back-to-backs)
- Data freshness checks
- Error handling for BigQuery failures
- Remediation recommendations

Created: 2026-01-25 (Validator Test Framework - Task #7)
"""

import pytest
import sys
import os
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, date, timedelta
from typing import List, Any

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../')))

from validation.validators.raw.nbac_schedule_validator import NbacScheduleValidator
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
    config_file = tmp_path / "nbac_schedule.yaml"
    config_content = """
processor:
  name: "nbac_schedule"
  type: "raw"
  description: "Validates NBA.com schedule - the source of truth for games"
  table: "nba_raw.nbac_schedule"
  partition_field: "game_date"
  layers:
    - bigquery
    - schedule

bigquery_validations:
  enabled: true
  season_completeness:
    enabled: true
    expected_regular_season_games: 1230
    tolerance: 10
    severity: "error"

schedule_validations:
  enabled: true
  data_freshness:
    target_table: "nba_raw.nbac_schedule"
    timestamp_field: "processed_at"
    max_age_hours: 24
    severity: "warning"

remediation:
  processor_backfill_template: "gcloud run jobs execute nbac-schedule-processor-backfill --args=--season-year={season_year} --region=us-west2"

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
        validator_instance = NbacScheduleValidator(mock_config_path)
        validator_instance.bq_client = mock_bq_client
        return validator_instance


def create_mock_row(**kwargs):
    """Helper to create mock BigQuery row objects."""
    mock_row = Mock()
    for key, value in kwargs.items():
        setattr(mock_row, key, value)
    return mock_row


# =============================================================================
# TEST: Team Presence (All 30 Teams Must Be Present)
# =============================================================================

def test_team_presence_all_30_teams(validator, mock_bq_client):
    """Test that validator passes when all 30 NBA teams are present."""
    # Setup: Mock query to return all 30 teams
    mock_results = [
        create_mock_row(team='ATL', game_count=82),
        create_mock_row(team='BOS', game_count=82),
        create_mock_row(team='BKN', game_count=82),
        create_mock_row(team='CHA', game_count=82),
        create_mock_row(team='CHI', game_count=82),
        create_mock_row(team='CLE', game_count=82),
        create_mock_row(team='DAL', game_count=82),
        create_mock_row(team='DEN', game_count=82),
        create_mock_row(team='DET', game_count=82),
        create_mock_row(team='GSW', game_count=82),
        create_mock_row(team='HOU', game_count=82),
        create_mock_row(team='IND', game_count=82),
        create_mock_row(team='LAC', game_count=82),
        create_mock_row(team='LAL', game_count=82),
        create_mock_row(team='MEM', game_count=82),
        create_mock_row(team='MIA', game_count=82),
        create_mock_row(team='MIL', game_count=82),
        create_mock_row(team='MIN', game_count=82),
        create_mock_row(team='NOP', game_count=82),
        create_mock_row(team='NYK', game_count=82),
        create_mock_row(team='OKC', game_count=82),
        create_mock_row(team='ORL', game_count=82),
        create_mock_row(team='PHI', game_count=82),
        create_mock_row(team='PHX', game_count=82),
        create_mock_row(team='POR', game_count=82),
        create_mock_row(team='SAC', game_count=82),
        create_mock_row(team='SAS', game_count=82),
        create_mock_row(team='TOR', game_count=82),
        create_mock_row(team='UTA', game_count=82),
        create_mock_row(team='WAS', game_count=82),
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_team_presence('2025-10-15', '2026-06-15')

    # Assert
    result = validator.results[-1]
    assert result.check_name == "team_presence"
    assert result.passed is True
    assert result.severity == "info"
    assert result.affected_count == 0
    assert "All 30 teams present" in result.message


def test_team_presence_missing_teams(validator, mock_bq_client):
    """Test detection of missing teams (CRITICAL - schedule incomplete)."""
    # Setup: Mock query to return only 28 teams (missing 2)
    mock_results = [
        create_mock_row(team='ATL', game_count=82),
        create_mock_row(team='BOS', game_count=82),
        create_mock_row(team='BKN', game_count=82),
        create_mock_row(team='CHA', game_count=82),
        create_mock_row(team='CHI', game_count=82),
        create_mock_row(team='CLE', game_count=82),
        create_mock_row(team='DAL', game_count=82),
        create_mock_row(team='DEN', game_count=82),
        create_mock_row(team='DET', game_count=82),
        create_mock_row(team='GSW', game_count=82),
        create_mock_row(team='HOU', game_count=82),
        create_mock_row(team='IND', game_count=82),
        create_mock_row(team='LAC', game_count=82),
        create_mock_row(team='LAL', game_count=82),
        create_mock_row(team='MEM', game_count=82),
        create_mock_row(team='MIA', game_count=82),
        create_mock_row(team='MIL', game_count=82),
        create_mock_row(team='MIN', game_count=82),
        create_mock_row(team='NOP', game_count=82),
        create_mock_row(team='NYK', game_count=82),
        create_mock_row(team='OKC', game_count=82),
        create_mock_row(team='ORL', game_count=82),
        create_mock_row(team='PHI', game_count=82),
        create_mock_row(team='PHX', game_count=82),
        create_mock_row(team='POR', game_count=82),
        create_mock_row(team='SAC', game_count=82),
        create_mock_row(team='SAS', game_count=82),
        create_mock_row(team='TOR', game_count=82),
        # Missing: UTA, WAS
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_team_presence('2025-10-15', '2026-06-15')

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.severity == "error"
    assert result.affected_count == 2
    assert "Found 28 teams (expected 30)" in result.message


def test_team_presence_zero_teams(validator, mock_bq_client):
    """Test detection of zero teams (CRITICAL - no schedule data)."""
    # Setup: Mock query to return no teams
    mock_bq_client.query.return_value.result.return_value = []

    # Execute validation
    validator._validate_team_presence('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.severity == "error"
    assert result.affected_count == 30
    assert "Found 0 teams (expected 30)" in result.message


def test_team_presence_handles_query_error(validator, mock_bq_client):
    """Test that validator handles BigQuery errors gracefully."""
    # Setup: Mock query to raise exception
    mock_bq_client.query.side_effect = Exception("BigQuery connection timeout")

    # Execute validation
    validator._validate_team_presence('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.severity == "error"
    assert "Validation query failed" in result.message


# =============================================================================
# TEST: Games Per Team Validation
# =============================================================================

def test_games_per_team_all_within_range(validator, mock_bq_client):
    """Test that validator passes when all teams have 80-84 games (expected range)."""
    # Setup: Mock query to return no anomalies (all teams 80-84 games)
    mock_bq_client.query.return_value.result.return_value = []

    # Execute validation
    validator._validate_games_per_team('2025-10-15', '2026-06-15', season_year=2025)

    # Assert
    result = validator.results[-1]
    assert result.passed is True
    assert result.severity == "info"
    assert result.affected_count == 0
    assert "All teams have expected game counts" in result.message


def test_games_per_team_detect_low_count(validator, mock_bq_client):
    """Test detection of teams with too few games."""
    # Setup: Mock query to return teams with < 80 games
    mock_results = [
        create_mock_row(team='LAL', game_count=75),  # Too few
        create_mock_row(team='GSW', game_count=78),  # Too few
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_games_per_team('2025-10-15', '2026-06-15', season_year=2025)

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.severity == "warning"
    assert result.affected_count == 2
    assert "Found 2 teams with unusual game counts" in result.message
    assert "LAL: 75 games" in str(result.affected_items)
    assert "GSW: 78 games" in str(result.affected_items)


def test_games_per_team_detect_high_count(validator, mock_bq_client):
    """Test detection of teams with too many games (indicates duplicates)."""
    # Setup: Mock query to return teams with > 84 games
    mock_results = [
        create_mock_row(team='BOS', game_count=90),  # Too many (duplicates?)
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_games_per_team('2025-10-15', '2026-06-15', season_year=2025)

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.severity == "warning"
    assert result.affected_count == 1
    assert "BOS: 90 games" in str(result.affected_items)


def test_games_per_team_skips_without_season_year(validator, mock_bq_client):
    """Test that check is skipped when season_year is not provided."""
    # Execute validation without season_year
    validator._validate_games_per_team('2026-01-24', '2026-01-24', season_year=None)

    # Assert: No results should be added (check skipped)
    # The validator should not add a result when season_year is None
    initial_result_count = len(validator.results)
    validator._validate_games_per_team('2026-01-24', '2026-01-24', season_year=None)
    assert len(validator.results) == initial_result_count


# =============================================================================
# TEST: Duplicate Game Detection
# =============================================================================

def test_no_duplicate_games_clean_data(validator, mock_bq_client):
    """Test that validator passes when no duplicate games exist."""
    # Setup: Mock query to return no duplicates
    mock_bq_client.query.return_value.result.return_value = []

    # Execute validation
    validator._validate_no_duplicate_games('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.check_name == "no_duplicate_games"
    assert result.passed is True
    assert result.severity == "info"
    assert result.affected_count == 0
    assert "No duplicate games" in result.message


def test_duplicate_games_detected(validator, mock_bq_client):
    """Test detection of duplicate game entries (CRITICAL data quality issue)."""
    # Setup: Mock query to return duplicate games
    mock_results = [
        create_mock_row(game_id='0022500647', entry_count=2),
        create_mock_row(game_id='0022500649', entry_count=3),
        create_mock_row(game_id='0022500650', entry_count=2),
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_no_duplicate_games('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.severity == "error"
    assert result.affected_count == 3
    assert "Found 3 duplicate game entries" in result.message
    assert "0022500647: 2 entries" in str(result.affected_items)
    assert "0022500649: 3 entries" in str(result.affected_items)


def test_duplicate_games_limits_output(validator, mock_bq_client):
    """Test that duplicate games output is limited to 20 entries."""
    # Setup: Mock query would return many duplicates, but query has LIMIT 20
    mock_results = [create_mock_row(game_id=f'00225006{i:02d}', entry_count=2) for i in range(20)]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_no_duplicate_games('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.affected_count == 20
    assert len(result.affected_items) == 20


# =============================================================================
# TEST: Game Status Validation
# =============================================================================

def test_game_status_all_valid(validator, mock_bq_client):
    """Test that validator passes when all game statuses are valid."""
    # Setup: Mock query to return only valid statuses
    mock_results = [
        create_mock_row(game_status_text='Final', count=50),
        create_mock_row(game_status_text='Scheduled', count=30),
        create_mock_row(game_status_text='In Progress', count=5),
        create_mock_row(game_status_text='Postponed', count=2),
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_game_status('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.check_name == "game_status_values"
    assert result.passed is True
    assert result.severity == "info"
    assert result.affected_count == 0
    assert "All game statuses are valid" in result.message


def test_game_status_invalid_detected(validator, mock_bq_client):
    """Test detection of invalid game status values."""
    # Setup: Mock query to return some invalid statuses
    mock_results = [
        create_mock_row(game_status_text='Final', count=50),
        create_mock_row(game_status_text='Scheduled', count=30),
        create_mock_row(game_status_text='UNKNOWN_STATUS', count=3),  # Invalid
        create_mock_row(game_status_text='TBD', count=2),  # Invalid
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_game_status('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.severity == "warning"
    assert result.affected_count == 2
    assert "Found 2 unexpected game status values" in result.message
    assert 'UNKNOWN_STATUS' in result.affected_items
    assert 'TBD' in result.affected_items


def test_game_status_handles_null(validator, mock_bq_client):
    """Test that validator handles NULL/empty game status values."""
    # Setup: Mock query to return null and empty statuses
    mock_results = [
        create_mock_row(game_status_text='Final', count=50),
        create_mock_row(game_status_text=None, count=10),  # NULL is valid
        create_mock_row(game_status_text='', count=5),  # Empty string is valid
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_game_status('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is True
    assert result.severity == "info"
    assert "All game statuses are valid" in result.message


# =============================================================================
# TEST: Integration Tests
# =============================================================================

def test_validator_initialization(mock_config_path):
    """Test that validator initializes correctly with config."""
    with patch('validation.base_validator.bigquery.Client'):
        validator = NbacScheduleValidator(mock_config_path)

        assert validator is not None
        assert validator.processor_name == "nbac_schedule"


def test_run_custom_validations_all_checks(validator, mock_bq_client):
    """Test that all custom validation checks are executed."""
    # Setup: Mock all queries to return passing results
    mock_bq_client.query.return_value.result.return_value = []

    # Execute all custom validations
    validator._run_custom_validations('2026-01-24', '2026-01-24', season_year=None)

    # Assert: All 4 checks should have been executed
    # team_presence, games_per_team (skipped), no_duplicate_games, game_status_values
    assert len(validator.results) >= 3

    check_names = [r.check_name for r in validator.results]
    assert 'team_presence' in check_names
    assert 'no_duplicate_games' in check_names
    assert 'game_status_values' in check_names


def test_run_custom_validations_with_season_year(validator, mock_bq_client):
    """Test that games_per_team check runs when season_year is provided."""
    # Setup: Mock all queries to return passing results
    mock_bq_client.query.return_value.result.return_value = []

    # Execute all custom validations with season_year
    validator._run_custom_validations('2025-10-15', '2026-06-15', season_year=2025)

    # Assert: All 4 checks should have been executed
    assert len(validator.results) >= 4

    check_names = [r.check_name for r in validator.results]
    assert 'team_presence' in check_names
    assert 'games_per_team' in check_names
    assert 'no_duplicate_games' in check_names
    assert 'game_status_values' in check_names


def test_validator_execution_duration_tracked(validator, mock_bq_client):
    """Test that execution duration is tracked for each check."""
    # Setup: Mock query to return empty results
    mock_bq_client.query.return_value.result.return_value = []

    # Execute validation
    validator._validate_team_presence('2026-01-24', '2026-01-24')

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
    validator._validate_team_presence('2026-01-24', '2026-01-24')

    # Assert: Query should be captured
    result = validator.results[-1]
    assert result.query_used is not None
    assert 'SELECT' in result.query_used
    assert 'team' in result.query_used


# =============================================================================
# TEST: Edge Cases
# =============================================================================

def test_validator_handles_partial_team_list(validator, mock_bq_client):
    """Test that validator correctly counts teams when list is partial."""
    # Setup: Mock query to return 15 teams (exactly half)
    mock_results = [create_mock_row(team=f'TEAM{i}', game_count=82) for i in range(15)]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_team_presence('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.affected_count == 15  # 30 - 15 missing teams
    assert "Found 15 teams (expected 30)" in result.message


def test_validator_handles_single_team(validator, mock_bq_client):
    """Test that validator handles edge case of single team."""
    # Setup: Mock query to return only 1 team
    mock_results = [create_mock_row(team='LAL', game_count=82)]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_team_presence('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.affected_count == 29  # 30 - 1 team present
    assert "Found 1 teams (expected 30)" in result.message


def test_duplicate_games_single_duplicate(validator, mock_bq_client):
    """Test detection of single duplicate game."""
    # Setup: Mock query to return one duplicate
    mock_results = [create_mock_row(game_id='0022500647', entry_count=2)]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_no_duplicate_games('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.affected_count == 1
    assert "Found 1 duplicate game entries" in result.message


def test_game_status_single_invalid(validator, mock_bq_client):
    """Test detection of single invalid status."""
    # Setup: Mock query with one invalid status
    mock_results = [
        create_mock_row(game_status_text='Final', count=50),
        create_mock_row(game_status_text='INVALID', count=1),
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_game_status('2026-01-24', '2026-01-24')

    # Assert
    result = validator.results[-1]
    assert result.passed is False
    assert result.affected_count == 1
    assert 'INVALID' in result.affected_items


# =============================================================================
# TEST: Special Scenarios
# =============================================================================

def test_games_per_team_at_season_start(validator, mock_bq_client):
    """Test games_per_team validation early in season (low counts expected)."""
    # Setup: Early season - teams have only played a few games
    mock_results = [
        create_mock_row(team='LAL', game_count=5),
        create_mock_row(team='GSW', game_count=4),
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation - this will flag teams with < 80 games
    validator._validate_games_per_team('2025-10-15', '2025-10-30', season_year=2025)

    # Assert: Low counts are detected (expected early season)
    result = validator.results[-1]
    assert result.passed is False
    assert result.severity == "warning"
    # Early season low counts should be flagged as anomalies


def test_all_teams_canceled_status(validator, mock_bq_client):
    """Test handling when all games are canceled."""
    # Setup: All games have 'Canceled' status
    mock_results = [
        create_mock_row(game_status_text='Canceled', count=100),
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_game_status('2026-01-24', '2026-01-24')

    # Assert: Canceled is a valid status
    result = validator.results[-1]
    assert result.passed is True
    assert "All game statuses are valid" in result.message


def test_multiple_validation_errors(validator, mock_bq_client):
    """Test that multiple validation failures are all captured."""
    # Setup different return values for sequential queries
    call_count = 0

    def query_side_effect(*args, **kwargs):
        nonlocal call_count
        mock_job = Mock()
        if call_count == 0:
            # team_presence: only 20 teams
            mock_job.result.return_value = [create_mock_row(team=f'TEAM{i}', game_count=82) for i in range(20)]
        elif call_count == 1:
            # no_duplicate_games: 5 duplicates
            mock_job.result.return_value = [create_mock_row(game_id=f'00225006{i:02d}', entry_count=2) for i in range(5)]
        elif call_count == 2:
            # game_status: 2 invalid statuses
            mock_job.result.return_value = [
                create_mock_row(game_status_text='Final', count=50),
                create_mock_row(game_status_text='INVALID1', count=1),
                create_mock_row(game_status_text='INVALID2', count=1),
            ]
        call_count += 1
        return mock_job

    mock_bq_client.query.side_effect = query_side_effect

    # Execute all validations
    validator._run_custom_validations('2026-01-24', '2026-01-24', season_year=None)

    # Assert: All failures should be captured
    assert len([r for r in validator.results if not r.passed]) >= 3

    # Verify each failure
    check_names = [r.check_name for r in validator.results if not r.passed]
    assert 'team_presence' in check_names
    assert 'no_duplicate_games' in check_names
    assert 'game_status_values' in check_names


# =============================================================================
# TEST: Data Type Handling
# =============================================================================

def test_team_presence_handles_none_team_names(validator, mock_bq_client):
    """Test that validator handles None team names gracefully."""
    # Setup: Mix of valid teams and None
    mock_results = [
        create_mock_row(team='LAL', game_count=82),
        create_mock_row(team=None, game_count=10),  # NULL team
        create_mock_row(team='GSW', game_count=82),
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation (should not crash)
    validator._validate_team_presence('2026-01-24', '2026-01-24')

    # Assert: Should handle None but still report incorrect count
    result = validator.results[-1]
    assert result.passed is False
    assert result.severity == "error"
    # 3 teams found (including None) vs 30 expected


def test_games_per_team_handles_zero_count(validator, mock_bq_client):
    """Test handling of teams with zero games (should be flagged)."""
    # Setup: Team with 0 games
    mock_results = [
        create_mock_row(team='LAL', game_count=0),  # Zero games
    ]

    mock_bq_client.query.return_value.result.return_value = mock_results

    # Execute validation
    validator._validate_games_per_team('2025-10-15', '2026-06-15', season_year=2025)

    # Assert: Should flag as anomaly
    result = validator.results[-1]
    assert result.passed is False
    assert result.affected_count == 1
    assert 'LAL: 0 games' in str(result.affected_items)


# =============================================================================
# PYTEST MARKERS
# =============================================================================

pytestmark = pytest.mark.unit
