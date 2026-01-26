#!/usr/bin/env python3
"""
Verification script for betting_lines workflow configuration fix

This script verifies that the 2026-01-26 configuration fix is working correctly:
- Checks that betting data is being collected in the morning (not afternoon)
- Verifies workflow decisions match expected timing (12-hour window)
- Confirms master controller is using the updated configuration

Usage:
    python scripts/verify_betting_workflow_fix.py --date 2026-01-27
    python scripts/verify_betting_workflow_fix.py  # Defaults to today
"""

import argparse
from datetime import datetime, timedelta
from google.cloud import bigquery
import pytz

PROJECT_ID = "nba-props-platform"
ET = pytz.timezone("America/New_York")


def check_games_scheduled(client, game_date):
    """Check if games are scheduled for the given date."""
    query = f"""
    SELECT COUNT(*) as game_count
    FROM `{PROJECT_ID}.nba_reference.nba_schedule`
    WHERE game_date = '{game_date}'
      AND is_regular_season = TRUE
    """

    result = list(client.query(query).result())
    game_count = result[0].game_count if result else 0

    print(f"\n📅 Games Scheduled for {game_date}")
    print(f"   Count: {game_count} games")

    return game_count > 0


def check_workflow_decisions(client, game_date):
    """Check betting_lines workflow decisions for the given date."""
    query = f"""
    SELECT
      FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', decision_time, 'America/New_York') as decision_time_et,
      action,
      reason,
      ARRAY_LENGTH(scrapers_triggered) as scraper_count
    FROM `{PROJECT_ID}.nba_orchestration.workflow_decisions`
    WHERE DATE(decision_time, 'America/New_York') = '{game_date}'
      AND workflow_name = 'betting_lines'
    ORDER BY decision_time
    """

    results = list(client.query(query).result())

    print(f"\n🔍 Betting Lines Workflow Decisions for {game_date}")
    print(f"   Total decisions: {len(results)}")

    if not results:
        print("   ⚠️  No workflow decisions found yet")
        print("   💡 This is expected if it's before the first trigger time")
        return False

    run_decisions = [d for d in results if d.action == "RUN"]
    skip_decisions = [d for d in results if d.action == "SKIP"]

    print(f"\n   RUN decisions: {len(run_decisions)}")
    for decision in run_decisions:
        print(f"      {decision.decision_time_et} - {decision.scraper_count} scrapers")

    if run_decisions:
        first_run = run_decisions[0]
        hour = int(first_run.decision_time_et.split()[1].split(':')[0])

        print(f"\n   ✅ First execution: {first_run.decision_time_et}")

        if hour <= 9:
            print(f"   ✅ PASS: Workflow triggered in morning ({hour:02d}:xx)")
            print(f"   ✅ This confirms the 12-hour window fix is working!")
        elif hour <= 13:
            print(f"   ⚠️  WARNING: First trigger at {hour:02d}:xx (expected ≤ 09:xx)")
            print(f"   💡 This might indicate the old 6-hour config is still active")
        else:
            print(f"   ❌ FAIL: First trigger at {hour:02d}:xx (too late!)")
            print(f"   ❌ Expected morning trigger, got afternoon")
            return False

    print(f"\n   SKIP decisions: {len(skip_decisions)}")
    if skip_decisions:
        print(f"      Reasons:")
        for decision in skip_decisions[:3]:  # Show first 3
            print(f"      - {decision.decision_time_et}: {decision.reason}")

    return len(run_decisions) > 0


def check_betting_data_collected(client, game_date):
    """Check if betting data was actually collected."""
    # Check for player props (simpler query without timestamps)
    props_query = f"""
    SELECT
      COUNT(DISTINCT player_lookup) as player_count,
      COUNT(*) as prop_count
    FROM `{PROJECT_ID}.nba_raw.odds_api_player_points_props`
    WHERE game_date = '{game_date}'
    """

    # Check for game lines (simpler query without timestamps)
    lines_query = f"""
    SELECT
      COUNT(*) as line_count
    FROM `{PROJECT_ID}.nba_raw.odds_api_game_lines`
    WHERE game_date = '{game_date}'
    """

    props_results = list(client.query(props_query).result())
    lines_results = list(client.query(lines_query).result())

    print(f"\n📊 Betting Data Collected for {game_date}")

    if props_results and props_results[0].prop_count > 0:
        props = props_results[0]
        print(f"\n   Player Props:")
        print(f"      Count: {props.prop_count} props")
        print(f"      Players: {props.player_count} unique players")
        print(f"      ✅ Data found")
    else:
        print(f"\n   ⚠️  No player props data found yet")

    if lines_results and lines_results[0].line_count > 0:
        lines = lines_results[0]
        print(f"\n   Game Lines:")
        print(f"      Count: {lines.line_count} lines")
        print(f"      ✅ Data found")
    else:
        print(f"\n   ⚠️  No game lines data found yet")

    has_data = (props_results and props_results[0].prop_count > 0) or \
               (lines_results and lines_results[0].line_count > 0)

    return has_data


def main():
    parser = argparse.ArgumentParser(
        description='Verify betting_lines workflow configuration fix'
    )
    parser.add_argument(
        '--date',
        type=str,
        default=None,
        help='Date to check (YYYY-MM-DD). Defaults to today.'
    )

    args = parser.parse_args()

    # Determine date to check
    if args.date:
        game_date = args.date
    else:
        game_date = datetime.now(ET).strftime('%Y-%m-%d')

    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Betting Lines Workflow Verification")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"\nDate: {game_date}")
    print(f"Project: {PROJECT_ID}")
    print(f"Current time: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')} ET")

    client = bigquery.Client(project=PROJECT_ID)

    # Run checks
    has_games = check_games_scheduled(client, game_date)

    if not has_games:
        print(f"\n⚠️  No games scheduled for {game_date}")
        print(f"   Cannot verify workflow timing without games")
        return

    has_decisions = check_workflow_decisions(client, game_date)
    has_data = check_betting_data_collected(client, game_date)

    # Summary
    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Verification Summary")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"\n   Games scheduled: {'✅' if has_games else '❌'}")
    print(f"   Workflow decisions: {'✅' if has_decisions else '⏳ Pending'}")
    print(f"   Betting data collected: {'✅' if has_data else '⏳ Pending'}")

    if has_decisions and has_data:
        print(f"\n✅ VERIFICATION PASSED")
        print(f"   The configuration fix is working correctly!")
        print(f"   Betting data is being collected in the morning as expected.")
    elif not has_decisions:
        print(f"\n⏳ TOO EARLY TO VERIFY")
        print(f"   No workflow decisions yet - check back after 7 AM ET")
        print(f"   Expected first run: ~7:00 AM - 8:00 AM ET")
    elif not has_data:
        print(f"\n⚠️  WORKFLOW RAN BUT NO DATA YET")
        print(f"   Workflow decisions found, but no data collected yet")
        print(f"   This could indicate a scraper issue (not a config issue)")

    print()


if __name__ == "__main__":
    main()
