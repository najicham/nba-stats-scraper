#!/usr/bin/env python3
"""
Root Cause Analyzer - Automated Pipeline Issue Diagnosis

When validation finds an issue, this script automatically diagnoses WHY.

Instead of just saying "low prediction coverage", it breaks down:
- How many players filtered by feature quality?
- How many filtered by missing props?
- How many filtered by registry issues?
- How many filtered by is_production_ready flag?

This dramatically reduces time to resolution by providing actionable insights.

Usage:
    python bin/validation/root_cause_analyzer.py --date 2026-01-24
    python bin/validation/root_cause_analyzer.py --issue low_coverage --date 2026-01-24
    python bin/validation/root_cause_analyzer.py --issue grading_lag --date 2026-01-24
    python bin/validation/root_cause_analyzer.py --issue missing_boxscores --date 2026-01-24

Created: 2026-01-25
Part of: Pipeline Resilience Improvements
"""

import argparse
import os
import sys
from datetime import date, timedelta, datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery

PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')


@dataclass
class RootCause:
    """A root cause finding."""
    category: str
    description: str
    impact_count: int
    impact_pct: float
    fix_suggestion: str
    details: Dict[str, Any]


@dataclass
class DiagnosisReport:
    """Full diagnosis report for an issue."""
    issue_type: str
    game_date: date
    summary: str
    root_causes: List[RootCause]
    recommended_actions: List[str]


