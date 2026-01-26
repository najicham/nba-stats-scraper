"""
Betting Context - Team Betting Context Calculator

Calculates betting context including spreads, totals, and line movement.

Extracted from upcoming_team_game_context_processor.py for maintainability.
"""

import logging
import pandas as pd
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class BettingContext:
    """
    Calculator for team betting context.

    Analyzes betting lines to calculate:
    - Game spreads
    - Game totals
    - Line movement
    - Source tracking
    """

    # Team name mapping for betting lines
    TEAM_NAME_MAP = {
        'Atlanta Hawks': 'ATL',
        'Boston Celtics': 'BOS',
        'Brooklyn Nets': 'BKN',
        'Charlotte Hornets': 'CHA',
        'Chicago Bulls': 'CHI',
        'Cleveland Cavaliers': 'CLE',
        'Dallas Mavericks': 'DAL',
        'Denver Nuggets': 'DEN',
        'Detroit Pistons': 'DET',
        'Golden State Warriors': 'GSW',
        'Houston Rockets': 'HOU',
        'Indiana Pacers': 'IND',
        'LA Clippers': 'LAC',
        'Los Angeles Clippers': 'LAC',
        'Los Angeles Lakers': 'LAL',
        'Memphis Grizzlies': 'MEM',
        'Miami Heat': 'MIA',
        'Milwaukee Bucks': 'MIL',
        'Minnesota Timberwolves': 'MIN',
        'New Orleans Pelicans': 'NOP',
        'New York Knicks': 'NYK',
        'Oklahoma City Thunder': 'OKC',
        'Orlando Magic': 'ORL',
        'Philadelphia 76ers': 'PHI',
        'Phoenix Suns': 'PHX',
        'Portland Trail Blazers': 'POR',
        'Sacramento Kings': 'SAC',
        'San Antonio Spurs': 'SAS',
        'Toronto Raptors': 'TOR',
        'Utah Jazz': 'UTA',
        'Washington Wizards': 'WAS'
    }

    def __init__(self, betting_lines: Optional[pd.DataFrame]):
        """
        Initialize the betting context calculator.

        Args:
            betting_lines: DataFrame with betting lines or None
        """
        self.betting_lines = betting_lines

    def calculate_betting_context(
        self,
        game: pd.Series,
        team_abbr: str,
        home_game: bool
    ) -> Dict:
        """
        Calculate betting context from odds API data.

        Handles team name mapping: "Los Angeles Lakers" → "LAL"

        Args:
            game: Game row from schedule
            team_abbr: Team abbreviation
            home_game: Whether team is home

        Returns:
            Dict with betting context
        """

        if self.betting_lines is None or len(self.betting_lines) == 0:
            return {
                'game_spread': None,
                'game_total': None,
                'game_spread_source': None,
                'game_total_source': None,
                'spread_movement': None,
                'total_movement': None,
                'betting_lines_updated_at': None
            }

        game_date = game['game_date'].date()
        game_id = game.get('game_id')

        # Filter lines for this game
        game_lines = self.betting_lines[
            (self.betting_lines['game_date'] == game_date)
        ]

        # Additional filtering by game_id if available
        if game_id and 'game_id' in game_lines.columns:
            game_lines = game_lines[game_lines['game_id'] == game_id]

        if len(game_lines) == 0:
            return {
                'game_spread': None,
                'game_total': None,
                'game_spread_source': None,
                'game_total_source': None,
                'spread_movement': None,
                'total_movement': None,
                'betting_lines_updated_at': None
            }

        # Prioritize DraftKings, fallback to FanDuel
        preferred_books = ['draftkings', 'fanduel']

        spread = None
        spread_source = None
        total = None
        total_source = None
        lines_timestamp = None

        for bookmaker in preferred_books:
            book_lines = game_lines[game_lines['bookmaker_key'] == bookmaker]

            if len(book_lines) == 0:
                continue

            # Get spread
            if spread is None:
                spread_lines = book_lines[book_lines['market_key'] == 'spreads']

                for _, line in spread_lines.iterrows():
                    outcome_name = line['outcome_name']

                    # Map team name to abbreviation
                    if self.team_name_matches(outcome_name, team_abbr):
                        spread = float(line['outcome_point'])
                        spread_source = bookmaker
                        lines_timestamp = line['snapshot_timestamp']
                        break

            # Get total
            if total is None:
                total_lines = book_lines[book_lines['market_key'] == 'totals']
                over_lines = total_lines[total_lines['outcome_name'] == 'Over']

                if len(over_lines) > 0:
                    total = float(over_lines.iloc[0]['outcome_point'])
                    total_source = bookmaker
                    if lines_timestamp is None:
                        lines_timestamp = over_lines.iloc[0]['snapshot_timestamp']

            # Stop if we found both
            if spread is not None and total is not None:
                break

        return {
            'game_spread': spread,
            'game_total': total,
            'game_spread_source': spread_source,
            'game_total_source': total_source,
            'spread_movement': None,  # TODO: Implement with opening line tracking
            'total_movement': None,   # TODO: Implement with opening line tracking
            'betting_lines_updated_at': lines_timestamp.isoformat() if lines_timestamp else None
        }

    def team_name_matches(self, outcome_name: str, team_abbr: str) -> bool:
        """
        Check if betting line outcome name matches team abbreviation.

        Handles mapping: "Los Angeles Lakers" → "LAL"

        Args:
            outcome_name: Team name from betting line
            team_abbr: Team abbreviation

        Returns:
            True if names match
        """

        # Strategy 1: Exact abbreviation match
        if outcome_name == team_abbr:
            return True

        # Strategy 2: Full name mapping
        if outcome_name in self.TEAM_NAME_MAP:
            return self.TEAM_NAME_MAP[outcome_name] == team_abbr

        # Strategy 3: Contains abbreviation
        if team_abbr in outcome_name:
            return True

        return False
