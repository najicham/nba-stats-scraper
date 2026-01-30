"""
Player Game Query Builder

Builds SQL queries for extracting players with upcoming games.
Supports two modes:
- Daily mode: Uses roster data + injuries
- Backfill mode: Uses gamebook player stats (no injuries)
"""

from datetime import date
from .shared_ctes import (
    games_today_cte,
    teams_playing_cte,
    latest_roster_per_team_cte,
    roster_players_cte,
    roster_players_with_games_cte,
    injuries_cte,
    props_cte,
    schedule_data_cte,
    gamebook_players_with_games_cte,
    daily_mode_final_select,
    backfill_mode_final_select,
)


class PlayerGameQueryBuilder:
    """
    Builds SQL queries for extracting players with games and props.

    This class encapsulates the complex SQL query logic for finding players
    who have games on a target date, combining data from:
    - Schedule data
    - Player rosters or gamebook stats
    - Prop betting lines (from multiple sources)
    - Injury reports (daily mode only)
    """

    def __init__(self, project_id: str):
        """
        Initialize the query builder.

        Args:
            project_id: Google Cloud project ID for BigQuery tables
        """
        self.project_id = project_id

    def build_daily_mode_query(self, target_date: date) -> str:
        """
        Build the daily mode query string.

        Daily mode uses roster data to find players and filters by injury status.
        This is used for live/near-live processing where roster data is available.

        Args:
            target_date: The date to query for

        Returns:
            SQL query string with parameterized date values
        """
        return f"""
        {games_today_cte(self.project_id)},
        {teams_playing_cte()},
        {latest_roster_per_team_cte(self.project_id)},
        {roster_players_cte(self.project_id)},
        {roster_players_with_games_cte()},
        {injuries_cte(self.project_id)},
        {props_cte(self.project_id)}
        {daily_mode_final_select()}
        """

    def build_backfill_mode_query(self) -> str:
        """
        Build the backfill mode query string.

        Backfill mode uses gamebook player stats to find players who actually played.
        This is used for historical processing where roster data may not be available.

        Returns:
            SQL query string with parameterized date values
        """
        return f"""
        {schedule_data_cte(self.project_id)},
        {gamebook_players_with_games_cte(self.project_id)},
        {props_cte(self.project_id)}
        {backfill_mode_final_select()}
        """
