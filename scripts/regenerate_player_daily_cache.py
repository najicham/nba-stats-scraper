#!/usr/bin/env python3
"""
Emergency script to regenerate player_daily_cache after date filter bug fix.

This script directly queries player_game_summary and recalculates rolling averages
with the CORRECT date filter (game_date < cache_date, not <=).

Usage:
    python scripts/regenerate_player_daily_cache.py --start-date 2024-12-27 --end-date 2025-01-26
    python scripts/regenerate_player_daily_cache.py --date 2025-01-26  # Single date
"""

import argparse
import logging
import os
import sys
from datetime import date, timedelta, datetime
from typing import List

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_date_range(start_date: date, end_date: date) -> List[date]:
    """Generate list of dates between start and end (inclusive)."""
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def regenerate_cache_for_date(client: bigquery.Client, project_id: str, cache_date: date) -> int:
    """
    Regenerate player_daily_cache for a single date using CORRECT date filter.

    Uses MERGE to update existing records or insert new ones.

    Returns: Number of rows affected
    """
    logger.info(f"Regenerating cache for {cache_date}")

    # Calculate season year (Oct-Sep season)
    season_year = cache_date.year if cache_date.month >= 10 else cache_date.year - 1

    query = f"""
    MERGE `{project_id}.nba_precompute.player_daily_cache` AS target
    USING (
        -- Step 1: Get game history for all players (games BEFORE cache_date)
        WITH player_games AS (
            SELECT
                player_lookup,
                universal_player_id,
                game_date,
                team_abbr,
                points,
                minutes_played,
                usage_rate,
                ts_pct,
                fg_makes,
                assisted_fg_makes,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY game_date DESC
                ) as game_rank
            FROM `{project_id}.nba_analytics.player_game_summary`
            WHERE game_date < DATE('{cache_date}')  -- FIX: Changed <= to <
              AND season_year = {season_year}
              AND is_active = TRUE
              AND (minutes_played > 0 OR points > 0)
        ),

        -- Step 2: Calculate rolling averages
        player_stats AS (
            SELECT
                player_lookup,
                universal_player_id,
                MAX(team_abbr) as team_abbr,

                -- Points averaging
                ROUND(AVG(CASE WHEN game_rank <= 5 THEN points END), 4) as points_avg_last_5,
                ROUND(AVG(CASE WHEN game_rank <= 10 THEN points END), 4) as points_avg_last_10,
                ROUND(AVG(points), 4) as points_avg_season,
                ROUND(STDDEV(CASE WHEN game_rank <= 10 THEN points END), 4) as points_std_last_10,

                -- Last 10 game averages
                ROUND(AVG(CASE WHEN game_rank <= 10 THEN minutes_played END), 4) as minutes_avg_last_10,
                ROUND(AVG(CASE WHEN game_rank <= 10 THEN usage_rate END), 4) as usage_rate_last_10,
                ROUND(AVG(CASE WHEN game_rank <= 10 THEN ts_pct END), 4) as ts_pct_last_10,

                -- Assisted rate
                ROUND(
                    SAFE_DIVIDE(
                        SUM(CASE WHEN game_rank <= 10 THEN assisted_fg_makes ELSE 0 END),
                        SUM(CASE WHEN game_rank <= 10 THEN fg_makes ELSE 0 END)
                    ),
                    9
                ) as assisted_rate_last_10,

                -- Season totals
                COUNT(*) as games_played_season,
                ROUND(AVG(usage_rate), 4) as player_usage_rate_season
            FROM player_games
            GROUP BY player_lookup, universal_player_id
            HAVING COUNT(*) >= 5  -- Minimum games required
        ),

        -- Step 3: Get players scheduled for this cache_date
        scheduled_players AS (
            SELECT DISTINCT
                player_lookup,
                universal_player_id,
                team_abbr
            FROM `{project_id}.nba_analytics.upcoming_player_game_context`
            WHERE game_date = DATE('{cache_date}')
        )

        -- Step 4: Join stats with scheduled players
        SELECT
            sp.player_lookup,
            sp.universal_player_id,
            DATE('{cache_date}') as cache_date,
            ps.points_avg_last_5,
            ps.points_avg_last_10,
            ps.points_avg_season,
            ps.points_std_last_10,
            ps.minutes_avg_last_10,
            ps.usage_rate_last_10,
            ps.ts_pct_last_10,
            ps.assisted_rate_last_10,
            ps.games_played_season,
            ps.player_usage_rate_season,
            sp.team_abbr,
            CURRENT_TIMESTAMP() as processed_at
        FROM scheduled_players sp
        INNER JOIN player_stats ps
            ON sp.player_lookup = ps.player_lookup
    ) AS source
    ON target.cache_date = source.cache_date
       AND target.player_lookup = source.player_lookup

    -- Update existing records
    WHEN MATCHED THEN UPDATE SET
        target.points_avg_last_5 = source.points_avg_last_5,
        target.points_avg_last_10 = source.points_avg_last_10,
        target.points_avg_season = source.points_avg_season,
        target.points_std_last_10 = source.points_std_last_10,
        target.minutes_avg_last_10 = source.minutes_avg_last_10,
        target.usage_rate_last_10 = source.usage_rate_last_10,
        target.ts_pct_last_10 = source.ts_pct_last_10,
        target.assisted_rate_last_10 = source.assisted_rate_last_10,
        target.games_played_season = source.games_played_season,
        target.player_usage_rate_season = source.player_usage_rate_season,
        target.processed_at = source.processed_at

    -- Insert new records (shouldn't happen, but handle gracefully)
    WHEN NOT MATCHED THEN INSERT (
        player_lookup,
        universal_player_id,
        cache_date,
        points_avg_last_5,
        points_avg_last_10,
        points_avg_season,
        points_std_last_10,
        minutes_avg_last_10,
        usage_rate_last_10,
        ts_pct_last_10,
        assisted_rate_last_10,
        games_played_season,
        player_usage_rate_season,
        team_abbr,
        processed_at
    ) VALUES (
        source.player_lookup,
        source.universal_player_id,
        source.cache_date,
        source.points_avg_last_5,
        source.points_avg_last_10,
        source.points_avg_season,
        source.points_std_last_10,
        source.minutes_avg_last_10,
        source.usage_rate_last_10,
        source.ts_pct_last_10,
        source.assisted_rate_last_10,
        source.games_played_season,
        source.player_usage_rate_season,
        source.team_abbr,
        source.processed_at
    )
    """

    try:
        job = client.query(query)
        result = job.result(timeout=300)  # 5 minute timeout

        # Get rows affected
        rows_affected = job.num_dml_affected_rows or 0
        logger.info(f"✅ {cache_date}: Updated {rows_affected} cache records")
        return rows_affected

    except Exception as e:
        logger.error(f"❌ {cache_date}: Failed - {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description='Regenerate player_daily_cache after bug fix')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--date', type=str, help='Single date to regenerate (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Print SQL without executing')

    args = parser.parse_args()

    # Initialize BigQuery client
    client = bigquery.Client()
    project_id = client.project

    # Determine date range
    if args.date:
        dates = [datetime.strptime(args.date, '%Y-%m-%d').date()]
    elif args.start_date and args.end_date:
        start = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        dates = get_date_range(start, end)
    else:
        parser.print_help()
        sys.exit(1)

    logger.info(f"Regenerating cache for {len(dates)} dates ({dates[0]} to {dates[-1]})")

    if args.dry_run:
        logger.info("DRY RUN - SQL would be executed but not running")
        return 0

    # Process each date
    total_rows = 0
    failed_dates = []

    for cache_date in dates:
        try:
            rows = regenerate_cache_for_date(client, project_id, cache_date)
            total_rows += rows
        except Exception as e:
            failed_dates.append((cache_date, str(e)))
            # Continue with other dates
            continue

    # Summary
    logger.info("="*70)
    logger.info("REGENERATION COMPLETE")
    logger.info("="*70)
    logger.info(f"Total dates processed: {len(dates)}")
    logger.info(f"Successful: {len(dates) - len(failed_dates)}")
    logger.info(f"Failed: {len(failed_dates)}")
    logger.info(f"Total rows updated: {total_rows}")

    if failed_dates:
        logger.error("Failed dates:")
        for cache_date, error in failed_dates:
            logger.error(f"  {cache_date}: {error}")
        return 1

    logger.info("✅ All dates regenerated successfully")
    return 0


if __name__ == '__main__':
    sys.exit(main())
