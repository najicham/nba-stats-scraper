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
WEIGHT_HOT_STREAK = 0.30      # 30%
WEIGHT_VOLATILITY = 0.20      # 20%
WEIGHT_OPPONENT_DEFENSE = 0.20 # 20%
WEIGHT_OPPORTUNITY = 0.15      # 15%
WEIGHT_HISTORICAL_RATE = 0.15  # 15%

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
    volatility_score: float       # 0-100
    opponent_defense_score: float # 0-100
    opportunity_score: float      # 0-100
    historical_rate_score: float  # 0-100

    # Raw values for debugging
    pts_vs_season_zscore: float
    points_std: float
    explosion_ratio: float
    opponent_def_rating: float
    injured_teammates_ppg: float
    historical_breakout_rate: float

    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary for logging."""
        return {
            'hot_streak_score': self.hot_streak_score,
            'volatility_score': self.volatility_score,
            'opponent_defense_score': self.opponent_defense_score,
            'opportunity_score': self.opportunity_score,
            'historical_rate_score': self.historical_rate_score,
            'pts_vs_season_zscore': self.pts_vs_season_zscore,
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
        # 1. Calculate Hot Streak Component (30%)
        hot_streak_score, z_score = self._calculate_hot_streak_component(
            phase4_data, phase3_data
        )

        # 2. Calculate Volatility Component (20%)
        volatility_score, std, explosion = self._calculate_volatility_component(
            phase4_data, phase3_data
        )

        # 3. Calculate Opponent Defense Component (20%)
        opponent_score, def_rating = self._calculate_opponent_defense_component(
            phase4_data
        )

        # 4. Calculate Opportunity Component (15%)
        opportunity_score, injured_ppg = self._calculate_opportunity_component(
            team_context
        )

        # 5. Calculate Historical Breakout Rate Component (15%)
        historical_score, hist_rate = self._calculate_historical_breakout_component(
            phase3_data
        )

        # Combine with weights
        composite_score = (
            hot_streak_score * WEIGHT_HOT_STREAK +
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
            volatility_score=volatility_score,
            opponent_defense_score=opponent_score,
            opportunity_score=opportunity_score,
            historical_rate_score=historical_score,
            pts_vs_season_zscore=z_score,
            points_std=std,
            explosion_ratio=explosion,
            opponent_def_rating=def_rating,
            injured_teammates_ppg=injured_ppg,
            historical_breakout_rate=hist_rate,
        )

        logger.debug(
            f"Breakout risk: score={composite_score:.1f}, "
            f"hot={hot_streak_score:.0f}, vol={volatility_score:.0f}, "
            f"def={opponent_score:.0f}, opp={opportunity_score:.0f}, "
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

    def _calculate_volatility_component(
        self,
        phase4_data: Dict[str, Any],
        phase3_data: Dict[str, Any]
    ) -> Tuple[float, float, float]:
        """
        Calculate volatility component based on scoring consistency.

        Combines:
        - Standard deviation of recent points
        - Explosion ratio: max(L5) / season_avg

        Returns:
            Tuple of (component_score 0-100, std_dev, explosion_ratio)
        """
        # Get standard deviation
        std = phase4_data.get('points_std_last_10')
        if std is None:
            std = phase3_data.get('points_std_last_10', 5.0)  # Default to league avg
        std = float(std) if std else 5.0

        # Calculate explosion ratio
        last_10_games = phase3_data.get('last_10_games', [])
        season_avg = phase4_data.get('points_avg_season')
        if season_avg is None:
            season_avg = phase3_data.get('points_avg_season', 12.0)
        season_avg = float(season_avg) if season_avg else 12.0

        explosion_ratio = 1.0
        if last_10_games and len(last_10_games) >= 3 and season_avg > 0:
            # Get last 5 games for max calculation
            last_5_points = [g.get('points', 0) or 0 for g in last_10_games[:5]]
            if last_5_points:
                max_points = max(last_5_points)
                explosion_ratio = max_points / season_avg

        # Score from std (0-50 points): higher std = higher score
        if std >= VOLATILITY_THRESHOLDS['high_std']:
            std_score = 50.0
        elif std >= VOLATILITY_THRESHOLDS['medium_std']:
            std_score = 35.0
        elif std >= VOLATILITY_THRESHOLDS['low_std']:
            std_score = 20.0
        else:
            std_score = 10.0

        # Score from explosion ratio (0-50 points): higher ratio = higher score
        if explosion_ratio >= VOLATILITY_THRESHOLDS['explosion_ratio_high']:
            explosion_score = 50.0
        elif explosion_ratio >= VOLATILITY_THRESHOLDS['explosion_ratio_medium']:
            explosion_score = 30.0
        else:
            explosion_score = 10.0

        # Combine (weight std slightly more as it's more stable)
        total_score = std_score * 0.6 + explosion_score * 0.4

        return round(total_score, 2), round(std, 2), round(explosion_ratio, 3)

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
        team_context: Optional[Dict[str, Any]]
    ) -> Tuple[float, float]:
        """
        Calculate opportunity component based on teammate injuries.

        More injured PPG from teammates = more opportunity = higher breakout risk.

        Returns:
            Tuple of (component_score 0-100, injured_teammates_ppg)
        """
        if team_context is None:
            return 20.0, 0.0  # Low default if no context

        injured_ppg = team_context.get('injured_teammates_ppg', 0.0)
        injured_ppg = float(injured_ppg) if injured_ppg else 0.0

        # Score based on how many points are "up for grabs"
        if injured_ppg >= 30.0:
            score = 100.0  # Multiple starters out
        elif injured_ppg >= 20.0:
            score = 80.0   # Star player out
        elif injured_ppg >= 12.0:
            score = 50.0   # Starter out
        elif injured_ppg >= 5.0:
            score = 30.0   # Role player out
        else:
            score = 10.0   # Team healthy

        return round(score, 2), round(injured_ppg, 1)

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
