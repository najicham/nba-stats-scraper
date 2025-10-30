"""
Path: tests/processors/precompute/team_defense_zone_analysis/test_integration.py
Integration Tests for Team Defense Zone Analysis Processor
Tests full end-to-end processing with mocked BigQuery data.
Run with: pytest tests/precompute/test_team_defense_integration.py -v
"""
import pytest
import pandas as pd
from datetime import date, datetime, timedelta
from unittest.mock import Mock, MagicMock, patch, call
from types import SimpleNamespace  # FIX: Added for mock objects
from google.cloud import bigquery

# Import processor
from data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor import (
    TeamDefenseZoneAnalysisProcessor
)


class TestFullProcessingFlow:
    """Test complete processing flow from extract to save."""
    
    @pytest.fixture
    def processor(self):
        """Create processor with mocked BigQuery."""
        with patch('data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor.bigquery.Client'):
            proc = TeamDefenseZoneAnalysisProcessor()
            proc.bq_client = Mock()
            proc.project_id = 'test-project'
            
            # Mock team mapper
            proc.team_mapper.get_all_nba_tricodes = Mock(return_value=[
                'LAL', 'GSW', 'BOS', 'MIA', 'PHX'  # 5 teams for testing
            ])
            
            return proc
    
    @pytest.fixture
    def mock_team_defense_data(self):
        """Create realistic team defense game summary data."""
        teams = ['LAL', 'GSW', 'BOS', 'MIA', 'PHX']
        data = []
        
        for team in teams:
            # Create 15 games per team
            for game_num in range(15):
                game_date = date(2025, 1, 27) - timedelta(days=game_num)
                data.append({
                    'defending_team_abbr': team,
                    'game_date': game_date,
                    'opp_paint_makes': 18 + (game_num % 5),
                    'opp_paint_attempts': 32 + (game_num % 8),
                    'opp_mid_range_makes': 7 + (game_num % 3),
                    'opp_mid_range_attempts': 18 + (game_num % 5),
                    'opp_three_pt_makes': 11 + (game_num % 4),
                    'opp_three_pt_attempts': 33 + (game_num % 6),
                    'points_in_paint_allowed': 38 + (game_num % 10),
                    'mid_range_points_allowed': 14 + (game_num % 6),
                    'three_pt_points_allowed': 33 + (game_num % 8),
                    'blocks_paint': 2 + (game_num % 3),
                    'blocks_mid_range': 1,
                    'blocks_three_pt': 0,
                    'points_allowed': 108 + (game_num % 15),
                    'defensive_rating': 110.0 + (game_num % 10),
                    'opponent_pace': 98.0 + (game_num % 5),
                    'processed_at': datetime(2025, 1, 27, 23, 5, 0)
                })
        
        return pd.DataFrame(data)
    
    def test_successful_processing(self, processor, mock_team_defense_data):
        """Test successful end-to-end processing."""
        # Setup
        processor.opts = {
            'analysis_date': date(2025, 1, 27),
            'season_year': 2024,
            'run_id': 'test-123'
        }
        processor.season_start_date = date(2024, 10, 22)
        
        # Mock dependency check (all pass)
        mock_dep_check = {
            'all_critical_present': True,
            'all_fresh': True,
            'missing': [],
            'stale': [],
            'is_early_season': False,
            'details': {
                'nba_analytics.team_defense_game_summary': {
                    'exists': True,
                    'row_count': 75,
                    'teams_found': 5,
                    'total_teams': 5,
                    'age_hours': 2.5,
                    'last_updated': '2025-01-27T23:05:00'
                }
            }
        }
        
        with patch.object(processor, 'check_dependencies', return_value=mock_dep_check):
            with patch.object(processor, 'track_source_usage'):
                # Mock BigQuery query for data extraction
                processor.bq_client.query.return_value.to_dataframe.return_value = mock_team_defense_data
                
                # Mock league average calculation
                mock_league_df = pd.DataFrame([{
                    'league_avg_paint_pct': 0.580,
                    'league_avg_mid_range_pct': 0.410,
                    'league_avg_three_pt_pct': 0.355,
                    'teams_in_sample': 5
                }])
                
                # Set up sequential query responses
                processor.bq_client.query.return_value.to_dataframe.side_effect = [
                    mock_team_defense_data,  # extract_raw_data
                    mock_league_df           # _calculate_league_averages
                ]
                
                # Execute
                processor.extract_raw_data()
                processor.calculate_precompute()
                
                # Verify results
                assert len(processor.transformed_data) == 5  # 5 teams
                
                # Check first team's data
                lal_data = next(t for t in processor.transformed_data if t['team_abbr'] == 'LAL')
                
                assert lal_data['analysis_date'] == '2025-01-27'
                assert lal_data['games_in_sample'] == 15
                assert lal_data['data_quality_tier'] == 'high'
                
                # Verify metrics exist
                assert lal_data['paint_pct_allowed_last_15'] is not None
                assert lal_data['mid_range_pct_allowed_last_15'] is not None
                assert lal_data['three_pt_pct_allowed_last_15'] is not None
                
                # Verify vs league metrics calculated
                assert lal_data['paint_defense_vs_league_avg'] is not None
                assert lal_data['mid_range_defense_vs_league_avg'] is not None
                assert lal_data['three_pt_defense_vs_league_avg'] is not None
                
                # Verify strengths/weaknesses identified
                assert lal_data['strongest_zone'] in ['paint', 'mid_range', 'perimeter']
                assert lal_data['weakest_zone'] in ['paint', 'mid_range', 'perimeter']
    
    def test_early_season_placeholder_flow(self, processor):
        """Test early season placeholder generation."""
        # Setup
        processor.opts = {
            'analysis_date': date(2024, 10, 28),  # 6 days after season start
            'season_year': 2024,
            'run_id': 'test-early'
        }
        processor.season_start_date = date(2024, 10, 22)
        
        # Mock dependency check (early season)
        mock_dep_check = {
            'all_critical_present': False,
            'all_fresh': True,
            'missing': [],
            'stale': [],
            'is_early_season': True,  # <-- Early season flag
            'details': {
                'nba_analytics.team_defense_game_summary': {
                    'exists': True,
                    'row_count': 15,  # Only 3 games per team
                    'teams_found': 5,
                    'total_teams': 5,
                    'age_hours': 2.0,
                    'last_updated': '2024-10-28T23:05:00'
                }
            }
        }
        
        with patch.object(processor, 'check_dependencies', return_value=mock_dep_check):
            with patch.object(processor, 'track_source_usage'):
                # Mock game count queries (3 games per team)
                mock_game_count = pd.DataFrame([{'game_count': 3}])
                processor.bq_client.query.return_value.to_dataframe.return_value = mock_game_count
                
                # Execute
                processor.extract_raw_data()
                
                # Verify placeholders created
                assert len(processor.transformed_data) == 5  # 5 teams
                
                # Check placeholder structure
                lal_placeholder = next(t for t in processor.transformed_data if t['team_abbr'] == 'LAL')
                
                # All business metrics should be None
                assert lal_placeholder['paint_pct_allowed_last_15'] is None
                assert lal_placeholder['mid_range_pct_allowed_last_15'] is None
                assert lal_placeholder['three_pt_pct_allowed_last_15'] is None
                assert lal_placeholder['defensive_rating_last_15'] is None
                assert lal_placeholder['strongest_zone'] is None
                assert lal_placeholder['weakest_zone'] is None
                
                # Context fields should be set
                assert lal_placeholder['games_in_sample'] == 3
                assert lal_placeholder['data_quality_tier'] == 'low'
                assert lal_placeholder['early_season_flag'] is True  # FIX 1: This should now pass
                assert 'Only 3 games available, need 15' in lal_placeholder['insufficient_data_reason']
    
    def test_insufficient_games_handling(self, processor, mock_team_defense_data):
        """Test handling when some teams have insufficient games."""
        # Setup
        processor.opts = {
            'analysis_date': date(2025, 1, 27),
            'season_year': 2024,
            'run_id': 'test-insufficient'
        }
        processor.season_start_date = date(2024, 10, 22)
        
        # Remove games for one team (LAL only has 10 games)
        insufficient_data = mock_team_defense_data[
            ~((mock_team_defense_data['defending_team_abbr'] == 'LAL') & 
              (mock_team_defense_data.index >= 10))
        ]
        
        # Mock dependency check (passes but one team insufficient)
        mock_dep_check = {
            'all_critical_present': True,
            'all_fresh': True,
            'missing': [],
            'stale': [],
            'is_early_season': False,
            'details': {
                'nba_analytics.team_defense_game_summary': {
                    'exists': True,
                    'row_count': 70,  # 10 + 15*4
                    'teams_found': 4,  # Only 4 teams have 15+ games
                    'age_hours': 2.5,
                    'last_updated': '2025-01-27T23:05:00'
                }
            }
        }
        
        with patch.object(processor, 'check_dependencies', return_value=mock_dep_check):
            with patch.object(processor, 'track_source_usage'):
                # Mock league averages
                mock_league_df = pd.DataFrame([{
                    'league_avg_paint_pct': 0.580,
                    'league_avg_mid_range_pct': 0.410,
                    'league_avg_three_pt_pct': 0.355,
                    'teams_in_sample': 4
                }])
                
                processor.bq_client.query.return_value.to_dataframe.side_effect = [
                    insufficient_data,
                    mock_league_df
                ]
                
                # Execute
                processor.extract_raw_data()
                processor.calculate_precompute()
                
                # Should process 4 teams successfully, fail 1
                assert len(processor.transformed_data) == 4
                assert len(processor.failed_entities) == 1
                
                # Check failed entity
                failed = processor.failed_entities[0]
                assert failed['entity_id'] == 'LAL'
                assert 'Only 10' in failed['reason']
                assert failed['category'] == 'INSUFFICIENT_DATA'


