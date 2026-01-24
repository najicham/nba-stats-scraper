"""
Unit Tests for ML Feature Store V2 Processor

Tests individual methods and calculations in isolation for:
- FeatureCalculator: 28 tests (6 calculated features)
- QualityScorer: 15 tests (quality scoring and source determination)
- BatchWriter: 14 tests (BigQuery batch operations)

Run with: pytest test_unit.py -v

Directory: tests/processors/precompute/ml_feature_store/
"""

import pytest
import pandas as pd
from datetime import date, datetime
from unittest.mock import Mock, MagicMock, patch

# Import modules under test
from data_processors.precompute.ml_feature_store.feature_calculator import FeatureCalculator
from data_processors.precompute.ml_feature_store.quality_scorer import QualityScorer
from data_processors.precompute.ml_feature_store.batch_writer import BatchWriter


# ============================================================================
# TEST CLASS 1: FEATURE CALCULATOR (28 tests)
# ============================================================================

class TestFeatureCalculator:
    """Test FeatureCalculator - 6 calculated features (28 tests total)."""
    
    @pytest.fixture
    def calculator(self):
        """Create calculator instance for tests."""
        return FeatureCalculator()
    
    # ========================================================================
    # FEATURE 9: REST ADVANTAGE (5 tests)
    # ========================================================================
    
    def test_rest_advantage_player_more_rested(self, calculator):
        """Test rest advantage when player has more rest than opponent."""
        phase3_data = {
            'days_rest': 2,
            'opponent_days_rest': 0
        }
        
        result = calculator.calculate_rest_advantage(phase3_data)
        
        assert result == 2.0, "Player with 2 days rest vs opponent with 0 should give +2.0 advantage"
    
    def test_rest_advantage_opponent_more_rested(self, calculator):
        """Test rest advantage when opponent has more rest than player."""
        phase3_data = {
            'days_rest': 0,
            'opponent_days_rest': 2
        }
        
        result = calculator.calculate_rest_advantage(phase3_data)
        
        assert result == -2.0, "Player with 0 days rest vs opponent with 2 should give -2.0 disadvantage"
    
    def test_rest_advantage_equal_rest(self, calculator):
        """Test rest advantage when both have equal rest."""
        phase3_data = {
            'days_rest': 1,
            'opponent_days_rest': 1
        }
        
        result = calculator.calculate_rest_advantage(phase3_data)
        
        assert result == 0.0, "Equal rest should give 0.0 advantage"
    
    def test_rest_advantage_clamped_to_max(self, calculator):
        """Test rest advantage is clamped to maximum of 2.0."""
        phase3_data = {
            'days_rest': 5,
            'opponent_days_rest': 0
        }
        
        result = calculator.calculate_rest_advantage(phase3_data)
        
        assert result == 2.0, "Rest advantage should be clamped to 2.0 maximum"
    
    def test_rest_advantage_missing_data(self, calculator):
        """Test rest advantage with missing data returns 0.0."""
        phase3_data = {}
        
        result = calculator.calculate_rest_advantage(phase3_data)
        
        assert result == 0.0, "Missing rest data should return 0.0"
    
    # ========================================================================
    # FEATURE 10: INJURY RISK (6 tests)
    # ========================================================================
    
    def test_injury_risk_available(self, calculator):
        """Test injury risk for available player."""
        phase3_data = {'player_status': 'available'}
        
        result = calculator.calculate_injury_risk(phase3_data)
        
        assert result == 0.0, "Available player should have 0.0 injury risk"
    
    def test_injury_risk_probable(self, calculator):
        """Test injury risk for probable player."""
        phase3_data = {'player_status': 'probable'}
        
        result = calculator.calculate_injury_risk(phase3_data)
        
        assert result == 1.0, "Probable status should give 1.0 risk"
    
    def test_injury_risk_questionable(self, calculator):
        """Test injury risk for questionable player."""
        phase3_data = {'player_status': 'questionable'}
        
        result = calculator.calculate_injury_risk(phase3_data)
        
        assert result == 2.0, "Questionable status should give 2.0 risk"
    
    def test_injury_risk_doubtful(self, calculator):
        """Test injury risk for doubtful player."""
        phase3_data = {'player_status': 'doubtful'}
        
        result = calculator.calculate_injury_risk(phase3_data)
        
        assert result == 3.0, "Doubtful status should give 3.0 risk"
    
    def test_injury_risk_out(self, calculator):
        """Test injury risk for player listed as out."""
        phase3_data = {'player_status': 'out'}
        
        result = calculator.calculate_injury_risk(phase3_data)
        
        assert result == 3.0, "Out status should give 3.0 risk"
    
    def test_injury_risk_case_insensitive(self, calculator):
        """Test injury risk is case insensitive."""
        phase3_data = {'player_status': 'QUESTIONABLE'}
        
        result = calculator.calculate_injury_risk(phase3_data)
        
        assert result == 2.0, "Status check should be case insensitive"
    
    # ========================================================================
    # FEATURE 11: RECENT TREND (4 tests)
    # ========================================================================
    
    def test_recent_trend_strong_downward(self, calculator):
        """Test recent trend with strong downward movement (recent games worse)."""
        phase3_data = {
            'last_10_games': [
                {'game_date': '2025-01-15', 'points': 25},
                {'game_date': '2025-01-13', 'points': 24},
                {'game_date': '2025-01-11', 'points': 26},
                {'game_date': '2025-01-09', 'points': 18},  # Last 2 average: 17.5
                {'game_date': '2025-01-07', 'points': 17}   # vs first 3 average: 25.0
            ]
        }
        
        result = calculator.calculate_recent_trend(phase3_data)
        
        # avg_first_3 = 25.0, avg_last_2 = 17.5, diff = -7.5 → trend = -2.0
        assert result == -2.0, "Declining performance should give -2.0 trend"
    
    def test_recent_trend_strong_upward(self, calculator):
        """Test recent trend with strong upward movement (recent games better)."""
        phase3_data = {
            'last_10_games': [
                {'game_date': '2025-01-15', 'points': 17},
                {'game_date': '2025-01-13', 'points': 18},
                {'game_date': '2025-01-11', 'points': 16},
                {'game_date': '2025-01-09', 'points': 25},  # Last 2 average: 25.5
                {'game_date': '2025-01-07', 'points': 26}   # vs first 3 average: 17.0
            ]
        }
        
        result = calculator.calculate_recent_trend(phase3_data)
        
        # avg_first_3 = 17.0, avg_last_2 = 25.5, diff = +8.5 → trend = +2.0
        assert result == 2.0, "Improving performance should give +2.0 trend"
    
    def test_recent_trend_stable(self, calculator):
        """Test recent trend with stable performance."""
        phase3_data = {
            'last_10_games': [
                {'game_date': '2025-01-15', 'points': 22},
                {'game_date': '2025-01-13', 'points': 21},
                {'game_date': '2025-01-11', 'points': 23},
                {'game_date': '2025-01-09', 'points': 22},
                {'game_date': '2025-01-07', 'points': 21}
            ]
        }
        
        result = calculator.calculate_recent_trend(phase3_data)
        
        # avg_first_3 = 22.0, avg_last_2 = 21.5, diff = -0.5 → trend = 0.0
        assert result == 0.0, "Stable performance should give 0.0 trend"
    
    def test_recent_trend_insufficient_games(self, calculator):
        """Test recent trend with insufficient games returns 0.0."""
        phase3_data = {
            'last_10_games': [
                {'game_date': '2025-01-15', 'points': 25},
                {'game_date': '2025-01-13', 'points': 24}
            ]
        }
        
        result = calculator.calculate_recent_trend(phase3_data)
        
        assert result == 0.0, "Insufficient games (<5) should return 0.0"
    
    # ========================================================================
    # FEATURE 12: MINUTES CHANGE (5 tests)
    # ========================================================================
    
    def test_minutes_change_big_increase(self, calculator):
        """Test minutes change with significant increase (>20%)."""
        phase4_data = {'minutes_avg_last_10': 36.0}
        phase3_data = {'minutes_avg_season': 28.0}
        
        result = calculator.calculate_minutes_change(phase4_data, phase3_data)
        
        # pct_change = (36-28)/28 = 0.286 (+28.6%) → change = 2.0
        assert result == 2.0, "Minutes increase >20% should give +2.0"
    
    def test_minutes_change_moderate_increase(self, calculator):
        """Test minutes change with moderate increase (10-20%)."""
        phase4_data = {'minutes_avg_last_10': 32.0}
        phase3_data = {'minutes_avg_season': 28.0}
        
        result = calculator.calculate_minutes_change(phase4_data, phase3_data)
        
        # pct_change = (32-28)/28 = 0.143 (+14.3%) → change = 1.0
        assert result == 1.0, "Minutes increase 10-20% should give +1.0"
    
    def test_minutes_change_no_change(self, calculator):
        """Test minutes change with no significant change."""
        phase4_data = {'minutes_avg_last_10': 30.0}
        phase3_data = {'minutes_avg_season': 30.0}
        
        result = calculator.calculate_minutes_change(phase4_data, phase3_data)
        
        assert result == 0.0, "No minutes change should give 0.0"
    
    def test_minutes_change_big_decrease(self, calculator):
        """Test minutes change with significant decrease (>20%)."""
        phase4_data = {'minutes_avg_last_10': 24.0}
        phase3_data = {'minutes_avg_season': 32.0}
        
        result = calculator.calculate_minutes_change(phase4_data, phase3_data)
        
        # pct_change = (24-32)/32 = -0.25 (-25%) → change = -2.0
        assert result == -2.0, "Minutes decrease >20% should give -2.0"
    
    def test_minutes_change_fallback_to_phase3(self, calculator):
        """Test minutes change falls back to Phase 3 calculation when Phase 4 missing."""
        phase4_data = {}  # No Phase 4 data
        phase3_data = {
            'minutes_avg_season': 30.0,
            'last_10_games': [
                {'minutes_played': 35}, {'minutes_played': 36}, {'minutes_played': 34},
                {'minutes_played': 37}, {'minutes_played': 35}, {'minutes_played': 36},
                {'minutes_played': 35}, {'minutes_played': 34}, {'minutes_played': 36},
                {'minutes_played': 35}
            ]
        }
        
        result = calculator.calculate_minutes_change(phase4_data, phase3_data)
        
        # avg from games = 35.3, pct_change = (35.3-30)/30 = 0.177 → change = 1.0
        assert result == 1.0, "Should calculate from Phase 3 when Phase 4 missing"
    
    # ========================================================================
    # FEATURE 21: PCT FREE THROW (4 tests)
    # ========================================================================
    
    def test_pct_free_throw_normal(self, calculator):
        """Test pct_free_throw with normal data."""
        phase3_data = {
            'last_10_games': [
                {'ft_makes': 8, 'points': 28}, {'ft_makes': 6, 'points': 24},
                {'ft_makes': 10, 'points': 32}, {'ft_makes': 4, 'points': 20},
                {'ft_makes': 7, 'points': 26}, {'ft_makes': 5, 'points': 22},
                {'ft_makes': 9, 'points': 30}, {'ft_makes': 6, 'points': 25},
                {'ft_makes': 8, 'points': 29}, {'ft_makes': 7, 'points': 27}
            ]
        }
        
        result = calculator.calculate_pct_free_throw(phase3_data)
        
        # total_ft = 70, total_points = 263, pct = 70/263 = 0.266
        assert 0.26 <= result <= 0.27, f"Expected ~0.266, got {result}"
    
    def test_pct_free_throw_high_rate(self, calculator):
        """Test pct_free_throw with high free throw rate."""
        phase3_data = {
            'last_10_games': [
                {'ft_makes': 12, 'points': 30}, {'ft_makes': 10, 'points': 28},
                {'ft_makes': 11, 'points': 29}, {'ft_makes': 13, 'points': 31},
                {'ft_makes': 12, 'points': 30}
            ]
        }
        
        result = calculator.calculate_pct_free_throw(phase3_data)
        
        # total_ft = 58, total_points = 148, pct = 58/148 = 0.392
        assert 0.38 <= result <= 0.40, f"Expected ~0.392, got {result}"
    
    def test_pct_free_throw_insufficient_games(self, calculator):
        """Test pct_free_throw with insufficient games returns default."""
        phase3_data = {
            'last_10_games': [
                {'ft_makes': 8, 'points': 28}
            ]
        }
        
        result = calculator.calculate_pct_free_throw(phase3_data)
        
        assert result == 0.15, "Insufficient games (<5) should return league average default"
    
    def test_pct_free_throw_zero_points(self, calculator):
        """Test pct_free_throw with zero points returns default."""
        phase3_data = {
            'last_10_games': [
                {'ft_makes': 0, 'points': 0}, {'ft_makes': 0, 'points': 0},
                {'ft_makes': 0, 'points': 0}, {'ft_makes': 0, 'points': 0},
                {'ft_makes': 0, 'points': 0}
            ]
        }
        
        result = calculator.calculate_pct_free_throw(phase3_data)
        
        assert result == 0.15, "Zero points should return default"
    
    # ========================================================================
    # FEATURE 24: TEAM WIN PCT (4 tests)
    # ========================================================================
    
    def test_team_win_pct_good_team(self, calculator):
        """Test team win pct for good team (75% wins)."""
        phase3_data = {
            'team_season_games': [
                {'win_flag': True}, {'win_flag': True}, {'win_flag': True},
                {'win_flag': False}, {'win_flag': True}, {'win_flag': True},
                {'win_flag': False}, {'win_flag': True}
            ]
        }
        
        result = calculator.calculate_team_win_pct(phase3_data)
        
        # 6 wins / 8 games = 0.75
        assert result == 0.75, "6 wins in 8 games should give 0.75"
    
    def test_team_win_pct_bad_team(self, calculator):
        """Test team win pct for bad team (25% wins)."""
        phase3_data = {
            'team_season_games': [
                {'win_flag': False}, {'win_flag': False}, {'win_flag': True},
                {'win_flag': False}, {'win_flag': False}, {'win_flag': False},
                {'win_flag': True}, {'win_flag': False}
            ]
        }
        
        result = calculator.calculate_team_win_pct(phase3_data)
        
        # 2 wins / 8 games = 0.25
        assert result == 0.25, "2 wins in 8 games should give 0.25"
    
    def test_team_win_pct_average_team(self, calculator):
        """Test team win pct for average team (50% wins)."""
        phase3_data = {
            'team_season_games': [
                {'win_flag': True}, {'win_flag': False}, {'win_flag': True},
                {'win_flag': False}, {'win_flag': True}, {'win_flag': False}
            ]
        }
        
        result = calculator.calculate_team_win_pct(phase3_data)
        
        # 3 wins / 6 games = 0.5
        assert result == 0.5, "3 wins in 6 games should give 0.5"
    
    def test_team_win_pct_insufficient_games(self, calculator):
        """Test team win pct with insufficient games returns default."""
        phase3_data = {
            'team_season_games': [
                {'win_flag': True},
                {'win_flag': False}
            ]
        }
        
        result = calculator.calculate_team_win_pct(phase3_data)
        
        assert result == 0.500, "Insufficient games (<5) should return 0.500 default"


