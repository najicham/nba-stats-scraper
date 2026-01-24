# Path: tests/processors/analytics/upcoming_player_game_context/test_integration.py
"""
Integration Tests for UpcomingPlayerGameContext Processor

Tests full end-to-end processor flow with mocked BigQuery.
Run with: pytest test_integration.py -v

Directory: tests/processors/analytics/upcoming_player_game_context/
"""

import pytest
import pandas as pd
from datetime import date, datetime, timedelta
from unittest.mock import Mock, MagicMock, patch, call
import json

# Import processor
from data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor import (
    UpcomingPlayerGameContextProcessor
)


class TestFullProcessorFlow:
    """Test complete processor execution flow."""

    @pytest.fixture
    def processor(self):
        """Create processor with mocked BigQuery client.

        The mock handles both query patterns:
        - .query().result() - returns empty iterable (for hash lookups)
        - .query().to_dataframe() - returns empty DataFrame by default
        """
        proc = UpcomingPlayerGameContextProcessor()

        # Create a properly configured mock client
        mock_client = Mock()

        def create_query_job(*args, **kwargs):
            """Create a mock query job that handles both patterns."""
            job = Mock()
            # For .result() - return empty iterable
            empty_result = Mock()
            empty_result.__iter__ = Mock(return_value=iter([]))
            job.result = Mock(return_value=empty_result)
            # For .to_dataframe() - return empty DataFrame
            import pandas as pd
            job.to_dataframe = Mock(return_value=pd.DataFrame())
            return job

        mock_client.query = Mock(side_effect=create_query_job)
        mock_client.insert_rows_json = Mock(return_value=[])

        proc.bq_client = mock_client
        proc.project_id = 'test-project'
        return proc
    
    @pytest.fixture
    def mock_bigquery_responses(self):
        """Create realistic BigQuery response data."""
        return {
            'props': pd.DataFrame([
                {
                    'player_lookup': 'lebronjames',
                    'game_id': '20251120_LAL_BOS',
                    'game_date': date(2025, 11, 20),
                    'home_team_abbr': 'BOS',
                    'away_team_abbr': 'LAL'
                },
                {
                    'player_lookup': 'stephencurry',
                    'game_id': '20251120_GSW_PHX',
                    'game_date': date(2025, 11, 20),
                    'home_team_abbr': 'PHX',
                    'away_team_abbr': 'GSW'
                }
            ]),
            'schedule': pd.DataFrame([
                {
                    'game_id': '20251120_LAL_BOS',
                    'game_date': date(2025, 11, 20),
                    'home_team_abbr': 'BOS',
                    'away_team_abbr': 'LAL',
                    'game_date_est': datetime(2025, 11, 20, 19, 30),
                    'is_primetime': True,
                    'season_year': 2025
                },
                {
                    'game_id': '20251120_GSW_PHX',
                    'game_date': date(2025, 11, 20),
                    'home_team_abbr': 'PHX',
                    'away_team_abbr': 'GSW',
                    'game_date_est': datetime(2025, 11, 20, 22, 0),
                    'is_primetime': False,
                    'season_year': 2025
                }
            ]),
            'boxscores': pd.DataFrame([
                # LeBron's last 10 games
                *[{
                    'player_lookup': 'lebronjames',
                    'game_date': date(2025, 11, 20 - i),
                    'team_abbr': 'LAL',
                    'points': 25 + (i % 3),
                    'minutes': f'{35 - i}:30',
                    'minutes_decimal': 35.5 - i,
                    'assists': 7,
                    'rebounds': 8
                } for i in range(1, 11)],
                # Curry's last 10 games
                *[{
                    'player_lookup': 'stephencurry',
                    'game_date': date(2025, 11, 20 - i),
                    'team_abbr': 'GSW',
                    'points': 28 + (i % 2),
                    'minutes': f'{33 - i}:45',
                    'minutes_decimal': 33.75 - i,
                    'assists': 6,
                    'rebounds': 5
                } for i in range(1, 11)]
            ]),
            'prop_lines_opening': pd.DataFrame([
                {'points_line': 24.5, 'bookmaker': 'draftkings', 'snapshot_timestamp': datetime(2025, 11, 19, 10, 0)},
                {'points_line': 27.5, 'bookmaker': 'draftkings', 'snapshot_timestamp': datetime(2025, 11, 19, 10, 0)}
            ]),
            'prop_lines_current': pd.DataFrame([
                {'points_line': 25.5, 'bookmaker': 'fanduel', 'snapshot_timestamp': datetime(2025, 11, 20, 16, 0)},
                {'points_line': 28.5, 'bookmaker': 'fanduel', 'snapshot_timestamp': datetime(2025, 11, 20, 16, 0)}
            ]),
            'game_lines_spreads_opening': pd.DataFrame([
                {'median_line': -5.5, 'bookmakers': 'draftkings,fanduel,betmgm', 'bookmaker_count': 3}
            ]),
            'game_lines_spreads_current': pd.DataFrame([
                {'median_line': -6.0, 'bookmakers': 'draftkings,fanduel,betmgm', 'bookmaker_count': 3}
            ]),
            'game_lines_totals_opening': pd.DataFrame([
                {'median_line': 225.0, 'bookmakers': 'draftkings,fanduel,betmgm', 'bookmaker_count': 3}
            ]),
            'game_lines_totals_current': pd.DataFrame([
                {'median_line': 226.5, 'bookmakers': 'draftkings,fanduel,betmgm', 'bookmaker_count': 3}
            ])
        }
    
    @pytest.mark.skip(reason="Needs extensive mock data update - mock DataFrame missing required columns")
    def test_successful_full_run(self, processor, mock_bigquery_responses):
        """Test complete successful processor run."""
        # Setup mock responses
        def mock_query_response(query, **kwargs):
            mock_result = Mock()

            # Handle .result() - must return proper iterator for next() calls
            class EmptyIterator:
                def __iter__(self):
                    return self
                def __next__(self):
                    raise StopIteration
            mock_result.result = Mock(return_value=EmptyIterator())

            if 'odds_api_player_points_props' in query and 'latest_props' in query:
                mock_result.to_dataframe.return_value = mock_bigquery_responses['props']
            elif 'nbac_schedule' in query:
                mock_result.to_dataframe.return_value = mock_bigquery_responses['schedule']
            elif 'bdl_player_boxscores' in query:
                mock_result.to_dataframe.return_value = mock_bigquery_responses['boxscores']
            elif 'opening_lines AS' in query or 'earliest_snapshot' in query:
                if 'points_line' in query:
                    mock_result.to_dataframe.return_value = mock_bigquery_responses['prop_lines_opening'].head(1)
                elif 'spreads' in query:
                    mock_result.to_dataframe.return_value = mock_bigquery_responses['game_lines_spreads_opening']
                else:
                    mock_result.to_dataframe.return_value = mock_bigquery_responses['game_lines_totals_opening']
            elif 'current_lines AS' in query or 'latest_snapshot' in query:
                if 'points_line' in query:
                    mock_result.to_dataframe.return_value = mock_bigquery_responses['prop_lines_current'].head(1)
                elif 'spreads' in query:
                    mock_result.to_dataframe.return_value = mock_bigquery_responses['game_lines_spreads_current']
                else:
                    mock_result.to_dataframe.return_value = mock_bigquery_responses['game_lines_totals_current']
            else:
                mock_result.to_dataframe.return_value = pd.DataFrame()

            return mock_result

        processor.bq_client.query.side_effect = mock_query_response
        processor.bq_client.insert_rows_json.return_value = []  # Success
        
        # Run processor
        result = processor.process_date(date(2025, 11, 20))
        
        # Verify success
        assert result['status'] == 'success'
        assert result['players_processed'] == 2  # LeBron and Curry
        assert result['players_failed'] == 0
        
        # Verify BigQuery insert was called
        assert processor.bq_client.insert_rows_json.called
        
        # Get inserted data
        insert_call = processor.bq_client.insert_rows_json.call_args
        inserted_data = insert_call[0][1]
        
        # Verify we have 2 records
        assert len(inserted_data) == 2
        
        # Verify record structure
        record = inserted_data[0]
        assert 'player_lookup' in record
        assert 'game_id' in record
        assert 'team_abbr' in record
        assert 'current_points_line' in record
        assert 'days_rest' in record
        assert 'points_avg_last_5' in record
    
    def test_no_players_with_props(self, processor):
        """Test handling when no players have prop bets."""
        # Mock empty props response
        mock_result = Mock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        processor.bq_client.query.return_value = mock_result
        
        # Run processor
        result = processor.process_date(date(2025, 11, 20))
        
        # Should succeed with 0 players processed
        assert result['status'] == 'success'
        assert result['players_processed'] == 0
    
    def test_player_with_no_history(self, processor, mock_bigquery_responses):
        """Test handling of rookie player with no boxscore history."""
        # Setup: Player with props but no historical games
        mock_bigquery_responses['props'] = pd.DataFrame([{
            'player_lookup': 'rookieplayer',
            'game_id': '20251120_LAL_BOS',
            'game_date': date(2025, 11, 20),
            'home_team_abbr': 'BOS',
            'away_team_abbr': 'LAL'
        }])
        
        def mock_query_response(query):
            mock_result = Mock()
            if 'odds_api_player_points_props' in query:
                mock_result.to_dataframe.return_value = mock_bigquery_responses['props']
            elif 'nbac_schedule' in query:
                mock_result.to_dataframe.return_value = mock_bigquery_responses['schedule']
            elif 'bdl_player_boxscores' in query:
                # No historical games
                mock_result.to_dataframe.return_value = pd.DataFrame()
            else:
                # Mock prop and game lines
                mock_result.to_dataframe.return_value = pd.DataFrame([
                    {'points_line': 15.5, 'bookmaker': 'draftkings', 'snapshot_timestamp': datetime.now()}
                ])
            return mock_result
        
        processor.bq_client.query.side_effect = mock_query_response
        processor.bq_client.insert_rows_json.return_value = []
        
        # Run processor
        result = processor.process_date(date(2025, 11, 20))
        
        # Should fail to process this player (can't determine team)
        assert result['players_failed'] == 1


