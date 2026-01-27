#!/usr/bin/env python3
"""
Boxscore Completeness Monitor

Checks if all scheduled games have boxscore data in BigQuery.
Sends alerts when coverage drops below threshold.

Usage:
    # Check yesterday (default)
    python scripts/check_boxscore_completeness.py

    # Check specific date
    python scripts/check_boxscore_completeness.py --date 2025-12-23

    # Check last 7 days
    python scripts/check_boxscore_completeness.py --days 7

    # Dry run (no alerts)
    python scripts/check_boxscore_completeness.py --dry-run
"""

import argparse
import logging
import sys
from datetime import date, timedelta
from typing import Dict, List, Tuple
from google.cloud import bigquery

# Add parent to path for imports
sys.path.insert(0, '/home/naji/code/nba-stats-scraper')

from shared.utils.notification_system import notify_error, notify_warning, notify_info

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BoxscoreCompletenessMonitor:
    """Monitor boxscore data completeness."""

    # Thresholds
    ALERT_THRESHOLD = 90.0  # Warning if below
    CRITICAL_THRESHOLD = 70.0  # Critical if below

    def __init__(self):
        self.bq_client = bigquery.Client()
        self.project_id = self.bq_client.project

    def check_completeness(
        self,
        start_date: date,
        end_date: date
    ) -> Tuple[Dict[str, dict], List[dict]]:
        """
        Check boxscore completeness for date range.

        Returns:
            Tuple of (team_coverage, missing_games)
        """
        # Query team coverage
        coverage_query = f"""
        WITH schedule AS (
          SELECT game_date, home_team_tricode as team FROM nba_raw.nbac_schedule
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
          UNION ALL
          SELECT game_date, away_team_tricode as team FROM nba_raw.nbac_schedule
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        ),
        team_games AS (
          SELECT team, COUNT(DISTINCT game_date) as scheduled_games
          FROM schedule
          GROUP BY team
        ),
        boxscore_games AS (
          SELECT team_abbr, COUNT(DISTINCT game_date) as boxscore_games
          FROM nba_raw.bdl_player_boxscores
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
          GROUP BY team_abbr
        )
        SELECT
          t.team,
          t.scheduled_games,
          COALESCE(b.boxscore_games, 0) as boxscore_games,
          ROUND(COALESCE(b.boxscore_games, 0) * 100.0 / t.scheduled_games, 1) as coverage_pct
        FROM team_games t
        LEFT JOIN boxscore_games b ON t.team = b.team_abbr
        ORDER BY coverage_pct, t.team
        """

        coverage_result = self.bq_client.query(coverage_query).result(timeout=60)
        team_coverage = {}
        for row in coverage_result:
            team_coverage[row.team] = {
                'scheduled': row.scheduled_games,
                'actual': row.boxscore_games,
                'coverage_pct': row.coverage_pct
            }

        # Query missing games
        missing_query = f"""
        WITH schedule AS (
          SELECT game_date, home_team_tricode as team FROM nba_raw.nbac_schedule
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
          UNION ALL
          SELECT game_date, away_team_tricode as team FROM nba_raw.nbac_schedule
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        ),
        boxscores AS (
          SELECT DISTINCT game_date, team_abbr FROM nba_raw.bdl_player_boxscores
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        )
        SELECT s.game_date, s.team
        FROM schedule s
        LEFT JOIN boxscores b ON s.game_date = b.game_date AND s.team = b.team_abbr
        WHERE b.team_abbr IS NULL
        ORDER BY s.game_date, s.team
        """

        missing_result = self.bq_client.query(missing_query).result(timeout=60)
        missing_games = [
            {'date': row.game_date.isoformat(), 'team': row.team}
            for row in missing_result
        ]

        return team_coverage, missing_games

    def analyze_results(
        self,
        team_coverage: Dict[str, dict],
        missing_games: List[dict]
    ) -> dict:
        """Analyze results and determine alert level."""
        critical_teams = []
        warning_teams = []
        ok_teams = []

        for team, data in team_coverage.items():
            if data['coverage_pct'] < self.CRITICAL_THRESHOLD:
                critical_teams.append((team, data['coverage_pct']))
            elif data['coverage_pct'] < self.ALERT_THRESHOLD:
                warning_teams.append((team, data['coverage_pct']))
            else:
                ok_teams.append((team, data['coverage_pct']))

        # Determine overall status
        if critical_teams:
            status = 'CRITICAL'
        elif warning_teams:
            status = 'WARNING'
        elif missing_games:
            status = 'MINOR'
        else:
            status = 'OK'

        return {
            'status': status,
            'critical_teams': critical_teams,
            'warning_teams': warning_teams,
            'ok_teams': ok_teams,
            'missing_count': len(missing_games),
            'missing_dates': list(set(g['date'] for g in missing_games))
        }

    def send_alerts(
        self,
        analysis: dict,
        start_date: date,
        end_date: date,
        dry_run: bool = False
    ):
        """Send appropriate alerts based on analysis."""
        if analysis['status'] == 'OK':
            logger.info("All boxscore data complete. No alerts needed.")
            return

        date_range = f"{start_date} to {end_date}" if start_date != end_date else str(start_date)

        if analysis['status'] == 'CRITICAL':
            title = f"CRITICAL: Boxscore Data Gaps ({date_range})"
            message = self._build_alert_message(analysis, 'critical')

            if dry_run:
                logger.info(f"[DRY RUN] Would send CRITICAL alert: {title}")
                logger.info(f"Message: {message}")
            else:
                notify_error(
                    title=title,
                    message=message,
                    context={
                        'critical_teams': analysis['critical_teams'],
                        'missing_dates': analysis['missing_dates']
                    }
                )

        elif analysis['status'] == 'WARNING':
            title = f"WARNING: Boxscore Coverage Below {self.ALERT_THRESHOLD}% ({date_range})"
            message = self._build_alert_message(analysis, 'warning')

            if dry_run:
                logger.info(f"[DRY RUN] Would send WARNING alert: {title}")
                logger.info(f"Message: {message}")
            else:
                notify_warning(
                    title=title,
                    message=message,
                    context={
                        'warning_teams': analysis['warning_teams'],
                        'missing_dates': analysis['missing_dates']
                    },
                    processor_name=self.__class__.__name__
                )

        elif analysis['status'] == 'MINOR':
            title = f"INFO: {analysis['missing_count']} Missing Boxscore Games ({date_range})"
            message = self._build_alert_message(analysis, 'info')

            if dry_run:
                logger.info(f"[DRY RUN] Would send INFO alert: {title}")
            else:
                logger.info(f"Minor gaps detected: {analysis['missing_count']} missing games")
                # Only log, don't send email for minor issues

    def _build_alert_message(self, analysis: dict, level: str) -> str:
        """Build alert message."""
        lines = []

        if analysis['critical_teams']:
            lines.append("CRITICAL TEAMS (below 70%):")
            for team, pct in analysis['critical_teams']:
                lines.append(f"  - {team}: {pct}%")
            lines.append("")

        if analysis['warning_teams']:
            lines.append("WARNING TEAMS (below 90%):")
            for team, pct in analysis['warning_teams']:
                lines.append(f"  - {team}: {pct}%")
            lines.append("")

        if analysis['missing_dates']:
            lines.append(f"Missing dates: {', '.join(analysis['missing_dates'])}")
            lines.append("")

        lines.append("To backfill, run:")
        lines.append(f"  ./bin/monitoring/check_boxscore_completeness.sh --days 7")
        lines.append("")
        lines.append("See docs/08-projects/current/BOXSCORE-GAPS-AND-CIRCUIT-BREAKERS.md")

        return "\n".join(lines)

    def print_report(self, team_coverage: Dict, missing_games: List, analysis: dict):
        """Print human-readable report."""
        print("\n" + "=" * 60)
        print("BOXSCORE COMPLETENESS REPORT")
        print("=" * 60)

        print("\nTeam Coverage:")
        print("-" * 40)

        for team, data in sorted(team_coverage.items(), key=lambda x: x[1]['coverage_pct']):
            pct = data['coverage_pct']
            status = ""
            if pct < self.CRITICAL_THRESHOLD:
                status = " [CRITICAL]"
            elif pct < self.ALERT_THRESHOLD:
                status = " [WARNING]"

            print(f"  {team}: {pct}% ({data['actual']}/{data['scheduled']} games){status}")

        print(f"\nMissing Games: {len(missing_games)}")
        print("-" * 40)

        if missing_games:
            for game in missing_games[:20]:
                print(f"  {game['date']}: {game['team']}")
            if len(missing_games) > 20:
                print(f"  ... and {len(missing_games) - 20} more")
        else:
            print("  None!")

        print(f"\nOverall Status: {analysis['status']}")
        print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Check boxscore completeness")
    parser.add_argument('--date', type=str, help='Specific date (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, default=1, help='Check last N days')
    parser.add_argument('--dry-run', action='store_true', help='Do not send alerts')
    parser.add_argument('--quiet', action='store_true', help='Minimal output')
    args = parser.parse_args()

    # Determine date range
    if args.date:
        start_date = end_date = date.fromisoformat(args.date)
    else:
        end_date = date.today() - timedelta(days=1)  # Yesterday
        start_date = end_date - timedelta(days=args.days - 1)

    logger.info(f"Checking boxscore completeness: {start_date} to {end_date}")

    monitor = BoxscoreCompletenessMonitor()

    # Run check
    team_coverage, missing_games = monitor.check_completeness(start_date, end_date)
    analysis = monitor.analyze_results(team_coverage, missing_games)

    # Print report
    if not args.quiet:
        monitor.print_report(team_coverage, missing_games, analysis)

    # Send alerts
    monitor.send_alerts(analysis, start_date, end_date, dry_run=args.dry_run)

    # Exit code based on status
    if analysis['status'] == 'CRITICAL':
        sys.exit(2)
    elif analysis['status'] in ('WARNING', 'MINOR'):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
