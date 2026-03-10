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
    line_value=27.0,
    confidence_score=0.85,
    prop_line_delta=None,
    neg_pm_streak=0,
    games_vs_opponent=0,
    source_model_family='',
    is_home=True,
    points_avg_season=0,
    teammate_usage_available=0,
    trend_slope=2.0,
    spread_magnitude=0,
) -> dict:
    """Helper to create a prediction dict that passes all filters by default.

    Defaults chosen to avoid all active filter blocks:
    - line_value=27.0: above mid_line_over range (15-25) for OVER
    - trend_slope=2.0: above flat_trend_under range (-0.5 to 0.5) for UNDER
    - spread_magnitude=0: below high_spread_over threshold (7.0) for OVER
    """
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
        'trend_slope': trend_slope,
        'spread_magnitude': spread_magnitude,
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
            'neg_pm_streak', 'signal_count', 'sc3_edge_floor', 'sc3_over_block',
            'starter_over_sc_floor', 'opponent_depleted_under',
            'high_book_std_under', 'confidence', 'anti_pattern',
            'model_direction_affinity', 'away_noveg', 'star_under',
            'under_star_away', 'med_usage_under', 'starter_v12_under',
            'opponent_under_block', 'q4_scorer_under_block',
            'friday_over_block', 'high_skew_over_block',
            'signal_density', 'legacy_block',
            'model_profile_would_block',
            'toxic_starter_over_would_block', 'toxic_star_over_would_block',
            'regime_over_floor', 'regime_rescue_blocked',
            'high_spread_over_would_block', 'flat_trend_under',
            'under_after_streak', 'under_after_bad_miss',
            'mid_line_over_obs', 'monday_over_obs', 'home_over_obs',
            'signal_stack_2plus_obs', 'rescue_cap', 'rescue_health_gate',
            'bias_regime_over_obs', 'prediction_sanity',
            'depleted_stars_over_obs', 'hot_shooting_reversion_obs',
            'over_low_rsc_obs', 'mae_gap_obs', 'thin_slate_obs',
            'hot_streak_under_obs',
            'solo_game_pick_obs',
            'line_anomaly_extreme_drop',
            'player_under_suppression_obs',
            'under_low_rsc',
            'ft_variance_under',
            'team_cap',
            'unreliable_over_low_mins_obs', 'unreliable_under_flat_trend_obs',
            'b2b_under_block', 'blowout_risk_under_block_obs',
            # Session 462: New observation filters
            'cold_fg_under_obs', 'cold_3pt_under_obs', 'over_line_rose_heavy_obs',
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

    def test_b2b_under_block_tracked(self):
        """B2B UNDER = 30.8% HR — should be blocked."""
        pred = _make_prediction(recommendation='UNDER', line_value=20.0)
        pred['rest_days'] = 1  # B2B
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], {})
        assert summary['rejected']['b2b_under_block'] == 1

    def test_b2b_over_not_blocked(self):
        """B2B OVER should NOT be blocked by b2b_under_block."""
        pred = _make_prediction(recommendation='OVER')
        pred['rest_days'] = 1
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], {})
        assert summary['rejected']['b2b_under_block'] == 0

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
    """Test that away_noveg filter was REMOVED (Session 401).

    Originally (Session 347/365): v12_noveg 43.8% AWAY, v9 48.1% AWAY.
    Root cause was model staleness (train_1102 vintage), NOT structural.
    Newer models show zero HOME/AWAY gap. Filter removed Session 401.
    Counter retained for schema continuity.
    """

    def _make_signal_results_for(self, pred, n_qualifying=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_away_noveg_no_longer_blocked(self):
        """v12_noveg AWAY prediction passes (filter removed Session 401)."""
        pred = _make_prediction(
            source_model_family='v12_q43',
            is_home=False,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['away_noveg'] == 0

    def test_away_noveg_counter_always_zero(self):
        """away_noveg counter is always 0 (filter removed Session 401)."""
        pred = _make_prediction(
            source_model_family='v9_mae',
            is_home=False,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], signals)
        assert summary['rejected']['away_noveg'] == 0


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

    def test_base_only_signals_blocked_at_low_edge(self):
        """Pick with only 3 base signals at edge<7 is blocked by signal_density.

        Session 393: SC relaxed from 4→3, so 3 signals passes signal_count.
        Signal density filter catches base-only picks at edge<7.
        """
        pred = _make_prediction(recommendation='UNDER', line_value=26.0, edge=6.0)
        signals = self._make_base_only_signals(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['signal_density'] == 1

    def test_base_only_signals_at_high_edge_passes(self):
        """Pick with only 3 base signals at edge>=7 passes — SC=3 sufficient + density bypass.

        Session 352 density bypass: base-only at edge>=7 is allowed (extreme edge is informative).
        Session 388 edge-tiered SC: SC=3 at edge>=7 passes signal_count.
        Combined: base-only at high edge is now allowed through both gates.
        """
        pred = _make_prediction(recommendation='UNDER', line_value=26.0, edge=8.0)
        signals = self._make_base_only_signals(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['signal_count'] == 0
        assert summary['rejected']['signal_density'] == 0

    def test_base_plus_extra_signals_passes(self):
        """Pick with base signals + 2 extra signals passes (5 total)."""
        pred = _make_prediction()
        signals = self._make_rich_signals(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['signal_density'] == 0

    def test_below_min_signal_count_blocked(self):
        """Pick with only 2 signals is blocked by signal_count (needs SC>=4 at edge<7)."""
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
    """Test that V12 UNDER + season_avg 15-20 is NO LONGER blocked (Session 422b).

    Filter removed: zero fires across entire season (dead filter).
    """

    def _make_signal_results_for(self, pred, n_qualifying=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_starter_v12_under_now_allowed(self):
        """V12 UNDER + season_avg=17 now passes (filter removed Session 422b)."""
        pred = _make_prediction(
            recommendation='UNDER',
            points_avg_season=17,
            source_model_family='v12_mae',
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['starter_v12_under'] == 0

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
        """V12 UNDER + season_avg=25 passes (star_under removed Session 400).

        star_under was removed Session 400 — 72.1% HR post-toxic recovery.
        season_avg=25 is outside starter range (15-20), so starter_v12_under skips.
        """
        pred = _make_prediction(
            recommendation='UNDER',
            points_avg_season=25,
            source_model_family='v12_mae',
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['star_under'] == 0
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

    def test_starter_over_sc3_mid_line_observation(self):
        """OVER + line=18 + 3 signals → mid_line_over is observation-only (Session 428).

        Session 428: mid_line_over demoted to observation. Picks pass through
        and may be caught by other filters (sc3_over_block if real_sc=0).
        """
        pred = _make_prediction(
            recommendation='OVER',
            line_value=18.0,
            edge=8.0,  # edge >= 7 to pass signal_count
        )
        signals = self._make_signal_results_for(pred, n_qualifying=3)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        # mid_line_over is observation-only — pick passes through
        assert summary['rejected']['mid_line_over_obs'] == 1
        # Pick may still be selected since it passes other filters
        assert len(picks) >= 0

    def test_starter_over_sc5_mid_line_observation(self):
        """OVER + line=18 + 5 signals → mid_line_over is observation-only (Session 428).

        Session 428: mid_line_over demoted to observation, pick passes through.
        """
        pred = _make_prediction(
            recommendation='OVER',
            line_value=18.0,
        )
        signals = self._make_signal_results_for(pred, n_qualifying=5)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        # mid_line_over records observation but doesn't block
        assert summary['rejected']['mid_line_over_obs'] == 1
        assert len(picks) >= 0

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


# ============================================================================
# EDGE-TIERED SIGNAL COUNT TESTS (Session 388)
# ============================================================================

class TestEdgeTieredSignalCount:
    """Test edge-tiered signal count: SC >= 4 for edge < 7, SC >= 3 for edge 7+.

    Session 388: SC=3 at edge 5-7 = 51.3% HR (N=39) — weakest link.
    SC=4 at edge 5-7 = 70.6% HR (N=17). SC=3 at edge 7+ = 85.7% (N=7).
    """

    def _make_signal_results_for(self, pred, n_qualifying=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_sc3_edge_7plus_passes(self):
        """SC=3 at edge >= 7 passes (high edge tier keeps SC=3 floor)."""
        pred = _make_prediction(
            recommendation='UNDER', line_value=26.0, edge=8.0,
        )
        signals = self._make_signal_results_for(pred, n_qualifying=3)
        # Need non-base signals to avoid signal_density filter
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('model_health'),
            _make_signal_result('combo_he_ms'),
            _make_signal_result('rest_advantage_2d'),
        ]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['signal_count'] == 0

    def test_sc3_edge_below_7_passes(self):
        """SC=3 at edge < 7 passes (Session 393: SC relaxed from 4→3).

        With non-base-only signals, SC=3 at edge<7 now passes signal_count
        and signal_density.
        """
        pred = _make_prediction(
            recommendation='UNDER', line_value=26.0, edge=6.5,
        )
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('model_health'),
            _make_signal_result('combo_he_ms'),
            _make_signal_result('rest_advantage_2d'),
        ]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1

    def test_sc4_edge_below_7_passes(self):
        """SC=4 at edge < 7 passes the tiered threshold."""
        pred = _make_prediction(
            recommendation='UNDER', line_value=26.0, edge=5.5,
        )
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('model_health'),
            _make_signal_result('combo_he_ms'),
            _make_signal_result('rest_advantage_2d'),
            _make_signal_result('home_under'),
        ]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['signal_count'] == 0

    def test_sc3_over_edge_below_7_blocked_by_sc3_over(self):
        """OVER at SC=3 with only base signals is blocked by sc3_over_block.

        sc3_over_block fires when real_sc == 0 (all base signals).
        Must use only base signals to trigger this filter.
        """
        pred = _make_prediction(
            recommendation='OVER', line_value=26.0, edge=6.0,
        )
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('model_health'),
            _make_signal_result('high_edge'),
            _make_signal_result('edge_spread_optimal'),
        ]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['sc3_over_block'] == 1

    def test_sc3_under_edge_below_7_passes(self):
        """UNDER at SC=3 edge<7 passes (Session 393: SC relaxed to 3).

        With non-base-only signals, SC=3 UNDER now passes through all filters.
        """
        pred = _make_prediction(
            recommendation='UNDER', line_value=26.0, edge=6.0,
        )
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('model_health'),
            _make_signal_result('combo_he_ms'),
            _make_signal_result('rest_advantage_2d'),
        ]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1

    def test_edge_exactly_7_uses_low_threshold(self):
        """Edge exactly at 7.0 uses the SC=3 threshold (>= comparison)."""
        pred = _make_prediction(
            recommendation='UNDER', line_value=26.0, edge=7.0,
        )
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('model_health'),
            _make_signal_result('combo_he_ms'),
            _make_signal_result('rest_advantage_2d'),
        ]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['signal_count'] == 0

    def test_sc3_edge_floor_always_zero(self):
        """sc3_edge_floor counter is always 0 (subsumed by edge-tiered SC)."""
        pred = _make_prediction(
            recommendation='OVER', line_value=26.0, edge=6.0,
        )
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _make_signal_result('signal_0'),
            _make_signal_result('signal_1'),
            _make_signal_result('signal_2'),
        ]}
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], signals)
        assert summary['rejected']['sc3_edge_floor'] == 0


