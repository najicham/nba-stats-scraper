#!/usr/bin/env python3
"""
Phase 3 Season Audit — Validates analytics completeness for the entire season.

Checks:
1. Player game summary coverage vs schedule
2. Team offense game summary coverage vs schedule
3. Data quality (DNPs marked, usage rates populated)
4. Cross-date consistency

Usage:
    PYTHONPATH=. python bin/monitoring/phase3_season_audit.py
    PYTHONPATH=. python bin/monitoring/phase3_season_audit.py --season 2025
    PYTHONPATH=. python bin/monitoring/phase3_season_audit.py --start 2026-01-01 --end 2026-02-10
    PYTHONPATH=. python bin/monitoring/phase3_season_audit.py --fix  # Show fix commands for gaps

Created: 2026-02-10 (Session 185)
"""

import argparse
import sys
from datetime import date

from google.cloud import bigquery


RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
CYAN = '\033[96m'
BOLD = '\033[1m'
RESET = '\033[0m'

PROJECT = 'nba-props-platform'


def run_audit(start_date: str, end_date: str, show_fix: bool = False):
    """Run the full Phase 3 season audit."""
    client = bigquery.Client(project=PROJECT)

    print(f"\n{BOLD}{'=' * 70}")
    print(f" Phase 3 Season Audit: {start_date} to {end_date}")
    print(f"{'=' * 70}{RESET}\n")

    # 1. Player Game Summary completeness
    print(f"{CYAN}[1/4] Player Game Summary Coverage{RESET}")
    pgs_gaps = check_pgs_coverage(client, start_date, end_date)

    # 2. Team Offense Game Summary completeness
    print(f"\n{CYAN}[2/4] Team Offense Game Summary Coverage{RESET}")
    team_gaps = check_team_coverage(client, start_date, end_date)

    # 3. Data quality checks
    print(f"\n{CYAN}[3/4] Data Quality Checks{RESET}")
    quality_issues = check_data_quality(client, start_date, end_date)

    # 4. Monthly summary
    print(f"\n{CYAN}[4/4] Monthly Summary{RESET}")
    show_monthly_summary(client, start_date, end_date)

    # Summary
    total_issues = len(pgs_gaps) + len(team_gaps) + len(quality_issues)
    print(f"\n{BOLD}{'=' * 70}")
    if total_issues == 0:
        print(f" {GREEN}AUDIT PASSED — No gaps found{RESET}")
    else:
        print(f" {YELLOW}AUDIT FOUND {total_issues} ISSUES{RESET}")
        if pgs_gaps:
            print(f"   PGS gaps: {len(pgs_gaps)} dates")
        if team_gaps:
            print(f"   Team gaps: {len(team_gaps)} date/team combos")
        if quality_issues:
            print(f"   Quality issues: {len(quality_issues)} dates")
    print(f"{'=' * 70}\n")

    # Show fix commands
    if show_fix and (pgs_gaps or team_gaps):
        print(f"\n{BOLD}Fix Commands:{RESET}")
        show_fix_commands(pgs_gaps, team_gaps)

    return total_issues


def check_pgs_coverage(client, start_date, end_date):
    """Check player_game_summary covers all scheduled games."""
    query = f"""
    WITH schedule AS (
      SELECT game_date, game_id, away_team_tricode, home_team_tricode
      FROM nba_reference.nba_schedule
      WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        AND game_status = 3
        AND is_regular_season = TRUE
    ),
    pgs AS (
      SELECT game_date, COUNT(DISTINCT game_id) as pgs_games
      FROM nba_analytics.player_game_summary
      WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      GROUP BY 1
    )
    SELECT
      s.game_date,
      COUNT(DISTINCT s.game_id) as scheduled,
      COALESCE(p.pgs_games, 0) as actual,
      COUNT(DISTINCT s.game_id) - COALESCE(p.pgs_games, 0) as missing
    FROM schedule s
    LEFT JOIN pgs p ON s.game_date = p.game_date
    GROUP BY s.game_date, p.pgs_games
    HAVING missing > 0
    ORDER BY s.game_date
    """
    rows = list(client.query(query).result())

    if not rows:
        print(f"  {GREEN}All games have player_game_summary records{RESET}")
    else:
        for row in rows:
            severity = RED if row.missing > 3 else YELLOW
            print(f"  {severity}{row.game_date}: {row.missing} games missing "
                  f"({row.actual}/{row.scheduled}){RESET}")

    return rows


