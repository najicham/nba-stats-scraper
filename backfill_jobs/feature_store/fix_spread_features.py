#!/usr/bin/env python3
"""
Fix spread_magnitude (Feature 41) and implied_team_total (Feature 42) in ml_feature_store_v2.

Problem:
- Feature 41 has been ALL ZEROS since Nov 2025 (entire season)
- Feature 42 has been game_total/2 for everyone (wrong — should differ by home/away spread)
- Root cause: odds_api_game_lines stores BOTH sides of each spread (+4.0 and -4.0).
  The median query without filtering took median of both, which always = 0.
- Fixed in Session 374b: Added `AND (outcome_point <= 0 OR market_key != 'spreads')`
  to betting_data.py. But historical data still needs correction.

Solution:
- Compute correct opening spread from odds_api_game_lines (with outcome_point <= 0 filter)
- Join with UPCG to get home_game + game_total per player
- Update ml_feature_store_v2 Feature 41 and 42 via MERGE

Usage:
    # Dry run
    PYTHONPATH=. python backfill_jobs/feature_store/fix_spread_features.py \
        --start-date 2025-11-04 --end-date 2026-02-28 --dry-run

    # Execute
    PYTHONPATH=. python backfill_jobs/feature_store/fix_spread_features.py \
        --start-date 2025-11-04 --end-date 2026-02-28

Created: Session 375, 2026-03-01
"""

import argparse
import logging
from datetime import date
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"


def get_correction_query(start_date: str, end_date: str) -> str:
    """Build the query that computes correct Feature 41/42 values."""
    return f"""
    WITH game_spreads AS (
        -- Compute correct opening spread per game from raw odds data.
        -- Uses earliest snapshot, median across bookmakers, favorite side only.
        SELECT DISTINCT
            g.game_date,
            g.home_team_abbr,
            g.away_team_abbr,
            PERCENTILE_CONT(g.outcome_point, 0.5) OVER(
                PARTITION BY g.game_date, g.home_team_abbr, g.away_team_abbr
            ) as spread
        FROM `{PROJECT_ID}.nba_raw.odds_api_game_lines` g
        JOIN (
            SELECT game_date, home_team_abbr, away_team_abbr,
                   MIN(snapshot_timestamp) as earliest
            FROM `{PROJECT_ID}.nba_raw.odds_api_game_lines`
            WHERE market_key = 'spreads'
              AND game_date BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY 1, 2, 3
        ) e ON g.game_date = e.game_date
           AND g.home_team_abbr = e.home_team_abbr
           AND g.away_team_abbr = e.away_team_abbr
           AND g.snapshot_timestamp = e.earliest
        WHERE g.market_key = 'spreads'
          AND g.outcome_point <= 0  -- Session 374b fix: favorite side only
          AND g.game_date BETWEEN '{start_date}' AND '{end_date}'
    ),
    upcg_players AS (
        -- Get home/away + game_total per player from UPCG.
        -- Extract home/away team from game_id format: YYYYMMDD_AWAY_HOME
        -- Deduplicate: some dates have duplicate player entries
        SELECT
            player_lookup,
            game_date,
            home_game,
            game_total,
            SPLIT(game_id, '_')[OFFSET(2)] as home_team,
            SPLIT(game_id, '_')[OFFSET(1)] as away_team
        FROM `{PROJECT_ID}.nba_analytics.upcoming_player_game_context`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
          AND game_total IS NOT NULL
        QUALIFY ROW_NUMBER() OVER(PARTITION BY player_lookup, game_date ORDER BY game_id) = 1
    )
    SELECT
        u.player_lookup,
        u.game_date,
        ABS(gs.spread) as new_f41,
        CASE
            WHEN u.home_game THEN (CAST(u.game_total AS FLOAT64) - gs.spread) / 2.0
            ELSE (CAST(u.game_total AS FLOAT64) + gs.spread) / 2.0
        END as new_f42,
        gs.spread as raw_spread,
        CAST(u.game_total AS FLOAT64) as game_total,
        u.home_game
    FROM upcg_players u
    JOIN game_spreads gs
        ON u.game_date = gs.game_date
        AND u.home_team = gs.home_team_abbr
        AND u.away_team = gs.away_team_abbr
    """


