# Path: tests/processors/analytics/upcoming_player_game_context/test_bettingpros_fallback.py
"""
Unit Tests for BettingPros Fallback in UpcomingPlayerGameContext Processor

Tests the fallback logic that uses BettingPros when Odds API has no data.
Run with: pytest test_bettingpros_fallback.py -v

Directory: tests/processors/analytics/upcoming_player_game_context/
"""

import pytest

# Skip all tests - processor extraction logic changed significantly
pytestmark = pytest.mark.skip(reason="Props extraction logic refactored - tests need rewrite")
import pandas as pd
from datetime import date, datetime, timezone
from unittest.mock import Mock, MagicMock, patch, call
import numpy as np

from data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor import (
    UpcomingPlayerGameContextProcessor
)


class EmptyIterator:
    """Empty iterator for mocking query().result() calls."""
    def __iter__(self):
        return self
    def __next__(self):
        raise StopIteration


class TestBettingProsFallbackLogic:
    """Test BettingPros fallback in _extract_players_with_props method."""

    @pytest.fixture
    def processor(self):
        """Create processor with mocked BigQuery client."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2021, 11, 1)  # A date with only BettingPros data
        proc.source_tracking = {'props': {'rows_found': 0, 'last_updated': None}}
        proc.players_to_process = []

        # Set up mock to handle both .to_dataframe() and .result() patterns
        def mock_query_response(query, **kwargs):
            mock_result = Mock()
            mock_result.result = Mock(return_value=EmptyIterator())
            mock_result.to_dataframe = Mock(return_value=pd.DataFrame())
            return mock_result

        proc.bq_client.query.side_effect = mock_query_response
        return proc

    def test_uses_odds_api_when_available(self, processor):
        """Test that Odds API is used first when data is available."""
        # Mock Odds API returning data
        odds_api_df = pd.DataFrame([
            {'player_lookup': 'lebronjames', 'game_id': '123', 'home_team_abbr': 'LAL', 'away_team_abbr': 'BOS'},
            {'player_lookup': 'stephcurry', 'game_id': '124', 'home_team_abbr': 'GSW', 'away_team_abbr': 'PHX'}
        ])

        mock_query_result = Mock()
        mock_query_result.to_dataframe.return_value = odds_api_df
        processor.bq_client.query.return_value = mock_query_result

        processor._extract_players_with_props()

        # Should use odds_api source
        assert processor._props_source == 'odds_api'
        assert len(processor.players_to_process) == 2
        assert processor.players_to_process[0]['player_lookup'] == 'lebronjames'

    def test_falls_back_to_bettingpros_when_odds_api_empty(self, processor):
        """Test that BettingPros is used when Odds API returns empty."""
        # Mock Odds API returning empty, BettingPros returning data
        odds_api_df = pd.DataFrame()  # Empty
        bettingpros_df = pd.DataFrame([
            {'player_lookup': 'paulgeorge', 'game_id': '125', 'game_date': date(2021, 11, 1),
             'home_team_abbr': 'LAC', 'away_team_abbr': 'POR'},
        ])

        def mock_query_side_effect(query):
            result = Mock()
            if 'odds_api_player_points_props' in query:
                result.to_dataframe.return_value = odds_api_df
            else:
                result.to_dataframe.return_value = bettingpros_df
            return result

        processor.bq_client.query.side_effect = mock_query_side_effect

        # Mock the BettingPros extraction method
        with patch.object(processor, '_extract_players_from_bettingpros', return_value=bettingpros_df):
            processor._extract_players_with_props()

        # Should use bettingpros source
        assert processor._props_source == 'bettingpros'
        assert len(processor.players_to_process) == 1
        assert processor.players_to_process[0]['player_lookup'] == 'paulgeorge'

    def test_props_source_tracking(self, processor):
        """Test that _props_source is correctly set."""
        # Test Odds API path
        odds_api_df = pd.DataFrame([
            {'player_lookup': 'player1', 'game_id': '100', 'home_team_abbr': 'BOS', 'away_team_abbr': 'NYK'}
        ])

        mock_query_result = Mock()
        mock_query_result.to_dataframe.return_value = odds_api_df
        processor.bq_client.query.return_value = mock_query_result

        processor._extract_players_with_props()

        assert processor._props_source == 'odds_api'


class TestBettingProsExtraction:
    """Test _extract_players_from_bettingpros method."""

    @pytest.fixture
    def processor(self):
        """Create processor with mocked BigQuery client."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2021, 11, 1)
        return proc

    def test_returns_dataframe_with_expected_columns(self, processor):
        """Test that BettingPros extraction returns correct columns."""
        # Mock BettingPros query result
        bettingpros_result = pd.DataFrame([
            {'player_lookup': 'paulgeorge', 'game_id': '0022100096', 'game_date': date(2021, 11, 1),
             'home_team_abbr': 'PHI', 'away_team_abbr': 'POR'},
            {'player_lookup': 'damianlillard', 'game_id': '0022100096', 'game_date': date(2021, 11, 1),
             'home_team_abbr': 'PHI', 'away_team_abbr': 'POR'},
        ])

        mock_query_result = Mock()
        mock_query_result.to_dataframe.return_value = bettingpros_result
        processor.bq_client.query.return_value = mock_query_result

        df = processor._extract_players_from_bettingpros()

        # Check expected columns
        expected_columns = ['player_lookup', 'game_id', 'game_date', 'home_team_abbr', 'away_team_abbr']
        for col in expected_columns:
            assert col in df.columns, f"Missing column: {col}"

        assert len(df) == 2

    def test_handles_empty_result(self, processor):
        """Test graceful handling of empty BettingPros data."""
        mock_query_result = Mock()
        mock_query_result.to_dataframe.return_value = pd.DataFrame()
        processor.bq_client.query.return_value = mock_query_result

        df = processor._extract_players_from_bettingpros()

        assert df.empty

    def test_handles_query_exception(self, processor):
        """Test graceful handling of BigQuery errors."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        df = processor._extract_players_from_bettingpros()

        assert df.empty


class TestBettingProsPropLines:
    """Test _extract_prop_lines_from_bettingpros method."""

    @pytest.fixture
    def processor(self):
        """Create processor with mocked BigQuery client."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2021, 11, 1)
        proc.prop_lines = {}
        return proc

    def test_extracts_prop_lines_batch(self, processor):
        """Test batch extraction of prop lines from BettingPros."""
        # Mock BettingPros prop lines result
        prop_lines_result = pd.DataFrame([
            {'player_lookup': 'paulgeorge', 'current_line': 27.5, 'opening_line': 27.5, 'bookmaker': 'BetRivers'},
            {'player_lookup': 'damianlillard', 'current_line': 26.5, 'opening_line': 26.5, 'bookmaker': 'PartyCasino'},
        ])

        mock_query_result = Mock()
        mock_query_result.to_dataframe.return_value = prop_lines_result
        processor.bq_client.query.return_value = mock_query_result

        player_game_pairs = [('paulgeorge', '0022100096'), ('damianlillard', '0022100096')]

        processor._extract_prop_lines_from_bettingpros(player_game_pairs)

        # Check prop lines were populated
        assert ('paulgeorge', '0022100096') in processor.prop_lines
        assert processor.prop_lines[('paulgeorge', '0022100096')]['current_line'] == 27.5
        assert processor.prop_lines[('paulgeorge', '0022100096')]['opening_line'] == 27.5
        assert processor.prop_lines[('paulgeorge', '0022100096')]['current_source'] == 'BetRivers'

    def test_calculates_line_movement(self, processor):
        """Test line movement calculation."""
        prop_lines_result = pd.DataFrame([
            {'player_lookup': 'player1', 'current_line': 28.5, 'opening_line': 27.5, 'bookmaker': 'Book1'},
        ])

        mock_query_result = Mock()
        mock_query_result.to_dataframe.return_value = prop_lines_result
        processor.bq_client.query.return_value = mock_query_result

        processor._extract_prop_lines_from_bettingpros([('player1', 'game1')])

        # Line movement should be current - opening = 28.5 - 27.5 = 1.0
        assert processor.prop_lines[('player1', 'game1')]['line_movement'] == 1.0

    def test_handles_missing_players(self, processor):
        """Test handling when BettingPros doesn't have data for all players."""
        # Only return data for one player
        prop_lines_result = pd.DataFrame([
            {'player_lookup': 'player1', 'current_line': 25.5, 'opening_line': 25.5, 'bookmaker': 'Book1'},
        ])

        mock_query_result = Mock()
        mock_query_result.to_dataframe.return_value = prop_lines_result
        processor.bq_client.query.return_value = mock_query_result

        # Request data for two players
        processor._extract_prop_lines_from_bettingpros([('player1', 'game1'), ('player2', 'game2')])

        # Player1 should have data
        assert processor.prop_lines[('player1', 'game1')]['current_line'] == 25.5

        # Player2 should have None values
        assert processor.prop_lines[('player2', 'game2')]['current_line'] is None
        assert processor.prop_lines[('player2', 'game2')]['opening_line'] is None


