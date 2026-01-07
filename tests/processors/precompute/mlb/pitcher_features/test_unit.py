#!/usr/bin/env python3
"""
Unit tests for MLB Pitcher Features Processor (V2 - 35 features).

Tests the feature calculation logic without BigQuery dependencies.
"""

import pytest
from datetime import date
from unittest.mock import Mock, patch


class TestPitcherFeaturesProcessor:
    """Tests for MlbPitcherFeaturesProcessor."""

    @pytest.fixture
    def processor(self):
        """Create processor with mocked BigQuery client."""
        with patch('data_processors.precompute.precompute_base.bigquery'):
            from data_processors.precompute.mlb.pitcher_features_processor import (
                MlbPitcherFeaturesProcessor
            )
            proc = MlbPitcherFeaturesProcessor()
            proc.bq_client = Mock()
            proc.project_id = 'test-project'
            return proc

    def test_processor_initialization(self, processor):
        """Test processor initializes with V2 feature version."""
        assert processor.processor_name == "mlb_pitcher_features"
        assert processor.target_table == "mlb_precompute.pitcher_ml_features"
        assert processor.feature_version == "v2_35features"

    def test_moneyline_to_probability_favorite(self, processor):
        """Test moneyline conversion for favorites (negative odds)."""
        # -150 favorite: 150/(150+100) = 0.60
        prob = processor._moneyline_to_probability(-150)
        assert abs(prob - 0.60) < 0.01

        # -200 heavy favorite: 200/(200+100) = 0.667
        prob = processor._moneyline_to_probability(-200)
        assert abs(prob - 0.667) < 0.01

    def test_moneyline_to_probability_underdog(self, processor):
        """Test moneyline conversion for underdogs (positive odds)."""
        # +150 underdog: 100/(150+100) = 0.40
        prob = processor._moneyline_to_probability(150)
        assert abs(prob - 0.40) < 0.01

        # +200 big underdog: 100/(200+100) = 0.333
        prob = processor._moneyline_to_probability(200)
        assert abs(prob - 0.333) < 0.01

    def test_moneyline_to_probability_none(self, processor):
        """Test default probability when moneyline is None."""
        prob = processor._moneyline_to_probability(None)
        assert prob == 0.5

    def test_safe_float_conversion(self, processor):
        """Test safe float conversion handles edge cases."""
        assert processor._safe_float(5.5) == 5.5
        assert processor._safe_float("3.14") == 3.14
        assert processor._safe_float(None) is None
        assert processor._safe_float("invalid") is None
        assert processor._safe_float({}) is None

    def test_estimate_abs_by_order(self, processor):
        """Test at-bat estimation by batting order."""
        assert processor._estimate_abs_by_order(1) == 4.5
        assert processor._estimate_abs_by_order(4) == 4.0
        assert processor._estimate_abs_by_order(9) == 3.5

    def test_calculate_bottom_up_k_empty_lineup(self, processor):
        """Test bottom-up K returns 0 for empty lineup."""
        result = processor._calculate_bottom_up_k([], {})
        assert result == 0.0

    def test_calculate_bottom_up_k_with_data(self, processor):
        """Test bottom-up K calculation with batter data."""
        opponent_batters = [
            {'player_lookup': 'batter1', 'batting_order': 1},
            {'player_lookup': 'batter2', 'batting_order': 2},
        ]
        batter_stats = {
            'batter1': {'k_rate_last_10': 0.25, 'season_k_rate': 0.24},
            'batter2': {'k_rate_last_10': 0.20, 'season_k_rate': 0.21},
        }

        result = processor._calculate_bottom_up_k(opponent_batters, batter_stats)

        # Batter1: 0.25 × 4.5 = 1.125
        # Batter2: 0.20 × 4.3 = 0.86
        # Total: ~1.99
        assert 1.9 <= result <= 2.1

    def test_calculate_team_k_rate_empty(self, processor):
        """Test team K rate returns None for empty lineup."""
        result = processor._calculate_team_k_rate([], {})
        assert result is None

    def test_calculate_team_k_rate_with_data(self, processor):
        """Test team K rate calculation."""
        opponent_batters = [
            {'player_lookup': 'batter1'},
            {'player_lookup': 'batter2'},
        ]
        batter_stats = {
            'batter1': {'k_rate_last_10': 0.25},
            'batter2': {'k_rate_last_10': 0.15},
        }

        result = processor._calculate_team_k_rate(opponent_batters, batter_stats)
        assert result == 0.20  # Average of 0.25 and 0.15

    def test_calculate_team_obp_fallback(self, processor):
        """Test team OBP returns league average for empty lineup."""
        result = processor._calculate_team_obp([], {})
        assert result == 0.320  # League average fallback


