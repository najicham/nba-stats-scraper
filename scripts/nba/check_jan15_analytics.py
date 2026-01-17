#!/usr/bin/env python3
"""
Check what analytics data exists for Jan 15, 2026
"""

from google.cloud import bigquery

def check_jan15_analytics():
    client = bigquery.Client(project='nba-props-platform')

    print("=" * 80)
    print("CHECKING ANALYTICS DATA FOR JAN 15, 2026")
    print("=" * 80)

    # Check player_game_summary
    print("\n1. Player Game Summary")
    print("-" * 80)
    query1 = """
    SELECT COUNT(*) as records
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date = '2026-01-15'
    """
    result1 = client.query(query1).result()
    for row in result1:
        print(f"Records: {row.records}")

    # Check games with player_game_summary data
    print("\n2. Games with Player Game Summary Data")
    print("-" * 80)
    query2 = """
    SELECT game_id, COUNT(*) as player_count
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date = '2026-01-15'
    GROUP BY game_id
    ORDER BY game_id
    """
    result2 = client.query(query2).result()
    analytics_games = list(result2)
    if analytics_games:
        print(f"Found {len(analytics_games)} games with analytics data:")
        for row in analytics_games:
            print(f"  {row.game_id}: {row.player_count} players")
    else:
        print("No games found with analytics data")

    # Compare source vs analytics
    print("\n3. Source Data Comparison")
    print("-" * 80)
    query3 = """
    WITH source_games AS (
        SELECT DISTINCT game_code as game_id
        FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date = '2026-01-15'
    ),
    analytics_games AS (
        SELECT DISTINCT game_id
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE game_date = '2026-01-15'
    )
    SELECT
        'In Source Only' as status,
        s.game_id
    FROM source_games s
    LEFT JOIN analytics_games a ON s.game_id = a.game_id
    WHERE a.game_id IS NULL

    UNION ALL

    SELECT
        'In Analytics Only' as status,
        a.game_id
    FROM analytics_games a
    LEFT JOIN source_games s ON a.game_id = s.game_id
    WHERE s.game_id IS NULL

    ORDER BY status, game_id
    """
    result3 = client.query(query3).result()
    mismatches = list(result3)
    if mismatches:
        print(f"Found {len(mismatches)} games with mismatches:")
        for row in mismatches:
            print(f"  {row.status}: {row.game_id}")
    else:
        print("✓ All source games have corresponding analytics data")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    check_jan15_analytics()
