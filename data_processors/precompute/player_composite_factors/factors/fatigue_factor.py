"""Fatigue composite factor calculator."""

from typing import Optional
import pandas as pd
from .base_factor import BaseFactor


class FatigueFactor(BaseFactor):
    """Calculate fatigue score based on rest, workload, and age.

    Higher score = better rested (less fatigued).

    Factors:
    - Days rest (0 = B2B, 1-2 = normal, 3+ = bonus)
    - Recent workload (games & minutes in last 7 days)
    - Recent back-to-backs (last 14 days)
    - Player age (30+ penalty, 35+ bigger penalty)

    Score range: 0-100 (internal)
    Adjustment range: -5.0 to 0.0
    """

    @property
    def name(self) -> str:
        return 'fatigue_score'

    @property
    def context_field(self) -> str:
        return 'fatigue_context_json'

    def calculate(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> float:
        """Calculate fatigue adjustment (-5.0 to 0.0).

        Args:
            player_row: Player context data

        Returns:
            Fatigue adjustment value
        """
        fatigue_score = self._calculate_fatigue_score(player_row)
        return self._score_to_adjustment(fatigue_score)

    def build_context(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> dict:
        """Build fatigue context for debugging.

        Args:
            player_row: Player context data

        Returns:
            Dictionary with fatigue breakdown
        """
        fatigue_score = self._calculate_fatigue_score(player_row)

        days_rest = self._safe_int(player_row.get('days_rest'), 0)
        back_to_back = self._safe_bool(player_row.get('back_to_back'), False)

        penalties = []
        bonuses = []

        if back_to_back:
            penalties.append("back_to_back: -15")
        if self._safe_int(player_row.get('games_in_last_7_days'), 0) >= 4:
            penalties.append("frequent_games: -10")
        if self._safe_float(player_row.get('minutes_in_last_7_days'), 0.0) > 240:
            penalties.append("heavy_minutes: -10")
        if self._safe_int(player_row.get('player_age'), 0) >= 35:
            penalties.append("veteran_age: -10")

        if days_rest >= 3:
            bonuses.append("extra_rest: +5")

        return {
            'days_rest': days_rest,
            'back_to_back': back_to_back,
            'games_last_7': self._safe_int(player_row.get('games_in_last_7_days'), 0),
            'minutes_last_7': self._safe_float(player_row.get('minutes_in_last_7_days'), 0.0),
            'avg_minutes_pg_last_7': self._safe_float(player_row.get('avg_minutes_per_game_last_7'), 0.0),
            'back_to_backs_last_14': self._safe_int(player_row.get('back_to_backs_last_14_days'), 0),
            'player_age': self._safe_int(player_row.get('player_age'), 25),
            'penalties_applied': penalties,
            'bonuses_applied': bonuses,
            'final_score': self._safe_int(fatigue_score, 0)
        }

    def get_range(self) -> tuple[float, float]:
        """Get expected adjustment range."""
        return (-5.0, 0.0)

    def _calculate_fatigue_score(self, player_row: pd.Series) -> int:
        """Calculate raw fatigue score (0-100).

        Returns:
            int: Fatigue score (0-100), clamped to range
        """
        score = 100  # Start at baseline

        # Days rest impact
        days_rest = self._safe_int(player_row.get('days_rest'), 1)
        back_to_back = self._safe_bool(player_row.get('back_to_back'), False)

        if back_to_back:
            score -= 15  # Heavy penalty for B2B
        elif days_rest >= 3:
            score += 5  # Bonus for extra rest

        # Recent workload
        games_last_7 = self._safe_int(player_row.get('games_in_last_7_days'), 3)
        minutes_last_7 = self._safe_float(player_row.get('minutes_in_last_7_days'), 200.0)
        avg_mpg_last_7 = self._safe_float(player_row.get('avg_minutes_per_game_last_7'), 30.0)

        if games_last_7 >= 4:
            score -= 10  # Playing frequently

        if minutes_last_7 > 240:
            score -= 10  # Heavy minutes load

        if avg_mpg_last_7 > 35:
            score -= 8  # Playing long stretches

        # Recent B2Bs
        recent_b2bs = self._safe_int(player_row.get('back_to_backs_last_14_days'), 0)
        if recent_b2bs >= 2:
            score -= 12  # Multiple recent B2Bs
        elif recent_b2bs == 1:
            score -= 5

        # Age factor
        age = self._safe_int(player_row.get('player_age'), 25)
        if age >= 35:
            score -= 10  # Veteran penalty
        elif age >= 30:
            score -= 5

        # Clamp to 0-100
        return max(0, min(100, score))

    def _score_to_adjustment(self, fatigue_score: int) -> float:
        """Convert fatigue score (0-100) to adjustment (-5.0 to 0.0).

        Linear mapping:
        - 100 (fresh) → 0.0 adjustment
        - 80 → -1.0
        - 50 → -2.5
        - 0 (exhausted) → -5.0 adjustment

        Formula: (fatigue_score - 100) / 20
        """
        return (fatigue_score - 100) / 20.0

    # Helper methods
    def _safe_int(self, value, default: int = 0) -> int:
        """Safely convert value to int."""
        if value is None or pd.isna(value):
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def _safe_float(self, value, default: float = 0.0) -> float:
        """Safely convert value to float."""
        if value is None or pd.isna(value):
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def _safe_bool(self, value, default: bool = False) -> bool:
        """Safely convert value to bool."""
        if value is None or pd.isna(value):
            return default
        return bool(value)
