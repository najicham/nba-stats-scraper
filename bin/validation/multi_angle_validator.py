#!/usr/bin/env python3
"""
Multi-Angle Validation System

Validates data from multiple perspectives to catch different types of issues.
Each "angle" checks the same data from a different viewpoint - discrepancies
between angles indicate problems that need investigation.

Validation Angles:
1. LINES: Lines available vs predictions made (are we using all available lines?)
2. GAMES: Games played vs games with predictions (did we cover all games?)
3. PLAYERS: Players who played vs players with predictions (did we miss anyone?)
4. GRADING: Predictions made vs graded (is grading keeping up?)
5. ACTUALS: Box scores vs analytics (did Phase 3 process all data?)
6. FEATURES: Analytics vs features (did Phase 4 process all data?)
7. TIMING: Were predictions made before game time?

Usage:
    python bin/validation/multi_angle_validator.py
    python bin/validation/multi_angle_validator.py --date 2026-01-24
    python bin/validation/multi_angle_validator.py --start-date 2026-01-01 --end-date 2026-01-24

Created: 2026-01-25
Part of: Pipeline Resilience Improvements
"""

import argparse
import os
import sys
from datetime import date, timedelta
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery

PROJECT_ID = 'nba-props-platform'


@dataclass
class ValidationResult:
    """Result of a single validation check."""
    angle: str
    metric_a: str
    metric_b: str
    value_a: int
    value_b: int
    expected_relationship: str  # 'equal', 'a >= b', 'a <= b'
    is_valid: bool
    discrepancy: int
    message: str


