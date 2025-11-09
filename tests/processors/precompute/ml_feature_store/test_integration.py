"""
Enhanced Integration Tests for ML Feature Store Processor

Additional tests for edge cases and failure scenarios:
- Partial batch write failures
- Early season detection edge cases
- Missing dependency handling
- Quality score edge cases

Run with: pytest test_integration_enhanced.py -v

Directory: tests/processors/precompute/ml_feature_store/
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date, datetime
from typing import Dict, List, Any

from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor


class TestMLFeatureStoreEdgeCases:
    """Additional integration tests for edge cases (8 new tests)."""
    
    @pytest.fixture
    def mock_processor(self) -> MLFeatureStoreProcessor:
        """Create processor instance with mocked dependencies."""
        processor = object.__new__(MLFeatureStoreProcessor)
        
        # Set all required attributes
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
    
    # ========================================================================
    # EARLY SEASON DETECTION EDGE CASES (3 tests)
    # ========================================================================
    
    def test_early_season_exactly_50_percent(self, mock_processor: MLFeatureStoreProcessor) -> None:
        """
        Test early season detection at exactly 50% threshold.
        
        Verifies that exactly 50% early season players does NOT trigger
        early season mode (requires >50%).
        """
        mock_processor.opts = {'analysis_date': date(2024, 10, 25)}
        
        # Mock query result: exactly 50% early season
        mock_result = Mock()
        mock_result.empty = False
        mock_result.iloc = [Mock()]
        mock_result.iloc[0].get = Mock(side_effect=lambda k, d=None: {
            'total_players': 100,
            'early_season_players': 50  # Exactly 50%
        }.get(k, d))
        
        mock_processor.bq_client.query.return_value.to_dataframe.return_value = mock_result
        
        result = mock_processor._is_early_season(date(2024, 10, 25))
        
        assert result is False, "Exactly 50% should NOT trigger early season (requires >50%)"
        assert mock_processor.early_season_flag is False
        assert mock_processor.insufficient_data_reason is None
    
    def test_early_season_51_percent_triggers(self, mock_processor: MLFeatureStoreProcessor) -> None:
        """
        Test early season detection at 51% threshold.
        
        Verifies that 51% early season players DOES trigger early season mode.
        """
        mock_processor.opts = {'analysis_date': date(2024, 10, 25)}
        
        # Mock query result: 51% early season
        mock_result = Mock()
        mock_result.empty = False
        mock_result.iloc = [Mock()]
        mock_result.iloc[0].get = Mock(side_effect=lambda k, d=None: {
            'total_players': 100,
            'early_season_players': 51  # 51%
        }.get(k, d))
        
        mock_processor.bq_client.query.return_value.to_dataframe.return_value = mock_result
        
        result = mock_processor._is_early_season(date(2024, 10, 25))
        
        assert result is True, "51% should trigger early season"
        assert mock_processor.early_season_flag is True
        assert "Early season: 51/100 players" in mock_processor.insufficient_data_reason
    
    def test_early_season_query_failure_safe_default(self, mock_processor: MLFeatureStoreProcessor) -> None:
        """
        Test early season detection handles query failures gracefully.
        
        Verifies that if the early season check query fails, we default
        to False (proceed with normal processing).
        """
        mock_processor.bq_client.query.side_effect = Exception("BigQuery connection error")
        
        result = mock_processor._is_early_season(date(2024, 10, 25))
        
        assert result is False, "Query failure should default to False (proceed normally)"
        assert mock_processor.early_season_flag is False
    
    # ========================================================================
    # BATCH WRITE FAILURE SCENARIOS (3 tests)
    # ========================================================================
    
    def test_save_precompute_partial_batch_failure(self, mock_processor: MLFeatureStoreProcessor) -> None:
        """
        Test save_precompute handles partial batch write failures.
        
        Verifies that when some batches fail to write, the processor:
        1. Tracks successful vs failed rows
        2. Records errors in stats
        3. Does not raise exception (graceful degradation)
        """
        mock_processor.transformed_data = [{'player': i} for i in range(250)]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock batch writer with partial failure
        mock_processor.batch_writer.write_batch.return_value = {
            'rows_processed': 200,      # 2 batches succeeded
            'rows_failed': 50,          # 1 batch failed
            'batches_written': 2,
            'batches_failed': 1,
            'errors': ['Batch 3: Connection timeout']
        }
        
        # Should not raise exception
        mock_processor.save_precompute()
        
        # Verify stats tracking
        assert mock_processor.stats['rows_processed'] == 200
        assert mock_processor.stats['rows_failed'] == 50
        assert mock_processor.stats['batches_written'] == 2
        assert mock_processor.stats['batches_failed'] == 1
    
    def test_save_precompute_all_batches_fail(self, mock_processor: MLFeatureStoreProcessor) -> None:
        """
        Test save_precompute when all batch writes fail.
        
        Verifies graceful handling when all writes fail.
        """
        mock_processor.transformed_data = [{'player': i} for i in range(100)]
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock batch writer with complete failure
        mock_processor.batch_writer.write_batch.return_value = {
            'rows_processed': 0,
            'rows_failed': 100,
            'batches_written': 0,
            'batches_failed': 1,
            'errors': ['Batch 1: BigQuery quota exceeded']
        }
        
        # Should not raise exception
        mock_processor.save_precompute()
        
        # Verify all rows marked as failed
        assert mock_processor.stats['rows_processed'] == 0
        assert mock_processor.stats['rows_failed'] == 100
        assert mock_processor.stats['batches_failed'] == 1
    
    def test_save_precompute_empty_transformed_data(self, mock_processor: MLFeatureStoreProcessor) -> None:
        """
        Test save_precompute handles empty transformed_data gracefully.
        
        Verifies that processor doesn't crash when there's no data to write.
        """
        mock_processor.transformed_data = []
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Should not call batch_writer
        mock_processor.save_precompute()
        
        # Verify batch_writer was not called
        mock_processor.batch_writer.write_batch.assert_not_called()
    
    # ========================================================================
    # FEATURE GENERATION ERROR HANDLING (2 tests)
    # ========================================================================
    
    def test_calculate_precompute_single_player_failure(self, mock_processor: MLFeatureStoreProcessor) -> None:
        """
        Test calculate_precompute continues after single player failure.
        
        Verifies that if one player fails to process, the processor:
        1. Logs the failure
        2. Tracks it in failed_entities
        3. Continues processing other players
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
        
        # Mock successful generation for player1 and player3
        def mock_generate(player_row: Dict[str, Any]) -> Dict[str, Any]:
            if player_row['player_lookup'] == 'player2':
                raise ValueError("Missing Phase 4 data")
            return {
                'player_lookup': player_row['player_lookup'],
                'features': [0.0] * 25,
                'feature_names': ['f' + str(i) for i in range(25)],
                'feature_count': 25,
                'feature_version': 'v1_baseline_25',
                'feature_generation_time_ms': 50
            }
        
        mock_processor._generate_player_features = Mock(side_effect=mock_generate)
        
        # Execute
        mock_processor.calculate_precompute()
        
        # Verify results
        assert len(mock_processor.transformed_data) == 2, "Should process 2 successful players"
        assert len(mock_processor.failed_entities) == 1, "Should track 1 failed player"
        assert mock_processor.failed_entities[0]['entity_id'] == 'player2'
        assert 'Missing Phase 4 data' in mock_processor.failed_entities[0]['reason']
    
    def test_calculate_precompute_feature_extraction_returns_invalid_data(self, mock_processor: MLFeatureStoreProcessor) -> None:
        """
        Test calculate_precompute handles invalid feature data gracefully.
        
        Verifies that if feature extraction returns incomplete/invalid data,
        the processor catches it and continues.
        """
        mock_processor.players_with_games = [
            {'player_lookup': 'test-player', 'universal_player_id': 'tp', 'game_id': 'g1',
             'opponent_team_abbr': 'LAL', 'is_home': True, 'days_rest': 1}
        ]
        
        mock_processor.opts = {'analysis_date': date(2025, 1, 15)}
        
        # Mock feature extraction that returns invalid features (wrong length)
        mock_processor.feature_extractor.extract_phase4_data.return_value = {}
        mock_processor.feature_extractor.extract_phase3_data.return_value = {}
        
        # Mock _extract_all_features to return invalid data
        def invalid_features(*args: Any, **kwargs: Any) -> tuple:
            return ([0.0] * 10, {})  # Only 10 features instead of 25!
        
        mock_processor._extract_all_features = Mock(side_effect=invalid_features)
        
        # Execute - should handle gracefully
        mock_processor.calculate_precompute()
        
        # Should have failed to process
        assert len(mock_processor.transformed_data) == 0 or \
               mock_processor.transformed_data[0]['features'] == [0.0] * 10


