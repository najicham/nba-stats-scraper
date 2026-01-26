"""
Performance Analyzer - Team Performance and Momentum

Analyzes recent team performance including win/loss streaks and game margins.

Extracted from upcoming_team_game_context_processor.py for maintainability.
"""

import logging
import pandas as pd
from typing import Dict

logger = logging.getLogger(__name__)


class PerformanceAnalyzer:
    """
    Analyzer for team performance and momentum.

    Analyzes recent games to calculate:
    - Win/loss streaks
    - Last game result and margin
    """

    def __init__(self, schedule_data: pd.DataFrame):
        """
        Initialize the performance analyzer.

        Args:
            schedule_data: DataFrame with team schedule and results
        """
        self.schedule_data = schedule_data

    def calculate_momentum_context(
        self,
        game: pd.Series,
        team_abbr: str
    ) -> Dict:
        """
        Calculate recent performance and momentum.

        Args:
            game: Game row from schedule
            team_abbr: Team abbreviation

        Returns:
            Dict with momentum metrics
        """

        game_date = game['game_date']

        # Get team's completed games before this one
        team_games = self.schedule_data[
            (
                (self.schedule_data['home_team_abbr'] == team_abbr) |
                (self.schedule_data['away_team_abbr'] == team_abbr)
            ) &
            (self.schedule_data['game_date'] < game_date) &
            (self.schedule_data['game_status'] == 3) &  # Final
            (self.schedule_data['winning_team_abbr'].notna())  # Has result
        ].sort_values('game_date', ascending=False)

        if len(team_games) == 0:
            return {
                'team_win_streak_entering': 0,
                'team_loss_streak_entering': 0,
                'last_game_margin': None,
                'last_game_result': None
            }

        # Last game result
        last_game = team_games.iloc[0]
        last_game_winner = last_game['winning_team_abbr']
        last_game_won = last_game_winner == team_abbr

        # Calculate margin
        if pd.notna(last_game['home_team_score']) and pd.notna(last_game['away_team_score']):
            if last_game['home_team_abbr'] == team_abbr:
                margin = int(last_game['home_team_score'] - last_game['away_team_score'])
            else:
                margin = int(last_game['away_team_score'] - last_game['home_team_score'])
        else:
            margin = None

        # Calculate streaks
        win_streak = 0
        loss_streak = 0

        for _, g in team_games.iterrows():
            winner = g['winning_team_abbr']
            if pd.isna(winner):
                break

            if winner == team_abbr:
                if loss_streak > 0:
                    break
                win_streak += 1
            else:
                if win_streak > 0:
                    break
                loss_streak += 1

        return {
            'team_win_streak_entering': int(win_streak),
            'team_loss_streak_entering': int(loss_streak),
            'last_game_margin': margin,
            'last_game_result': 'W' if last_game_won else 'L'
        }
