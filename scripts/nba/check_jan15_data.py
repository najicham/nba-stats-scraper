#!/usr/bin/env python3
"""
Quick script to check if source data exists for Jan 15, 2026
"""

from google.cloud import bigquery

def check_jan15_data():
    client = bigquery.Client(project='nba-props-platform')

    print("=" * 80)
    print("CHECKING SOURCE DATA FOR JAN 15, 2026")
    print("=" * 80)

    # Check NBA.com gamebook
    print("\n1. NBA.com Gamebook Player Stats")
    print("-" * 80)
    query1 = """
    SELECT COUNT(*) as records
    FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
    WHERE game_date = '2026-01-15'
    """
    result1 = client.query(query1).result()
    for row in result1:
        print(f"Records: {row.records}")

    # Check BDL boxscores
    print("\n2. BDL Player Boxscores")
    print("-" * 80)
    query2 = """
    SELECT COUNT(*) as records
    FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
    WHERE game_date = '2026-01-15'
    """
    result2 = client.query(query2).result()
    for row in result2:
        print(f"Records: {row.records}")

    # Check what games we have gamebook data for
    print("\n3. Games with Gamebook Data")
    print("-" * 80)
    query3 = """
    SELECT DISTINCT game_code, COUNT(*) as player_count
    FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
    WHERE game_date = '2026-01-15'
    GROUP BY game_code
    ORDER BY game_code
    """
    result3 = client.query(query3).result()
    games = list(result3)
    if games:
        print(f"Found {len(games)} games with gamebook data:")
        for row in games:
            print(f"  {row.game_code}: {row.player_count} players")
    else:
        print("No games found with gamebook data")

    # Additional check: What games were scheduled?
    print("\n4. Games Scheduled for Jan 15, 2026")
    print("-" * 80)
    query4 = """
    SELECT game_id, game_code, home_team_id, away_team_id, game_status, game_status_text
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE DATE(game_date) = '2026-01-15'
    ORDER BY game_code
    """
    result4 = client.query(query4).result()
    scheduled_games = list(result4)
    if scheduled_games:
        print(f"Found {len(scheduled_games)} scheduled games:")
        for row in scheduled_games:
            print(f"  {row.game_code}: {row.away_team_id} @ {row.home_team_id} - Status: {row.game_status_text}")
    else:
        print("No games scheduled")

    # Check if BDL has any data at all for this date
    print("\n5. BDL Boxscores Detail")
    print("-" * 80)
    query5 = """
    SELECT game_id, COUNT(*) as player_count
    FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
    WHERE game_date = '2026-01-15'
    GROUP BY game_id
    ORDER BY game_id
    """
    result5 = client.query(query5).result()
    bdl_games = list(result5)
    if bdl_games:
        print(f"Found {len(bdl_games)} games in BDL boxscores:")
        for row in bdl_games:
            print(f"  Game ID {row.game_id}: {row.player_count} players")
    else:
        print("No games found in BDL boxscores")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Scheduled games: {len(scheduled_games)}")
    print(f"Games with NBA.com gamebook data: {len(games)}")
    print(f"Games with BDL boxscore data: {len(bdl_games)}")

    if len(scheduled_games) > 0:
        if len(games) == 0 and len(bdl_games) == 0:
            print("\n⚠️  NO SOURCE DATA EXISTS for Jan 15, 2026")
            print("Games were scheduled but no gamebook or boxscore data was collected.")
        elif len(games) < len(scheduled_games) or len(bdl_games) < len(scheduled_games):
            print("\n⚠️  PARTIAL SOURCE DATA")
            print(f"Missing gamebook data for {len(scheduled_games) - len(games)} games")
            print(f"Missing BDL data for {len(scheduled_games) - len(bdl_games)} games")
        else:
            print("\n✓ All scheduled games have source data")
    else:
        print("\n⚠️  No games were scheduled for Jan 15, 2026")

    print("=" * 80)

if __name__ == "__main__":
    check_jan15_data()
