"""Pace factor calculator."""

from typing import Optional
import pandas as pd
from .base_factor import BaseFactor


class PaceFactor(BaseFactor):
    """Calculate pace adjustment based on game pace differential.

    Faster pace = more possessions = more opportunities = positive
    Slower pace = fewer possessions = fewer opportunities = negative

    Formula: pace_differential / 2.0
    (Scaled down from typical 4-6 point differentials)

    Adjustment range: -3.0 to +3.0
    """

    # League constants
    LEAGUE_AVG_PACE = 100.0  # Baseline NBA pace

    @property
    def name(self) -> str:
        return 'pace_score'

    @property
    def context_field(self) -> str:
        return 'pace_context_json'

    def calculate(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> float:
        """Calculate pace score (-3.0 to +3.0).

        Args:
            player_row: Player context data

        Returns:
            Pace adjustment value
        """
        pace_diff = self._safe_float(player_row.get('pace_differential'), 0.0)

        # Simple scaling: divide by 2 to get reasonable adjustment range
        pace_score = pace_diff / 2.0

        # Clamp to -3.0 to +3.0
        return max(-3.0, min(3.0, pace_score))

    def build_context(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> dict:
        """Build pace context for debugging.

        Args:
            player_row: Player context data

        Returns:
            Dictionary with pace breakdown
        """
        score = self.calculate(player_row, player_shot, team_defense)

        pace_diff = self._safe_float(player_row.get('pace_differential'), 0.0)
        opponent_pace = self._safe_float(player_row.get('opponent_pace_last_10'), self.LEAGUE_AVG_PACE)

        pace_env = 'normal'
        if pace_diff > 2.0:
            pace_env = 'fast'
        elif pace_diff < -2.0:
            pace_env = 'slow'

        return {
            'pace_differential': pace_diff,
            'opponent_pace_last_10': opponent_pace,
            'league_avg_pace': self.LEAGUE_AVG_PACE,
            'pace_environment': pace_env,
            'final_score': self._safe_float(score, 0.0)
        }

    def get_range(self) -> tuple[float, float]:
        """Get expected adjustment range."""
        return (-3.0, 3.0)

    # Helper methods
    def _safe_float(self, value, default: float = 0.0) -> float:
        """Safely convert value to float."""
        if value is None or pd.isna(value):
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
