"""
Personnel Tracker - Roster and Injury Tracking

Tracks player availability and injury status for teams.

Extracted from upcoming_team_game_context_processor.py for maintainability.
"""

import logging
import pandas as pd
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class PersonnelTracker:
    """
    Tracker for team personnel availability.

    Analyzes injury reports to calculate:
    - Players out count
    - Questionable players count
    """

    def __init__(self, injury_data: Optional[pd.DataFrame]):
        """
        Initialize the personnel tracker.

        Args:
            injury_data: DataFrame with injury reports or None
        """
        self.injury_data = injury_data

    def calculate_personnel_context(
        self,
        game: pd.Series,
        team_abbr: str
    ) -> Dict:
        """
        Calculate personnel availability from injury reports.

        Args:
            game: Game row from schedule
            team_abbr: Team abbreviation

        Returns:
            Dict with personnel metrics
        """

        if self.injury_data is None or len(self.injury_data) == 0:
            return {
                'starters_out_count': 0,
                'questionable_players_count': 0
            }

        game_date = game['game_date'].date()

        # Get team's injury data for this game
        team_injuries = self.injury_data[
            (self.injury_data['game_date'] == game_date) &
            (self.injury_data['team'] == team_abbr)
        ]

        if len(team_injuries) == 0:
            return {
                'starters_out_count': 0,
                'questionable_players_count': 0
            }

        # Count by status
        out_count = len(team_injuries[team_injuries['injury_status'] == 'out'])
        questionable_count = len(team_injuries[
            team_injuries['injury_status'].isin(['questionable', 'doubtful'])
        ])

        return {
            'starters_out_count': int(out_count),
            'questionable_players_count': int(questionable_count)
        }
