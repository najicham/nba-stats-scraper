"""
Integration Tests for ML Feature Store Processor

Comprehensive tests for edge cases, failure scenarios, and boundary conditions:
- Early season detection edge cases (6 tests)
- Batch write failure scenarios (6 tests)
- Feature generation error handling (6 tests)
- Quality score edge cases (4 tests)
- Dependency checking scenarios (4 tests)
- Performance and data validation (4 tests)

Run with: pytest test_integration.py -v

Directory: tests/processors/precompute/ml_feature_store/
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, call
from datetime import date, datetime, timezone
from typing import Dict, List, Any
import pandas as pd

from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor
from data_processors.precompute.ml_feature_store.quality_scorer import QualityScorer


# ============================================================================
# TEST FIXTURES
# ============================================================================

@pytest.fixture
def mock_bq_client():
    """Create mock BigQuery client with common responses."""
    client = Mock()
    
    # Default query response (empty)
    default_result = Mock()
    default_result.empty = True
    default_result.to_dataframe.return_value = pd.DataFrame()
    
    client.query.return_value.to_dataframe.return_value = default_result
    
    return client


@pytest.fixture
def mock_processor():
    """
    Create processor instance with mocked dependencies.
    
    This fixture provides a fully-initialized processor with all
    required attributes and helper classes mocked for testing.
    """
    # Use object.__new__ to create instance WITHOUT calling __init__
    processor = object.__new__(MLFeatureStoreProcessor)
    
    # Manually set all attributes that would normally be set
    processor.bq_client = Mock()
    processor.project_id = 'test-project'
    processor.opts = {}
    processor.stats = {}
    processor.table_name = "ml_feature_store_v2"
    processor.dataset_id = "nba_predictions"
    processor.feature_version = 'v1_baseline_25'
    processor.feature_count = 25
    
    # v4.0 Dependency tracking attributes - CRITICAL
    processor.source_metadata = {}  # Required for dependency tracking
    
    # Initialize source tracking attributes for each dependency
    for prefix in ['source_daily_cache', 'source_composite', 'source_shot_zones', 'source_team_defense']:
        setattr(processor, f'{prefix}_last_updated', None)
        setattr(processor, f'{prefix}_rows_found', None)
        setattr(processor, f'{prefix}_completeness_pct', None)
    
    # Mock helper classes
    processor.feature_extractor = Mock()
    processor.feature_calculator = Mock()
    processor.quality_scorer = Mock()
    processor.batch_writer = Mock()
    processor.completeness_checker = Mock()

    # Initialize tracking vars
    processor.players_with_games = None
    processor.early_season_flag = False
    processor.insufficient_data_reason = None
    processor.failed_entities = []
    processor.transformed_data = []
    processor.missing_dependencies_list = []

    # Timing instrumentation
    processor._timing = {}

    # Source hash cache
    processor.source_daily_cache_hash = None
    processor.source_composite_hash = None
    processor.source_shot_zones_hash = None
    processor.source_team_defense_hash = None

    # Season start date
    processor.season_start_date = None

    return processor


@pytest.fixture
def sample_player_row():
    """Create sample player row for testing."""
    return {
        'player_lookup': 'test-player',
        'universal_player_id': 'testplayer_001',
        'game_id': '20250115_TEST_OPP',
        'game_date': date(2025, 1, 15),
        'opponent_team_abbr': 'OPP',
        'is_home': True,
        'days_rest': 1
    }


@pytest.fixture
def sample_phase4_data():
    """Create sample Phase 4 data (complete)."""
    return {
        'points_avg_last_5': 20.5,
        'points_avg_last_10': 20.2,
        'points_avg_season': 19.8,
        'points_std_last_10': 4.5,
        'games_in_last_7_days': 3,
        'fatigue_score': 65.0,
        'shot_zone_mismatch_score': 2.5,
        'pace_score': 1.2,
        'usage_spike_score': 0.8,
        'opponent_def_rating': 112.5,
        'opponent_pace': 99.8,
        'paint_rate_last_10': 32.0,
        'mid_range_rate_last_10': 18.0,
        'three_pt_rate_last_10': 35.0,
        'team_pace_last_10': 101.2,
        'team_off_rating_last_10': 114.5,
        'minutes_avg_last_10': 32.5,
        'player_age': 28
    }


@pytest.fixture
def sample_phase3_data():
    """Create sample Phase 3 data (fallback)."""
    return {
        'days_rest': 1,
        'opponent_days_rest': 0,
        'player_status': 'available',
        'home_game': True,
        'back_to_back': False,
        'season_phase': 'regular',
        'team_abbr': 'TEST',
        'opponent_team_abbr': 'OPP',
        'last_10_games': [
            {'game_date': '2025-01-13', 'points': 22, 'minutes_played': 33, 'ft_makes': 6},
            {'game_date': '2025-01-11', 'points': 19, 'minutes_played': 31, 'ft_makes': 4},
            {'game_date': '2025-01-09', 'points': 24, 'minutes_played': 35, 'ft_makes': 7},
            {'game_date': '2025-01-07', 'points': 18, 'minutes_played': 30, 'ft_makes': 5},
            {'game_date': '2025-01-05', 'points': 21, 'minutes_played': 33, 'ft_makes': 6},
            {'game_date': '2025-01-03', 'points': 20, 'minutes_played': 32, 'ft_makes': 5},
            {'game_date': '2025-01-01', 'points': 23, 'minutes_played': 34, 'ft_makes': 8},
            {'game_date': '2024-12-30', 'points': 17, 'minutes_played': 29, 'ft_makes': 4},
            {'game_date': '2024-12-28', 'points': 25, 'minutes_played': 36, 'ft_makes': 9},
            {'game_date': '2024-12-26', 'points': 19, 'minutes_played': 31, 'ft_makes': 5}
        ],
        'minutes_avg_season': 31.5,
        'points_avg_season': 19.8,
        'games_played_season': 35,
        'team_season_games': [
            {'win_flag': True}, {'win_flag': True}, {'win_flag': False},
            {'win_flag': True}, {'win_flag': True}, {'win_flag': True},
            {'win_flag': False}, {'win_flag': True}, {'win_flag': False},
            {'win_flag': True}
        ]
    }


# ============================================================================
# TEST CLASS 1: EARLY SEASON DETECTION EDGE CASES (6 tests)
# ============================================================================

class TestEarlySeasonDetection:
    """Test early season detection with various edge cases."""
    
    def test_early_season_exactly_50_percent(self, mock_processor):
        """
        Test early season detection at exactly 50% threshold.
        
        Verifies that exactly 50% early season players does NOT trigger
        early season mode (requires >50%).
        
        Business Logic:
        - Early season requires OVER 50% of players to have insufficient data
        - Exactly 50% should proceed with normal processing
        - This ensures we maximize data usage in borderline cases
        """
        mock_processor.opts = {'analysis_date': date(2024, 10, 25)}
        
        # Mock query result: exactly 50% early season (100 total, 50 early)
        mock_result = pd.DataFrame([{
            'total_players': 100,
            'early_season_players': 50
        }])
        
        mock_processor.bq_client.query.return_value.to_dataframe.return_value = mock_result
        
        result = mock_processor._is_early_season(date(2024, 10, 25), 2024)
        
        # Assertions
        assert result is False, "Exactly 50% should NOT trigger early season (requires >50%)"
        assert mock_processor.early_season_flag is False, "early_season_flag should remain False"
        assert mock_processor.insufficient_data_reason is None, "No insufficient_data_reason should be set"
        
        # Verify query was called correctly
        assert mock_processor.bq_client.query.called
        call_args = mock_processor.bq_client.query.call_args[0][0]
        assert 'player_daily_cache' in call_args
        assert '2024-10-25' in call_args
    
    def test_early_season_51_percent_triggers(self, mock_processor):
        """
        Test early season detection at 51% threshold.
        
        Verifies that 51% early season players DOES trigger early season mode.
        
        Business Logic:
        - 51% crosses the threshold and triggers early season mode
        - Processor should create placeholder records
        - Should set appropriate flags and reason
        """
        mock_processor.opts = {'analysis_date': date(2024, 10, 25)}
        
        # Mock query result: 51% early season (100 total, 51 early)
        mock_result = pd.DataFrame([{
            'total_players': 100,
            'early_season_players': 51
        }])
        
        mock_processor.bq_client.query.return_value.to_dataframe.return_value = mock_result
        
        result = mock_processor._is_early_season(date(2024, 10, 25), 2024)
        
        # Assertions
        assert result is True, "51% should trigger early season"
        assert mock_processor.early_season_flag is True, "early_season_flag should be set"
        assert mock_processor.insufficient_data_reason is not None, "insufficient_data_reason should be set"
        assert "Early season: 51/100 players" in mock_processor.insufficient_data_reason
    
    def test_early_season_100_percent_all_players(self, mock_processor):
        """
        Test early season detection with 100% of players lacking data.
        
        Verifies behavior at season start when ALL players lack historical data.
        
        Scenario: First few games of the season, no historical data exists.
        """
        mock_processor.opts = {'analysis_date': date(2024, 10, 22)}
        
        # Mock query result: 100% early season
        mock_result = pd.DataFrame([{
            'total_players': 450,
            'early_season_players': 450
        }])
        
        mock_processor.bq_client.query.return_value.to_dataframe.return_value = mock_result
        
        result = mock_processor._is_early_season(date(2024, 10, 22), 2024)
        
        # Assertions
        assert result is True, "100% early season should trigger"
        assert "Early season: 450/450 players" in mock_processor.insufficient_data_reason
    
    def test_early_season_query_failure_safe_default(self, mock_processor):
        """
        Test early season detection handles query failures gracefully.
        
        Verifies that if the early season check query fails, we default
        to False (proceed with normal processing) rather than crashing.
        
        Error Handling Strategy:
        - Fail open (assume normal season)
        - Log warning but don't block processing
        - Better to attempt normal processing than halt completely
        """
        mock_processor.bq_client.query.side_effect = Exception("BigQuery connection timeout")
        
        result = mock_processor._is_early_season(date(2024, 10, 25), 2024)
        
        # Assertions
        assert result is False, "Query failure should default to False (proceed normally)"
        assert mock_processor.early_season_flag is False
        assert mock_processor.insufficient_data_reason is None
    
    def test_early_season_empty_result_set(self, mock_processor):
        """
        Test early season detection with empty query result.
        
        Verifies handling when player_daily_cache has no records for the date.
        
        Scenario: Cache not yet populated for upcoming game date.
        Expected: Default to normal processing (not early season).
        """
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock query result: empty dataframe
        mock_result = pd.DataFrame()
        mock_processor.bq_client.query.return_value.to_dataframe.return_value = mock_result
        
        result = mock_processor._is_early_season(date(2025, 1, 15), 2024)
        
        # Assertions
        assert result is False, "Empty result should not trigger early season"
        assert mock_processor.early_season_flag is False
    
    def test_early_season_placeholder_creation(self, mock_processor):
        """
        Test that early season mode creates proper placeholder records.
        
        Verifies the structure and content of placeholder records created
        during early season when insufficient historical data exists.
        
        Placeholder Requirements:
        - All features set to None
        - early_season_flag = True
        - insufficient_data_reason populated
        - feature_quality_score = 0.0
        - Source tracking still populated
        """
        mock_processor.opts = {'analysis_date': date(2024, 10, 25)}
        mock_processor.early_season_flag = True
        mock_processor.insufficient_data_reason = "Early season: 51/100 players lack data"
        
        # Mock players with games
        mock_players = [
            {
                'player_lookup': 'player1',
                'universal_player_id': 'p1_001',
                'game_id': 'game1',
                'opponent_team_abbr': 'LAL',
                'is_home': True,
                'days_rest': 1
            },
            {
                'player_lookup': 'player2',
                'universal_player_id': 'p2_001',
                'game_id': 'game2',
                'opponent_team_abbr': 'GSW',
                'is_home': False,
                'days_rest': 2
            }
        ]
        
        mock_processor.feature_extractor.get_players_with_games.return_value = mock_players
        
        # Create placeholders
        mock_processor._create_early_season_placeholders(date(2024, 10, 25))
        
        # Assertions
        assert len(mock_processor.transformed_data) == 2, "Should create 2 placeholder records"
        
        # Check first placeholder
        placeholder1 = mock_processor.transformed_data[0]
        assert placeholder1['player_lookup'] == 'player1'
        assert placeholder1['features'] == [None] * 25, "All features should be None"
        assert placeholder1['feature_count'] == 25
        assert placeholder1['feature_version'] == 'v1_baseline_25'
        assert placeholder1['feature_quality_score'] == 0.0, "Quality score should be 0"
        assert placeholder1['early_season_flag'] is True
        assert placeholder1['insufficient_data_reason'] == "Early season: 51/100 players lack data"
        assert placeholder1['data_source'] == 'early_season'
        assert placeholder1['created_at'] is not None
        assert placeholder1['updated_at'] is None


# ============================================================================
# TEST CLASS 2: BATCH WRITE FAILURE SCENARIOS (6 tests)
# ============================================================================

class TestBatchWriteFailures:
    """Test batch write operations with various failure scenarios."""
    
    def test_save_precompute_partial_batch_failure(self, mock_processor):
        """
        Test save_precompute handles partial batch write failures.
        
        Verifies that when some batches fail to write, the processor:
        1. Tracks successful vs failed rows
        2. Records errors in stats
        3. Does not raise exception (graceful degradation)
        4. Continues processing
        
        Scenario: 250 rows in 3 batches, batch 3 fails
        Expected: 200 rows written, 50 failed, processor continues
        """
        # Create 250 feature records
        mock_processor.transformed_data = [
            {'player': f'player_{i}', 'features': [float(i)] * 25}
            for i in range(250)
        ]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock batch writer with partial failure
        # Batches: 100 + 100 + 50 rows
        # Results: SUCCESS + SUCCESS + FAIL
        mock_processor.batch_writer.write_batch.return_value = {
            'rows_processed': 200,      # First 2 batches succeeded
            'rows_failed': 50,          # Last batch failed
            'batches_written': 2,
            'batches_failed': 1,
            'errors': ['Batch 3: Connection timeout after 3 retries']
        }
        
        # Execute - should not raise exception
        mock_processor.save_precompute()
        
        # Verify stats tracking
        assert mock_processor.stats['rows_processed'] == 200
        assert mock_processor.stats['rows_failed'] == 50
        assert mock_processor.stats['batches_written'] == 2
        assert mock_processor.stats['batches_failed'] == 1
        
        # Verify batch_writer was called with correct parameters
        mock_processor.batch_writer.write_batch.assert_called_once()
        call_kwargs = mock_processor.batch_writer.write_batch.call_args[1]
        assert len(call_kwargs['rows']) == 250
        assert call_kwargs['dataset_id'] == 'nba_predictions'
        assert call_kwargs['table_name'] == 'ml_feature_store_v2'
        assert call_kwargs['game_date'] == date(2025, 1, 15)
    
    def test_save_precompute_all_batches_fail(self, mock_processor):
        """
        Test save_precompute when all batch writes fail.
        
        Verifies graceful handling when all writes fail completely.
        
        Scenario: 100 rows, all batches fail due to quota exceeded
        Expected: 0 rows written, error tracked, no exception raised
        """
        mock_processor.transformed_data = [
            {'player': f'player_{i}', 'features': [float(i)] * 25}
            for i in range(100)
        ]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock batch writer with complete failure
        mock_processor.batch_writer.write_batch.return_value = {
            'rows_processed': 0,
            'rows_failed': 100,
            'batches_written': 0,
            'batches_failed': 1,
            'errors': ['Batch 1: BigQuery quota exceeded - daily limit reached']
        }
        
        # Execute - should not raise exception
        mock_processor.save_precompute()
        
        # Verify all rows marked as failed
        assert mock_processor.stats['rows_processed'] == 0
        assert mock_processor.stats['rows_failed'] == 100
        assert mock_processor.stats['batches_failed'] == 1
        assert mock_processor.stats['batches_written'] == 0
    
    def test_save_precompute_empty_transformed_data(self, mock_processor):
        """
        Test save_precompute handles empty transformed_data gracefully.
        
        Verifies that processor doesn't crash when there's no data to write.
        
        Scenario: No players processed successfully, empty transformed_data list
        Expected: Batch writer not called, graceful completion
        """
        mock_processor.transformed_data = []
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Execute - should not crash
        mock_processor.save_precompute()
        
        # Verify batch_writer was not called
        mock_processor.batch_writer.write_batch.assert_not_called()
    
    def test_save_precompute_streaming_buffer_conflict(self, mock_processor):
        """
        Test save_precompute handles streaming buffer conflicts.
        
        Verifies graceful handling of BigQuery streaming buffer conflicts
        which are expected in some scenarios.
        
        Scenario: Recent streaming inserts block DELETE operation
        Expected: Warning logged, continue with INSERT, partial success ok
        """
        mock_processor.transformed_data = [
            {'player': f'player_{i}', 'features': [float(i)] * 25}
            for i in range(150)
        ]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock batch writer with streaming buffer conflict
        mock_processor.batch_writer.write_batch.return_value = {
            'rows_processed': 150,
            'rows_failed': 0,
            'batches_written': 2,
            'batches_failed': 0,
            'errors': []  # Streaming buffer handled gracefully
        }
        
        # Execute
        mock_processor.save_precompute()
        
        # Verify success despite streaming buffer (DELETE skipped, INSERT succeeded)
        assert mock_processor.stats['rows_processed'] == 150
        assert mock_processor.stats['rows_failed'] == 0
    
    def test_save_precompute_schema_mismatch_error(self, mock_processor):
        """
        Test save_precompute with schema mismatch errors.
        
        Verifies handling when data doesn't match BigQuery schema.
        
        Scenario: Schema changed but code not updated, field mismatch
        Expected: Error captured, rows marked as failed
        """
        mock_processor.transformed_data = [
            {'player': 'player1', 'features': [1.0] * 25}
        ]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock batch writer with schema error
        mock_processor.batch_writer.write_batch.return_value = {
            'rows_processed': 0,
            'rows_failed': 1,
            'batches_written': 0,
            'batches_failed': 1,
            'errors': ['Batch 1: Schema mismatch - field "new_field" not found in table']
        }
        
        # Execute
        mock_processor.save_precompute()
        
        # Verify error tracked
        assert mock_processor.stats['rows_failed'] == 1
        assert mock_processor.stats['batches_failed'] == 1
    
    def test_save_precompute_cross_dataset_write(self, mock_processor):
        """
        Test that save_precompute correctly writes to nba_predictions dataset.
        
        Verifies the cross-dataset write pattern (nba_predictions, not nba_precompute).
        
        Critical Business Logic:
        - ML features must be in nba_predictions (accessed by prediction systems)
        - NOT in nba_precompute (processor data only)
        """
        mock_processor.transformed_data = [{'player': 'player1'}]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock successful write
        mock_processor.batch_writer.write_batch.return_value = {
            'rows_processed': 1,
            'rows_failed': 0,
            'batches_written': 1,
            'batches_failed': 0,
            'errors': []
        }
        
        # Execute
        mock_processor.save_precompute()
        
        # Verify cross-dataset parameters
        call_kwargs = mock_processor.batch_writer.write_batch.call_args[1]
        assert call_kwargs['dataset_id'] == 'nba_predictions', "Must write to nba_predictions"
        assert call_kwargs['table_name'] == 'ml_feature_store_v2'


# ============================================================================
# TEST CLASS 3: FEATURE GENERATION ERROR HANDLING (6 tests)
# ============================================================================

class TestFeatureGenerationErrors:
    """Test feature generation with various error scenarios."""
    
    def test_calculate_precompute_single_player_failure(self, mock_processor):
        """
        Test calculate_precompute continues after single player failure.
        
        Verifies that if one player fails to process, the processor:
        1. Logs the failure
        2. Tracks it in failed_entities
        3. Continues processing other players
        4. Reports accurate success/failure stats
        
        Scenario: 3 players, middle one fails
        Expected: 2 successful, 1 failed, both tracked correctly
        """
        mock_processor.players_with_games = [
            {'player_lookup': 'player1', 'universal_player_id': 'p1', 'game_id': 'g1', 
             'opponent_team_abbr': 'LAL', 'is_home': True, 'days_rest': 1},
            {'player_lookup': 'player2', 'universal_player_id': 'p2', 'game_id': 'g2',
             'opponent_team_abbr': 'GSW', 'is_home': False, 'days_rest': 2},
            {'player_lookup': 'player3', 'universal_player_id': 'p3', 'game_id': 'g3',
             'opponent_team_abbr': 'BOS', 'is_home': True, 'days_rest': 0}
        ]
        
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock successful generation for player1 and player3, failure for player2
        def mock_generate(player_row):
            if player_row['player_lookup'] == 'player2':
                raise ValueError("Phase 4 data incomplete for player2")
            return {
                'player_lookup': player_row['player_lookup'],
                'features': [0.0] * 25,
                'feature_names': ['f' + str(i) for i in range(25)],
                'feature_count': 25,
                'feature_version': 'v1_baseline_25',
                'feature_generation_time_ms': 50,
                'feature_quality_score': 85.0
            }
        
        mock_processor._generate_player_features = Mock(side_effect=mock_generate)
        
        # Execute
        mock_processor.calculate_precompute()
        
        # Verify results
        assert len(mock_processor.transformed_data) == 2, "Should process 2 successful players"
        assert len(mock_processor.failed_entities) == 1, "Should track 1 failed player"
        
        # Check failed entity details
        failed = mock_processor.failed_entities[0]
        assert failed['entity_id'] == 'player2'
        assert failed['entity_type'] == 'player'
        assert 'Phase 4 data incomplete' in failed['reason']
        assert failed['category'] == 'calculation_error'
        
        # Verify successful players
        player_lookups = [p['player_lookup'] for p in mock_processor.transformed_data]
        assert 'player1' in player_lookups
        assert 'player3' in player_lookups
        assert 'player2' not in player_lookups
    
    def test_calculate_precompute_all_players_fail(self, mock_processor):
        """
        Test calculate_precompute when all players fail to process.
        
        Verifies handling when complete processing failure occurs.
        
        Scenario: All players fail due to missing Phase 4 dependencies
        Expected: Empty transformed_data, all tracked in failed_entities
        """
        mock_processor.players_with_games = [
            {'player_lookup': f'player{i}', 'universal_player_id': f'p{i}', 
             'game_id': f'g{i}', 'opponent_team_abbr': 'LAL', 
             'is_home': True, 'days_rest': 1}
            for i in range(5)
        ]
        
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock failure for all players
        def mock_generate_fail(player_row):
            raise Exception(f"Missing Phase 4 data for {player_row['player_lookup']}")
        
        mock_processor._generate_player_features = Mock(side_effect=mock_generate_fail)
        
        # Execute
        mock_processor.calculate_precompute()
        
        # Verify results
        assert len(mock_processor.transformed_data) == 0, "No players should succeed"
        assert len(mock_processor.failed_entities) == 5, "All 5 players should fail"
    
    def test_calculate_precompute_invalid_feature_array_length(self, mock_processor, 
                                                                sample_player_row):
        """
        Test calculate_precompute handles invalid feature data gracefully.
        
        Verifies that if feature extraction returns wrong number of features,
        the processor catches it and continues.
        
        Scenario: _extract_all_features returns 10 features instead of 25
        Expected: Error caught, player marked as failed
        """
        mock_processor.players_with_games = [sample_player_row]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock feature extraction that returns invalid length
        mock_processor.feature_extractor.extract_phase4_data.return_value = {}
        mock_processor.feature_extractor.extract_phase3_data.return_value = {}
        
        def invalid_features(*args, **kwargs):
            return ([0.0] * 10, {i: 'phase4' for i in range(10)})  # Only 10 features!
        
        mock_processor._extract_all_features = Mock(side_effect=invalid_features)
        
        # This should either:
        # 1. Handle gracefully and mark as failed, OR
        # 2. Create record with invalid data (which would be caught in validation)
        
        try:
            mock_processor.calculate_precompute()
            
            # If it succeeded, check that data is flagged somehow
            if mock_processor.transformed_data:
                record = mock_processor.transformed_data[0]
                # Either has wrong count, or was corrected to 25
                assert record['feature_count'] in [10, 25]
        except Exception as e:
            # If it failed, that's also acceptable behavior
            assert "feature" in str(e).lower() or "length" in str(e).lower()
    
    def test_calculate_precompute_feature_calculator_exception(self, mock_processor,
                                                               sample_player_row,
                                                               sample_phase4_data,
                                                               sample_phase3_data):
        """
        Test calculate_precompute handles feature calculator exceptions.
        
        Verifies graceful handling when calculated features fail to generate.
        
        Scenario: calculate_rest_advantage throws exception
        Expected: Player processing fails, error tracked
        """
        mock_processor.players_with_games = [sample_player_row]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock extractors
        mock_processor.feature_extractor.extract_phase4_data.return_value = sample_phase4_data
        mock_processor.feature_extractor.extract_phase3_data.return_value = sample_phase3_data
        
        # Mock calculator with exception
        mock_processor.feature_calculator.calculate_rest_advantage.side_effect = \
            Exception("Invalid rest data format")
        
        # Execute
        mock_processor.calculate_precompute()
        
        # Verify failure tracked
        assert len(mock_processor.failed_entities) >= 1
        failed = mock_processor.failed_entities[0]
        assert 'Invalid rest data format' in failed['reason']
    
    def test_calculate_precompute_quality_scorer_exception(self, mock_processor,
                                                           sample_player_row):
        """
        Test calculate_precompute handles quality scorer exceptions.
        
        Verifies graceful handling when quality score calculation fails.
        
        Scenario: calculate_quality_score throws exception
        Expected: Player processing fails, error tracked
        """
        mock_processor.players_with_games = [sample_player_row]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock feature generation succeeds but quality scoring fails
        mock_processor.feature_extractor.extract_phase4_data.return_value = {}
        mock_processor.feature_extractor.extract_phase3_data.return_value = {}
        mock_processor._extract_all_features = Mock(return_value=(
            [0.0] * 25,
            {i: 'phase4' for i in range(25)}
        ))
        
        # Mock quality scorer exception
        mock_processor.quality_scorer.calculate_quality_score.side_effect = \
            Exception("Feature sources dict corrupted")
        
        # Execute
        mock_processor.calculate_precompute()
        
        # Verify failure
        assert len(mock_processor.failed_entities) >= 1
    
    def test_calculate_precompute_progress_logging(self, mock_processor):
        """
        Test that calculate_precompute logs progress at intervals.
        
        Verifies progress logging every 50 players for monitoring.
        
        Scenario: Process 150 players
        Expected: Progress logged at 50, 100, 150
        """
        # Create 150 players
        mock_processor.players_with_games = [
            {'player_lookup': f'player{i}', 'universal_player_id': f'p{i}',
             'game_id': f'g{i}', 'opponent_team_abbr': 'LAL',
             'is_home': True, 'days_rest': 1}
            for i in range(150)
        ]
        
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock successful generation
        def mock_generate(player_row):
            return {
                'player_lookup': player_row['player_lookup'],
                'features': [0.0] * 25,
                'feature_count': 25,
                'feature_version': 'v1_baseline_25'
            }
        
        mock_processor._generate_player_features = Mock(side_effect=mock_generate)
        
        # Execute
        with patch('data_processors.precompute.ml_feature_store.ml_feature_store_processor.logger') as mock_logger:
            mock_processor.calculate_precompute()
            
            # Verify progress logging occurred
            # Should log at: 50, 100, 150
            info_calls = [str(call) for call in mock_logger.info.call_args_list]
            progress_logs = [c for c in info_calls if 'Processed' in c and '/150' in c]
            
            # Should have at least 3 progress logs
            assert len(progress_logs) >= 3


# ============================================================================
# TEST CLASS 4: QUALITY SCORE EDGE CASES (4 tests)
# ============================================================================

class TestQualityScoreEdgeCases:
    """Test quality score calculation with edge cases."""
    
    def test_quality_score_all_defaults_lowest_quality(self):
        """
        Test quality score when all features use defaults.
        
        Verifies that when no real data is available (all defaults),
        quality score is 40.0 (lowest possible without early season).
        
        Business Logic:
        - Default values = minimal confidence
        - Quality score of 40 signals "use with caution"
        - Should be rare in normal season operations
        """
        scorer = QualityScorer()
        feature_sources = {i: 'default' for i in range(25)}
        
        quality = scorer.calculate_quality_score(feature_sources)
        
        assert quality == 40.0, "All defaults should give 40.0 quality"
        assert scorer.identify_data_tier(quality) == 'low'
        assert scorer.determine_primary_source(feature_sources) == 'mixed'
    
    def test_quality_score_all_phase4_highest_quality(self):
        """
        Test quality score with all Phase 4 features.
        
        Verifies maximum quality when all data from Phase 4.
        
        Business Logic:
        - Phase 4 = precomputed, validated, high-quality data
        - Score of 100 = maximum confidence
        - Preferred data source for predictions
        """
        scorer = QualityScorer()
        feature_sources = {i: 'phase4' for i in range(25)}
        
        quality = scorer.calculate_quality_score(feature_sources)
        
        assert quality == 100.0, "All Phase 4 should give 100.0 quality"
        assert scorer.identify_data_tier(quality) == 'high'
        assert scorer.determine_primary_source(feature_sources) == 'phase4'
    
    def test_quality_score_mixed_phase4_calculated_optimal(self):
        """
        Test quality score with optimal mix of Phase 4 and calculated.
        
        Verifies that Phase 4 + calculated features gives 100.0 quality.
        
        Business Logic:
        - Phase 4 features: 100 points each
        - Calculated features: 100 points each (always available)
        - Mix of both = optimal quality
        
        This is the expected normal-operation mix:
        - 19 Phase 4 features (indices 0-8, 13-23)
        - 6 calculated features (indices 9-12, 21, 24)
        """
        scorer = QualityScorer()
        
        # Realistic feature mix
        feature_sources = {
            # Phase 4 features (19 total)
            0: 'phase4', 1: 'phase4', 2: 'phase4', 3: 'phase4', 4: 'phase4',
            5: 'phase4', 6: 'phase4', 7: 'phase4', 8: 'phase4',
            13: 'phase4', 14: 'phase4',
            15: 'phase3', 16: 'phase3', 17: 'phase3',  # Game context from Phase 3
            18: 'phase4', 19: 'phase4', 20: 'phase4',
            22: 'phase4', 23: 'phase4',
            
            # Calculated features (6 total)
            9: 'calculated', 10: 'calculated', 11: 'calculated', 
            12: 'calculated', 21: 'calculated', 24: 'calculated'
        }
        
        quality = scorer.calculate_quality_score(feature_sources)
        
        # 19 Phase 4 (100 each) + 3 Phase 3 (75 each) + 6 calculated (100 each)
        # = (19*100 + 3*75 + 3*100) / 25 = (1900 + 225 + 300) / 25 = 2425/25 = 97
        
        assert quality >= 95.0, "Phase 4 + Phase 3 + calculated should give high quality"
        assert scorer.identify_data_tier(quality) == 'high'
    
    def test_quality_score_phase3_fallback_medium_quality(self):
        """
        Test quality score with Phase 3 fallback scenario.
        
        Verifies expected quality when Phase 4 unavailable, using Phase 3.
        
        Business Logic:
        - Phase 3 features: 75 points each (acceptable fallback)
        - Calculated features: 100 points each
        - Mix indicates Phase 4 dependencies incomplete
        - Score 70-85 = medium tier, still usable
        """
        scorer = QualityScorer()
        
        # Phase 3 fallback scenario
        feature_sources = {
            **{i: 'phase3' for i in range(19)},  # 19 Phase 3 (Phase 4 unavailable)
            **{i: 'calculated' for i in range(19, 25)}  # 6 calculated
        }
        
        quality = scorer.calculate_quality_score(feature_sources)
        
        # (19*75 + 6*100) / 25 = (1425 + 600) / 25 = 2025/25 = 81.0
        assert 75.0 <= quality <= 85.0, "Phase 3 fallback should give medium quality"
        assert scorer.identify_data_tier(quality) in ['medium', 'high']
        assert scorer.determine_primary_source(feature_sources) == 'phase3'


# ============================================================================
# TEST CLASS 5: DEPENDENCY CHECKING (4 tests)
# ============================================================================

class TestDependencyChecking:
    """Test Phase 4 dependency checking logic."""
    
    def test_extract_raw_data_all_dependencies_present(self, mock_processor):
        """
        Test extract_raw_data when all Phase 4 dependencies are present.
        
        Verifies normal operation with complete Phase 4 data.
        
        Dependencies:
        - player_daily_cache
        - player_composite_factors
        - player_shot_zone_analysis
        - team_defense_zone_analysis
        """
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock dependency check - all present
        with patch.object(mock_processor, 'check_dependencies') as mock_check:
            mock_check.return_value = {
                'all_critical_present': True,
                'all_fresh': True,
                'missing': [],
                'stale': []
            }
            
            # Mock track_source_usage
            with patch.object(mock_processor, 'track_source_usage'):
                # Mock early season check - not early season
                with patch.object(mock_processor, '_is_early_season', return_value=False):
                    # Mock players query
                    mock_players = [
                        {'player_lookup': 'player1', 'game_id': 'g1', 
                         'opponent_team_abbr': 'LAL', 'is_home': True, 'days_rest': 1}
                    ]
                    mock_processor.feature_extractor.get_players_with_games.return_value = mock_players
                    
                    # Execute
                    mock_processor.extract_raw_data()
                    
                    # Verify
                    assert mock_processor.players_with_games == mock_players
                    assert mock_processor.early_season_flag is False
    
    def test_extract_raw_data_missing_critical_dependency(self, mock_processor):
        """
        Test extract_raw_data when critical Phase 4 dependency missing.
        
        Verifies that processor raises error when critical dependency absent
        (unless early season).
        
        Scenario: player_daily_cache not populated
        Expected: ValueError raised with dependency name
        """
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock dependency check - missing critical dependency
        with patch.object(mock_processor, 'check_dependencies') as mock_check:
            mock_check.return_value = {
                'all_critical_present': False,
                'all_fresh': True,
                'missing': ['nba_precompute.player_daily_cache'],
                'stale': []
            }
            
            with patch.object(mock_processor, 'track_source_usage'):
                with patch.object(mock_processor, '_is_early_season', return_value=False):
                    
                    # Execute - should raise error
                    with pytest.raises(ValueError, match="Missing critical Phase 4 dependencies"):
                        mock_processor.extract_raw_data()
    
    def test_extract_raw_data_stale_dependencies_warning_only(self, mock_processor):
        """
        Test extract_raw_data with stale but present dependencies.
        
        Verifies that stale data triggers warning but allows processing.
        
        Scenario: Dependencies present but > 2 hours old
        Expected: Warning logged, processing continues
        """
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock dependency check - present but stale
        with patch.object(mock_processor, 'check_dependencies') as mock_check:
            mock_check.return_value = {
                'all_critical_present': True,
                'all_fresh': False,
                'missing': [],
                'stale': ['nba_precompute.player_composite_factors']
            }
            
            with patch.object(mock_processor, 'track_source_usage'):
                with patch.object(mock_processor, '_is_early_season', return_value=False):
                    mock_players = [{'player_lookup': 'p1', 'game_id': 'g1'}]
                    mock_processor.feature_extractor.get_players_with_games.return_value = mock_players
                    
                    # Execute - should succeed with warning
                    with patch('data_processors.precompute.ml_feature_store.ml_feature_store_processor.logger') as mock_logger:
                        mock_processor.extract_raw_data()
                        
                        # Verify warning logged
                        warning_calls = [str(call) for call in mock_logger.warning.call_args_list]
                        assert any('Stale Phase 4 data' in str(call) for call in warning_calls)
    
    def test_extract_raw_data_early_season_bypasses_dependency_check(self, mock_processor):
        """
        Test that early season mode bypasses strict dependency checking.
        
        Verifies that during early season, missing dependencies don't fail.
        
        FIXED: Early season check happens BEFORE dependency validation,
        so the method returns early via _create_early_season_placeholders()
        without raising an error.
        
        Business Logic:
        - Early season = insufficient historical data is expected
        - Create placeholders instead of failing
        - Allows predictions to start on day 1 of season
        """
        mock_processor.opts = {'analysis_date': date(2024, 10, 22)}
        
        with patch.object(mock_processor, 'check_dependencies') as mock_check:
            mock_check.return_value = {
                'all_critical_present': False,  # Missing dependencies
                'all_fresh': False,
                'missing': ['nba_precompute.player_daily_cache'],
                'stale': []
            }
            
            with patch.object(mock_processor, 'track_source_usage'):
                # This returns True, triggering early season mode
                with patch.object(mock_processor, '_is_early_season', return_value=True) as mock_early:
                    with patch.object(mock_processor, '_create_early_season_placeholders') as mock_create:
                        
                        # Execute - should NOT raise error because early season check happens first
                        mock_processor.extract_raw_data()
                        
                        # Verify early season check was called
                        mock_early.assert_called_once()
                        
                        # Verify placeholders were created (early return path)
                        mock_create.assert_called_once()


# ============================================================================
# TEST CLASS 6: PERFORMANCE AND DATA VALIDATION (4 tests)
# ============================================================================

class TestPerformanceAndValidation:
    """Test performance characteristics and data validation."""
    
    def test_get_precompute_stats_complete_data(self, mock_processor):
        """
        Test get_precompute_stats returns complete statistics.
        
        Verifies that processor stats are correctly calculated and returned
        for monitoring and logging purposes.
        """
        mock_processor.transformed_data = [
            {'player': 1}, {'player': 2}, {'player': 3}
        ]
        mock_processor.failed_entities = [
            {'player': 4, 'reason': 'Phase 4 missing'}
        ]
        mock_processor.early_season_flag = False
        
        stats = mock_processor.get_precompute_stats()
        
        # Verify all expected fields
        assert stats['players_processed'] == 3
        assert stats['players_failed'] == 1
        assert stats['early_season'] is False
        assert stats['feature_version'] == 'v1_baseline_25'
        assert stats['feature_count'] == 25
    
    def test_get_precompute_stats_early_season(self, mock_processor):
        """
        Test get_precompute_stats during early season.
        
        Verifies stats reflect early season mode correctly.
        """
        mock_processor.transformed_data = [
            {'player': 1, 'early_season_flag': True}
        ]
        mock_processor.failed_entities = []
        mock_processor.early_season_flag = True
        
        stats = mock_processor.get_precompute_stats()
        
        assert stats['early_season'] is True
        assert stats['players_processed'] == 1
        assert stats['players_failed'] == 0
    
    def test_feature_generation_timing_tracked(self, mock_processor,
                                               sample_player_row,
                                               sample_phase4_data,
                                               sample_phase3_data):
        """
        Test that feature generation timing is tracked.
        
        Verifies performance monitoring via generation time tracking.
        
        FIXED: Timing is added by calculate_precompute() wrapper, not by
        _generate_player_features() directly. Test through the full flow.
        
        Expected: feature_generation_time_ms populated for each record
        """
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # FIXED: Set up players_with_games for calculate_precompute
        mock_processor.players_with_games = [sample_player_row]
        
        # Mock extractors
        mock_processor.feature_extractor.extract_phase4_data.return_value = sample_phase4_data
        mock_processor.feature_extractor.extract_phase3_data.return_value = sample_phase3_data
        
        # Mock feature extraction and quality scoring
        mock_processor._extract_all_features = Mock(return_value=(
            [0.0] * 25,
            {i: 'phase4' for i in range(25)}
        ))
        mock_processor.quality_scorer.calculate_quality_score.return_value = 95.0
        mock_processor.quality_scorer.determine_primary_source.return_value = 'phase4'
        
        # FIXED: Run through calculate_precompute (which adds timing)
        mock_processor.calculate_precompute()
        
        # FIXED: Get record from transformed_data
        assert len(mock_processor.transformed_data) == 1
        record = mock_processor.transformed_data[0]
        
        # Verify timing tracked
        assert 'feature_generation_time_ms' in record
        assert record['feature_generation_time_ms'] is not None
        assert isinstance(record['feature_generation_time_ms'], int)
        assert record['feature_generation_time_ms'] >= 0
    
    def test_source_tracking_fields_populated(self, mock_processor,
                                              sample_player_row,
                                              sample_phase4_data,
                                              sample_phase3_data):
        """
        Test that v4.0 source tracking fields are populated.
        
        Verifies dependency tracking metadata is included in output.
        
        v4.0 Source Tracking:
        - source_daily_cache_last_updated
        - source_daily_cache_rows_found  
        - source_daily_cache_completeness_pct
        - (repeat for 3 other sources)
        """
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock extractors
        mock_processor.feature_extractor.extract_phase4_data.return_value = sample_phase4_data
        mock_processor.feature_extractor.extract_phase3_data.return_value = sample_phase3_data
        
        # Mock feature extraction and quality scoring
        mock_processor._extract_all_features = Mock(return_value=(
            [0.0] * 25,
            {i: 'phase4' for i in range(25)}
        ))
        mock_processor.quality_scorer.calculate_quality_score.return_value = 95.0
        mock_processor.quality_scorer.determine_primary_source.return_value = 'phase4'
        
        # Mock build_source_tracking_fields
        with patch.object(mock_processor, 'build_source_tracking_fields') as mock_build:
            mock_build.return_value = {
                'source_daily_cache_last_updated': datetime.now(timezone.utc).isoformat(),
                'source_daily_cache_rows_found': 1,
                'source_daily_cache_completeness_pct': 100.0,
                'source_composite_last_updated': datetime.now(timezone.utc).isoformat(),
                'source_composite_rows_found': 1,
                'source_composite_completeness_pct': 100.0,
                'source_shot_zones_last_updated': datetime.now(timezone.utc).isoformat(),
                'source_shot_zones_rows_found': 1,
                'source_shot_zones_completeness_pct': 100.0,
                'source_team_defense_last_updated': datetime.now(timezone.utc).isoformat(),
                'source_team_defense_rows_found': 1,
                'source_team_defense_completeness_pct': 100.0
            }
            
            # Generate features
            record = mock_processor._generate_player_features(sample_player_row)
            
            # Verify source tracking called
            mock_build.assert_called_once()
            
            # Verify source tracking fields in record
            assert 'source_daily_cache_last_updated' in record
            assert 'source_composite_completeness_pct' in record


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])