def dry_run(client: bigquery.Client, start_date: str, end_date: str):
    """Show what would be corrected without making changes."""
    logger.info("=" * 60)
    logger.info("DRY RUN — Feature 41/42 Spread Fix")
    logger.info("=" * 60)

    # Count affected rows
    count_query = f"""
    SELECT
        COUNT(*) as total_rows,
        COUNT(DISTINCT game_date) as total_dates,
        COUNTIF(feature_41_value = 0) as f41_zero,
        COUNTIF(feature_41_value IS NULL) as f41_null
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    """
    result = list(client.query(count_query).result())
    row = result[0]
    logger.info(f"Feature store: {row.total_rows:,} rows across {row.total_dates} dates")
    logger.info(f"  Feature 41 = 0: {row.f41_zero:,}")
    logger.info(f"  Feature 41 NULL: {row.f41_null:,}")

    # Preview corrections
    correction_query = get_correction_query(start_date, end_date)
    preview_query = f"""
    WITH corrections AS ({correction_query})
    SELECT
        COUNT(*) as rows_to_fix,
        COUNT(DISTINCT game_date) as dates_covered,
        ROUND(AVG(new_f41), 2) as avg_spread_magnitude,
        ROUND(MIN(new_f41), 1) as min_spread,
        ROUND(MAX(new_f41), 1) as max_spread,
        ROUND(AVG(new_f42), 2) as avg_implied_total,
        ROUND(MIN(new_f42), 1) as min_implied,
        ROUND(MAX(new_f42), 1) as max_implied
    FROM corrections
    """
    result = list(client.query(preview_query).result())
    row = result[0]
    logger.info(f"\nCorrections to apply:")
    logger.info(f"  Rows to fix: {row.rows_to_fix:,}")
    logger.info(f"  Dates covered: {row.dates_covered}")
    logger.info(f"  Spread magnitude: avg={row.avg_spread_magnitude}, "
                f"range=[{row.min_spread}, {row.max_spread}]")
    logger.info(f"  Implied team total: avg={row.avg_implied_total}, "
                f"range=[{row.min_implied}, {row.max_implied}]")

    # Show per-date sample
    sample_query = f"""
    WITH corrections AS ({correction_query})
    SELECT
        game_date,
        COUNT(*) as players,
        ROUND(AVG(new_f41), 2) as avg_spread,
        ROUND(AVG(new_f42), 2) as avg_implied,
        ROUND(AVG(CASE WHEN home_game THEN new_f42 END), 2) as avg_implied_home,
        ROUND(AVG(CASE WHEN NOT home_game THEN new_f42 END), 2) as avg_implied_away
    FROM corrections
    GROUP BY 1
    ORDER BY 1 DESC
    LIMIT 10
    """
    logger.info(f"\nPer-date sample (most recent 10):")
    logger.info(f"{'Date':<12} {'Players':>8} {'AvgSpread':>10} {'AvgImpTot':>10} "
                f"{'HomeImp':>8} {'AwayImp':>8}")
    logger.info("-" * 60)
    for row in client.query(sample_query).result():
        logger.info(f"{str(row.game_date):<12} {row.players:>8} {row.avg_spread:>10} "
                    f"{row.avg_implied:>10} {row.avg_implied_home or 0:>8} "
                    f"{row.avg_implied_away or 0:>8}")

    # Show specific player corrections
    player_sample = f"""
    WITH corrections AS ({correction_query})
    SELECT
        c.player_lookup,
        c.game_date,
        f.feature_41_value as old_f41,
        c.new_f41,
        f.feature_42_value as old_f42,
        ROUND(c.new_f42, 2) as new_f42,
        c.raw_spread,
        c.home_game
    FROM corrections c
    JOIN `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` f
        ON c.player_lookup = f.player_lookup AND c.game_date = f.game_date
    WHERE c.game_date = '{end_date}'
    ORDER BY c.player_lookup
    LIMIT 10
    """
    logger.info(f"\nSample corrections for {end_date}:")
    logger.info(f"{'Player':<20} {'OldF41':>7} {'NewF41':>7} {'OldF42':>8} "
                f"{'NewF42':>8} {'Spread':>7} {'Home':>5}")
    logger.info("-" * 70)
    for row in client.query(player_sample).result():
        logger.info(f"{row.player_lookup:<20} {row.old_f41 or 0:>7.1f} {row.new_f41:>7.1f} "
                    f"{row.old_f42 or 0:>8.1f} {row.new_f42:>8.2f} "
                    f"{row.raw_spread:>7.1f} {str(row.home_game):>5}")

    # Check for games without spread data (will remain unchanged)
    gap_query = f"""
    SELECT COUNT(*) as rows_no_spread
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` f
    WHERE f.game_date BETWEEN '{start_date}' AND '{end_date}'
      AND f.player_lookup NOT IN (
          SELECT player_lookup FROM ({correction_query})
      )
    """
    result = list(client.query(gap_query).result())
    no_spread = result[0].rows_no_spread
    if no_spread > 0:
        logger.info(f"\n{no_spread:,} rows have no matching spread data — "
                    f"will set to NULL (missing)")

    logger.info(f"\n[DRY RUN] No changes made. Run without --dry-run to execute.")


