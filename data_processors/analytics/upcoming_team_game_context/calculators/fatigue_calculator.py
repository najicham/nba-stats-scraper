"""
Fatigue Calculator - Team Fatigue Metrics

Calculates team fatigue metrics including rest days, back-to-backs, and game density.

Extracted from upcoming_team_game_context_processor.py for maintainability.
"""

import logging
import pandas as pd
from datetime import date, timedelta
from typing import Dict

logger = logging.getLogger(__name__)


class FatigueCalculator:
    """
    Calculator for team fatigue metrics.

    Analyzes team schedule to calculate:
    - Days rest
    - Back-to-back games
    - Games in rolling windows (7, 14 days)
    """

    def __init__(self, schedule_data: pd.DataFrame):
        """
        Initialize the fatigue calculator.

        Args:
            schedule_data: DataFrame with team schedule
        """
        self.schedule_data = schedule_data

    def calculate_basic_context(
        self,
        game: pd.Series,
        team_abbr: str,
        home_game: bool
    ) -> Dict:
        """
        Calculate basic game context fields.

        Args:
            game: Game row from schedule
            team_abbr: Team abbreviation
            home_game: Whether team is home

        Returns:
            Dict with basic context
        """

        return {
            'is_back_to_back': False,  # Will be set in fatigue calculation
            'days_since_last_game': None,  # Will be set in fatigue calculation
            'game_number_in_season': None  # Will be set in fatigue calculation
        }

    def calculate_fatigue_context(
        self,
        game: pd.Series,
        team_abbr: str
    ) -> Dict:
        """
        Calculate fatigue metrics using team's recent schedule.

        Metrics:
        - team_days_rest: Days since last game
        - team_back_to_back: Boolean for consecutive days
        - games_in_last_7_days: Count
        - games_in_last_14_days: Count

        Args:
            game: Game row from schedule
            team_abbr: Team abbreviation

        Returns:
            Dict with fatigue metrics
        """

        game_date = game['game_date']

        # Get team's games before this one
        team_games = self.schedule_data[
            (
                (self.schedule_data['home_team_abbr'] == team_abbr) |
                (self.schedule_data['away_team_abbr'] == team_abbr)
            ) &
            (self.schedule_data['game_date'] < game_date) &
            (self.schedule_data['game_status'] == 3)  # Only completed games
        ].sort_values('game_date')

        if len(team_games) == 0:
            # First game of season
            return {
                'team_days_rest': None,
                'team_back_to_back': False,
                'games_in_last_7_days': 0,
                'games_in_last_14_days': 0,
                'is_back_to_back': False,
                'days_since_last_game': None,
                'game_number_in_season': 1
            }

        # Last game date
        last_game_date = team_games.iloc[-1]['game_date']
        days_rest = (game_date - last_game_date).days - 1  # Subtract 1 (0 = back-to-back)
        is_b2b = days_rest == 0

        # Games in windows
        seven_days_ago = game_date - timedelta(days=7)
        fourteen_days_ago = game_date - timedelta(days=14)

        games_last_7 = len(team_games[team_games['game_date'] > seven_days_ago])
        games_last_14 = len(team_games[team_games['game_date'] > fourteen_days_ago])

        return {
            'team_days_rest': int(days_rest),
            'team_back_to_back': bool(is_b2b),
            'games_in_last_7_days': int(games_last_7),
            'games_in_last_14_days': int(games_last_14),
            'is_back_to_back': bool(is_b2b),
            'days_since_last_game': int((game_date - last_game_date).days),
            'game_number_in_season': int(len(team_games) + 1)
        }