class RootCauseAnalyzer:
    """
    Analyzes pipeline issues to find root causes.

    Key insight: When validation fails, knowing WHERE it failed is not enough.
    We need to know WHY it failed to fix it efficiently.
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)

    def analyze(self, issue_type: str, game_date: date) -> DiagnosisReport:
        """Analyze a specific issue type for a date."""
        if issue_type == "low_coverage":
            return self._analyze_low_coverage(game_date)
        elif issue_type == "grading_lag":
            return self._analyze_grading_lag(game_date)
        elif issue_type == "missing_boxscores":
            return self._analyze_missing_boxscores(game_date)
        elif issue_type == "missing_analytics":
            return self._analyze_missing_analytics(game_date)
        elif issue_type == "low_feature_quality":
            return self._analyze_low_feature_quality(game_date)
        else:
            return self._analyze_all(game_date)

    def _query(self, sql: str) -> List[Dict]:
        """Execute query and return results."""
        try:
            results = list(self.client.query(sql).result())
            return [dict(row) for row in results]
        except Exception as e:
            print(f"Query error: {e}")
            return []

    def _analyze_low_coverage(self, game_date: date) -> DiagnosisReport:
        """Analyze why prediction coverage is low."""
        query = f"""
        WITH
        -- All players with props (should get predictions)
        props_players AS (
          SELECT DISTINCT player_lookup
          FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
          WHERE game_date = '{game_date}'
        ),

        -- Players with features
        feature_players AS (
          SELECT
            player_lookup,
            feature_quality_score,
            CASE WHEN feature_quality_score >= 65 THEN TRUE ELSE FALSE END as high_quality
          FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
          WHERE game_date = '{game_date}'
        ),

        -- Players with predictions
        predicted_players AS (
          SELECT DISTINCT player_lookup
          FROM `{self.project_id}.nba_predictions.player_prop_predictions`
          WHERE game_date = '{game_date}'
            AND system_id = 'catboost_v8' AND is_active = TRUE
        ),

        -- Player registry
        registry_players AS (
          SELECT DISTINCT player_lookup
          FROM `{self.project_id}.nba_predictions.player_registry`
          WHERE is_active = TRUE
        ),

        -- Join analysis
        analysis AS (
          SELECT
            p.player_lookup,
            CASE WHEN f.player_lookup IS NOT NULL THEN TRUE ELSE FALSE END as has_features,
            COALESCE(f.high_quality, FALSE) as has_high_quality_features,
            CASE WHEN pred.player_lookup IS NOT NULL THEN TRUE ELSE FALSE END as has_prediction,
            CASE WHEN r.player_lookup IS NOT NULL THEN TRUE ELSE FALSE END as in_registry
          FROM props_players p
          LEFT JOIN feature_players f ON p.player_lookup = f.player_lookup
          LEFT JOIN predicted_players pred ON p.player_lookup = pred.player_lookup
          LEFT JOIN registry_players r ON p.player_lookup = r.player_lookup
        )

        SELECT
          COUNT(*) as total_props_players,
          COUNTIF(has_prediction) as predicted,
          COUNTIF(NOT has_features) as missing_features,
          COUNTIF(has_features AND NOT has_high_quality_features) as low_quality_features,
          COUNTIF(has_high_quality_features AND NOT has_prediction) as filtered_other,
          COUNTIF(NOT in_registry) as not_in_registry
        FROM analysis
        """

        results = self._query(query)
        if not results:
            return DiagnosisReport(
                issue_type="low_coverage",
                game_date=game_date,
                summary="Could not analyze coverage",
                root_causes=[],
                recommended_actions=[]
            )

        data = results[0]
        total = data.get('total_props_players') or 0
        predicted = data.get('predicted') or 0
        missing_features = data.get('missing_features') or 0
        low_quality = data.get('low_quality_features') or 0
        filtered_other = data.get('filtered_other') or 0
        not_in_registry = data.get('not_in_registry') or 0

        gap = total - predicted
        root_causes = []

        if missing_features > 0:
            root_causes.append(RootCause(
                category="missing_features",
                description=f"{missing_features} players have props but no features",
                impact_count=missing_features,
                impact_pct=(missing_features / gap * 100) if gap > 0 else 0,
                fix_suggestion="Run Phase 4 backfill to generate missing features",
                details={"command": f"python bin/backfill/phase4.py --date {game_date}"}
            ))

        if low_quality > 0:
            root_causes.append(RootCause(
                category="low_quality_features",
                description=f"{low_quality} players have features but quality < 65",
                impact_count=low_quality,
                impact_pct=(low_quality / gap * 100) if gap > 0 else 0,
                fix_suggestion="Low quality features due to incomplete rolling windows. Check Phase 3 analytics.",
                details={"threshold": 65}
            ))

        if not_in_registry > 0:
            root_causes.append(RootCause(
                category="registry_gaps",
                description=f"{not_in_registry} players not in active registry",
                impact_count=not_in_registry,
                impact_pct=(not_in_registry / gap * 100) if gap > 0 else 0,
                fix_suggestion="Update player registry with new players",
                details={}
            ))

        if filtered_other > 0:
            root_causes.append(RootCause(
                category="other_filters",
                description=f"{filtered_other} players have high quality features but no prediction",
                impact_count=filtered_other,
                impact_pct=(filtered_other / gap * 100) if gap > 0 else 0,
                fix_suggestion="Check player_loader.py filters (is_production_ready, etc.)",
                details={}
            ))

        # Sort by impact
        root_causes.sort(key=lambda x: x.impact_count, reverse=True)

        # Generate actions
        actions = []
        if missing_features > 0:
            actions.append(f"1. Run Phase 4 backfill: python bin/backfill/phase4.py --date {game_date}")
        if low_quality > 0:
            actions.append("2. Check Phase 3 analytics completeness")
        if filtered_other > 0:
            actions.append("3. Review player_loader.py filters in predictions/coordinator/")
        actions.append(f"4. Re-run Phase 5: python bin/backfill/phase5_predictions.py --date {game_date}")

        coverage_pct = (predicted / total * 100) if total > 0 else 0
        return DiagnosisReport(
            issue_type="low_coverage",
            game_date=game_date,
            summary=f"Coverage: {coverage_pct:.1f}% ({predicted}/{total} players). Gap: {gap} players.",
            root_causes=root_causes,
            recommended_actions=actions
        )

    def _analyze_grading_lag(self, game_date: date) -> DiagnosisReport:
        """Analyze why grading is behind."""
        query = f"""
        WITH
        predictions AS (
          SELECT
            player_lookup,
            game_id,
            line_source,
            CASE WHEN line_source = 'ACTUAL_PROP' THEN TRUE ELSE FALSE END as has_prop
          FROM `{self.project_id}.nba_predictions.player_prop_predictions`
          WHERE game_date = '{game_date}'
            AND system_id = 'catboost_v8' AND is_active = TRUE
        ),
        graded AS (
          SELECT DISTINCT player_lookup, game_id
          FROM `{self.project_id}.nba_predictions.prediction_accuracy`
          WHERE game_date = '{game_date}'
            AND system_id = 'catboost_v8'
        ),
        boxscores AS (
          SELECT DISTINCT player_lookup, game_id
          FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
          WHERE game_date = '{game_date}'
        ),
        analysis AS (
          SELECT
            p.player_lookup,
            p.game_id,
            p.has_prop,
            CASE WHEN g.player_lookup IS NOT NULL THEN TRUE ELSE FALSE END as is_graded,
            CASE WHEN b.player_lookup IS NOT NULL THEN TRUE ELSE FALSE END as has_boxscore
          FROM predictions p
          LEFT JOIN graded g ON p.player_lookup = g.player_lookup AND p.game_id = g.game_id
          LEFT JOIN boxscores b ON p.player_lookup = b.player_lookup
        )
        SELECT
          COUNTIF(has_prop) as total_with_props,
          COUNTIF(has_prop AND is_graded) as graded,
          COUNTIF(has_prop AND NOT is_graded) as ungraded,
          COUNTIF(has_prop AND NOT is_graded AND NOT has_boxscore) as missing_boxscore,
          COUNTIF(has_prop AND NOT is_graded AND has_boxscore) as has_boxscore_not_graded
        FROM analysis
        """

        results = self._query(query)
        if not results:
            return DiagnosisReport(
                issue_type="grading_lag",
                game_date=game_date,
                summary="Could not analyze grading",
                root_causes=[],
                recommended_actions=[]
            )

        data = results[0]
        total = data.get('total_with_props') or 0
        graded = data.get('graded') or 0
        ungraded = data.get('ungraded') or 0
        missing_boxscore = data.get('missing_boxscore') or 0
        has_boxscore_not_graded = data.get('has_boxscore_not_graded') or 0

        root_causes = []

        if missing_boxscore > 0:
            root_causes.append(RootCause(
                category="missing_boxscores",
                description=f"{missing_boxscore} predictions can't be graded - no boxscore data",
                impact_count=missing_boxscore,
                impact_pct=(missing_boxscore / ungraded * 100) if ungraded > 0 else 0,
                fix_suggestion="Fetch missing boxscores first",
                details={"command": f"python bin/backfill/bdl_boxscores.py --date {game_date}"}
            ))

        if has_boxscore_not_graded > 0:
            root_causes.append(RootCause(
                category="grading_processor_issue",
                description=f"{has_boxscore_not_graded} predictions have boxscores but aren't graded",
                impact_count=has_boxscore_not_graded,
                impact_pct=(has_boxscore_not_graded / ungraded * 100) if ungraded > 0 else 0,
                fix_suggestion="Run grading backfill",
                details={"command": f"python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --start-date {game_date} --end-date {game_date}"}
            ))

        actions = []
        if missing_boxscore > 0:
            actions.append(f"1. Fetch boxscores: python bin/backfill/bdl_boxscores.py --date {game_date}")
        actions.append(f"2. Run grading: python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --start-date {game_date} --end-date {game_date}")

        grading_pct = (graded / total * 100) if total > 0 else 0
        return DiagnosisReport(
            issue_type="grading_lag",
            game_date=game_date,
            summary=f"Grading: {grading_pct:.1f}% ({graded}/{total}). Ungraded: {ungraded}.",
            root_causes=root_causes,
            recommended_actions=actions
        )

    def _analyze_missing_boxscores(self, game_date: date) -> DiagnosisReport:
        """Analyze why boxscores are missing."""
        query = f"""
        WITH
        schedule AS (
          SELECT
            game_id as nba_game_id,
            CONCAT(FORMAT_DATE('%Y%m%d', game_date), '_', away_team_tricode, '_', home_team_tricode) as bdl_game_id,
            home_team_tricode,
            away_team_tricode,
            game_status
          FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
          WHERE game_date = '{game_date}' AND game_status = 3
        ),
        boxscores AS (
          SELECT DISTINCT game_id
          FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
          WHERE game_date = '{game_date}'
        )
        SELECT
          s.nba_game_id,
          s.bdl_game_id,
          s.home_team_tricode,
          s.away_team_tricode,
          CASE WHEN b.game_id IS NOT NULL THEN TRUE ELSE FALSE END as has_boxscore
        FROM schedule s
        LEFT JOIN boxscores b ON s.bdl_game_id = b.game_id
        WHERE b.game_id IS NULL
        """

        results = self._query(query)

        if not results:
            return DiagnosisReport(
                issue_type="missing_boxscores",
                game_date=game_date,
                summary="All scheduled games have boxscores",
                root_causes=[],
                recommended_actions=[]
            )

        missing_games = [f"{r['away_team_tricode']}@{r['home_team_tricode']}" for r in results]

        root_causes = [
            RootCause(
                category="scraper_failure",
                description=f"{len(results)} games not scraped: {', '.join(missing_games)}",
                impact_count=len(results),
                impact_pct=100,
                fix_suggestion="Run BDL boxscore scraper for this date",
                details={"games": missing_games}
            )
        ]

        return DiagnosisReport(
            issue_type="missing_boxscores",
            game_date=game_date,
            summary=f"{len(results)} games missing boxscores",
            root_causes=root_causes,
            recommended_actions=[f"python bin/backfill/bdl_boxscores.py --date {game_date}"]
        )

    def _analyze_missing_analytics(self, game_date: date) -> DiagnosisReport:
        """Analyze why analytics are missing."""
        query = f"""
        WITH
        boxscore_games AS (
          SELECT DISTINCT game_id
          FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
          WHERE game_date = '{game_date}'
        ),
        analytics_games AS (
          SELECT DISTINCT game_id
          FROM `{self.project_id}.nba_analytics.player_game_summary`
          WHERE game_date = '{game_date}'
        )
        SELECT
          b.game_id,
          CASE WHEN a.game_id IS NOT NULL THEN TRUE ELSE FALSE END as has_analytics
        FROM boxscore_games b
        LEFT JOIN analytics_games a ON b.game_id = a.game_id
        WHERE a.game_id IS NULL
        """

        results = self._query(query)

        if not results:
            return DiagnosisReport(
                issue_type="missing_analytics",
                game_date=game_date,
                summary="All boxscore games have analytics",
                root_causes=[],
                recommended_actions=[]
            )

        root_causes = [
            RootCause(
                category="phase3_failure",
                description=f"{len(results)} games have boxscores but no analytics (Phase 3 stalled)",
                impact_count=len(results),
                impact_pct=100,
                fix_suggestion="Run Phase 3 backfill",
                details={"stuck_games": [r['game_id'] for r in results]}
            )
        ]

        return DiagnosisReport(
            issue_type="missing_analytics",
            game_date=game_date,
            summary=f"{len(results)} games stuck after Phase 2",
            root_causes=root_causes,
            recommended_actions=[f"python bin/backfill/phase3.py --date {game_date}"]
        )

    def _analyze_low_feature_quality(self, game_date: date) -> DiagnosisReport:
        """Analyze why feature quality is low."""
        query = f"""
        SELECT
          COUNT(*) as total,
          AVG(feature_quality_score) as avg_quality,
          COUNTIF(feature_quality_score < 65) as low_count,
          AVG(l7d_completeness_pct) as avg_l7d,
          AVG(l14d_completeness_pct) as avg_l14d
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2` f
        LEFT JOIN `{self.project_id}.nba_analytics.upcoming_player_game_context` c
          ON f.player_lookup = c.player_lookup AND f.game_date = c.game_date
        WHERE f.game_date = '{game_date}'
        """

        results = self._query(query)
        if not results:
            return DiagnosisReport(
                issue_type="low_feature_quality",
                game_date=game_date,
                summary="No feature data to analyze",
                root_causes=[],
                recommended_actions=[]
            )

        data = results[0]
        avg_quality = data.get('avg_quality') or 0
        low_count = data.get('low_count') or 0
        avg_l7d = data.get('avg_l7d') or 0
        avg_l14d = data.get('avg_l14d') or 0

        root_causes = []

        if avg_l7d < 70:
            root_causes.append(RootCause(
                category="incomplete_rolling_windows",
                description=f"L7D completeness only {avg_l7d:.1f}% (target: 80%+)",
                impact_count=low_count,
                impact_pct=100,
                fix_suggestion="Backfill analytics for the past 14 days",
                details={"avg_l7d": avg_l7d, "avg_l14d": avg_l14d}
            ))

        return DiagnosisReport(
            issue_type="low_feature_quality",
            game_date=game_date,
            summary=f"Avg quality: {avg_quality:.1f}, {low_count} players below threshold",
            root_causes=root_causes,
            recommended_actions=[
                f"1. Backfill Phase 3 analytics: python bin/backfill/phase3.py --start-date {game_date - timedelta(days=14)} --end-date {game_date}",
                f"2. Regenerate Phase 4 features: python bin/backfill/phase4.py --date {game_date}"
            ]
        )

    def _analyze_all(self, game_date: date) -> DiagnosisReport:
        """Run all analyses and combine."""
        reports = [
            self._analyze_low_coverage(game_date),
            self._analyze_grading_lag(game_date),
            self._analyze_missing_boxscores(game_date),
            self._analyze_missing_analytics(game_date)
        ]

        all_causes = []
        all_actions = set()

        for report in reports:
            for cause in report.root_causes:
                if cause.impact_count > 0:
                    all_causes.append(cause)
            all_actions.update(report.recommended_actions)

        return DiagnosisReport(
            issue_type="comprehensive",
            game_date=game_date,
            summary=f"Analyzed {len(reports)} issue types",
            root_causes=sorted(all_causes, key=lambda x: x.impact_count, reverse=True),
            recommended_actions=sorted(list(all_actions))
        )


def print_report(report: DiagnosisReport):
    """Print diagnosis report."""
    print("\n" + "=" * 80)
    print(f"ROOT CAUSE ANALYSIS: {report.issue_type}")
    print(f"Date: {report.game_date}")
    print(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    print(f"\nSummary: {report.summary}")

    if report.root_causes:
        print(f"\n{'-'*80}")
        print("ROOT CAUSES (sorted by impact)")
        print(f"{'-'*80}")

        for i, cause in enumerate(report.root_causes, 1):
            print(f"\n{i}. [{cause.category}] {cause.description}")
            print(f"   Impact: {cause.impact_count} items ({cause.impact_pct:.1f}% of gap)")
            print(f"   Fix: {cause.fix_suggestion}")
            if cause.details.get('command'):
                print(f"   Command: {cause.details['command']}")
    else:
        print("\nNo specific root causes identified.")

    if report.recommended_actions:
        print(f"\n{'-'*80}")
        print("RECOMMENDED ACTIONS")
        print(f"{'-'*80}")
        for action in report.recommended_actions:
            print(f"  {action}")

    print("\n" + "=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Root cause analyzer")
    parser.add_argument('--date', type=str, required=True, help='Date to analyze (YYYY-MM-DD)')
    parser.add_argument('--issue', type=str, default='all',
                        choices=['all', 'low_coverage', 'grading_lag', 'missing_boxscores',
                                 'missing_analytics', 'low_feature_quality'],
                        help='Issue type to analyze')

    args = parser.parse_args()
    game_date = date.fromisoformat(args.date)

    analyzer = RootCauseAnalyzer()
    report = analyzer.analyze(args.issue, game_date)
    print_report(report)


if __name__ == "__main__":
    main()
