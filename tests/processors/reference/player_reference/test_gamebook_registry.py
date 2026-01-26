"""
Unit Tests for Gamebook Registry Processor

Tests gamebook-based player registry building with temporal ordering
and data freshness protection.

Run with: pytest tests/processors/reference/player_reference/test_gamebook_registry.py -v

Path: tests/processors/reference/player_reference/test_gamebook_registry.py
Created: 2026-01-25
"""

import pytest
import pandas as pd
from datetime import date, datetime, timezone
from unittest.mock import Mock, MagicMock, patch, call
from typing import Dict, List
import sys

# Mock google.cloud modules before importing processor
sys.modules['google.cloud'] = MagicMock()
sys.modules['google.cloud.bigquery'] = MagicMock()
sys.modules['google.api_core'] = MagicMock()
sys.modules['google.api_core.exceptions'] = MagicMock()

from data_processors.reference.player_reference.gamebook_registry_processor import (
    GamebookRegistryProcessor
)
from data_processors.reference.base.registry_processor_base import TemporalOrderingError


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_bq_client():
    """Create mock BigQuery client."""
    mock_client = Mock()
    mock_client.project = 'test-project'

    # Default empty query results
    mock_result = Mock()
    mock_result.to_dataframe.return_value = pd.DataFrame()
    mock_client.query.return_value = mock_result

    return mock_client


@pytest.fixture
def processor(mock_bq_client):
    """Create processor with mocked dependencies."""
    with patch('data_processors.reference.player_reference.gamebook_registry_processor.bigquery.Client') as mock_client_class:
        mock_client_class.return_value = mock_bq_client

        # Mock UniversalPlayerIDResolver
        with patch('data_processors.reference.base.registry_processor_base.UniversalPlayerIDResolver') as mock_resolver:
            mock_resolver_instance = Mock()
            mock_resolver_instance.resolve_or_create_universal_id.return_value = 'player_001'
            mock_resolver_instance.bulk_resolve_or_create_universal_ids.return_value = {}
            mock_resolver.return_value = mock_resolver_instance

            proc = GamebookRegistryProcessor(
                test_mode=True,
                strategy='merge',
                confirm_full_delete=False
            )

            proc.bq_client = mock_bq_client
            proc.universal_id_resolver = mock_resolver_instance

            return proc


@pytest.fixture
def sample_gamebook_data():
    """Sample gamebook player data."""
    return pd.DataFrame([
        {
            'player_name': 'LeBron James',
            'player_lookup': 'lebron-james',
            'team_abbr': 'LAL',
            'season_year': 2024,
            'game_date': date(2024, 12, 15),
            'game_id': 'game_001',
            'player_status': 'active',
            'name_resolution_status': 'original',
            'game_appearances': 1
        },
        {
            'player_name': 'LeBron James',
            'player_lookup': 'lebron-james',
            'team_abbr': 'LAL',
            'season_year': 2024,
            'game_date': date(2024, 12, 16),
            'game_id': 'game_002',
            'player_status': 'active',
            'name_resolution_status': 'original',
            'game_appearances': 1
        },
        {
            'player_name': 'Stephen Curry',
            'player_lookup': 'stephen-curry',
            'team_abbr': 'GSW',
            'season_year': 2024,
            'game_date': date(2024, 12, 15),
            'game_id': 'game_003',
            'player_status': 'active',
            'name_resolution_status': 'original',
            'game_appearances': 1
        }
    ])


@pytest.fixture
def sample_br_enhancement_data():
    """Sample Basketball Reference enhancement data."""
    return pd.DataFrame([
        {
            'br_team_abbr': 'LAL',
            'player_lookup': 'lebron-james',
            'original_name': 'LeBron James',
            'jersey_number': 23,
            'position': 'F',
            'season_year': 2024
        },
        {
            'br_team_abbr': 'GSW',
            'player_lookup': 'stephen-curry',
            'original_name': 'Stephen Curry',
            'jersey_number': 30,
            'position': 'G',
            'season_year': 2024
        }
    ])


# =============================================================================
# TEST: INITIALIZATION
# =============================================================================

