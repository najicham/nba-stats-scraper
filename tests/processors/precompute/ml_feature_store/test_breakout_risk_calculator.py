"""
Unit Tests for Breakout Risk Score Calculator

Tests the BreakoutRiskCalculator which calculates a composite 0-100 score
predicting breakout probability for role players.

Run with: pytest test_breakout_risk_calculator.py -v

Directory: tests/processors/precompute/ml_feature_store/
"""

import pytest
from data_processors.precompute.ml_feature_store.breakout_risk_calculator import (
    BreakoutRiskCalculator,
    BreakoutRiskComponents,
    calculate_breakout_risk,
    WEIGHT_HOT_STREAK,
    WEIGHT_COLD_STREAK_BONUS,
    WEIGHT_VOLATILITY,
    WEIGHT_OPPONENT_DEFENSE,
    WEIGHT_OPPORTUNITY,
    WEIGHT_HISTORICAL_RATE,
)


class TestBreakoutRiskCalculator:
    """Test BreakoutRiskCalculator - composite breakout prediction."""

    @pytest.fixture
    def calculator(self):
        """Create calculator instance for tests."""
        return BreakoutRiskCalculator()

    @pytest.fixture
    def neutral_phase4_data(self):
        """Phase 4 data with neutral values."""
        return {
            'points_avg_last_5': 12.0,
            'points_avg_last_10': 12.0,
            'points_avg_season': 12.0,
            'points_std_last_10': 5.0,
            'pts_vs_season_zscore': 0.0,
            'opponent_def_rating': 112.0,  # League average
            'usage_rate_last_10': 20.0,  # Session 126: neutral usage
            'player_usage_rate_season': 20.0,
        }

    @pytest.fixture
    def neutral_phase3_data(self):
        """Phase 3 data with neutral values."""
        return {
            'points_avg_last_5': 12.0,
            'points_avg_season': 12.0,
            'points_std_last_10': 5.0,
            'last_10_games': [
                {'points': 12}, {'points': 11}, {'points': 13}, {'points': 10}, {'points': 14},
                {'points': 12}, {'points': 11}, {'points': 13}, {'points': 10}, {'points': 14},
            ],
        }

    # ========================================================================
    # COMPOSITE SCORE TESTS
    # ========================================================================

    def test_composite_score_neutral_player(self, calculator, neutral_phase4_data, neutral_phase3_data):
        """Test composite score for player with neutral values."""
        score, components = calculator.calculate_breakout_risk_score(
            neutral_phase4_data, neutral_phase3_data
        )

        # Neutral player should score around 30-50 (moderate risk)
        assert 25 <= score <= 55, f"Neutral player score {score} outside expected 25-55 range"
        assert isinstance(components, BreakoutRiskComponents)

    def test_composite_score_very_hot_player(self, calculator, neutral_phase3_data):
        """Test composite score for player on hot streak."""
        hot_phase4 = {
            'points_avg_last_5': 18.0,
            'points_avg_last_10': 14.0,  # Session 126: for cold streak calc
            'points_avg_season': 12.0,
            'points_std_last_10': 5.0,
            'pts_vs_season_zscore': 1.8,  # Very hot
            'opponent_def_rating': 118.0,  # Weak defense
            'usage_rate_last_10': 25.0,  # Session 126: Rising usage
            'player_usage_rate_season': 20.0,
        }

        score, components = calculator.calculate_breakout_risk_score(
            hot_phase4, neutral_phase3_data
        )

        # Session 126: With updated weights (hot_streak at 15% not 30%), but
        # compensated by weak defense (20%) and rising usage
        # Hot streak=100*0.15=15, cold_bonus=30*0.10=3, vol~35*0.25=9, def=90*0.20=18, opp~56*0.15=8, hist~35*0.15=5 = ~58
        assert score >= 50, f"Hot player vs weak defense should score >= 50, got {score}"
        assert components.hot_streak_score >= 90, "Hot streak component should be very high"

    def test_composite_score_cold_player(self, calculator, neutral_phase3_data):
        """Test composite score for cold player."""
        cold_phase4 = {
            'points_avg_last_5': 8.0,
            'points_avg_last_10': 11.0,  # Session 126: L5 < L10 = cold streak
            'points_avg_season': 12.0,
            'points_std_last_10': 3.0,  # Low volatility
            'pts_vs_season_zscore': -1.5,  # Very cold
            'opponent_def_rating': 108.0,  # Strong defense
            'usage_rate_last_10': 18.0,  # Session 126: Falling usage
            'player_usage_rate_season': 20.0,
        }

        score, components = calculator.calculate_breakout_risk_score(
            cold_phase4, neutral_phase3_data
        )

        # Session 126: Cold player gets COLD STREAK BONUS (mean reversion)
        # But strong defense, low volatility, and falling usage balance it
        # Score still moderate due to mean reversion signal
        assert score <= 50, f"Cold player vs strong defense should score <= 50, got {score}"
        assert components.cold_streak_bonus >= 70, "Cold streak should trigger mean reversion bonus"

    def test_composite_score_range_clamped(self, calculator, neutral_phase3_data):
        """Test that composite score is always between 0-100."""
        # Extreme hot case
        extreme_hot_phase4 = {
            'pts_vs_season_zscore': 3.0,
            'points_std_last_10': 15.0,
            'opponent_def_rating': 125.0,
        }

        score, _ = calculator.calculate_breakout_risk_score(
            extreme_hot_phase4, neutral_phase3_data, {'injured_teammates_ppg': 50}
        )
        assert 0 <= score <= 100, f"Score {score} outside 0-100 range"

        # Extreme cold case
        extreme_cold_phase4 = {
            'pts_vs_season_zscore': -3.0,
            'points_std_last_10': 1.0,
            'opponent_def_rating': 100.0,
        }

        score, _ = calculator.calculate_breakout_risk_score(
            extreme_cold_phase4, neutral_phase3_data, {'injured_teammates_ppg': 0}
        )
        assert 0 <= score <= 100, f"Score {score} outside 0-100 range"

    # ========================================================================
    # HOT STREAK COMPONENT TESTS
    # ========================================================================

    def test_hot_streak_very_hot(self, calculator, neutral_phase4_data, neutral_phase3_data):
        """Test hot streak component for very hot player (z >= 1.5)."""
        hot_phase4 = {**neutral_phase4_data, 'pts_vs_season_zscore': 1.8}

        _, components = calculator.calculate_breakout_risk_score(hot_phase4, neutral_phase3_data)

        assert components.hot_streak_score == 100.0, "z >= 1.5 should give 100 hot streak score"

    def test_hot_streak_very_cold(self, calculator, neutral_phase4_data, neutral_phase3_data):
        """Test hot streak component for very cold player (z <= -1.5)."""
        cold_phase4 = {**neutral_phase4_data, 'pts_vs_season_zscore': -2.0}

        _, components = calculator.calculate_breakout_risk_score(cold_phase4, neutral_phase3_data)

        assert components.hot_streak_score == 0.0, "z <= -1.5 should give 0 hot streak score"

    def test_hot_streak_neutral(self, calculator, neutral_phase4_data, neutral_phase3_data):
        """Test hot streak component for neutral player (z = 0)."""
        _, components = calculator.calculate_breakout_risk_score(
            neutral_phase4_data, neutral_phase3_data
        )

        assert components.hot_streak_score == 50.0, "z = 0 should give 50 hot streak score"

    def test_hot_streak_fallback_to_calculation(self, calculator, neutral_phase3_data):
        """Test hot streak uses calculated z-score when missing from phase4."""
        # Phase 4 without z-score, Phase 3 has the data to calculate it
        phase4_no_zscore = {
            'points_avg_season': 12.0,
            'points_std_last_10': 4.0,
        }
        phase3_with_data = {
            **neutral_phase3_data,
            'points_avg_last_5': 16.0,  # 4 points above season avg = 1.0 z-score
            'points_avg_season': 12.0,
            'points_std_last_10': 4.0,
        }

        _, components = calculator.calculate_breakout_risk_score(phase4_no_zscore, phase3_with_data)

        # z = (16 - 12) / 4 = 1.0 -> score = ((1.0 + 1.5) / 3.0) * 100 = 83.33
        assert 80 <= components.hot_streak_score <= 87, f"Calculated z-score should give ~83, got {components.hot_streak_score}"

    # ========================================================================
    # VOLATILITY COMPONENT TESTS
    # ========================================================================

    def test_volatility_high_std(self, calculator, neutral_phase3_data):
        """Test volatility component with high standard deviation."""
        high_std_phase4 = {
            'points_std_last_10': 10.0,  # Very high
            'points_avg_season': 12.0,
        }

        _, components = calculator.calculate_breakout_risk_score(high_std_phase4, neutral_phase3_data)

        # High std (10) gives 50 points, but explosion ratio from neutral phase3 is low (~1.17)
        # Combined: 50 * 0.6 + 10 * 0.4 = 34
        assert components.volatility_score >= 30, "High std should give moderate-high volatility score"

    def test_volatility_low_std(self, calculator, neutral_phase3_data):
        """Test volatility component with low standard deviation."""
        low_std_phase4 = {
            'points_std_last_10': 2.0,  # Very low
            'points_avg_season': 12.0,
        }
        low_vol_phase3 = {
            **neutral_phase3_data,
            'last_10_games': [{'points': 12} for _ in range(10)],  # All same score
        }

        _, components = calculator.calculate_breakout_risk_score(low_std_phase4, low_vol_phase3)

        assert components.volatility_score <= 25, "Low std should give low volatility score"

    def test_volatility_high_explosion_ratio(self, calculator, neutral_phase4_data):
        """Test volatility component with high explosion ratio."""
        explosive_phase3 = {
            'points_avg_season': 12.0,
            'last_10_games': [
                {'points': 28},  # Explosion game (2.33x avg)
                {'points': 10}, {'points': 11}, {'points': 10}, {'points': 9},
                {'points': 10}, {'points': 11}, {'points': 10}, {'points': 9}, {'points': 10},
            ],
        }

        _, components = calculator.calculate_breakout_risk_score(neutral_phase4_data, explosive_phase3)

        # max=28, avg=12 -> ratio=2.33 >= 1.8 threshold
        assert components.explosion_ratio >= 1.8, f"Explosion ratio should be >= 1.8, got {components.explosion_ratio}"

    # ========================================================================
    # OPPONENT DEFENSE COMPONENT TESTS
    # ========================================================================

    def test_opponent_defense_very_weak(self, calculator, neutral_phase3_data):
        """Test opponent defense component for very weak defense."""
        weak_def_phase4 = {
            'opponent_def_rating': 118.0,  # Very weak
        }

        _, components = calculator.calculate_breakout_risk_score(weak_def_phase4, neutral_phase3_data)

        assert components.opponent_defense_score >= 85, "Very weak defense should give high score"

    def test_opponent_defense_strong(self, calculator, neutral_phase3_data):
        """Test opponent defense component for strong defense."""
        strong_def_phase4 = {
            'opponent_def_rating': 105.0,  # Strong
        }

        _, components = calculator.calculate_breakout_risk_score(strong_def_phase4, neutral_phase3_data)

        assert components.opponent_defense_score <= 35, "Strong defense should give low score"

    def test_opponent_defense_missing_uses_league_avg(self, calculator, neutral_phase3_data):
        """Test that missing defense rating defaults to league average."""
        no_def_phase4 = {}

        _, components = calculator.calculate_breakout_risk_score(no_def_phase4, neutral_phase3_data)

        # League avg (112) -> should give ~50 score
        assert 45 <= components.opponent_defense_score <= 55, "Missing def rating should use league avg"

    # ========================================================================
    # OPPORTUNITY COMPONENT TESTS (Session 126: Updated for usage trend + injury combo)
    # ========================================================================

    def test_opportunity_star_injured(self, calculator, neutral_phase4_data, neutral_phase3_data):
        """Test opportunity component when star player is injured."""
        team_context = {'injured_teammates_ppg': 25.0}

        _, components = calculator.calculate_breakout_risk_score(
            neutral_phase4_data, neutral_phase3_data, team_context
        )

        # Session 126: Combined score = usage(50)*0.6 + injury(80)*0.4 = 62
        # Star injured gives injury_score=80, neutral usage gives usage_score=50
        assert components.opportunity_score >= 55, "Star player out should give elevated opportunity"
        assert components.injured_teammates_ppg == 25.0

    def test_opportunity_team_healthy(self, calculator, neutral_phase4_data, neutral_phase3_data):
        """Test opportunity component when team is healthy."""
        team_context = {'injured_teammates_ppg': 0.0}

        _, components = calculator.calculate_breakout_risk_score(
            neutral_phase4_data, neutral_phase3_data, team_context
        )

        # Session 126: Combined score = usage(50)*0.6 + injury(20)*0.4 = 38
        # Healthy team gives injury_score=20, neutral usage gives usage_score=50
        assert components.opportunity_score <= 45, "Healthy team should give moderate-low opportunity"
        assert components.injured_teammates_ppg == 0.0

    def test_opportunity_no_context(self, calculator, neutral_phase4_data, neutral_phase3_data):
        """Test opportunity component without team context."""
        _, components = calculator.calculate_breakout_risk_score(
            neutral_phase4_data, neutral_phase3_data, None
        )

        # Session 126: Combined score = usage(50)*0.6 + injury(20)*0.4 = 38
        # No context defaults to injury_score=20, neutral usage gives usage_score=50
        assert 35 <= components.opportunity_score <= 45, "No team context should give neutral-ish score"

    def test_opportunity_rising_usage(self, calculator, neutral_phase3_data):
        """Session 126: Test opportunity component with rising usage trend."""
        rising_usage_phase4 = {
            'points_avg_last_5': 12.0,
            'points_avg_last_10': 12.0,
            'points_avg_season': 12.0,
            'points_std_last_10': 5.0,
            'pts_vs_season_zscore': 0.0,
            'opponent_def_rating': 112.0,
            'usage_rate_last_10': 25.0,  # Rising usage
            'player_usage_rate_season': 20.0,
        }

        _, components = calculator.calculate_breakout_risk_score(
            rising_usage_phase4, neutral_phase3_data, None
        )

        # Rising usage (+5%) should give usage_score=80, injury default=20
        # Combined = 80*0.6 + 20*0.4 = 56
        assert components.opportunity_score >= 50, "Rising usage should give elevated opportunity"
        assert components.usage_trend >= 4.0, "Usage trend should be positive"

    # ========================================================================
    # HISTORICAL BREAKOUT RATE TESTS
    # ========================================================================

    def test_historical_rate_frequent_breakouts(self, calculator, neutral_phase4_data):
        """Test historical rate for player with frequent breakouts."""
        frequent_breakout_phase3 = {
            'points_avg_season': 12.0,
            'last_10_games': [
                {'points': 20}, {'points': 22}, {'points': 18},  # 3 breakouts (>= 18)
                {'points': 10}, {'points': 11}, {'points': 12}, {'points': 10},
                {'points': 11}, {'points': 12}, {'points': 10},
            ],
        }

        _, components = calculator.calculate_breakout_risk_score(
            neutral_phase4_data, frequent_breakout_phase3
        )

        # 3/10 = 30% breakout rate -> high score
        assert components.historical_rate_score >= 70, f"30% breakout rate should give high score, got {components.historical_rate_score}"

    def test_historical_rate_no_breakouts(self, calculator, neutral_phase4_data):
        """Test historical rate for player with no recent breakouts."""
        no_breakout_phase3 = {
            'points_avg_season': 12.0,
            'last_10_games': [{'points': 10 + i % 3} for i in range(10)],  # All below 18
        }

        _, components = calculator.calculate_breakout_risk_score(
            neutral_phase4_data, no_breakout_phase3
        )

        assert components.historical_rate_score <= 15, "No breakouts should give low score"

    def test_historical_rate_insufficient_games(self, calculator, neutral_phase4_data):
        """Test historical rate with insufficient game history."""
        few_games_phase3 = {
            'points_avg_season': 12.0,
            'last_10_games': [{'points': 12}, {'points': 11}],  # Only 2 games
        }

        _, components = calculator.calculate_breakout_risk_score(
            neutral_phase4_data, few_games_phase3
        )

        # Should default to league baseline
        assert components.historical_rate_score == 35.0, "Insufficient games should use baseline"

    # ========================================================================
    # HELPER METHOD TESTS
    # ========================================================================

    def test_is_role_player_in_range(self, calculator, neutral_phase4_data, neutral_phase3_data):
        """Test role player detection for player in range."""
        in_range_phase4 = {**neutral_phase4_data, 'points_avg_season': 12.0}

        assert calculator.is_role_player(in_range_phase4, neutral_phase3_data)

    def test_is_role_player_star(self, calculator, neutral_phase4_data, neutral_phase3_data):
        """Test role player detection for star player."""
        star_phase4 = {**neutral_phase4_data, 'points_avg_season': 25.0}

        assert not calculator.is_role_player(star_phase4, neutral_phase3_data)

    def test_is_role_player_bench(self, calculator, neutral_phase4_data, neutral_phase3_data):
        """Test role player detection for deep bench player."""
        bench_phase4 = {**neutral_phase4_data, 'points_avg_season': 5.0}

        assert not calculator.is_role_player(bench_phase4, neutral_phase3_data)

    def test_get_risk_category(self, calculator):
        """Test risk category determination."""
        assert calculator.get_risk_category(15) == 'low'
        assert calculator.get_risk_category(35) == 'moderate'
        assert calculator.get_risk_category(60) == 'high'
        assert calculator.get_risk_category(85) == 'very_high'

    def test_should_skip_under_bet_high_risk(self, calculator):
        """Test skip recommendation for high risk player."""
        should_skip, reason = calculator.should_skip_under_bet(score=65, edge=-2.5)

        assert should_skip, "High risk (65) with low edge should skip"
        assert 'breakout_risk' in reason

    def test_should_skip_under_bet_low_risk(self, calculator):
        """Test skip recommendation for low risk player."""
        should_skip, reason = calculator.should_skip_under_bet(score=25, edge=-3.0)

        assert not should_skip, "Low risk (25) should not skip"
        assert reason is None

    def test_should_skip_under_bet_high_edge_allows_risk(self, calculator):
        """Test that high edge allows more risk."""
        should_skip, _ = calculator.should_skip_under_bet(score=60, edge=-6.0)

        assert not should_skip, "High edge (6.0) should tolerate 60 risk score"

    # ========================================================================
    # CONVENIENCE FUNCTION TESTS
    # ========================================================================

    def test_calculate_breakout_risk_function(self, neutral_phase4_data, neutral_phase3_data):
        """Test standalone convenience function."""
        score = calculate_breakout_risk(neutral_phase4_data, neutral_phase3_data)

        assert isinstance(score, float)
        assert 0 <= score <= 100


