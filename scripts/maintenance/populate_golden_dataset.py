#!/usr/bin/env python3
"""
Helper script to populate the golden dataset table with initial records.

This script helps create the initial golden dataset by:
1. Selecting good candidate player-date combinations
2. Calculating rolling averages from raw data
3. Generating INSERT statements for manual review

Usage:
    # Generate golden dataset entries for specific players
    python scripts/maintenance/populate_golden_dataset.py \
        --players "LeBron James,Stephen Curry,Luka Doncic" \
        --start-date 2024-12-01 \
        --end-date 2024-12-31

    # Auto-select diverse player sample
    python scripts/maintenance/populate_golden_dataset.py \
        --auto-select 5 \
        --start-date 2024-12-01 \
        --end-date 2024-12-31

    # Generate for specific date
    python scripts/maintenance/populate_golden_dataset.py \
        --players "Giannis Antetokounmpo,Joel Embiid" \
        --date 2024-12-15

Created: 2026-01-27
Purpose: Populate golden dataset with verified rolling averages
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def get_bq_client():
    """Get BigQuery client."""
    from google.cloud import bigquery
    return bigquery.Client()


def get_player_lookup(client, player_name: str) -> Optional[tuple]:
    """
    Get player_lookup and player_id for a player name.

    Returns:
        Tuple of (player_lookup, player_id) or None if not found
    """
    project_id = client.project

    query = f"""
    SELECT DISTINCT
        player_lookup,
        universal_player_id
    FROM `{project_id}.nba_reference.nba_players_registry`
    WHERE LOWER(player_name) = LOWER('{player_name}')
      AND season = '2024-25'
    LIMIT 1
    """

    results = list(client.query(query).result(timeout=60))
    if not results:
        return None

    row = results[0]
    return (row.player_lookup, row.universal_player_id)


def get_player_games_before_date(
    client,
    player_lookup: str,
    game_date: date,
    season: str = "2024-25"
) -> pd.DataFrame:
    """Get a player's games before a specific date."""
    project_id = client.project

    query = f"""
    SELECT
        game_date,
        points,
        rebounds_total as rebounds,
        assists,
        minutes_played,
        usage_rate
    FROM `{project_id}.nba_analytics.player_game_summary`
    WHERE player_lookup = '{player_lookup}'
      AND game_date < '{game_date}'
      AND season = '{season}'
      AND minutes_played > 0
    ORDER BY game_date DESC
    """

    results = client.query(query).result(timeout=60)
    df = results.to_dataframe()

    return df


def calculate_rolling_averages(player_games: pd.DataFrame) -> Dict[str, Optional[float]]:
    """Calculate rolling averages."""
    last_5_games = player_games.head(5)
    last_10_games = player_games.head(10)

    result = {}

    # Points
    result['pts_l5'] = round(float(last_5_games['points'].mean()), 4) if len(last_5_games) > 0 else None
    result['pts_l10'] = round(float(last_10_games['points'].mean()), 4) if len(last_10_games) > 0 else None
    result['pts_season'] = round(float(player_games['points'].mean()), 4) if len(player_games) > 0 else None

    # Rebounds
    result['reb_l5'] = round(float(last_5_games['rebounds'].mean()), 4) if len(last_5_games) > 0 else None
    result['reb_l10'] = round(float(last_10_games['rebounds'].mean()), 4) if len(last_10_games) > 0 else None

    # Assists
    result['ast_l5'] = round(float(last_5_games['assists'].mean()), 4) if len(last_5_games) > 0 else None
    result['ast_l10'] = round(float(last_10_games['assists'].mean()), 4) if len(last_10_games) > 0 else None

    # Minutes
    result['minutes_l10'] = round(float(last_10_games['minutes_played'].mean()), 4) if len(last_10_games) > 0 else None

    # Usage rate
    result['usage_l10'] = round(float(last_10_games['usage_rate'].mean()), 4) if len(last_10_games) > 0 else None

    return result


def generate_insert_statement(
    player_id: str,
    player_name: str,
    player_lookup: str,
    game_date: date,
    averages: Dict[str, Optional[float]],
    notes: Optional[str] = None
) -> str:
    """Generate BigQuery INSERT statement."""

    # Format the values
    def fmt(val):
        return f"{val}" if val is not None else "NULL"

    notes_str = f"'{notes}'" if notes else "NULL"

    insert = f"""
INSERT INTO `nba-props-platform.nba_reference.golden_dataset`
  (player_id, player_name, player_lookup, game_date,
   expected_pts_l5, expected_pts_l10, expected_pts_season,
   expected_reb_l5, expected_reb_l10,
   expected_ast_l5, expected_ast_l10,
   expected_minutes_l10, expected_usage_rate_l10,
   verified_by, verified_at, notes, is_active)
VALUES
  ('{player_id}', '{player_name}', '{player_lookup}', '{game_date}',
   {fmt(averages['pts_l5'])}, {fmt(averages['pts_l10'])}, {fmt(averages['pts_season'])},
   {fmt(averages['reb_l5'])}, {fmt(averages['reb_l10'])},
   {fmt(averages['ast_l5'])}, {fmt(averages['ast_l10'])},
   {fmt(averages['minutes_l10'])}, {fmt(averages['usage_l10'])},
   'script', CURRENT_TIMESTAMP(), {notes_str}, TRUE);
"""
    return insert


