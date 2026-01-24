"""
File: shared/utils/odds_player_props_preference.py

Odds API Player Props - Bookmaker Preference Utilities

Provides convenient Python functions for querying player points props with
DraftKings preferred and FanDuel as fallback.

Usage:
    from shared.utils.odds_player_props_preference import (
        get_preferred_player_props,
        get_player_props_by_player,
        get_props_for_game
    )
    
    # Get all props for a date
    props = get_preferred_player_props('2025-03-31')
    
    # Get props for specific player
    shai_props = get_player_props_by_player('2025-03-31', 'Shai Gilgeous-Alexander')
    
    # Get all players' props for a game
    game_props = get_props_for_game('20250331_CHI_OKC')
"""

import logging
from google.cloud import bigquery
import pandas as pd
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# Initialize BigQuery client
client = bigquery.Client()

# Project and dataset
PROJECT_ID = "nba-props-platform"
DATASET = "nba_raw"
TABLE_NAME = "odds_api_player_points_props"
FULL_TABLE_PATH = f"{PROJECT_ID}.{DATASET}.{TABLE_NAME}"


def get_preferred_player_props(
    game_date: str,
    player_name: Optional[str] = None,
    team_abbr: Optional[str] = None,
    min_line: Optional[float] = None,
    max_line: Optional[float] = None,
    snapshot_tag: Optional[str] = None
) -> pd.DataFrame:
    """
    Get player props with DraftKings preferred, FanDuel as fallback.
    
    Returns one bookmaker per player based on preference ranking.
    
    Args:
        game_date: Date in 'YYYY-MM-DD' format (required for partition filter)
        player_name: Optional filter for specific player (e.g., "LeBron James")
        team_abbr: Optional filter for team (e.g., "LAL", "GSW")
        min_line: Optional minimum points line (e.g., 25.0 for stars only)
        max_line: Optional maximum points line (e.g., 15.0 for role players)
        snapshot_tag: Optional snapshot time filter (e.g., "snap-2130")
        
    Returns:
        DataFrame with columns:
            - game_id, odds_api_event_id, game_date, game_start_time
            - home_team_abbr, away_team_abbr
            - snapshot_timestamp, snapshot_tag, minutes_before_tipoff
            - bookmaker, player_name, player_lookup
            - points_line, over_price, under_price
            - over_price_american, under_price_american
            - bookmaker_last_update, source_file_path
            
    Example:
        # Get all props for a date
        props = get_preferred_player_props('2025-03-31')
        
        # Get props for specific player
        lebron = get_preferred_player_props('2025-03-31', player_name='LeBron James')
        
        # Get props for Lakers players
        lakers = get_preferred_player_props('2025-03-31', team_abbr='LAL')
        
        # Get only star player props (25+ points)
        stars = get_preferred_player_props('2025-03-31', min_line=25.0)
    """
    query = f"""
        WITH ranked_bookmakers AS (
            SELECT 
                *,
                -- Rank: DraftKings=1, FanDuel=2 (lower is better)
                ROW_NUMBER() OVER (
                    PARTITION BY game_id, player_name, snapshot_timestamp
                    ORDER BY 
                        CASE bookmaker 
                            WHEN 'draftkings' THEN 1 
                            WHEN 'fanduel' THEN 2 
                            ELSE 99 
                        END
                ) as bookmaker_rank
            FROM `{FULL_TABLE_PATH}`
            WHERE game_date = @game_date
    """
    
    # Build query parameters
    query_params = [
        bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
    ]
    
    # Add optional filters
    if player_name:
        query += " AND player_name = @player_name"
        query_params.append(
            bigquery.ScalarQueryParameter("player_name", "STRING", player_name)
        )
    
    if team_abbr:
        query += " AND (home_team_abbr = @team_abbr OR away_team_abbr = @team_abbr)"
        query_params.append(
            bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr)
        )
    
    if min_line is not None:
        query += " AND points_line >= @min_line"
        query_params.append(
            bigquery.ScalarQueryParameter("min_line", "FLOAT64", min_line)
        )
    
    if max_line is not None:
        query += " AND points_line <= @max_line"
        query_params.append(
            bigquery.ScalarQueryParameter("max_line", "FLOAT64", max_line)
        )
    
    if snapshot_tag:
        query += " AND snapshot_tag = @snapshot_tag"
        query_params.append(
            bigquery.ScalarQueryParameter("snapshot_tag", "STRING", snapshot_tag)
        )
    
    query += """
        )
        SELECT 
            game_id,
            odds_api_event_id,
            game_date,
            game_start_time,
            home_team_abbr,
            away_team_abbr,
            snapshot_timestamp,
            snapshot_tag,
            minutes_before_tipoff,
            bookmaker,
            player_name,
            player_lookup,
            points_line,
            over_price,
            under_price,
            over_price_american,
            under_price_american,
            bookmaker_last_update,
            source_file_path
        FROM ranked_bookmakers
        WHERE bookmaker_rank = 1
        ORDER BY points_line DESC, player_name
    """
    
    # Configure query job
    job_config = bigquery.QueryJobConfig(query_parameters=query_params)
    
    # Execute query
    df = client.query(query, job_config=job_config).to_dataframe()
    
    return df


