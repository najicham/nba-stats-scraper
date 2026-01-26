"""Usage spike factor calculator."""

from typing import Optional
import pandas as pd
from .base_factor import BaseFactor


class UsageSpikeFactor(BaseFactor):
    """Calculate usage spike adjustment based on projected vs recent usage.

    Higher projected usage vs recent = more opportunities = positive
    Lower projected usage vs recent = fewer opportunities = negative

    Star teammates out amplifies positive spikes:
    - 1 star out: +15% boost
    - 2+ stars out: +30% boost

    Adjustment range: -3.0 to +3.0
    """

    @property
    def name(self) -> str:
        return 'usage_spike_score'

    @property
    def context_field(self) -> str:
        return 'usage_context_json'

    def calculate(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> float:
        """Calculate usage spike score (-3.0 to +3.0).

        Args:
            player_row: Player context data

        Returns:
            Usage spike adjustment value
        """
        projected_usage = self._safe_float(player_row.get('projected_usage_rate'), 25.0)
        baseline_usage = self._safe_float(player_row.get('avg_usage_rate_last_7_games'), 25.0)
        stars_out = self._safe_int(player_row.get('star_teammates_out'), 0)

        # Avoid division by zero
        if baseline_usage == 0:
            return 0.0

        # Calculate usage differential
        usage_diff = projected_usage - baseline_usage

        # Scale to adjustment range (typical usage diffs are 2-5 points)
        base_score = usage_diff * 0.3

        # Apply star teammates out boost (only for positive spikes)
        if stars_out > 0 and base_score > 0:
            if stars_out >= 2:
                base_score *= 1.30  # 30% boost
            else:
                base_score *= 1.15  # 15% boost

        # Clamp to -3.0 to +3.0
        return max(-3.0, min(3.0, base_score))

    def build_context(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> dict:
        """Build usage spike context for debugging.

        Args:
            player_row: Player context data

        Returns:
            Dictionary with usage breakdown
        """
        score = self.calculate(player_row, player_shot, team_defense)

        projected = self._safe_float(player_row.get('projected_usage_rate'), 0.0)
        baseline = self._safe_float(player_row.get('avg_usage_rate_last_7_games'), 0.0)
        stars_out = self._safe_int(player_row.get('star_teammates_out'), 0)

        usage_diff = projected - baseline

        trend = 'stable'
        if usage_diff > 2.0:
            trend = 'spike'
        elif usage_diff < -2.0:
            trend = 'drop'

        return {
            'projected_usage_rate': projected,
            'avg_usage_last_7': baseline,
            'usage_differential': usage_diff,
            'star_teammates_out': stars_out,
            'usage_trend': trend,
            'final_score': self._safe_float(score, 0.0)
        }

    def get_range(self) -> tuple[float, float]:
        """Get expected adjustment range."""
        return (-3.0, 3.0)

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
