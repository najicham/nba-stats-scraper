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
        -- Session 458 FIX: game_date < (not <=), handle is_dnp NULL for older records
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
                fg_attempts,
                paint_attempts,
                three_pt_attempts,
                assisted_fg_makes,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY game_date DESC
                ) as game_rank
            FROM `{project_id}.nba_analytics.player_game_summary`
            WHERE game_date < DATE('{cache_date}')  -- FIX: strictly before (was <=)
              AND season_year = {season_year}
              AND is_active = TRUE
              AND (is_dnp IS NULL OR is_dnp = FALSE)  -- FIX: NULL = pre-is_dnp era
              AND (minutes_played > 0 OR points > 0)
        ),

        -- Step 2: Calculate rolling averages for ALL leaked features
        player_stats AS (
            SELECT
                player_lookup,
                universal_player_id,
                MAX(team_abbr) as team_abbr,

                -- Features 0-4: Points averaging
                CAST(ROUND(AVG(CASE WHEN game_rank <= 5 THEN points END), 4) AS NUMERIC) as points_avg_last_5,
                CAST(ROUND(AVG(CASE WHEN game_rank <= 10 THEN points END), 4) AS NUMERIC) as points_avg_last_10,
                CAST(ROUND(AVG(points), 4) AS NUMERIC) as points_avg_season,
                CAST(ROUND(STDDEV(CASE WHEN game_rank <= 10 THEN points END), 4) AS NUMERIC) as points_std_last_10,

                -- Feature 31: Minutes average
                CAST(ROUND(AVG(CASE WHEN game_rank <= 10 THEN minutes_played END), 4) AS NUMERIC) as minutes_avg_last_10,
                CAST(ROUND(AVG(CASE WHEN game_rank <= 10 THEN usage_rate END), 4) AS NUMERIC) as usage_rate_last_10,
                CAST(ROUND(AVG(CASE WHEN game_rank <= 10 THEN ts_pct END), 4) AS NUMERIC) as ts_pct_last_10,

                -- Assisted rate
                CAST(ROUND(
                    SAFE_DIVIDE(
                        SUM(CASE WHEN game_rank <= 10 THEN assisted_fg_makes ELSE 0 END),
                        SUM(CASE WHEN game_rank <= 10 THEN fg_makes ELSE 0 END)
                    ),
                    9
                ) AS NUMERIC) as assisted_rate_last_10,

                -- Feature 18: paint_rate_last_10 (FIX: was leaked via shot_zone_analysis)
                -- Stored as percentage (44.53 = 44.53%) to match shot_zone_analysis format
                CAST(ROUND(
                    SAFE_DIVIDE(
                        SUM(CASE WHEN game_rank <= 10 THEN paint_attempts END),
                        SUM(CASE WHEN game_rank <= 10 THEN fg_attempts END)
                    ) * 100,
                    2
                ) AS NUMERIC) as paint_rate_last_10,

                -- Feature 20: three_pt_rate_last_10 (FIX: was leaked via shot_zone_analysis)
                CAST(ROUND(
                    SAFE_DIVIDE(
                        SUM(CASE WHEN game_rank <= 10 THEN three_pt_attempts END),
                        SUM(CASE WHEN game_rank <= 10 THEN fg_attempts END)
                    ) * 100,
                    2
                ) AS NUMERIC) as three_pt_rate_last_10,

                -- Games in time windows (FIX: use < not <= for cache_date boundary)
                CAST(COUNTIF(game_date >= DATE_SUB(DATE('{cache_date}'), INTERVAL 7 DAY)) AS INT64) as games_in_last_7_days,
                CAST(COUNTIF(game_date >= DATE_SUB(DATE('{cache_date}'), INTERVAL 14 DAY)) AS INT64) as games_in_last_14_days,

                -- Season totals
                COUNT(*) as games_played_season,
                CAST(ROUND(AVG(usage_rate), 4) AS NUMERIC) as player_usage_rate_season
            FROM player_games
            GROUP BY player_lookup, universal_player_id
            HAVING COUNT(*) >= 5  -- Minimum games required
        ),

        -- Step 3: Team pace and off rating (features 22-23) from team_offense_game_summary
        team_stats AS (
            SELECT
                team_abbr,
                CAST(ROUND(AVG(pace), 4) AS NUMERIC) as team_pace_last_10,
                CAST(ROUND(AVG(offensive_rating), 4) AS NUMERIC) as team_off_rating_last_10
            FROM (
                SELECT
                    team_abbr, pace, offensive_rating,
                    ROW_NUMBER() OVER (PARTITION BY team_abbr ORDER BY game_date DESC) as rn
                FROM `{project_id}.nba_analytics.team_offense_game_summary`
                WHERE game_date < DATE('{cache_date}')  -- FIX: strictly before
            )
            WHERE rn <= 10
            GROUP BY team_abbr
        ),

        -- Step 4: Get players from EXISTING cache entries
        existing_cache_players AS (
            SELECT DISTINCT player_lookup
            FROM `{project_id}.nba_precompute.player_daily_cache`
            WHERE cache_date = DATE('{cache_date}')
        )

        -- Step 5: Join all sources
        SELECT
            ps.player_lookup,
            ps.universal_player_id,
            DATE('{cache_date}') as cache_date,
            ps.points_avg_last_5,
            ps.points_avg_last_10,
            ps.points_avg_season,
            ps.points_std_last_10,
            ps.minutes_avg_last_10,
            ps.usage_rate_last_10,
            ps.ts_pct_last_10,
            ps.assisted_rate_last_10,
            ps.paint_rate_last_10,
            ps.three_pt_rate_last_10,
            ts.team_pace_last_10,
            ts.team_off_rating_last_10,
            ps.games_in_last_7_days,
            ps.games_in_last_14_days,
            ps.games_played_season,
            ps.player_usage_rate_season
        FROM existing_cache_players ec
        INNER JOIN player_stats ps
            ON ec.player_lookup = ps.player_lookup
        LEFT JOIN team_stats ts
            ON ps.team_abbr = ts.team_abbr
    ) AS source
    ON target.cache_date = source.cache_date
       AND target.player_lookup = source.player_lookup

    -- Update ALL leaked fields
    WHEN MATCHED THEN UPDATE SET
        target.points_avg_last_5 = source.points_avg_last_5,
        target.points_avg_last_10 = source.points_avg_last_10,
        target.points_avg_season = source.points_avg_season,
        target.points_std_last_10 = source.points_std_last_10,
        target.minutes_avg_last_10 = source.minutes_avg_last_10,
        target.usage_rate_last_10 = source.usage_rate_last_10,
        target.ts_pct_last_10 = source.ts_pct_last_10,
        target.assisted_rate_last_10 = source.assisted_rate_last_10,
        target.paint_rate_last_10 = source.paint_rate_last_10,
        target.three_pt_rate_last_10 = source.three_pt_rate_last_10,
        target.team_pace_last_10 = source.team_pace_last_10,
        target.team_off_rating_last_10 = source.team_off_rating_last_10,
        target.games_in_last_7_days = source.games_in_last_7_days,
        target.games_in_last_14_days = source.games_in_last_14_days,
        target.games_played_season = source.games_played_season,
        target.player_usage_rate_season = source.player_usage_rate_season
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
    parser.add_argument('--all-historical', action='store_true',
                        help='Regenerate ALL historical cache dates (before 2025-10-01)')
    parser.add_argument('--dry-run', action='store_true', help='Print SQL without executing')
    parser.add_argument('--progress-file', type=str, default=None,
                        help='File to track progress (resume from last completed date)')

    args = parser.parse_args()

    # Initialize BigQuery client
    client = bigquery.Client()
    project_id = client.project

    # Determine date range
    if args.date:
        dates = [datetime.strptime(args.date, '%Y-%m-%d').date()]
    elif args.all_historical:
        # Query BQ for all cache dates before current season
        logger.info("Querying BQ for all historical cache dates...")
        cutoff = args.end_date or '2025-10-01'
        start_cutoff = args.start_date or '2021-01-01'
        query = f"""
        SELECT DISTINCT cache_date
        FROM `{project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date < '{cutoff}'
          AND cache_date >= '{start_cutoff}'
        ORDER BY cache_date
        """
        result = client.query(query).result()
        dates = [row.cache_date for row in result]
        logger.info(f"Found {len(dates)} historical cache dates")
    elif args.start_date and args.end_date:
        start = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        dates = get_date_range(start, end)
    else:
        parser.print_help()
        sys.exit(1)

    if not dates:
        logger.info("No dates to process")
        return 0

    # Resume from progress file if provided
    if args.progress_file and os.path.exists(args.progress_file):
        with open(args.progress_file, 'r') as f:
            completed = set(line.strip() for line in f if line.strip())
        before = len(dates)
        dates = [d for d in dates if d.isoformat() not in completed]
        logger.info(f"Resuming: {before - len(dates)} already done, {len(dates)} remaining")

    logger.info(f"Regenerating cache for {len(dates)} dates ({dates[0]} to {dates[-1]})")

    if args.dry_run:
        logger.info("DRY RUN - SQL would be executed but not running")
        return 0

    # Process each date
    total_rows = 0
    failed_dates = []

    for i, cache_date in enumerate(dates, 1):
        try:
            rows = regenerate_cache_for_date(client, project_id, cache_date)
            total_rows += rows
            # Write progress
            if args.progress_file:
                with open(args.progress_file, 'a') as f:
                    f.write(f"{cache_date.isoformat()}\n")
            if i % 50 == 0:
                logger.info(f"Progress: {i}/{len(dates)} dates ({i*100//len(dates)}%)")
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
