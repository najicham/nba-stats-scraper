"""
Roster Coverage Monitor
========================
Monitors ESPN roster freshness in BigQuery to catch stale data that breaks predictions.

This module addresses the Jan 23, 2026 incident where stale ESPN rosters
(last updated Jan 14) caused POR/SAC players to be missing from predictions.

Key Checks:
1. All 30 teams should have roster data within MAX_ROSTER_AGE_DAYS
2. Alert if any team's roster is older than threshold
3. Special alert for teams playing today with stale rosters

Usage:
    # Run as standalone check
    python -m monitoring.nba.roster_coverage_monitor

    # Import and use
    from monitoring.nba.roster_coverage_monitor import RosterCoverageMonitor
    monitor = RosterCoverageMonitor()
    issues = monitor.check_roster_coverage()
"""

import logging
import os
from datetime import date, datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class RosterIssue:
    """Represents a roster freshness issue."""
    team: str
    latest_roster_date: Optional[date]
    age_days: int
    is_playing_today: bool
    severity: AlertSeverity
    message: str

    def to_dict(self) -> dict:
        return {
            'team': self.team,
            'latest_roster_date': self.latest_roster_date.isoformat() if self.latest_roster_date else None,
            'age_days': self.age_days,
            'is_playing_today': self.is_playing_today,
            'severity': self.severity.value,
            'message': self.message
        }


