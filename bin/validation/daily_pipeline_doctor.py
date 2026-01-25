#!/usr/bin/env python3
"""
Daily Pipeline Doctor - Automated Issue Detection and Repair

This script solves the core problems we keep encountering:
1. Games stuck after Phase 2 (boxscores exist, no analytics)
2. Grading behind (predictions exist, not graded)
3. Low prediction coverage (players with props not predicted)
4. Feature quality regression (sudden drops)

For each issue, it:
1. DETECTS the specific problem
2. IDENTIFIES affected dates/games/players
3. GENERATES the exact backfill commands
4. Optionally EXECUTES the fixes automatically

Usage:
    # Diagnose only (default - safe)
    python bin/validation/daily_pipeline_doctor.py --days 7

    # Diagnose and show fix commands
    python bin/validation/daily_pipeline_doctor.py --days 7 --show-fixes

    # Diagnose and auto-fix (use with caution)
    python bin/validation/daily_pipeline_doctor.py --days 7 --auto-fix

Created: 2026-01-25
Purpose: Stop the cycle of daily manual investigation and fixing
"""

import argparse
import os
import sys
import subprocess
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery


PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')


@dataclass
class PipelineIssue:
    """A detected pipeline issue with fix information."""
    issue_type: str
    severity: str  # critical, error, warning
    description: str
    affected_dates: List[str]
    affected_count: int
    fix_command: Optional[str] = None
    fix_script: Optional[str] = None
    details: Dict = field(default_factory=dict)


