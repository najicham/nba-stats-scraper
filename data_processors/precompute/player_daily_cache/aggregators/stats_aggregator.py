"""Stats aggregator for player_game_summary data.

Aggregates recent performance metrics from player game history:
- Points averaging (last 5, last 10, season)
- Minutes, usage rate, true shooting percentage (last 10)
- Assisted rate calculation
- Season totals
"""

import pandas as pd
from typing import Dict, Optional


class StatsAggregator:
    """Aggregate player game summary statistics."""

    @staticmethod
    def aggregate(player_games: pd.DataFrame) -> Dict[str, Optional[float]]:
        """Aggregate stats from player game history.

        Args:
            player_games: DataFrame with player game-level stats (sorted desc by date)

        Returns:
            Dictionary with aggregated stats
        """
        # Filter out DNP games FIRST (Session 114: Critical bug fix)
        # DNP games have either NULL points or (points=0 AND minutes=NULL)
        # Keep legitimate 0-point games (players who played but scored 0)
        played_games = player_games[
            (player_games['points'].notna()) &
            (
                (player_games['points'] > 0) |  # Non-zero points
                (player_games['minutes_played'].notna())  # Or has minutes (played)
            )
        ]

        # Get windows from PLAYED games only (excluding DNPs)
        last_5_games = played_games.head(5)
        last_10_games = played_games.head(10)

        # Points averaging (round to 4 decimal places for BigQuery NUMERIC compatibility)
        # All calculations now use played_games (DNPs excluded)
        points_avg_last_5 = round(float(last_5_games['points'].mean()), 4) if len(last_5_games) > 0 else None
        points_avg_last_10 = round(float(last_10_games['points'].mean()), 4) if len(last_10_games) > 0 else None
        points_avg_season = round(float(played_games['points'].mean()), 4) if len(played_games) > 0 else None
        points_std_last_10 = round(float(last_10_games['points'].std()), 4) if len(last_10_games) > 1 else None

        # Last 10 game averages (from played games)
        minutes_avg_last_10 = round(float(last_10_games['minutes_played'].mean()), 4) if len(last_10_games) > 0 else None
        usage_rate_last_10 = round(float(last_10_games['usage_rate'].mean()), 4) if len(last_10_games) > 0 else None
        ts_pct_last_10 = round(float(last_10_games['ts_pct'].mean()), 4) if len(last_10_games) > 0 else None

        # Season totals (from played games - DNPs don't count as games played)
        games_played_season = int(len(played_games))
        player_usage_rate_season = round(float(played_games['usage_rate'].mean()), 4) if len(played_games) > 0 else None

        # Calculate assisted rate from last 10 games (round to 9 decimal places)
        assisted_rate_last_10 = None
        if len(last_10_games) > 0:
            total_fg_makes = last_10_games['fg_makes'].sum()
            total_assisted = last_10_games['assisted_fg_makes'].sum()
            if total_fg_makes > 0:
                assisted_rate_last_10 = round(float(total_assisted / total_fg_makes), 9)

        return {
            # Points metrics
            'points_avg_last_5': points_avg_last_5,
            'points_avg_last_10': points_avg_last_10,
            'points_avg_season': points_avg_season,
            'points_std_last_10': points_std_last_10,

            # Last 10 game metrics
            'minutes_avg_last_10': minutes_avg_last_10,
            'usage_rate_last_10': usage_rate_last_10,
            'ts_pct_last_10': ts_pct_last_10,
            'assisted_rate_last_10': assisted_rate_last_10,

            # Season metrics
            'games_played_season': games_played_season,
            'player_usage_rate_season': player_usage_rate_season,
        }

    @staticmethod
    def get_required_columns() -> list[str]:
        """Get required columns from player_game_summary."""
        return [
            'points',
            'minutes_played',
            'usage_rate',
            'ts_pct',
            'fg_makes',
            'assisted_fg_makes',
        ]
