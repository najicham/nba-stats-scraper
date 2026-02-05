# File: data_processors/precompute/ml_feature_store/breakout_risk_calculator.py
"""
Breakout Risk Score Calculator - Feature 37

Calculates a composite 0-100 score predicting breakout probability for role players.
A breakout is defined as scoring >= 1.5x season average in a single game.

Use Case:
- Filter UNDER bets on role players with high breakout risk
- Role player (8-16 PPG) UNDER bets have 42-45% hit rate (losing money)
- This score helps identify which specific players are likely to break out

Component Weights (calibrated from historical analysis):
- Hot Streak Component (30%): Recent performance vs season baseline
- Volatility Component (20%): Standard deviation and max scoring in recent games
- Opponent Defense Component (20%): How leaky is the opponent defense?
- Opportunity Component (15%): Teammate injuries creating more shots
- Historical Breakout Rate (15%): Player's baseline breakout tendency

Score Interpretation:
- 0-25: Low risk - Safe for UNDER bet
- 26-50: Moderate risk - Proceed with caution
- 51-75: High risk - Consider skipping UNDER
- 76-100: Very high risk - Skip UNDER bet

Version: 1.0 (Session 125 - Feb 2026)
"""

import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# BigQuery NUMERIC type precision limit
NUMERIC_PRECISION = 9

# Component weight configuration (total = 100%)
# Updated in Session 126 based on Opus agent research:
# - Reduced hot streak (cold players break out MORE - mean reversion)
# - Added cold streak bonus (mean reversion signal)
# - Enhanced volatility with CV ratio (strongest predictor)
# - Enhanced opportunity with usage trend
WEIGHT_HOT_STREAK = 0.15      # 15% (reduced from 30%)
WEIGHT_COLD_STREAK_BONUS = 0.10  # 10% (NEW - mean reversion)
WEIGHT_VOLATILITY = 0.25      # 25% (increased from 20%, uses CV ratio)
WEIGHT_OPPONENT_DEFENSE = 0.20 # 20% (unchanged)
WEIGHT_OPPORTUNITY = 0.15      # 15% (enhanced with usage trend)
WEIGHT_HISTORICAL_RATE = 0.15  # 15% (unchanged)

# Thresholds for component scoring
HOT_STREAK_THRESHOLDS = {
    'very_hot': 1.5,   # z-score > 1.5 = max score
    'hot': 0.5,        # z-score > 0.5 = elevated
    'cold': -0.5,      # z-score < -0.5 = reduced
    'very_cold': -1.5, # z-score < -1.5 = min score
}

VOLATILITY_THRESHOLDS = {
    'high_std': 8.0,    # std > 8 = very volatile
    'medium_std': 5.0,  # std > 5 = moderately volatile
    'low_std': 3.0,     # std < 3 = consistent
    'explosion_ratio_high': 1.8,  # max(L5)/avg > 1.8 = explosive
    'explosion_ratio_medium': 1.5,
    # CV Ratio thresholds (Session 126 - strongest predictor found)
    # CV = std / avg - normalized volatility
    'cv_very_high': 0.60,   # 29.5% breakout rate (3.3x baseline)
    'cv_high': 0.40,        # 18.1% breakout rate
    'cv_medium': 0.25,      # 13.7% breakout rate
    # Below 0.25 = 9.0% breakout rate (very consistent)
}

# Cold streak thresholds for mean reversion (Session 126)
# Counter-intuitive: Cold players break out MORE (27.1% vs 17.2%)
COLD_STREAK_THRESHOLDS = {
    'very_cold': -0.20,  # L5 is 20%+ below L10 = high mean reversion potential
    'cold': -0.10,       # L5 is 10-20% below L10 = moderate potential
}

# Usage trend thresholds (Session 126)
# Rising usage = +7% breakout rate (23.5% vs 16.1%)
USAGE_TREND_THRESHOLDS = {
    'rising_strong': 3.0,   # Usage rate L10 is 3%+ above season
    'rising': 1.5,          # Usage rate L10 is 1.5-3% above season
    'falling': -1.5,        # Usage rate L10 is below season
}

