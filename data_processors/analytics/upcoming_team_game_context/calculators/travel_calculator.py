"""
Travel Calculator - Team Travel Metrics

Calculates travel distance for teams based on game locations.

Extracted from upcoming_team_game_context_processor.py for maintainability.
"""

import logging
import pandas as pd
from typing import Dict

logger = logging.getLogger(__name__)


class TravelCalculator:
    """
    Calculator for team travel metrics.

    Calculates:
    - Travel miles between games
    """

    def __init__(self, schedule_data: pd.DataFrame, travel_distances: dict):
        """
        Initialize the travel calculator.

        Args:
            schedule_data: DataFrame with team schedule
            travel_distances: Dict mapping "FROM_TO" to distance in miles
        """
        self.schedule_data = schedule_data
        self.travel_distances = travel_distances

    def calculate_travel_context(
        self,
        game: pd.Series,
        team_abbr: str,
        home_game: bool,
        fatigue_context: Dict
    ) -> Dict:
        """
        Calculate travel distance to this game.

        Args:
            game: Game row from schedule
            team_abbr: Team abbreviation
            home_game: Whether team is home
            fatigue_context: Fatigue context with game history

        Returns:
            Dict with travel metrics
        """

        if home_game:
            return {'travel_miles': 0}

        # For away games, need last opponent location
        game_date = game['game_date']

        team_games = self.schedule_data[
            (
                (self.schedule_data['home_team_abbr'] == team_abbr) |
                (self.schedule_data['away_team_abbr'] == team_abbr)
            ) &
            (self.schedule_data['game_date'] < game_date)
        ].sort_values('game_date')

        if len(team_games) == 0:
            return {'travel_miles': 0}

        # Last game location
        last_game = team_games.iloc[-1]
        if last_game['home_team_abbr'] == team_abbr:
            last_location = team_abbr  # Was at home
        else:
            last_location = last_game['home_team_abbr']  # Was at opponent's arena

        # Current game location (opponent's arena for away game)
        current_location = game['home_team_abbr']

        # Lookup travel distance
        travel_key = f"{last_location}_{current_location}"
        travel_miles = self.travel_distances.get(travel_key, 0)

        return {'travel_miles': int(travel_miles)}