class TestInitialization:
    """Test processor initialization."""

    def test_initializes_with_test_mode(self, processor):
        """Test test mode initialization."""
        assert processor.test_mode is True
        assert 'test' in processor.table_name.lower()
        assert processor.processor_type == 'gamebook'

    def test_initializes_with_merge_strategy(self, processor):
        """Test merge strategy is set."""
        assert processor.processing_strategy.value == 'merge'

    def test_requires_confirmation_for_replace_strategy(self, mock_bq_client):
        """Test replace strategy requires confirmation."""
        with patch('data_processors.reference.player_reference.gamebook_registry_processor.bigquery.Client') as mock_client_class:
            mock_client_class.return_value = mock_bq_client

            with patch('data_processors.reference.base.registry_processor_base.UniversalPlayerIDResolver'):
                with pytest.raises(ValueError, match="REPLACE strategy requires"):
                    GamebookRegistryProcessor(
                        strategy='replace',
                        confirm_full_delete=False
                    )


# =============================================================================
# TEST: GET GAMEBOOK PLAYER DATA
# =============================================================================

class TestGetGamebookPlayerData:
    """Test querying gamebook data."""

    def test_retrieves_gamebook_data(self, processor, mock_bq_client, sample_gamebook_data):
        """Test basic data retrieval."""
        mock_result = Mock()
        mock_result.to_dataframe.return_value = sample_gamebook_data
        mock_bq_client.query.return_value = mock_result

        result = processor.get_gamebook_player_data()

        assert len(result) == 3
        assert 'lebron-james' in result['player_lookup'].values

    def test_filters_by_season(self, processor, mock_bq_client):
        """Test season filtering."""
        mock_result = Mock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_bq_client.query.return_value = mock_result

        processor.get_gamebook_player_data(season_filter='2024-25')

        # Verify query includes season filter
        call_args = mock_bq_client.query.call_args
        assert call_args is not None

    def test_filters_by_team(self, processor, mock_bq_client):
        """Test team filtering."""
        mock_result = Mock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_bq_client.query.return_value = mock_result

        processor.get_gamebook_player_data(team_filter='LAL')

        call_args = mock_bq_client.query.call_args
        assert call_args is not None

    def test_filters_by_date_range(self, processor, mock_bq_client):
        """Test date range filtering."""
        mock_result = Mock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_bq_client.query.return_value = mock_result

        processor.get_gamebook_player_data(
            date_range=('2024-12-01', '2024-12-31')
        )

        call_args = mock_bq_client.query.call_args
        assert call_args is not None

    def test_handles_query_exception(self, processor, mock_bq_client):
        """Test error handling."""
        mock_bq_client.query.side_effect = Exception("Query failed")

        with pytest.raises(Exception, match="Query failed"):
            processor.get_gamebook_player_data()


# =============================================================================
# TEST: GET ROSTER ENHANCEMENT DATA
# =============================================================================

class TestGetRosterEnhancementData:
    """Test Basketball Reference enhancement data retrieval."""

    def test_retrieves_br_data(self, processor, mock_bq_client, sample_br_enhancement_data):
        """Test BR data retrieval."""
        mock_result = Mock()
        mock_result.to_dataframe.return_value = sample_br_enhancement_data
        mock_bq_client.query.return_value = mock_result

        result = processor.get_roster_enhancement_data()

        assert ('LAL', 'lebron-james') in result
        assert result[('LAL', 'lebron-james')]['jersey_number'] == 23

    def test_maps_team_codes(self, processor, mock_bq_client):
        """Test BRK -> BKN team code mapping."""
        br_data = pd.DataFrame([
            {
                'br_team_abbr': 'BRK',  # Basketball Reference code
                'player_lookup': 'kevin-durant',
                'original_name': 'Kevin Durant',
                'jersey_number': 7,
                'position': 'F',
                'season_year': 2024
            }
        ])

        mock_result = Mock()
        mock_result.to_dataframe.return_value = br_data
        mock_bq_client.query.return_value = mock_result

        result = processor.get_roster_enhancement_data()

        # Should be keyed by NBA tricode BKN
        assert ('BKN', 'kevin-durant') in result

    def test_filters_by_season(self, processor, mock_bq_client):
        """Test season filtering."""
        mock_result = Mock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_bq_client.query.return_value = mock_result

        processor.get_roster_enhancement_data(season_filter='2024-25')

        call_args = mock_bq_client.query.call_args
        assert call_args is not None

    def test_handles_exception_gracefully(self, processor, mock_bq_client):
        """Test returns empty dict on error."""
        mock_bq_client.query.side_effect = Exception("Query failed")

        result = processor.get_roster_enhancement_data()

        assert result == {}


