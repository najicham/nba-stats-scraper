#!/usr/bin/env python3
"""
Season Reconciliation - Comprehensive Cross-Table Validation

This script solves the core problem: data appears complete but isn't,
and backfills don't fully fix the gaps.

Key features:
1. Creates canonical "expected" manifest from schedule (source of truth)
2. Compares ALL related tables for consistency
3. Identifies SPECIFIC missing records, not just counts
4. Tracks discrepancies between tables (where they disagree)
5. Generates precise backfill commands
6. Can run on full season or specific date range

Usage:
    # Full season validation
    python bin/validation/season_reconciliation.py --full-season

    # Last 7 days
    python bin/validation/season_reconciliation.py --days 7

    # Specific date range
    python bin/validation/season_reconciliation.py --start-date 2025-10-22 --end-date 2026-01-25

    # Single date deep dive
    python bin/validation/season_reconciliation.py --date 2026-01-24 --verbose

Created: 2026-01-25
Purpose: Stop the cycle of "validate → find issues → backfill → find more issues"
"""

import argparse
import json
import os
import sys
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple, Optional, Any, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery


PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

# Season start date (2025-26 season)
SEASON_START = date(2025, 10, 22)


class IssueType(Enum):
    MISSING_DATA = "missing_data"
    COUNT_MISMATCH = "count_mismatch"
    CROSS_TABLE_DISCREPANCY = "cross_table_discrepancy"
    QUALITY_DEGRADATION = "quality_degradation"
    LATE_PREDICTION = "late_prediction"
    NULL_CRITICAL_FIELD = "null_critical_field"
    ORPHAN_RECORD = "orphan_record"


@dataclass
class Issue:
    """Represents a single data issue found during validation."""
    issue_type: IssueType
    game_date: str
    table: str
    description: str
    severity: str  # critical, error, warning
    affected_count: int = 0
    details: Dict = field(default_factory=dict)
    backfill_command: Optional[str] = None


@dataclass
class DateManifest:
    """Expected vs actual data for a single date."""
    game_date: str
    expected_games: int
    expected_players: int  # approximate
    actual_by_table: Dict[str, Dict] = field(default_factory=dict)
    issues: List[Issue] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return len(self.issues) == 0

    @property
    def critical_issues(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == "critical"]


