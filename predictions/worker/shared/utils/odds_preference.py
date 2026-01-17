"""
File: shared/utils/odds_preference.py

Odds API Game Lines - Bookmaker Preference Utilities

Provides convenient Python functions for querying game lines with
DraftKings preferred and FanDuel as fallback.

Coverage Stats (Oct 2021 → Mar 2025):
- Total games: 5,260
- DraftKings: 5,235 games (99.52%)
- FanDuel fallback: 25 games (0.48%)

Usage:
    from shared.utils.odds_preference import get_preferred_game_lines, get_game_lines_summary
    
    # Get all lines for a date
    lines = get_preferred_game_lines('2024-01-24')
    
    # Get simplified summary
    summary = get_game_lines_summary('2024-01-24')
    
    # Check coverage stats
    stats = get_bookmaker_coverage_stats('2021-10-01', '2025-03-31')
"""

from google.cloud import bigquery
import pandas as pd
from typing import Optional, List, Dict

# Initialize BigQuery client
client = bigquery.Client()

# Project and dataset
PROJECT_ID = "nba-props-platform"
DATASET = "nba_raw"
VIEW_NAME = "odds_api_game_lines_preferred"
FULL_VIEW_PATH = f"{PROJECT_ID}.{DATASET}.{VIEW_NAME}"


def get_preferred_game_lines(
    game_date: str,
    home_team: Optional[str] = None,
    away_team: Optional[str] = None,
    market_keys: Optional[List[str]] = None
) -> pd.DataFrame:
    """
    Get game lines with DraftKings preferred, FanDuel as fallback.
    
    Returns one bookmaker per game/market/outcome based on preference ranking.
    
    Args:
        game_date: Date in 'YYYY-MM-DD' format (required for partition filter)
        home_team: Optional filter for home team name (e.g., "Los Angeles Clippers")
        away_team: Optional filter for away team name
        market_keys: Optional list of markets to include (e.g., ['spreads', 'totals'])
        
    Returns:
        DataFrame with columns:
            - snapshot_timestamp, previous_snapshot_timestamp, next_snapshot_timestamp
            - game_id, sport_key, sport_title, commence_time, game_date
            - home_team, away_team, home_team_abbr, away_team_abbr
            - bookmaker_key, bookmaker_title, bookmaker_last_update
            - market_key, market_last_update
            - outcome_name, outcome_price, outcome_point
            - source_file_path, created_at, processed_at
            
    Example:
        # Get all lines for a date
        lines = get_preferred_game_lines('2024-01-24')
        
        # Get only spreads
        spreads = get_preferred_game_lines('2024-01-24', market_keys=['spreads'])
        
        # Get lines for specific team
        clippers = get_preferred_game_lines('2024-01-24', home_team='Los Angeles Clippers')
    """
    query = f"""
        SELECT *
        FROM `{FULL_VIEW_PATH}`
        WHERE game_date = @game_date
    """
    
    # Build query parameters
    query_params = [
        bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
    ]
    
    # Add optional filters
    if home_team:
        query += " AND home_team = @home_team"
        query_params.append(
            bigquery.ScalarQueryParameter("home_team", "STRING", home_team)
        )
    
    if away_team:
        query += " AND away_team = @away_team"
        query_params.append(
            bigquery.ScalarQueryParameter("away_team", "STRING", away_team)
        )
    
    if market_keys:
        query += " AND market_key IN UNNEST(@market_keys)"
        query_params.append(
            bigquery.ArrayQueryParameter("market_keys", "STRING", market_keys)
        )
    
    query += " ORDER BY game_id, market_key, outcome_name"
    
    # Configure query job
    job_config = bigquery.QueryJobConfig(query_parameters=query_params)
    
    # Execute query
    df = client.query(query, job_config=job_config).to_dataframe()
    
    return df


