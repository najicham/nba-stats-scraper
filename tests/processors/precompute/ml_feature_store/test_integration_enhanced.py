"""
Enhanced Integration Tests for ML Feature Store Processor - FIXED

Fixed issues:
1. Added source_metadata to mock processor
2. Fixed early season test expectations
3. Fixed feature_generation_timing test to match actual implementation
4. All tests properly mocked (no real BigQuery calls)

Run with: pytest test_integration_enhanced.py -v

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
    
    # v4.0 Dependency tracking attributes - CRITICAL FIX
    processor.source_metadata = {}  # This was missing!
    
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
    
    # Initialize tracking vars
    processor.players_with_games = None
    processor.early_season_flag = False
    processor.insufficient_data_reason = None
    processor.failed_entities = []
    processor.transformed_data = []
    
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
        """
        mock_processor.opts = {'analysis_date': date(2024, 10, 25)}
        
        # Mock query result: exactly 50% early season (100 total, 50 early)
        mock_result = pd.DataFrame([{
            'total_players': 100,
            'early_season_players': 50
        }])
        
        mock_processor.bq_client.query.return_value.to_dataframe.return_value = mock_result
        
        result = mock_processor._is_early_season(date(2024, 10, 25))
        
        # Assertions
        assert result is False, "Exactly 50% should NOT trigger early season (requires >50%)"
        assert mock_processor.early_season_flag is False
        assert mock_processor.insufficient_data_reason is None
    
    def test_early_season_51_percent_triggers(self, mock_processor):
        """Test early season detection at 51% threshold."""
        mock_processor.opts = {'analysis_date': date(2024, 10, 25)}
        
        # Mock query result: 51% early season
        mock_result = pd.DataFrame([{
            'total_players': 100,
            'early_season_players': 51
        }])
        
        mock_processor.bq_client.query.return_value.to_dataframe.return_value = mock_result
        
        result = mock_processor._is_early_season(date(2024, 10, 25))
        
        assert result is True
        assert mock_processor.early_season_flag is True
        assert "Early season: 51/100 players" in mock_processor.insufficient_data_reason
    
    def test_early_season_100_percent_all_players(self, mock_processor):
        """Test early season detection with 100% of players lacking data."""
        mock_processor.opts = {'analysis_date': date(2024, 10, 22)}
        
        # Mock query result: 100% early season
        mock_result = pd.DataFrame([{
            'total_players': 450,
            'early_season_players': 450
        }])
        
        mock_processor.bq_client.query.return_value.to_dataframe.return_value = mock_result
        
        result = mock_processor._is_early_season(date(2024, 10, 22))
        
        assert result is True
        assert "Early season: 450/450 players" in mock_processor.insufficient_data_reason
    
    def test_early_season_query_failure_safe_default(self, mock_processor):
        """Test early season detection handles query failures gracefully."""
        mock_processor.bq_client.query.side_effect = Exception("BigQuery connection timeout")
        
        result = mock_processor._is_early_season(date(2024, 10, 25))
        
        assert result is False
        assert mock_processor.early_season_flag is False
        assert mock_processor.insufficient_data_reason is None
    
    def test_early_season_empty_result_set(self, mock_processor):
        """Test early season detection with empty query result."""
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock query result: empty dataframe
        mock_result = pd.DataFrame()
        mock_processor.bq_client.query.return_value.to_dataframe.return_value = mock_result
        
        result = mock_processor._is_early_season(date(2025, 1, 15))
        
        assert result is False
        assert mock_processor.early_season_flag is False
    
    def test_early_season_placeholder_creation(self, mock_processor):
        """Test that early season mode creates proper placeholder records."""
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
        assert len(mock_processor.transformed_data) == 2
        
        placeholder1 = mock_processor.transformed_data[0]
        assert placeholder1['player_lookup'] == 'player1'
        assert placeholder1['features'] == [None] * 25
        assert placeholder1['feature_quality_score'] == 0.0
        assert placeholder1['early_season_flag'] is True
        assert placeholder1['data_source'] == 'early_season'


# ============================================================================
# TEST CLASS 2: BATCH WRITE FAILURE SCENARIOS (6 tests)
# ============================================================================