def get_player_props_by_player(
    game_date: str,
    player_name: str
) -> pd.DataFrame:
    """
    Get all props for a specific player on a given date.
    
    Useful for tracking a single player's lines across games or snapshots.
    
    Args:
        game_date: Date in 'YYYY-MM-DD' format
        player_name: Full player name (e.g., "Shai Gilgeous-Alexander")
        
    Returns:
        DataFrame with all bookmakers and snapshots for that player
        
    Example:
        shai = get_player_props_by_player('2025-03-31', 'Shai Gilgeous-Alexander')
        print(f"Line: {shai.iloc[0]['points_line']}")
        print(f"Bookmaker: {shai.iloc[0]['bookmaker']}")
    """
    return get_preferred_player_props(game_date, player_name=player_name)


def get_props_for_game(
    game_id: str,
    game_date: str
) -> pd.DataFrame:
    """
    Get all player props for a specific game.
    
    Args:
        game_id: Game identifier (e.g., "20250331_CHI_OKC")
        game_date: Date in 'YYYY-MM-DD' format (required for partition filter)
        
    Returns:
        DataFrame with all players' props for that game
        
    Example:
        game_props = get_props_for_game('20250331_CHI_OKC', '2025-03-31')
        print(game_props[['player_name', 'points_line', 'bookmaker']])
    """
    query = f"""
        WITH ranked_bookmakers AS (
            SELECT 
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY game_id, player_name, snapshot_timestamp
                    ORDER BY 
                        CASE bookmaker 
                            WHEN 'draftkings' THEN 1 
                            WHEN 'fanduel' THEN 2 
                            ELSE 99 
                        END
                ) as bookmaker_rank
            FROM `{FULL_TABLE_PATH}`
            WHERE game_date = @game_date
                AND game_id = @game_id
        )
        SELECT 
            game_id,
            odds_api_event_id,
            game_date,
            game_start_time,
            home_team_abbr,
            away_team_abbr,
            snapshot_timestamp,
            snapshot_tag,
            minutes_before_tipoff,
            bookmaker,
            player_name,
            player_lookup,
            points_line,
            over_price,
            under_price,
            over_price_american,
            under_price_american,
            bookmaker_last_update,
            source_file_path
        FROM ranked_bookmakers
        WHERE bookmaker_rank = 1
        ORDER BY points_line DESC, player_name
    """
    
    query_params = [
        bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        bigquery.ScalarQueryParameter("game_id", "STRING", game_id)
    ]
    
    job_config = bigquery.QueryJobConfig(query_parameters=query_params)
    df = client.query(query, job_config=job_config).to_dataframe()
    
    return df


def get_props_summary_by_team(
    game_date: str,
    team_abbr: str
) -> pd.DataFrame:
    """
    Get a summary of all player props for a specific team.
    
    Args:
        game_date: Date in 'YYYY-MM-DD' format
        team_abbr: Team abbreviation (e.g., "LAC", "LAL")
        
    Returns:
        DataFrame with team's players and their props
        
    Example:
        clippers = get_props_summary_by_team('2025-03-31', 'LAC')
        print(clippers[['player_name', 'points_line']])
    """
    return get_preferred_player_props(game_date, team_abbr=team_abbr)