class TestDataExtractionScenarios:
    """Test various data extraction scenarios."""
    
    @pytest.fixture
    def processor(self):
        """Create processor with mocked BigQuery client."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2025, 11, 20)
        return proc
    
    def test_extract_players_with_props_success(self, processor):
        """Test successful extraction of players with props."""
        # Mock response
        mock_result = Mock()
        mock_result.to_dataframe.return_value = pd.DataFrame([
            {'player_lookup': 'lebronjames', 'game_id': '20251120_LAL_BOS', 
             'game_date': date(2025, 11, 20), 'home_team_abbr': 'BOS', 'away_team_abbr': 'LAL'},
            {'player_lookup': 'stephencurry', 'game_id': '20251120_GSW_PHX',
             'game_date': date(2025, 11, 20), 'home_team_abbr': 'PHX', 'away_team_abbr': 'GSW'}
        ])
        processor.bq_client.query.return_value = mock_result
        
        # Extract
        processor._extract_players_with_props()
        
        # Verify
        assert len(processor.players_to_process) == 2
        assert processor.source_tracking['props']['rows_found'] == 2
        assert processor.players_to_process[0]['player_lookup'] == 'lebronjames'
    
    def test_extract_schedule_data(self, processor):
        """Test schedule data extraction."""
        # Setup players
        processor.players_to_process = [
            {'player_lookup': 'lebronjames', 'game_id': '20251120_LAL_BOS'}
        ]
        
        # Mock response
        mock_result = Mock()
        mock_result.to_dataframe.return_value = pd.DataFrame([
            {
                'game_id': '20251120_LAL_BOS',
                'game_date': date(2025, 11, 20),
                'home_team_abbr': 'BOS',
                'away_team_abbr': 'LAL',
                'game_date_est': datetime(2025, 11, 20, 19, 30),
                'is_primetime': True,
                'season_year': 2025
            }
        ])
        processor.bq_client.query.return_value = mock_result
        
        # Extract
        processor._extract_schedule_data()
        
        # Verify
        assert '20251120_LAL_BOS' in processor.schedule_data
        assert processor.schedule_data['20251120_LAL_BOS']['home_team_abbr'] == 'BOS'
        assert processor.source_tracking['schedule']['rows_found'] == 1


class TestCalculationScenarios:
    """Test calculation scenarios with realistic data."""
    
    @pytest.fixture
    def processor(self):
        """Create processor with sample data."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2025, 11, 20)
        
        # Setup sample historical data
        proc.historical_boxscores = {
            'lebronjames': pd.DataFrame([
                {'game_date': date(2025, 11, 19), 'team_abbr': 'LAL', 'points': 25, 
                 'minutes': '35:30', 'minutes_decimal': 35.5},
                {'game_date': date(2025, 11, 17), 'team_abbr': 'LAL', 'points': 28,
                 'minutes': '37:15', 'minutes_decimal': 37.25},
                {'game_date': date(2025, 11, 15), 'team_abbr': 'LAL', 'points': 22,
                 'minutes': '34:00', 'minutes_decimal': 34.0}
            ])
        }
        
        # Setup game info
        proc.schedule_data = {
            '20251120_LAL_BOS': {
                'game_id': '20251120_LAL_BOS',
                'home_team_abbr': 'BOS',
                'away_team_abbr': 'LAL',
                'game_date': date(2025, 11, 20)
            }
        }
        
        # Setup prop lines
        proc.prop_lines = {
            ('lebronjames', '20251120_LAL_BOS'): {
                'opening_line': 24.5,
                'opening_source': 'draftkings',
                'current_line': 25.5,
                'current_source': 'fanduel',
                'line_movement': 1.0
            }
        }
        
        # Setup game lines
        proc.game_lines = {
            '20251120_LAL_BOS': {
                'game_spread': -5.5,
                'opening_spread': -5.0,
                'spread_movement': -0.5,
                'spread_source': 'consensus',
                'game_total': 226.5,
                'opening_total': 225.0,
                'total_movement': 1.5,
                'total_source': 'consensus'
            }
        }
        
        # Setup source tracking
        proc.source_tracking = {
            'boxscore': {'last_updated': datetime(2025, 11, 20, 10, 0), 'rows_found': 3},
            'schedule': {'last_updated': datetime(2025, 11, 20, 9, 0), 'rows_found': 1},
            'props': {'last_updated': datetime(2025, 11, 20, 11, 0), 'rows_found': 1},
            'game_lines': {'last_updated': datetime(2025, 11, 20, 11, 0), 'rows_found': 1}
        }
        
        return proc
    
    def test_calculate_player_context_complete(self, processor):
        """Test complete player context calculation."""
        player_info = {
            'player_lookup': 'lebronjames',
            'game_id': '20251120_LAL_BOS',
            'home_team_abbr': 'BOS',
            'away_team_abbr': 'LAL'
        }
        
        # Calculate context
        context = processor._calculate_player_context(player_info)
        
        # Verify core fields
        assert context is not None
        assert context['player_lookup'] == 'lebronjames'
        assert context['game_id'] == '20251120_LAL_BOS'
        assert context['team_abbr'] == 'LAL'
        assert context['opponent_team_abbr'] == 'BOS'
        
        # Verify prop context
        assert context['current_points_line'] == 25.5
        assert context['opening_points_line'] == 24.5
        assert context['line_movement'] == 1.0
        
        # Verify fatigue metrics
        assert context['days_rest'] == 1  # Last game was 11/19
        assert context['back_to_back'] is False
        
        # Verify performance metrics
        assert context['points_avg_last_5'] is not None
        
        # Verify game context
        assert context['game_spread'] == -5.5
        assert context['game_total'] == 226.5
        assert context['home_game'] is False  # LAL is away team
        
        # Verify data quality
        assert context['data_quality_tier'] == 'low'  # Only 3 games
        
        # Verify source tracking fields exist
        assert 'source_boxscore_last_updated' in context
        assert 'source_schedule_last_updated' in context
        assert 'source_props_last_updated' in context
        assert 'source_game_lines_last_updated' in context