DEFENSE_THRESHOLDS = {
    'very_weak': 116.0,  # def rating > 116 = very leaky
    'weak': 113.0,       # def rating > 113 = leaky
    'average': 110.0,    # def rating > 110 = average
    # Below 110 = strong defense
}

# League average defensive rating for normalization
LEAGUE_AVG_DEF_RATING = 112.0


@dataclass
class BreakoutRiskComponents:
    """Container for individual breakout risk components."""
    hot_streak_score: float       # 0-100
    cold_streak_bonus: float      # 0-100 (Session 126: mean reversion)
    volatility_score: float       # 0-100
    opponent_defense_score: float # 0-100
    opportunity_score: float      # 0-100
    historical_rate_score: float  # 0-100

    # Raw values for debugging
    pts_vs_season_zscore: float
    cv_ratio: float               # Session 126: coefficient of variation
    usage_trend: float            # Session 126: usage rate trend
    l5_vs_l10_trend: float        # Session 126: L5/L10 ratio for cold streak
    points_std: float
    explosion_ratio: float
    opponent_def_rating: float
    injured_teammates_ppg: float
    historical_breakout_rate: float

    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary for logging."""
        return {
            'hot_streak_score': self.hot_streak_score,
            'cold_streak_bonus': self.cold_streak_bonus,
            'volatility_score': self.volatility_score,
            'opponent_defense_score': self.opponent_defense_score,
            'opportunity_score': self.opportunity_score,
            'historical_rate_score': self.historical_rate_score,
            'pts_vs_season_zscore': self.pts_vs_season_zscore,
            'cv_ratio': self.cv_ratio,
            'usage_trend': self.usage_trend,
            'l5_vs_l10_trend': self.l5_vs_l10_trend,
            'points_std': self.points_std,
            'explosion_ratio': self.explosion_ratio,
            'opponent_def_rating': self.opponent_def_rating,
            'injured_teammates_ppg': self.injured_teammates_ppg,
            'historical_breakout_rate': self.historical_breakout_rate,
        }


class BreakoutRiskCalculator:
    """
    Calculate breakout risk score from Phase 3/4 data.

    This calculator combines multiple signals to produce a 0-100 score
    predicting the probability of a role player scoring >= 1.5x their
    season average.
    """

    def __init__(self):
        """Initialize breakout risk calculator."""
        pass

    def calculate_breakout_risk_score(
        self,
        phase4_data: Dict[str, Any],
        phase3_data: Dict[str, Any],
        team_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[float, BreakoutRiskComponents]:
        """
        Calculate composite breakout risk score.

        Args:
            phase4_data: Dict with Phase 4 precompute data including:
                - points_avg_last_5 (index 0)
                - points_avg_season (index 2)
                - points_std_last_10 (index 3)
                - pts_vs_season_zscore (index 35)
                - opponent_def_rating (index 13)
            phase3_data: Dict with Phase 3 analytics data including:
                - last_10_games: List[Dict] with points per game
                - team_injured_ppg: Float (if available)
            team_context: Optional dict with:
                - injured_teammates_ppg: PPG of injured teammates

        Returns:
            Tuple of (breakout_risk_score 0-100, BreakoutRiskComponents)
        """
        # 1. Calculate Hot Streak Component (15%) - Reduced from 30%
        hot_streak_score, z_score = self._calculate_hot_streak_component(
            phase4_data, phase3_data
        )

        # 2. Calculate Cold Streak Bonus (10%) - NEW: Mean reversion signal
        # Counter-intuitive: Cold players break out MORE (27.1% vs 17.2%)
        cold_streak_bonus, l5_vs_l10_trend = self._calculate_cold_streak_bonus(
            phase4_data, phase3_data
        )

        # 3. Calculate Volatility Component (25%) - Enhanced with CV ratio
        # CV ratio is the strongest predictor found (+0.198 correlation)
        volatility_score, std, explosion, cv_ratio = self._calculate_volatility_component(
            phase4_data, phase3_data
        )

        # 4. Calculate Opponent Defense Component (20%)
        opponent_score, def_rating = self._calculate_opponent_defense_component(
            phase4_data
        )

        # 5. Calculate Opportunity Component (15%) - Enhanced with usage trend
        # Rising usage = +7% breakout rate
        opportunity_score, injured_ppg, usage_trend = self._calculate_opportunity_component(
            phase4_data, team_context
        )

        # 6. Calculate Historical Breakout Rate Component (15%)
        historical_score, hist_rate = self._calculate_historical_breakout_component(
            phase3_data
        )

        # Combine with updated weights (Session 126)
        composite_score = (
            hot_streak_score * WEIGHT_HOT_STREAK +
            cold_streak_bonus * WEIGHT_COLD_STREAK_BONUS +
            volatility_score * WEIGHT_VOLATILITY +
            opponent_score * WEIGHT_OPPONENT_DEFENSE +
            opportunity_score * WEIGHT_OPPORTUNITY +
            historical_score * WEIGHT_HISTORICAL_RATE
        )

        # Clamp to 0-100 and round
        composite_score = max(0.0, min(100.0, composite_score))
        composite_score = round(composite_score, NUMERIC_PRECISION)

        # Build components for debugging/transparency
        components = BreakoutRiskComponents(
            hot_streak_score=hot_streak_score,
            cold_streak_bonus=cold_streak_bonus,
            volatility_score=volatility_score,
            opponent_defense_score=opponent_score,
            opportunity_score=opportunity_score,
            historical_rate_score=historical_score,
            pts_vs_season_zscore=z_score,
            cv_ratio=cv_ratio,
            usage_trend=usage_trend,
            l5_vs_l10_trend=l5_vs_l10_trend,
            points_std=std,
            explosion_ratio=explosion,
            opponent_def_rating=def_rating,
            injured_teammates_ppg=injured_ppg,
            historical_breakout_rate=hist_rate,
        )

        logger.debug(
            f"Breakout risk: score={composite_score:.1f}, "
            f"hot={hot_streak_score:.0f}, cold={cold_streak_bonus:.0f}, "
            f"vol={volatility_score:.0f} (cv={cv_ratio:.2f}), "
            f"def={opponent_score:.0f}, opp={opportunity_score:.0f} (usage={usage_trend:+.1f}), "
            f"hist={historical_score:.0f}"
        )

        return composite_score, components

    def _calculate_hot_streak_component(
        self,
        phase4_data: Dict[str, Any],
        phase3_data: Dict[str, Any]
    ) -> Tuple[float, float]:
        """
        Calculate hot streak component based on recent performance.

        Uses pts_vs_season_zscore from feature store or calculates if missing.

        Returns:
            Tuple of (component_score 0-100, z_score)
        """
        # Try to get z-score from Phase 4 (already calculated)
        z_score = phase4_data.get('pts_vs_season_zscore')

        # Fallback: calculate from Phase 3 data
        if z_score is None:
            l5_avg = phase3_data.get('points_avg_last_5')
            season_avg = phase3_data.get('points_avg_season')
            std = phase3_data.get('points_std_last_10')

            if all(v is not None for v in [l5_avg, season_avg, std]) and std > 0:
                z_score = (float(l5_avg) - float(season_avg)) / float(std)
            else:
                z_score = 0.0  # Neutral if missing

        # Convert z-score to 0-100 scale
        # z = -1.5 -> 0, z = 0 -> 50, z = 1.5 -> 100
        if z_score >= HOT_STREAK_THRESHOLDS['very_hot']:
            score = 100.0
        elif z_score <= HOT_STREAK_THRESHOLDS['very_cold']:
            score = 0.0
        else:
            # Linear interpolation: map [-1.5, 1.5] -> [0, 100]
            score = ((z_score + 1.5) / 3.0) * 100.0

        return round(score, 2), round(z_score, 4)

    def _calculate_cold_streak_bonus(
        self,
        phase4_data: Dict[str, Any],
        phase3_data: Dict[str, Any]
    ) -> Tuple[float, float]:
        """
        Calculate cold streak bonus for mean reversion.

        Session 126 Discovery: Cold players break out MORE than hot players.
        - Cold streak (L5 20%+ below L10): 27.1% breakout rate
        - Normal: 17-20% breakout rate
        - Hot streak: 21.7% breakout rate

        This is COUNTER-INTUITIVE but statistically significant.
        Mean reversion is real in NBA scoring.

        Returns:
            Tuple of (component_score 0-100, l5_vs_l10_trend)
        """
        # Get L5 and L10 averages
        l5_avg = phase4_data.get('points_avg_last_5')
        if l5_avg is None:
            l5_avg = phase3_data.get('points_avg_last_5')

        l10_avg = phase4_data.get('points_avg_last_10')
        if l10_avg is None:
            l10_avg = phase3_data.get('points_avg_last_10')

        # Calculate trend (L5 vs L10)
        if l5_avg is None or l10_avg is None or l10_avg <= 0:
            return 50.0, 0.0  # Neutral if missing

        l5_avg = float(l5_avg)
        l10_avg = float(l10_avg)
        l5_vs_l10_trend = (l5_avg - l10_avg) / l10_avg

        # Score: Cold streaks get HIGH scores (mean reversion potential)
        # Very cold (20%+ below L10): 100 points
        # Cold (10-20% below): 75 points
        # Normal: 50 points
        # Hot: 30 points (lower score - already performing well)
        if l5_vs_l10_trend <= COLD_STREAK_THRESHOLDS['very_cold']:
            score = 100.0  # Very cold = high mean reversion potential
        elif l5_vs_l10_trend <= COLD_STREAK_THRESHOLDS['cold']:
            score = 75.0   # Cold = moderate mean reversion
        elif l5_vs_l10_trend >= 0.10:
            score = 30.0   # Hot = lower potential (already elevated)
        else:
            score = 50.0   # Normal

        return round(score, 2), round(l5_vs_l10_trend, 4)

    def _calculate_volatility_component(
        self,
        phase4_data: Dict[str, Any],
        phase3_data: Dict[str, Any]
    ) -> Tuple[float, float, float, float]:
        """
        Calculate volatility component based on scoring consistency.

        Session 126: Enhanced with CV ratio (coefficient of variation).
        CV ratio is the strongest predictor found (+0.198 correlation).
        - High CV (60%+): 29.5% breakout rate (3.3x baseline)
        - Low CV (<25%): 9.0% breakout rate

        Combines:
        - CV ratio: std / avg (normalized volatility) - PRIMARY
        - Explosion ratio: max(L5) / season_avg - SECONDARY

        Returns:
            Tuple of (component_score 0-100, std_dev, explosion_ratio, cv_ratio)
        """
        # Get standard deviation and season average
        std = phase4_data.get('points_std_last_10')
        if std is None:
            std = phase3_data.get('points_std_last_10', 5.0)
        std = float(std) if std else 5.0

        season_avg = phase4_data.get('points_avg_season')
        if season_avg is None:
            season_avg = phase3_data.get('points_avg_season', 12.0)
        season_avg = float(season_avg) if season_avg else 12.0

        # Calculate CV ratio (coefficient of variation) - STRONGEST SIGNAL
        cv_ratio = std / season_avg if season_avg > 0 else 0.5

        # Calculate explosion ratio
        last_10_games = phase3_data.get('last_10_games', [])
        explosion_ratio = 1.0
        if last_10_games and len(last_10_games) >= 3 and season_avg > 0:
            last_5_points = [g.get('points', 0) or 0 for g in last_10_games[:5]]
            if last_5_points:
                max_points = max(last_5_points)
                explosion_ratio = max_points / season_avg

        # Score from CV ratio (0-60 points) - PRIMARY scoring
        # Based on Session 126 Opus agent research:
        # CV >= 0.60: 29.5% breakout (3.3x baseline)
        # CV 0.40-0.60: 18.1% breakout
        # CV 0.25-0.40: 13.7% breakout
        # CV < 0.25: 9.0% breakout
        if cv_ratio >= VOLATILITY_THRESHOLDS['cv_very_high']:
            cv_score = 60.0
        elif cv_ratio >= VOLATILITY_THRESHOLDS['cv_high']:
            cv_score = 45.0
        elif cv_ratio >= VOLATILITY_THRESHOLDS['cv_medium']:
            cv_score = 25.0
        else:
            cv_score = 10.0

        # Score from explosion ratio (0-40 points) - SECONDARY
        if explosion_ratio >= VOLATILITY_THRESHOLDS['explosion_ratio_high']:
            explosion_score = 40.0
        elif explosion_ratio >= VOLATILITY_THRESHOLDS['explosion_ratio_medium']:
            explosion_score = 25.0
        else:
            explosion_score = 10.0

        # Combine: CV ratio is primary (60% weight), explosion secondary (40%)
        total_score = cv_score * 0.6 + explosion_score * 0.4

        return round(total_score, 2), round(std, 2), round(explosion_ratio, 3), round(cv_ratio, 4)

    def _calculate_opponent_defense_component(
        self,
        phase4_data: Dict[str, Any]
    ) -> Tuple[float, float]:
        """
        Calculate opponent defense component based on defensive rating.

        Weaker defenses allow more breakouts.

        Returns:
            Tuple of (component_score 0-100, def_rating)
        """
        def_rating = phase4_data.get('opponent_def_rating')

        if def_rating is None:
            # Use league average if missing
            def_rating = LEAGUE_AVG_DEF_RATING
            score = 50.0  # Neutral
        else:
            def_rating = float(def_rating)

            # Map defensive rating to score
            # Lower def rating = better defense = lower breakout risk
            # Higher def rating = worse defense = higher breakout risk
            if def_rating >= DEFENSE_THRESHOLDS['very_weak']:
                score = 90.0
            elif def_rating >= DEFENSE_THRESHOLDS['weak']:
                score = 70.0
            elif def_rating >= DEFENSE_THRESHOLDS['average']:
                score = 50.0
            else:
                # Strong defense (< 110)
                # Linear interpolation from 100 to 110 -> 10 to 50
                score = max(10.0, 50.0 - (DEFENSE_THRESHOLDS['average'] - def_rating) * 4.0)

        return round(score, 2), round(def_rating, 2)

    def _calculate_opportunity_component(
        self,
        phase4_data: Dict[str, Any],
        team_context: Optional[Dict[str, Any]]
    ) -> Tuple[float, float, float]:
        """
        Calculate opportunity component based on:
        1. Teammate injuries (if available)
        2. Usage rate trend (Session 126: Rising usage = +7% breakout rate)

        Returns:
            Tuple of (component_score 0-100, injured_teammates_ppg, usage_trend)
        """
        # Calculate usage trend (Session 126)
        # Rising usage indicates player getting more involved in offense
        usage_l10 = phase4_data.get('usage_rate_last_10')
        usage_season = phase4_data.get('player_usage_rate_season')

        usage_trend = 0.0
        usage_score = 50.0  # Neutral default

        if usage_l10 is not None and usage_season is not None:
            usage_l10 = float(usage_l10)
            usage_season = float(usage_season)
            usage_trend = usage_l10 - usage_season

            # Score from usage trend
            # Rising strong (+3%+): 80 points
            # Rising (+1.5-3%): 65 points
            # Normal: 50 points
            # Falling (-1.5%+): 30 points
            if usage_trend >= USAGE_TREND_THRESHOLDS['rising_strong']:
                usage_score = 80.0
            elif usage_trend >= USAGE_TREND_THRESHOLDS['rising']:
                usage_score = 65.0
            elif usage_trend <= USAGE_TREND_THRESHOLDS['falling']:
                usage_score = 30.0
            else:
                usage_score = 50.0

        # Calculate injury component
        injured_ppg = 0.0
        injury_score = 20.0  # Low default if no injury context

        if team_context is not None:
            injured_ppg = team_context.get('injured_teammates_ppg', 0.0)
            injured_ppg = float(injured_ppg) if injured_ppg else 0.0

            # Score based on how many points are "up for grabs"
            if injured_ppg >= 30.0:
                injury_score = 100.0  # Multiple starters out
            elif injured_ppg >= 20.0:
                injury_score = 80.0   # Star player out
            elif injured_ppg >= 12.0:
                injury_score = 50.0   # Starter out
            elif injured_ppg >= 5.0:
                injury_score = 30.0   # Role player out
            else:
                injury_score = 20.0   # Team healthy

        # Combine: Usage trend (60%) + Injury opportunity (40%)
        # Usage trend is more consistently available and predictive
        total_score = usage_score * 0.6 + injury_score * 0.4

        return round(total_score, 2), round(injured_ppg, 1), round(usage_trend, 2)

    def _calculate_historical_breakout_component(
        self,
        phase3_data: Dict[str, Any]
    ) -> Tuple[float, float]:
        """
        Calculate historical breakout rate component.

        Based on what % of games this player scored >= 1.5x their average.

        Returns:
            Tuple of (component_score 0-100, historical_breakout_rate)
        """
        last_games = phase3_data.get('last_10_games', [])
        season_avg = phase3_data.get('points_avg_season')

        if not last_games or len(last_games) < 5 or not season_avg:
            return 35.0, 0.17  # League baseline ~17%

        season_avg = float(season_avg)
        breakout_threshold = season_avg * 1.5

        # Count breakouts in available history (up to 10 games)
        breakout_count = sum(
            1 for g in last_games
            if (g.get('points') or 0) >= breakout_threshold
        )

        breakout_rate = breakout_count / len(last_games)

        # Convert rate to 0-100 score
        # 0% rate -> 10, 17% rate -> 50, 35%+ rate -> 100
        if breakout_rate >= 0.35:
            score = 100.0
        elif breakout_rate <= 0.0:
            score = 10.0
        else:
            # Linear interpolation: map [0, 0.35] -> [10, 100]
            score = 10.0 + (breakout_rate / 0.35) * 90.0

        return round(score, 2), round(breakout_rate, 4)

    def is_role_player(self, phase4_data: Dict[str, Any], phase3_data: Dict[str, Any]) -> bool:
        """
        Check if player is a role player (8-16 PPG season average).

        This score is most meaningful for role players where breakouts
        are the primary cause of UNDER bet losses.
        """
        season_avg = phase4_data.get('points_avg_season')
        if season_avg is None:
            season_avg = phase3_data.get('points_avg_season')

        if season_avg is None:
            return False

        return 8.0 <= float(season_avg) <= 16.0

    def get_risk_category(self, score: float) -> str:
        """
        Convert numeric score to risk category.

        Returns one of: 'low', 'moderate', 'high', 'very_high'
        """
        if score < 25:
            return 'low'
        elif score < 50:
            return 'moderate'
        elif score < 75:
            return 'high'
        else:
            return 'very_high'

    def should_skip_under_bet(self, score: float, edge: float = 0.0) -> Tuple[bool, str]:
        """
        Recommend whether to skip an UNDER bet based on breakout risk.

        Uses a sliding threshold based on edge:
        - Higher edge allows taking more risk
        - Lower edge requires lower risk score

        Args:
            score: Breakout risk score (0-100)
            edge: Predicted edge in points (positive = OVER edge, negative = UNDER edge)

        Returns:
            Tuple of (should_skip, reason)
        """
        # For UNDER bets (negative edge), we skip if breakout risk is high
        # Threshold adjusts based on edge magnitude
        abs_edge = abs(edge)

        if abs_edge >= 5.0:
            threshold = 70  # High edge - accept more risk
        elif abs_edge >= 3.0:
            threshold = 55  # Medium edge
        else:
            threshold = 40  # Low edge - be conservative

        if score >= threshold:
            return True, f"breakout_risk_{score:.0f}_threshold_{threshold}"

        return False, None

    def calculate_composite_breakout_signal(
        self,
        phase4_data: Dict[str, Any],
        phase3_data: Dict[str, Any],
        game_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[int, Dict[str, bool]]:
        """
        Calculate composite breakout signal (0-5 score).

        Session 126 Discovery: Players with 4+ factors have 37% breakout rate (2x baseline).
        This simple signal is highly predictive of breakout games.

        Components (each adds +1 to score):
        1. High variance (CV >= 60%): +1
        2. Cold streak (L5 20%+ below L10): +1
        3. Starter status: +1
        4. Home game: +1
        5. Rested (<=2 games in 7 days): +1

        Historical Performance:
        - Score 5: 57.1% breakout rate
        - Score 4: 37.4% breakout rate
        - Score 3: 29.6% breakout rate
        - Score 2: 24.8% breakout rate
        - Score 1: 15.4% breakout rate
        - Score 0: 2.9% breakout rate

        Args:
            phase4_data: Phase 4 data with points, usage, and game context
            phase3_data: Phase 3 data with last_10_games
            game_context: Optional game context with home_away, is_starter

        Returns:
            Tuple of (composite_score 0-5, factors_dict)
        """
        factors = {}
        score = 0

        # 1. High variance (CV ratio >= 60%)
        std = phase4_data.get('points_std_last_10')
        season_avg = phase4_data.get('points_avg_season')
        if std is not None and season_avg is not None and float(season_avg) > 0:
            cv_ratio = float(std) / float(season_avg)
            factors['high_variance'] = cv_ratio >= 0.60
        else:
            factors['high_variance'] = False
        if factors['high_variance']:
            score += 1

        # 2. Cold streak (L5 20%+ below L10) - Mean reversion signal
        l5_avg = phase4_data.get('points_avg_last_5')
        l10_avg = phase4_data.get('points_avg_last_10')
        if l5_avg is not None and l10_avg is not None and float(l10_avg) > 0:
            l5_vs_l10 = (float(l5_avg) - float(l10_avg)) / float(l10_avg)
            factors['cold_streak'] = l5_vs_l10 <= -0.20
        else:
            factors['cold_streak'] = False
        if factors['cold_streak']:
            score += 1

        # 3. Starter status (if available from game context)
        if game_context and game_context.get('is_starter'):
            factors['is_starter'] = True
            score += 1
        else:
            # Default: check if player typically starts (usage proxy)
            usage = phase4_data.get('usage_rate_last_10')
            factors['is_starter'] = usage is not None and float(usage) >= 18.0
            if factors['is_starter']:
                score += 1

        # 4. Home game
        if game_context and game_context.get('home_away') == 'home':
            factors['home_game'] = True
            score += 1
        else:
            # Check if available in phase4 data (feature index 15)
            home_away = phase4_data.get('home_away')
            factors['home_game'] = home_away == 1.0 or home_away == 'home'
            if factors['home_game']:
                score += 1

        # 5. Rested (<=2 games in 7 days)
        games_in_7 = phase4_data.get('games_in_last_7_days')
        if games_in_7 is not None:
            factors['rested'] = float(games_in_7) <= 2
        else:
            factors['rested'] = False
        if factors['rested']:
            score += 1

        logger.debug(
            f"Composite breakout signal: {score}/5 - "
            f"var={factors['high_variance']}, cold={factors['cold_streak']}, "
            f"starter={factors['is_starter']}, home={factors['home_game']}, "
            f"rested={factors['rested']}"
        )

        return score, factors


# Convenience function for direct calculation
def calculate_breakout_risk(
    phase4_data: Dict[str, Any],
    phase3_data: Dict[str, Any],
    team_context: Optional[Dict[str, Any]] = None
) -> float:
    """
    Calculate breakout risk score (0-100).

    Convenience wrapper for BreakoutRiskCalculator.
    """
    calculator = BreakoutRiskCalculator()
    score, _ = calculator.calculate_breakout_risk_score(
        phase4_data, phase3_data, team_context
    )
    return score