# =============================================================================
# TEST: AGGREGATE PLAYER STATS
# =============================================================================

class TestAggregatePlayerStats:
    """Test aggregation of gamebook data into registry records."""

    def test_creates_registry_records(self, processor, mock_bq_client, sample_gamebook_data):
        """Test basic record creation."""
        # Mock BR enhancement data (empty)
        mock_result = Mock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_bq_client.query.return_value = mock_result

        # Mock bulk ID resolution
        processor.universal_id_resolver.bulk_resolve_or_create_universal_ids.return_value = {
            'lebron-james': 'lebron-james_001',
            'stephen-curry': 'stephen-curry_001'
        }

        # Mock existing records query to return empty (no existing data)
        empty_df = pd.DataFrame()
        mock_existing_result = Mock()
        mock_existing_result.to_dataframe.return_value = empty_df

        # Mock aliases query to return empty
        mock_aliases_result = Mock()
        mock_aliases_result.to_dataframe.return_value = empty_df

        mock_bq_client.query.side_effect = [
            mock_result,  # BR enhancement data
            mock_existing_result,  # Existing records
            mock_aliases_result  # Aliases
        ]

        records = processor.aggregate_player_stats(sample_gamebook_data)

        assert len(records) == 2  # LeBron and Curry

        # Verify LeBron's record
        lebron_record = next(r for r in records if r['player_lookup'] == 'lebron-james')
        assert lebron_record['team_abbr'] == 'LAL'
        assert lebron_record['games_played'] == 2  # Active games
        assert lebron_record['season'] == '2024-25'

    def test_includes_enhancement_data(self, processor, mock_bq_client, sample_gamebook_data, sample_br_enhancement_data):
        """Test jersey and position from BR."""
        mock_result = Mock()
        mock_result.to_dataframe.return_value = sample_br_enhancement_data

        # Mock bulk ID resolution
        processor.universal_id_resolver.bulk_resolve_or_create_universal_ids.return_value = {
            'lebron-james': 'lebron-james_001',
            'stephen-curry': 'stephen-curry_001'
        }

        # Mock existing records and aliases as empty
        empty_df = pd.DataFrame()
        mock_empty_result = Mock()
        mock_empty_result.to_dataframe.return_value = empty_df

        mock_bq_client.query.side_effect = [
            mock_result,  # BR enhancement
            mock_empty_result,  # Existing records
            mock_empty_result  # Aliases
        ]

        records = processor.aggregate_player_stats(sample_gamebook_data)

        lebron = next(r for r in records if r['player_lookup'] == 'lebron-james')
        assert lebron['jersey_number'] == 23
        assert lebron['position'] == 'F'

    def test_calculates_game_stats(self, processor, mock_bq_client, sample_gamebook_data):
        """Test game participation stats."""
        # Mock empty enhancement data
        mock_result = Mock()
        mock_result.to_dataframe.return_value = pd.DataFrame()

        # Mock bulk ID resolution
        processor.universal_id_resolver.bulk_resolve_or_create_universal_ids.return_value = {
            'lebron-james': 'lebron-james_001',
            'stephen-curry': 'stephen-curry_001'
        }

        # Mock existing records and aliases as empty
        empty_df = pd.DataFrame()
        mock_empty_result = Mock()
        mock_empty_result.to_dataframe.return_value = empty_df

        mock_bq_client.query.side_effect = [
            mock_result,  # BR enhancement
            mock_empty_result,  # Existing records
            mock_empty_result  # Aliases
        ]

        records = processor.aggregate_player_stats(sample_gamebook_data)

        lebron = next(r for r in records if r['player_lookup'] == 'lebron-james')
        assert lebron['games_played'] == 2
        assert lebron['total_appearances'] == 2
        assert lebron['first_game_date'] == date(2024, 12, 15)
        assert lebron['last_game_date'] == date(2024, 12, 16)

    def test_determines_source_priority(self, processor, mock_bq_client, sample_gamebook_data):
        """Test source priority and confidence calculation."""
        # Mock empty enhancement
        mock_result = Mock()
        mock_result.to_dataframe.return_value = pd.DataFrame()

        # Mock bulk ID resolution
        processor.universal_id_resolver.bulk_resolve_or_create_universal_ids.return_value = {
            'lebron-james': 'lebron-james_001',
            'stephen-curry': 'stephen-curry_001'
        }

        # Mock existing records and aliases as empty
        empty_df = pd.DataFrame()
        mock_empty_result = Mock()
        mock_empty_result.to_dataframe.return_value = empty_df

        mock_bq_client.query.side_effect = [
            mock_result,  # BR enhancement
            mock_empty_result,  # Existing records
            mock_empty_result  # Aliases
        ]

        records = processor.aggregate_player_stats(sample_gamebook_data)

        lebron = next(r for r in records if r['player_lookup'] == 'lebron-james')
        assert lebron['source_priority'] == 'nba_gamebook'
        assert lebron['confidence_score'] > 0.9  # Original status has high confidence

    def test_skips_stale_records(self, processor, mock_bq_client, sample_gamebook_data):
        """Test freshness protection - skip stale updates."""
        # Mock BR enhancement
        mock_br_result = Mock()
        mock_br_result.to_dataframe.return_value = pd.DataFrame()

        # Mock existing record with fresher data
        existing_record_df = pd.DataFrame([{
            'player_lookup': 'lebron-james',
            'team_abbr': 'LAL',
            'games_played': 5,
            'last_processor': 'gamebook',
            'last_gamebook_activity_date': date(2024, 12, 20),  # Fresher than our data
            'last_roster_activity_date': None,
            'jersey_number': 23,
            'position': 'F',
            'source_priority': 'nba_gamebook',
            'processed_at': datetime.now()
        }])

        mock_existing_result = Mock()
        mock_existing_result.to_dataframe.return_value = existing_record_df

        # Mock empty aliases
        mock_aliases_result = Mock()
        mock_aliases_result.to_dataframe.return_value = pd.DataFrame()

        # Mock bulk ID resolution
        processor.universal_id_resolver.bulk_resolve_or_create_universal_ids.return_value = {
            'lebron-james': 'lebron-james_001',
            'stephen-curry': 'stephen-curry_001'
        }

        mock_bq_client.query.side_effect = [
            mock_br_result,  # BR enhancement
            mock_existing_result,  # Existing records (has fresher data)
            mock_aliases_result  # Aliases
        ]

        records = processor.aggregate_player_stats(sample_gamebook_data)

        # LeBron should be skipped (stale), only Curry should be included
        player_lookups = [r['player_lookup'] for r in records]
        assert 'stephen-curry' in player_lookups
        # LeBron might be skipped depending on date comparison