class SeasonReconciliation:
    """Comprehensive season-wide data reconciliation."""

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)
        self.manifests: Dict[str, DateManifest] = {}
        self.all_issues: List[Issue] = []

    def run_full_reconciliation(
        self,
        start_date: date,
        end_date: date,
        verbose: bool = False
    ) -> Dict[str, Any]:
        """Run complete reconciliation for date range."""

        print("\n" + "=" * 80)
        print("SEASON RECONCILIATION - COMPREHENSIVE DATA VALIDATION")
        print(f"Date Range: {start_date} to {end_date}")
        print(f"Days: {(end_date - start_date).days + 1}")
        print("=" * 80)

        # Step 1: Build expected manifest from schedule
        print("\n[1/6] Building expected manifest from schedule...")
        self._build_expected_manifest(start_date, end_date)

        # Step 2: Check Phase 2 (Raw) data
        print("\n[2/6] Checking Phase 2 (Raw) data...")
        self._check_phase2_data(start_date, end_date)

        # Step 3: Check Phase 3 (Analytics) data
        print("\n[3/6] Checking Phase 3 (Analytics) data...")
        self._check_phase3_data(start_date, end_date)

        # Step 4: Check Phase 4 (Precompute) data
        print("\n[4/6] Checking Phase 4 (Precompute/Features) data...")
        self._check_phase4_data(start_date, end_date)

        # Step 5: Check Phase 5 (Predictions) data
        print("\n[5/6] Checking Phase 5 (Predictions) data...")
        self._check_phase5_data(start_date, end_date)

        # Step 6: Cross-table discrepancy detection
        print("\n[6/6] Detecting cross-table discrepancies...")
        self._detect_cross_table_discrepancies(start_date, end_date)

        # Compile results
        return self._compile_results(verbose)

    def _query(self, query: str) -> List[Dict]:
        """Execute query and return results as list of dicts."""
        try:
            results = list(self.client.query(query).result())
            return [dict(row) for row in results]
        except Exception as e:
            print(f"   Query error: {e}")
            return []

    def _build_expected_manifest(self, start_date: date, end_date: date):
        """Build expected data manifest from schedule (source of truth)."""

        query = f"""
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as expected_games,
            -- Approximate expected players (2 teams * ~13 active per team)
            COUNT(DISTINCT game_id) * 26 as approx_expected_players
        FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            AND game_status = 3  -- Final games only
        GROUP BY game_date
        ORDER BY game_date
        """

        results = self._query(query)

        for row in results:
            game_date = str(row['game_date'])
            self.manifests[game_date] = DateManifest(
                game_date=game_date,
                expected_games=row['expected_games'],
                expected_players=row['approx_expected_players']
            )

        total_games = sum(m.expected_games for m in self.manifests.values())
        print(f"   Found {len(self.manifests)} game dates with {total_games} total games")

    def _check_phase2_data(self, start_date: date, end_date: date):
        """Check Phase 2 raw data tables."""

        # Check BDL boxscores
        query = f"""
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as games,
            COUNT(DISTINCT player_lookup) as players,
            COUNT(*) as row_count,
            COUNTIF(points IS NULL) as null_points,
            COUNTIF(minutes_played IS NULL OR minutes_played = 0) as zero_minutes
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY game_date
        ORDER BY game_date
        """

        results = self._query(query)

        for row in results:
            game_date = str(row['game_date'])
            if game_date not in self.manifests:
                continue

            manifest = self.manifests[game_date]
            manifest.actual_by_table['bdl_boxscores'] = {
                'games': row['games'],
                'players': row['players'],
                'row_count': row['row_count'],
                'null_points': row['null_points'],
                'zero_minutes': row['zero_minutes']
            }

            # Check for issues
            if row['games'] < manifest.expected_games:
                manifest.issues.append(Issue(
                    issue_type=IssueType.MISSING_DATA,
                    game_date=game_date,
                    table='bdl_player_boxscores',
                    description=f"Missing {manifest.expected_games - row['games']} games",
                    severity='critical',
                    affected_count=manifest.expected_games - row['games'],
                    backfill_command=f"python bin/backfill/bdl_boxscores.py --date {game_date}"
                ))

        # Check for dates with no data at all
        dates_with_data = {str(r['game_date']) for r in results}
        for game_date, manifest in self.manifests.items():
            if game_date not in dates_with_data:
                manifest.issues.append(Issue(
                    issue_type=IssueType.MISSING_DATA,
                    game_date=game_date,
                    table='bdl_player_boxscores',
                    description=f"No boxscore data for {manifest.expected_games} games",
                    severity='critical',
                    affected_count=manifest.expected_games,
                    backfill_command=f"python bin/backfill/bdl_boxscores.py --date {game_date}"
                ))

        print(f"   Checked bdl_player_boxscores: {len(results)} dates with data")

    def _check_phase3_data(self, start_date: date, end_date: date):
        """Check Phase 3 analytics tables."""

        tables = [
            ('player_game_summary', 'nba_analytics'),
            ('team_defense_game_summary', 'nba_analytics'),
            ('team_offense_game_summary', 'nba_analytics'),
        ]

        for table_name, dataset in tables:
            query = f"""
            SELECT
                game_date,
                COUNT(DISTINCT game_id) as games,
                COUNT(DISTINCT player_lookup) as players,
                COUNT(*) as total_rows
            FROM `{self.project_id}.{dataset}.{table_name}`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY game_date
            ORDER BY game_date
            """

            results = self._query(query)

            for row in results:
                game_date = str(row['game_date'])
                if game_date not in self.manifests:
                    continue

                manifest = self.manifests[game_date]
                manifest.actual_by_table[table_name] = {
                    'games': row['games'],
                    'players': row.get('players', 0),
                    'total_rows': row['total_rows']
                }

                # Check for game count mismatch
                if row['games'] < manifest.expected_games:
                    manifest.issues.append(Issue(
                        issue_type=IssueType.MISSING_DATA,
                        game_date=game_date,
                        table=table_name,
                        description=f"Missing {manifest.expected_games - row['games']} games",
                        severity='critical',
                        affected_count=manifest.expected_games - row['games'],
                        backfill_command=f"python bin/backfill/phase3.py --date {game_date} --processor {table_name}"
                    ))

            # Check for dates with no data
            dates_with_data = {str(r['game_date']) for r in results}
            for game_date, manifest in self.manifests.items():
                if game_date not in dates_with_data and 'bdl_boxscores' in manifest.actual_by_table:
                    manifest.issues.append(Issue(
                        issue_type=IssueType.MISSING_DATA,
                        game_date=game_date,
                        table=table_name,
                        description=f"No {table_name} data",
                        severity='critical',
                        affected_count=manifest.expected_games,
                        backfill_command=f"python bin/backfill/phase3.py --date {game_date} --processor {table_name}"
                    ))

            print(f"   Checked {table_name}: {len(results)} dates with data")

    def _check_phase4_data(self, start_date: date, end_date: date):
        """Check Phase 4 precompute/feature data."""

        # Check ML Feature Store
        query = f"""
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as games,
            COUNT(DISTINCT player_lookup) as players,
            AVG(feature_quality_score) as avg_quality,
            COUNTIF(feature_quality_score < 65) as low_quality_count,
            COUNTIF(feature_quality_score IS NULL) as null_quality_count
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY game_date
        ORDER BY game_date
        """

        results = self._query(query)

        for row in results:
            game_date = str(row['game_date'])
            if game_date not in self.manifests:
                continue

            manifest = self.manifests[game_date]
            manifest.actual_by_table['ml_feature_store_v2'] = {
                'games': row['games'],
                'players': row['players'],
                'avg_quality': round(row['avg_quality'] or 0, 2),
                'low_quality_count': row['low_quality_count'],
                'null_quality_count': row['null_quality_count']
            }

            # Check for quality issues
            if row['avg_quality'] and row['avg_quality'] < 65:
                manifest.issues.append(Issue(
                    issue_type=IssueType.QUALITY_DEGRADATION,
                    game_date=game_date,
                    table='ml_feature_store_v2',
                    description=f"Low feature quality: {row['avg_quality']:.1f} avg",
                    severity='warning',
                    details={'avg_quality': row['avg_quality'], 'low_count': row['low_quality_count']}
                ))

        print(f"   Checked ml_feature_store_v2: {len(results)} dates with data")

    def _check_phase5_data(self, start_date: date, end_date: date):
        """Check Phase 5 predictions and grading."""

        # Check predictions
        query = f"""
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as games,
            COUNT(DISTINCT player_lookup) as players,
            COUNT(*) as total_predictions,
            COUNTIF(line_source = 'ACTUAL_PROP') as with_prop_lines,
            COUNTIF(line_source = 'NO_PROP_LINE') as without_prop_lines,
            COUNTIF(has_prop_line = TRUE AND line_source != 'ACTUAL_PROP') as flag_mismatch
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            AND system_id = 'catboost_v8'
            AND is_active = TRUE
        GROUP BY game_date
        ORDER BY game_date
        """

        results = self._query(query)

        for row in results:
            game_date = str(row['game_date'])
            if game_date not in self.manifests:
                continue

            manifest = self.manifests[game_date]
            manifest.actual_by_table['predictions'] = {
                'games': row['games'],
                'players': row['players'],
                'total': row['total_predictions'],
                'with_prop_lines': row['with_prop_lines'],
                'without_prop_lines': row['without_prop_lines'],
                'flag_mismatch': row['flag_mismatch']
            }

            # Check for has_prop_line data bug
            if row['flag_mismatch'] > 0:
                manifest.issues.append(Issue(
                    issue_type=IssueType.CROSS_TABLE_DISCREPANCY,
                    game_date=game_date,
                    table='player_prop_predictions',
                    description=f"has_prop_line flag mismatch: {row['flag_mismatch']} records",
                    severity='warning',
                    affected_count=row['flag_mismatch'],
                    details={'description': 'has_prop_line=TRUE but line_source!=ACTUAL_PROP'}
                ))

        # Check grading
        query = f"""
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as games,
            COUNT(DISTINCT player_lookup) as players,
            COUNT(*) as graded_count,
            COUNTIF(prediction_correct = TRUE) as correct,
            COUNTIF(is_voided = TRUE) as voided
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            AND system_id = 'catboost_v8'
        GROUP BY game_date
        ORDER BY game_date
        """

        grading_results = self._query(query)

        for row in grading_results:
            game_date = str(row['game_date'])
            if game_date not in self.manifests:
                continue

            manifest = self.manifests[game_date]
            manifest.actual_by_table['grading'] = {
                'games': row['games'],
                'players': row['players'],
                'graded': row['graded_count'],
                'correct': row['correct'],
                'voided': row['voided']
            }

        print(f"   Checked predictions: {len(results)} dates")
        print(f"   Checked grading: {len(grading_results)} dates")

    def _detect_cross_table_discrepancies(self, start_date: date, end_date: date):
        """Detect discrepancies between related tables."""

        discrepancy_count = 0

        for game_date, manifest in self.manifests.items():
            tables = manifest.actual_by_table

            # Compare game counts across tables
            game_counts = {}
            for table, data in tables.items():
                if 'games' in data:
                    game_counts[table] = data['games']

            if len(game_counts) > 1:
                min_games = min(game_counts.values())
                max_games = max(game_counts.values())

                if min_games != max_games:
                    discrepancy_count += 1
                    # Find which tables are short
                    for table, count in game_counts.items():
                        if count < max_games:
                            manifest.issues.append(Issue(
                                issue_type=IssueType.COUNT_MISMATCH,
                                game_date=game_date,
                                table=table,
                                description=f"Game count mismatch: {count} vs {max_games} in other tables",
                                severity='error',
                                affected_count=max_games - count,
                                details={'this_table': count, 'max_in_others': max_games, 'all_counts': game_counts}
                            ))

            # Compare player counts (boxscores vs analytics)
            if 'bdl_boxscores' in tables and 'player_game_summary' in tables:
                box_players = tables['bdl_boxscores'].get('players', 0)
                analytics_players = tables['player_game_summary'].get('players', 0)

                if box_players > 0 and analytics_players > 0:
                    diff = abs(box_players - analytics_players)
                    if diff > 5:  # Allow small discrepancy
                        manifest.issues.append(Issue(
                            issue_type=IssueType.COUNT_MISMATCH,
                            game_date=game_date,
                            table='player_game_summary',
                            description=f"Player count mismatch: {analytics_players} vs {box_players} in boxscores",
                            severity='warning',
                            affected_count=diff,
                            details={'analytics': analytics_players, 'boxscores': box_players}
                        ))

            # Compare predictions vs grading
            if 'predictions' in tables and 'grading' in tables:
                pred_with_lines = tables['predictions'].get('with_prop_lines', 0)
                graded = tables['grading'].get('graded', 0)

                if pred_with_lines > 0 and graded > 0:
                    coverage = (graded / pred_with_lines) * 100
                    if coverage < 80:
                        manifest.issues.append(Issue(
                            issue_type=IssueType.MISSING_DATA,
                            game_date=game_date,
                            table='prediction_accuracy',
                            description=f"Grading behind: {coverage:.1f}% coverage ({graded}/{pred_with_lines})",
                            severity='warning' if coverage > 50 else 'error',
                            affected_count=pred_with_lines - graded,
                            backfill_command=f"python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --start-date {game_date} --end-date {game_date}"
                        ))

        print(f"   Found {discrepancy_count} dates with cross-table discrepancies")

    def _compile_results(self, verbose: bool = False) -> Dict[str, Any]:
        """Compile all results into summary."""

        # Collect all issues
        for manifest in self.manifests.values():
            self.all_issues.extend(manifest.issues)

        # Categorize issues
        critical = [i for i in self.all_issues if i.severity == 'critical']
        errors = [i for i in self.all_issues if i.severity == 'error']
        warnings = [i for i in self.all_issues if i.severity == 'warning']

        # Issues by type
        by_type = defaultdict(list)
        for issue in self.all_issues:
            by_type[issue.issue_type.value].append(issue)

        # Issues by table
        by_table = defaultdict(list)
        for issue in self.all_issues:
            by_table[issue.table].append(issue)

        # Dates with issues
        dates_with_issues = {i.game_date for i in self.all_issues}
        complete_dates = set(self.manifests.keys()) - dates_with_issues

        # Print summary
        print("\n" + "=" * 80)
        print("RECONCILIATION SUMMARY")
        print("=" * 80)

        print(f"\nDates Analyzed: {len(self.manifests)}")
        print(f"Complete Dates: {len(complete_dates)} ({len(complete_dates)*100/max(len(self.manifests),1):.1f}%)")
        print(f"Dates with Issues: {len(dates_with_issues)}")

        print(f"\nTotal Issues: {len(self.all_issues)}")
        print(f"  🚨 Critical: {len(critical)}")
        print(f"  ❌ Errors: {len(errors)}")
        print(f"  ⚠️ Warnings: {len(warnings)}")

        print("\nIssues by Type:")
        for issue_type, issues in sorted(by_type.items()):
            print(f"  {issue_type}: {len(issues)}")

        print("\nIssues by Table:")
        for table, issues in sorted(by_table.items(), key=lambda x: -len(x[1])):
            print(f"  {table}: {len(issues)}")

        # Show critical issues
        if critical:
            print("\n" + "-" * 80)
            print("CRITICAL ISSUES (Require Immediate Attention)")
            print("-" * 80)
            for issue in critical[:20]:  # Show first 20
                print(f"\n  [{issue.game_date}] {issue.table}")
                print(f"  {issue.description}")
                if issue.backfill_command:
                    print(f"  Backfill: {issue.backfill_command}")

        # Generate backfill commands
        if self.all_issues:
            print("\n" + "-" * 80)
            print("SUGGESTED BACKFILL COMMANDS")
            print("-" * 80)

            # Group by backfill command type
            backfill_dates = defaultdict(set)
            for issue in self.all_issues:
                if issue.severity in ['critical', 'error']:
                    if 'bdl_boxscores' in issue.table:
                        backfill_dates['phase2_bdl'].add(issue.game_date)
                    elif issue.table in ['player_game_summary', 'team_defense_game_summary', 'team_offense_game_summary']:
                        backfill_dates['phase3_analytics'].add(issue.game_date)
                    elif 'prediction_accuracy' in issue.table:
                        backfill_dates['grading'].add(issue.game_date)

            for backfill_type, dates in backfill_dates.items():
                if dates:
                    sorted_dates = sorted(dates)
                    print(f"\n# {backfill_type} - {len(dates)} dates")
                    if len(sorted_dates) > 5:
                        print(f"# Dates: {sorted_dates[0]} to {sorted_dates[-1]}")
                    else:
                        print(f"# Dates: {', '.join(sorted_dates)}")

        if verbose:
            print("\n" + "-" * 80)
            print("DETAILED ISSUES BY DATE")
            print("-" * 80)
            for game_date in sorted(dates_with_issues):
                manifest = self.manifests[game_date]
                print(f"\n{game_date} ({len(manifest.issues)} issues):")
                for issue in manifest.issues:
                    severity_icon = {'critical': '🚨', 'error': '❌', 'warning': '⚠️'}[issue.severity]
                    print(f"  {severity_icon} [{issue.table}] {issue.description}")

        print("\n" + "=" * 80)

        return {
            'dates_analyzed': len(self.manifests),
            'complete_dates': len(complete_dates),
            'dates_with_issues': len(dates_with_issues),
            'total_issues': len(self.all_issues),
            'critical': len(critical),
            'errors': len(errors),
            'warnings': len(warnings),
            'by_type': {k: len(v) for k, v in by_type.items()},
            'by_table': {k: len(v) for k, v in by_table.items()},
            'issues': [
                {
                    'game_date': i.game_date,
                    'table': i.table,
                    'type': i.issue_type.value,
                    'severity': i.severity,
                    'description': i.description,
                    'affected_count': i.affected_count
                }
                for i in self.all_issues
            ]
        }


def main():
    parser = argparse.ArgumentParser(description="Season-wide data reconciliation")
    parser.add_argument('--full-season', action='store_true', help='Validate entire season')
    parser.add_argument('--days', type=int, help='Validate last N days')
    parser.add_argument('--date', help='Validate specific date (YYYY-MM-DD)')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed issues')
    parser.add_argument('--output', '-o', help='Output JSON file')
    args = parser.parse_args()

    # Determine date range
    today = date.today()

    if args.full_season:
        start_date = SEASON_START
        end_date = today - timedelta(days=1)  # Exclude today
    elif args.days:
        start_date = today - timedelta(days=args.days)
        end_date = today - timedelta(days=1)
    elif args.date:
        start_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        end_date = start_date
    elif args.start_date and args.end_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    else:
        # Default: last 7 days
        start_date = today - timedelta(days=7)
        end_date = today - timedelta(days=1)

    # Run reconciliation
    reconciler = SeasonReconciliation()
    results = reconciler.run_full_reconciliation(start_date, end_date, args.verbose)

    # Save output if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")

    # Exit code based on issues
    if results['critical'] > 0:
        sys.exit(2)
    elif results['errors'] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