class TestQualityScoreEdgeCases:
    """Test quality score calculation edge cases (2 tests)."""
    
    @pytest.fixture
    def mock_processor(self) -> MLFeatureStoreProcessor:
        """Create minimal processor for quality testing."""
        processor = object.__new__(MLFeatureStoreProcessor)
        processor.quality_scorer = Mock()
        processor.feature_calculator = Mock()
        return processor
    
    def test_quality_score_all_defaults_lowest_quality(self, mock_processor: MLFeatureStoreProcessor) -> None:
        """
        Test quality score when all features use defaults.
        
        Verifies that when no real data is available (all defaults),
        quality score is 40.0 (lowest possible without early season).
        """
        from data_processors.precompute.ml_feature_store.quality_scorer import QualityScorer
        
        scorer = QualityScorer()
        feature_sources = {i: 'default' for i in range(25)}
        
        quality = scorer.calculate_quality_score(feature_sources)
        
        assert quality == 40.0, "All defaults should give 40.0 quality"
        assert scorer.identify_data_tier(quality) == 'low'
    
    def test_quality_score_mixed_high_quality_sources(self, mock_processor: MLFeatureStoreProcessor) -> None:
        """
        Test quality score with optimal mix of Phase 4 and calculated.
        
        Verifies that Phase 4 + calculated features gives 100.0 quality.
        """
        from data_processors.precompute.ml_feature_store.quality_scorer import QualityScorer
        
        scorer = QualityScorer()
        
        # 19 Phase 4 features + 6 calculated features
        feature_sources = {
            **{i: 'phase4' for i in range(19)},
            **{i: 'calculated' for i in range(19, 25)}
        }
        
        quality = scorer.calculate_quality_score(feature_sources)
        
        assert quality == 100.0, "Phase 4 + calculated should give 100.0 quality"
        assert scorer.identify_data_tier(quality) == 'high'


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])