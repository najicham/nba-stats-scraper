"""
Unit tests for change detection system

Tests PlayerChangeDetector and TeamChangeDetector for incremental processing.

Run:
    pytest tests/unit/shared/test_change_detector.py -v

Coverage:
    pytest tests/unit/shared/test_change_detector.py --cov=shared.change_detection --cov-report=html
"""

import pytest
from datetime import date
from unittest.mock import Mock, MagicMock, patch
from google.cloud import bigquery

# Import change detectors
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from shared.change_detection.change_detector import (
    ChangeDetector,
    PlayerChangeDetector,
    TeamChangeDetector
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_bigquery_client():
    """Mock BigQuery client."""
    with patch('shared.change_detection.change_detector.bigquery.Client') as mock_client:
        yield mock_client.return_value


@pytest.fixture
def sample_game_date():
    """Sample game date for testing."""
    return date(2025, 11, 29)


# ============================================================================
# TEST: PlayerChangeDetector
# ============================================================================

def test_player_change_detector_no_changes(mock_bigquery_client, sample_game_date):
    """Test when no players have changed data."""
    # Setup mock to return empty results
    mock_query_results = []
    mock_bigquery_client.query.return_value.result.return_value = mock_query_results

    # Create detector
    detector = PlayerChangeDetector(project_id='test-project')
    detector._client = mock_bigquery_client

    # Run change detection
    changed_players = detector.detect_changes(game_date=sample_game_date)

    # Verify
    assert changed_players == []
    assert mock_bigquery_client.query.called


def test_player_change_detector_some_changes(mock_bigquery_client, sample_game_date):
    """Test when some players have changed data."""
    # Setup mock to return changed players
    mock_row = Mock()
    mock_row.entity_id = 'lebron-james'
    mock_query_results = [mock_row]
    mock_bigquery_client.query.return_value.result.return_value = mock_query_results

    # Create detector
    detector = PlayerChangeDetector(project_id='test-project')
    detector._client = mock_bigquery_client

    # Run change detection
    changed_players = detector.detect_changes(game_date=sample_game_date)

    # Verify
    assert changed_players == ['lebron-james']
    assert mock_bigquery_client.query.called


def test_player_change_detector_multiple_changes(mock_bigquery_client, sample_game_date):
    """Test when multiple players have changed."""
    # Setup mock to return multiple changed players
    players = ['lebron-james', 'stephen-curry', 'kevin-durant']
    mock_query_results = [Mock(entity_id=p) for p in players]
    mock_bigquery_client.query.return_value.result.return_value = mock_query_results

    # Create detector
    detector = PlayerChangeDetector(project_id='test-project')
    detector._client = mock_bigquery_client

    # Run change detection
    changed_players = detector.detect_changes(game_date=sample_game_date)

    # Verify
    assert changed_players == players
    assert len(changed_players) == 3


def test_player_change_detector_query_error_returns_empty(mock_bigquery_client, sample_game_date):
    """Test graceful handling of query errors."""
    # Setup mock to raise exception
    mock_bigquery_client.query.side_effect = Exception("BigQuery error")

    # Create detector
    detector = PlayerChangeDetector(project_id='test-project')
    detector._client = mock_bigquery_client

    # Run change detection (should not raise, returns empty list)
    changed_players = detector.detect_changes(game_date=sample_game_date)

    # Verify - returns empty list on error (fall back to full batch)
    assert changed_players == []


def test_player_change_detector_count_total(mock_bigquery_client, sample_game_date):
    """Test counting total players."""
    # Setup mock
    mock_row = Mock(total=450)  # ~450 players in a typical NBA day
    mock_bigquery_client.query.return_value.result.return_value = [mock_row]

    # Create detector
    detector = PlayerChangeDetector(project_id='test-project')
    detector._client = mock_bigquery_client

    # Count total
    total = detector._count_total_entities(sample_game_date)

    # Verify
    assert total == 450


# ============================================================================
# TEST: TeamChangeDetector
# ============================================================================

def test_team_change_detector_no_changes(mock_bigquery_client, sample_game_date):
    """Test when no teams have changed data."""
    # Setup mock
    mock_bigquery_client.query.return_value.result.return_value = []

    # Create detector
    detector = TeamChangeDetector(project_id='test-project')
    detector._client = mock_bigquery_client

    # Run change detection
    changed_teams = detector.detect_changes(game_date=sample_game_date)

    # Verify
    assert changed_teams == []


def test_team_change_detector_some_changes(mock_bigquery_client, sample_game_date):
    """Test when some teams have changed."""
    # Setup mock
    teams = ['LAL', 'GSW', 'BOS']
    mock_query_results = [Mock(entity_id=t) for t in teams]
    mock_bigquery_client.query.return_value.result.return_value = mock_query_results

    # Create detector
    detector = TeamChangeDetector(project_id='test-project')
    detector._client = mock_bigquery_client

    # Run change detection
    changed_teams = detector.detect_changes(game_date=sample_game_date)

    # Verify
    assert changed_teams == teams
    assert len(changed_teams) == 3


def test_team_change_detector_count_total(mock_bigquery_client, sample_game_date):
    """Test counting total teams."""
    # Setup mock
    mock_row = Mock(total=30)  # 30 NBA teams
    mock_bigquery_client.query.return_value.result.return_value = [mock_row]

    # Create detector
    detector = TeamChangeDetector(project_id='test-project')
    detector._client = mock_bigquery_client

    # Count total
    total = detector._count_total_entities(sample_game_date)

    # Verify
    assert total == 30


# ============================================================================
# TEST: Change Statistics
# ============================================================================

def test_get_change_stats_incremental(mock_bigquery_client, sample_game_date):
    """Test change statistics for incremental run."""
    # Setup: 1 player changed out of 450 total
    mock_row = Mock(total=450)
    mock_bigquery_client.query.return_value.result.return_value = [mock_row]

    detector = PlayerChangeDetector(project_id='test-project')
    detector._client = mock_bigquery_client

    changed_entities = ['lebron-james']  # Only 1 changed

    # Get stats
    stats = detector.get_change_stats(
        game_date=sample_game_date,
        changed_entities=changed_entities
    )

    # Verify
    assert stats['entities_total'] == 450
    assert stats['entities_changed'] == 1
    assert stats['entities_skipped'] == 449
    assert stats['efficiency_gain_pct'] == pytest.approx(99.8, rel=0.1)
    assert stats['is_incremental'] is True


def test_get_change_stats_full_batch(mock_bigquery_client, sample_game_date):
    """Test change statistics for full batch (all changed)."""
    # Setup: All 450 players changed
    mock_row = Mock(total=450)
    mock_bigquery_client.query.return_value.result.return_value = [mock_row]

    detector = PlayerChangeDetector(project_id='test-project')
    detector._client = mock_bigquery_client

    # All changed
    changed_entities = [f'player-{i}' for i in range(450)]

    # Get stats
    stats = detector.get_change_stats(
        game_date=sample_game_date,
        changed_entities=changed_entities
    )

    # Verify
    assert stats['entities_total'] == 450
    assert stats['entities_changed'] == 450
    assert stats['entities_skipped'] == 0
    assert stats['efficiency_gain_pct'] == 0.0
    assert stats['is_incremental'] is False  # All changed = not incremental


def test_get_change_stats_moderate_changes(mock_bigquery_client, sample_game_date):
    """Test change statistics with moderate changes (~10%)."""
    # Setup: 45 players changed out of 450
    mock_row = Mock(total=450)
    mock_bigquery_client.query.return_value.result.return_value = [mock_row]

    detector = PlayerChangeDetector(project_id='test-project')
    detector._client = mock_bigquery_client

    changed_entities = [f'player-{i}' for i in range(45)]  # 10% changed

    # Get stats
    stats = detector.get_change_stats(
        game_date=sample_game_date,
        changed_entities=changed_entities
    )

    # Verify
    assert stats['entities_total'] == 450
    assert stats['entities_changed'] == 45
    assert stats['entities_skipped'] == 405
    assert stats['efficiency_gain_pct'] == 90.0
    assert stats['is_incremental'] is True


# ============================================================================
# TEST: Custom Change Detection Fields
# ============================================================================

def test_player_change_detector_custom_fields(mock_bigquery_client, sample_game_date):
    """Test using custom change detection fields."""
    # This test verifies the query is built correctly with custom fields
    detector = PlayerChangeDetector(project_id='test-project')
    detector._client = mock_bigquery_client

    custom_fields = ['minutes', 'points']  # Only check these 2 fields

    # Build query with custom fields
    query = detector._build_change_detection_query(
        game_date=sample_game_date,
        change_detection_fields=custom_fields
    )

    # Verify query contains our custom fields
    assert 'minutes' in query
    assert 'points' in query

    # Verify the comparison logic
    assert 'r.minutes IS DISTINCT FROM p.minutes' in query
    assert 'r.points IS DISTINCT FROM p.points' in query


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
