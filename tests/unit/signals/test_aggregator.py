"""
Unit Tests for BestBetsAggregator

Tests cover:
1. Filter summary return type (tuple)
2. Filter rejection counts for each filter
3. Edge distribution tracking
4. Empty predictions handling
"""

import pytest
from unittest.mock import patch, MagicMock

from ml.signals.aggregator import BestBetsAggregator
from ml.signals.base_signal import SignalResult
from ml.signals.combo_registry import _FALLBACK_REGISTRY


def _make_signal_result(tag: str, qualifies: bool = True) -> SignalResult:
    """Helper to create a mock SignalResult."""
    return SignalResult(
        qualifies=qualifies,
        confidence=0.5,
        source_tag=tag,
    )


def _make_prediction(
    player_lookup='player_a',
    game_id='20260220_LAL_GSW',
    edge=6.0,
    recommendation='OVER',
    feature_quality_score=90,
    line_value=20.0,
    confidence_score=0.85,
    prop_line_delta=None,
    neg_pm_streak=0,
    games_vs_opponent=0,
    source_model_family='',
    is_home=True,
) -> dict:
    """Helper to create a prediction dict that passes all filters by default."""
    return {
        'player_lookup': player_lookup,
        'game_id': game_id,
        'player_name': 'Player A',
        'team_abbr': 'LAL',
        'opponent_team_abbr': 'GSW',
        'predicted_points': 25.0,
        'line_value': line_value,
        'recommendation': recommendation,
        'edge': edge,
        'confidence_score': confidence_score,
        'feature_quality_score': feature_quality_score,
        'prop_line_delta': prop_line_delta,
        'neg_pm_streak': neg_pm_streak,
        'games_vs_opponent': games_vs_opponent,
        'source_model_family': source_model_family,
        'is_home': is_home,
    }


class TestComboRegistryNoAntiPattern:
    """Verify ANTI_PATTERN entries were removed from fallback registry (Session 314)."""

    def test_no_anti_pattern_in_fallback_registry(self):
        """ANTI_PATTERN entries for high_edge and edge_spread_optimal+high_edge
        blocked ALL edge 5+ candidates by construction. They must not exist."""
        for combo_id, entry in _FALLBACK_REGISTRY.items():
            assert entry.classification != 'ANTI_PATTERN', (
                f"ANTI_PATTERN entry found in fallback registry: {combo_id}"
            )

    def test_high_edge_standalone_not_in_registry(self):
        assert 'high_edge' not in _FALLBACK_REGISTRY

    def test_edge_spread_high_edge_not_in_registry(self):
        assert 'edge_spread_optimal+high_edge' not in _FALLBACK_REGISTRY


class TestAggregatorReturnType:
    """Test that aggregate() returns (picks, filter_summary) tuple."""

    def test_returns_tuple(self):
        agg = BestBetsAggregator()
        result = agg.aggregate([], {})
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_empty_predictions_filter_summary(self):
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([], {})
        assert picks == []
        assert summary['total_candidates'] == 0
        assert summary['passed_filters'] == 0
        assert summary['rejected'] == {
            'blacklist': 0,
            'edge_floor': 0,
            'under_edge_7plus': 0,
            'familiar_matchup': 0,
            'quality_floor': 0,
            'bench_under': 0,
            'line_jumped_under': 0,
            'line_dropped_under': 0,
            'neg_pm_streak': 0,
            'signal_count': 0,
            'confidence': 0,
            'anti_pattern': 0,
            'model_direction_affinity': 0,
            'away_noveg': 0,
            'signal_density': 0,
        }