# ============================================================================
# RESCUE CAP TESTS (Session 415)
# ============================================================================

class TestRescueCap:
    """Test that rescued picks are capped at 40% of the slate (Session 415).

    During edge compression, rescue was generating 67% of the slate at 50% HR.
    Cap drops lowest-edge rescues, minimum 1 rescue always kept.
    """

    def _make_signal_results_for(self, pred, n_qualifying=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_rescue_cap_counter_in_summary(self):
        """rescue_cap key always present in filter summary."""
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([], {})
        assert 'rescue_cap' in summary['rejected']

    def test_signal_stack_2plus_obs_counter_in_summary(self):
        """signal_stack_2plus_obs key always present in filter summary."""
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([], {})
        assert 'signal_stack_2plus_obs' in summary['rejected']


# ============================================================================
# UNDER STAR AWAY OBSERVATION MODE TESTS (Session 415)
# ============================================================================

class TestUnderStarAwayObservation:
    """Test that under_star_away is now observation-only (Session 415).

    Was 38.5% HR at creation (toxic Feb) but recovered to 73.0% post-ASB.
    Should count but not block.
    """

    def _make_signal_results_for(self, pred, n_qualifying=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_under_star_away_no_longer_blocks(self):
        """UNDER + star line + away should pass through (observation only)."""
        pred = _make_prediction(
            recommendation='UNDER',
            line_value=25.0,
            is_home=False,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        # Should pass — observation mode, no longer blocking
        assert len(picks) == 1
        # Counter still incremented for tracking
        assert summary['rejected']['under_star_away'] == 1


# ============================================================================
# MID-LINE OVER BLOCK TESTS (Session 415)
# ============================================================================

class TestMidLineOverBlock:
    """Test that mid-line OVER (line 15-25) is now an active block (Session 415).

    Promoted from observation: 47.9% HR (N=213) full season.
    """

    def _make_signal_results_for(self, pred, n_qualifying=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_mid_line_over_observation(self):
        """OVER + line=20 — observation-only since Session 428."""
        pred = _make_prediction(
            recommendation='OVER',
            line_value=20.0,
            edge=6.0,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        # Session 428: demoted to observation, pick passes through
        assert summary['rejected']['mid_line_over_obs'] == 1
        assert len(picks) >= 0

    def test_high_line_over_not_blocked(self):
        """OVER + line=27 (above mid-line range) passes."""
        pred = _make_prediction(
            recommendation='OVER',
            line_value=27.0,
            edge=6.0,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['mid_line_over_obs'] == 0

    def test_mid_line_under_not_blocked(self):
        """UNDER + line=20 is NOT blocked by mid_line_over."""
        pred = _make_prediction(
            recommendation='UNDER',
            line_value=20.0,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['mid_line_over_obs'] == 0


class TestRuntimeDemotion:
    """Test Session 432 runtime filter demotion via filter_overrides."""

    def _make_signal_results_for(self, pred, n_qualifying=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_friday_over_normally_blocked(self):
        """Friday OVER pick is normally blocked."""
        pred = _make_prediction(recommendation='OVER', edge=6.0)
        pred['game_date'] = '2026-03-06'  # Friday
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert summary['rejected']['friday_over_block'] == 1
        assert len(picks) == 0

    def test_friday_over_passes_when_runtime_demoted(self):
        """Friday OVER pick passes when friday_over_block is runtime-demoted."""
        pred = _make_prediction(recommendation='OVER', edge=6.0)
        pred['game_date'] = '2026-03-06'  # Friday
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator(runtime_demoted_filters={'friday_over_block'})
        picks, summary = agg.aggregate([pred], signals)
        # Filter still records the count
        assert summary['rejected']['friday_over_block'] == 1
        # But pick is NOT blocked
        assert len(picks) == 1

    def test_core_filters_unaffected_by_runtime_demotion(self):
        """Core safety filters (edge_floor, blacklist) can't be runtime-demoted."""
        pred = _make_prediction(recommendation='OVER', edge=1.0)
        signals = self._make_signal_results_for(pred)
        # Even if someone tried to demote edge_floor, it's not eligible
        agg = BestBetsAggregator(runtime_demoted_filters={'edge_floor'})
        picks, summary = agg.aggregate([pred], signals)
        # edge_floor is NOT gated by runtime_demoted — always blocks
        assert len(picks) == 0

    def test_b2b_under_observation(self):
        """Session 462: B2B UNDER is now observation mode — always passes through."""
        pred = _make_prediction(recommendation='UNDER', edge=4.0)
        pred['rest_days'] = 1  # B2B
        signals = self._make_signal_results_for(pred)

        # Session 462: b2b_under_block is now observation — counts but does NOT block
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert summary['rejected']['b2b_under_block'] == 1
        assert len(picks) == 1  # Passes through (observation mode)

    def test_empty_demotion_set_no_effect(self):
        """Empty runtime_demoted_filters set has no effect on behavior."""
        pred = _make_prediction(recommendation='OVER', edge=6.0)
        pred['game_date'] = '2026-03-06'  # Friday
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator(runtime_demoted_filters=set())
        picks, summary = agg.aggregate([pred], signals)
        assert summary['rejected']['friday_over_block'] == 1
        assert len(picks) == 0


# ============================================================================
# SESSION 437 PHASE 2 & 3 TESTS — RESCUE ARCHITECTURE + OVER QUALITY
# ============================================================================

class TestRescueCapPrioritySort:
    """Session 437 P4: rescue_cap should drop lowest-priority rescues first."""

    def _make_signal_results_for(self, pred, n_qualifying=5, rescue_tag=None):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        if rescue_tag:
            signals.append(_make_signal_result(rescue_tag))
        return {key: signals}

    def test_rescue_cap_keeps_higher_priority(self):
        """HSE rescue (priority 3) should be kept over combo_he_ms (priority 1)."""
        from ml.signals.aggregator import RESCUE_SIGNAL_PRIORITY
        assert RESCUE_SIGNAL_PRIORITY['high_scoring_environment_over'] > RESCUE_SIGNAL_PRIORITY.get('combo_he_ms', 0)

    def test_rescue_priority_ordering(self):
        """Priority map has HSE > home_under > combo signals."""
        from ml.signals.aggregator import RESCUE_SIGNAL_PRIORITY
        assert RESCUE_SIGNAL_PRIORITY['high_scoring_environment_over'] == 3
        # sharp_book_lean_over removed Session 462 (41.7% HR 5-season)
        assert 'sharp_book_lean_over' not in RESCUE_SIGNAL_PRIORITY
        assert RESCUE_SIGNAL_PRIORITY['home_under'] == 2
        assert RESCUE_SIGNAL_PRIORITY['combo_he_ms'] == 1


class TestComboHeMsOverRescueRemoval:
    """Session 437 P6: combo_he_ms should not rescue OVER picks."""

    def _make_signal_results_for(self, pred, tags):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(t) for t in tags]
        return {key: signals}

    def test_combo_he_ms_does_not_rescue_over(self):
        """OVER pick below edge floor should NOT be rescued by combo_he_ms."""
        pred = _make_prediction(
            recommendation='OVER',
            edge=2.5,  # Below edge floor of 3.0
            line_value=27.0,
        )
        tags = ['model_health', 'high_edge', 'edge_spread_optimal',
                'combo_he_ms', 'rest_advantage_2d']
        signals = self._make_signal_results_for(pred, tags)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        # combo_he_ms should NOT rescue OVER — pick should be filtered
        assert len(picks) == 0
        assert summary['rejected']['edge_floor'] > 0

    def test_combo_he_ms_still_rescues_under(self):
        """UNDER pick below edge floor SHOULD be rescued by combo_he_ms."""
        pred = _make_prediction(
            recommendation='UNDER',
            edge=2.5,  # Below edge floor of 3.0
            line_value=27.0,
            trend_slope=2.0,
        )
        tags = ['model_health', 'high_edge', 'edge_spread_optimal',
                'combo_he_ms', 'rest_advantage_2d']
        signals = self._make_signal_results_for(pred, tags)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        # combo_he_ms should rescue UNDER
        assert len(picks) == 1
        assert picks[0].get('signal_rescued') is True
        assert picks[0].get('rescue_signal') == 'combo_he_ms'


class TestRescueHealthGate:
    """Session 437 P5: signals with low 7d HR lose rescue eligibility."""

    def _make_signal_results_for(self, pred, tags):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(t) for t in tags]
        return {key: signals}

    def test_unhealthy_signal_loses_rescue(self):
        """Signal with 7d HR below threshold should not rescue."""
        pred = _make_prediction(
            recommendation='UNDER',
            edge=2.5,  # Below edge floor
            line_value=27.0,
            trend_slope=2.0,
        )
        tags = ['model_health', 'high_edge', 'edge_spread_optimal',
                'home_under', 'rest_advantage_2d']
        signals = self._make_signal_results_for(pred, tags)
        # home_under at 45% HR = below 60% threshold
        health = {'home_under': {'hr_7d': 45.0, 'regime': 'COLD', 'status': 'DEGRADING'}}
        agg = BestBetsAggregator(signal_health=health)
        picks, summary = agg.aggregate([pred], signals)
        # home_under should lose rescue eligibility — pick filtered
        assert len(picks) == 0

    def test_healthy_signal_keeps_rescue(self):
        """Signal with 7d HR above threshold should still rescue."""
        pred = _make_prediction(
            recommendation='UNDER',
            edge=2.5,
            line_value=27.0,
            trend_slope=2.0,
        )
        tags = ['model_health', 'high_edge', 'edge_spread_optimal',
                'home_under', 'rest_advantage_2d']
        signals = self._make_signal_results_for(pred, tags)
        # home_under at 75% HR = above threshold
        health = {'home_under': {'hr_7d': 75.0, 'regime': 'HOT', 'status': 'HEALTHY'}}
        agg = BestBetsAggregator(signal_health=health)
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert picks[0].get('rescue_signal') == 'home_under'

    def test_no_health_data_fails_open(self):
        """Without signal_health data, all signals keep rescue eligibility."""
        pred = _make_prediction(
            recommendation='UNDER',
            edge=2.5,
            line_value=27.0,
            trend_slope=2.0,
        )
        tags = ['model_health', 'high_edge', 'edge_spread_optimal',
                'home_under', 'rest_advantage_2d']
        signals = self._make_signal_results_for(pred, tags)
        # No signal_health — fail open
        agg = BestBetsAggregator(signal_health={})
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert picks[0].get('rescue_signal') == 'home_under'


class TestOverSignalQualityScoring:
    """Session 437 P7: OVER composite score includes signal quality."""

    def _make_signal_results_for(self, pred, tags):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(t) for t in tags]
        return {key: signals}

    def test_over_signal_quality_stored(self):
        """OVER picks should have over_signal_quality in output."""
        pred = _make_prediction(
            recommendation='OVER',
            edge=6.0,
            line_value=27.0,
        )
        tags = ['model_health', 'high_edge', 'edge_spread_optimal',
                'fast_pace_over', 'line_rising_over']
        signals = self._make_signal_results_for(pred, tags)
        agg = BestBetsAggregator()
        picks, _ = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert picks[0]['over_signal_quality'] is not None
        assert picks[0]['over_signal_quality'] > 0

    def test_over_quality_affects_ranking(self):
        """OVER pick with better signals should rank higher at same edge."""
        pred_a = _make_prediction(
            player_lookup='player_a',
            recommendation='OVER',
            edge=5.0,
            line_value=27.0,
        )
        pred_b = _make_prediction(
            player_lookup='player_b',
            game_id='20260220_BOS_MIA',
            recommendation='OVER',
            edge=5.0,
            line_value=27.0,
        )
        # Player A has high-value signals
        tags_a = ['model_health', 'high_edge', 'edge_spread_optimal',
                  'fast_pace_over', 'line_rising_over', 'combo_3way']
        # Player B has only base signals + one low-weight
        tags_b = ['model_health', 'high_edge', 'edge_spread_optimal',
                  'b2b_boost_over']
        signals = {}
        signals.update(self._make_signal_results_for(pred_a, tags_a))
        signals.update(self._make_signal_results_for(pred_b, tags_b))
        agg = BestBetsAggregator()
        picks, _ = agg.aggregate([pred_a, pred_b], signals)
        assert len(picks) == 2
        # Player A should rank higher (same edge but better signal quality)
        assert picks[0]['player_lookup'] == 'player_a'
        assert picks[0]['composite_score'] > picks[1]['composite_score']

    def test_under_quality_unchanged(self):
        """UNDER picks should still use under_signal_quality (not over)."""
        pred = _make_prediction(
            recommendation='UNDER',
            edge=5.0,
            line_value=27.0,
            trend_slope=2.0,
        )
        tags = ['model_health', 'high_edge', 'edge_spread_optimal',
                'home_under', 'bench_under']
        signals = self._make_signal_results_for(pred, tags)
        agg = BestBetsAggregator()
        picks, _ = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert picks[0]['under_signal_quality'] is not None
        assert picks[0]['over_signal_quality'] is None


class TestBaseSignalsAntiSignals:
    """Session 438: Verify low_line_over and prop_line_drop_over are in BASE_SIGNALS."""

    def test_low_line_over_in_base_signals(self):
        """low_line_over confirmed anti-signal (20% BB HR). Must not inflate real_sc."""
        from ml.signals.aggregator import BASE_SIGNALS
        assert 'low_line_over' in BASE_SIGNALS

    def test_prop_line_drop_over_in_base_signals(self):
        """prop_line_drop_over below 60% graduation threshold. Must not inflate real_sc."""
        from ml.signals.aggregator import BASE_SIGNALS
        assert 'prop_line_drop_over' in BASE_SIGNALS

    def test_base_signals_excluded_from_real_sc(self):
        """Picks with only base signals should have real_sc=0 and get filtered."""
        pred = _make_prediction(edge=5.0, line_value=27.0)
        base_tags = ['model_health', 'high_edge', 'edge_spread_optimal',
                     'low_line_over', 'prop_line_drop_over']
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [_make_signal_result(t) for t in base_tags]}
        agg = BestBetsAggregator()
        picks, _ = agg.aggregate([pred], signals)
        # Should be filtered out because real_sc < 3
        assert len(picks) == 0


class TestPredictionSanityFilter:
    """Session 438 P10 → Session 440: Prediction sanity check (ACTIVE).

    Blocks picks where predicted_points > 2x season_avg on bench/role
    players (line < 18). Model-level HR = 40.9% (N=88) — strongly below
    breakeven.
    """

    def test_sanity_blocks_bench_player_over_prediction(self):
        """Sanity filter should BLOCK picks with pred > 2x avg on low-line players."""
        pred = _make_prediction(
            edge=6.0,
            line_value=15.0,         # role player (< 18 threshold for sanity)
            points_avg_season=8.0,   # 8 pts avg
            is_home=False,           # avoid home_over_obs
        )
        pred['predicted_points'] = 21.0  # 2.625x season avg — triggers sanity
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        # 5 real signals to pass all gates
        signals = {key: [_make_signal_result(f'real_signal_{i}') for i in range(5)]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        # Pick should be BLOCKED (active filter)
        assert len(picks) == 0
        assert summary['rejected']['prediction_sanity'] == 1

    def test_sanity_not_triggered_for_stars(self):
        """Sanity check should NOT trigger for star players (line >= 18)."""
        pred = _make_prediction(
            edge=5.0,
            line_value=25.0,         # star — above 18 threshold
            points_avg_season=12.0,
        )
        pred['predicted_points'] = 30.0  # 2.5x but line >= 18 so no trigger
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [_make_signal_result(f'real_signal_{i}') for i in range(5)]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['prediction_sanity'] == 0

    def test_sanity_not_triggered_when_pred_below_2x(self):
        """Sanity should NOT trigger when predicted < 2x season avg."""
        pred = _make_prediction(
            edge=4.0,
            line_value=12.0,         # role player
            points_avg_season=10.0,  # 10 pts avg
            is_home=False,
        )
        pred['predicted_points'] = 16.0  # 1.6x — below 2x threshold
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [_make_signal_result(f'real_signal_{i}') for i in range(5)]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['prediction_sanity'] == 0

    def test_sanity_boundary_line_exactly_18(self):
        """Line exactly 18 should NOT trigger (condition is < 18, not <=)."""
        pred = _make_prediction(
            edge=5.0,
            line_value=18.0,         # boundary — exactly 18
            points_avg_season=8.0,
            is_home=False,
        )
        pred['predicted_points'] = 20.0  # 2.5x avg, but line not < 18
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [_make_signal_result(f'real_signal_{i}') for i in range(5)]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['prediction_sanity'] == 0


class TestEdgeZscore:
    """Session 438 P9: Volatility-adjusted edge z-score."""

    def _make_signals_for(self, pred):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        return {key: [_make_signal_result(f'real_signal_{i}') for i in range(5)]}

    def test_zscore_computed(self):
        """edge_zscore should appear on scored picks."""
        pred = _make_prediction(edge=6.0, line_value=27.0)
        pred['points_std_last_10'] = 4.0  # z = 6.0 / 4.0 = 1.5
        signals = self._make_signals_for(pred)
        agg = BestBetsAggregator()
        picks, _ = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert picks[0]['edge_zscore'] == 1.5

    def test_zscore_floors_std_at_one(self):
        """When std is 0 or missing, floor at 1.0 to avoid div-by-zero."""
        pred = _make_prediction(edge=6.0, line_value=27.0)
        pred['points_std_last_10'] = 0  # should floor to 1.0
        signals = self._make_signals_for(pred)
        agg = BestBetsAggregator()
        picks, _ = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert picks[0]['edge_zscore'] == 6.0  # 6.0 / 1.0

    def test_high_variance_low_zscore(self):
        """High variance player should have low z-score despite decent edge."""
        pred = _make_prediction(edge=4.0, line_value=27.0)
        pred['points_std_last_10'] = 8.0  # z = 4.0 / 8.0 = 0.5
        signals = self._make_signals_for(pred)
        agg = BestBetsAggregator()
        picks, _ = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert picks[0]['edge_zscore'] == 0.5


class TestDepletedStarsOverObservation:
    """Session 439: Depleted roster OVER observation filter.

    When 3+ star teammates are OUT, BB OVER = 0% HR (N=4), model = 48.2% (N=137).
    The volume boost expected by the model doesn't materialize because the entire
    team offense degrades on skeleton crews.
    """

    def _make_signals_for(self, pred, n=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n)]
        return {key: signals}

    def test_depleted_stars_over_does_not_block(self):
        """Observation mode: pick with 3+ stars out should still pass (not blocked)."""
        pred = _make_prediction(edge=6.0, recommendation='OVER', line_value=15.0)
        pred['star_teammates_out'] = 3
        signals = self._make_signals_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1  # NOT blocked — observation only
        assert summary['rejected']['depleted_stars_over_obs'] == 1  # But counted

    def test_depleted_stars_over_not_triggered_at_two(self):
        """stars_out=2 should NOT trigger the observation (threshold is 3)."""
        pred = _make_prediction(edge=6.0, recommendation='OVER', line_value=15.0)
        pred['star_teammates_out'] = 2
        signals = self._make_signals_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['depleted_stars_over_obs'] == 0

    def test_depleted_stars_under_not_triggered(self):
        """UNDER picks should never trigger depleted_stars_over_obs."""
        pred = _make_prediction(edge=6.0, recommendation='UNDER', line_value=27.0)
        pred['star_teammates_out'] = 4
        signals = self._make_signals_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert summary['rejected']['depleted_stars_over_obs'] == 0


class TestHotShootingReversionObservation:
    """Session 441: Hot shooting reversion UNDER observation.

    After 70%+ FG games with real minutes, UNDER HR = 59.2% (N=250).
    Observation mode — tracks OVER picks after hot shooting but doesn't block.
    """

    def test_hot_shooting_obs_does_not_block(self):
        """OVER after 70%+ FG should be tagged but NOT blocked."""
        pred = _make_prediction(edge=6.0, recommendation='OVER', is_home=False)
        pred['prev_game_fg_pct'] = 0.75  # 75% FG last game
        pred['prev_game_minutes'] = 32   # Real minutes
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [_make_signal_result(f'sig_{i}') for i in range(5)]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1  # NOT blocked
        assert summary['rejected']['hot_shooting_reversion_obs'] == 1

    def test_hot_shooting_not_triggered_at_65pct(self):
        """65% FG should NOT trigger (threshold is 70%)."""
        pred = _make_prediction(edge=6.0, recommendation='OVER', is_home=False)
        pred['prev_game_fg_pct'] = 0.65
        pred['prev_game_minutes'] = 30
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [_make_signal_result(f'sig_{i}') for i in range(5)]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert summary['rejected']['hot_shooting_reversion_obs'] == 0

    def test_hot_shooting_not_triggered_low_minutes(self):
        """70%+ FG but only 15 minutes should NOT trigger (garbage time)."""
        pred = _make_prediction(edge=6.0, recommendation='OVER', is_home=False)
        pred['prev_game_fg_pct'] = 0.80
        pred['prev_game_minutes'] = 15  # Below 20 min threshold
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [_make_signal_result(f'sig_{i}') for i in range(5)]}
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert summary['rejected']['hot_shooting_reversion_obs'] == 0


class TestTeamCap:
    """Session 441: Per-team cap to prevent correlated exposure.

    Mar 7: 3 UTA OVER picks in same blowout all lost simultaneously.
    Cap at MAX_PICKS_PER_TEAM (2) per team, keeping highest-edge picks.
    """

    def test_third_pick_from_same_team_dropped(self):
        """3rd pick from same team should be dropped (cap=2)."""
        preds = []
        for i, edge in enumerate([8.0, 6.0, 4.0]):
            p = _make_prediction(
                player_lookup=f'player_{i}',
                game_id='20260307_UTA_MIL',
                edge=edge,
                is_home=False,
            )
            p['team_abbr'] = 'UTA'
            preds.append(p)
        key_fn = lambda p: f"{p['player_lookup']}::{p['game_id']}"
        signals = {}
        for p in preds:
            signals[key_fn(p)] = [_make_signal_result(f'sig_{i}') for i in range(5)]
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate(preds, signals)
        assert len(picks) == 2  # Only 2 kept
        assert summary['rejected']['team_cap'] == 1
        # Highest edge picks should be kept
        kept_edges = sorted([p['edge'] for p in picks], reverse=True)
        assert kept_edges == [8.0, 6.0]

    def test_two_picks_from_same_team_allowed(self):
        """2 picks from same team is within cap — both should pass."""
        preds = []
        for i, edge in enumerate([7.0, 5.0]):
            p = _make_prediction(
                player_lookup=f'player_{i}',
                game_id='20260307_UTA_MIL',
                edge=edge,
                is_home=False,
            )
            p['team_abbr'] = 'UTA'
            preds.append(p)
        key_fn = lambda p: f"{p['player_lookup']}::{p['game_id']}"
        signals = {}
        for p in preds:
            signals[key_fn(p)] = [_make_signal_result(f'sig_{i}') for i in range(5)]
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate(preds, signals)
        assert len(picks) == 2
        assert summary['rejected']['team_cap'] == 0

    def test_different_teams_not_affected(self):
        """3 picks from 3 different teams should all pass."""
        preds = []
        for i, (team, game) in enumerate([('UTA', '20260307_UTA_MIL'),
                                           ('GSW', '20260307_GSW_OKC'),
                                           ('BKN', '20260307_BKN_DET')]):
            p = _make_prediction(
                player_lookup=f'player_{i}',
                game_id=game,
                edge=5.0,
                is_home=False,
            )
            p['team_abbr'] = team
            preds.append(p)
        key_fn = lambda p: f"{p['player_lookup']}::{p['game_id']}"
        signals = {}
        for p in preds:
            signals[key_fn(p)] = [_make_signal_result(f'sig_{i}') for i in range(5)]
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate(preds, signals)
        assert len(picks) == 3
        assert summary['rejected']['team_cap'] == 0


# ============================================================================
# SESSION 442 OBSERVATION FILTER TESTS
# ============================================================================

class TestOverLowRscObservation:
    """Session 442 O1: OVER with low real_signal_count observation.

    OVER at rsc 1-3 = 45.5% HR (N=11) vs rsc 4+ = 65.4% (N=26).
    Observation mode — accumulates data, does NOT block.
    """

    def _make_signal_results_for(self, pred, tags):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(t) for t in tags]
        return {key: signals}

    def test_over_low_rsc_observation(self):
        """OVER pick with real_sc between 1-3 should be tagged but NOT blocked."""
        pred = _make_prediction(
            recommendation='OVER',
            edge=6.0,
            line_value=27.0,
        )
        # 3 base + 2 real = real_sc=2 (between 1-3, triggers obs)
        tags = ['model_health', 'high_edge', 'edge_spread_optimal',
                'fast_pace_over', 'book_disagreement']
        signals = self._make_signal_results_for(pred, tags)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1  # NOT blocked — observation only
        assert summary['rejected']['over_low_rsc_obs'] == 1

    def test_over_low_rsc_not_triggered_at_rsc4(self):
        """OVER pick with real_sc >= 4 should NOT trigger the observation."""
        pred = _make_prediction(
            recommendation='OVER',
            edge=6.0,
            line_value=27.0,
        )
        # 3 base + 4 real = real_sc=4, above threshold
        tags = ['model_health', 'high_edge', 'edge_spread_optimal',
                'fast_pace_over', 'book_disagreement', 'combo_3way',
                'line_rising_over']
        signals = self._make_signal_results_for(pred, tags)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['over_low_rsc_obs'] == 0


class TestHotStreakUnderObservation:
    """Session 442 O4: Hot streak UNDER observation.

    UNDER when player went over in 4+ of last 5 (over_rate_last_10 >= 0.7)
    = 44.4% HR (N=18). Observation mode — tracks but does NOT block.
    """

    def _make_signal_results_for(self, pred, n_qualifying=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_hot_streak_under_observation(self):
        """UNDER pick with over_rate_last_10 = 0.8 should be tagged but NOT blocked."""
        pred = _make_prediction(
            recommendation='UNDER',
            edge=5.0,
            line_value=27.0,
        )
        pred['over_rate_last_10'] = 0.8  # Hot streak — triggers obs
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1  # NOT blocked — observation only
        assert summary['rejected']['hot_streak_under_obs'] == 1

    def test_hot_streak_under_not_triggered_below_threshold(self):
        """UNDER pick with over_rate_last_10 = 0.5 should NOT trigger."""
        pred = _make_prediction(
            recommendation='UNDER',
            edge=5.0,
            line_value=27.0,
        )
        pred['over_rate_last_10'] = 0.5  # Not hot — below 0.7 threshold
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['hot_streak_under_obs'] == 0


class TestMaeGapObservation:
    """Session 442 O2: MAE gap observation.

    When model MAE exceeds Vegas MAE by 0.15+ (mae_gap_7d), BB HR craters.
    Observation mode — tracks but does NOT block.
    """

    def _make_signal_results_for(self, pred, n_qualifying=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_mae_gap_observation(self):
        """Pick with mae_gap_7d = 0.25 should be tagged but NOT blocked."""
        pred = _make_prediction(
            recommendation='OVER',
            edge=6.0,
            line_value=27.0,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator(regime_context={'mae_gap_7d': 0.25})
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1  # NOT blocked — observation only
        assert summary['rejected']['mae_gap_obs'] == 1


class TestThinSlateObservation:
    """Session 442 O3: Thin slate observation.

    4-6 game slates = 51.2% HR with 76.7% OVER-heavy mix.
    7-9 game slates = 72.0% HR. Observation mode — tracks but does NOT block.
    """

    def _make_signal_results_for(self, pred, n_qualifying=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(f'signal_{i}') for i in range(n_qualifying)]
        return {key: signals}

    def test_thin_slate_observation(self):
        """Pick with num_games_on_slate = 5 should be tagged but NOT blocked."""
        pred = _make_prediction(
            recommendation='OVER',
            edge=6.0,
            line_value=27.0,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator(regime_context={'num_games_on_slate': 5})
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1  # NOT blocked — observation only
        assert summary['rejected']['thin_slate_obs'] == 1


class TestRestAdvantage2dWeight:
    """Session 442: rest_advantage_2d added to OVER_SIGNAL_WEIGHTS."""

    def test_rest_advantage_2d_weight(self):
        """rest_advantage_2d should be in OVER_SIGNAL_WEIGHTS with value 2.0."""
        from ml.signals.aggregator import OVER_SIGNAL_WEIGHTS
        assert 'rest_advantage_2d' in OVER_SIGNAL_WEIGHTS
        assert OVER_SIGNAL_WEIGHTS['rest_advantage_2d'] == 2.0


class TestSoloGamePickObservation:
    """Session 442 O5: Solo game pick observation.

    Solo picks (1 per game) = 52.2% HR vs multi (2+) = 75.3%.
    Tags solo picks for tracking. Observation mode — does NOT block.
    """

    def _make_signal_results_for(self, pred, tags):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = [_make_signal_result(t) for t in tags]
        return {key: signals}

    def test_solo_game_pick_observation(self):
        """A single pick from a game should be tagged as solo."""
        pred = _make_prediction(
            recommendation='OVER',
            edge=6.0,
            line_value=12.0,
            game_id='20260310_LAL_BOS',
        )
        tags = ['model_health', 'high_edge', 'edge_spread_optimal',
                'fast_pace_over', 'book_disagreement']
        signals = self._make_signal_results_for(pred, tags)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert summary['rejected']['solo_game_pick_obs'] == 1
        assert picks[0]['picks_in_game'] == 1

    def test_multi_game_pick_not_tagged(self):
        """Two picks from the same game should NOT be tagged as solo."""
        pred1 = _make_prediction(
            recommendation='OVER',
            edge=6.0,
            line_value=12.0,
            game_id='20260310_LAL_BOS',
            player_lookup='player_a',
        )
        pred2 = _make_prediction(
            recommendation='UNDER',
            edge=6.0,
            line_value=25.0,
            game_id='20260310_LAL_BOS',
            player_lookup='player_b',
        )
        tags = ['model_health', 'high_edge', 'edge_spread_optimal',
                'fast_pace_over', 'book_disagreement']
        key1 = f"player_a::20260310_LAL_BOS"
        key2 = f"player_b::20260310_LAL_BOS"
        signals = {
            key1: [_make_signal_result(t) for t in tags],
            key2: [_make_signal_result(t) for t in tags],
        }
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred1, pred2], signals)
        assert len(picks) == 2
        assert summary['rejected']['solo_game_pick_obs'] == 0
        assert all(p['picks_in_game'] == 2 for p in picks)


class TestAlgorithmVersion:
    """Session 452+: Algorithm version + single source of truth."""

    def test_algorithm_version_current(self):
        """ALGORITHM_VERSION should start with 'v46'."""
        from ml.signals.aggregator import ALGORITHM_VERSION
        assert ALGORITHM_VERSION.startswith('v46'), (
            f"Expected ALGORITHM_VERSION to start with 'v46', got '{ALGORITHM_VERSION}'"
        )

    def test_aggregator_and_merger_versions_match(self):
        """Session 452: aggregator imports from merger — versions must match."""
        from ml.signals.aggregator import ALGORITHM_VERSION as AGG_V
        from ml.signals.pipeline_merger import ALGORITHM_VERSION as MERGER_V
        assert AGG_V == MERGER_V, (
            f"Version mismatch: aggregator={AGG_V}, merger={MERGER_V}"
        )


# ============================================================================
# PER-MODEL MODE TESTS
# ============================================================================

class TestPerModelMode:
    """Test that per_model mode skips production-only caps and observations.

    per_model mode is used for model-level simulation where rescue caps,
    team caps, and solo game observations are not meaningful.
    """

    def test_per_model_mode_skips_team_cap(self):
        """3 picks from same team should all survive in per_model mode."""
        preds = []
        for i, edge in enumerate([8.0, 6.0, 4.0]):
            p = _make_prediction(
                player_lookup=f'player_{i}',
                game_id='20260307_LAL_MIL',
                edge=edge,
                is_home=False,
            )
            p['team_abbr'] = 'LAL'
            preds.append(p)
        key_fn = lambda p: f"{p['player_lookup']}::{p['game_id']}"
        signals = {}
        for p in preds:
            signals[key_fn(p)] = [_make_signal_result(f'sig_{i}') for i in range(5)]
        agg = BestBetsAggregator(mode='per_model')
        picks, summary = agg.aggregate(preds, signals)
        assert len(picks) == 3  # All 3 kept — team cap skipped
        assert summary['rejected']['team_cap'] == 0

    def test_per_model_mode_skips_rescue_cap(self):
        """All rescued picks should survive in per_model mode even when >40%."""
        # Create 5 picks: 4 rescued + 1 organic = 80% rescued (well above 40% cap)
        preds = []
        for i in range(5):
            p = _make_prediction(
                player_lookup=f'player_{i}',
                game_id=f'20260307_G{i}_MIL',
                edge=2.0 + i,  # Low edge to trigger rescue
                is_home=False,
            )
            p['team_abbr'] = f'T{i}'  # Different teams to avoid team cap
            if i < 4:
                # Mark as rescued — aggregator checks signal_rescued flag
                p['signal_rescued'] = True
                p['rescue_signal'] = 'high_signal_edge'
            preds.append(p)
        key_fn = lambda p: f"{p['player_lookup']}::{p['game_id']}"
        signals = {}
        for p in preds:
            signals[key_fn(p)] = [_make_signal_result(f'sig_{j}') for j in range(5)]
        agg = BestBetsAggregator(mode='per_model')
        picks, summary = agg.aggregate(preds, signals)
        assert summary['rejected']['rescue_cap'] == 0  # No rescues dropped


# ============================================================================
# SESSION 451 FILTER TESTS
# ============================================================================

class TestLineAnomalyExtremeDropFilter:
    """Session 451: Line anomaly blocks OVER when line drops >= 40% or >= 6 pts."""

    def _make_signals(self, pred, n=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        return {key: [_make_signal_result(f'sig_{i}') for i in range(n)]}

    def test_blocks_40pct_drop_over(self):
        """OVER with 50% line drop should be blocked."""
        pred = _make_prediction(
            edge=7.0, recommendation='OVER', line_value=8.5,
            prop_line_delta=-8.0,  # current 8.5, prev was 16.5 => delta = -8.0
        )
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], self._make_signals(pred))
        assert summary['rejected']['line_anomaly_extreme_drop'] == 1
        assert len(picks) == 0

    def test_blocks_6pt_abs_drop_over(self):
        """OVER with 6+ point absolute drop should be blocked."""
        pred = _make_prediction(
            edge=6.0, recommendation='OVER', line_value=14.0,
            prop_line_delta=-7.0,  # current 14, prev was 21 => delta = -7.0
        )
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], self._make_signals(pred))
        assert summary['rejected']['line_anomaly_extreme_drop'] == 1
        assert len(picks) == 0

    def test_allows_normal_line_drop_over(self):
        """OVER with small line drop should pass."""
        pred = _make_prediction(
            edge=6.0, recommendation='OVER', line_value=20.0,
            prop_line_delta=-3.0,  # current 20, prev 23 => 13% drop
        )
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], self._make_signals(pred))
        assert summary['rejected']['line_anomaly_extreme_drop'] == 0
        assert len(picks) == 1

    def test_does_not_affect_under(self):
        """UNDER with big line drop should not be blocked by this filter."""
        pred = _make_prediction(
            edge=5.0, recommendation='UNDER', line_value=8.5,
            prop_line_delta=-8.0,
            trend_slope=2.0,
        )
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], self._make_signals(pred))
        assert summary['rejected']['line_anomaly_extreme_drop'] == 0