class TestDependencyChecking:
    """Test dependency checking logic."""
    
    @pytest.fixture
    def processor(self):
        with patch('data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor.bigquery.Client'):
            proc = TeamDefenseZoneAnalysisProcessor()
            proc.bq_client = Mock()
            proc.project_id = 'test-project'
            proc.opts = {
                'analysis_date': date(2025, 1, 27),
                'season_year': 2024
            }
            proc.season_start_date = date(2024, 10, 22)
            return proc
    
    def test_check_table_data_per_team_game_count(self, processor):
        """Test custom per_team_game_count check type."""
        config = {
            'check_type': 'per_team_game_count',
            'min_games_required': 15,
            'min_teams_with_data': 25,
            'entity_field': 'defending_team_abbr'
        }
        
        # FIX 2: Changed from dict to SimpleNamespace object
        mock_row = SimpleNamespace(
            teams_with_min_games=28,
            total_games=420,
            last_updated=datetime(2025, 1, 27, 23, 5, 0),
            total_teams=30
        )
        
        processor.bq_client.query.return_value.result.return_value = [mock_row]
        
        # Execute
        exists, details = processor._check_table_data(
            'nba_analytics.team_defense_game_summary',
            date(2025, 1, 27),
            config
        )
        
        # Verify
        assert exists is True
        assert details['teams_found'] == 28
        assert details['total_teams'] == 30
        assert details['row_count'] == 420
        assert details['min_games_required'] == 15
        assert details['age_hours'] is not None
    
    def test_check_table_data_insufficient_teams(self, processor):
        """Test per_team_game_count when insufficient teams."""
        config = {
            'check_type': 'per_team_game_count',
            'min_games_required': 15,
            'min_teams_with_data': 25,
            'entity_field': 'defending_team_abbr'
        }
        
        # FIX 3: Changed from dict to SimpleNamespace object
        mock_row = SimpleNamespace(
            teams_with_min_games=20,
            total_games=300,
            last_updated=datetime(2025, 1, 27, 23, 5, 0),
            total_teams=30
        )
        
        processor.bq_client.query.return_value.result.return_value = [mock_row]
        
        # Execute
        exists, details = processor._check_table_data(
            'nba_analytics.team_defense_game_summary',
            date(2025, 1, 27),
            config
        )
        
        # Should fail (20 < 25)
        assert exists is False
        assert details['teams_found'] == 20
        assert details['min_teams_required'] == 25


