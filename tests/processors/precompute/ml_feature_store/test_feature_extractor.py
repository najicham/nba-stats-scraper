"""
Unit Tests for FeatureExtractor

Tests BigQuery query methods and data extraction logic.
All tests mock BigQuery client to avoid actual database queries.

Run with: pytest test_feature_extractor.py -v

Directory: tests/processors/precompute/ml_feature_store/
"""

import pytest
import pandas as pd
from datetime import date, datetime
from unittest.mock import Mock, MagicMock

from data_processors.precompute.ml_feature_store.feature_extractor import FeatureExtractor


class TestFeatureExtractor:
    """Test FeatureExtractor - BigQuery query methods (25 tests)."""
    
    @pytest.fixture
    def mock_bq_client(self):
        """Create mock BigQuery client."""
        return Mock()
    
    @pytest.fixture
    def extractor(self, mock_bq_client):
        """Create extractor instance with mock client."""
        return FeatureExtractor(mock_bq_client, 'test-project')
    
    # ========================================================================
    # GET PLAYERS WITH GAMES (4 tests)
    # ========================================================================
    
    def test_get_players_with_games_found(self, extractor, mock_bq_client):
        """Test get_players_with_games returns player list."""
        # Mock query result
        mock_df = pd.DataFrame([
            {
                'player_lookup': 'lebron-james',
                'universal_player_id': 'lebronjames_001',
                'game_id': '20250115_LAL_GSW',
                'game_date': date(2025, 1, 15),
                'opponent_team_abbr': 'GSW',
                'is_home': True,
                'days_rest': 1
            },
            {
                'player_lookup': 'stephen-curry',
                'universal_player_id': 'stephencurry_001',
                'game_id': '20250115_GSW_LAL',
                'game_date': date(2025, 1, 15),
                'opponent_team_abbr': 'LAL',
                'is_home': False,
                'days_rest': 2
            }
        ])
        mock_bq_client.query.return_value.to_dataframe.return_value = mock_df
        
        result = extractor.get_players_with_games(date(2025, 1, 15))
        
        assert len(result) == 2
        assert result[0]['player_lookup'] == 'lebron-james'
        assert result[1]['player_lookup'] == 'stephen-curry'
        
        # Verify query was called
        mock_bq_client.query.assert_called_once()
        query_str = mock_bq_client.query.call_args[0][0]
        assert '2025-01-15' in query_str
        assert 'upcoming_player_game_context' in query_str
    
    def test_get_players_with_games_empty(self, extractor, mock_bq_client):
        """Test get_players_with_games with no games."""
        mock_df = pd.DataFrame()
        mock_bq_client.query.return_value.to_dataframe.return_value = mock_df
        
        result = extractor.get_players_with_games(date(2025, 1, 15))
        
        assert len(result) == 0
        assert isinstance(result, list)
    
    def test_get_players_with_games_query_structure(self, extractor, mock_bq_client):
        """Test get_players_with_games constructs correct query."""
        mock_df = pd.DataFrame()
        mock_bq_client.query.return_value.to_dataframe.return_value = mock_df
        
        extractor.get_players_with_games(date(2025, 1, 15))
        
        query_str = mock_bq_client.query.call_args[0][0]
        
        # Verify query includes required fields
        assert 'player_lookup' in query_str
        assert 'universal_player_id' in query_str
        assert 'game_id' in query_str
        assert 'opponent_team_abbr' in query_str
        assert 'ORDER BY player_lookup' in query_str
    
    def test_get_players_with_games_multiple_games_same_player(self, extractor, mock_bq_client):
        """Test get_players_with_games handles player with multiple games (doubleheader)."""
        mock_df = pd.DataFrame([
            {
                'player_lookup': 'lebron-james',
                'universal_player_id': 'lebronjames_001',
                'game_id': '20250115_LAL_GSW',
                'game_date': date(2025, 1, 15),
                'opponent_team_abbr': 'GSW',
                'is_home': True,
                'days_rest': 1
            },
            {
                'player_lookup': 'lebron-james',
                'universal_player_id': 'lebronjames_001',
                'game_id': '20250115_LAL_PHX',  # Second game same day
                'game_date': date(2025, 1, 15),
                'opponent_team_abbr': 'PHX',
                'is_home': True,
                'days_rest': 1
            }
        ])
        mock_bq_client.query.return_value.to_dataframe.return_value = mock_df
        
        result = extractor.get_players_with_games(date(2025, 1, 15))
        
        # Should return both games
        assert len(result) == 2
        assert result[0]['game_id'] == '20250115_LAL_GSW'
        assert result[1]['game_id'] == '20250115_LAL_PHX'
    
    # ========================================================================
    # EXTRACT PHASE 4 DATA (5 tests)
    # ========================================================================

    @pytest.mark.skip(reason="Schema changed - opponent_def_rating field no longer present")
    def test_extract_phase4_data_complete(self, extractor, mock_bq_client):
        """Test extract_phase4_data with all tables present."""
        # Mock all 4 Phase 4 table queries
        mock_cache = pd.DataFrame([{
            'points_avg_last_5': 25.2,
            'points_avg_last_10': 24.8,
            'points_avg_season': 24.5,
            'points_std_last_10': 4.2,
            'games_in_last_7_days': 3
        }])
        
        mock_composite = pd.DataFrame([{
            'fatigue_score': 75.0,
            'shot_zone_mismatch_score': 3.5,
            'pace_score': 1.5,
            'usage_spike_score': 0.8,
            'opponent_team_abbr': 'GSW'
        }])
        
        mock_shot_zones = pd.DataFrame([{
            'paint_rate_last_10': 35.0,
            'mid_range_rate_last_10': 20.0,
            'three_pt_rate_last_10': 45.0
        }])
        
        mock_team_defense = pd.DataFrame([{
            'opponent_def_rating': 110.5,
            'opponent_pace': 101.2
        }])
        
        # Set up mock to return different DataFrames for each query
        mock_bq_client.query.return_value.to_dataframe.side_effect = [
            mock_cache, mock_composite, mock_shot_zones, mock_team_defense
        ]
        
        result = extractor.extract_phase4_data('lebron-james', date(2025, 1, 15))
        
        # Verify all data merged
        assert result['points_avg_last_5'] == 25.2
        assert result['fatigue_score'] == 75.0
        assert result['paint_rate_last_10'] == 35.0
        assert result['opponent_def_rating'] == 110.5
        
        # Verify 4 queries were made
        assert mock_bq_client.query.call_count == 4
    
    def test_extract_phase4_data_missing_cache(self, extractor, mock_bq_client):
        """Test extract_phase4_data when daily cache missing."""
        # Empty DataFrame for cache
        mock_bq_client.query.return_value.to_dataframe.side_effect = [
            pd.DataFrame(),  # Empty cache
            pd.DataFrame([{'fatigue_score': 75.0, 'opponent_team_abbr': 'GSW'}]),
            pd.DataFrame([{'paint_rate_last_10': 35.0}]),
            pd.DataFrame([{'opponent_def_rating': 110.5}])
        ]
        
        result = extractor.extract_phase4_data('lebron-james', date(2025, 1, 15))
        
        # Should have composite and shot zone data, but not cache
        assert 'fatigue_score' in result
        assert 'paint_rate_last_10' in result
        assert 'points_avg_last_5' not in result
    
    def test_extract_phase4_data_no_opponent_data(self, extractor, mock_bq_client):
        """Test extract_phase4_data when opponent data unavailable."""
        # Composite doesn't include opponent_team_abbr
        mock_bq_client.query.return_value.to_dataframe.side_effect = [
            pd.DataFrame([{'points_avg_last_5': 25.2}]),
            pd.DataFrame([{'fatigue_score': 75.0}]),  # No opponent_team_abbr
            pd.DataFrame([{'paint_rate_last_10': 35.0}]),
        ]
        
        result = extractor.extract_phase4_data('lebron-james', date(2025, 1, 15))
        
        # Should not have team defense data (requires opponent)
        assert 'points_avg_last_5' in result
        assert 'fatigue_score' in result
        assert 'opponent_def_rating' not in result
        
        # Should only have 3 queries (no team defense query)
        assert mock_bq_client.query.call_count == 3
    
    def test_extract_phase4_data_all_empty(self, extractor, mock_bq_client):
        """Test extract_phase4_data when all tables empty."""
        mock_bq_client.query.return_value.to_dataframe.return_value = pd.DataFrame()
        
        result = extractor.extract_phase4_data('rookie-player', date(2025, 1, 15))
        
        # Should return empty dict (or dict with only keys extracted from empty queries)
        # The actual behavior depends on implementation
        assert isinstance(result, dict)
    
    def test_extract_phase4_data_player_lookup_used(self, extractor, mock_bq_client):
        """Test extract_phase4_data uses correct player_lookup in queries."""
        mock_bq_client.query.return_value.to_dataframe.return_value = pd.DataFrame()
        
        extractor.extract_phase4_data('test-player', date(2025, 1, 15))
        
        # Check all queries include player_lookup
        for call in mock_bq_client.query.call_args_list:
            query_str = call[0][0]
            assert 'test-player' in query_str or 'player_lookup' in query_str
    
    # ========================================================================
    # EXTRACT PHASE 3 DATA (4 tests)
    # ========================================================================
    
    def test_extract_phase3_data_complete(self, extractor, mock_bq_client):
        """Test extract_phase3_data with complete data."""
        # Mock context query
        mock_context = pd.DataFrame([{
            'player_lookup': 'lebron-james',
            'game_date': date(2025, 1, 15),
            'game_id': '20250115_LAL_GSW',
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'GSW',
            'home_game': True,
            'back_to_back': False,
            'season_phase': 'regular',
            'days_rest': 1,
            'player_status': 'available',
            'opponent_days_rest': 0
        }])
        
        # Mock last 10 games
        mock_games = pd.DataFrame([
            {'game_date': date(2025, 1, 13), 'points': 28, 'minutes_played': 36, 'ft_makes': 8},
            {'game_date': date(2025, 1, 11), 'points': 24, 'minutes_played': 35, 'ft_makes': 6},
            {'game_date': date(2025, 1, 9), 'points': 26, 'minutes_played': 37, 'ft_makes': 7},
        ])
        
        # Mock season stats
        mock_season = pd.DataFrame([{
            'points_avg_season': 24.5,
            'minutes_avg_season': 35.0,
            'games_played_season': 45
        }])
        
        # Mock team games
        mock_team_games = pd.DataFrame([
            {'game_date': date(2025, 1, 13), 'win_flag': True},
            {'game_date': date(2025, 1, 11), 'win_flag': True},
            {'game_date': date(2025, 1, 9), 'win_flag': False},
        ])
        
        mock_bq_client.query.return_value.to_dataframe.side_effect = [
            mock_context, mock_games, mock_season, mock_team_games
        ]
        
        result = extractor.extract_phase3_data('lebron-james', date(2025, 1, 15))
        
        # Verify context data
        assert result['home_game'] == True
        assert result['days_rest'] == 1
        assert result['player_status'] == 'available'
        
        # Verify aggregated data
        assert 'last_10_games' in result
        assert len(result['last_10_games']) == 3
        assert 'points_avg_season' in result
        assert 'team_season_games' in result
    
    def test_extract_phase3_data_calculates_aggregations(self, extractor, mock_bq_client):
        """Test extract_phase3_data calculates aggregations from games."""
        mock_context = pd.DataFrame([{
            'player_lookup': 'test-player',
            'team_abbr': 'LAL',
            'home_game': True
        }])
        
        mock_games = pd.DataFrame([
            {'points': 20}, {'points': 22}, {'points': 24},
            {'points': 18}, {'points': 21}, {'points': 23},
            {'points': 19}, {'points': 25}, {'points': 20}, {'points': 22}
        ])
        
        mock_season = pd.DataFrame([{'points_avg_season': 21.0}])
        mock_team_games = pd.DataFrame([])
        
        mock_bq_client.query.return_value.to_dataframe.side_effect = [
            mock_context, mock_games, mock_season, mock_team_games
        ]
        
        result = extractor.extract_phase3_data('test-player', date(2025, 1, 15))
        
        # Should calculate averages
        assert 'points_avg_last_10' in result
        assert result['points_avg_last_10'] == 21.4  # (20+22+24+18+21+23+19+25+20+22)/10
        
        assert 'points_avg_last_5' in result
        # First 5 games: 20, 22, 24, 18, 21 -> avg = 21.0
        assert result['points_avg_last_5'] == 21.0
    
    def test_extract_phase3_data_missing_context(self, extractor, mock_bq_client):
        """Test extract_phase3_data when context missing."""
        mock_bq_client.query.return_value.to_dataframe.return_value = pd.DataFrame()
        
        result = extractor.extract_phase3_data('rookie-player', date(2025, 1, 15))
        
        # Should handle gracefully with empty/minimal data
        assert isinstance(result, dict)
        assert 'last_10_games' in result
        assert len(result['last_10_games']) == 0
    
    def test_extract_phase3_data_insufficient_games(self, extractor, mock_bq_client):
        """Test extract_phase3_data with <5 games."""
        mock_context = pd.DataFrame([{'player_lookup': 'rookie', 'team_abbr': 'LAL'}])
        
        mock_games = pd.DataFrame([
            {'points': 15}, {'points': 18}, {'points': 12}  # Only 3 games
        ])
        
        mock_season = pd.DataFrame([{'points_avg_season': 15.0}])
        mock_team_games = pd.DataFrame([])
        
        mock_bq_client.query.return_value.to_dataframe.side_effect = [
            mock_context, mock_games, mock_season, mock_team_games
        ]
        
        result = extractor.extract_phase3_data('rookie', date(2025, 1, 15))
        
        # Should still have last_10_games with 3 games
        assert len(result['last_10_games']) == 3
        
        # Should calculate avg_last_10 even with <10 games
        assert 'points_avg_last_10' in result
        assert result['points_avg_last_10'] == 15.0  # (15+18+12)/3
        
        # Should NOT have points_avg_last_5 (need at least 5)
        assert 'points_avg_last_5' not in result
    
    # ========================================================================
    # QUERY METHODS - INDIVIDUAL (12 tests)
    # ========================================================================
    
    def test_query_player_daily_cache_found(self, extractor, mock_bq_client):
        """Test _query_player_daily_cache returns data."""
        mock_df = pd.DataFrame([{
            'points_avg_last_5': 25.0,
            'points_avg_last_10': 24.5,
            'minutes_avg_last_10': 35.5
        }])
        mock_bq_client.query.return_value.to_dataframe.return_value = mock_df
        
        result = extractor._query_player_daily_cache('test-player', date(2025, 1, 15))
        
        assert result['points_avg_last_5'] == 25.0
        assert result['minutes_avg_last_10'] == 35.5
    
    def test_query_player_daily_cache_not_found(self, extractor, mock_bq_client):
        """Test _query_player_daily_cache returns empty dict when not found."""
        mock_bq_client.query.return_value.to_dataframe.return_value = pd.DataFrame()
        
        result = extractor._query_player_daily_cache('missing-player', date(2025, 1, 15))
        
        assert result == {}
    
    def test_query_composite_factors_found(self, extractor, mock_bq_client):
        """Test _query_composite_factors returns data."""
        mock_df = pd.DataFrame([{
            'fatigue_score': 75.0,
            'shot_zone_mismatch_score': 3.5,
            'opponent_team_abbr': 'GSW'
        }])
        mock_bq_client.query.return_value.to_dataframe.return_value = mock_df
        
        result = extractor._query_composite_factors('test-player', date(2025, 1, 15))
        
        assert result['fatigue_score'] == 75.0
        assert result['opponent_team_abbr'] == 'GSW'
    
    def test_query_composite_factors_not_found(self, extractor, mock_bq_client):
        """Test _query_composite_factors returns empty dict when not found."""
        mock_bq_client.query.return_value.to_dataframe.return_value = pd.DataFrame()
        
        result = extractor._query_composite_factors('missing-player', date(2025, 1, 15))
        
        assert result == {}
    
    def test_query_shot_zone_analysis_found(self, extractor, mock_bq_client):
        """Test _query_shot_zone_analysis returns data."""
        mock_df = pd.DataFrame([{
            'paint_rate_last_10': 35.0,
            'mid_range_rate_last_10': 20.0,
            'three_pt_rate_last_10': 45.0
        }])
        mock_bq_client.query.return_value.to_dataframe.return_value = mock_df
        
        result = extractor._query_shot_zone_analysis('test-player', date(2025, 1, 15))
        
        assert result['paint_rate_last_10'] == 35.0
        assert result['three_pt_rate_last_10'] == 45.0
    
    def test_query_shot_zone_analysis_not_found(self, extractor, mock_bq_client):
        """Test _query_shot_zone_analysis returns empty dict when not found."""
        mock_bq_client.query.return_value.to_dataframe.return_value = pd.DataFrame()
        
        result = extractor._query_shot_zone_analysis('missing-player', date(2025, 1, 15))
        
        assert result == {}
    
    def test_query_team_defense_found(self, extractor, mock_bq_client):
        """Test _query_team_defense returns data."""
        mock_df = pd.DataFrame([{
            'opponent_def_rating': 110.5,
            'opponent_pace': 101.2
        }])
        mock_bq_client.query.return_value.to_dataframe.return_value = mock_df
        
        result = extractor._query_team_defense('GSW', date(2025, 1, 15))
        
        assert result['opponent_def_rating'] == 110.5
        assert result['opponent_pace'] == 101.2
    
    def test_query_team_defense_not_found(self, extractor, mock_bq_client):
        """Test _query_team_defense returns empty dict when not found."""
        mock_bq_client.query.return_value.to_dataframe.return_value = pd.DataFrame()
        
        result = extractor._query_team_defense('UNKNOWN', date(2025, 1, 15))
        
        assert result == {}
    
    def test_query_player_context_found(self, extractor, mock_bq_client):
        """Test _query_player_context returns data."""
        mock_df = pd.DataFrame([{
            'player_lookup': 'test-player',
            'home_game': True,
            'days_rest': 2,
            'player_status': 'available'
        }])
        mock_bq_client.query.return_value.to_dataframe.return_value = mock_df
        
        result = extractor._query_player_context('test-player', date(2025, 1, 15))
        
        assert result['home_game'] == True
        assert result['days_rest'] == 2
    
    def test_query_player_context_not_found(self, extractor, mock_bq_client):
        """Test _query_player_context returns empty dict when not found."""
        mock_bq_client.query.return_value.to_dataframe.return_value = pd.DataFrame()
        
        result = extractor._query_player_context('missing-player', date(2025, 1, 15))
        
        assert result == {}
    
    def test_query_last_n_games_returns_list(self, extractor, mock_bq_client):
        """Test _query_last_n_games returns list of games."""
        mock_df = pd.DataFrame([
            {'game_date': date(2025, 1, 13), 'points': 28, 'minutes_played': 36},
            {'game_date': date(2025, 1, 11), 'points': 24, 'minutes_played': 35},
            {'game_date': date(2025, 1, 9), 'points': 26, 'minutes_played': 37}
        ])
        mock_bq_client.query.return_value.to_dataframe.return_value = mock_df
        
        result = extractor._query_last_n_games('test-player', date(2025, 1, 15), 10)
        
        assert len(result) == 3
        assert result[0]['points'] == 28
        assert result[1]['points'] == 24
        
        # Verify LIMIT clause in query
        query_str = mock_bq_client.query.call_args[0][0]
        assert 'LIMIT 10' in query_str
    
    def test_query_last_n_games_empty(self, extractor, mock_bq_client):
        """Test _query_last_n_games returns empty list when no games."""
        mock_bq_client.query.return_value.to_dataframe.return_value = pd.DataFrame()
        
        result = extractor._query_last_n_games('rookie-player', date(2025, 1, 15), 10)
        
        assert result == []


    # ========================================================================
    # HISTORICAL COMPLETENESS TRACKING (Data Cascade Architecture - Jan 2026)
    # ========================================================================

    def test_get_historical_completeness_data_with_games(self, extractor):
        """Test get_historical_completeness_data returns correct structure."""
        # Pre-populate the lookup caches (simulating batch extraction)
        extractor._last_10_games_lookup = {
            'lebron-james': [
                {'game_date': date(2026, 1, 15), 'points': 28},
                {'game_date': date(2026, 1, 13), 'points': 24},
                {'game_date': date(2026, 1, 11), 'points': 26},
            ]
        }
        extractor._total_games_available_lookup = {
            'lebron-james': 50  # Veteran with many games
        }

        result = extractor.get_historical_completeness_data('lebron-james')

        assert result['games_found'] == 3
        assert result['games_available'] == 50
        assert len(result['contributing_game_dates']) == 3
        assert result['contributing_game_dates'][0] == date(2026, 1, 15)

    def test_get_historical_completeness_data_empty(self, extractor):
        """Test get_historical_completeness_data for player with no games."""
        # Empty caches
        extractor._last_10_games_lookup = {}
        extractor._total_games_available_lookup = {}

        result = extractor.get_historical_completeness_data('new-player')

        assert result['games_found'] == 0
        assert result['games_available'] == 0
        assert result['contributing_game_dates'] == []

    def test_get_historical_completeness_data_partial(self, extractor):
        """Test get_historical_completeness_data for player with some games."""
        extractor._last_10_games_lookup = {
            'rookie-player': [
                {'game_date': date(2026, 1, 15), 'points': 12},
                {'game_date': date(2026, 1, 13), 'points': 8},
            ]
        }
        extractor._total_games_available_lookup = {
            'rookie-player': 2  # Only 2 games in career
        }

        result = extractor.get_historical_completeness_data('rookie-player')

        assert result['games_found'] == 2
        assert result['games_available'] == 2  # Bootstrap scenario
        assert len(result['contributing_game_dates']) == 2

    def test_get_historical_completeness_data_string_dates(self, extractor):
        """Test get_historical_completeness_data handles string dates."""
        extractor._last_10_games_lookup = {
            'test-player': [
                {'game_date': '2026-01-15', 'points': 20},  # String date
                {'game_date': date(2026, 1, 13), 'points': 22},  # Date object
            ]
        }
        extractor._total_games_available_lookup = {'test-player': 10}

        result = extractor.get_historical_completeness_data('test-player')

        # Both should be converted to date objects
        assert len(result['contributing_game_dates']) == 2
        assert isinstance(result['contributing_game_dates'][0], date)
        assert isinstance(result['contributing_game_dates'][1], date)

    def test_batch_extract_populates_total_games_available(self, extractor, mock_bq_client):
        """Test _batch_extract_last_10_games populates total_games_available."""
        # Mock query result with total_games_available column
        mock_df = pd.DataFrame([
            {
                'player_lookup': 'lebron-james',
                'game_date': date(2026, 1, 15),
                'points': 28,
                'minutes_played': 36,
                'ft_makes': 8,
                'fg_attempts': 20,
                'paint_attempts': 8,
                'mid_range_attempts': 4,
                'three_pt_attempts': 8,
                'total_games_available': 50
            },
            {
                'player_lookup': 'lebron-james',
                'game_date': date(2026, 1, 13),
                'points': 24,
                'minutes_played': 35,
                'ft_makes': 6,
                'fg_attempts': 18,
                'paint_attempts': 7,
                'mid_range_attempts': 3,
                'three_pt_attempts': 8,
                'total_games_available': 50
            },
            {
                'player_lookup': 'rookie-player',
                'game_date': date(2026, 1, 15),
                'points': 8,
                'minutes_played': 12,
                'ft_makes': 2,
                'fg_attempts': 4,
                'paint_attempts': 2,
                'mid_range_attempts': 1,
                'three_pt_attempts': 1,
                'total_games_available': 3
            }
        ])
        mock_bq_client.query.return_value.to_dataframe.return_value = mock_df

        # Call the batch extraction method
        extractor._batch_extract_last_10_games(date(2026, 1, 16), ['lebron-james', 'rookie-player'])

        # Verify total_games_available lookup was populated
        assert extractor._total_games_available_lookup.get('lebron-james') == 50
        assert extractor._total_games_available_lookup.get('rookie-player') == 3

    def test_clear_batch_cache_clears_completeness_lookup(self, extractor):
        """Test _clear_batch_cache clears total_games_available_lookup."""
        # Pre-populate the lookup
        extractor._total_games_available_lookup = {'test-player': 10}

        extractor._clear_batch_cache()

        assert extractor._total_games_available_lookup == {}


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