def get_game_lines_summary(
    game_date: str,
    home_team: Optional[str] = None
) -> pd.DataFrame:
    """
    Get a simplified summary of game lines (one row per game).
    
    Pivots the data to show spreads and totals in a single row per game,
    making it easier to see all lines at a glance.
    
    Args:
        game_date: Date in 'YYYY-MM-DD' format (required for partition filter)
        home_team: Optional filter for home team name
        
    Returns:
        DataFrame with columns:
            - game_id, game_date, home_team, away_team
            - spread_value: Point spread (e.g., -7.5)
            - spread_home_price: Home team spread odds
            - spread_away_price: Away team spread odds
            - spread_bookmaker: Which bookmaker for spread
            - total_value: Total points line (e.g., 220.5)
            - over_price: Over odds
            - under_price: Under odds
            - total_bookmaker: Which bookmaker for total
            
    Example:
        summary = get_game_lines_summary('2024-01-24')
        print(summary[['home_team', 'spread_value', 'total_value']])
        
        # Check which bookmaker was used
        print(summary[['home_team', 'spread_bookmaker', 'total_bookmaker']])
    """
    query = f"""
        WITH spreads AS (
            SELECT
                game_id,
                game_date,
                home_team,
                away_team,
                bookmaker_key as spread_bookmaker,
                MAX(CASE WHEN outcome_name = home_team THEN outcome_point END) as spread_value,
                MAX(CASE WHEN outcome_name = home_team THEN outcome_price END) as spread_home_price,
                MAX(CASE WHEN outcome_name = away_team THEN outcome_price END) as spread_away_price
            FROM `{FULL_VIEW_PATH}`
            WHERE game_date = @game_date
                AND market_key = 'spreads'
                {f"AND home_team = @home_team" if home_team else ""}
            GROUP BY game_id, game_date, home_team, away_team, bookmaker_key
        ),
        totals AS (
            SELECT
                game_id,
                bookmaker_key as total_bookmaker,
                MAX(CASE WHEN outcome_name = 'Over' THEN outcome_point END) as total_value,
                MAX(CASE WHEN outcome_name = 'Over' THEN outcome_price END) as over_price,
                MAX(CASE WHEN outcome_name = 'Under' THEN outcome_price END) as under_price
            FROM `{FULL_VIEW_PATH}`
            WHERE game_date = @game_date
                AND market_key = 'totals'
                {f"AND home_team = @home_team" if home_team else ""}
            GROUP BY game_id, bookmaker_key
        )
        SELECT
            s.game_id,
            s.game_date,
            s.home_team,
            s.away_team,
            s.spread_value,
            s.spread_home_price,
            s.spread_away_price,
            s.spread_bookmaker,
            t.total_value,
            t.over_price,
            t.under_price,
            t.total_bookmaker
        FROM spreads s
        LEFT JOIN totals t ON s.game_id = t.game_id
        ORDER BY s.home_team
    """
    
    # Build query parameters
    query_params = [
        bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
    ]
    
    if home_team:
        query_params.append(
            bigquery.ScalarQueryParameter("home_team", "STRING", home_team)
        )
    
    # Configure query job
    job_config = bigquery.QueryJobConfig(query_parameters=query_params)
    
    # Execute query
    df = client.query(query, job_config=job_config).to_dataframe()
    
    return df


def get_bookmaker_coverage_stats(
    start_date: str,
    end_date: str
) -> Dict[str, float]:
    """
    Get statistics on bookmaker coverage for a date range.
    
    Shows how often DraftKings vs FanDuel is used across games.
    
    Args:
        start_date: Start date in 'YYYY-MM-DD' format
        end_date: End date in 'YYYY-MM-DD' format
        
    Returns:
        Dictionary with keys:
            - total_games: Total unique games in date range
            - games_using_draftkings: Games with DraftKings data
            - games_using_fanduel: Games with FanDuel data (as fallback)
            - dk_coverage_pct: Percentage of games using DraftKings
            
    Example:
        stats = get_bookmaker_coverage_stats('2021-10-01', '2025-03-31')
        print(f"DraftKings coverage: {stats['dk_coverage_pct']:.2f}%")
        print(f"FanDuel fallback: {stats['games_using_fanduel']} games")
    """
    query = f"""
        WITH game_bookmakers AS (
            SELECT DISTINCT
                game_id,
                game_date,
                bookmaker_key
            FROM `{FULL_VIEW_PATH}`
            WHERE game_date BETWEEN @start_date AND @end_date
        )
        SELECT
            COUNT(DISTINCT game_id) as total_games,
            COUNT(DISTINCT CASE WHEN bookmaker_key = 'draftkings' THEN game_id END) as games_using_draftkings,
            COUNT(DISTINCT CASE WHEN bookmaker_key = 'fanduel' THEN game_id END) as games_using_fanduel
        FROM game_bookmakers
    """
    
    # Build query parameters
    query_params = [
        bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
        bigquery.ScalarQueryParameter("end_date", "DATE", end_date)
    ]
    
    # Configure query job
    job_config = bigquery.QueryJobConfig(query_parameters=query_params)
    
    # Execute query
    result = client.query(query, job_config=job_config).to_dataframe()
    
    # Convert to dictionary
    stats = result.iloc[0].to_dict()
    
    # Calculate coverage percentage
    if stats['total_games'] > 0:
        stats['dk_coverage_pct'] = (
            stats['games_using_draftkings'] / stats['total_games'] * 100
        )
    else:
        stats['dk_coverage_pct'] = 0.0
    
    return stats


