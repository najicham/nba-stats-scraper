"""
Unit Tests for BestBetsAggregator

Tests cover:
1. Filter summary return type (tuple)
2. Filter rejection counts for each filter
3. Edge distribution tracking
4. Empty predictions handling
5. Starter OVER SC floor (Session 382c)

Updated Session 382c: Fixed all tests for current filter stack (SC=3 OVER edge floor,
OVER edge 5+ floor, V12 UNDER 7+ exemption, starter OVER SC floor).
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
    points_avg_season=0,
    teammate_usage_available=0,
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
        'points_avg_season': points_avg_season,
        'teammate_usage_available': teammate_usage_available,
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
        # Verify all expected filter keys exist
        expected_keys = {
            'blacklist', 'edge_floor', 'over_edge_floor', 'under_edge_7plus',
            'familiar_matchup', 'quality_floor', 'bench_under',
            'line_jumped_under', 'line_dropped_under', 'line_dropped_over',
            'neg_pm_streak', 'signal_count', 'sc3_edge_floor',
            'starter_over_sc_floor', 'opponent_depleted_under',
            'high_book_std_under', 'confidence', 'anti_pattern',
            'model_direction_affinity', 'away_noveg', 'star_under',
            'under_star_away', 'med_usage_under', 'starter_v12_under',
            'opponent_under_block', 'signal_density', 'legacy_block',
        }
        assert set(summary['rejected'].keys()) == expected_keys
        # All counts should be 0 for empty input
        for key, val in summary['rejected'].items():
            assert val == 0, f"Expected {key}=0, got {val}"


class TestFilterTracking:
    """Test that individual filter rejections are tracked correctly."""

    def _make_signal_results_for(self, pred, n_qualifying=5):
        """Build signal results dict with enough qualifying signals.

        Default 5 signals to pass SC=3 OVER edge floor and starter OVER SC floor.
        """
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
        pred = _make_prediction(edge=2.5)  # Below MIN_EDGE=3.0 (Session 352)
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], {})
        assert summary['rejected']['edge_floor'] == 1

    def test_under_edge_7plus_tracked(self):
        """V9 UNDER edge 7+ is blocked (V12 is exempt since Session 367)."""
        pred = _make_prediction(
            edge=8.0, recommendation='UNDER', line_value=20.0,
            source_model_family='v9_mae',
        )
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], {})
        assert summary['rejected']['under_edge_7plus'] == 1

    def test_under_edge_7plus_v12_allowed(self):
        """V12 models are exempt from the UNDER edge 7+ block (Session 367)."""
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
        signals = self._make_signal_results_for(pred, n_qualifying=5)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert summary['passed_filters'] == 1
        assert len(picks) == 1


class TestMultipleFilters:
    """Test scenarios with multiple predictions hitting different filters."""

    def test_mixed_rejections(self):
        preds = [
            _make_prediction(player_lookup='p1', edge=2.0),      # edge_floor
            _make_prediction(player_lookup='p2', edge=8.0, recommendation='UNDER',
                             source_model_family='v9_mae'),  # under_edge_7plus (V9)
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

    def _make_signal_results_for(self, pred, n_qualifying=5):
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

    def _make_signal_results_for(self, pred, n_qualifying=5):
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

    def test_away_v9_blocked(self):
        """V9 AWAY prediction is blocked (Session 365: 48.1% AWAY HR, N=449)."""
        pred = _make_prediction(
            source_model_family='v9_mae',
            is_home=False,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['away_noveg'] == 1

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

    def _make_base_only_signals(self, pred, n_base=3):
        """Build signal results with only base signals."""
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        base_tags = ['model_health', 'high_edge', 'edge_spread_optimal']
        return {key: [_make_signal_result(t) for t in base_tags[:n_base]]}

    def _make_rich_signals(self, pred, n_extra=2):
        """Build signal results with base + additional signals.

        Default 5 total (3 base + 2 extra) to pass SC=3 OVER and starter OVER SC floors.
        """
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [
            _make_signal_result('model_health'),
            _make_signal_result('high_edge'),
            _make_signal_result('edge_spread_optimal'),
        ]
        for i in range(n_extra):
            signals.append(_make_signal_result(f'extra_signal_{i}'))
        return {key: signals}

    def test_base_only_signals_blocked(self):
        """Pick with only model_health + high_edge + edge_spread_optimal is blocked.

        Uses UNDER to avoid SC=3 OVER edge floor (which would catch it first).
        """
        pred = _make_prediction(recommendation='UNDER', line_value=26.0)
        signals = self._make_base_only_signals(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['signal_density'] == 1

    def test_base_plus_extra_signals_passes(self):
        """Pick with base signals + 2 extra signals passes (5 total)."""
        pred = _make_prediction()
        signals = self._make_rich_signals(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['signal_density'] == 0

    def test_below_min_signal_count_blocked(self):
        """Pick with only 2 signals is blocked by signal_count (MIN_SIGNAL_COUNT=3)."""
        pred = _make_prediction()
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('model_health'),
            _make_signal_result('high_edge'),
        ]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['signal_count'] == 1

    def test_non_base_signals_pass(self):
        """Pick with non-base signals (e.g. combo signals) passes."""
        pred = _make_prediction()
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('model_health'),
            _make_signal_result('combo_he_ms'),
            _make_signal_result('combo_3way'),
            _make_signal_result('rest_advantage_2d'),
            _make_signal_result('home_under'),
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
        """Pick with base + book_disagreement + extra passes (5 total)."""
        pred = _make_prediction()
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('model_health'),
            _make_signal_result('high_edge'),
            _make_signal_result('edge_spread_optimal'),
            _make_signal_result('book_disagreement'),
            _make_signal_result('rest_advantage_2d'),
        ]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['signal_density'] == 0


# ============================================================================
# MEDIUM TEAMMATE USAGE UNDER BLOCK TESTS (Session 355)
# ============================================================================

class TestMedTeammateUsageUnderBlock:
    """Test that UNDER + medium teammate_usage (15-30) is blocked (Session 355).

    Model has 0% importance on teammate_usage_available but production data
    shows 32.0% HR (N=25) when moderate usage available + UNDER.
    """

    def _make_signal_results_for(self, pred, n_qualifying=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_medium_usage_under_blocked(self):
        """UNDER + teammate_usage=20 is blocked."""
        pred = _make_prediction(
            recommendation='UNDER',
            teammate_usage_available=20,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['med_usage_under'] == 1

    def test_low_usage_under_allowed(self):
        """UNDER + teammate_usage=10 (below 15) passes."""
        pred = _make_prediction(
            recommendation='UNDER',
            teammate_usage_available=10,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['med_usage_under'] == 0

    def test_high_usage_under_allowed(self):
        """UNDER + teammate_usage=35 (above 30) passes."""
        pred = _make_prediction(
            recommendation='UNDER',
            teammate_usage_available=35,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['med_usage_under'] == 0

    def test_medium_usage_over_allowed(self):
        """OVER + medium usage is NOT blocked (only UNDER is problematic)."""
        pred = _make_prediction(
            recommendation='OVER',
            teammate_usage_available=20,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['med_usage_under'] == 0


# ============================================================================
# STARTER V12 UNDER BLOCK TESTS (Session 355)
# ============================================================================

class TestStarterV12UnderBlock:
    """Test that V12 UNDER + season_avg 15-20 is blocked (Session 355).

    V12 UNDER is specifically bad for 15-20 line range: 46.7% HR (N=30).
    """

    def _make_signal_results_for(self, pred, n_qualifying=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_starter_v12_under_blocked(self):
        """V12 UNDER + season_avg=17 is blocked."""
        pred = _make_prediction(
            recommendation='UNDER',
            points_avg_season=17,
            source_model_family='v12_mae',
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['starter_v12_under'] == 1

    def test_starter_v9_under_allowed(self):
        """V9 UNDER + season_avg=17 passes (only V12 is blocked)."""
        pred = _make_prediction(
            recommendation='UNDER',
            points_avg_season=17,
            source_model_family='v9_mae',
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['starter_v12_under'] == 0

    def test_starter_v12_over_allowed(self):
        """V12 OVER + season_avg=17 passes (only UNDER is blocked).

        Uses 5 signals to pass SC=3 OVER floor and starter OVER SC floor.
        """
        pred = _make_prediction(
            recommendation='OVER',
            points_avg_season=17,
            source_model_family='v12_mae',
        )
        signals = self._make_signal_results_for(pred, n_qualifying=5)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['starter_v12_under'] == 0

    def test_star_v12_under_not_affected(self):
        """V12 UNDER + season_avg=25 hits star block, not starter block."""
        pred = _make_prediction(
            recommendation='UNDER',
            points_avg_season=25,
            source_model_family='v12_mae',
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['star_under'] == 1
        assert summary['rejected']['starter_v12_under'] == 0


# ============================================================================
# PREMIUM SIGNAL EDGE FLOOR BYPASS TESTS (Session 355)
# ============================================================================

class TestPremiumSignalEdgeFloorBypass:
    """Test that combo_3way and combo_he_ms bypass the edge floor (Session 355).

    These signals have 95%+ HR, so filtering them by edge floor wastes profit.
    Uses UNDER to avoid OVER edge 5+ floor (Session 378).
    """

    def test_premium_signal_bypasses_edge_floor(self):
        """Pick with edge=2.0 UNDER + combo_3way signal bypasses edge floor."""
        pred = _make_prediction(edge=2.0, recommendation='UNDER', line_value=26.0)
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('model_health'),
            _make_signal_result('combo_3way'),
            _make_signal_result('high_edge'),
            _make_signal_result('rest_advantage_2d'),
            _make_signal_result('home_under'),
        ]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['edge_floor'] == 0

    def test_premium_combo_he_ms_bypasses_edge_floor(self):
        """Pick with edge=2.0 UNDER + combo_he_ms signal bypasses edge floor."""
        pred = _make_prediction(edge=2.0, recommendation='UNDER', line_value=26.0)
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('model_health'),
            _make_signal_result('combo_he_ms'),
            _make_signal_result('edge_spread_optimal'),
            _make_signal_result('rest_advantage_2d'),
            _make_signal_result('home_under'),
        ]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['edge_floor'] == 0

    def test_no_premium_signal_still_blocked(self):
        """Pick with edge=2.0 and no premium signals is still blocked."""
        pred = _make_prediction(edge=2.0)
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('model_health'),
            _make_signal_result('high_edge'),
            _make_signal_result('edge_spread_optimal'),
        ]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['edge_floor'] == 1


# ============================================================================
# STARTER OVER SC FLOOR TESTS (Session 382c)
# ============================================================================

class TestStarterOverScFloor:
    """Test that Starter OVER (line 15-25) requires SC >= 5 (Session 382c).

    Starter OVER collapsed from 90% Jan to 33.3% Feb (3-6). Full season 63.2% (N=19).
    SC >= 5 preserves high-confidence picks while filtering marginal SC 3-4 ones.
    """

    def _make_signal_results_for(self, pred, n_qualifying=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_starter_over_sc3_blocked(self):
        """OVER + line=18 + 3 signals → blocked by starter OVER SC floor.

        SC=3 OVER edge<7 filter may also fire first, but the pick is rejected.
        """
        pred = _make_prediction(
            recommendation='OVER',
            line_value=18.0,
            edge=8.0,  # edge >= 7 to avoid SC=3 OVER edge floor
        )
        signals = self._make_signal_results_for(pred, n_qualifying=4)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['starter_over_sc_floor'] == 1

    def test_starter_over_sc5_passes(self):
        """OVER + line=18 + 5 signals → passes starter OVER SC floor."""
        pred = _make_prediction(
            recommendation='OVER',
            line_value=18.0,
        )
        signals = self._make_signal_results_for(pred, n_qualifying=5)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['starter_over_sc_floor'] == 0

    def test_role_over_sc3_passes(self):
        """OVER + line=12 (role tier, not starter) + 4 signals → passes.

        Line < 15 is outside starter range, so starter_over_sc_floor does not apply.
        """
        pred = _make_prediction(
            recommendation='OVER',
            line_value=12.0,
            edge=8.0,  # edge >= 7 to avoid SC=3 OVER edge floor
        )
        signals = self._make_signal_results_for(pred, n_qualifying=4)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['starter_over_sc_floor'] == 0

    def test_starter_under_sc3_passes(self):
        """UNDER + line=18 + 4 signals → passes (only OVER restricted)."""
        pred = _make_prediction(
            recommendation='UNDER',
            line_value=18.0,
        )
        signals = self._make_signal_results_for(pred, n_qualifying=4)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['starter_over_sc_floor'] == 0

    def test_star_over_sc4_passes(self):
        """OVER + line=26 (star tier) + 4 signals → passes (line >= 25, not starter)."""
        pred = _make_prediction(
            recommendation='OVER',
            line_value=26.0,
            edge=8.0,
        )
        signals = self._make_signal_results_for(pred, n_qualifying=4)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['starter_over_sc_floor'] == 0

    def test_filter_counter_in_summary(self):
        """starter_over_sc_floor key always present in filter summary."""
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([], {})
        assert 'starter_over_sc_floor' in summary['rejected']