class TestPlatoonAdvantageCalculation:
    """Tests for platoon advantage feature (f27)."""

    @pytest.fixture
    def processor(self):
        """Create processor with mocked dependencies."""
        with patch('data_processors.precompute.precompute_base.bigquery'):
            from data_processors.precompute.mlb.pitcher_features_processor import (
                MlbPitcherFeaturesProcessor
            )
            proc = MlbPitcherFeaturesProcessor()
            proc.bq_client = Mock()
            proc.project_id = 'test-project'
            return proc

    def test_platoon_advantage_empty_lineup(self, processor):
        """Test platoon advantage returns 0 for empty lineup."""
        result = processor._calculate_platoon_advantage('R', [], {})
        assert result == 0.0

    def test_platoon_advantage_rhp_vs_lineup(self, processor):
        """Test platoon advantage for RHP."""
        opponent_batters = [
            {'player_lookup': 'batter1'},
            {'player_lookup': 'batter2'},
        ]

        # Batter 1: K rate 0.25 vs RHP, 0.20 vs LHP (easier to K vs RHP)
        # Batter 2: K rate 0.30 vs RHP, 0.22 vs LHP (easier to K vs RHP)
        batter_splits = {
            'batter1': {
                'vs_rhp': {'k_rate': 0.25},
                'vs_lhp': {'k_rate': 0.20},
            },
            'batter2': {
                'vs_rhp': {'k_rate': 0.30},
                'vs_lhp': {'k_rate': 0.22},
            },
        }

        result = processor._calculate_platoon_advantage('R', opponent_batters, batter_splits)

        # Batter1: 0.25 - 0.20 = 0.05 (advantage for RHP)
        # Batter2: 0.30 - 0.22 = 0.08 (advantage for RHP)
        # Average: 0.065
        assert 0.06 <= result <= 0.07

    def test_platoon_advantage_lhp_vs_lineup(self, processor):
        """Test platoon advantage for LHP."""
        opponent_batters = [
            {'player_lookup': 'batter1'},
        ]

        # Batter struggles more vs LHP
        batter_splits = {
            'batter1': {
                'vs_lhp': {'k_rate': 0.35},
                'vs_rhp': {'k_rate': 0.20},
            },
        }

        result = processor._calculate_platoon_advantage('L', opponent_batters, batter_splits)

        # 0.35 - 0.20 = 0.15 (big advantage for LHP)
        assert abs(result - 0.15) < 0.001