class RosterCoverageMonitor:
    """
    Monitors roster coverage in BigQuery.

    Thresholds:
    - WARNING: Any team > 3 days stale
    - CRITICAL: Any team > 5 days stale
    - CRITICAL: Team playing today with > 2 days stale roster
    """

    # Thresholds for roster staleness
    MAX_ROSTER_AGE_DAYS_WARNING = 3
    MAX_ROSTER_AGE_DAYS_CRITICAL = 5
    MAX_ROSTER_AGE_DAYS_GAME_DAY = 2

    # Total NBA teams
    EXPECTED_TEAMS = 30

    def __init__(self, project_id: str = None):
        """Initialize monitor with BigQuery client."""
        self.project_id = project_id or os.environ.get('GCP_PROJECT', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        logger.info(f"RosterCoverageMonitor initialized for project: {self.project_id}")

    def check_roster_coverage(self, check_date: date = None) -> Dict:
        """
        Check roster coverage for all teams.

        Args:
            check_date: Date to check (defaults to today)

        Returns:
            Dict with coverage stats and any issues found
        """
        check_date = check_date or date.today()
        logger.info(f"Checking roster coverage for {check_date}")

        # Get roster freshness per team
        roster_freshness = self._get_roster_freshness(check_date)

        # Get teams playing today
        teams_playing_today = self._get_teams_playing_today(check_date)

        # Analyze issues
        issues = self._analyze_freshness(roster_freshness, teams_playing_today, check_date)

        # Build summary
        teams_with_data = len(roster_freshness)
        teams_current = sum(1 for t in roster_freshness.values() if t['age_days'] <= self.MAX_ROSTER_AGE_DAYS_WARNING)
        teams_stale = sum(1 for t in roster_freshness.values() if t['age_days'] > self.MAX_ROSTER_AGE_DAYS_WARNING)
        teams_critical = sum(1 for t in roster_freshness.values() if t['age_days'] > self.MAX_ROSTER_AGE_DAYS_CRITICAL)

        result = {
            'check_date': check_date.isoformat(),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'summary': {
                'expected_teams': self.EXPECTED_TEAMS,
                'teams_with_data': teams_with_data,
                'teams_current': teams_current,
                'teams_stale': teams_stale,
                'teams_critical': teams_critical,
                'teams_playing_today': len(teams_playing_today),
                'coverage_pct': round(teams_with_data / self.EXPECTED_TEAMS * 100, 1)
            },
            'thresholds': {
                'warning_days': self.MAX_ROSTER_AGE_DAYS_WARNING,
                'critical_days': self.MAX_ROSTER_AGE_DAYS_CRITICAL,
                'game_day_days': self.MAX_ROSTER_AGE_DAYS_GAME_DAY
            },
            'roster_freshness': roster_freshness,
            'issues': [i.to_dict() for i in issues],
            'has_critical_issues': any(i.severity == AlertSeverity.CRITICAL for i in issues),
            'has_warning_issues': any(i.severity == AlertSeverity.WARNING for i in issues)
        }

        # Log summary
        if result['has_critical_issues']:
            logger.error(f"CRITICAL roster issues found: {len([i for i in issues if i.severity == AlertSeverity.CRITICAL])} teams")
        elif result['has_warning_issues']:
            logger.warning(f"Roster warnings found: {len([i for i in issues if i.severity == AlertSeverity.WARNING])} teams")
        else:
            logger.info(f"Roster coverage OK: {teams_current}/{self.EXPECTED_TEAMS} teams current")

        return result

    def _get_roster_freshness(self, check_date: date) -> Dict[str, Dict]:
        """Get roster freshness per team from BigQuery."""
        query = """
        SELECT
            team_abbr,
            MAX(roster_date) as latest_roster,
            DATE_DIFF(@check_date, MAX(roster_date), DAY) as age_days,
            COUNT(DISTINCT player_lookup) as player_count
        FROM `nba_raw.espn_team_rosters`
        WHERE roster_date >= DATE_SUB(@check_date, INTERVAL 90 DAY)
        GROUP BY team_abbr
        ORDER BY team_abbr
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        results = {}
        for row in self.bq_client.query(query, job_config=job_config):
            results[row['team_abbr']] = {
                'latest_roster': row['latest_roster'],
                'age_days': row['age_days'],
                'player_count': row['player_count']
            }

        return results

    def _get_teams_playing_today(self, check_date: date) -> set:
        """Get set of teams playing on the given date."""
        query = """
        SELECT DISTINCT team_abbr
        FROM (
            SELECT home_team_tricode as team_abbr FROM `nba_reference.nba_schedule` WHERE game_date = @check_date
            UNION ALL
            SELECT away_team_tricode as team_abbr FROM `nba_reference.nba_schedule` WHERE game_date = @check_date
        )
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        teams = set()
        for row in self.bq_client.query(query, job_config=job_config):
            teams.add(row['team_abbr'])

        return teams

    def _analyze_freshness(
        self,
        roster_freshness: Dict[str, Dict],
        teams_playing_today: set,
        check_date: date
    ) -> List[RosterIssue]:
        """Analyze roster freshness and generate issues."""
        issues = []

        # Check each team
        for team, data in roster_freshness.items():
            age_days = data['age_days']
            is_playing = team in teams_playing_today

            # Determine severity
            if is_playing and age_days > self.MAX_ROSTER_AGE_DAYS_GAME_DAY:
                # Team playing today with stale roster - CRITICAL
                issues.append(RosterIssue(
                    team=team,
                    latest_roster_date=data['latest_roster'],
                    age_days=age_days,
                    is_playing_today=True,
                    severity=AlertSeverity.CRITICAL,
                    message=f"Team {team} playing today has stale roster ({age_days} days old). "
                           f"Predictions may be incomplete!"
                ))
            elif age_days > self.MAX_ROSTER_AGE_DAYS_CRITICAL:
                # Very stale roster - CRITICAL
                issues.append(RosterIssue(
                    team=team,
                    latest_roster_date=data['latest_roster'],
                    age_days=age_days,
                    is_playing_today=is_playing,
                    severity=AlertSeverity.CRITICAL,
                    message=f"Team {team} roster is critically stale ({age_days} days old)"
                ))
            elif age_days > self.MAX_ROSTER_AGE_DAYS_WARNING:
                # Stale roster - WARNING
                issues.append(RosterIssue(
                    team=team,
                    latest_roster_date=data['latest_roster'],
                    age_days=age_days,
                    is_playing_today=is_playing,
                    severity=AlertSeverity.WARNING,
                    message=f"Team {team} roster is stale ({age_days} days old)"
                ))

        # Check for missing teams
        all_nba_teams = {
            'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
            'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
            'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
        }
        missing_teams = all_nba_teams - set(roster_freshness.keys())
        for team in missing_teams:
            is_playing = team in teams_playing_today
            issues.append(RosterIssue(
                team=team,
                latest_roster_date=None,
                age_days=999,
                is_playing_today=is_playing,
                severity=AlertSeverity.CRITICAL,
                message=f"Team {team} has NO roster data in past 90 days!"
            ))

        # Sort by severity (critical first) then by age
        issues.sort(key=lambda x: (0 if x.severity == AlertSeverity.CRITICAL else 1, -x.age_days))

        return issues

    def format_alert_message(self, result: Dict) -> str:
        """Format result as alert message."""
        lines = []
        lines.append(f"Roster Coverage Check - {result['check_date']}")
        lines.append("=" * 50)

        summary = result['summary']
        lines.append(f"Coverage: {summary['teams_with_data']}/{summary['expected_teams']} teams ({summary['coverage_pct']}%)")
        lines.append(f"Current (<={self.MAX_ROSTER_AGE_DAYS_WARNING}d): {summary['teams_current']}")
        lines.append(f"Stale (>{self.MAX_ROSTER_AGE_DAYS_WARNING}d): {summary['teams_stale']}")
        lines.append(f"Critical (>{self.MAX_ROSTER_AGE_DAYS_CRITICAL}d): {summary['teams_critical']}")
        lines.append(f"Teams playing today: {summary['teams_playing_today']}")

        if result['issues']:
            lines.append("")
            lines.append("ISSUES FOUND:")
            lines.append("-" * 50)
            for issue in result['issues']:
                severity_emoji = "!!!" if issue['severity'] == 'critical' else "!"
                lines.append(f"{severity_emoji} [{issue['severity'].upper()}] {issue['message']}")

        return "\n".join(lines)


def main():
    """Run roster coverage check as standalone script."""
    import argparse
    import json

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='Check ESPN roster coverage')
    parser.add_argument('--date', type=str, help='Date to check (YYYY-MM-DD)', default=None)
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    check_date = date.fromisoformat(args.date) if args.date else None

    monitor = RosterCoverageMonitor()
    result = monitor.check_roster_coverage(check_date)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(monitor.format_alert_message(result))

        # Exit with error code if critical issues
        if result['has_critical_issues']:
            exit(1)


if __name__ == '__main__':
    main()