def get_game_bookmakers(
    game_date: str,
    home_team: str
) -> pd.DataFrame:
    """
    Check which bookmakers are available for a specific game.
    
    Useful for debugging why a particular bookmaker was chosen.
    
    Args:
        game_date: Date in 'YYYY-MM-DD' format
        home_team: Home team name
        
    Returns:
        DataFrame showing which bookmaker was used for each market
        
    Example:
        bookmakers = get_game_bookmakers('2024-01-24', 'Los Angeles Clippers')
        print(bookmakers[['market_key', 'bookmaker_key']])
    """
    query = f"""
        SELECT DISTINCT
            market_key,
            bookmaker_key,
            bookmaker_title
        FROM `{FULL_VIEW_PATH}`
        WHERE game_date = @game_date
            AND home_team = @home_team
        ORDER BY market_key, bookmaker_key
    """
    
    query_params = [
        bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        bigquery.ScalarQueryParameter("home_team", "STRING", home_team)
    ]
    
    job_config = bigquery.QueryJobConfig(query_parameters=query_params)
    df = client.query(query, job_config=job_config).to_dataframe()
    
    return df


# Convenience function for common use case
def get_todays_lines() -> pd.DataFrame:
    """
    Get today's game lines with preferred bookmakers.
    
    Returns:
        DataFrame with all lines for today's games
        
    Example:
        todays_lines = get_todays_lines()
        summary = get_game_lines_summary(date.today().isoformat())
    """
    from datetime import date
    today = date.today().isoformat()
    return get_preferred_game_lines(today)


if __name__ == "__main__":
    # Example usage and testing
    print("🎯 Odds Preference Utility - Examples\n")
    
    # Example 1: Get lines for a specific date
    print("Example 1: Get all lines for 2024-01-24")
    lines = get_preferred_game_lines('2024-01-24')
    print(f"  Found {len(lines)} rows for {lines['game_id'].nunique()} games")
    print(f"  Bookmakers used: {lines['bookmaker_key'].unique()}\n")
    
    # Example 2: Get summary
    print("Example 2: Get game summary for 2024-01-24")
    summary = get_game_lines_summary('2024-01-24')
    print(f"  Found {len(summary)} games")
    if len(summary) > 0:
        print("  Sample game:")
        print(f"    {summary.iloc[0]['home_team']} vs {summary.iloc[0]['away_team']}")
        print(f"    Spread: {summary.iloc[0]['spread_value']} (via {summary.iloc[0]['spread_bookmaker']})")
        print(f"    Total: {summary.iloc[0]['total_value']} (via {summary.iloc[0]['total_bookmaker']})\n")
    
    # Example 3: Coverage stats
    print("Example 3: Check bookmaker coverage (Oct 2021 - Mar 2025)")
    stats = get_bookmaker_coverage_stats('2021-10-01', '2025-03-31')
    print(f"  Total games: {stats['total_games']}")
    print(f"  DraftKings: {stats['games_using_draftkings']} ({stats['dk_coverage_pct']:.2f}%)")
    print(f"  FanDuel fallback: {stats['games_using_fanduel']}\n")
    
    # Example 4: Check specific team
    print("Example 4: Check Clippers game bookmakers")
    bookmakers = get_game_bookmakers('2024-01-24', 'Los Angeles Clippers')
    if len(bookmakers) > 0:
        print(f"  Bookmakers for Clippers game on 2024-01-24:")
        for _, row in bookmakers.iterrows():
            print(f"    {row['market_key']}: {row['bookmaker_title']}")
    else:
        print("  No Clippers game found on this date")