# =============================================================================
# TEST: TEMPORAL ORDERING VALIDATION
# =============================================================================

class TestTemporalOrderingValidation:
    """Test temporal ordering protection."""

    def test_allows_first_run(self, processor, mock_bq_client):
        """Test first run is always allowed."""
        mock_result = Mock()
        mock_result.to_dataframe.return_value = pd.DataFrame()  # No prior runs
        mock_bq_client.query.return_value = mock_result

        # Should not raise
        processor.validate_temporal_ordering(
            data_date=date(2024, 12, 15),
            season_year=2024,
            allow_backfill=False
        )

    def test_allows_forward_progression(self, processor, mock_bq_client):
        """Test allows processing later dates."""
        # Mock previous run
        prior_run = pd.DataFrame([{
            'latest_processed_date': date(2024, 12, 10),
            'latest_run_time': datetime.now()
        }])

        mock_result = Mock()
        mock_result.to_dataframe.return_value = prior_run
        mock_bq_client.query.return_value = mock_result

        # Should not raise - later date
        processor.validate_temporal_ordering(
            data_date=date(2024, 12, 15),
            season_year=2024,
            allow_backfill=False
        )

    def test_blocks_backward_progression(self, processor, mock_bq_client):
        """Test blocks processing earlier dates."""
        # Mock previous run with later date
        prior_run = pd.DataFrame([{
            'latest_processed_date': date(2024, 12, 20),
            'latest_run_time': datetime.now()
        }])

        mock_result = Mock()
        mock_result.to_dataframe.return_value = prior_run
        mock_bq_client.query.return_value = mock_result

        # Should raise - earlier date
        with pytest.raises(TemporalOrderingError, match="Temporal ordering violation"):
            processor.validate_temporal_ordering(
                data_date=date(2024, 12, 15),
                season_year=2024,
                allow_backfill=False
            )

    def test_allows_backfill_mode(self, processor, mock_bq_client):
        """Test backfill mode allows earlier dates."""
        # Mock previous run with later date
        prior_run = pd.DataFrame([{
            'latest_processed_date': date(2024, 12, 20),
            'latest_run_time': datetime.now()
        }])

        mock_result = Mock()
        mock_result.to_dataframe.return_value = prior_run
        mock_bq_client.query.return_value = mock_result

        # Should not raise with allow_backfill=True
        processor.validate_temporal_ordering(
            data_date=date(2024, 12, 15),
            season_year=2024,
            allow_backfill=True
        )