class TestWeakSpotsCalculation:
    """Tests for lineup weak spots feature (f33)."""

    @pytest.fixture
    def processor(self):
        """Create processor with mocked dependencies."""
        with patch('data_processors.precompute.precompute_base.bigquery'):
            from data_processors.precompute.mlb.pitcher_features_processor import (
                MlbPitcherFeaturesProcessor
            )
            proc = MlbPitcherFeaturesProcessor()
            proc.bq_client = Mock()
            proc.project_id = 'test-project'
            return proc

    def test_count_weak_spots_none(self, processor):
        """Test no weak spots when all batters have low K rates."""
        opponent_batters = [
            {'player_lookup': 'batter1'},
            {'player_lookup': 'batter2'},
        ]
        batter_profiles = {
            'batter1': {'season_k_rate': 0.18},
            'batter2': {'season_k_rate': 0.22},
        }

        result = processor._count_weak_spots(opponent_batters, batter_profiles)
        assert result == 0

    def test_count_weak_spots_some(self, processor):
        """Test counting batters with K rate > 0.28."""
        opponent_batters = [
            {'player_lookup': 'batter1'},
            {'player_lookup': 'batter2'},
            {'player_lookup': 'batter3'},
        ]
        batter_profiles = {
            'batter1': {'season_k_rate': 0.35},  # Weak spot
            'batter2': {'season_k_rate': 0.22},  # Not weak
            'batter3': {'season_k_rate': 0.30},  # Weak spot
        }

        result = processor._count_weak_spots(opponent_batters, batter_profiles)
        assert result == 2


class TestMatchupEdgeCalculation:
    """Tests for matchup edge feature (f34)."""

    @pytest.fixture
    def processor(self):
        """Create processor with mocked dependencies."""
        with patch('data_processors.precompute.precompute_base.bigquery'):
            from data_processors.precompute.mlb.pitcher_features_processor import (
                MlbPitcherFeaturesProcessor
            )
            proc = MlbPitcherFeaturesProcessor()
            proc.bq_client = Mock()
            proc.project_id = 'test-project'
            return proc

    def test_matchup_edge_neutral(self, processor):
        """Test matchup edge around 0 for average matchup."""
        opponent_batters = [{'player_lookup': 'batter1'}]
        batter_profiles = {'batter1': {'season_k_rate': 0.22}}  # League avg
        p_arsenal = {
            'overall_whiff_rate': 0.25,  # Baseline
            'put_away_rate': 0.30,  # Baseline
        }

        result = processor._calculate_matchup_edge(
            'pitcher1', opponent_batters, batter_profiles, 'R', p_arsenal
        )

        # Should be close to 0 for average matchup
        assert -0.5 <= result <= 0.5

    def test_matchup_edge_pitcher_advantage(self, processor):
        """Test positive matchup edge for elite pitcher vs weak lineup."""
        opponent_batters = [{'player_lookup': 'batter1'}]
        batter_profiles = {'batter1': {'season_k_rate': 0.35}}  # High K batter
        p_arsenal = {
            'overall_whiff_rate': 0.32,  # Elite
            'put_away_rate': 0.45,  # Elite
        }

        result = processor._calculate_matchup_edge(
            'pitcher1', opponent_batters, batter_profiles, 'R', p_arsenal
        )

        # Should be positive - pitcher advantage
        assert result > 0

    def test_matchup_edge_clamped_to_range(self, processor):
        """Test matchup edge is clamped to -3 to +3."""
        opponent_batters = [{'player_lookup': 'batter1'}]
        batter_profiles = {'batter1': {'season_k_rate': 0.50}}  # Extreme
        p_arsenal = {
            'overall_whiff_rate': 0.50,  # Extreme
            'put_away_rate': 0.60,  # Extreme
        }

        result = processor._calculate_matchup_edge(
            'pitcher1', opponent_batters, batter_profiles, 'R', p_arsenal
        )

        assert -3.0 <= result <= 3.0


