"""Tests for health-aware signal weighting in aggregator.

Session 469: COLD signals get reduced weight in composite scoring.
"""

import pytest
from ml.signals.aggregator import BestBetsAggregator


class TestHealthMultiplier:
    """Test _health_multiplier method."""

    def test_no_health_data_returns_1(self):
        agg = BestBetsAggregator(signal_health={})
        assert agg._health_multiplier('home_under') == 1.0

    def test_normal_regime_returns_1(self):
        agg = BestBetsAggregator(signal_health={
            'home_under': {'regime': 'NORMAL', 'is_model_dependent': False}
        })
        assert agg._health_multiplier('home_under') == 1.0

    def test_hot_regime_returns_1_2(self):
        agg = BestBetsAggregator(signal_health={
            'book_disagreement': {'regime': 'HOT', 'is_model_dependent': False}
        })
        assert agg._health_multiplier('book_disagreement') == 1.2

    def test_cold_behavioral_returns_0_5(self):
        agg = BestBetsAggregator(signal_health={
            'home_under': {'regime': 'COLD', 'is_model_dependent': False}
        })
        assert agg._health_multiplier('home_under') == 0.5

    def test_cold_model_dependent_returns_0(self):
        agg = BestBetsAggregator(signal_health={
            'combo_3way': {'regime': 'COLD', 'is_model_dependent': True}
        })
        assert agg._health_multiplier('combo_3way') == 0.0

    def test_unknown_signal_returns_1(self):
        agg = BestBetsAggregator(signal_health={
            'other_signal': {'regime': 'NORMAL', 'is_model_dependent': False}
        })
        assert agg._health_multiplier('nonexistent_signal') == 1.0


class TestOverLineRoseHeavyFilter:
    """Test over_line_rose_heavy is now an active blocking filter."""

    def test_over_line_rose_heavy_blocks(self):
        """OVER picks with BettingPros line rose >= 1.0 should be blocked."""
        agg = BestBetsAggregator()
        predictions = [{
            'player_lookup': 'test_player',
            'game_id': 'g1',
            'game_date': '2026-03-11',
            'system_id': 'catboost_v12_test',
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'BOS',
            'recommendation': 'OVER',
            'edge': 6.0,
            'predicted_points': 25.0,
            'line_value': 19.0,
            'current_points_line': 19.0,
            'confidence_score': 0.7,
            'feature_quality_score': 95,
            'bp_line_movement': 1.5,  # Line rose >= 1.0 → should block
            'points_avg_season': 20.0,
        }]
        from ml.signals.base_signal import SignalResult
        # Provide enough signals to pass SC gate
        signal_results = {
            'test_player::g1': [
                SignalResult(qualifies=True, confidence=0.9, source_tag='model_health'),
                SignalResult(qualifies=True, confidence=0.9, source_tag='high_edge'),
                SignalResult(qualifies=True, confidence=0.9, source_tag='edge_spread_optimal'),
                SignalResult(qualifies=True, confidence=0.9, source_tag='line_rising_over'),
            ]
        }
        picks, summary = agg.aggregate(predictions, signal_results)
        # Pick should be filtered by over_line_rose_heavy
        assert summary['rejected']['over_line_rose_heavy'] == 1
        assert len(picks) == 0
