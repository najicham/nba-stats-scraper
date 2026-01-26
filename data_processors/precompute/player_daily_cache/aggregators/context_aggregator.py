"""Context aggregator for upcoming_player_game_context data.

Extracts fatigue metrics and demographics from player context:
- Games in last N days
- Minutes in last N days
- Back-to-back games count
- Average minutes per game
- Fourth quarter minutes
- Player age
"""

import pandas as pd
from typing import Dict, Optional


class ContextAggregator:
    """Extract player context data (no aggregation - direct copy)."""

    @staticmethod
    def aggregate(context_row: pd.Series) -> Dict[str, Optional[float]]:
        """Extract fatigue and demographic data from context row.

        Args:
            context_row: Single row of upcoming_player_game_context

        Returns:
            Dictionary with fatigue metrics and demographics
        """
        # Fatigue metrics (direct copy from context)
        games_in_last_7_days = int(context_row['games_in_last_7_days']) if pd.notna(context_row['games_in_last_7_days']) else None
        games_in_last_14_days = int(context_row['games_in_last_14_days']) if pd.notna(context_row['games_in_last_14_days']) else None
        minutes_in_last_7_days = int(context_row['minutes_in_last_7_days']) if pd.notna(context_row['minutes_in_last_7_days']) else None
        minutes_in_last_14_days = int(context_row['minutes_in_last_14_days']) if pd.notna(context_row['minutes_in_last_14_days']) else None
        back_to_backs_last_14_days = int(context_row['back_to_backs_last_14_days']) if pd.notna(context_row['back_to_backs_last_14_days']) else None
        avg_minutes_per_game_last_7 = round(float(context_row['avg_minutes_per_game_last_7']), 4) if pd.notna(context_row['avg_minutes_per_game_last_7']) else None
        fourth_quarter_minutes_last_7 = int(context_row['fourth_quarter_minutes_last_7']) if pd.notna(context_row['fourth_quarter_minutes_last_7']) else None

        # Player demographics
        player_age = int(context_row['player_age']) if pd.notna(context_row['player_age']) else None

        return {
            # Fatigue metrics
            'games_in_last_7_days': games_in_last_7_days,
            'games_in_last_14_days': games_in_last_14_days,
            'minutes_in_last_7_days': minutes_in_last_7_days,
            'minutes_in_last_14_days': minutes_in_last_14_days,
            'back_to_backs_last_14_days': back_to_backs_last_14_days,
            'avg_minutes_per_game_last_7': avg_minutes_per_game_last_7,
            'fourth_quarter_minutes_last_7': fourth_quarter_minutes_last_7,

            # Demographics
            'player_age': player_age,
        }

    @staticmethod
    def get_required_columns() -> list[str]:
        """Get required columns from upcoming_player_game_context."""
        return [
            'games_in_last_7_days',
            'games_in_last_14_days',
            'minutes_in_last_7_days',
            'minutes_in_last_14_days',
            'back_to_backs_last_14_days',
            'avg_minutes_per_game_last_7',
            'fourth_quarter_minutes_last_7',
            'player_age',
        ]
