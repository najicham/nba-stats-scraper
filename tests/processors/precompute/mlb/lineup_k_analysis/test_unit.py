#!/usr/bin/env python3
"""
Unit tests for MLB Lineup K Analysis Processor.

Tests the bottom-up K calculation logic without BigQuery dependencies.
"""

import pytest
from datetime import date
from unittest.mock import Mock, patch, MagicMock


class TestLineupKAnalysisProcessor:
    """Tests for MlbLineupKAnalysisProcessor."""

    @pytest.fixture
    def processor(self):
        """Create processor with mocked BigQuery client."""
        with patch('data_processors.precompute.precompute_base.bigquery'):
            from data_processors.precompute.mlb.lineup_k_analysis_processor import (
                MlbLineupKAnalysisProcessor
            )
            proc = MlbLineupKAnalysisProcessor()
            proc.bq_client = Mock()
            proc.project_id = 'test-project'
            return proc

    def test_processor_initialization(self, processor):
        """Test processor initializes with correct attributes."""
        assert processor.processor_name == "mlb_lineup_k_analysis"
        assert processor.target_table == "mlb_precompute.lineup_k_analysis"

    def test_estimate_abs_by_order(self, processor):
        """Test at-bat estimation by batting order position."""
        # Leadoff gets most ABs
        assert processor._estimate_abs_by_order(1) == 4.5
        # 9-hole gets fewest
        assert processor._estimate_abs_by_order(9) == 3.5
        # Middle of order
        assert processor._estimate_abs_by_order(4) == 4.0
        assert processor._estimate_abs_by_order(5) == 3.9
        # Invalid position returns default
        assert processor._estimate_abs_by_order(10) == 3.8
        assert processor._estimate_abs_by_order(0) == 3.8

    def test_compute_lineup_analysis_no_batters(self, processor):
        """Test handling when no batters in lineup."""
        game = {
            'game_pk': '12345',
            'home_team_abbr': 'NYY',
            'away_team_abbr': 'BOS'
        }

        result = processor._compute_lineup_analysis(
            pitcher_lookup='cole_gerrit',
            game=game,
            side='home',
            lineups={},  # Empty lineups
            batter_stats={},
            batter_splits={},
            pitcher_hands={'cole_gerrit': 'R'},
            game_date=date(2025, 6, 15)
        )

        assert result is None

    def test_compute_lineup_analysis_basic(self, processor):
        """Test basic lineup analysis calculation."""
        game = {
            'game_pk': '12345',
            'home_team_abbr': 'NYY',
            'away_team_abbr': 'BOS'
        }

        # BOS batters (opponent when pitcher is home)
        lineups = {
            '12345': {
                'BOS': [
                    {'player_lookup': 'devers_rafael', 'player_name': 'Rafael Devers', 'batting_order': 1, 'team_abbr': 'BOS'},
                    {'player_lookup': 'turner_justin', 'player_name': 'Justin Turner', 'batting_order': 2, 'team_abbr': 'BOS'},
                    {'player_lookup': 'yoshida_masataka', 'player_name': 'Masataka Yoshida', 'batting_order': 3, 'team_abbr': 'BOS'},
                ]
            }
        }

        batter_stats = {
            'devers_rafael': {'k_rate_last_10': 0.20, 'season_k_rate': 0.22},
            'turner_justin': {'k_rate_last_10': 0.25, 'season_k_rate': 0.24},
            'yoshida_masataka': {'k_rate_last_10': 0.15, 'season_k_rate': 0.16},
        }

        batter_splits = {
            'devers_rafael': {'vs_rhp': {'k_rate': 0.22}},
            'turner_justin': {'vs_rhp': {'k_rate': 0.26}},
            'yoshida_masataka': {'vs_rhp': {'k_rate': 0.14}},
        }

        pitcher_hands = {'cole_gerrit': 'R'}

        result = processor._compute_lineup_analysis(
            pitcher_lookup='cole_gerrit',
            game=game,
            side='home',
            lineups=lineups,
            batter_stats=batter_stats,
            batter_splits=batter_splits,
            pitcher_hands=pitcher_hands,
            game_date=date(2025, 6, 15)
        )

        assert result is not None
        assert result['pitcher_lookup'] == 'cole_gerrit'
        assert result['opponent_team_abbr'] == 'BOS'
        assert result['game_id'] == '12345'

        # Check bottom-up calculation is reasonable
        assert result['bottom_up_expected_k'] > 0
        assert result['batters_with_k_data'] == 3
        assert result['data_completeness_pct'] == 100.0

    def test_lineup_quality_tier_classification(self, processor):
        """Test lineup quality tier classification logic."""
        game = {
            'game_pk': '12345',
            'home_team_abbr': 'NYY',
            'away_team_abbr': 'BOS'
        }

        # High K-prone lineup (avg K rate > 0.30)
        lineups = {
            '12345': {
                'BOS': [
                    {'player_lookup': 'batter1', 'player_name': 'Batter 1', 'batting_order': 1, 'team_abbr': 'BOS'},
                    {'player_lookup': 'batter2', 'player_name': 'Batter 2', 'batting_order': 2, 'team_abbr': 'BOS'},
                ]
            }
        }

        # High K rate batters
        batter_stats = {
            'batter1': {'k_rate_last_10': 0.35, 'season_k_rate': 0.34},
            'batter2': {'k_rate_last_10': 0.32, 'season_k_rate': 0.31},
        }

        result = processor._compute_lineup_analysis(
            pitcher_lookup='cole_gerrit',
            game=game,
            side='home',
            lineups=lineups,
            batter_stats=batter_stats,
            batter_splits={},
            pitcher_hands={'cole_gerrit': 'R'},
            game_date=date(2025, 6, 15)
        )

        assert result['lineup_quality_tier'] == 'HIGH_K_PRONE'
        assert result['weak_spot_count'] == 2  # Both batters have K rate > 0.28

    def test_lineup_quality_tier_elite_k_resistant(self, processor):
        """Test elite K resistant lineup classification."""
        game = {
            'game_pk': '12345',
            'home_team_abbr': 'NYY',
            'away_team_abbr': 'BOS'
        }

        lineups = {
            '12345': {
                'BOS': [
                    {'player_lookup': 'batter1', 'player_name': 'Batter 1', 'batting_order': 1, 'team_abbr': 'BOS'},
                    {'player_lookup': 'batter2', 'player_name': 'Batter 2', 'batting_order': 2, 'team_abbr': 'BOS'},
                ]
            }
        }

        # Low K rate batters (elite contact hitters)
        batter_stats = {
            'batter1': {'k_rate_last_10': 0.12, 'season_k_rate': 0.13},
            'batter2': {'k_rate_last_10': 0.15, 'season_k_rate': 0.14},
        }

        result = processor._compute_lineup_analysis(
            pitcher_lookup='cole_gerrit',
            game=game,
            side='home',
            lineups=lineups,
            batter_stats=batter_stats,
            batter_splits={},
            pitcher_hands={'cole_gerrit': 'R'},
            game_date=date(2025, 6, 15)
        )

        assert result['lineup_quality_tier'] == 'ELITE_K_RESISTANT'
        assert result['weak_spot_count'] == 0

    def test_bottom_up_k_calculation_accuracy(self, processor):
        """Test bottom-up K calculation is mathematically correct."""
        game = {
            'game_pk': '12345',
            'home_team_abbr': 'NYY',
            'away_team_abbr': 'BOS'
        }

        lineups = {
            '12345': {
                'BOS': [
                    {'player_lookup': 'batter1', 'batting_order': 1, 'team_abbr': 'BOS'},
                    {'player_lookup': 'batter2', 'batting_order': 2, 'team_abbr': 'BOS'},
                ]
            }
        }

        # Known K rates
        batter_stats = {
            'batter1': {'k_rate_last_10': 0.25},  # 25% K rate
            'batter2': {'k_rate_last_10': 0.20},  # 20% K rate
        }

        batter_splits = {
            'batter1': {'vs_rhp': {'k_rate': 0.25}},
            'batter2': {'vs_rhp': {'k_rate': 0.20}},
        }

        result = processor._compute_lineup_analysis(
            pitcher_lookup='pitcher1',
            game=game,
            side='home',
            lineups=lineups,
            batter_stats=batter_stats,
            batter_splits=batter_splits,
            pitcher_hands={'pitcher1': 'R'},
            game_date=date(2025, 6, 15)
        )

        # Manual calculation:
        # Batter 1: 0.25 K rate × 4.5 ABs (order 1) = 1.125 expected Ks
        # Batter 2: 0.20 K rate × 4.3 ABs (order 2) = 0.86 expected Ks
        # Total: ~1.99 expected Ks

        assert result is not None
        assert 1.9 <= result['bottom_up_expected_k'] <= 2.1

    def test_platoon_splits_used_correctly(self, processor):
        """Test that platoon splits are used when available."""
        game = {
            'game_pk': '12345',
            'home_team_abbr': 'NYY',
            'away_team_abbr': 'BOS'
        }

        lineups = {
            '12345': {
                'BOS': [
                    {'player_lookup': 'batter1', 'batting_order': 1, 'team_abbr': 'BOS'},
                ]
            }
        }

        # Season K rate is 0.20, but vs LHP is 0.35 (much higher)
        batter_stats = {
            'batter1': {'k_rate_last_10': 0.20, 'season_k_rate': 0.20},
        }

        batter_splits = {
            'batter1': {
                'vs_lhp': {'k_rate': 0.35},  # Much higher vs LHP
                'vs_rhp': {'k_rate': 0.18},
            },
        }

        # Test with LHP - should use vs_lhp split (0.35)
        result_vs_lhp = processor._compute_lineup_analysis(
            pitcher_lookup='lhp_pitcher',
            game=game,
            side='home',
            lineups=lineups,
            batter_stats=batter_stats,
            batter_splits=batter_splits,
            pitcher_hands={'lhp_pitcher': 'L'},
            game_date=date(2025, 6, 15)
        )

        # Test with RHP - should use vs_rhp split (0.18)
        result_vs_rhp = processor._compute_lineup_analysis(
            pitcher_lookup='rhp_pitcher',
            game=game,
            side='home',
            lineups=lineups,
            batter_stats=batter_stats,
            batter_splits=batter_splits,
            pitcher_hands={'rhp_pitcher': 'R'},
            game_date=date(2025, 6, 15)
        )

        # LHP should get more expected Ks due to higher K rate vs LHP
        assert result_vs_lhp['lineup_k_rate_vs_hand'] > result_vs_rhp['lineup_k_rate_vs_hand']
        assert result_vs_lhp['bottom_up_expected_k'] > result_vs_rhp['bottom_up_expected_k']


