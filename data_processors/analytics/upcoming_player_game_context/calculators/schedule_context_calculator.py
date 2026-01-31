"""
Schedule Context Calculator - Forward-Looking Schedule Features

Calculates schedule-based features for player game context:
- Next game rest days (how many days until the player's next game after this one)
- Games in next 7 days
- Next opponent win percentage
- Next game is primetime
- Opponent schedule asymmetry (opponent's rest days, games in next 7 days, etc.)

These features capture schedule density and fatigue outlook which can affect:
- Potential for rest/load management
- Coach's rotation decisions
- Player effort allocation

Created: 2026-01-30
"""

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional

import pandas as pd
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded

logger = logging.getLogger(__name__)


class ScheduleContextCalculator:
    """
    Calculator for schedule-based context features.

    Uses schedule data to compute forward-looking features about
    upcoming games and opponent schedule asymmetry.
    """

    def __init__(self, bq_client: bigquery.Client, project_id: str):
        """
        Initialize the calculator.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
        """
        self.bq_client = bq_client
        self.project_id = project_id
        # Cache for team schedule data
        self._team_schedules: Dict[str, pd.DataFrame] = {}

    def get_schedule_context(
        self,
        team_abbr: str,
        game_date: date,
        schedule_data: Dict
    ) -> Dict:
        """
        Get forward-looking schedule context for a team's game.

        Args:
            team_abbr: Team abbreviation (e.g., 'LAL')
            game_date: Date of the current game
            schedule_data: Dict of schedule data keyed by game_id

        Returns:
            Dict with schedule context fields:
            - next_game_days_rest: Days until team's next game (0 if B2B)
            - games_in_next_7_days: Number of games in 7 days following this game
            - next_opponent_win_pct: Win percentage of next opponent (None if no data)
            - next_game_is_primetime: Whether next game is primetime
        """
        # Convert schedule_data values to a DataFrame for this team's games
        team_schedule = self._get_team_schedule(team_abbr, schedule_data)

        if team_schedule.empty:
            return {
                'next_game_days_rest': None,
                'games_in_next_7_days': 0,
                'next_opponent_win_pct': None,
                'next_game_is_primetime': False
            }

        # Sort by game_date
        team_schedule = team_schedule.sort_values('game_date')

        # Find games after the current game
        future_games = team_schedule[team_schedule['game_date'] > game_date]

        if future_games.empty:
            return {
                'next_game_days_rest': None,
                'games_in_next_7_days': 0,
                'next_opponent_win_pct': None,
                'next_game_is_primetime': False
            }

        # Next game info
        next_game = future_games.iloc[0]
        next_game_date = next_game['game_date']
        if isinstance(next_game_date, str):
            next_game_date = date.fromisoformat(next_game_date)

        next_game_days_rest = (next_game_date - game_date).days

        # Games in next 7 days (after game_date)
        window_end = game_date + timedelta(days=7)
        games_next_7 = future_games[
            (future_games['game_date'] > game_date) &
            (future_games['game_date'] <= window_end)
        ]
        games_in_next_7_days = len(games_next_7)

        # Next game is primetime
        next_game_is_primetime = bool(next_game.get('is_primetime', False))

        # Next opponent win percentage (requires querying team standings)
        next_opponent = self._get_opponent_from_game(team_abbr, next_game)
        next_opponent_win_pct = self._get_team_win_pct(next_opponent, game_date) if next_opponent else None

        return {
            'next_game_days_rest': next_game_days_rest,
            'games_in_next_7_days': games_in_next_7_days,
            'next_opponent_win_pct': next_opponent_win_pct,
            'next_game_is_primetime': next_game_is_primetime
        }

    def get_opponent_schedule_asymmetry(
        self,
        team_abbr: str,
        opponent_abbr: str,
        game_date: date,
        schedule_data: Dict
    ) -> Dict:
        """
        Get opponent's schedule asymmetry metrics.

        Compares the scheduling situation between two teams - asymmetry
        where one team is rested and the other is fatigued can be predictive.

        Args:
            team_abbr: Player's team abbreviation
            opponent_abbr: Opponent team abbreviation
            game_date: Date of the current game
            schedule_data: Dict of schedule data keyed by game_id

        Returns:
            Dict with opponent asymmetry fields:
            - opponent_days_rest: Opponent's days rest coming into this game
            - opponent_games_in_next_7_days: Opponent's games in next 7 days
            - opponent_next_game_days_rest: Days until opponent's next game
        """
        # Get opponent's schedule
        opp_schedule = self._get_team_schedule(opponent_abbr, schedule_data)

        if opp_schedule.empty:
            return {
                'opponent_days_rest': None,
                'opponent_games_in_next_7_days': 0,
                'opponent_next_game_days_rest': None
            }

        opp_schedule = opp_schedule.sort_values('game_date')

        # Opponent's days rest (games before this one)
        past_games = opp_schedule[opp_schedule['game_date'] < game_date]
        if not past_games.empty:
            last_game_date = past_games.iloc[-1]['game_date']
            if isinstance(last_game_date, str):
                last_game_date = date.fromisoformat(last_game_date)
            opponent_days_rest = (game_date - last_game_date).days
        else:
            opponent_days_rest = None

        # Opponent's games in next 7 days
        future_games = opp_schedule[opp_schedule['game_date'] > game_date]
        window_end = game_date + timedelta(days=7)
        opp_games_next_7 = future_games[
            (future_games['game_date'] > game_date) &
            (future_games['game_date'] <= window_end)
        ]
        opponent_games_in_next_7_days = len(opp_games_next_7)

        # Opponent's next game days rest
        if not future_games.empty:
            next_game_date = future_games.iloc[0]['game_date']
            if isinstance(next_game_date, str):
                next_game_date = date.fromisoformat(next_game_date)
            opponent_next_game_days_rest = (next_game_date - game_date).days
        else:
            opponent_next_game_days_rest = None

        return {
            'opponent_days_rest': opponent_days_rest,
            'opponent_games_in_next_7_days': opponent_games_in_next_7_days,
            'opponent_next_game_days_rest': opponent_next_game_days_rest
        }

    def _get_team_schedule(self, team_abbr: str, schedule_data: Dict) -> pd.DataFrame:
        """
        Extract all games for a team from schedule_data.

        Args:
            team_abbr: Team abbreviation
            schedule_data: Dict of schedule data keyed by game_id

        Returns:
            DataFrame with team's games
        """
        team_games = []
        seen_dates = set()  # Avoid duplicates from multiple game_id formats

        for game_id, game_info in schedule_data.items():
            if not isinstance(game_info, dict):
                continue

            home_team = game_info.get('home_team_abbr')
            away_team = game_info.get('away_team_abbr')
            game_date = game_info.get('game_date')

            if team_abbr in (home_team, away_team):
                # Create a unique key to avoid duplicates
                date_key = str(game_date)
                if date_key not in seen_dates:
                    seen_dates.add(date_key)
                    team_games.append(game_info)

        if not team_games:
            return pd.DataFrame()

        df = pd.DataFrame(team_games)

        # Ensure game_date is a proper date type
        if 'game_date' in df.columns:
            df['game_date'] = pd.to_datetime(df['game_date']).dt.date

        return df

    def _get_opponent_from_game(self, team_abbr: str, game_info: pd.Series) -> Optional[str]:
        """
        Get opponent abbreviation from game info.

        Args:
            team_abbr: Our team
            game_info: Row from schedule DataFrame

        Returns:
            Opponent team abbreviation
        """
        home_team = game_info.get('home_team_abbr')
        away_team = game_info.get('away_team_abbr')

        if team_abbr == home_team:
            return away_team
        elif team_abbr == away_team:
            return home_team
        return None

    def _get_team_win_pct(self, team_abbr: str, as_of_date: date) -> Optional[float]:
        """
        Get a team's win percentage as of a specific date.

        Args:
            team_abbr: Team abbreviation
            as_of_date: Date to calculate standings as of

        Returns:
            Win percentage (0.0-1.0) or None if unavailable
        """
        if not team_abbr:
            return None

        try:
            # Query team's record from game results
            query = f"""
            WITH team_games AS (
                SELECT
                    game_date,
                    CASE
                        WHEN home_team_tricode = @team_abbr
                             AND home_team_score > away_team_score THEN 1
                        WHEN away_team_tricode = @team_abbr
                             AND away_team_score > home_team_score THEN 1
                        ELSE 0
                    END as won,
                    1 as played
                FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
                WHERE (home_team_tricode = @team_abbr OR away_team_tricode = @team_abbr)
                  AND game_date < @as_of_date
                  AND game_date >= DATE_SUB(@as_of_date, INTERVAL 90 DAY)
                  AND game_status = 3  -- Final games only
                  AND home_team_score IS NOT NULL
                  AND away_team_score IS NOT NULL
            )
            SELECT
                SUM(won) as wins,
                SUM(played) as games_played
            FROM team_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
                    bigquery.ScalarQueryParameter("as_of_date", "DATE", as_of_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                if row.games_played and row.games_played > 0:
                    return round(row.wins / row.games_played, 3)

            return None

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.debug(f"Could not get win pct for {team_abbr}: {e}")
            return None
        except (KeyError, AttributeError, TypeError) as e:
            logger.debug(f"Data error getting win pct for {team_abbr}: {e}")
            return None
