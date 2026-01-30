"""
Shared CTE Definitions for Player Game Queries

This module contains common SQL CTE (Common Table Expression) definitions
used by both player_loaders.py and player_game_query_builder.py.

Consolidating these CTEs here ensures:
1. Consistency between daily and backfill query logic
2. Single point of maintenance for query patterns
3. Easier testing and validation of SQL fragments

Usage:
    from .shared_ctes import (
        games_today_cte,
        props_cte,
        schedule_data_cte,
    )

    # Build query using shared CTEs
    query = f'''
    {games_today_cte(project_id)}
    {props_cte(project_id)}
    -- rest of query
    '''
"""


def games_today_cte(project_id: str, with_prefix: bool = True) -> str:
    """
    Build the games_today CTE for extracting scheduled games.

    This CTE creates a standardized game_id format (YYYYMMDD_AWAY_HOME)
    and extracts home/away team abbreviations from the schedule.

    Args:
        project_id: Google Cloud project ID for BigQuery tables
        with_prefix: If True, includes 'WITH' prefix. Set False when chaining CTEs.

    Returns:
        SQL CTE fragment for games scheduled on @game_date
    """
    prefix = "WITH " if with_prefix else ""
    return f"""{prefix}games_today AS (
            -- Get all games scheduled for target date
            -- Creates standard game_id format (YYYYMMDD_AWAY_HOME)
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
            FROM `{project_id}.nba_raw.v_nbac_schedule_latest`
            WHERE game_date = @game_date
        )"""


def teams_playing_cte() -> str:
    """
    Build the teams_playing CTE from games_today.

    Extracts all unique team abbreviations (both home and away)
    from the games_today CTE.

    Returns:
        SQL CTE fragment for teams playing on target date
    """
    return """teams_playing AS (
            -- Get all teams playing today (both home and away)
            SELECT DISTINCT home_team_abbr as team_abbr FROM games_today
            UNION DISTINCT
            SELECT DISTINCT away_team_abbr as team_abbr FROM games_today
        )"""


def latest_roster_per_team_cte(project_id: str) -> str:
    """
    Build the latest_roster_per_team CTE for roster date lookup.

    Finds the most recent roster date for each team within the
    specified date range (@roster_start to @roster_end).

    Args:
        project_id: Google Cloud project ID for BigQuery tables

    Returns:
        SQL CTE fragment for latest roster dates per team
    """
    return f"""latest_roster_per_team AS (
            -- Find the most recent roster PER TEAM within partition range
            -- Different teams may have different latest dates
            SELECT team_abbr, MAX(roster_date) as roster_date
            FROM `{project_id}.nba_raw.espn_team_rosters`
            WHERE roster_date >= @roster_start
              AND roster_date <= @roster_end
            GROUP BY team_abbr
        )"""


def roster_players_cte(project_id: str) -> str:
    """
    Build the roster_players CTE for extracting players from rosters.

    Gets all players from the latest roster for each team that is
    playing on the target date.

    Args:
        project_id: Google Cloud project ID for BigQuery tables

    Returns:
        SQL CTE fragment for roster players
    """
    return f"""roster_players AS (
            -- Get all players from rosters of teams playing today
            -- Using date range for partition elimination, then filter to latest per team
            SELECT DISTINCT
                r.player_lookup,
                r.team_abbr
            FROM `{project_id}.nba_raw.espn_team_rosters` r
            INNER JOIN latest_roster_per_team lr
                ON r.team_abbr = lr.team_abbr
                AND r.roster_date = lr.roster_date
            WHERE r.roster_date >= @roster_start
              AND r.roster_date <= @roster_end
              AND r.team_abbr IN (SELECT team_abbr FROM teams_playing)
              AND r.player_lookup IS NOT NULL
        )"""


def roster_players_with_games_cte() -> str:
    """
    Build the players_with_games CTE for daily mode (roster-based).

    Joins roster players with their game information to get
    game_id and home/away team details.

    Returns:
        SQL CTE fragment for players with their game info
    """
    return """players_with_games AS (
            -- Join roster players with their game info
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
        )"""