class TestErrorHandling:
    """Test error handling and recovery."""
    
    @pytest.fixture
    def processor(self):
        with patch('data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor.bigquery.Client'):
            proc = TeamDefenseZoneAnalysisProcessor()
            proc.bq_client = Mock()
            proc.project_id = 'test-project'
            return proc
    
    def test_missing_critical_dependency(self, processor):
        """Test handling of missing critical dependencies."""
        processor.opts = {
            'analysis_date': date(2025, 1, 27),
            'season_year': 2024,
            'run_id': 'test-error'
        }
        processor.season_start_date = date(2024, 10, 22)
        
        # Mock dependency check failure
        mock_dep_check = {
            'all_critical_present': False,
            'all_fresh': True,
            'missing': ['nba_analytics.team_defense_game_summary'],
            'stale': [],
            'is_early_season': False,
            'details': {
                'nba_analytics.team_defense_game_summary': {
                    'exists': False,
                    'error': 'Table not found'
                }
            }
        }
        
        with patch.object(processor, 'check_dependencies', return_value=mock_dep_check):
            with patch.object(processor, 'track_source_usage'):
                # Should raise ValueError
                with pytest.raises(ValueError, match="Missing critical dependencies"):
                    processor.extract_raw_data()
    
    def test_stale_data_warning(self, processor):
        """Test handling of stale upstream data."""
        processor.opts = {
            'analysis_date': date(2025, 1, 27),
            'season_year': 2024,
            'run_id': 'test-stale'
        }
        processor.season_start_date = date(2024, 10, 22)
        
        # Mock stale data (5 days old)
        mock_dep_check = {
            'all_critical_present': True,
            'all_fresh': False,  # Stale!
            'missing': [],
            'stale': ['nba_analytics.team_defense_game_summary: 120.0h old'],
            'is_early_season': False,
            'details': {
                'nba_analytics.team_defense_game_summary': {
                    'exists': True,
                    'row_count': 450,
                    'teams_found': 30,
                    'age_hours': 120.0,
                    'last_updated': '2025-01-22T23:05:00'
                }
            }
        }
        
        # Should not raise, just warn
        with patch.object(processor, 'check_dependencies', return_value=mock_dep_check):
            with patch.object(processor, 'track_source_usage'):
                # FIX 4: Return empty DataFrame with proper columns
                empty_df = pd.DataFrame(columns=[
                    'defending_team_abbr', 'game_date', 'opp_paint_makes',
                    'opp_paint_attempts', 'opp_mid_range_makes', 'opp_mid_range_attempts',
                    'opp_three_pt_makes', 'opp_three_pt_attempts', 'points_in_paint_allowed',
                    'mid_range_points_allowed', 'three_pt_points_allowed', 'blocks_paint',
                    'blocks_mid_range', 'blocks_three_pt', 'points_allowed',
                    'defensive_rating', 'opponent_pace', 'processed_at'
                ])
                processor.bq_client.query.return_value.to_dataframe.return_value = empty_df
                
                # Should not raise exception
                try:
                    processor.extract_raw_data()
                except ValueError:
                    pytest.fail("Should not raise exception for stale data")