def compare_bookmakers(
    game_date: str,
    player_name: str
) -> pd.DataFrame:
    """
    Compare lines from different bookmakers for a specific player.
    
    Shows ALL bookmakers (not just preferred) to see line shopping opportunities.
    
    Args:
        game_date: Date in 'YYYY-MM-DD' format
        player_name: Full player name
        
    Returns:
        DataFrame with all bookmakers' lines for comparison
        
    Example:
        comparison = compare_bookmakers('2025-03-31', 'Shai Gilgeous-Alexander')
        print(comparison[['bookmaker', 'points_line', 'over_price', 'under_price']])
        
        # Find best Over odds
        best_over = comparison.loc[comparison['over_price'].idxmax()]
    """
    query = f"""
        SELECT 
            bookmaker,
            player_name,
            points_line,
            over_price,
            under_price,
            over_price_american,
            under_price_american,
            snapshot_timestamp,
            snapshot_tag
        FROM `{FULL_TABLE_PATH}`
        WHERE game_date = @game_date
            AND player_name = @player_name
        ORDER BY bookmaker, snapshot_timestamp DESC
    """
    
    query_params = [
        bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        bigquery.ScalarQueryParameter("player_name", "STRING", player_name)
    ]
    
    job_config = bigquery.QueryJobConfig(query_parameters=query_params)
    df = client.query(query, job_config=job_config).to_dataframe()
    
    return df


def get_line_movement(
    game_date: str,
    player_name: str,
    bookmaker: str = 'draftkings'
) -> pd.DataFrame:
    """
    Track line movement for a player throughout the day.
    
    Shows how the line changed across different snapshots.
    
    Args:
        game_date: Date in 'YYYY-MM-DD' format
        player_name: Full player name
        bookmaker: Bookmaker to track (default: 'draftkings')
        
    Returns:
        DataFrame with line movement over time
        
    Example:
        movement = get_line_movement('2025-03-31', 'Shai Gilgeous-Alexander')
        print(movement[['snapshot_tag', 'points_line', 'over_price', 'minutes_before_tipoff']])
    """
    query = f"""
        SELECT 
            snapshot_timestamp,
            snapshot_tag,
            minutes_before_tipoff,
            points_line,
            over_price,
            under_price,
            over_price_american,
            under_price_american,
            bookmaker_last_update
        FROM `{FULL_TABLE_PATH}`
        WHERE game_date = @game_date
            AND player_name = @player_name
            AND bookmaker = @bookmaker
        ORDER BY snapshot_timestamp
    """
    
    query_params = [
        bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        bigquery.ScalarQueryParameter("player_name", "STRING", player_name),
        bigquery.ScalarQueryParameter("bookmaker", "STRING", bookmaker)
    ]
    
    job_config = bigquery.QueryJobConfig(query_parameters=query_params)
    df = client.query(query, job_config=job_config).to_dataframe()
    
    return df


def get_bookmaker_coverage_stats(
    start_date: str,
    end_date: str
) -> Dict[str, float]:
    """
    Get statistics on bookmaker coverage for player props.
    
    Args:
        start_date: Start date in 'YYYY-MM-DD' format
        end_date: End date in 'YYYY-MM-DD' format
        
    Returns:
        Dictionary with coverage statistics
        
    Example:
        stats = get_bookmaker_coverage_stats('2025-03-01', '2025-03-31')
        print(f"DraftKings coverage: {stats['dk_coverage_pct']:.2f}%")
    """
    query = f"""
        WITH player_props AS (
            SELECT DISTINCT
                game_date,
                game_id,
                player_name,
                bookmaker
            FROM `{FULL_TABLE_PATH}`
            WHERE game_date BETWEEN @start_date AND @end_date
        )
        SELECT
            COUNT(DISTINCT CONCAT(game_date, game_id, player_name)) as total_player_props,
            COUNT(DISTINCT CASE WHEN bookmaker = 'draftkings' 
                THEN CONCAT(game_date, game_id, player_name) END) as props_with_draftkings,
            COUNT(DISTINCT CASE WHEN bookmaker = 'fanduel' 
                THEN CONCAT(game_date, game_id, player_name) END) as props_with_fanduel
        FROM player_props
    """
    
    query_params = [
        bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
        bigquery.ScalarQueryParameter("end_date", "DATE", end_date)
    ]
    
    job_config = bigquery.QueryJobConfig(query_parameters=query_params)
    result = client.query(query, job_config=job_config).to_dataframe()
    
    stats = result.iloc[0].to_dict()
    
    if stats['total_player_props'] > 0:
        stats['dk_coverage_pct'] = (
            stats['props_with_draftkings'] / stats['total_player_props'] * 100
        )
        stats['fd_coverage_pct'] = (
            stats['props_with_fanduel'] / stats['total_player_props'] * 100
        )
    else:
        stats['dk_coverage_pct'] = 0.0
        stats['fd_coverage_pct'] = 0.0
    
    return stats