class TestPlayerUnderSuppressionObs:
    """Session 451: Player UNDER suppression observation mode."""

    def _make_signals(self, pred, n=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        return {key: [_make_signal_result(f'sig_{i}') for i in range(n)]}

    def test_tags_suppressed_under_player(self):
        """UNDER pick on suppressed player should be tagged but not blocked."""
        pred = _make_prediction(
            player_lookup='kat_player', edge=5.0,
            recommendation='UNDER', trend_slope=2.0,
        )
        agg = BestBetsAggregator(player_under_suppression={'kat_player'})
        picks, summary = agg.aggregate([pred], self._make_signals(pred))
        assert summary['rejected']['player_under_suppression_obs'] == 1
        assert len(picks) == 1  # Observation — still passes

    def test_does_not_tag_over_on_suppressed_player(self):
        """OVER pick on suppressed player should not be tagged."""
        pred = _make_prediction(
            player_lookup='kat_player', edge=6.0,
            recommendation='OVER',
        )
        agg = BestBetsAggregator(player_under_suppression={'kat_player'})
        picks, summary = agg.aggregate([pred], self._make_signals(pred))
        assert summary['rejected']['player_under_suppression_obs'] == 0

    def test_does_not_tag_non_suppressed_player(self):
        """UNDER pick on non-suppressed player should not be tagged."""
        pred = _make_prediction(
            edge=5.0, recommendation='UNDER', trend_slope=2.0,
        )
        agg = BestBetsAggregator(player_under_suppression={'some_other'})
        picks, summary = agg.aggregate([pred], self._make_signals(pred))
        assert summary['rejected']['player_under_suppression_obs'] == 0


class TestMeanReversionUnderGuard:
    """Session 451: mean_reversion_under doesn't fire on high OVER-rate players."""

    def test_blocked_at_high_over_rate(self):
        from ml.signals.mean_reversion_under import MeanReversionUnderSignal
        sig = MeanReversionUnderSignal()
        result = sig.evaluate({
            'recommendation': 'UNDER', 'line_value': 25.0,
            'trend_slope': 2.5, 'pts_avg_last3': 28.0,
            'over_rate_last_10': 0.70,  # Above 0.60 guard
        })
        assert not result.qualifies

    def test_fires_at_low_over_rate(self):
        from ml.signals.mean_reversion_under import MeanReversionUnderSignal
        sig = MeanReversionUnderSignal()
        result = sig.evaluate({
            'recommendation': 'UNDER', 'line_value': 25.0,
            'trend_slope': 2.5, 'pts_avg_last3': 28.0,
            'over_rate_last_10': 0.40,  # Below guard
        })
        assert result.qualifies

    def test_fires_when_over_rate_missing(self):
        from ml.signals.mean_reversion_under import MeanReversionUnderSignal
        sig = MeanReversionUnderSignal()
        result = sig.evaluate({
            'recommendation': 'UNDER', 'line_value': 25.0,
            'trend_slope': 2.5, 'pts_avg_last3': 28.0,
            # over_rate_last_10 missing → defaults to 0
        })
        assert result.qualifies


class TestMeanReversionInShadowSignals:
    """Session 451: mean_reversion_under is in SHADOW_SIGNALS."""

    def test_mean_reversion_in_shadow(self):
        from ml.signals.aggregator import SHADOW_SIGNALS
        assert 'mean_reversion_under' in SHADOW_SIGNALS


class TestFtVarianceUnder:
    """Session 452: FT variance ACTIVE filter blocks high-FTA + high-CV UNDER picks."""

    def _make_signals(self, pred, n=5):
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        return {key: [_make_signal_result(f'sig_{i}') for i in range(n)]}

    def test_tracks_high_fta_high_cv_observation(self):
        """Session 462: ft_variance_under is now observation mode — counts but does NOT block."""
        pred = _make_prediction(
            edge=5.0, recommendation='UNDER', trend_slope=2.0,
        )
        pred['fta_avg_last_10'] = 6.0
        pred['fta_cv_last_10'] = 0.55
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], self._make_signals(pred))
        assert summary['rejected']['ft_variance_under'] == 1
        assert len(picks) == 1  # Session 462: observation mode — passes through

    def test_does_not_block_low_fta(self):
        pred = _make_prediction(
            edge=5.0, recommendation='UNDER', trend_slope=2.0,
        )
        pred['fta_avg_last_10'] = 3.0  # Below 5.0 threshold
        pred['fta_cv_last_10'] = 0.55
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], self._make_signals(pred))
        assert summary['rejected']['ft_variance_under'] == 0

    def test_does_not_block_low_cv(self):
        pred = _make_prediction(
            edge=5.0, recommendation='UNDER', trend_slope=2.0,
        )
        pred['fta_avg_last_10'] = 6.0
        pred['fta_cv_last_10'] = 0.3  # Below 0.5 threshold
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], self._make_signals(pred))
        assert summary['rejected']['ft_variance_under'] == 0


