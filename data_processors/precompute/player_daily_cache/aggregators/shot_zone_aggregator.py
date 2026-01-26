"""Shot zone aggregator for player_shot_zone_analysis data.

Extracts shot zone tendencies from player shot zone analysis:
- Primary scoring zone
- Paint rate (last 10 games)
- Three-point rate (last 10 games)
"""

import pandas as pd
from typing import Dict, Optional


class ShotZoneAggregator:
    """Extract shot zone tendency data (no aggregation - direct copy)."""

    @staticmethod
    def aggregate(shot_zone_row: pd.Series) -> Dict[str, Optional[float]]:
        """Extract shot zone tendencies from shot zone row.

        Args:
            shot_zone_row: Single row of player_shot_zone_analysis

        Returns:
            Dictionary with shot zone metrics
        """
        # Shot zone tendencies (direct copy from shot_zone_analysis)
        primary_scoring_zone = str(shot_zone_row['primary_scoring_zone']) if pd.notna(shot_zone_row['primary_scoring_zone']) else None
        paint_rate_last_10 = float(shot_zone_row['paint_rate_last_10']) if pd.notna(shot_zone_row['paint_rate_last_10']) else None
        three_pt_rate_last_10 = float(shot_zone_row['three_pt_rate_last_10']) if pd.notna(shot_zone_row['three_pt_rate_last_10']) else None

        return {
            'primary_scoring_zone': primary_scoring_zone,
            'paint_rate_last_10': paint_rate_last_10,
            'three_pt_rate_last_10': three_pt_rate_last_10,
        }

    @staticmethod
    def get_required_columns() -> list[str]:
        """Get required columns from player_shot_zone_analysis."""
        return [
            'primary_scoring_zone',
            'paint_rate_last_10',
            'three_pt_rate_last_10',
        ]