def check_team_coverage(client, start_date, end_date):
    """Check team_offense_game_summary covers all teams that played."""
    query = f"""
    WITH expected_teams AS (
      SELECT game_date, away_team_tricode as team FROM nba_reference.nba_schedule
      WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        AND game_status = 3 AND is_regular_season = TRUE
      UNION ALL
      SELECT game_date, home_team_tricode FROM nba_reference.nba_schedule
      WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        AND game_status = 3 AND is_regular_season = TRUE
    ),
    actual_teams AS (
      SELECT game_date, team_abbr FROM nba_analytics.team_offense_game_summary
      WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    )
    SELECT e.game_date, e.team,
      CASE WHEN a.team_abbr IS NULL THEN 'MISSING' ELSE 'OK' END as status
    FROM expected_teams e
    LEFT JOIN actual_teams a ON e.game_date = a.game_date AND e.team = a.team_abbr
    WHERE a.team_abbr IS NULL
    ORDER BY e.game_date, e.team
    """
    rows = list(client.query(query).result())

    if not rows:
        print(f"  {GREEN}All teams have team_offense_game_summary records{RESET}")
    else:
        # Group by date for display
        by_date = {}
        for row in rows:
            d = str(row.game_date)
            by_date.setdefault(d, []).append(row.team)
        for d, teams in sorted(by_date.items()):
            print(f"  {YELLOW}{d}: Missing teams: {', '.join(teams)}{RESET}")

    return rows


def check_data_quality(client, start_date, end_date):
    """Check data quality metrics across the season."""
    query = f"""
    SELECT
      game_date,
      COUNT(*) as total,
      COUNTIF(is_dnp = FALSE AND minutes_played > 0) as active,
      COUNTIF(is_dnp = FALSE AND usage_rate IS NOT NULL AND usage_rate > 0) as has_usage,
      ROUND(100.0 * COUNTIF(is_dnp = FALSE AND usage_rate IS NOT NULL AND usage_rate > 0) /
        NULLIF(COUNTIF(is_dnp = FALSE AND minutes_played > 0), 0), 1) as usage_pct,
      COUNTIF(is_dnp = FALSE AND usage_rate > 50) as suspicious_usage
    FROM nba_analytics.player_game_summary
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY 1
    HAVING usage_pct < 80 OR suspicious_usage > 0
    ORDER BY usage_pct ASC
    """
    rows = list(client.query(query).result())

    if not rows:
        print(f"  {GREEN}Data quality checks passed (usage rate >= 80% everywhere){RESET}")
    else:
        for row in rows:
            severity = RED if (row.usage_pct or 0) < 50 else YELLOW
            extra = f", {row.suspicious_usage} suspicious (>50%)" if row.suspicious_usage else ""
            print(f"  {severity}{row.game_date}: usage_rate coverage {row.usage_pct}% "
                  f"({row.has_usage}/{row.active} active players){extra}{RESET}")

    return rows


def show_monthly_summary(client, start_date, end_date):
    """Show monthly Phase 3 health summary."""
    query = f"""
    WITH daily AS (
      SELECT
        game_date,
        COUNT(DISTINCT game_id) as games,
        COUNT(*) as records,
        COUNTIF(is_dnp = FALSE AND minutes_played > 0) as active
      FROM nba_analytics.player_game_summary
      WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      GROUP BY 1
    )
    SELECT
      FORMAT_DATE('%Y-%m', game_date) as month,
      COUNT(*) as game_dates,
      SUM(games) as total_games,
      SUM(records) as total_records,
      SUM(active) as total_active,
      ROUND(AVG(active * 1.0 / NULLIF(games, 0)), 0) as avg_active_per_game
    FROM daily
    GROUP BY 1
    ORDER BY 1
    """
    rows = list(client.query(query).result())

    print(f"  {'Month':<10} {'Dates':>6} {'Games':>6} {'Records':>8} {'Active':>7} {'Avg/Game':>9}")
    print(f"  {'-' * 50}")
    for row in rows:
        print(f"  {row.month:<10} {row.game_dates:>6} {row.total_games:>6} "
              f"{row.total_records:>8} {row.total_active:>7} {row.avg_active_per_game:>9.0f}")


def show_fix_commands(pgs_gaps, team_gaps):
    """Show commands to fix identified gaps."""
    analytics_url = "https://nba-phase3-analytics-processors-756957797294.us-west2.run.app"

    # Collect unique dates needing fixes
    fix_dates = set()
    for row in pgs_gaps:
        fix_dates.add(str(row.game_date))
    for row in team_gaps:
        fix_dates.add(str(row.game_date))

    for d in sorted(fix_dates):
        print(f'\n  # Fix {d}:')
        print(f'  curl -X POST "{analytics_url}/process-date-range" \\')
        print(f'    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \\')
        print(f'    -H "Content-Type: application/json" \\')
        print(f'    -d \'{{"start_date": "{d}", "end_date": "{d}", '
              f'"backfill_mode": true, "trigger_reason": "phase3_audit_fix"}}\'')


def main():
    parser = argparse.ArgumentParser(description='Phase 3 Season Audit')
    parser.add_argument('--season', type=int, default=2025,
                        help='Season year (default: 2025 for 2025-26 season)')
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--fix', action='store_true',
                        help='Show fix commands for gaps')
    args = parser.parse_args()

    if args.start and args.end:
        start_date = args.start
        end_date = args.end
    else:
        # Default: full season
        start_date = f'{args.season}-10-22'
        end_date = str(date.today())

    issues = run_audit(start_date, end_date, show_fix=args.fix)
    sys.exit(1 if issues > 0 else 0)


if __name__ == '__main__':
    main()