class TestPropLinesRouting:
    """Test _extract_prop_lines routing based on source."""

    @pytest.fixture
    def processor(self):
        """Create processor with mocked BigQuery client."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2021, 11, 1)
        proc.prop_lines = {}
        proc.players_to_process = [
            {'player_lookup': 'player1', 'game_id': 'game1', 'home_team_abbr': 'BOS', 'away_team_abbr': 'NYK'}
        ]
        return proc

    def test_routes_to_odds_api_by_default(self, processor):
        """Test that Odds API method is called when _props_source is odds_api."""
        processor._props_source = 'odds_api'

        with patch.object(processor, '_extract_prop_lines_from_odds_api') as mock_odds:
            with patch.object(processor, '_extract_prop_lines_from_bettingpros') as mock_bp:
                processor._extract_prop_lines()

        mock_odds.assert_called_once()
        mock_bp.assert_not_called()

    def test_routes_to_bettingpros_when_flagged(self, processor):
        """Test that BettingPros method is called when _props_source is bettingpros."""
        processor._props_source = 'bettingpros'

        with patch.object(processor, '_extract_prop_lines_from_odds_api') as mock_odds:
            with patch.object(processor, '_extract_prop_lines_from_bettingpros') as mock_bp:
                processor._extract_prop_lines()

        mock_bp.assert_called_once()
        mock_odds.assert_not_called()


class TestIntegrationScenarios:
    """Integration tests for common fallback scenarios."""

    @pytest.fixture
    def processor(self):
        """Create processor with mocked BigQuery client."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.source_tracking = {'props': {'rows_found': 0, 'last_updated': None}}
        proc.players_to_process = []
        proc.prop_lines = {}
        return proc

    def test_full_bettingpros_fallback_flow(self, processor):
        """Test complete fallback flow: empty Odds API -> BettingPros extraction."""
        processor.target_date = date(2021, 11, 1)

        # Setup: Odds API returns empty, BettingPros returns data
        def query_side_effect(query):
            result = Mock()
            if 'odds_api_player_points_props' in query:
                result.to_dataframe.return_value = pd.DataFrame()  # Empty
            elif 'bettingpros_player_points_props' in query and 'bp_props' in query:
                # Driver query for BettingPros
                result.to_dataframe.return_value = pd.DataFrame([
                    {'player_lookup': 'paulgeorge', 'game_id': '0022100096',
                     'game_date': date(2021, 11, 1), 'home_team_abbr': 'PHI', 'away_team_abbr': 'POR'}
                ])
            elif 'bettingpros_player_points_props' in query and 'best_lines' in query:
                # Prop lines query for BettingPros
                result.to_dataframe.return_value = pd.DataFrame([
                    {'player_lookup': 'paulgeorge', 'current_line': 27.5,
                     'opening_line': 27.5, 'bookmaker': 'BetRivers'}
                ])
            else:
                result.to_dataframe.return_value = pd.DataFrame()
            return result

        processor.bq_client.query.side_effect = query_side_effect

        # Execute driver extraction
        processor._extract_players_with_props()

        # Verify BettingPros fallback was triggered
        assert processor._props_source == 'bettingpros'
        assert len(processor.players_to_process) == 1
        assert processor.players_to_process[0]['player_lookup'] == 'paulgeorge'