class TestFilterTracking:
    """Test that individual filter rejections are tracked correctly."""

    def _make_signal_results_for(self, pred, n_qualifying=3):
        """Build signal results dict with enough qualifying signals."""
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_blacklist_tracked(self):
        pred = _make_prediction(player_lookup='bad_player')
        agg = BestBetsAggregator(player_blacklist={'bad_player'})
        _, summary = agg.aggregate([pred], {})
        assert summary['rejected']['blacklist'] == 1
        assert summary['passed_filters'] == 0

    def test_edge_floor_tracked(self):
        pred = _make_prediction(edge=3.0)  # Below MIN_EDGE=5.0
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], {})
        assert summary['rejected']['edge_floor'] == 1

    def test_under_edge_7plus_tracked(self):
        pred = _make_prediction(edge=8.0, recommendation='UNDER', line_value=20.0)
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], {})
        assert summary['rejected']['under_edge_7plus'] == 1

    def test_under_edge_7plus_v12_allowed(self):
        """V12 models are exempt from the UNDER edge 7+ block (Session 326)."""
        pred = _make_prediction(
            edge=8.0, recommendation='UNDER', line_value=27.5,
            source_model_family='v12_mae',
        )
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], {})
        assert summary['rejected']['under_edge_7plus'] == 0

    def test_familiar_matchup_tracked(self):
        pred = _make_prediction(games_vs_opponent=7)
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], {})
        assert summary['rejected']['familiar_matchup'] == 1

    def test_quality_floor_tracked(self):
        pred = _make_prediction(feature_quality_score=50)
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], {})
        assert summary['rejected']['quality_floor'] == 1

    def test_bench_under_tracked(self):
        pred = _make_prediction(recommendation='UNDER', line_value=10.0)
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], {})
        assert summary['rejected']['bench_under'] == 1

    def test_line_jumped_under_tracked(self):
        pred = _make_prediction(
            recommendation='UNDER', prop_line_delta=3.0, feature_quality_score=90
        )
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], {})
        assert summary['rejected']['line_jumped_under'] == 1

    def test_line_dropped_under_tracked(self):
        pred = _make_prediction(
            recommendation='UNDER', prop_line_delta=-3.0, feature_quality_score=90
        )
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], {})
        assert summary['rejected']['line_dropped_under'] == 1

    def test_neg_pm_streak_tracked(self):
        pred = _make_prediction(recommendation='UNDER', neg_pm_streak=4)
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], {})
        assert summary['rejected']['neg_pm_streak'] == 1

    def test_signal_count_tracked(self):
        """Prediction passes all negative filters but has 0 qualifying signals."""
        pred = _make_prediction()
        agg = BestBetsAggregator()
        # Empty signal results → signal_count filter
        _, summary = agg.aggregate([pred], {})
        assert summary['rejected']['signal_count'] == 1

    def test_total_candidates_correct(self):
        preds = [_make_prediction(player_lookup=f'p{i}', edge=2.0) for i in range(5)]
        agg = BestBetsAggregator()
        _, summary = agg.aggregate(preds, {})
        assert summary['total_candidates'] == 5

    def test_passed_filters_correct(self):
        """One prediction passes all filters including signal count."""
        pred = _make_prediction()
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert summary['passed_filters'] == 1
        assert len(picks) == 1


class TestMultipleFilters:
    """Test scenarios with multiple predictions hitting different filters."""

    def test_mixed_rejections(self):
        preds = [
            _make_prediction(player_lookup='p1', edge=2.0),      # edge_floor
            _make_prediction(player_lookup='p2', edge=8.0, recommendation='UNDER'),  # under_edge_7plus
            _make_prediction(player_lookup='p3', feature_quality_score=0),  # quality_floor
        ]
        agg = BestBetsAggregator()
        _, summary = agg.aggregate(preds, {})
        assert summary['total_candidates'] == 3
        assert summary['rejected']['edge_floor'] == 1
        assert summary['rejected']['under_edge_7plus'] == 1
        assert summary['rejected']['quality_floor'] == 1
        assert summary['passed_filters'] == 0


# ============================================================================
# MODEL-DIRECTION AFFINITY FILTER TESTS (Session 330)
# ============================================================================

class TestModelDirectionAffinityFilter:
    """Test that model_direction_blocks parameter is respected in aggregator."""

    def _make_signal_results_for(self, pred, n_qualifying=3):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_blocked_combo_rejected(self):
        """Prediction with blocked model+direction+edge combo is rejected."""
        # Use V12+vegas OVER (not caught by the hardcoded UNDER 7+ block)
        pred = _make_prediction(
            player_lookup='player_v12_over',
            edge=6.0,
            recommendation='OVER',
            source_model_family='v12_mae',
        )
        signals = self._make_signal_results_for(pred)

        # Block v12_vegas OVER 5_7
        blocked = {('v12_vegas', 'OVER', '5_7')}
        agg = BestBetsAggregator(
            model_direction_blocks=blocked,
        )
        picks, summary = agg.aggregate([pred], signals)

        assert len(picks) == 0
        assert summary['rejected']['model_direction_affinity'] == 1

    def test_non_blocked_combo_passes(self):
        """Prediction with non-blocked combo passes the filter."""
        pred = _make_prediction(
            player_lookup='player_v9_over',
            edge=6.0,
            recommendation='OVER',
            source_model_family='v9_mae',
        )
        signals = self._make_signal_results_for(pred)

        # Only block v9 UNDER 7+, not v9 OVER
        blocked = {('v9', 'UNDER', '7_plus')}
        agg = BestBetsAggregator(
            model_direction_blocks=blocked,
        )
        picks, summary = agg.aggregate([pred], signals)

        assert len(picks) == 1
        assert summary['rejected']['model_direction_affinity'] == 0

    def test_empty_blocks_no_effect(self):
        """Empty model_direction_blocks should not filter anything."""
        pred = _make_prediction(
            source_model_family='v9_mae',
        )
        signals = self._make_signal_results_for(pred)

        agg = BestBetsAggregator(
            model_direction_blocks=set(),
        )
        picks, summary = agg.aggregate([pred], signals)

        assert len(picks) == 1
        assert summary['rejected']['model_direction_affinity'] == 0

    def test_none_blocks_no_effect(self):
        """None model_direction_blocks should not filter anything."""
        pred = _make_prediction(
            source_model_family='v9_mae',
        )
        signals = self._make_signal_results_for(pred)

        agg = BestBetsAggregator(
            model_direction_blocks=None,
        )
        picks, summary = agg.aggregate([pred], signals)

        assert len(picks) == 1
        assert summary['rejected']['model_direction_affinity'] == 0

    def test_filter_counter_in_summary(self):
        """model_direction_affinity key always present in filter summary."""
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([], {})
        assert 'model_direction_affinity' in summary['rejected']