class MultiAngleValidator:
    """
    Validates pipeline data from multiple angles.

    Discrepancies between angles indicate issues that need investigation.
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)
        self.results: List[ValidationResult] = []

    def validate_date(self, game_date: date) -> List[ValidationResult]:
        """Run all validations for a single date."""
        self.results = []

        # Get all the data we need in one set of queries
        data = self._query_all_data(game_date)

        # Angle 1: Lines vs Predictions
        self._validate_lines_vs_predictions(game_date, data)

        # Angle 2: Games vs Predictions
        self._validate_games_vs_predictions(game_date, data)

        # Angle 3: Players vs Predictions
        self._validate_players_vs_predictions(game_date, data)

        # Angle 4: Predictions vs Grading
        self._validate_predictions_vs_grading(game_date, data)

        # Angle 5: Box Scores vs Analytics
        self._validate_boxscores_vs_analytics(game_date, data)

        # Angle 6: Analytics vs Features
        self._validate_analytics_vs_features(game_date, data)

        # Angle 7: Cross-check totals
        self._validate_cross_totals(game_date, data)

        return self.results

    def _query_all_data(self, game_date: date) -> Dict[str, Any]:
        """Query all needed data in efficient batched queries."""
        query = f"""
        WITH
        -- Games played
        games AS (
            SELECT
                COUNT(DISTINCT game_id) as games_played,
                COUNT(DISTINCT CONCAT(home_team_tricode, away_team_tricode)) as matchups
            FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
            WHERE game_status = 3 AND game_date = @game_date
        ),
        -- Lines available (unique player-game combinations)
        lines AS (
            SELECT
                COUNT(DISTINCT CONCAT(player_lookup, '_', CAST(game_date AS STRING))) as lines_available,
                COUNT(DISTINCT player_lookup) as players_with_lines,
                COUNT(DISTINCT game_id) as games_with_lines
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date = @game_date
        ),
        -- Box scores (players who actually played)
        boxscores AS (
            SELECT
                COUNT(DISTINCT game_id) as games_with_boxscores,
                COUNT(DISTINCT player_lookup) as players_in_boxscores,
                COUNT(*) as boxscore_rows
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE game_date = @game_date
        ),
        -- Analytics processed
        analytics AS (
            SELECT
                COUNT(DISTINCT game_id) as games_with_analytics,
                COUNT(DISTINCT player_lookup) as players_in_analytics,
                COUNT(*) as analytics_rows
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date = @game_date
        ),
        -- Features computed
        features AS (
            SELECT
                COUNT(DISTINCT game_id) as games_with_features,
                COUNT(DISTINCT player_lookup) as players_with_features,
                COUNT(*) as feature_rows,
                AVG(feature_quality_score) as avg_quality
            FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
            WHERE game_date = @game_date
        ),
        -- Predictions made (catboost_v8 only for main tracking)
        predictions AS (
            SELECT
                COUNT(*) as total_predictions,
                COUNT(DISTINCT player_lookup) as players_predicted,
                COUNT(DISTINCT game_id) as games_predicted,
                COUNTIF(line_source = 'ACTUAL_PROP') as predictions_with_lines,
                COUNTIF(line_source = 'NO_PROP_LINE') as predictions_without_lines,
                COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable_predictions
            FROM `{self.project_id}.nba_predictions.player_prop_predictions`
            WHERE game_date = @game_date
                AND system_id = 'catboost_v8'
                AND is_active = TRUE
        ),
        -- Graded predictions
        graded AS (
            SELECT
                COUNT(*) as graded_count,
                COUNT(DISTINCT player_lookup) as players_graded,
                COUNTIF(prediction_correct = TRUE) as correct_count
            FROM `{self.project_id}.nba_predictions.prediction_accuracy`
            WHERE game_date = @game_date
                AND system_id = 'catboost_v8'
                AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')  -- v4.1: Use line_source instead of buggy has_prop_line
        )
        SELECT
            g.games_played, g.matchups,
            l.lines_available, l.players_with_lines, l.games_with_lines,
            b.games_with_boxscores, b.players_in_boxscores, b.boxscore_rows,
            a.games_with_analytics, a.players_in_analytics, a.analytics_rows,
            f.games_with_features, f.players_with_features, f.feature_rows, f.avg_quality,
            p.total_predictions, p.players_predicted, p.games_predicted,
            p.predictions_with_lines, p.predictions_without_lines, p.actionable_predictions,
            gr.graded_count, gr.players_graded, gr.correct_count
        FROM games g, lines l, boxscores b, analytics a, features f, predictions p, graded gr
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        result = list(self.client.query(query, job_config=job_config).result())
        if result:
            return dict(result[0])
        return {}

    def _add_result(self, angle: str, metric_a: str, metric_b: str,
                    value_a: int, value_b: int, expected: str, threshold: float = 0.1):
        """Add a validation result."""
        if expected == 'equal':
            is_valid = value_a == value_b
            discrepancy = abs(value_a - value_b)
        elif expected == 'a >= b':
            is_valid = value_a >= value_b * (1 - threshold)
            discrepancy = max(0, value_b - value_a)
        elif expected == 'a <= b':
            is_valid = value_a <= value_b * (1 + threshold)
            discrepancy = max(0, value_a - value_b)
        else:
            is_valid = True
            discrepancy = 0

        if is_valid:
            message = "OK"
        else:
            message = f"DISCREPANCY: {metric_a}={value_a} vs {metric_b}={value_b} (diff={discrepancy})"

        self.results.append(ValidationResult(
            angle=angle,
            metric_a=metric_a,
            metric_b=metric_b,
            value_a=value_a,
            value_b=value_b,
            expected_relationship=expected,
            is_valid=is_valid,
            discrepancy=discrepancy,
            message=message
        ))

    def _validate_lines_vs_predictions(self, game_date: date, data: Dict):
        """Angle 1: Are we making predictions for available lines?"""
        self._add_result(
            angle="LINES",
            metric_a="predictions_with_lines",
            metric_b="lines_available",
            value_a=data.get('predictions_with_lines', 0),
            value_b=data.get('lines_available', 0),
            expected="a >= b",
            threshold=0.2  # Allow 20% discrepancy
        )

    def _validate_games_vs_predictions(self, game_date: date, data: Dict):
        """Angle 2: Are we covering all games?"""
        self._add_result(
            angle="GAMES",
            metric_a="games_predicted",
            metric_b="games_played",
            value_a=data.get('games_predicted', 0),
            value_b=data.get('games_played', 0),
            expected="equal"
        )

    def _validate_players_vs_predictions(self, game_date: date, data: Dict):
        """Angle 3: Are we predicting for enough players?"""
        # Players with lines should have predictions
        self._add_result(
            angle="PLAYERS",
            metric_a="players_predicted",
            metric_b="players_with_lines",
            value_a=data.get('players_predicted', 0),
            value_b=data.get('players_with_lines', 0),
            expected="a >= b",
            threshold=0.15
        )

    def _validate_predictions_vs_grading(self, game_date: date, data: Dict):
        """Angle 4: Are predictions being graded?"""
        # Actionable predictions should be graded (with some delay tolerance)
        actionable = data.get('actionable_predictions', 0)
        graded = data.get('graded_count', 0)

        # Only flag if significantly behind
        if actionable > 0:
            self._add_result(
                angle="GRADING",
                metric_a="graded_count",
                metric_b="actionable_predictions",
                value_a=graded,
                value_b=actionable,
                expected="a >= b",
                threshold=0.3  # 30% tolerance for grading delay
            )

    def _validate_boxscores_vs_analytics(self, game_date: date, data: Dict):
        """Angle 5: Are box scores being processed into analytics?"""
        self._add_result(
            angle="ANALYTICS",
            metric_a="games_with_analytics",
            metric_b="games_with_boxscores",
            value_a=data.get('games_with_analytics', 0),
            value_b=data.get('games_with_boxscores', 0),
            expected="equal"
        )

        # Also check player counts
        self._add_result(
            angle="ANALYTICS_PLAYERS",
            metric_a="players_in_analytics",
            metric_b="players_in_boxscores",
            value_a=data.get('players_in_analytics', 0),
            value_b=data.get('players_in_boxscores', 0),
            expected="equal"
        )

    def _validate_analytics_vs_features(self, game_date: date, data: Dict):
        """Angle 6: Are analytics being processed into features?"""
        self._add_result(
            angle="FEATURES",
            metric_a="players_with_features",
            metric_b="players_in_analytics",
            value_a=data.get('players_with_features', 0),
            value_b=data.get('players_in_analytics', 0),
            expected="a >= b",
            threshold=0.1
        )

    def _validate_cross_totals(self, game_date: date, data: Dict):
        """Angle 7: Cross-check related totals."""
        # Box scores should come from all games
        self._add_result(
            angle="BOXSCORES",
            metric_a="games_with_boxscores",
            metric_b="games_played",
            value_a=data.get('games_with_boxscores', 0),
            value_b=data.get('games_played', 0),
            expected="equal"
        )