def execute_backfill(client: bigquery.Client, start_date: str, end_date: str):
    """Execute the Feature 41/42 correction via MERGE."""
    logger.info("=" * 60)
    logger.info("EXECUTING Feature 41/42 Spread Fix")
    logger.info("=" * 60)

    correction_query = get_correction_query(start_date, end_date)

    # Step 1: Update rows that HAVE spread data
    merge_query = f"""
    MERGE INTO `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` target
    USING ({correction_query}) source
    ON target.player_lookup = source.player_lookup
       AND target.game_date = source.game_date
       AND target.game_date BETWEEN '{start_date}' AND '{end_date}'
    WHEN MATCHED THEN UPDATE SET
        target.feature_41_value = source.new_f41,
        target.feature_41_source = 'phase3',
        target.feature_41_quality = 85.0,
        target.feature_42_value = source.new_f42,
        target.feature_42_source = 'phase3',
        target.feature_42_quality = 85.0,
        target.updated_at = CURRENT_TIMESTAMP()
    """

    logger.info("Step 1: Updating rows with spread data via MERGE...")
    job = client.query(merge_query)
    job.result()
    logger.info(f"  Updated {job.num_dml_affected_rows:,} rows")

    # Step 2: Set rows WITHOUT spread data to NULL (properly missing, not 0)
    null_query = f"""
    UPDATE `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` target
    SET
        target.feature_41_value = NULL,
        target.feature_41_source = 'missing',
        target.feature_41_quality = 0.0,
        target.feature_42_value = NULL,
        target.feature_42_source = 'missing',
        target.feature_42_quality = 0.0,
        target.updated_at = CURRENT_TIMESTAMP()
    WHERE target.game_date BETWEEN '{start_date}' AND '{end_date}'
      AND target.feature_41_value = 0
    """

    logger.info("Step 2: Setting remaining zero-spread rows to NULL (truly missing)...")
    job = client.query(null_query)
    job.result()
    logger.info(f"  Updated {job.num_dml_affected_rows:,} rows to NULL")


def verify(client: bigquery.Client, start_date: str, end_date: str):
    """Verify the backfill results."""
    logger.info("\n" + "=" * 60)
    logger.info("VERIFICATION")
    logger.info("=" * 60)

    verify_query = f"""
    SELECT
        COUNT(*) as total_rows,
        COUNTIF(feature_41_value IS NOT NULL AND feature_41_value > 0) as f41_nonzero,
        COUNTIF(feature_41_value = 0) as f41_zero,
        COUNTIF(feature_41_value IS NULL) as f41_null,
        ROUND(AVG(CASE WHEN feature_41_value > 0 THEN feature_41_value END), 2) as f41_avg,
        COUNTIF(feature_42_value IS NOT NULL) as f42_present,
        COUNTIF(feature_42_value IS NULL) as f42_null,
        ROUND(AVG(feature_42_value), 2) as f42_avg
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    """
    result = list(client.query(verify_query).result())
    row = result[0]

    logger.info(f"Feature 41 (spread_magnitude):")
    logger.info(f"  Non-zero: {row.f41_nonzero:,} (avg={row.f41_avg})")
    logger.info(f"  Zero: {row.f41_zero:,}")
    logger.info(f"  NULL: {row.f41_null:,}")
    logger.info(f"Feature 42 (implied_team_total):")
    logger.info(f"  Present: {row.f42_present:,} (avg={row.f42_avg})")
    logger.info(f"  NULL: {row.f42_null:,}")

    success = row.f41_zero == 0
    if success:
        logger.info("\nBACKFILL SUCCESSFUL — zero Feature 41 rows remaining: 0")
    else:
        logger.warning(f"\nWARNING: {row.f41_zero} rows still have Feature 41 = 0")

    return success


def main():
    parser = argparse.ArgumentParser(
        description='Fix Feature 41/42 (spread) in ml_feature_store_v2')
    parser.add_argument('--start-date', type=str, required=True,
                        help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, required=True,
                        help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show corrections without executing')
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    logger.info(f"Date range: {args.start_date} to {args.end_date}")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'EXECUTE'}")

    if args.dry_run:
        dry_run(client, args.start_date, args.end_date)
    else:
        execute_backfill(client, args.start_date, args.end_date)
        verify(client, args.start_date, args.end_date)


if __name__ == '__main__':
    main()
