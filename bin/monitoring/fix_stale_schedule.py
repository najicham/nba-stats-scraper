#!/usr/bin/env python3
"""
Fix stale schedule data - marks old in-progress games as Final.

This prevents analytics processors from skipping due to ENABLE_GAMES_FINISHED_CHECK
when schedule data hasn't been refreshed.

Usage:
    python bin/monitoring/fix_stale_schedule.py [--dry-run]

Safe to run: Only updates games that are > 4 hours past their start time.
"""

import argparse
import logging
import sys
from datetime import datetime, timezone, timedelta
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"


def find_stale_games(client: bigquery.Client) -> list:
    """Find games that are likely finished but still show as in-progress."""
    query = """
    SELECT 
        game_id,
        game_date,
        game_status,
        start_time_et,
        home_team_abbr,
        away_team_abbr,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), 
            TIMESTAMP(CONCAT(game_date, ' ', start_time_et), 'America/New_York'),
            HOUR) as hours_since_start
    FROM `nba_raw.nbac_schedule`
    WHERE game_status IN (1, 2)  -- Scheduled or In Progress
      AND game_date < CURRENT_DATE('America/New_York')  -- Past dates only
    ORDER BY game_date DESC, start_time_et
    """
    
    results = list(client.query(query).result())
    stale_games = []
    
    for row in results:
        # Game is stale if > 4 hours since start time
        if row.hours_since_start and row.hours_since_start > 4:
            stale_games.append({
                'game_id': row.game_id,
                'game_date': str(row.game_date),
                'current_status': row.game_status,
                'start_time_et': row.start_time_et,
                'matchup': f"{row.away_team_abbr}@{row.home_team_abbr}",
                'hours_since_start': row.hours_since_start
            })
    
    return stale_games


def fix_stale_games(client: bigquery.Client, stale_games: list, dry_run: bool = False) -> int:
    """Update stale games to Final status."""
    if not stale_games:
        logger.info("No stale games to fix")
        return 0
    
    game_ids = [g['game_id'] for g in stale_games]
    
    if dry_run:
        logger.info(f"[DRY RUN] Would update {len(game_ids)} games to Final status")
        for game in stale_games:
            logger.info(f"  - {game['game_date']} {game['matchup']} (status={game['current_status']}, {game['hours_since_start']:.1f}h old)")
        return 0
    
    # Build update query
    game_ids_str = "', '".join(game_ids)
    update_query = f"""
    UPDATE `nba_raw.nbac_schedule`
    SET game_status = 3
    WHERE game_id IN ('{game_ids_str}')
    """
    
    result = client.query(update_query).result()
    logger.info(f"✅ Updated {len(game_ids)} games to Final status")
    
    for game in stale_games:
        logger.info(f"  - {game['game_date']} {game['matchup']}")
    
    return len(game_ids)


def main():
    parser = argparse.ArgumentParser(description='Fix stale schedule data')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without making changes')
    args = parser.parse_args()
    
    client = bigquery.Client(project=PROJECT_ID)
    
    logger.info("Checking for stale schedule data...")
    stale_games = find_stale_games(client)
    
    if not stale_games:
        logger.info("✅ No stale schedule data found")
        return 0
    
    logger.info(f"Found {len(stale_games)} stale games")
    fixed = fix_stale_games(client, stale_games, dry_run=args.dry_run)
    
    return 0 if fixed >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
