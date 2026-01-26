"""Shot zone mismatch factor calculator."""

from typing import Optional
import pandas as pd
from .base_factor import BaseFactor


class ShotZoneMismatchFactor(BaseFactor):
    """Calculate shot zone mismatch based on player strength vs opponent defense.

    Positive = favorable matchup (player's strength vs defense weakness)
    Negative = unfavorable matchup (player's strength vs defense strength)

    Logic:
    1. Identify player's primary scoring zone
    2. Get opponent's defense rating in that zone
    3. Weight by player's usage of that zone
    4. Apply extreme matchup bonus if diff > 5.0

    Adjustment range: -10.0 to +10.0
    """

    @property
    def name(self) -> str:
        return 'shot_zone_mismatch_score'

    @property
    def context_field(self) -> str:
        return 'shot_zone_context_json'

    def calculate(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> float:
        """Calculate shot zone mismatch score (-10.0 to +10.0).

        Args:
            player_row: Player context data (unused)
            player_shot: Player shot zone data
            team_defense: Team defense data

        Returns:
            Mismatch score, 0.0 if data missing
        """
        if player_shot is None or team_defense is None:
            return 0.0

        # Get player's primary zone and usage rate
        primary_zone = player_shot.get('primary_scoring_zone', 'paint')

        # Map zone to usage rate field
        zone_rate_map = {
            'paint': 'paint_rate_last_10',
            'mid_range': 'mid_range_rate_last_10',
            'perimeter': 'three_pt_rate_last_10'
        }

        zone_rate_field = zone_rate_map.get(primary_zone, 'paint_rate_last_10')
        zone_usage_pct = self._safe_float(player_shot.get(zone_rate_field), 50.0)

        # Get opponent's defense rating in that zone
        defense_field_map = {
            'paint': 'paint_defense_vs_league_avg',
            'mid_range': 'mid_range_defense_vs_league_avg',
            'perimeter': 'three_pt_defense_vs_league_avg'
        }

        defense_field = defense_field_map.get(primary_zone, 'paint_defense_vs_league_avg')
        defense_rating = self._safe_float(team_defense.get(defense_field), 0.0)

        # Calculate mismatch
        # Positive defense rating = weak defense (good for offense)
        # Negative defense rating = strong defense (bad for offense)
        base_mismatch = defense_rating

        # Weight by zone usage (50%+ usage = full weight, lower = reduced)
        usage_weight = min(zone_usage_pct / 50.0, 1.0)
        weighted_mismatch = base_mismatch * usage_weight

        # Apply extreme matchup bonus (20% boost if abs > 5.0)
        if abs(weighted_mismatch) > 5.0:
            weighted_mismatch *= 1.2

        # Clamp to -10.0 to +10.0
        return max(-10.0, min(10.0, weighted_mismatch))

    def build_context(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series] = None,
        team_defense: Optional[pd.Series] = None
    ) -> dict:
        """Build shot zone mismatch context for debugging.

        Args:
            player_row: Player context data (unused)
            player_shot: Player shot zone data
            team_defense: Team defense data

        Returns:
            Dictionary with mismatch breakdown
        """
        if player_shot is None or team_defense is None:
            return {'missing_data': True}

        score = self.calculate(player_row, player_shot, team_defense)

        primary_zone_raw = player_shot.get('primary_scoring_zone')
        primary_zone = str(primary_zone_raw) if primary_zone_raw is not None and not pd.isna(primary_zone_raw) else 'unknown'

        zone_rate_map = {
            'paint': 'paint_rate_last_10',
            'mid_range': 'mid_range_rate_last_10',
            'perimeter': 'three_pt_rate_last_10'
        }

        rate_field = zone_rate_map.get(primary_zone, 'paint_rate_last_10')
        zone_freq = self._safe_float(player_shot.get(rate_field), 0.0)

        defense_field_map = {
            'paint': 'paint_defense_vs_league_avg',
            'mid_range': 'mid_range_defense_vs_league_avg',
            'perimeter': 'three_pt_defense_vs_league_avg'
        }

        defense_field = defense_field_map.get(primary_zone, 'paint_defense_vs_league_avg')
        defense_rating = self._safe_float(team_defense.get(defense_field), 0.0)

        mismatch_type = 'neutral'
        if score > 2.0:
            mismatch_type = 'favorable'
        elif score < -2.0:
            mismatch_type = 'unfavorable'

        weakest_zone_raw = team_defense.get('weakest_zone')
        weakest_zone = str(weakest_zone_raw) if weakest_zone_raw is not None and not pd.isna(weakest_zone_raw) else 'unknown'

        return {
            'player_primary_zone': primary_zone,
            'primary_zone_frequency': zone_freq,
            'opponent_weak_zone': weakest_zone,
            'opponent_defense_vs_league': defense_rating,
            'mismatch_type': mismatch_type,
            'final_score': self._safe_float(score, 0.0)
        }

    def get_range(self) -> tuple[float, float]:
        """Get expected adjustment range."""
        return (-10.0, 10.0)

    # Helper methods
    def _safe_float(self, value, default: float = 0.0) -> float:
        """Safely convert value to float."""
        if value is None or pd.isna(value):
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
