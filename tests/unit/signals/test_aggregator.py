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
            'under_after_streak',
            'mid_line_over_obs', 'monday_over_obs', 'home_over_obs',
            'signal_stack_2plus_obs', 'rescue_cap',
            'unreliable_over_low_mins_obs', 'unreliable_under_flat_trend_obs',
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

    def test_starter_over_sc3_blocked_by_mid_line(self):
        """OVER + line=18 + 3 signals → blocked by mid_line_over (Session 415).

        Session 415: mid_line_over promoted to active block, subsumes
        starter_over_sc_floor for all OVER + line 15-25 picks.
        """
        pred = _make_prediction(
            recommendation='OVER',
            line_value=18.0,
            edge=8.0,  # edge >= 7 to pass signal_count
        )
        signals = self._make_signal_results_for(pred, n_qualifying=3)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        # mid_line_over fires before sc3_over_block and starter_over_sc_floor
        assert summary['rejected']['mid_line_over_obs'] == 1

    def test_starter_over_sc5_blocked_by_mid_line(self):
        """OVER + line=18 + 5 signals → blocked by mid_line_over (Session 415).

        Session 415: mid_line_over subsumes starter_over_sc_floor.
        """
        pred = _make_prediction(
            recommendation='OVER',
            line_value=18.0,
        )
        signals = self._make_signal_results_for(pred, n_qualifying=5)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['mid_line_over_obs'] == 1

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

    def test_mid_line_over_blocked(self):
        """OVER + line=20 is now blocked."""
        pred = _make_prediction(
            recommendation='OVER',
            line_value=20.0,
            edge=6.0,
        )
        signals = self._make_signal_results_for(pred)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)
        assert len(picks) == 0
        assert summary['rejected']['mid_line_over_obs'] == 1

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