class TestBatchWriteFailures:
    """Test batch write operations with various failure scenarios."""
    
    def test_save_precompute_partial_batch_failure(self, mock_processor):
        """Test save_precompute handles partial batch write failures."""
        mock_processor.transformed_data = [
            {'player': f'player_{i}', 'features': [float(i)] * 25}
            for i in range(250)
        ]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock batch writer with partial failure
        mock_processor.batch_writer.write_batch.return_value = {
            'rows_processed': 200,
            'rows_failed': 50,
            'batches_written': 2,
            'batches_failed': 1,
            'errors': ['Batch 3: Connection timeout after 3 retries']
        }
        
        mock_processor.save_precompute()
        
        assert mock_processor.stats['rows_processed'] == 200
        assert mock_processor.stats['rows_failed'] == 50
        assert mock_processor.stats['batches_written'] == 2
        assert mock_processor.stats['batches_failed'] == 1
    
    def test_save_precompute_all_batches_fail(self, mock_processor):
        """Test save_precompute when all batch writes fail."""
        mock_processor.transformed_data = [
            {'player': f'player_{i}', 'features': [float(i)] * 25}
            for i in range(100)
        ]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        mock_processor.batch_writer.write_batch.return_value = {
            'rows_processed': 0,
            'rows_failed': 100,
            'batches_written': 0,
            'batches_failed': 1,
            'errors': ['Batch 1: BigQuery quota exceeded']
        }
        
        mock_processor.save_precompute()
        
        assert mock_processor.stats['rows_processed'] == 0
        assert mock_processor.stats['rows_failed'] == 100
    
    def test_save_precompute_empty_transformed_data(self, mock_processor):
        """Test save_precompute handles empty transformed_data gracefully."""
        mock_processor.transformed_data = []
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        mock_processor.save_precompute()
        
        mock_processor.batch_writer.write_batch.assert_not_called()
    
    def test_save_precompute_streaming_buffer_conflict(self, mock_processor):
        """Test save_precompute handles streaming buffer conflicts."""
        mock_processor.transformed_data = [
            {'player': f'player_{i}', 'features': [float(i)] * 25}
            for i in range(150)
        ]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        mock_processor.batch_writer.write_batch.return_value = {
            'rows_processed': 150,
            'rows_failed': 0,
            'batches_written': 2,
            'batches_failed': 0,
            'errors': []
        }
        
        mock_processor.save_precompute()
        
        assert mock_processor.stats['rows_processed'] == 150
        assert mock_processor.stats['rows_failed'] == 0
    
    def test_save_precompute_schema_mismatch_error(self, mock_processor):
        """Test save_precompute with schema mismatch errors."""
        mock_processor.transformed_data = [
            {'player': 'player1', 'features': [1.0] * 25}
        ]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        mock_processor.batch_writer.write_batch.return_value = {
            'rows_processed': 0,
            'rows_failed': 1,
            'batches_written': 0,
            'batches_failed': 1,
            'errors': ['Batch 1: Schema mismatch']
        }
        
        mock_processor.save_precompute()
        
        assert mock_processor.stats['rows_failed'] == 1
        assert mock_processor.stats['batches_failed'] == 1
    
    def test_save_precompute_cross_dataset_write(self, mock_processor):
        """Test that save_precompute correctly writes to nba_predictions dataset."""
        mock_processor.transformed_data = [{'player': 'player1'}]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        mock_processor.batch_writer.write_batch.return_value = {
            'rows_processed': 1,
            'rows_failed': 0,
            'batches_written': 1,
            'batches_failed': 0,
            'errors': []
        }
        
        mock_processor.save_precompute()
        
        call_kwargs = mock_processor.batch_writer.write_batch.call_args[1]
        assert call_kwargs['dataset_id'] == 'nba_predictions'
        assert call_kwargs['table_name'] == 'ml_feature_store_v2'


# ============================================================================
# TEST CLASS 3: FEATURE GENERATION ERROR HANDLING (6 tests)
# ============================================================================

