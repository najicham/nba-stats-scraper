#!/usr/bin/env python3
"""
Cleanup duplicate records in player_game_summary.
One-time maintenance script.

This script identifies and removes duplicate player-game records,
keeping the most recent record by processed_at timestamp.

Usage:
    # Dry run (default) - shows what would be done
    python scripts/maintenance/cleanup_duplicates.py

    # Execute cleanup
    python scripts/maintenance/cleanup_duplicates.py --execute
"""

from google.cloud import bigquery

PROJECT_ID = 'nba-props-platform'


def cleanup_duplicates(dry_run: bool = True):
    """
    Remove duplicate records from player_game_summary table.

    Args:
        dry_run: If True, only count duplicates. If False, execute cleanup.
    """
    client = bigquery.Client(project=PROJECT_ID)

    if dry_run:
        # Count duplicates instead of cleaning
        count_query = """
        SELECT COUNT(*) as duplicate_count FROM (
            SELECT game_id, player_lookup, COUNT(*) as cnt
            FROM `{project}.nba_analytics.player_game_summary`
            GROUP BY game_id, player_lookup
            HAVING cnt > 1
        )
        """.format(project=PROJECT_ID)

        result = client.query(count_query).result()
        count = next(result).duplicate_count
        print(f"DRY RUN: Would remove duplicates from {count} player-game combinations")

        # Also show sample of duplicates
        if count > 0:
            sample_query = """
            SELECT
                game_id,
                player_lookup,
                COUNT(*) as duplicate_count,
                MIN(processed_at) as earliest,
                MAX(processed_at) as latest
            FROM `{project}.nba_analytics.player_game_summary`
            GROUP BY game_id, player_lookup
            HAVING COUNT(*) > 1
            ORDER BY duplicate_count DESC, game_id
            LIMIT 10
            """.format(project=PROJECT_ID)

            print("\nSample of duplicates:")
            print("game_id | player_lookup | count | earliest | latest")
            print("-" * 80)
            for row in client.query(sample_query).result():
                print(f"{row.game_id} | {row.player_lookup} | {row.duplicate_count} | {row.earliest} | {row.latest}")

        return

    # Execute cleanup
    # Use CREATE OR REPLACE to rebuild the table with deduplicated data
    cleanup_query = """
    CREATE OR REPLACE TABLE `{project}.nba_analytics.player_game_summary` AS
    SELECT * EXCEPT(rn) FROM (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY game_id, player_lookup
                ORDER BY processed_at DESC
            ) as rn
        FROM `{project}.nba_analytics.player_game_summary`
    ) WHERE rn = 1
    """.format(project=PROJECT_ID)

    print("Executing cleanup...")
    job = client.query(cleanup_query)
    job.result()  # Wait for completion
    print("Cleanup complete")

    # Show final verification
    verify_query = """
    SELECT COUNT(*) as duplicate_count FROM (
        SELECT game_id, player_lookup, COUNT(*) as cnt
        FROM `{project}.nba_analytics.player_game_summary`
        GROUP BY game_id, player_lookup
        HAVING cnt > 1
    )
    """.format(project=PROJECT_ID)

    result = client.query(verify_query).result()
    remaining = next(result).duplicate_count
    print(f"Verification: {remaining} duplicate player-game combinations remaining (should be 0)")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(
        description='Cleanup duplicate records in player_game_summary table'
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually execute cleanup (default is dry-run mode)'
    )
    args = parser.parse_args()

    cleanup_duplicates(dry_run=not args.execute)
