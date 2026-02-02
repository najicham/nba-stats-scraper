#!/usr/bin/env python3
"""
Tests for PlayerMovementRegistryProcessor

Tests the processor's ability to update player registry from trade data.
"""

import pytest
from datetime import datetime, date, timedelta, timezone
import pandas as pd
from unittest.mock import Mock, MagicMock, patch

from data_processors.reference.player_reference.player_movement_registry_processor import (
    PlayerMovementRegistryProcessor,
    normalize_team_abbr,
    process_recent_trades
)


class TestTeamNormalization:
    """Test team abbreviation normalization."""

    def test_normalize_standard_teams(self):
        """Test normalization of standard team codes."""
        assert normalize_team_abbr('LAL') == 'LAL'
        assert normalize_team_abbr('BOS') == 'BOS'
        assert normalize_team_abbr('GSW') == 'GSW'

    def test_normalize_special_cases(self):
        """Test normalization of special case team codes."""
        assert normalize_team_abbr('BRK') == 'BKN'  # Brooklyn
        assert normalize_team_abbr('CHO') == 'CHA'  # Charlotte
        assert normalize_team_abbr('PHO') == 'PHX'  # Phoenix

    def test_normalize_already_normalized(self):
        """Test that normalized codes pass through unchanged."""
        assert normalize_team_abbr('BKN') == 'BKN'
        assert normalize_team_abbr('CHA') == 'CHA'
        assert normalize_team_abbr('PHX') == 'PHX'