class TestErrorHandling:
    """Test error handling scenarios."""
    
    @pytest.fixture
    def processor(self):
        """Create processor with mocked BigQuery client."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        return proc
    
    def test_bigquery_query_error(self, processor):
        """Test handling of BigQuery query error."""
        # Mock query error
        processor.bq_client.query.side_effect = Exception("BigQuery error")
        
        # Run processor
        result = processor.process_date(date(2025, 11, 20))
        
        # Should return error status
        assert result['status'] == 'error'
        assert 'BigQuery error' in result['error']
    
    def test_bigquery_insert_error(self, processor):
        """Test handling of BigQuery insert error."""
        # Mock successful queries
        mock_result = Mock()
        mock_result.to_dataframe.return_value = pd.DataFrame()
        processor.bq_client.query.return_value = mock_result
        
        # Mock insert error
        processor.bq_client.insert_rows_json.return_value = [
            {'index': 0, 'errors': [{'reason': 'invalid', 'message': 'Invalid data'}]}
        ]
        
        # Setup some data to save
        processor.transformed_data = [{'player_lookup': 'test', 'game_date': '2025-11-20'}]
        
        # Try to save
        success = processor.save_analytics()
        
        # Should fail
        assert success is False


class TestSourceTracking:
    """Test source tracking functionality."""
    
    @pytest.fixture
    def processor(self):
        """Create processor with source tracking data."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.source_tracking = {
            'boxscore': {
                'last_updated': datetime(2025, 11, 20, 10, 0),
                'rows_found': 25,
                'completeness_pct': None
            },
            'schedule': {
                'last_updated': datetime(2025, 11, 20, 9, 0),
                'rows_found': 10,
                'completeness_pct': None
            },
            'props': {
                'last_updated': datetime(2025, 11, 20, 11, 0),
                'rows_found': 10,
                'completeness_pct': None
            },
            'game_lines': {
                'last_updated': datetime(2025, 11, 20, 11, 0),
                'rows_found': 5,
                'completeness_pct': None
            }
        }
        proc.players_to_process = [{'player_lookup': f'player{i}', 'game_id': f'game{i}'} for i in range(10)]
        proc.lookback_days = 30
        return proc
    
    def test_source_tracking_fields_populated(self, processor):
        """Test that source tracking fields are properly populated."""
        fields = processor._build_source_tracking_fields()
        
        # Check all expected fields exist
        assert 'source_boxscore_last_updated' in fields
        assert 'source_boxscore_rows_found' in fields
        assert 'source_boxscore_completeness_pct' in fields
        
        assert 'source_schedule_last_updated' in fields
        assert 'source_schedule_rows_found' in fields
        assert 'source_schedule_completeness_pct' in fields
        
        assert 'source_props_last_updated' in fields
        assert 'source_props_rows_found' in fields
        assert 'source_props_completeness_pct' in fields
        
        assert 'source_game_lines_last_updated' in fields
        assert 'source_game_lines_rows_found' in fields
        assert 'source_game_lines_completeness_pct' in fields
        
        # Check values are correct
        assert fields['source_boxscore_rows_found'] == 25
        assert fields['source_schedule_rows_found'] == 10
        assert fields['source_props_rows_found'] == 10
        assert fields['source_game_lines_rows_found'] == 5


# Run tests with: pytest test_integration.py -v
# Run specific test: pytest test_integration.py::TestFullProcessorFlow::test_successful_full_run -v
# Run with coverage: pytest test_integration.py --cov=data_processors.analytics.upcoming_player_game_context --cov-report=html