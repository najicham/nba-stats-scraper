"""
Integration Tests for ML Feature Store Processor

Tests end-to-end processor flow with mock data.
These tests require full infrastructure mocking (BigQuery, etc).

Run with: pytest test_integration.py -v

Directory: tests/processors/precompute/ml_feature_store/
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date, datetime
import sys
import os

from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor


class TestMLFeatureStoreProcessorIntegration:
    """Integration tests for complete processor flow (6 tests)."""
    
    @pytest.fixture
    def mock_processor(self):
        """Create processor instance with mocked dependencies."""
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
        
        # v4.0 Dependency tracking attributes
        processor.source_metadata = {}
        
        # Initialize source tracking attributes for each dependency
        # These would normally be set by track_source_usage()
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
        
        yield processor
    
    # ========================================================================
    # FEATURE GENERATION (2 tests)
    # ========================================================================
    
    def test_generate_player_features_complete_phase4(self, mock_processor):
        """
        Test feature generation with complete Phase 4 data.
        
        Verifies that processor correctly uses Phase 4 data when available
        and generates all 25 features with proper source tracking.
        """
        # Mock player row
        player_row = {
            'player_lookup': 'lebron-james',
            'universal_player_id': 'lebronjames_001',
            'game_id': '20250115_LAL_GSW',
            'game_date': date(2025, 1, 15),
            'opponent_team_abbr': 'GSW',
            'is_home': True,
            'days_rest': 1
        }
        
        # Mock Phase 4 data (all features available)
        phase4_data = {
            'points_avg_last_5': 25.2,
            'points_avg_last_10': 24.8,
            'points_avg_season': 24.5,
            'points_std_last_10': 4.2,
            'games_in_last_7_days': 3,
            'fatigue_score': 75,
            'shot_zone_mismatch_score': 3.5,
            'pace_score': 1.5,
            'usage_spike_score': 0.8,
            'opponent_def_rating': 110.5,
            'opponent_pace': 101.2,
            'paint_rate_last_10': 35.0,
            'mid_range_rate_last_10': 20.0,
            'three_pt_rate_last_10': 45.0,
            'team_pace_last_10': 99.8,
            'team_off_rating_last_10': 115.2,
            'minutes_avg_last_10': 35.5
        }
        
        # Mock Phase 3 data (for calculated features)
        phase3_data = {
            'days_rest': 1,
            'opponent_days_rest': 0,
            'player_status': 'available',
            'home_game': True,
            'back_to_back': False,
            'season_phase': 'regular',
            'last_10_games': [
                {'game_date': '2025-01-13', 'points': 28, 'minutes_played': 36, 'ft_makes': 8},
                {'game_date': '2025-01-11', 'points': 24, 'minutes_played': 35, 'ft_makes': 6},
                {'game_date': '2025-01-09', 'points': 26, 'minutes_played': 37, 'ft_makes': 7},
                {'game_date': '2025-01-07', 'points': 22, 'minutes_played': 34, 'ft_makes': 5},
                {'game_date': '2025-01-05', 'points': 25, 'minutes_played': 36, 'ft_makes': 6}
            ],
            'minutes_avg_season': 34.0,
            'team_season_games': [
                {'win_flag': True}, {'win_flag': True}, {'win_flag': False},
                {'win_flag': True}, {'win_flag': True}, {'win_flag': True},
                {'win_flag': False}, {'win_flag': True}
            ]
        }
        
        # Mock extractors
        mock_processor.feature_extractor.extract_phase4_data.return_value = phase4_data
        mock_processor.feature_extractor.extract_phase3_data.return_value = phase3_data
        
        # Mock calculator
        mock_processor.feature_calculator.calculate_rest_advantage.return_value = 1.0
        mock_processor.feature_calculator.calculate_injury_risk.return_value = 0.0
        mock_processor.feature_calculator.calculate_recent_trend.return_value = 0.0
        mock_processor.feature_calculator.calculate_minutes_change.return_value = 1.0
        mock_processor.feature_calculator.calculate_pct_free_throw.return_value = 0.25
        mock_processor.feature_calculator.calculate_team_win_pct.return_value = 0.75
        
        # Mock quality scorer
        mock_processor.quality_scorer.calculate_quality_score.return_value = 95.0
        mock_processor.quality_scorer.determine_primary_source.return_value = 'phase4'
        
        # Set opts
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Generate features
        record = mock_processor._generate_player_features(player_row)
        
        # Assertions
        assert record['player_lookup'] == 'lebron-james'
        assert record['feature_count'] == 25
        assert record['feature_version'] == 'v1_baseline_25'
        assert len(record['features']) == 25
        assert len(record['feature_names']) == 25
        
        # Check feature quality
        assert record['feature_quality_score'] == 95.0
        assert record['data_source'] == 'phase4'
        
        # Check specific features
        features = record['features']
        assert features[0] == 25.2  # points_avg_last_5
        assert features[5] == 75.0  # fatigue_score
        assert features[9] == 1.0   # rest_advantage
        assert features[10] == 0.0  # injury_risk
    
    def test_generate_player_features_missing_phase4(self, mock_processor):
        """
        Test feature generation with missing Phase 4 data.
        
        Verifies fallback to Phase 3 works correctly and quality score
        reflects the lower data quality.
        """
        player_row = {
            'player_lookup': 'test-player',
            'universal_player_id': 'testplayer_001',
            'game_id': '20250115_TEST_TEST',
            'opponent_team_abbr': 'LAL',
            'is_home': False,
            'days_rest': 1
        }
        
        # Phase 4 mostly missing
        phase4_data = {}
        
        # Phase 3 has fallback data
        phase3_data = {
            'points_avg_last_10': 15.0,
            'points_avg_season': 14.5,
            'days_rest': 1,
            'opponent_days_rest': 1,
            'player_status': 'available',
            'home_game': False,
            'back_to_back': False,
            'season_phase': 'regular',
            'last_10_games': [
                {'game_date': '2025-01-13', 'points': 16, 'minutes_played': 28, 'ft_makes': 4},
                {'game_date': '2025-01-11', 'points': 14, 'minutes_played': 27, 'ft_makes': 3},
                {'game_date': '2025-01-09', 'points': 15, 'minutes_played': 29, 'ft_makes': 4},
                {'game_date': '2025-01-07', 'points': 14, 'minutes_played': 26, 'ft_makes': 3},
                {'game_date': '2025-01-05', 'points': 16, 'minutes_played': 28, 'ft_makes': 5}
            ],
            'minutes_avg_season': 27.0,
            'team_season_games': [
                {'win_flag': True}, {'win_flag': False}, {'win_flag': True},
                {'win_flag': False}, {'win_flag': True}, {'win_flag': False}
            ]
        }
        
        # Mock extractors
        mock_processor.feature_extractor.extract_phase4_data.return_value = phase4_data
        mock_processor.feature_extractor.extract_phase3_data.return_value = phase3_data
        
        # Mock calculator
        mock_processor.feature_calculator.calculate_rest_advantage.return_value = 0.0
        mock_processor.feature_calculator.calculate_injury_risk.return_value = 0.0
        mock_processor.feature_calculator.calculate_recent_trend.return_value = 0.0
        mock_processor.feature_calculator.calculate_minutes_change.return_value = 0.0
        mock_processor.feature_calculator.calculate_pct_free_throw.return_value = 0.20
        mock_processor.feature_calculator.calculate_team_win_pct.return_value = 0.50
        
        # Mock quality scorer
        mock_processor.quality_scorer.calculate_quality_score.return_value = 65.0
        mock_processor.quality_scorer.determine_primary_source.return_value = 'phase3'
        
        # Set opts
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Generate features
        record = mock_processor._generate_player_features(player_row)
        
        # Assertions
        assert record['player_lookup'] == 'test-player'
        assert len(record['features']) == 25
        assert record['feature_quality_score'] == 65.0, "Lower quality when Phase 4 missing"
        assert record['data_source'] == 'phase3', "Should use Phase 3 as primary source"
    
    # ========================================================================
    # FEATURE EXTRACTION (1 test)
    # ========================================================================
    
    def test_extract_all_features_structure(self, mock_processor):
        """
        Test that extract_all_features returns correct structure.
        
        Verifies the feature extraction returns 25 features and proper
        source tracking for all features.
        """
        phase4_data = {
            'points_avg_last_5': 20.0,
            'points_avg_last_10': 19.5,
            'points_avg_season': 19.0,
            'points_std_last_10': 3.5,
            'games_in_last_7_days': 3,
            'fatigue_score': 60,
            'shot_zone_mismatch_score': 2.0,
            'pace_score': 1.0,
            'usage_spike_score': 0.5
        }
        
        phase3_data = {
            'home_game': True,
            'back_to_back': False,
            'season_phase': 'regular',
            'days_rest': 1,
            'opponent_days_rest': 1,
            'player_status': 'available',
            'last_10_games': []
        }
        
        # Mock calculator
        mock_processor.feature_calculator.calculate_rest_advantage.return_value = 0.0
        mock_processor.feature_calculator.calculate_injury_risk.return_value = 0.0
        mock_processor.feature_calculator.calculate_recent_trend.return_value = 0.0
        mock_processor.feature_calculator.calculate_minutes_change.return_value = 0.0
        mock_processor.feature_calculator.calculate_pct_free_throw.return_value = 0.15
        mock_processor.feature_calculator.calculate_team_win_pct.return_value = 0.50
        
        # Extract features
        features, feature_sources = mock_processor._extract_all_features(phase4_data, phase3_data)
        
        # Assertions
        assert len(features) == 25, "Should extract exactly 25 features"
        assert len(feature_sources) == 25, "Should track source for all 25 features"
        assert all(isinstance(f, (int, float)) for f in features), "All features should be numeric"
        assert all(source in ['phase4', 'phase3', 'default', 'calculated'] 
                  for source in feature_sources.values()), "All sources should be valid"
    
    # ========================================================================
    # CALCULATE PRECOMPUTE (2 tests)
    # ========================================================================
    
    def test_calculate_precompute_success(self, mock_processor):
        """
        Test calculate_precompute processes all players successfully.
        
        Verifies the main calculation loop processes multiple players
        and tracks success/failure correctly.
        """
        # Mock players list
        mock_processor.players_with_games = [
            {
                'player_lookup': 'player1',
                'universal_player_id': 'player1_001',
                'game_id': 'game1',
                'opponent_team_abbr': 'LAL',
                'is_home': True,
                'days_rest': 1
            },
            {
                'player_lookup': 'player2',
                'universal_player_id': 'player2_001',
                'game_id': 'game2',
                'opponent_team_abbr': 'GSW',
                'is_home': False,
                'days_rest': 2
            }
        ]
        
        # Mock feature generation
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock extractors and calculators
        mock_processor.feature_extractor.extract_phase4_data.return_value = {}
        mock_processor.feature_extractor.extract_phase3_data.return_value = {
            'home_game': True,
            'back_to_back': False,
            'season_phase': 'regular',
            'days_rest': 1,
            'opponent_days_rest': 1,
            'player_status': 'available',
            'last_10_games': []
        }
        
        mock_processor.feature_calculator.calculate_rest_advantage.return_value = 0.0
        mock_processor.feature_calculator.calculate_injury_risk.return_value = 0.0
        mock_processor.feature_calculator.calculate_recent_trend.return_value = 0.0
        mock_processor.feature_calculator.calculate_minutes_change.return_value = 0.0
        mock_processor.feature_calculator.calculate_pct_free_throw.return_value = 0.15
        mock_processor.feature_calculator.calculate_team_win_pct.return_value = 0.50
        
        mock_processor.quality_scorer.calculate_quality_score.return_value = 75.0
        mock_processor.quality_scorer.determine_primary_source.return_value = 'mixed'
        
        # Run calculation
        mock_processor.calculate_precompute()
        
        # Assertions
        assert len(mock_processor.transformed_data) == 2, "Should process both players"
        assert len(mock_processor.failed_entities) == 0, "Should have no failures"
        
        # Check first record
        record1 = mock_processor.transformed_data[0]
        assert record1['player_lookup'] == 'player1'
        assert len(record1['features']) == 25
        assert record1['feature_generation_time_ms'] is not None
    
    def test_calculate_precompute_early_season(self, mock_processor):
        """
        Test calculate_precompute handles early season correctly.
        
        Verifies that early season flag prevents normal processing
        and uses pre-created placeholder records.
        """
        # Set early season flag
        mock_processor.early_season_flag = True
        mock_processor.transformed_data = [{'placeholder': True}]
        
        # Run calculation
        mock_processor.calculate_precompute()
        
        # Should not process anything (placeholders already created)
        assert len(mock_processor.transformed_data) == 1
        assert mock_processor.transformed_data[0]['placeholder'] is True
    
    # ========================================================================
    # GET PRECOMPUTE STATS (1 test)
    # ========================================================================
    
    def test_get_precompute_stats(self, mock_processor):
        """
        Test get_precompute_stats returns correct statistics.
        
        Verifies that processor stats are correctly calculated and returned
        for monitoring and logging purposes.
        """
        mock_processor.transformed_data = [{'player': 1}, {'player': 2}, {'player': 3}]
        mock_processor.failed_entities = [{'player': 4}]
        mock_processor.early_season_flag = False
        
        stats = mock_processor.get_precompute_stats()
        
        assert stats['players_processed'] == 3
        assert stats['players_failed'] == 1
        assert stats['early_season'] is False
        assert stats['feature_version'] == 'v1_baseline_25'
        assert stats['feature_count'] == 25


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])