def process_player_date(
    client,
    player_name: str,
    game_date: date,
    notes: Optional[str] = None
) -> Optional[str]:
    """
    Process a single player-date combination and generate INSERT statement.

    Returns:
        INSERT statement or None if failed
    """
    logger.info(f"\nProcessing: {player_name} on {game_date}")

    # Get player lookup
    player_info = get_player_lookup(client, player_name)
    if not player_info:
        logger.error(f"Player not found: {player_name}")
        return None

    player_lookup, player_id = player_info
    logger.info(f"  Found: {player_lookup} (ID: {player_id})")

    # Get player's game history
    player_games = get_player_games_before_date(client, player_lookup, game_date)

    if len(player_games) == 0:
        logger.error(f"No games found for {player_name} before {game_date}")
        return None

    logger.info(f"  Found {len(player_games)} games before {game_date}")

    # Calculate rolling averages
    averages = calculate_rolling_averages(player_games)

    # Log calculated values
    logger.info(f"  Calculated averages:")
    logger.info(f"    PTS L5:  {averages['pts_l5']}")
    logger.info(f"    PTS L10: {averages['pts_l10']}")
    logger.info(f"    REB L5:  {averages['reb_l5']}")
    logger.info(f"    AST L5:  {averages['ast_l5']}")

    # Generate INSERT statement
    insert_stmt = generate_insert_statement(
        player_id, player_name, player_lookup, game_date, averages, notes
    )

    return insert_stmt


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Generate golden dataset INSERT statements',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate for specific players and date
  python scripts/maintenance/populate_golden_dataset.py \\
      --players "LeBron James,Stephen Curry" \\
      --date 2024-12-15

  # Generate for date range (picks one date per player)
  python scripts/maintenance/populate_golden_dataset.py \\
      --players "Luka Doncic,Giannis Antetokounmpo,Joel Embiid" \\
      --start-date 2024-12-01 \\
      --end-date 2024-12-31

  # Output to file
  python scripts/maintenance/populate_golden_dataset.py \\
      --players "Jayson Tatum" \\
      --date 2024-12-15 \\
      --output golden_dataset_inserts.sql
        """
    )

    parser.add_argument(
        '--players',
        required=True,
        help='Comma-separated list of player names (e.g., "LeBron James,Stephen Curry")'
    )

    parser.add_argument(
        '--date',
        help='Specific game date (YYYY-MM-DD)'
    )

    parser.add_argument(
        '--start-date',
        help='Start of date range (YYYY-MM-DD)'
    )

    parser.add_argument(
        '--end-date',
        help='End of date range (YYYY-MM-DD)'
    )

    parser.add_argument(
        '--notes',
        help='Optional notes for all records (e.g., "Mid-season check")'
    )

    parser.add_argument(
        '--output',
        help='Output file for INSERT statements (default: print to stdout)'
    )

    args = parser.parse_args()

    # Parse players
    players = [p.strip() for p in args.players.split(',')]

    # Parse dates
    if args.date:
        game_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        game_dates = [game_date]
    elif args.start_date and args.end_date:
        start = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        # Pick middle date for simplicity
        game_dates = [start + (end - start) / 2]
    else:
        logger.error("Must provide either --date or both --start-date and --end-date")
        return 1

    # Get BigQuery client
    try:
        client = get_bq_client()
    except Exception as e:
        logger.error(f"Failed to create BigQuery client: {e}")
        return 1

    # Process each player-date combination
    insert_statements = []
    for player_name in players:
        for game_date in game_dates:
            insert_stmt = process_player_date(client, player_name, game_date, args.notes)
            if insert_stmt:
                insert_statements.append(insert_stmt)

    # Output results
    if insert_statements:
        logger.info(f"\n{'='*80}")
        logger.info(f"Generated {len(insert_statements)} INSERT statement(s)")
        logger.info(f"{'='*80}\n")

        output = "\n".join(insert_statements)

        if args.output:
            with open(args.output, 'w') as f:
                f.write(output)
            logger.info(f"INSERT statements written to: {args.output}")
        else:
            print(output)

        logger.info("\n⚠️  IMPORTANT: Review these INSERT statements carefully before running!")
        logger.info("   Verify the calculated values match expectations.")
        logger.info("   Run: bq query < output_file.sql\n")
    else:
        logger.error("No INSERT statements generated")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