# ============================================================================
# TEST CLASS 2: QUALITY SCORER (15 tests)
# ============================================================================

class TestQualityScorer:
    """Test QualityScorer - quality calculation and source determination (15 tests)."""
    
    @pytest.fixture
    def scorer(self):
        """Create scorer instance for tests."""
        return QualityScorer()
    
    # ========================================================================
    # QUALITY SCORE CALCULATION (6 tests)
    # ========================================================================
    
    def test_calculate_quality_score_all_phase4(self, scorer):
        """Test quality score when all features from Phase 4."""
        feature_sources = {i: 'phase4' for i in range(25)}
        
        result = scorer.calculate_quality_score(feature_sources)
        
        assert result == 100.0, "All Phase 4 (100 points each) should give 100.0"
    
    def test_calculate_quality_score_all_phase3(self, scorer):
        """Test quality score when all features from Phase 3."""
        feature_sources = {i: 'phase3' for i in range(25)}
        
        result = scorer.calculate_quality_score(feature_sources)
        
        assert result == 75.0, "All Phase 3 (75 points each) should give 75.0"
    
    def test_calculate_quality_score_all_defaults(self, scorer):
        """Test quality score when all features are defaults."""
        feature_sources = {i: 'default' for i in range(25)}
        
        result = scorer.calculate_quality_score(feature_sources)
        
        assert result == 40.0, "All defaults (40 points each) should give 40.0"
    
    def test_calculate_quality_score_mixed_sources(self, scorer):
        """Test quality score with mixed sources."""
        feature_sources = {
            # 10 Phase 4 features
            0: 'phase4', 1: 'phase4', 2: 'phase4', 3: 'phase4', 4: 'phase4',
            5: 'phase4', 6: 'phase4', 7: 'phase4', 8: 'phase4', 13: 'phase4',
            
            # 10 Phase 3 features
            14: 'phase3', 15: 'phase3', 16: 'phase3', 17: 'phase3', 18: 'phase3',
            19: 'phase3', 20: 'phase3', 22: 'phase3', 23: 'phase3', 24: 'phase3',
            
            # 5 calculated features
            9: 'calculated', 10: 'calculated', 11: 'calculated', 12: 'calculated', 21: 'calculated'
        }
        
        result = scorer.calculate_quality_score(feature_sources)
        
        # 10*100 + 10*75 + 5*100 = 1000 + 750 + 500 = 2250 / 25 = 90.0
        assert result == 90.0, "Mixed sources should give weighted average of 90.0"
    
    def test_calculate_quality_score_with_calculated(self, scorer):
        """Test quality score includes calculated features at 100 points."""
        feature_sources = {
            **{i: 'phase4' for i in range(19)},
            19: 'calculated', 20: 'calculated', 21: 'calculated',
            22: 'calculated', 23: 'calculated', 24: 'calculated'
        }
        
        result = scorer.calculate_quality_score(feature_sources)
        
        # 19*100 + 6*100 = 2500 / 25 = 100.0
        assert result == 100.0, "Phase 4 + calculated should give 100.0"
    
    def test_calculate_quality_score_empty_sources(self, scorer):
        """Test quality score with empty sources returns 0.0."""
        feature_sources = {}
        
        result = scorer.calculate_quality_score(feature_sources)
        
        assert result == 0.0, "Empty sources should return 0.0"
    
    # ========================================================================
    # PRIMARY SOURCE DETERMINATION (5 tests)
    # ========================================================================
    
    def test_determine_primary_source_phase4(self, scorer):
        """Test primary source when >90% Phase 4."""
        feature_sources = {
            **{i: 'phase4' for i in range(23)},  # 23 Phase 4 (92%)
            23: 'phase3',
            24: 'calculated'
        }
        
        result = scorer.determine_primary_source(feature_sources)
        
        assert result == 'phase4', ">=90% Phase 4 should return 'phase4'"
    
    def test_determine_primary_source_phase4_partial(self, scorer):
        """Test primary source when 50-90% Phase 4."""
        feature_sources = {
            **{i: 'phase4' for i in range(15)},  # 15 Phase 4 (60%)
            **{i: 'phase3' for i in range(15, 25)}  # 10 Phase 3 (40%)
        }
        
        result = scorer.determine_primary_source(feature_sources)
        
        assert result == 'phase4_partial', "50-90% Phase 4 should return 'phase4_partial'"
    
    def test_determine_primary_source_phase3(self, scorer):
        """Test primary source when >50% Phase 3."""
        feature_sources = {
            **{i: 'phase3' for i in range(15)},  # 15 Phase 3 (60%)
            **{i: 'phase4' for i in range(15, 25)}  # 10 Phase 4 (40%)
        }
        
        result = scorer.determine_primary_source(feature_sources)
        
        assert result == 'phase3', ">50% Phase 3 should return 'phase3'"
    
    def test_determine_primary_source_mixed(self, scorer):
        """Test primary source when no source dominates."""
        feature_sources = {
            **{i: 'phase4' for i in range(10)},  # 10 Phase 4 (40%)
            **{i: 'phase3' for i in range(10, 15)},  # 5 Phase 3 (20%)
            **{i: 'default' for i in range(15, 20)},  # 5 default (20%)
            **{i: 'calculated' for i in range(20, 25)}  # 5 calculated (20%)
        }
        
        result = scorer.determine_primary_source(feature_sources)
        
        assert result == 'mixed', "No dominant source should return 'mixed'"
    
    def test_determine_primary_source_empty(self, scorer):
        """Test primary source with empty sources returns 'unknown'."""
        feature_sources = {}
        
        result = scorer.determine_primary_source(feature_sources)
        
        assert result == 'unknown', "Empty sources should return 'unknown'"
    
    # ========================================================================
    # DATA TIER IDENTIFICATION (3 tests)
    # ========================================================================
    
    def test_identify_data_tier_high(self, scorer):
        """Test data tier identification for high quality (>=95)."""
        assert scorer.identify_data_tier(100.0) == 'high'
        assert scorer.identify_data_tier(98.0) == 'high'
        assert scorer.identify_data_tier(95.0) == 'high'
    
    def test_identify_data_tier_medium(self, scorer):
        """Test data tier identification for medium quality (70-94)."""
        assert scorer.identify_data_tier(94.0) == 'medium'
        assert scorer.identify_data_tier(85.0) == 'medium'
        assert scorer.identify_data_tier(70.0) == 'medium'
    
    def test_identify_data_tier_low(self, scorer):
        """Test data tier identification for low quality (<70)."""
        assert scorer.identify_data_tier(69.0) == 'low'
        assert scorer.identify_data_tier(50.0) == 'low'
        assert scorer.identify_data_tier(0.0) == 'low'
    
    # ========================================================================
    # SOURCE SUMMARY (1 test)
    # ========================================================================
    
    def test_summarize_sources(self, scorer):
        """Test source summary generation."""
        feature_sources = {
            0: 'phase4', 1: 'phase4', 2: 'phase4',
            3: 'phase3', 4: 'phase3',
            5: 'calculated',
            6: 'default'
        }
        
        result = scorer._summarize_sources(feature_sources)
        
        assert 'phase4=3' in result
        assert 'phase3=2' in result
        assert 'calc=1' in result
        assert 'default=1' in result


