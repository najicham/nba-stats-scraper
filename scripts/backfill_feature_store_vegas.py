#!/usr/bin/env python3
"""
Backfill Feature Store Vegas Lines

Fixes ml_feature_store_v2 records that have vegas_line = 0 by looking up
the correct values from upcoming_player_game_context (Phase 3).

Background:
- Feature store was querying bettingpros_player_points_props only
- BettingPros scraper was down Oct-Nov 2025
- Phase 3 uses odds_api as primary source, so it has data
- This script backfills the missing Vegas data

Usage:
    PYTHONPATH=. python scripts/backfill_feature_store_vegas.py --start 2025-11-01 --end 2025-12-31
    PYTHONPATH=. python scripts/backfill_feature_store_vegas.py --start 2025-11-01 --end 2025-12-31 --dry-run

Session 59 - Odds Data Cascade Fix
"""

import argparse
import sys
from datetime import datetime, date
from google.cloud import bigquery
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"


def get_fixable_records(client: bigquery.Client, start_date: str, end_date: str) -> list:
    """Get records that can be fixed (have Phase 3 data but feature store has vegas=0)."""

    query = f"""
    WITH feature_store AS (
        SELECT
            player_lookup,
            game_date,
            feature_version,
            feature_count,
            features,
            feature_quality_score,
            quality_tier
        FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
          AND feature_count >= 33
          AND features[SAFE_OFFSET(25)] = 0  -- Currently missing vegas
    ),
    phase3 AS (
        SELECT
            player_lookup,
            game_date,
            current_points_line,
            opening_points_line,
            line_movement,
            has_prop_line
        FROM `{PROJECT_ID}.nba_analytics.upcoming_player_game_context`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
          AND current_points_line IS NOT NULL
          AND current_points_line > 0
    )
    SELECT
        f.player_lookup,
        f.game_date,
        f.feature_version,
        f.feature_count,
        f.features,
        f.feature_quality_score,
        f.quality_tier,
        p.current_points_line,
        p.opening_points_line,
        p.line_movement
    FROM feature_store f
    INNER JOIN phase3 p ON f.player_lookup = p.player_lookup AND f.game_date = p.game_date
    ORDER BY f.game_date, f.player_lookup
    """

    result = client.query(query).to_dataframe()
    return result.to_dict('records')


def fix_features_array(features: list, vegas_line: float, opening_line: float, line_move: float) -> list:
    """Update the features array with correct Vegas values."""
    # Features array indices for Vegas:
    # 25: vegas_points_line
    # 26: vegas_opening_line
    # 27: vegas_line_move
    # 28: has_vegas_line

    new_features = list(features)  # Copy the array

    new_features[25] = float(vegas_line) if vegas_line else 0.0
    new_features[26] = float(opening_line) if opening_line else float(vegas_line) if vegas_line else 0.0
    new_features[27] = float(line_move) if line_move else 0.0
    new_features[28] = 1.0 if vegas_line else 0.0

    return new_features


def backfill_records(client: bigquery.Client, records: list, dry_run: bool = False) -> int:
    """Delete and re-insert records with fixed Vegas data."""

    if not records:
        logger.info("No records to fix")
        return 0

    # Group by date for batch processing
    by_date = {}
    for r in records:
        game_date = r['game_date'].strftime('%Y-%m-%d') if hasattr(r['game_date'], 'strftime') else str(r['game_date'])
        if game_date not in by_date:
            by_date[game_date] = []
        by_date[game_date].append(r)

    total_fixed = 0

    for game_date, date_records in by_date.items():
        logger.info(f"Processing {game_date}: {len(date_records)} records")

        if dry_run:
            for r in date_records[:3]:  # Show first 3 as sample
                logger.info(f"  Would fix: {r['player_lookup']} - vegas_line: {r['current_points_line']}")
            total_fixed += len(date_records)
            continue

        # Build delete query
        player_lookups = [r['player_lookup'] for r in date_records]
        delete_query = f"""
        DELETE FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
        WHERE game_date = '{game_date}'
          AND player_lookup IN ({','.join([f"'{p}'" for p in player_lookups])})
        """

        # Execute delete
        client.query(delete_query).result()

        # Build insert rows with fixed features
        rows_to_insert = []
        for r in date_records:
            fixed_features = fix_features_array(
                r['features'],
                r['current_points_line'],
                r['opening_points_line'],
                r['line_movement']
            )

            rows_to_insert.append({
                'player_lookup': r['player_lookup'],
                'game_date': game_date,
                'feature_version': r['feature_version'],
                'feature_count': r['feature_count'],
                'features': fixed_features,
                'feature_quality_score': float(r['feature_quality_score']) if r['feature_quality_score'] else None,
                'quality_tier': r['quality_tier'],
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat(),
            })

        # Insert fixed records
        table_ref = f"{PROJECT_ID}.nba_predictions.ml_feature_store_v2"
        errors = client.insert_rows_json(table_ref, rows_to_insert)

        if errors:
            logger.error(f"Errors inserting rows for {game_date}: {errors}")
        else:
            logger.info(f"  Fixed {len(date_records)} records")
            total_fixed += len(date_records)

    return total_fixed


def main():
    parser = argparse.ArgumentParser(description='Backfill feature store Vegas lines from Phase 3')
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be fixed without making changes')
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info(" BACKFILL FEATURE STORE VEGAS LINES")
    logger.info("=" * 70)
    logger.info(f"Date range: {args.start} to {args.end}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("")

    client = bigquery.Client(project=PROJECT_ID)

    # Get fixable records
    logger.info("Finding records that need fixing...")
    records = get_fixable_records(client, args.start, args.end)
    logger.info(f"Found {len(records)} records to fix")

    if not records:
        logger.info("No records need fixing!")
        return

    # Show summary by month
    by_month = {}
    for r in records:
        month = r['game_date'].strftime('%Y-%m') if hasattr(r['game_date'], 'strftime') else str(r['game_date'])[:7]
        by_month[month] = by_month.get(month, 0) + 1

    logger.info("Records to fix by month:")
    for month, count in sorted(by_month.items()):
        logger.info(f"  {month}: {count}")
    logger.info("")

    # Execute backfill
    if args.dry_run:
        logger.info("DRY RUN - No changes will be made")
        logger.info("")

    total_fixed = backfill_records(client, records, args.dry_run)

    logger.info("")
    logger.info("=" * 70)
    if args.dry_run:
        logger.info(f"DRY RUN COMPLETE: Would fix {total_fixed} records")
    else:
        logger.info(f"BACKFILL COMPLETE: Fixed {total_fixed} records")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