class TestPlayerMovementRegistryProcessor:
    """Test PlayerMovementRegistryProcessor functionality."""

    @pytest.fixture
    def processor(self):
        """Create a test processor instance."""
        with patch('data_processors.reference.base.registry_processor_base.bigquery.Client'):
            processor = PlayerMovementRegistryProcessor(test_mode=True)
            processor.bq_client = Mock()
            processor.project_id = 'test-project'
            processor.table_name = 'test.registry'
            return processor

    def test_initialization(self, processor):
        """Test processor initializes correctly."""
        assert processor.processor_type == 'player_movement'
        assert processor.test_mode == True
        assert processor.processing_strategy.value == 'merge'

    def test_get_recent_trades_query_structure(self, processor):
        """Test that get_recent_trades builds correct query."""
        # Mock the query result
        mock_df = pd.DataFrame({
            'player_lookup': ['traeyoung', 'cjmccollum'],
            'player_full_name': ['Trae Young', 'CJ McCollum'],
            'team_abbr': ['WAS', 'ATL'],
            'transaction_date': [date(2026, 2, 1), date(2026, 2, 1)],
            'transaction_description': ['Trade description 1', 'Trade description 2'],
            'transaction_type': ['Trade', 'Trade']
        })

        processor.bq_client.query.return_value.to_dataframe.return_value = mock_df

        # Run the method
        result = processor.get_recent_trades(lookback_hours=24)

        # Verify query was called
        assert processor.bq_client.query.called
        assert len(result) == 2
        assert 'traeyoung' in result['player_lookup'].values

    def test_build_update_records_with_team_change(self, processor):
        """Test building update records when team changes."""
        # Sample trade data
        trades_df = pd.DataFrame({
            'player_lookup': ['traeyoung'],
            'player_full_name': ['Trae Young'],
            'team_abbr': ['WAS'],
            'transaction_date': [date(2026, 2, 1)]
        })

        # Sample registry data (old team)
        registry_df = pd.DataFrame({
            'player_lookup': ['traeyoung'],
            'player_name': ['Trae Young'],
            'team_abbr': ['ATL'],
            'season': ['2025-26'],
            'source_priority': ['roster_espn'],
            'roster_update_count': [5]
        })

        # Build update records
        updates = processor.build_update_records(trades_df, registry_df, '2025-26')

        assert len(updates) == 1
        assert updates[0]['player_lookup'] == 'traeyoung'
        assert updates[0]['team_abbr'] == 'WAS'
        assert updates[0]['source_priority'] == 'player_movement'
        assert updates[0]['season'] == '2025-26'

    def test_build_update_records_no_change_needed(self, processor):
        """Test that no update is created when team already correct."""
        # Sample trade data
        trades_df = pd.DataFrame({
            'player_lookup': ['traeyoung'],
            'player_full_name': ['Trae Young'],
            'team_abbr': ['WAS'],
            'transaction_date': [date(2026, 2, 1)]
        })

        # Sample registry data (already correct)
        registry_df = pd.DataFrame({
            'player_lookup': ['traeyoung'],
            'player_name': ['Trae Young'],
            'team_abbr': ['WAS'],
            'season': ['2025-26'],
            'source_priority': ['player_movement'],
            'roster_update_count': [5]
        })

        # Build update records
        updates = processor.build_update_records(trades_df, registry_df, '2025-26')

        # Should be empty since no update needed
        assert len(updates) == 0

    def test_build_update_records_player_not_in_registry(self, processor):
        """Test handling of players not found in registry."""
        # Sample trade data
        trades_df = pd.DataFrame({
            'player_lookup': ['newplayer'],
            'player_full_name': ['New Player'],
            'team_abbr': ['LAL'],
            'transaction_date': [date(2026, 2, 1)]
        })

        # Empty registry (player not found) - need to have the correct columns
        registry_df = pd.DataFrame(columns=[
            'player_lookup', 'player_name', 'team_abbr', 'season',
            'source_priority', 'roster_update_count'
        ])

        # Build update records
        updates = processor.build_update_records(trades_df, registry_df, '2025-26')

        # Should be empty - can't update a player that doesn't exist
        assert len(updates) == 0

    def test_team_normalization_in_updates(self, processor):
        """Test that team abbreviations are normalized during update."""
        # Sample trade data with BRK (should normalize to BKN)
        trades_df = pd.DataFrame({
            'player_lookup': ['testplayer'],
            'player_full_name': ['Test Player'],
            'team_abbr': ['BRK'],  # Should be normalized
            'transaction_date': [date(2026, 2, 1)]
        })

        # Sample registry data
        registry_df = pd.DataFrame({
            'player_lookup': ['testplayer'],
            'player_name': ['Test Player'],
            'team_abbr': ['NYK'],
            'season': ['2025-26'],
            'source_priority': ['roster_espn'],
            'roster_update_count': [0]
        })

        # Build update records
        updates = processor.build_update_records(trades_df, registry_df, '2025-26')

        assert len(updates) == 1
        assert updates[0]['team_abbr'] == 'BKN'  # Normalized from BRK

    def test_get_registry_records_for_players_handles_empty_list(self, processor):
        """Test that empty player list returns empty DataFrame."""
        result = processor.get_registry_records_for_players([], '2025-26')
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_apply_updates_via_merge_no_updates(self, processor):
        """Test apply_updates_via_merge with no updates."""
        result = processor.apply_updates_via_merge([], '2025-26')

        assert result['status'] == 'no_updates_needed'
        assert result['records_updated'] == 0
        assert result['players_updated'] == []


class TestModuleLevelFunction:
    """Test module-level process_recent_trades function."""

    @patch('data_processors.reference.player_reference.player_movement_registry_processor.PlayerMovementRegistryProcessor')
    def test_process_recent_trades_function(self, mock_processor_class):
        """Test module-level function creates processor and calls method."""
        # Mock processor instance
        mock_processor = Mock()
        mock_processor.process_recent_trades.return_value = {
            'status': 'success',
            'trades_found': 5,
            'records_updated': 5
        }
        mock_processor_class.return_value = mock_processor

        # Call function
        result = process_recent_trades(
            lookback_hours=48,
            season_year=2025,
            test_mode=True
        )

        # Verify processor was created correctly
        mock_processor_class.assert_called_once_with(
            test_mode=True,
            strategy='merge'
        )

        # Verify process method was called
        mock_processor.process_recent_trades.assert_called_once_with(
            lookback_hours=48,
            season_year=2025
        )

        # Verify result
        assert result['status'] == 'success'
        assert result['trades_found'] == 5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