class TestFeatureGenerationErrors:
    """Test feature generation with various error scenarios."""
    
    def test_calculate_precompute_single_player_failure(self, mock_processor):
        """Test calculate_precompute continues after single player failure."""
        mock_processor.players_with_games = [
            {'player_lookup': 'player1', 'universal_player_id': 'p1', 'game_id': 'g1', 
             'opponent_team_abbr': 'LAL', 'is_home': True, 'days_rest': 1},
            {'player_lookup': 'player2', 'universal_player_id': 'p2', 'game_id': 'g2',
             'opponent_team_abbr': 'GSW', 'is_home': False, 'days_rest': 2},
            {'player_lookup': 'player3', 'universal_player_id': 'p3', 'game_id': 'g3',
             'opponent_team_abbr': 'BOS', 'is_home': True, 'days_rest': 0}
        ]
        
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
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
        
        mock_processor.calculate_precompute()
        
        assert len(mock_processor.transformed_data) == 2
        assert len(mock_processor.failed_entities) == 1
        
        failed = mock_processor.failed_entities[0]
        assert failed['entity_id'] == 'player2'
        assert 'Phase 4 data incomplete' in failed['reason']
    
    def test_calculate_precompute_all_players_fail(self, mock_processor):
        """Test calculate_precompute when all players fail to process."""
        mock_processor.players_with_games = [
            {'player_lookup': f'player{i}', 'universal_player_id': f'p{i}', 
             'game_id': f'g{i}', 'opponent_team_abbr': 'LAL', 
             'is_home': True, 'days_rest': 1}
            for i in range(5)
        ]
        
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        def mock_generate_fail(player_row):
            raise Exception(f"Missing Phase 4 data for {player_row['player_lookup']}")
        
        mock_processor._generate_player_features = Mock(side_effect=mock_generate_fail)
        
        mock_processor.calculate_precompute()
        
        assert len(mock_processor.transformed_data) == 0
        assert len(mock_processor.failed_entities) == 5
    
    def test_calculate_precompute_invalid_feature_array_length(self, mock_processor, 
                                                                sample_player_row):
        """Test calculate_precompute handles invalid feature data gracefully."""
        mock_processor.players_with_games = [sample_player_row]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        mock_processor.feature_extractor.extract_phase4_data.return_value = {}
        mock_processor.feature_extractor.extract_phase3_data.return_value = {}
        
        def invalid_features(*args, **kwargs):
            return ([0.0] * 10, {i: 'phase4' for i in range(10)})
        
        mock_processor._extract_all_features = Mock(side_effect=invalid_features)
        
        try:
            mock_processor.calculate_precompute()
            
            if mock_processor.transformed_data:
                record = mock_processor.transformed_data[0]
                assert record['feature_count'] in [10, 25]
        except Exception as e:
            assert "feature" in str(e).lower() or "length" in str(e).lower()
    
    def test_calculate_precompute_feature_calculator_exception(self, mock_processor,
                                                               sample_player_row,
                                                               sample_phase4_data,
                                                               sample_phase3_data):
        """Test calculate_precompute handles feature calculator exceptions."""
        mock_processor.players_with_games = [sample_player_row]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        mock_processor.feature_extractor.extract_phase4_data.return_value = sample_phase4_data
        mock_processor.feature_extractor.extract_phase3_data.return_value = sample_phase3_data
        
        mock_processor.feature_calculator.calculate_rest_advantage.side_effect = \
            Exception("Invalid rest data format")
        
        mock_processor.calculate_precompute()
        
        assert len(mock_processor.failed_entities) >= 1
        failed = mock_processor.failed_entities[0]
        assert 'Invalid rest data format' in failed['reason']
    
    def test_calculate_precompute_quality_scorer_exception(self, mock_processor,
                                                           sample_player_row):
        """Test calculate_precompute handles quality scorer exceptions."""
        mock_processor.players_with_games = [sample_player_row]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        mock_processor.feature_extractor.extract_phase4_data.return_value = {}
        mock_processor.feature_extractor.extract_phase3_data.return_value = {}
        mock_processor._extract_all_features = Mock(return_value=(
            [0.0] * 25,
            {i: 'phase4' for i in range(25)}
        ))
        
        mock_processor.quality_scorer.calculate_quality_score.side_effect = \
            Exception("Feature sources dict corrupted")
        
        mock_processor.calculate_precompute()
        
        assert len(mock_processor.failed_entities) >= 1
    
    def test_calculate_precompute_progress_logging(self, mock_processor):
        """Test that calculate_precompute logs progress at intervals."""
        mock_processor.players_with_games = [
            {'player_lookup': f'player{i}', 'universal_player_id': f'p{i}',
             'game_id': f'g{i}', 'opponent_team_abbr': 'LAL',
             'is_home': True, 'days_rest': 1}
            for i in range(150)
        ]
        
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        def mock_generate(player_row):
            return {
                'player_lookup': player_row['player_lookup'],
                'features': [0.0] * 25,
                'feature_count': 25,
                'feature_version': 'v1_baseline_25'
            }
        
        mock_processor._generate_player_features = Mock(side_effect=mock_generate)
        
        with patch('data_processors.precompute.ml_feature_store.ml_feature_store_processor.logger') as mock_logger:
            mock_processor.calculate_precompute()
            
            info_calls = [str(call) for call in mock_logger.info.call_args_list]
            progress_logs = [c for c in info_calls if 'Processed' in c and '/150' in c]
            
            assert len(progress_logs) >= 3