class TestFeatureVectorConstruction:
    """Tests for the 35-element feature vector."""

    @pytest.fixture
    def processor(self):
        """Create processor with mocked dependencies."""
        with patch('data_processors.precompute.precompute_base.bigquery'):
            from data_processors.precompute.mlb.pitcher_features_processor import (
                MlbPitcherFeaturesProcessor
            )
            proc = MlbPitcherFeaturesProcessor()
            proc.bq_client = Mock()
            proc.project_id = 'test-project'
            return proc

    def test_feature_vector_length(self, processor):
        """Test that feature vector has exactly 35 elements."""
        game = {
            'game_pk': '12345',
            'home_team_abbr': 'NYY',
            'away_team_abbr': 'BOS',
            'is_day_game': True,
            'game_type': 'R',
        }

        result = processor._compute_pitcher_features(
            pitcher_lookup='cole_gerrit',
            game=game,
            side='home',
            lineups={},
            pitcher_stats={},
            batter_stats={},
            betting_lines={},
            pitcher_splits={},
            game_lines={},
            ballpark_factors={},
            pitcher_vs_team={},
            lineup_analysis={},
            umpire_data={},
            innings_projections={},
            arsenal_data={},
            batter_profiles={},
            batter_splits={},
            pitcher_hands={'cole_gerrit': 'R'},
            game_date=date(2025, 6, 15)
        )

        assert result is not None
        assert 'feature_vector' in result
        assert len(result['feature_vector']) == 35

    def test_feature_vector_contains_v1_features(self, processor):
        """Test that V1 features (f25-f29) are in the vector."""
        game = {
            'game_pk': '12345',
            'home_team_abbr': 'NYY',
            'away_team_abbr': 'BOS',
            'is_day_game': False,
            'game_type': 'R',
        }

        lineup_analysis = {
            'cole_gerrit': {
                'bottom_up_expected_k': 7.5,
                'lineup_k_rate_vs_hand': 0.24,
                'weak_spot_count': 3,
            }
        }

        result = processor._compute_pitcher_features(
            pitcher_lookup='cole_gerrit',
            game=game,
            side='home',
            lineups={},
            pitcher_stats={},
            batter_stats={},
            betting_lines={},
            pitcher_splits={},
            game_lines={},
            ballpark_factors={},
            pitcher_vs_team={},
            lineup_analysis=lineup_analysis,
            umpire_data={},
            innings_projections={},
            arsenal_data={},
            batter_profiles={},
            batter_splits={},
            pitcher_hands={'cole_gerrit': 'R'},
            game_date=date(2025, 6, 15)
        )

        # Check V1 features are populated
        assert result['f25_bottom_up_k_expected'] == 7.5
        assert result['f26_lineup_k_vs_hand'] == 0.24

        # Check they're in the vector at correct positions
        feature_vector = result['feature_vector']
        assert feature_vector[25] == 7.5  # f25
        assert feature_vector[26] == 0.24  # f26

    def test_feature_vector_contains_v2_features(self, processor):
        """Test that V2 features (f30-f34) are in the vector."""
        game = {
            'game_pk': '12345',
            'home_team_abbr': 'NYY',
            'away_team_abbr': 'BOS',
            'is_day_game': False,
            'game_type': 'R',
        }

        arsenal_data = {
            'cole_gerrit': {
                'velocity_trend': 1.5,
                'overall_whiff_rate': 0.30,
                'put_away_rate': 0.40,
            }
        }

        result = processor._compute_pitcher_features(
            pitcher_lookup='cole_gerrit',
            game=game,
            side='home',
            lineups={},
            pitcher_stats={},
            batter_stats={},
            betting_lines={},
            pitcher_splits={},
            game_lines={},
            ballpark_factors={},
            pitcher_vs_team={},
            lineup_analysis={},
            umpire_data={},
            innings_projections={},
            arsenal_data=arsenal_data,
            batter_profiles={},
            batter_splits={},
            pitcher_hands={'cole_gerrit': 'R'},
            game_date=date(2025, 6, 15)
        )

        # Check V2 features are populated
        assert result['f30_velocity_trend'] == 1.5
        assert result['f31_whiff_rate'] == 0.30
        assert result['f32_put_away_rate'] == 0.40

        # Check they're in the vector at correct positions
        feature_vector = result['feature_vector']
        assert feature_vector[30] == 1.5  # f30
        assert feature_vector[31] == 0.30  # f31
        assert feature_vector[32] == 0.40  # f32


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