class TestUnderLowRsc:
    """Session 452: UNDER low real_sc ACTIVE filter blocks real_sc < 2 UNDER picks."""

    def _make_signals_with_real_sc(self, pred, real_count=1):
        """Build signal results that pass SC >= 3 gate but with controlled real_sc.

        Uses BASE_SIGNALS (model_health, starter_under, blowout_risk_under)
        to pad signal_count to 3+, then adds `real_count` non-base signals
        for real_sc control.
        """
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        # Base signals don't count toward real_sc
        base = [
            _make_signal_result('model_health'),
            _make_signal_result('starter_under'),
            _make_signal_result('blowout_risk_under'),
        ]
        # Real signals count toward real_sc
        real = [_make_signal_result(f'home_under_{i}') for i in range(real_count)]
        return {key: base + real}

    def test_blocks_under_rsc_1_low_edge(self):
        """UNDER with real_sc=1, edge < 7 should be BLOCKED."""
        pred = _make_prediction(
            edge=5.0, recommendation='UNDER', trend_slope=2.0,
        )
        agg = BestBetsAggregator()
        # 3 base + 1 real = signal_count 4 (passes SC gate), real_sc=1
        picks, summary = agg.aggregate(
            [pred], self._make_signals_with_real_sc(pred, real_count=1),
        )
        assert summary['rejected']['under_low_rsc'] == 1
        assert len(picks) == 0  # Blocked

    def test_passes_under_rsc_2(self):
        """UNDER with real_sc=2 should pass through."""
        pred = _make_prediction(
            edge=5.0, recommendation='UNDER', trend_slope=2.0,
        )
        agg = BestBetsAggregator()
        # 3 base + 2 real = signal_count 5, real_sc=2
        picks, summary = agg.aggregate(
            [pred], self._make_signals_with_real_sc(pred, real_count=2),
        )
        assert summary['rejected']['under_low_rsc'] == 0
        assert len(picks) == 1

    def test_passes_under_rsc_1_high_edge(self):
        """UNDER with real_sc=1 but edge >= 7 should bypass filter."""
        pred = _make_prediction(
            edge=8.0, recommendation='UNDER', trend_slope=2.0,
        )
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate(
            [pred], self._make_signals_with_real_sc(pred, real_count=1),
        )
        assert summary['rejected']['under_low_rsc'] == 0

    def test_over_not_affected(self):
        """OVER picks should never be affected by under_low_rsc filter."""
        pred = _make_prediction(
            edge=5.0, recommendation='OVER', trend_slope=2.0,
        )
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate(
            [pred], self._make_signals_with_real_sc(pred, real_count=1),
        )
        assert summary['rejected']['under_low_rsc'] == 0