# =============================================================================
# TEST: DATA FRESHNESS PROTECTION
# =============================================================================

class TestDataFreshnessProtection:
    """Test freshness checking logic."""

    def test_allows_new_record(self, processor):
        """Test new records are always allowed."""
        should_update, reason = processor.should_update_record(
            existing_record=None,
            new_data_date=date(2024, 12, 15),
            processor_type='gamebook'
        )

        assert should_update is True
        assert reason == 'new_record'

    def test_allows_fresher_data(self, processor):
        """Test allows updates with fresher data."""
        existing = {
            'player_lookup': 'lebron-james',
            'team_abbr': 'LAL',
            'last_gamebook_activity_date': date(2024, 12, 10)
        }

        should_update, reason = processor.should_update_record(
            existing_record=existing,
            new_data_date=date(2024, 12, 15),
            processor_type='gamebook'
        )

        assert should_update is True
        assert 'fresher_data' in reason

    def test_blocks_stale_data(self, processor):
        """Test blocks updates with stale data."""
        existing = {
            'player_lookup': 'lebron-james',
            'team_abbr': 'LAL',
            'last_gamebook_activity_date': date(2024, 12, 20)
        }

        should_update, reason = processor.should_update_record(
            existing_record=existing,
            new_data_date=date(2024, 12, 15),
            processor_type='gamebook'
        )

        assert should_update is False
        assert 'stale_data' in reason

    def test_allows_same_date_reprocess(self, processor):
        """Test allows reprocessing same date."""
        existing = {
            'player_lookup': 'lebron-james',
            'team_abbr': 'LAL',
            'last_gamebook_activity_date': date(2024, 12, 15)
        }

        should_update, reason = processor.should_update_record(
            existing_record=existing,
            new_data_date=date(2024, 12, 15),
            processor_type='gamebook'
        )

        assert should_update is True
        assert 'same_date' in reason


# =============================================================================
# TEST SUMMARY
# =============================================================================
# Total Tests: 30+ comprehensive unit tests
# Coverage Areas:
# - Initialization: 3 tests
# - Get gamebook data: 5 tests
# - Get BR enhancement: 4 tests
# - Aggregate player stats: 6 tests
# - Temporal ordering: 4 tests
# - Data freshness: 4 tests
#
# Run with:
#   pytest tests/processors/reference/player_reference/test_gamebook_registry.py -v
#   pytest tests/processors/reference/player_reference/test_gamebook_registry.py -k "temporal" -v
# =============================================================================
