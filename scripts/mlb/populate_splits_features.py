#!/usr/bin/env python3
"""
Populate Splits Features in pitcher_game_summary

Joins bdl_pitcher_splits data to pitcher_game_summary to populate:
- home_away_k_diff
- day_night_k_diff

These are seasonal features - each pitcher's performance difference
between home/away and day/night for that season.

Usage:
    python scripts/mlb/populate_splits_features.py [--dry-run]
"""

import argparse
import logging
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def check_splits_data(client: bigquery.Client) -> dict:
    """Check how much splits data we have."""
    query = """
    SELECT
        season,
        COUNT(*) as records,
        COUNT(home_away_k_diff) as has_home_away,
        COUNT(day_night_k_diff) as has_day_night,
        AVG(home_away_k_diff) as avg_home_away_diff,
        AVG(day_night_k_diff) as avg_day_night_diff
    FROM `nba-props-platform.mlb_raw.bdl_pitcher_splits`
    GROUP BY season
    ORDER BY season
    """
    result = list(client.query(query).result())

    stats = {}
    for row in result:
        stats[row.season] = {
            'records': row.records,
            'has_home_away': row.has_home_away,
            'has_day_night': row.has_day_night,
            'avg_home_away_diff': row.avg_home_away_diff,
            'avg_day_night_diff': row.avg_day_night_diff,
        }
    return stats


def populate_features(client: bigquery.Client, dry_run: bool = False) -> int:
    """Populate splits features in pitcher_game_summary."""

    # First check current state
    check_query = """
    SELECT
        COUNT(*) as total,
        COUNTIF(home_away_k_diff IS NOT NULL) as has_home_away,
        COUNTIF(day_night_k_diff IS NOT NULL) as has_day_night
    FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
    WHERE game_date >= '2024-01-01'
    """

    before = list(client.query(check_query).result())[0]
    logger.info(f"Before: total={before.total}, home_away={before.has_home_away}, day_night={before.has_day_night}")

    if dry_run:
        logger.info("DRY RUN: Would run UPDATE query")
        return 0

    # Update pitcher_game_summary with splits data
    update_query = """
    UPDATE `nba-props-platform.mlb_analytics.pitcher_game_summary` pgs
    SET
        home_away_k_diff = splits.home_away_k_diff,
        day_night_k_diff = splits.day_night_k_diff
    FROM (
        SELECT
            player_lookup,
            season,
            home_away_k_diff,
            day_night_k_diff
        FROM `nba-props-platform.mlb_raw.bdl_pitcher_splits`
        WHERE home_away_k_diff IS NOT NULL OR day_night_k_diff IS NOT NULL
    ) splits
    WHERE pgs.player_lookup = splits.player_lookup
      AND EXTRACT(YEAR FROM pgs.game_date) = splits.season
      AND pgs.game_date >= '2024-01-01'
    """

    try:
        job = client.query(update_query)
        result = job.result()
        rows_affected = job.num_dml_affected_rows
        logger.info(f"Updated {rows_affected} rows")

        # Check after
        after = list(client.query(check_query).result())[0]
        logger.info(f"After: total={after.total}, home_away={after.has_home_away}, day_night={after.has_day_night}")

        return rows_affected

    except Exception as e:
        logger.error(f"Update failed: {e}")
        return 0


def main():
    parser = argparse.ArgumentParser(description='Populate splits features')
    parser.add_argument('--dry-run', action='store_true', help='Do not update database')
    args = parser.parse_args()

    client = bigquery.Client()

    # Check splits data availability
    logger.info("Checking splits data...")
    stats = check_splits_data(client)
    for season, data in stats.items():
        logger.info(
            f"Season {season}: {data['records']} records, "
            f"avg home_away_diff={data['avg_home_away_diff']:.2f}, "
            f"avg day_night_diff={data['avg_day_night_diff']:.2f}"
        )

    # Populate features
    logger.info("\nPopulating features...")
    updated = populate_features(client, args.dry_run)
    logger.info(f"Total updated: {updated}")


if __name__ == '__main__':
    main()