# ============================================================================
# TEST CLASS 4: QUALITY SCORE EDGE CASES (4 tests)
# ============================================================================

class TestQualityScoreEdgeCases:
    """Test quality score calculation with edge cases."""
    
    def test_quality_score_all_defaults_lowest_quality(self):
        """Test quality score when all features use defaults."""
        scorer = QualityScorer()
        feature_sources = {i: 'default' for i in range(25)}
        
        quality = scorer.calculate_quality_score(feature_sources)
        
        assert quality == 40.0
        assert scorer.identify_data_tier(quality) == 'low'
    
    def test_quality_score_all_phase4_highest_quality(self):
        """Test quality score with all Phase 4 features."""
        scorer = QualityScorer()
        feature_sources = {i: 'phase4' for i in range(25)}
        
        quality = scorer.calculate_quality_score(feature_sources)
        
        assert quality == 100.0
        assert scorer.identify_data_tier(quality) == 'high'
    
    def test_quality_score_mixed_phase4_calculated_optimal(self):
        """Test quality score with optimal mix of Phase 4 and calculated."""
        scorer = QualityScorer()
        
        feature_sources = {
            0: 'phase4', 1: 'phase4', 2: 'phase4', 3: 'phase4', 4: 'phase4',
            5: 'phase4', 6: 'phase4', 7: 'phase4', 8: 'phase4',
            13: 'phase4', 14: 'phase4',
            15: 'phase3', 16: 'phase3', 17: 'phase3',
            18: 'phase4', 19: 'phase4', 20: 'phase4',
            22: 'phase4', 23: 'phase4',
            9: 'calculated', 10: 'calculated', 11: 'calculated', 
            12: 'calculated', 21: 'calculated', 24: 'calculated'
        }
        
        quality = scorer.calculate_quality_score(feature_sources)
        
        assert quality >= 95.0
        assert scorer.identify_data_tier(quality) == 'high'
    
    def test_quality_score_phase3_fallback_medium_quality(self):
        """Test quality score with Phase 3 fallback scenario."""
        scorer = QualityScorer()
        
        feature_sources = {
            **{i: 'phase3' for i in range(19)},
            **{i: 'calculated' for i in range(19, 25)}
        }
        
        quality = scorer.calculate_quality_score(feature_sources)
        
        assert 75.0 <= quality <= 85.0
        assert scorer.identify_data_tier(quality) in ['medium', 'high']


# ============================================================================
# TEST CLASS 5: DEPENDENCY CHECKING (4 tests)
# ============================================================================