def get_top_lines_for_date(
    game_date: str,
    top_n: int = 20
) -> pd.DataFrame:
    """
    Get the highest point lines for a given date.
    
    Useful for identifying star players and their expected performances.
    
    Args:
        game_date: Date in 'YYYY-MM-DD' format
        top_n: Number of top lines to return (default: 20)
        
    Returns:
        DataFrame with top N highest point lines
        
    Example:
        top_props = get_top_lines_for_date('2025-03-31', top_n=10)
        print(top_props[['player_name', 'points_line', 'home_team_abbr', 'away_team_abbr']])
    """
    props = get_preferred_player_props(game_date)
    return props.nlargest(top_n, 'points_line')


# Convenience function for common use case
def get_todays_props(team_abbr: Optional[str] = None) -> pd.DataFrame:
    """
    Get today's player props with preferred bookmakers.
    
    Args:
        team_abbr: Optional team filter (e.g., "LAC")
        
    Returns:
        DataFrame with all props for today
        
    Example:
        todays_props = get_todays_props()
        clippers_props = get_todays_props(team_abbr='LAC')
    """
    from datetime import date
    today = date.today().isoformat()
    return get_preferred_player_props(today, team_abbr=team_abbr)


if __name__ == "__main__":
    # Configure logging for standalone execution
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

    # Example usage and testing
    logger.info("Player Props Preference Utility - Examples")

    test_date = '2025-03-31'

    # Example 1: Get all props for a date
    logger.info(f"Example 1: Get all props for {test_date}")
    try:
        props = get_preferred_player_props(test_date)
        logger.info(f"  Found {len(props)} player props for {props['player_name'].nunique()} players")
        logger.info(f"  Top line: {props.iloc[0]['player_name']} - {props.iloc[0]['points_line']} points")
        logger.info(f"  Bookmakers used: {props['bookmaker'].unique()}")
    except Exception as e:
        logger.error(f"  Error: {e}")

    # Example 2: Get props for specific player
    logger.info("Example 2: Get props for Shai Gilgeous-Alexander")
    try:
        shai = get_player_props_by_player(test_date, 'Shai Gilgeous-Alexander')
        if len(shai) > 0:
            logger.info(f"  Line: {shai.iloc[0]['points_line']}")
            logger.info(f"  Over: {shai.iloc[0]['over_price']}")
            logger.info(f"  Under: {shai.iloc[0]['under_price']}")
            logger.info(f"  Bookmaker: {shai.iloc[0]['bookmaker']}")
        else:
            logger.warning("  No props found")
    except Exception as e:
        logger.error(f"  Error: {e}")

    # Example 3: Compare bookmakers
    logger.info("Example 3: Compare bookmakers for a player")
    try:
        comparison = compare_bookmakers(test_date, 'Shai Gilgeous-Alexander')
        if len(comparison) > 0:
            logger.info(f"  Found {len(comparison)} bookmaker lines")
            for _, row in comparison.iterrows():
                logger.info(f"    {row['bookmaker']}: {row['points_line']} pts, Over {row['over_price']}")
        else:
            logger.warning("  No comparison data found")
    except Exception as e:
        logger.error(f"  Error: {e}")

    # Example 4: Get top lines
    logger.info("Example 4: Top 5 highest point lines")
    try:
        top_props = get_top_lines_for_date(test_date, top_n=5)
        if len(top_props) > 0:
            for i, row in top_props.iterrows():
                logger.info(f"  {row['player_name']}: {row['points_line']} pts ({row['bookmaker']})")
        else:
            logger.warning("  No data found")
    except Exception as e:
        logger.error(f"  Error: {e}")