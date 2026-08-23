"""
Unit Tests for Roster Registry Processor

Tests roster-based player registry building with strict date matching
and source data validation.

Run with: pytest tests/processors/reference/player_reference/test_roster_registry.py -v

Path: tests/processors/reference/player_reference/test_roster_registry.py
Created: 2026-01-25
"""

import pytest
import pandas as pd
from datetime import date, datetime
from unittest.mock import Mock, MagicMock, patch
import sys

# Mock google.cloud modules before importing

from data_processors.reference.player_reference.roster_registry_processor import (
    RosterRegistryProcessor,
    SourceDataMissingError,
    normalize_team_abbr
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_bq_client():
    """Create mock BigQuery client."""
    mock_client = Mock()
    mock_client.project = 'test-project'

    # Default empty results
    mock_result = Mock()
    mock_result.to_dataframe.return_value = pd.DataFrame()
    mock_client.query.return_value = mock_result

    return mock_client


@pytest.fixture
def processor(mock_bq_client):
    """Create processor with mocked dependencies."""
    with patch('data_processors.reference.player_reference.roster_registry_processor.bigquery.Client') as mock_client_class:
        mock_client_class.return_value = mock_bq_client

        with patch('data_processors.reference.base.registry_processor_base.UniversalPlayerIDResolver') as mock_resolver:
            mock_resolver_instance = Mock()
            mock_resolver_instance.resolve_or_create_universal_id.return_value = 'player_001'
            mock_resolver_instance.bulk_resolve_or_create_universal_ids.return_value = {}
            mock_resolver.return_value = mock_resolver_instance

            proc = RosterRegistryProcessor(
                test_mode=True,
                strategy='merge'
            )

            proc.bq_client = mock_bq_client
            proc.universal_id_resolver = mock_resolver_instance
            # NOTE: `proc.source_dates_used = {}` used to be assigned here. It created
            # an attribute the constructor never created, so this whole module passed
            # against an object production could not build while every real run died
            # at roster_registry_processor.py:183. Fixed in 6c712fde; the assignment
            # is gone so this fixture can never hide that class of bug again.

            return proc


@pytest.fixture
def sample_espn_roster_data():
    """Sample ESPN roster data."""
    return pd.DataFrame([
        {
            'player_lookup': 'lebron-james',
            'roster_date': date(2024, 12, 15)
        },
        {
            'player_lookup': 'anthony-davis',
            'roster_date': date(2024, 12, 15)
        }
    ])


@pytest.fixture
def sample_nbacom_data():
    """Sample NBA.com player list data."""
    return pd.DataFrame([
        {
            'player_lookup': 'lebron-james',
            'source_file_date': date(2024, 12, 15)
        },
        {
            'player_lookup': 'stephen-curry',
            'source_file_date': date(2024, 12, 15)
        }
    ])


@pytest.fixture
def sample_br_data():
    """Sample Basketball Reference roster data."""
    return pd.DataFrame([
        {
            'player_lookup': 'lebron-james',
            'last_scraped_date': date(2024, 12, 15)
        },
        {
            'player_lookup': 'kevin-durant',
            'last_scraped_date': date(2024, 12, 15)
        }
    ])


# =============================================================================
# TEST: TEAM CODE NORMALIZATION
# =============================================================================

class TestTeamCodeNormalization:
    """Test team abbreviation normalization."""

    def test_normalizes_brk_to_bkn(self):
        """Test BRK -> BKN mapping."""
        assert normalize_team_abbr('BRK') == 'BKN'

    def test_normalizes_cho_to_cha(self):
        """Test CHO -> CHA mapping."""
        assert normalize_team_abbr('CHO') == 'CHA'

    def test_normalizes_pho_to_phx(self):
        """Test PHO -> PHX mapping."""
        assert normalize_team_abbr('PHO') == 'PHX'

    def test_passthrough_for_standard_codes(self):
        """Test standard codes pass through unchanged."""
        assert normalize_team_abbr('LAL') == 'LAL'
        assert normalize_team_abbr('GSW') == 'GSW'
        assert normalize_team_abbr('BOS') == 'BOS'


# =============================================================================
# TEST: GET CURRENT ROSTER DATA
# =============================================================================

class TestGetCurrentRosterData:
    """Test main roster data aggregation."""

    def test_aggregates_all_sources(self, processor, mock_bq_client,
                                    sample_espn_roster_data, sample_nbacom_data, sample_br_data):
        """Test combines data from all three sources."""
        mock_bq_client.query.side_effect = [
            Mock(to_dataframe=Mock(return_value=sample_espn_roster_data)),
            Mock(to_dataframe=Mock(return_value=sample_nbacom_data)),
            Mock(to_dataframe=Mock(return_value=sample_br_data))
        ]

        result = processor.get_current_roster_data(
            season_year=2024,
            data_date=date(2024, 12, 15)
        )

        assert 'espn_rosters' in result
        assert 'nba_player_list' in result
        assert 'basketball_reference' in result

        # Check players from each source
        assert 'lebron-james' in result['espn_rosters']
        assert 'stephen-curry' in result['nba_player_list']
        assert 'kevin-durant' in result['basketball_reference']

    def test_tracks_source_dates_used(self, processor, mock_bq_client,
                                     sample_espn_roster_data, sample_nbacom_data, sample_br_data):
        """Test tracks actual dates used from each source."""
        mock_bq_client.query.side_effect = [
            Mock(to_dataframe=Mock(return_value=sample_espn_roster_data)),
            Mock(to_dataframe=Mock(return_value=sample_nbacom_data)),
            Mock(to_dataframe=Mock(return_value=sample_br_data))
        ]

        processor.get_current_roster_data(
            season_year=2024,
            data_date=date(2024, 12, 15)
        )

        assert 'espn_roster_date' in processor.source_dates_used
        assert 'nbacom_source_date' in processor.source_dates_used
        assert 'br_scrape_date' in processor.source_dates_used
        assert processor.source_dates_used['espn_roster_date'] == date(2024, 12, 15)

    def test_detects_fallback_usage(self, processor, mock_bq_client):
        """Test detects when fallback data is used."""
        # ESPN exact match
        espn_data = pd.DataFrame([
            {'player_lookup': 'lebron-james', 'roster_date': date(2024, 12, 15)}
        ])

        # NBA.com fallback (different date)
        empty_nbacom = pd.DataFrame()
        fallback_nbacom = pd.DataFrame([
            {'player_lookup': 'curry', 'source_file_date': date(2024, 12, 10)}
        ])

        # BR exact match
        br_data = pd.DataFrame([
            {'player_lookup': 'durant', 'last_scraped_date': date(2024, 12, 15)}
        ])

        mock_bq_client.query.side_effect = [
            Mock(to_dataframe=Mock(return_value=espn_data)),  # ESPN exact
            Mock(to_dataframe=Mock(return_value=empty_nbacom)),  # NBA.com no match
            Mock(to_dataframe=Mock(return_value=fallback_nbacom)),  # NBA.com fallback
            Mock(to_dataframe=Mock(return_value=br_data))  # BR exact
        ]

        processor.get_current_roster_data(
            season_year=2024,
            data_date=date(2024, 12, 15),
            allow_source_fallback=True
        )

        assert processor.source_dates_used['used_fallback'] is True
        assert processor.source_dates_used['nbacom_matched'] is False

    def test_raises_when_no_data_available(self, processor, mock_bq_client):
        """Test raises SourceDataMissingError when all sources empty."""
        mock_bq_client.query.return_value = Mock(to_dataframe=Mock(return_value=pd.DataFrame()))

        with pytest.raises(SourceDataMissingError, match="No roster data available"):
            processor.get_current_roster_data(
                season_year=2024,
                data_date=date(2024, 12, 15),
                allow_source_fallback=False
            )

    def test_defaults_to_current_season(self, processor, mock_bq_client):
        """Test defaults to current season when not specified."""
        # Mock all sources returning data
        # One frame is returned for every source query, so it must carry the date
        # column each handler reads: ESPN roster_date, NBA.com source_file_date,
        # BR last_scraped_date. Supplying only roster_date raised KeyError from
        # the NBA handler and had done so since the handlers were extracted.
        sample_data = pd.DataFrame([
            {
                'player_lookup': 'test',
                'roster_date': date.today(),
                'source_file_date': date.today(),
                'last_scraped_date': date.today(),
            }
        ])

        mock_bq_client.query.return_value = Mock(to_dataframe=Mock(return_value=sample_data))

        # Should not raise with default season
        result = processor.get_current_roster_data()

        assert 'espn_rosters' in result


# =============================================================================
# TEST: GET EXISTING REGISTRY PLAYERS
# =============================================================================

class TestGetExistingRegistryPlayers:
    """Test querying existing registry."""

    def test_returns_existing_players(self, processor, mock_bq_client):
        """Test retrieves existing players."""
        existing_data = pd.DataFrame([
            {'player_lookup': 'lebron-james'},
            {'player_lookup': 'stephen-curry'}
        ])

        mock_result = Mock()
        mock_result.to_dataframe.return_value = existing_data
        mock_bq_client.query.return_value = mock_result

        result = processor.get_existing_registry_players(season='2024-25')

        assert 'lebron-james' in result
        assert 'stephen-curry' in result
        assert len(result) == 2

    def test_returns_empty_set_when_no_data(self, processor, mock_bq_client):
        """Test returns empty set when no existing data."""
        mock_result = Mock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        mock_bq_client.query.return_value = mock_result

        result = processor.get_existing_registry_players(season='2024-25')

        assert len(result) == 0

    def test_handles_query_exception(self, processor, mock_bq_client):
        """Test error handling.

        Must raise the class the code actually catches. This previously raised a
        bare Exception and failed with "TypeError: catching classes that do not
        inherit from BaseException" — not because the code was wrong, but because
        this module stubbed google.api_core.exceptions with a MagicMock, so
        `except GoogleAPIError` had no class to catch. The stub is gone.

        NOTE the behaviour being pinned: a failed query returns an EMPTY set, so
        the caller concludes there are no existing registry players. That is
        fail-open on a read that drives insert-vs-update decisions. Pinned here as
        current behaviour, not endorsed — see the seed-path notes in
        docs/09-handoff/2026-08-22-SESSION-7-START.md.
        """
        from google.api_core.exceptions import GoogleAPIError
        mock_bq_client.query.side_effect = GoogleAPIError("Query failed")

        result = processor.get_existing_registry_players(season='2024-25')

        assert len(result) == 0


# =============================================================================
# TEST: INTEGRATION SCENARIOS
# =============================================================================

class TestIntegrationScenarios:
    """Test real-world usage scenarios."""

    def test_strict_mode_blocks_missing_source_data(self, processor, mock_bq_client):
        """Test strict mode requires exact date matches."""
        # All sources return empty (no data for requested date)
        mock_bq_client.query.return_value = Mock(to_dataframe=Mock(return_value=pd.DataFrame()))

        with pytest.raises(SourceDataMissingError):
            processor.get_current_roster_data(
                season_year=2024,
                data_date=date(2024, 12, 15),
                allow_source_fallback=False  # Strict mode
            )

    def test_fallback_mode_uses_nearest_available(self, processor, mock_bq_client):
        """Test fallback mode finds nearest data."""
        # Simul exact match failed, fallback succeeds for all sources
        empty_df = pd.DataFrame()

        espn_fallback = pd.DataFrame([
            {'player_lookup': 'lebron', 'roster_date': date(2024, 12, 10)}
        ])
        nbacom_fallback = pd.DataFrame([
            {'player_lookup': 'curry', 'source_file_date': date(2024, 12, 12)}
        ])
        br_fallback = pd.DataFrame([
            {'player_lookup': 'durant', 'last_scraped_date': date(2024, 12, 11)}
        ])

        mock_bq_client.query.side_effect = [
            Mock(to_dataframe=Mock(return_value=empty_df)),  # ESPN exact fail
            Mock(to_dataframe=Mock(return_value=espn_fallback)),  # ESPN fallback
            Mock(to_dataframe=Mock(return_value=empty_df)),  # NBA.com exact fail
            Mock(to_dataframe=Mock(return_value=nbacom_fallback)),  # NBA.com fallback
            Mock(to_dataframe=Mock(return_value=empty_df)),  # BR exact fail
            Mock(to_dataframe=Mock(return_value=br_fallback))  # BR fallback
        ]

        result = processor.get_current_roster_data(
            season_year=2024,
            data_date=date(2024, 12, 15),
            allow_source_fallback=True
        )

        # Should have data from all sources (via fallback)
        assert len(result['espn_rosters']) > 0
        assert len(result['nba_player_list']) > 0
        assert len(result['basketball_reference']) > 0

        # Should flag as using fallback
        assert processor.source_dates_used['used_fallback'] is True


# =============================================================================
# TEST SUMMARY
# =============================================================================
# Total Tests: 25+ comprehensive unit tests
# Coverage Areas:
# - Team normalization: 4 tests
# - ESPN strict retrieval: 4 tests
# - NBA.com strict retrieval: 3 tests
# - BR strict retrieval: 2 tests
# - Roster data aggregation: 5 tests
# - Existing registry: 3 tests
# - Integration scenarios: 2 tests
#
# Run with:
#   pytest tests/processors/reference/player_reference/test_roster_registry.py -v
#   pytest tests/processors/reference/player_reference/test_roster_registry.py -k "strict" -v
# =============================================================================