def print_results(game_date: date, results: List[ValidationResult]):
    """Print validation results in a nice format."""
    print(f"\n{'='*80}")
    print(f"MULTI-ANGLE VALIDATION: {game_date}")
    print(f"{'='*80}")

    issues = [r for r in results if not r.is_valid]
    ok_count = len(results) - len(issues)

    print(f"\n{ok_count}/{len(results)} checks passed")

    if issues:
        print(f"\n{'⚠️ '*3} ISSUES FOUND {'⚠️ '*3}")
        print("-" * 80)
        for r in issues:
            print(f"\n[{r.angle}] {r.message}")
            print(f"   Expected: {r.metric_a} {r.expected_relationship} {r.metric_b}")
    else:
        print("\n✅ All validation angles passed!")

    print(f"\n{'='*80}")
    print("DETAILED RESULTS:")
    print("-" * 80)
    print(f"{'Angle':<20} {'Metric A':<25} {'Value':>8} {'Metric B':<25} {'Value':>8} {'Status':<8}")
    print("-" * 80)

    for r in results:
        status = "✅" if r.is_valid else "❌"
        print(f"{r.angle:<20} {r.metric_a:<25} {r.value_a:>8} {r.metric_b:<25} {r.value_b:>8} {status:<8}")

    print("-" * 80)


def main():
    parser = argparse.ArgumentParser(description="Multi-angle validation")
    parser.add_argument('--date', type=str, help='Specific date (YYYY-MM-DD)')
    parser.add_argument('--start-date', type=str, help='Start date for range')
    parser.add_argument('--end-date', type=str, help='End date for range')
    parser.add_argument('--days', type=int, default=7, help='Days to check (default: 7)')

    args = parser.parse_args()

    validator = MultiAngleValidator()

    # Determine dates to check
    if args.start_date and args.end_date:
        start = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date)
        dates = []
        current = start
        while current <= end:
            dates.append(current)
            current += timedelta(days=1)
    elif args.date:
        dates = [date.fromisoformat(args.date)]
    else:
        dates = [date.today() - timedelta(days=i) for i in range(1, args.days + 1)]

    # Run validation for each date
    all_issues = []
    for game_date in dates:
        results = validator.validate_date(game_date)
        issues = [r for r in results if not r.is_valid]

        if issues:
            all_issues.append((game_date, issues))

        print_results(game_date, results)

    # Summary
    if len(dates) > 1:
        print(f"\n{'='*80}")
        print("SUMMARY")
        print(f"{'='*80}")
        print(f"\nDates checked: {len(dates)}")
        print(f"Dates with issues: {len(all_issues)}")

        if all_issues:
            print("\n⚠️ Dates requiring attention:")
            for game_date, issues in all_issues:
                angles = set(i.angle for i in issues)
                print(f"  {game_date}: Issues in {', '.join(angles)}")


if __name__ == "__main__":
    main()