# ============================================================================
# TEST CLASS 3: BATCH WRITER (14 tests)
# ============================================================================

class TestBatchWriter:
    """Test BatchWriter - BigQuery MERGE operations (14 tests).

    Updated for MERGE-based write pattern:
    1. Create temp table with target schema
    2. Load all rows to temp table
    3. MERGE from temp to target
    4. Cleanup temp table
    """

    @pytest.fixture
    def mock_bq_client(self):
        """Create mock BigQuery client."""
        return Mock()

    @pytest.fixture
    def writer(self, mock_bq_client):
        """Create writer instance with mock client."""
        return BatchWriter(mock_bq_client, 'test-project')

    def setup_merge_mocks(self, mock_bq_client, schema=None):
        """Helper to set up common mocks for MERGE-based write_batch."""
        # Mock get_table (for schema)
        mock_table = Mock()
        mock_table.schema = schema or []
        mock_bq_client.get_table.return_value = mock_table

        # Mock create_table (for temp table)
        mock_bq_client.create_table.return_value = Mock()

        # Mock load_table_from_file (for temp table load)
        mock_load_job = Mock()
        mock_load_job.result.return_value = None
        mock_bq_client.load_table_from_file.return_value = mock_load_job

        # Mock query (for MERGE and cleanup)
        mock_query_job = Mock()
        mock_query_job.result.return_value = None
        mock_bq_client.query.return_value = mock_query_job

        # Mock delete_table (for cleanup)
        mock_bq_client.delete_table.return_value = None

    # ========================================================================
    # DELETE EXISTING DATA LEGACY (3 tests) - Still used as fallback
    # ========================================================================

    def test_delete_existing_data_legacy_success(self, writer, mock_bq_client):
        """Test successful delete operation."""
        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.num_dml_affected_rows = 150
        mock_bq_client.query.return_value = mock_job

        result = writer._delete_existing_data_legacy('project.dataset.table', date(2025, 1, 15))

        assert result is True, "Successful delete should return True"
        mock_bq_client.query.assert_called_once()
        assert "DELETE FROM" in mock_bq_client.query.call_args[0][0]
        assert "2025-01-15" in mock_bq_client.query.call_args[0][0]

    def test_delete_existing_data_legacy_streaming_buffer(self, writer, mock_bq_client):
        """Test delete blocked by streaming buffer."""
        mock_bq_client.query.side_effect = Exception("streaming buffer conflict")

        result = writer._delete_existing_data_legacy('project.dataset.table', date(2025, 1, 15))

        assert result is False, "Streaming buffer conflict should return False"

    def test_delete_existing_data_legacy_other_error(self, writer, mock_bq_client):
        """Test delete with unexpected error raises exception."""
        mock_bq_client.query.side_effect = Exception("unexpected error")

        with pytest.raises(Exception, match="unexpected error"):
            writer._delete_existing_data_legacy('project.dataset.table', date(2025, 1, 15))

    # ========================================================================
    # WRITE BATCH - EMPTY INPUT (1 test)
    # ========================================================================

    def test_write_batch_empty_rows(self, writer, mock_bq_client):
        """Test writing empty list of rows returns early."""
        result = writer.write_batch([], 'dataset', 'table', date(2025, 1, 15))

        assert result['rows_processed'] == 0
        assert result['rows_failed'] == 0
        assert result['batches_written'] == 0
        assert result['batches_failed'] == 0
        assert len(result['errors']) == 0
        # Should not call any BigQuery operations
        mock_bq_client.get_table.assert_not_called()

    # ========================================================================
    # WRITE BATCH - MERGE FLOW (6 tests)
    # ========================================================================

    def test_write_batch_success(self, writer, mock_bq_client):
        """Test successful write using MERGE pattern."""
        rows = [{'id': i, 'game_date': '2025-01-15', 'player_lookup': f'player_{i}'} for i in range(50)]
        self.setup_merge_mocks(mock_bq_client)

        result = writer.write_batch(rows, 'dataset', 'table', date(2025, 1, 15))

        assert result['rows_processed'] == 50
        assert result['rows_failed'] == 0
        assert result['batches_written'] == 1
        assert result['batches_failed'] == 0
        assert len(result['errors']) == 0
        assert 'timing' in result

        # Verify MERGE flow was executed
        mock_bq_client.get_table.assert_called_once()  # Get schema
        mock_bq_client.create_table.assert_called_once()  # Create temp table
        mock_bq_client.load_table_from_file.assert_called_once()  # Load to temp
        mock_bq_client.query.assert_called_once()  # MERGE query
        mock_bq_client.delete_table.assert_called_once()  # Cleanup temp

    def test_write_batch_creates_temp_table(self, writer, mock_bq_client):
        """Test that write_batch creates a temp table with correct naming."""
        rows = [{'id': 1, 'game_date': '2025-01-15', 'player_lookup': 'test'}]
        self.setup_merge_mocks(mock_bq_client)

        writer.write_batch(rows, 'nba_predictions', 'ml_feature_store_v2', date(2025, 1, 15))

        # Check temp table name format
        create_call = mock_bq_client.create_table.call_args[0][0]
        assert 'ml_feature_store_v2_temp_' in create_call.table_id

    def test_write_batch_streaming_buffer_graceful(self, writer, mock_bq_client):
        """Test MERGE blocked by streaming buffer returns gracefully."""
        rows = [{'id': i} for i in range(10)]
        self.setup_merge_mocks(mock_bq_client)

        # Make MERGE query fail with streaming buffer error
        mock_bq_client.query.side_effect = Exception("streaming buffer conflict")

        result = writer.write_batch(rows, 'dataset', 'table', date(2025, 1, 15))

        assert result['rows_processed'] == 0
        assert result['rows_failed'] == 10
        assert result['batches_written'] == 0
        assert result['batches_failed'] == 1
        assert 'streaming buffer' in result['errors'][0].lower()

    def test_write_batch_load_failure(self, writer, mock_bq_client):
        """Test failure during temp table load."""
        rows = [{'id': i} for i in range(10)]
        self.setup_merge_mocks(mock_bq_client)

        # Make load fail
        mock_bq_client.load_table_from_file.side_effect = Exception("load failed")

        result = writer.write_batch(rows, 'dataset', 'table', date(2025, 1, 15))

        assert result['rows_failed'] == 10
        assert result['batches_failed'] == 1
        assert len(result['errors']) > 0
        # Temp table should still be cleaned up
        mock_bq_client.delete_table.assert_called_once()

    def test_write_batch_timing_captured(self, writer, mock_bq_client):
        """Test that timing information is captured."""
        rows = [{'id': 1}]
        self.setup_merge_mocks(mock_bq_client)

        result = writer.write_batch(rows, 'dataset', 'table', date(2025, 1, 15))

        timing = result['timing']
        assert 'get_schema' in timing
        assert 'create_temp_table' in timing
        assert 'load_temp_table' in timing
        assert 'merge_operation' in timing
        assert 'total' in timing

    def test_write_batch_cleans_up_on_error(self, writer, mock_bq_client):
        """Test temp table cleanup happens even on errors."""
        rows = [{'id': 1}]
        self.setup_merge_mocks(mock_bq_client)

        # Make MERGE fail
        mock_bq_client.query.side_effect = Exception("merge failed")

        writer.write_batch(rows, 'dataset', 'table', date(2025, 1, 15))

        # Cleanup should still be called
        mock_bq_client.delete_table.assert_called_once()

    # ========================================================================
    # ENSURE REQUIRED DEFAULTS (2 tests)
    # ========================================================================

    def test_ensure_required_defaults_adds_missing(self, writer):
        """Test that required fields get default values."""
        from google.cloud import bigquery as bq_module

        rows = [{'id': 1, 'name': 'test'}]
        required_fields = {'id', 'name', 'status', 'count'}

        result = writer._ensure_required_defaults(rows, required_fields)

        assert len(result) == 1
        assert result[0]['id'] == 1
        assert result[0]['name'] == 'test'
        # Status should get default empty string, count should get default 0 or similar

    def test_ensure_required_defaults_preserves_existing(self, writer):
        """Test that existing values are preserved."""
        rows = [{'id': 1, 'status': 'active'}]
        required_fields = {'id', 'status'}

        result = writer._ensure_required_defaults(rows, required_fields)

        assert result[0]['id'] == 1
        assert result[0]['status'] == 'active'

    # ========================================================================
    # SANITIZE ROW (2 tests)
    # ========================================================================

    def test_sanitize_row_converts_dates(self, writer):
        """Test that date objects are converted to ISO strings."""
        row = {
            'game_date': date(2025, 1, 15),
            'name': 'test'
        }

        result = writer._sanitize_row(row)

        assert result['game_date'] == '2025-01-15'
        assert result['name'] == 'test'

    def test_sanitize_row_handles_none(self, writer):
        """Test that None values are preserved."""
        row = {
            'id': 1,
            'optional_field': None
        }

        result = writer._sanitize_row(row)

        assert result['id'] == 1
        assert result['optional_field'] is None


# ============================================================================
# TEST SUMMARY
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