def injuries_cte(project_id: str) -> str:
    """
    Build the injuries CTE for injury status lookup.

    Gets the latest injury report for players on the target date.

    Args:
        project_id: Google Cloud project ID for BigQuery tables

    Returns:
        SQL CTE fragment for injury status
    """
    return f"""injuries AS (
            -- Get latest injury report for target date
            SELECT DISTINCT
                player_lookup,
                injury_status
            FROM `{project_id}.nba_raw.nbac_injury_report`
            WHERE report_date = @game_date
              AND player_lookup IS NOT NULL
        )"""


def props_cte(project_id: str) -> str:
    """
    Build the props CTE combining multiple betting data sources.

    Combines prop lines from:
    - odds_api_player_points_props
    - bettingpros_player_points_props (active only)

    Args:
        project_id: Google Cloud project ID for BigQuery tables

    Returns:
        SQL CTE fragment for player prop lines
    """
    return f"""props AS (
            -- Check which players have prop lines (from either source)
            SELECT DISTINCT
                player_lookup,
                points_line,
                'odds_api' as prop_source
            FROM `{project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date = @game_date
              AND player_lookup IS NOT NULL
            UNION DISTINCT
            SELECT DISTINCT
                player_lookup,
                points_line,
                'bettingpros' as prop_source
            FROM `{project_id}.nba_raw.bettingpros_player_points_props`
            WHERE game_date = @game_date
              AND is_active = TRUE
              AND player_lookup IS NOT NULL
        )"""


def schedule_data_cte(project_id: str, with_prefix: bool = True) -> str:
    """
    Build the schedule_data CTE for backfill mode.

    Creates a mapping between NBA official game_id and standard format,
    along with team tricodes for joining with gamebook data.

    Args:
        project_id: Google Cloud project ID for BigQuery tables
        with_prefix: If True, includes 'WITH' prefix. Set False when chaining CTEs.

    Returns:
        SQL CTE fragment for schedule data with game_id mapping
    """
    prefix = "WITH " if with_prefix else ""
    return f"""{prefix}schedule_data AS (
            -- Get schedule data with partition filter
            -- Creates standard game_id format (YYYYMMDD_AWAY_HOME)
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
            FROM `{project_id}.nba_raw.v_nbac_schedule_latest`
            WHERE game_date = @game_date
        )"""


def gamebook_players_with_games_cte(project_id: str) -> str:
    """
    Build the players_with_games CTE for backfill mode (gamebook-based).

    Gets players who actually played from gamebook stats, joined with
    schedule data for standardized game_id and team info.

    Args:
        project_id: Google Cloud project ID for BigQuery tables

    Returns:
        SQL CTE fragment for gamebook players with game info
    """
    return f"""players_with_games AS (
            -- Get ALL active players from gamebook who have games on target date
            SELECT DISTINCT
                g.player_lookup,
                s.game_id,  -- Use standard game_id from schedule
                g.team_abbr,
                g.player_status,
                -- Get home/away from schedule since gamebook may not have it
                COALESCE(s.home_team_tricode, g.team_abbr) as home_team_abbr,
                COALESCE(s.away_team_tricode, g.team_abbr) as away_team_abbr
            FROM `{project_id}.nba_raw.nbac_gamebook_player_stats` g
            LEFT JOIN schedule_data s
                ON g.game_id = s.nba_game_id
            WHERE g.game_date = @game_date
              AND g.player_lookup IS NOT NULL
              AND (g.player_status IS NULL OR g.player_status NOT IN ('DNP', 'DND', 'NWT'))
        )"""


def daily_mode_final_select() -> str:
    """
    Build the final SELECT for daily mode with injury filtering.

    Joins players_with_games with injuries and props, filtering out
    players marked as Out or Doubtful.

    Returns:
        SQL SELECT statement for daily mode output
    """
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
        -- Filter out players marked OUT or DOUBTFUL in injury report
        WHERE i.injury_status IS NULL
           OR i.injury_status NOT IN ('Out', 'OUT', 'Doubtful', 'DOUBTFUL')
        """


def backfill_mode_final_select() -> str:
    """
    Build the final SELECT for backfill mode without injury filtering.

    Joins players_with_games with props. No injury filtering since
    gamebook data reflects who actually played.

    Returns:
        SQL SELECT statement for backfill mode output
    """
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
