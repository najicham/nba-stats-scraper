#!/usr/bin/env python3
"""
Simple check for Jan 15, 2026 data
"""

from google.cloud import bigquery

def check_data():
    client = bigquery.Client(project='nba-props-platform')

    print("=" * 80)
    print("DATA AVAILABILITY CHECK - JANUARY 15, 2026")
    print("=" * 80)

    # Check what games were scheduled
    print("\n1. SCHEDULED GAMES")
    print("-" * 80)
    query_scheduled = """
    SELECT game_code, home_team_id, away_team_id, game_status_text
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE DATE(game_date) = '2026-01-15'
    ORDER BY game_code
    """
    result = client.query(query_scheduled).result()
    scheduled = list(result)
    print(f"Scheduled games: {len(scheduled)}")
    for row in scheduled:
        print(f"  {row.game_code}: Status={row.game_status_text}")

    # Check gamebook source data
    print("\n2. NBA.COM GAMEBOOK SOURCE DATA")
    print("-" * 80)
    query_gamebook = """
    SELECT game_code, COUNT(*) as players
    FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
    WHERE game_date = '2026-01-15'
    GROUP BY game_code
    ORDER BY game_code
    """
    result = client.query(query_gamebook).result()
    gamebook = list(result)
    print(f"Games with gamebook data: {len(gamebook)}")
    for row in gamebook:
        print(f"  {row.game_code}: {row.players} players")

    # Check BDL source data
    print("\n3. BDL BOXSCORE SOURCE DATA")
    print("-" * 80)
    query_bdl = """
    SELECT game_id, COUNT(*) as players
    FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
    WHERE game_date = '2026-01-15'
    GROUP BY game_id
    ORDER BY game_id
    """
    result = client.query(query_bdl).result()
    bdl = list(result)
    print(f"Games with BDL data: {len(bdl)}")
    for row in bdl:
        print(f"  {row.game_id}: {row.players} players")

    # Check analytics data
    print("\n4. ANALYTICS DATA (player_game_summary)")
    print("-" * 80)
    query_analytics = """
    SELECT game_id, COUNT(*) as players
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date = '2026-01-15'
    GROUP BY game_id
    ORDER BY game_id
    """
    result = client.query(query_analytics).result()
    analytics = list(result)
    print(f"Games with analytics data: {len(analytics)}")
    for row in analytics:
        print(f"  {row.game_id}: {row.players} players")

    # Show a sample of missing players
    print("\n5. SAMPLE PLAYERS IN SOURCE BUT NOT IN ANALYTICS")
    print("-" * 80)
    query_missing = """
    SELECT
        g.game_code,
        g.player_name,
        g.team_abbr,
        g.minutes,
        g.minutes_decimal,
        g.points,
        g.player_status
    FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats` g
    WHERE g.game_date = '2026-01-15'
    ORDER BY g.game_code, g.team_abbr, g.player_status, g.minutes_decimal DESC
    LIMIT 30
    """
    result = client.query(query_missing).result()
    print(f"{'Game':17} {'Player':25} {'Team':5} {'Min':5} {'Pts':5} {'Status':10}")
    print("-" * 80)
    for row in result:
        mins = row.minutes if row.minutes else 'DNP'
        pts = row.points if row.points is not None else '-'
        print(f"{row.game_code:17} {row.player_name:25} {row.team_abbr:5} {str(mins):5} {str(pts):5} {row.player_status:10}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Scheduled games:           {len(scheduled)}")
    print(f"Games with gamebook data:  {len(gamebook)}")
    print(f"Games with BDL data:       {len(bdl)}")
    print(f"Games with analytics data: {len(analytics)}")
    print()

    # Calculate totals
    gamebook_total = sum(g.players for g in gamebook)
    analytics_total = sum(a.players for a in analytics)

    print(f"Total players in gamebook: {gamebook_total}")
    print(f"Total players in analytics: {analytics_total}")
    print(f"Missing from analytics: {gamebook_total - analytics_total}")
    print(f"Capture rate: {(analytics_total / gamebook_total * 100):.1f}%")
    print("=" * 80)

if __name__ == "__main__":
    check_data()
