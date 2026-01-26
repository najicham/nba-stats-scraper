"""
Player Game Query Builder

Builds SQL queries for extracting players with upcoming games.
Supports two modes:
- Daily mode: Uses roster data + injuries
- Backfill mode: Uses gamebook player stats (no injuries)
"""

from datetime import date, timedelta
from typing import Optional


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
        {self._games_today_cte()}
        {self._teams_playing_cte()}
        {self._latest_roster_per_team_cte()}
        {self._roster_players_cte()}
        {self._roster_players_with_games_cte()}
        {self._injuries_cte()}
        {self._props_cte()}
        {self._daily_mode_final_select()}
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
        {self._schedule_data_cte()}
        {self._gamebook_players_with_games_cte()}
        {self._props_cte()}
        {self._backfill_mode_final_select()}
        """

    # ========================================================================
    # Common CTEs (used by both modes)
    # ========================================================================

    def _props_cte(self) -> str:
        """
        Build props CTE combining multiple betting data sources.

        Combines prop lines from:
        - odds_api_player_points_props
        - bettingpros_player_points_props
        """
        return f"""props AS (
            SELECT DISTINCT
                player_lookup,
                points_line,
                'odds_api' as prop_source
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date = @game_date
              AND player_lookup IS NOT NULL
            UNION DISTINCT
            SELECT DISTINCT
                player_lookup,
                points_line,
                'bettingpros' as prop_source
            FROM `{self.project_id}.nba_raw.bettingpros_player_points_props`
            WHERE game_date = @game_date
              AND is_active = TRUE
              AND player_lookup IS NOT NULL
        )"""

    # ========================================================================
    # Daily Mode CTEs
    # ========================================================================

    def _games_today_cte(self) -> str:
        """Build games_today CTE for daily mode."""
        return f"""WITH games_today AS (
            SELECT
                CONCAT(
                    FORMAT_DATE('%Y%m%d', game_date),
                    '_',
                    away_team_tricode,
                    '_',
                    home_team_tricode
                ) as game_id,
                game_date,
                home_team_tricode as home_team_abbr,
                away_team_tricode as away_team_abbr
            FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
            WHERE game_date = @game_date
        ),"""

    def _teams_playing_cte(self) -> str:
        """Build teams_playing CTE for daily mode."""
        return """teams_playing AS (
            SELECT DISTINCT home_team_abbr as team_abbr FROM games_today
            UNION DISTINCT
            SELECT DISTINCT away_team_abbr as team_abbr FROM games_today
        ),"""

    def _latest_roster_per_team_cte(self) -> str:
        """Build latest_roster_per_team CTE for daily mode."""
        return f"""latest_roster_per_team AS (
            SELECT team_abbr, MAX(roster_date) as roster_date
            FROM `{self.project_id}.nba_raw.espn_team_rosters`
            WHERE roster_date >= @roster_start
              AND roster_date <= @roster_end
            GROUP BY team_abbr
        ),"""

    def _roster_players_cte(self) -> str:
        """Build roster_players CTE for daily mode."""
        return f"""roster_players AS (
            SELECT DISTINCT
                r.player_lookup,
                r.team_abbr
            FROM `{self.project_id}.nba_raw.espn_team_rosters` r
            INNER JOIN latest_roster_per_team lr
                ON r.team_abbr = lr.team_abbr
                AND r.roster_date = lr.roster_date
            WHERE r.roster_date >= @roster_start
              AND r.roster_date <= @roster_end
              AND r.team_abbr IN (SELECT team_abbr FROM teams_playing)
              AND r.player_lookup IS NOT NULL
        ),"""

    def _roster_players_with_games_cte(self) -> str:
        """Build players_with_games CTE for daily mode (roster-based)."""
        return """players_with_games AS (
            SELECT DISTINCT
                rp.player_lookup,
                g.game_id,
                rp.team_abbr,
                g.home_team_abbr,
                g.away_team_abbr
            FROM roster_players rp
            INNER JOIN games_today g
                ON rp.team_abbr = g.home_team_abbr
                OR rp.team_abbr = g.away_team_abbr
        ),"""

    def _injuries_cte(self) -> str:
        """Build injuries CTE for daily mode."""
        return f"""injuries AS (
            SELECT DISTINCT
                player_lookup,
                injury_status
            FROM `{self.project_id}.nba_raw.nbac_injury_report`
            WHERE report_date = @game_date
              AND player_lookup IS NOT NULL
        ),"""

    def _daily_mode_final_select(self) -> str:
        """Build final SELECT for daily mode with injury filtering."""
        return """SELECT
            p.player_lookup,
            p.game_id,
            p.team_abbr,
            p.home_team_abbr,
            p.away_team_abbr,
            i.injury_status,
            pr.points_line,
            pr.prop_source,
            CASE WHEN pr.player_lookup IS NOT NULL THEN TRUE ELSE FALSE END as has_prop_line
        FROM players_with_games p
        LEFT JOIN injuries i ON p.player_lookup = i.player_lookup
        LEFT JOIN props pr ON p.player_lookup = pr.player_lookup
        WHERE i.injury_status IS NULL
           OR i.injury_status NOT IN ('Out', 'OUT', 'Doubtful', 'DOUBTFUL')
        """

    # ========================================================================
    # Backfill Mode CTEs
    # ========================================================================

    def _schedule_data_cte(self) -> str:
        """Build schedule_data CTE for backfill mode."""
        return f"""WITH schedule_data AS (
            SELECT
                game_id as nba_game_id,
                CONCAT(
                    FORMAT_DATE('%Y%m%d', game_date),
                    '_',
                    away_team_tricode,
                    '_',
                    home_team_tricode
                ) as game_id,
                home_team_tricode,
                away_team_tricode
            FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
            WHERE game_date = @game_date
        ),"""

    def _gamebook_players_with_games_cte(self) -> str:
        """Build players_with_games CTE for backfill mode (gamebook-based)."""
        return """players_with_games AS (
            SELECT DISTINCT
                g.player_lookup,
                s.game_id,
                g.team_abbr,
                g.player_status,
                COALESCE(s.home_team_tricode, g.team_abbr) as home_team_abbr,
                COALESCE(s.away_team_tricode, g.team_abbr) as away_team_abbr
            FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats` g
            LEFT JOIN schedule_data s
                ON g.game_id = s.nba_game_id
            WHERE g.game_date = @game_date
              AND g.player_lookup IS NOT NULL
              AND (g.player_status IS NULL OR g.player_status NOT IN ('DNP', 'DND', 'NWT'))
        ),"""

    def _backfill_mode_final_select(self) -> str:
        """Build final SELECT for backfill mode without injury filtering."""
        return """SELECT
            p.player_lookup,
            p.game_id,
            p.team_abbr,
            p.home_team_abbr,
            p.away_team_abbr,
            p.player_status,
            pr.points_line,
            pr.prop_source,
            CASE WHEN pr.player_lookup IS NOT NULL THEN TRUE ELSE FALSE END as has_prop_line
        FROM players_with_games p
        LEFT JOIN props pr ON p.player_lookup = pr.player_lookup
        """