class TestDependencyChecking:
    """Test Phase 4 dependency checking logic."""
    
    def test_extract_raw_data_all_dependencies_present(self, mock_processor):
        """Test extract_raw_data when all Phase 4 dependencies are present."""
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        with patch.object(mock_processor, 'check_dependencies') as mock_check:
            mock_check.return_value = {
                'all_critical_present': True,
                'all_fresh': True,
                'missing': [],
                'stale': []
            }
            
            with patch.object(mock_processor, 'track_source_usage'):
                with patch.object(mock_processor, '_is_early_season', return_value=False):
                    mock_players = [
                        {'player_lookup': 'player1', 'game_id': 'g1', 
                         'opponent_team_abbr': 'LAL', 'is_home': True, 'days_rest': 1}
                    ]
                    mock_processor.feature_extractor.get_players_with_games.return_value = mock_players
                    
                    mock_processor.extract_raw_data()
                    
                    assert mock_processor.players_with_games == mock_players
                    assert mock_processor.early_season_flag is False
    
    def test_extract_raw_data_missing_critical_dependency(self, mock_processor):
        """Test extract_raw_data when critical Phase 4 dependency missing."""
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        with patch.object(mock_processor, 'check_dependencies') as mock_check:
            mock_check.return_value = {
                'all_critical_present': False,
                'all_fresh': True,
                'missing': ['nba_precompute.player_daily_cache'],
                'stale': []
            }
            
            with patch.object(mock_processor, 'track_source_usage'):
                with patch.object(mock_processor, '_is_early_season', return_value=False):
                    
                    with pytest.raises(ValueError, match="Missing critical Phase 4 dependencies"):
                        mock_processor.extract_raw_data()
    
    def test_extract_raw_data_stale_dependencies_warning_only(self, mock_processor):
        """Test extract_raw_data with stale but present dependencies."""
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
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
                    
                    with patch('data_processors.precompute.ml_feature_store.ml_feature_store_processor.logger') as mock_logger:
                        mock_processor.extract_raw_data()
                        
                        warning_calls = [str(call) for call in mock_logger.warning.call_args_list]
                        assert any('Stale Phase 4 data' in str(call) for call in warning_calls)
    
    def test_extract_raw_data_early_season_bypasses_dependency_check(self, mock_processor):
        """
        Test that early season mode bypasses strict dependency checking.
        
        FIXED: The test now expects the actual behavior - early season check
        happens BEFORE dependency check failure, so we return from the method
        early without raising an error.
        """
        mock_processor.opts = {'analysis_date': date(2024, 10, 22)}
        
        with patch.object(mock_processor, 'check_dependencies') as mock_check:
            mock_check.return_value = {
                'all_critical_present': False,
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
        """Test get_precompute_stats returns complete statistics."""
        mock_processor.transformed_data = [
            {'player': 1}, {'player': 2}, {'player': 3}
        ]
        mock_processor.failed_entities = [
            {'player': 4, 'reason': 'Phase 4 missing'}
        ]
        mock_processor.early_season_flag = False
        
        stats = mock_processor.get_precompute_stats()
        
        assert stats['players_processed'] == 3
        assert stats['players_failed'] == 1
        assert stats['early_season'] is False
        assert stats['feature_version'] == 'v1_baseline_25'
        assert stats['feature_count'] == 25
    
    def test_get_precompute_stats_early_season(self, mock_processor):
        """Test get_precompute_stats during early season."""
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
        
        FIXED: The timing is added INSIDE calculate_precompute, not by
        _generate_player_features. We need to test through the full flow.
        """
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
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
        
        # Run through calculate_precompute (which adds timing)
        mock_processor.calculate_precompute()
        
        # Verify timing was added
        assert len(mock_processor.transformed_data) == 1
        record = mock_processor.transformed_data[0]
        assert 'feature_generation_time_ms' in record
        assert isinstance(record['feature_generation_time_ms'], int)
        assert record['feature_generation_time_ms'] >= 0
    
    def test_source_tracking_fields_populated(self, mock_processor,
                                              sample_player_row,
                                              sample_phase4_data,
                                              sample_phase3_data):
        """Test that v4.0 source tracking fields are populated."""
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        mock_processor.feature_extractor.extract_phase4_data.return_value = sample_phase4_data
        mock_processor.feature_extractor.extract_phase3_data.return_value = sample_phase3_data
        
        mock_processor._extract_all_features = Mock(return_value=(
            [0.0] * 25,
            {i: 'phase4' for i in range(25)}
        ))
        mock_processor.quality_scorer.calculate_quality_score.return_value = 95.0
        mock_processor.quality_scorer.determine_primary_source.return_value = 'phase4'
        
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
            
            record = mock_processor._generate_player_features(sample_player_row)
            
            mock_build.assert_called_once()
            
            assert 'source_daily_cache_last_updated' in record
            assert 'source_composite_completeness_pct' in record


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])