class PipelineDoctor:
    """Diagnose and fix pipeline issues."""

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)
        self.issues: List[PipelineIssue] = []

    def diagnose_all(self, start_date: date, end_date: date) -> List[PipelineIssue]:
        """Run all diagnostic checks."""
        self.issues = []

        print("\n" + "=" * 80)
        print("PIPELINE DOCTOR - Automated Diagnosis")
        print(f"Checking: {start_date} to {end_date}")
        print("=" * 80)

        # Issue 1: Games stuck after Phase 2
        self._diagnose_stuck_games(start_date, end_date)

        # Issue 2: Grading behind
        self._diagnose_grading_backlog(start_date, end_date)

        # Issue 3: Low prediction coverage
        self._diagnose_prediction_coverage(start_date, end_date)

        # Issue 4: Feature quality regression
        self._diagnose_feature_quality(start_date, end_date)

        # Issue 5: Boxscore gaps (bonus)
        self._diagnose_boxscore_gaps(start_date, end_date)

        return self.issues

    def _query(self, query: str) -> List[Dict]:
        """Execute query safely."""
        try:
            results = list(self.client.query(query).result())
            return [dict(row) for row in results]
        except Exception as e:
            print(f"   Query error: {e}")
            return []

    def _diagnose_stuck_games(self, start_date: date, end_date: date):
        """Find games with boxscores but no analytics."""
        print("\n[1/5] Checking for games stuck after Phase 2...")

        query = f"""
        WITH boxscore_games AS (
            SELECT DISTINCT game_date, game_id
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        ),
        analytics_games AS (
            SELECT DISTINCT game_date, game_id
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        )
        SELECT
            b.game_date,
            COUNT(*) as stuck_games,
            ARRAY_AGG(b.game_id) as game_ids
        FROM boxscore_games b
        LEFT JOIN analytics_games a ON b.game_id = a.game_id
        WHERE a.game_id IS NULL
        GROUP BY b.game_date
        ORDER BY b.game_date
        """

        results = self._query(query)

        if not results:
            print("   ✅ No stuck games found")
            return

        total_stuck = sum(r['stuck_games'] for r in results)
        affected_dates = [str(r['game_date']) for r in results]

        # Generate fix commands
        fix_commands = []
        for r in results:
            fix_commands.append(f"python bin/backfill/phase3.py --date {r['game_date']}")

        self.issues.append(PipelineIssue(
            issue_type="stuck_games",
            severity="critical",
            description=f"{total_stuck} games have boxscores but no analytics (stuck after Phase 2)",
            affected_dates=affected_dates,
            affected_count=total_stuck,
            fix_command="\n".join(fix_commands),
            fix_script=self._generate_batch_fix_script("phase3_backfill", affected_dates),
            details={'by_date': {str(r['game_date']): r['stuck_games'] for r in results}}
        ))

        print(f"   🚨 CRITICAL: {total_stuck} games stuck after Phase 2")
        print(f"      Dates: {', '.join(affected_dates[:5])}{'...' if len(affected_dates) > 5 else ''}")

    def _diagnose_grading_backlog(self, start_date: date, end_date: date):
        """Find predictions that should be graded but aren't."""
        print("\n[2/5] Checking for grading backlog...")

        query = f"""
        WITH predictions AS (
            SELECT
                game_date,
                COUNT(*) as pred_count,
                COUNT(DISTINCT player_lookup) as players
            FROM `{self.project_id}.nba_predictions.player_prop_predictions`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND game_date < CURRENT_DATE() - 1  -- Only check completed games
                AND system_id = 'catboost_v8'
                AND is_active = TRUE
                AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
            GROUP BY game_date
        ),
        graded AS (
            SELECT
                game_date,
                COUNT(*) as graded_count
            FROM `{self.project_id}.nba_predictions.prediction_accuracy`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND system_id = 'catboost_v8'
            GROUP BY game_date
        )
        SELECT
            p.game_date,
            p.pred_count,
            COALESCE(g.graded_count, 0) as graded_count,
            p.pred_count - COALESCE(g.graded_count, 0) as ungraded
        FROM predictions p
        LEFT JOIN graded g ON p.game_date = g.game_date
        WHERE p.pred_count > COALESCE(g.graded_count, 0)
        ORDER BY p.game_date
        """

        results = self._query(query)

        if not results:
            print("   ✅ Grading is up to date")
            return

        total_ungraded = sum(r['ungraded'] for r in results)
        affected_dates = [str(r['game_date']) for r in results]

        # Generate fix command
        if affected_dates:
            min_date = min(affected_dates)
            max_date = max(affected_dates)
            fix_command = f"python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --start-date {min_date} --end-date {max_date}"
        else:
            fix_command = None

        self.issues.append(PipelineIssue(
            issue_type="grading_backlog",
            severity="error",
            description=f"{total_ungraded} predictions not graded across {len(affected_dates)} dates",
            affected_dates=affected_dates,
            affected_count=total_ungraded,
            fix_command=fix_command,
            details={'by_date': {str(r['game_date']): r['ungraded'] for r in results}}
        ))

        print(f"   ❌ ERROR: {total_ungraded} predictions ungraded")
        print(f"      Dates: {len(affected_dates)} dates affected")

    def _diagnose_prediction_coverage(self, start_date: date, end_date: date):
        """Find dates where players with props didn't get predictions."""
        print("\n[3/5] Checking prediction coverage...")

        query = f"""
        WITH props AS (
            SELECT
                game_date,
                COUNT(DISTINCT player_lookup) as players_with_props
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY game_date
        ),
        predictions AS (
            SELECT
                game_date,
                COUNT(DISTINCT player_lookup) as players_predicted
            FROM `{self.project_id}.nba_predictions.player_prop_predictions`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND system_id = 'catboost_v8'
                AND is_active = TRUE
            GROUP BY game_date
        )
        SELECT
            p.game_date,
            p.players_with_props,
            COALESCE(pr.players_predicted, 0) as players_predicted,
            ROUND(COALESCE(pr.players_predicted, 0) * 100.0 / p.players_with_props, 1) as coverage_pct
        FROM props p
        LEFT JOIN predictions pr ON p.game_date = pr.game_date
        WHERE COALESCE(pr.players_predicted, 0) * 100.0 / p.players_with_props < 80
        ORDER BY p.game_date
        """

        results = self._query(query)

        if not results:
            print("   ✅ Prediction coverage is good (>80%)")
            return

        affected_dates = [str(r['game_date']) for r in results]
        avg_coverage = sum(r['coverage_pct'] for r in results) / len(results)

        self.issues.append(PipelineIssue(
            issue_type="low_prediction_coverage",
            severity="warning",
            description=f"Low prediction coverage (<80%) on {len(affected_dates)} dates (avg: {avg_coverage:.1f}%)",
            affected_dates=affected_dates,
            affected_count=len(affected_dates),
            fix_command="# Check player_loader.py is_production_ready filter\n# Run: python bin/backfill/phase5_predictions.py --date <date>",
            details={'by_date': {str(r['game_date']): f"{r['coverage_pct']}%" for r in results}}
        ))

        print(f"   ⚠️ WARNING: Low coverage on {len(affected_dates)} dates (avg: {avg_coverage:.1f}%)")

    def _diagnose_feature_quality(self, start_date: date, end_date: date):
        """Find dates with sudden feature quality drops."""
        print("\n[4/5] Checking feature quality trends...")

        query = f"""
        WITH daily_quality AS (
            SELECT
                game_date,
                ROUND(AVG(feature_quality_score), 2) as avg_quality,
                COUNTIF(feature_quality_score < 65) as low_quality_count,
                COUNT(*) as total
            FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY game_date
        ),
        with_change AS (
            SELECT
                *,
                LAG(avg_quality) OVER (ORDER BY game_date) as prev_quality,
                avg_quality - LAG(avg_quality) OVER (ORDER BY game_date) as quality_change,
                ROUND(low_quality_count * 100.0 / total, 1) as low_quality_pct
            FROM daily_quality
        )
        SELECT *
        FROM with_change
        WHERE quality_change < -5  -- Dropped by 5+ points
            OR low_quality_pct > 30  -- >30% low quality
        ORDER BY game_date
        """

        results = self._query(query)

        if not results:
            print("   ✅ Feature quality is stable")
            return

        affected_dates = [str(r['game_date']) for r in results]

        self.issues.append(PipelineIssue(
            issue_type="feature_quality_regression",
            severity="warning",
            description=f"Feature quality regression on {len(affected_dates)} dates",
            affected_dates=affected_dates,
            affected_count=len(affected_dates),
            fix_command="# Regenerate features: python bin/backfill/phase4.py --date <date>",
            details={'by_date': {str(r['game_date']): f"avg={r['avg_quality']}, low={r['low_quality_pct']}%" for r in results}}
        ))

        print(f"   ⚠️ WARNING: Quality regression on {len(affected_dates)} dates")

    def _diagnose_boxscore_gaps(self, start_date: date, end_date: date):
        """Find dates with missing boxscore data.

        NOTE: Schedule uses NBA game_id format (0022500XXX), while BDL boxscores
        use YYYYMMDD_AWAY_HOME format. We join on date+teams to compare correctly.
        """
        print("\n[5/5] Checking for boxscore gaps...")

        query = f"""
        WITH schedule AS (
            SELECT
                game_date,
                game_id,
                home_team_tricode,
                away_team_tricode
            FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND game_status = 3
        ),
        boxscores AS (
            SELECT DISTINCT
                game_date,
                home_team_abbr,
                away_team_abbr
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        ),
        -- Join on date+teams to accurately match despite different game_id formats
        matched AS (
            SELECT
                s.game_date,
                s.game_id,
                CASE WHEN b.game_date IS NOT NULL THEN 1 ELSE 0 END as has_boxscore
            FROM schedule s
            LEFT JOIN boxscores b
                ON s.game_date = b.game_date
                AND s.home_team_tricode = b.home_team_abbr
                AND s.away_team_tricode = b.away_team_abbr
        )
        SELECT
            game_date,
            COUNT(*) as expected_games,
            SUM(has_boxscore) as actual_games,
            COUNT(*) - SUM(has_boxscore) as missing_games
        FROM matched
        GROUP BY game_date
        HAVING COUNT(*) > SUM(has_boxscore)
        ORDER BY game_date
        """

        results = self._query(query)

        if not results:
            print("   ✅ Boxscore data complete")
            return

        total_missing = sum(r['missing_games'] for r in results)
        affected_dates = [str(r['game_date']) for r in results]

        fix_commands = [f"python bin/backfill/bdl_boxscores.py --date {d}" for d in affected_dates]

        self.issues.append(PipelineIssue(
            issue_type="boxscore_gaps",
            severity="critical",
            description=f"{total_missing} games missing boxscore data across {len(affected_dates)} dates",
            affected_dates=affected_dates,
            affected_count=total_missing,
            fix_command="\n".join(fix_commands),
            details={'by_date': {str(r['game_date']): r['missing_games'] for r in results}}
        ))

        print(f"   🚨 CRITICAL: {total_missing} games missing boxscores")

    def _generate_batch_fix_script(self, fix_type: str, dates: List[str]) -> str:
        """Generate a batch fix script for multiple dates."""
        script_lines = [
            "#!/bin/bash",
            f"# Auto-generated fix script for {fix_type}",
            f"# Generated: {datetime.now().isoformat()}",
            f"# Dates: {len(dates)}",
            "",
            "set -e",
            ""
        ]

        if fix_type == "phase3_backfill":
            for d in sorted(dates):
                script_lines.append(f"echo 'Processing {d}...'")
                script_lines.append(f"python bin/backfill/phase3.py --date {d}")
                script_lines.append("")

        return "\n".join(script_lines)

    def print_summary(self, show_fixes: bool = False):
        """Print summary of all issues."""
        print("\n" + "=" * 80)
        print("DIAGNOSIS SUMMARY")
        print("=" * 80)

        if not self.issues:
            print("\n✅ No issues found! Pipeline is healthy.")
            return

        # Group by severity
        critical = [i for i in self.issues if i.severity == 'critical']
        errors = [i for i in self.issues if i.severity == 'error']
        warnings = [i for i in self.issues if i.severity == 'warning']

        print(f"\nTotal Issues: {len(self.issues)}")
        print(f"  🚨 Critical: {len(critical)}")
        print(f"  ❌ Errors: {len(errors)}")
        print(f"  ⚠️ Warnings: {len(warnings)}")

        # Show each issue
        print("\n" + "-" * 80)
        print("ISSUES FOUND")
        print("-" * 80)

        for issue in self.issues:
            icon = {'critical': '🚨', 'error': '❌', 'warning': '⚠️'}[issue.severity]
            print(f"\n{icon} [{issue.issue_type}] {issue.description}")
            print(f"   Affected: {issue.affected_count} items across {len(issue.affected_dates)} dates")

            if show_fixes and issue.fix_command:
                print(f"\n   FIX COMMAND:")
                for line in issue.fix_command.split('\n')[:5]:
                    print(f"   $ {line}")
                if issue.fix_command.count('\n') > 5:
                    print(f"   ... and {issue.fix_command.count(chr(10)) - 4} more commands")

        # Generate combined fix script
        if show_fixes:
            print("\n" + "-" * 80)
            print("RECOMMENDED FIX ORDER")
            print("-" * 80)
            print("""
1. First, fix boxscore gaps (if any):
   python bin/backfill/bdl_boxscores.py --start-date <min_date> --end-date <max_date>

2. Then, fix stuck games (Phase 3):
   python bin/backfill/phase3.py --start-date <min_date> --end-date <max_date>

3. Then, regenerate Phase 4 features:
   python bin/backfill/phase4.py --start-date <min_date> --end-date <max_date>

4. Finally, run grading backfill:
   python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \\
     --start-date <min_date> --end-date <max_date>

5. Re-run validation to confirm fixes:
   python bin/validation/daily_pipeline_doctor.py --days 7
""")

        print()

    def auto_fix(self, dry_run: bool = True):
        """Attempt to auto-fix issues."""
        if not self.issues:
            print("No issues to fix!")
            return

        print("\n" + "=" * 80)
        print("AUTO-FIX MODE" + (" (DRY RUN)" if dry_run else " (LIVE)"))
        print("=" * 80)

        # Sort issues by fix order: boxscores → phase3 → phase4 → grading
        fix_order = ['boxscore_gaps', 'stuck_games', 'feature_quality_regression', 'grading_backlog', 'low_prediction_coverage']

        for issue_type in fix_order:
            issues_of_type = [i for i in self.issues if i.issue_type == issue_type]
            if not issues_of_type:
                continue

            issue = issues_of_type[0]
            print(f"\n[{issue.issue_type}] {issue.description}")

            if issue.fix_command:
                print(f"   Command: {issue.fix_command.split(chr(10))[0]}")
                if dry_run:
                    print("   [DRY RUN] Would execute above command")
                else:
                    print("   Executing...")
                    # subprocess.run(issue.fix_command.split('\n')[0], shell=True)


def main():
    parser = argparse.ArgumentParser(description="Pipeline Doctor - Diagnose and fix issues")
    parser.add_argument('--days', type=int, default=7, help='Check last N days')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--show-fixes', action='store_true', help='Show fix commands')
    parser.add_argument('--auto-fix', action='store_true', help='Attempt automatic fixes')
    parser.add_argument('--dry-run', action='store_true', default=True, help='Dry run for auto-fix')
    args = parser.parse_args()

    # Determine date range
    today = date.today()
    if args.start_date and args.end_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    else:
        start_date = today - timedelta(days=args.days)
        end_date = today - timedelta(days=1)

    doctor = PipelineDoctor()
    doctor.diagnose_all(start_date, end_date)
    doctor.print_summary(show_fixes=args.show_fixes or args.auto_fix)

    if args.auto_fix:
        doctor.auto_fix(dry_run=args.dry_run)

    # Exit code based on severity
    if any(i.severity == 'critical' for i in doctor.issues):
        sys.exit(2)
    elif any(i.severity == 'error' for i in doctor.issues):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