# ============================================================================
# AWAY NOVEG FILTER TESTS (Session 347)
# ============================================================================

class TestAwayNovegFilter:
    """Test that v12_noveg AWAY predictions are blocked (Session 347).

    v12_noveg models hit 57-59% HOME but only 43-44% AWAY — +15pp gap.
    """

    def _make_signal_results_for(self, pred, n_qualifying=3):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_away_noveg_blocked(self):
        """v12_noveg AWAY prediction is rejected."""
        pred = _make_prediction(
            source_model_family='v12_q43',
            is_home=False,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['away_noveg'] == 1

    def test_home_noveg_allowed(self):
        """v12_noveg HOME prediction passes the filter."""
        pred = _make_prediction(
            source_model_family='v12_q43',
            is_home=True,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['away_noveg'] == 0

    def test_away_non_noveg_allowed(self):
        """Non-noveg AWAY prediction is NOT blocked."""
        pred = _make_prediction(
            source_model_family='v9_mae',
            is_home=False,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['away_noveg'] == 0

    def test_away_noveg_q45_blocked(self):
        """v12_q45 (also noveg group) AWAY prediction is rejected."""
        pred = _make_prediction(
            source_model_family='v12_q45',
            is_home=False,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['away_noveg'] == 1

    def test_away_noveg_q55_tw_blocked(self):
        """v12_noveg_q55_tw (shadow model) AWAY prediction is rejected."""
        pred = _make_prediction(
            source_model_family='v12_noveg_q55_tw',
            is_home=False,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['away_noveg'] == 1

    def test_away_v12_vegas_allowed(self):
        """v12_mae (v12_vegas group) AWAY prediction is NOT blocked."""
        pred = _make_prediction(
            source_model_family='v12_mae',
            is_home=False,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['away_noveg'] == 0

    def test_missing_is_home_treated_as_away(self):
        """Prediction without is_home field is treated as AWAY (blocked)."""
        pred = _make_prediction(
            source_model_family='v12_q43',
        )
        del pred['is_home']  # Remove the field entirely
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['away_noveg'] == 1


# ============================================================================
# SIGNAL DENSITY FILTER TESTS (Session 348)
# ============================================================================

class TestSignalDensityFilter:
    """Test that picks with only base signals are blocked (Session 348).

    Base signals (model_health, high_edge, edge_spread_optimal) fire on
    nearly every edge 5+ pick. Picks with ONLY these hit 57.1% (N=42).
    Picks with at least one additional signal hit 77.8% (N=63).
    """

    def _make_base_only_signals(self, pred):
        """Build signal results with only the 3 base signals."""
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        return {key: [
            _make_signal_result('model_health'),
            _make_signal_result('high_edge'),
            _make_signal_result('edge_spread_optimal'),
        ]}

    def _make_rich_signals(self, pred):
        """Build signal results with base + additional signal."""
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        return {key: [
            _make_signal_result('model_health'),
            _make_signal_result('high_edge'),
            _make_signal_result('edge_spread_optimal'),
            _make_signal_result('rest_advantage_2d'),
        ]}

    def test_base_only_signals_blocked(self):
        """Pick with only model_health + high_edge + edge_spread_optimal is blocked."""
        pred = _make_prediction()
        signals = self._make_base_only_signals(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['signal_density'] == 1

    def test_base_plus_one_signal_passes(self):
        """Pick with base signals + rest_advantage_2d passes."""
        pred = _make_prediction()
        signals = self._make_rich_signals(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['signal_density'] == 0

    def test_two_base_signals_blocked(self):
        """Pick with subset of base signals (2 of 3) is also blocked."""
        pred = _make_prediction()
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('model_health'),
            _make_signal_result('high_edge'),
        ]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['signal_density'] == 1

    def test_non_base_signals_pass(self):
        """Pick with non-base signals (e.g. combo signals) passes."""
        pred = _make_prediction()
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('model_health'),
            _make_signal_result('combo_he_ms'),
            _make_signal_result('combo_3way'),
        ]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['signal_density'] == 0

    def test_filter_counter_in_summary(self):
        """signal_density key always present in filter summary."""
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([], {})
        assert 'signal_density' in summary['rejected']

    def test_base_plus_book_disagreement_passes(self):
        """Pick with base + book_disagreement passes (100% HR combo)."""
        pred = _make_prediction()
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('model_health'),
            _make_signal_result('high_edge'),
            _make_signal_result('edge_spread_optimal'),
            _make_signal_result('book_disagreement'),
        ]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['signal_density'] == 0
