"""Team aggregator for team_offense_game_summary data.

Aggregates team context metrics from recent games:
- Team pace (last 10 games average)
- Team offensive rating (last 10 games average)
"""

import pandas as pd
from typing import Dict, Optional


class TeamAggregator:
    """Aggregate team offense statistics."""

    @staticmethod
    def aggregate(team_games: pd.DataFrame) -> Dict[str, Optional[float]]:
        """Aggregate team stats from recent games.

        Args:
            team_games: DataFrame with team game-level stats (last 10 games)

        Returns:
            Dictionary with aggregated team metrics
        """
        # Team context (last 10 games averages)
        # Round to 4 decimal places for BigQuery NUMERIC compatibility
        team_pace_last_10 = round(float(team_games['pace'].mean()), 4) if len(team_games) > 0 else None
        team_off_rating_last_10 = round(float(team_games['offensive_rating'].mean()), 4) if len(team_games) > 0 else None

        return {
            'team_pace_last_10': team_pace_last_10,
            'team_off_rating_last_10': team_off_rating_last_10,
        }

    @staticmethod
    def get_required_columns() -> list[str]:
        """Get required columns from team_offense_game_summary."""
        return [
            'pace',
            'offensive_rating',
        ]