class TestSourceTrackingIntegration:
    """Test v4.0 source tracking integration."""
    
    @pytest.fixture
    def processor(self):
        with patch('data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor.bigquery.Client'):
            proc = TeamDefenseZoneAnalysisProcessor()
            proc.bq_client = Mock()
            proc.project_id = 'test-project'
            return proc
    
    def test_source_tracking_populated_in_output(self, processor):
        """Test that source tracking fields are in output records."""
        processor.opts = {
            'analysis_date': date(2025, 1, 27),
            'season_year': 2024
        }
        processor.season_start_date = date(2024, 10, 22)
        
        # Mock source metadata
        processor.source_metadata = {
            'nba_analytics.team_defense_game_summary': {
                'last_updated': '2025-01-27T23:05:00Z',
                'rows_found': 450,
                'completeness_pct': 100.00
            }
        }
        
        # FIX 5: Provide 15 games of data instead of 1
        processor.raw_data = pd.DataFrame([
            {
                'defending_team_abbr': 'LAL',
                'game_date': date(2025, 1, 27) - timedelta(days=i),
                'opp_paint_makes': 20,
                'opp_paint_attempts': 35,
                'opp_mid_range_makes': 8,
                'opp_mid_range_attempts': 20,
                'opp_three_pt_makes': 12,
                'opp_three_pt_attempts': 35,
                'points_in_paint_allowed': 42,
                'mid_range_points_allowed': 16,
                'three_pt_points_allowed': 36,
                'blocks_paint': 2,
                'blocks_mid_range': 1,
                'blocks_three_pt': 0,
                'points_allowed': 110,
                'defensive_rating': 112.5,
                'opponent_pace': 99.2
            }
            for i in range(15)  # 15 games
        ])
        
        processor.league_averages = {
            'paint_pct': 0.580,
            'mid_range_pct': 0.410,
            'three_pt_pct': 0.355
        }
        
        # Execute
        processor.calculate_precompute()
        
        # Verify source tracking in output
        assert len(processor.transformed_data) == 1
        record = processor.transformed_data[0]
        
        # Check v4.0 fields present
        assert 'source_team_defense_last_updated' in record
        assert 'source_team_defense_rows_found' in record
        assert 'source_team_defense_completeness_pct' in record
        
        # Check values
        assert record['source_team_defense_last_updated'] == '2025-01-27T23:05:00Z'
        assert record['source_team_defense_rows_found'] == 450
        assert record['source_team_defense_completeness_pct'] == 100.00


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])