class TestComponentWeights:
    """Test that component weights sum to 100%."""

    def test_weights_sum_to_one(self):
        """Verify all component weights sum to 1.0 (100%)."""
        # Session 126: Added WEIGHT_COLD_STREAK_BONUS for mean reversion
        total = (
            WEIGHT_HOT_STREAK +
            WEIGHT_COLD_STREAK_BONUS +
            WEIGHT_VOLATILITY +
            WEIGHT_OPPONENT_DEFENSE +
            WEIGHT_OPPORTUNITY +
            WEIGHT_HISTORICAL_RATE
        )

        assert abs(total - 1.0) < 0.001, f"Weights should sum to 1.0, got {total}"


class TestBreakoutRiskComponents:
    """Test BreakoutRiskComponents dataclass."""

    def test_to_dict(self):
        """Test components to_dict method."""
        # Session 126: Updated with new fields (cold_streak_bonus, cv_ratio, usage_trend, l5_vs_l10_trend)
        components = BreakoutRiskComponents(
            hot_streak_score=80.0,
            cold_streak_bonus=50.0,  # Session 126
            volatility_score=50.0,
            opponent_defense_score=70.0,
            opportunity_score=30.0,
            historical_rate_score=40.0,
            pts_vs_season_zscore=1.2,
            cv_ratio=0.5,  # Session 126
            usage_trend=2.0,  # Session 126
            l5_vs_l10_trend=0.1,  # Session 126
            points_std=6.5,
            explosion_ratio=1.6,
            opponent_def_rating=115.0,
            injured_teammates_ppg=15.0,
            historical_breakout_rate=0.2,
        )

        result = components.to_dict()

        assert result['hot_streak_score'] == 80.0
        assert result['cold_streak_bonus'] == 50.0
        assert result['cv_ratio'] == 0.5
        assert result['usage_trend'] == 2.0
        assert result['opponent_def_rating'] == 115.0
        assert len(result) == 15  # Updated from 11 to 15 (4 new fields)
