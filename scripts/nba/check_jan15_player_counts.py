#!/usr/bin/env python3
"""
Compare player counts between source and analytics for Jan 15, 2026
"""

from google.cloud import bigquery

def check_player_counts():
    client = bigquery.Client(project='nba-props-platform')

    print("=" * 80)
    print("PLAYER COUNT COMPARISON - JAN 15, 2026")
    print("=" * 80)

    query = """
    WITH source_counts AS (
        SELECT
            REPLACE(game_code, '/', '_') as game_id,
            COUNT(*) as source_players
        FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date = '2026-01-15'
        GROUP BY game_code
    ),
    analytics_counts AS (
        SELECT
            game_id,
            COUNT(*) as analytics_players
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE game_date = '2026-01-15'
        GROUP BY game_id
    )
    SELECT
        COALESCE(s.game_id, a.game_id) as game_id,
        COALESCE(s.source_players, 0) as source_players,
        COALESCE(a.analytics_players, 0) as analytics_players,
        COALESCE(s.source_players, 0) - COALESCE(a.analytics_players, 0) as difference
    FROM source_counts s
    FULL OUTER JOIN analytics_counts a ON s.game_id = a.game_id
    ORDER BY game_id
    """

    result = client.query(query).result()

    print("\nGame                    Source  Analytics  Difference")
    print("-" * 80)

    total_source = 0
    total_analytics = 0
    missing_players = 0

    for row in result:
        total_source += row.source_players
        total_analytics += row.analytics_players
        if row.difference > 0:
            missing_players += row.difference
            print(f"{row.game_id:20} {row.source_players:6} {row.analytics_players:10} {row.difference:11} ⚠️")
        else:
            print(f"{row.game_id:20} {row.source_players:6} {row.analytics_players:10} {row.difference:11}")

    print("-" * 80)
    print(f"{'TOTALS':20} {total_source:6} {total_analytics:10} {total_source - total_analytics:11}")
    print()
    print(f"Missing players in analytics: {missing_players}")
    print(f"Percentage captured: {(total_analytics / total_source * 100):.1f}%")
    print("=" * 80)

    # Show sample of missing players
    print("\nSAMPLE OF MISSING PLAYERS (first 20)")
    print("-" * 80)
    query2 = """
    WITH analytics_players AS (
        SELECT player_name, game_id
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE game_date = '2026-01-15'
    )
    SELECT
        REPLACE(g.game_code, '/', '_') as game_id,
        g.player_name,
        g.team_abbr,
        g.minutes,
        g.points,
        g.player_status
    FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats` g
    LEFT JOIN analytics_players a
        ON g.player_name = a.player_name
        AND REPLACE(g.game_code, '/', '_') = a.game_id
    WHERE g.game_date = '2026-01-15'
        AND a.player_name IS NULL
    ORDER BY g.game_code, g.team_abbr, g.player_status, g.minutes DESC
    LIMIT 20
    """

    result2 = client.query(query2).result()

    print(f"{'Game ID':20} {'Player Name':25} {'Team':5} {'Min':5} {'Pts':5} {'Status':10}")
    print("-" * 80)
    for row in result2:
        mins = row.minutes if row.minutes else 'DNP'
        pts = row.points if row.points is not None else '-'
        print(f"{row.game_id:20} {row.player_name:25} {row.team_abbr:5} {str(mins):5} {str(pts):5} {row.player_status:10}")

    print("=" * 80)

if __name__ == "__main__":
    check_player_counts()