class TestBottomUpKCalculation:
    """Focused tests on the bottom-up K calculation formula."""

    @pytest.fixture
    def processor(self):
        """Create processor with mocked dependencies."""
        with patch('data_processors.precompute.precompute_base.bigquery'):
            from data_processors.precompute.mlb.lineup_k_analysis_processor import (
                MlbLineupKAnalysisProcessor
            )
            proc = MlbLineupKAnalysisProcessor()
            proc.bq_client = Mock()
            proc.project_id = 'test-project'
            return proc

    def test_full_nine_batter_lineup(self, processor):
        """Test with full 9-batter lineup."""
        game = {
            'game_pk': '12345',
            'home_team_abbr': 'NYY',
            'away_team_abbr': 'BOS'
        }

        # Create 9 batters
        batters = []
        batter_stats = {}
        for i in range(1, 10):
            batter_id = f'batter{i}'
            batters.append({
                'player_lookup': batter_id,
                'batting_order': i,
                'team_abbr': 'BOS'
            })
            # 22% league average K rate
            batter_stats[batter_id] = {'k_rate_last_10': 0.22, 'season_k_rate': 0.22}

        lineups = {'12345': {'BOS': batters}}

        result = processor._compute_lineup_analysis(
            pitcher_lookup='pitcher1',
            game=game,
            side='home',
            lineups=lineups,
            batter_stats=batter_stats,
            batter_splits={},
            pitcher_hands={'pitcher1': 'R'},
            game_date=date(2025, 6, 15)
        )

        # With 9 batters at 22% K rate and ~35 total ABs
        # Expected Ks ≈ 0.22 × 35 ≈ 7.7
        assert result['batters_with_k_data'] == 9
        assert 7.0 <= result['bottom_up_expected_k'] <= 8.5
        assert result['lineup_quality_tier'] == 'AVERAGE'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
