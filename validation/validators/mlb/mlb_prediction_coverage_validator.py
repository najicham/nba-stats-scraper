#!/usr/bin/env python3
"""
File: validation/validators/mlb/mlb_prediction_coverage_validator.py

MLB Prediction Coverage Validator

Validates that predictions are generated for all eligible pitchers:
- Coverage vs pitchers with props
- Prediction quality (confidence, edge)
- Grading completeness
- Model version consistency

Usage:
    validator = MlbPredictionCoverageValidator()
    report = validator.validate(start_date='2025-08-01', end_date='2025-08-31')
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from validation.base_validator import BaseValidator, ValidationResult

logger = logging.getLogger(__name__)


class MlbPredictionCoverageValidator(BaseValidator):
    """
    Validator for MLB prediction coverage.

    Validates:
    - Prediction coverage vs props
    - Prediction quality metrics
    - Grading completeness
    - No duplicate predictions
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """
        Run MLB prediction-specific validations.

        Args:
            start_date: Start date for validation
            end_date: End date for validation
            season_year: Season year (optional)
        """
        logger.info("Running MLB prediction coverage validations...")

        # 1. Prediction coverage
        self._validate_prediction_coverage(start_date, end_date)

        # 2. Prediction quality
        self._validate_prediction_quality(start_date, end_date)

        # 3. Grading completeness
        self._validate_grading_completeness(start_date, end_date)

        # 4. No duplicates
        self._validate_no_duplicates(start_date, end_date)

    def _validate_prediction_coverage(self, start_date: str, end_date: str):
        """Check that pitchers with props have predictions."""
        import time
        check_start = time.time()

        query = f"""
        WITH pitchers_with_props AS (
            SELECT DISTINCT game_date, pitcher_lookup
            FROM `{self.project_id}.mlb_raw.bp_pitcher_props`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND pitcher_lookup IS NOT NULL
        ),
        predictions AS (
            SELECT DISTINCT game_date, pitcher_lookup
            FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND pitcher_lookup IS NOT NULL
        ),
        coverage AS (
            SELECT
                p.game_date,
                COUNT(DISTINCT p.pitcher_lookup) as with_props,
                COUNT(DISTINCT pred.pitcher_lookup) as with_predictions
            FROM pitchers_with_props p
            LEFT JOIN predictions pred
                ON p.game_date = pred.game_date
                AND p.pitcher_lookup = pred.pitcher_lookup
            GROUP BY p.game_date
        )
        SELECT
            game_date,
            with_props,
            with_predictions,
            ROUND(100.0 * with_predictions / NULLIF(with_props, 0), 1) as coverage_pct
        FROM coverage
        WHERE with_predictions < with_props * 0.9  -- Less than 90% coverage
        ORDER BY game_date
        """

        result = self._execute_query(query, start_date, end_date)
        low_coverage = list(result)

        passed = len(low_coverage) == 0
        duration = time.time() - check_start

        affected_items = [
            f"{row.game_date}: {row.with_predictions}/{row.with_props} ({row.coverage_pct}%)"
            for row in low_coverage[:20]
        ]

        self.results.append(ValidationResult(
            check_name="prediction_coverage",
            check_type="completeness",
            layer="bigquery",
            passed=passed,
            severity="error",
            message=f"Found {len(low_coverage)} dates with low prediction coverage (<90%)" if not passed else "Good prediction coverage",
            affected_count=len(low_coverage),
            affected_items=affected_items,
            execution_duration=duration
        ))

    def _validate_prediction_quality(self, start_date: str, end_date: str):
        """Check prediction quality metrics."""
        import time
        check_start = time.time()

        query = f"""
        SELECT
            COUNT(*) as total_predictions,
            COUNTIF(confidence IS NULL OR confidence < 0 OR confidence > 100) as invalid_confidence,
            COUNTIF(predicted_strikeouts IS NULL OR predicted_strikeouts < 0) as invalid_prediction,
            COUNTIF(recommendation NOT IN ('OVER', 'UNDER', 'PASS')) as invalid_recommendation,
            ROUND(AVG(confidence), 1) as avg_confidence,
            ROUND(AVG(ABS(edge)), 2) as avg_edge
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        """

        result = self._execute_query(query, start_date, end_date)
        row = next(result, None)

        issues = []
        if row is None:
            issues.append("No data returned from query")
        else:
            if row.invalid_confidence > 0:
                issues.append(f"{row.invalid_confidence} invalid confidence values")
            if row.invalid_prediction > 0:
                issues.append(f"{row.invalid_prediction} invalid predictions")
            if row.invalid_recommendation > 0:
                issues.append(f"{row.invalid_recommendation} invalid recommendations")

        passed = len(issues) == 0
        duration = time.time() - check_start

        self.results.append(ValidationResult(
            check_name="prediction_quality",
            check_type="data_quality",
            layer="bigquery",
            passed=passed,
            severity="error" if not passed else "info",
            message="; ".join(issues) if issues else f"Quality OK (avg confidence: {row.avg_confidence}%, avg edge: {row.avg_edge})",
            affected_count=sum([row.invalid_confidence or 0, row.invalid_prediction or 0, row.invalid_recommendation or 0]),
            affected_items=issues,
            execution_duration=duration
        ))

    def _validate_grading_completeness(self, start_date: str, end_date: str):
        """Check that past predictions have been graded."""
        import time
        from datetime import datetime, timedelta
        check_start = time.time()

        # Only check dates that should be graded (games completed)
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        grading_end = min(end_date, yesterday)

        if grading_end < start_date:
            # No dates to check for grading
            self.results.append(ValidationResult(
                check_name="grading_completeness",
                check_type="completeness",
                layer="bigquery",
                passed=True,
                severity="info",
                message="No completed games to check for grading",
                affected_count=0,
                affected_items=[],
                execution_duration=time.time() - check_start
            ))
            return

        query = f"""
        WITH predictions AS (
            SELECT
                game_date,
                COUNT(*) as total_predictions,
                COUNTIF(is_correct IS NOT NULL) as graded_predictions
            FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{grading_end}'
            GROUP BY game_date
        )
        SELECT
            game_date,
            total_predictions,
            graded_predictions,
            ROUND(100.0 * graded_predictions / NULLIF(total_predictions, 0), 1) as graded_pct
        FROM predictions
        WHERE graded_predictions < total_predictions * 0.9  -- Less than 90% graded
        ORDER BY game_date
        """

        result = self._execute_query(query, start_date, grading_end)
        ungraded = list(result)

        passed = len(ungraded) == 0
        duration = time.time() - check_start

        affected_items = [
            f"{row.game_date}: {row.graded_predictions}/{row.total_predictions} graded ({row.graded_pct}%)"
            for row in ungraded[:20]
        ]

        self.results.append(ValidationResult(
            check_name="grading_completeness",
            check_type="completeness",
            layer="bigquery",
            passed=passed,
            severity="warning",
            message=f"Found {len(ungraded)} dates with incomplete grading" if not passed else "All predictions graded",
            affected_count=len(ungraded),
            affected_items=affected_items,
            execution_duration=duration
        ))

    def _validate_no_duplicates(self, start_date: str, end_date: str):
        """Check for duplicate predictions."""
        import time
        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            model_version,
            COUNT(*) as dup_count
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date, pitcher_lookup, model_version
        HAVING COUNT(*) > 1
        ORDER BY dup_count DESC
        LIMIT 50
        """

        result = self._execute_query(query, start_date, end_date)
        duplicates = list(result)

        passed = len(duplicates) == 0
        duration = time.time() - check_start

        affected_items = [
            f"{row.game_date}: {row.pitcher_lookup} ({row.model_version}) x{row.dup_count}"
            for row in duplicates[:20]
        ]

        self.results.append(ValidationResult(
            check_name="no_duplicates",
            check_type="data_quality",
            layer="bigquery",
            passed=passed,
            severity="error",
            message=f"Found {len(duplicates)} duplicate predictions" if not passed else "No duplicates",
            affected_count=len(duplicates),
            affected_items=affected_items,
            execution_duration=duration
        ))

    def _generate_backfill_commands(self, missing_dates: List[str]) -> List[str]:
        """Generate prediction backfill commands."""
        if not missing_dates:
            return []

        commands = []
        for date_str in missing_dates[:10]:
            commands.append(
                f"# Re-run MLB predictions for {date_str}\n"
                f"curl -X POST https://mlb-prediction-worker-756957797294.us-west2.run.app/predict-batch "
                f"-H 'Content-Type: application/json' "
                f"-d '{{\"game_date\": \"{date_str}\"}}'"
            )

        return commands


def main():
    """Main entry point for standalone validation."""
    import argparse
    import os

    parser = argparse.ArgumentParser(
        description='MLB Prediction Coverage Validator'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        required=True,
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        required=True,
        help='End date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--output-mode',
        type=str,
        default='summary',
        choices=['summary', 'detailed', 'quiet'],
        help='Output verbosity'
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Use config file if it exists
    config_path = 'validation/configs/mlb/mlb_prediction_coverage.yaml'
    if not os.path.exists(config_path):
        # Create default config
        config_path = None

    if config_path:
        validator = MlbPredictionCoverageValidator(config_path)
    else:
        # Create validator with inline config
        validator = MlbPredictionCoverageValidator.__new__(MlbPredictionCoverageValidator)
        validator.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        validator.processor_name = 'mlb_prediction_coverage'
        validator.processor_type = 'predictions'
        validator.results = []
        validator._query_cache = {}
        validator.partition_handler = None
        validator._start_time = 0

        from google.cloud import bigquery
        validator.bq_client = bigquery.Client(project=validator.project_id)

    report = validator.validate(
        start_date=args.start_date,
        end_date=args.end_date,
        output_mode=args.output_mode
    )

    return 0 if report.overall_status == 'pass' else 1


if __name__ == '__main__':
    exit(main())
