#!/usr/bin/env python3
# File: validation/validators/grading/mlb_prediction_grading_validator.py
# Description: Validator for MLB pitcher strikeouts prediction grading
# Created: 2026-01-24
"""
Validator for MLB Pitcher Strikeouts Prediction Grading table.

Validates mlb_predictions.pitcher_strikeouts which contains
graded MLB pitcher strikeout predictions.

Business key: prediction_id
Join keys: pitcher_lookup + game_date

Grading logic:
- OVER: correct if actual > line
- UNDER: correct if actual < line
- PUSH: actual = line (is_correct = NULL)
- PASS: not graded

Validation checks:
1. No stale ungraded records (CRITICAL)
2. Correctness validity (TRUE/FALSE/NULL only)
3. Actual strikeouts bounds (0-20)
4. Actual vs line consistency
5. NULL handling for PASS
6. Graded timestamp validity
7. Volume per date
8. Missing actuals percentage
9. No duplicate predictions
10. Data freshness
"""

import sys
import os
import time
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from validation.base_validator import BaseValidator, ValidationResult
import logging

logger = logging.getLogger(__name__)


class MLBPredictionGradingValidator(BaseValidator):
    """
    Validator for MLB Pitcher Strikeouts Prediction Grading table.

    This table contains graded MLB pitcher strikeout predictions with:
    - Predicted strikeouts vs actual strikeouts
    - OVER/UNDER recommendation correctness
    - Line timing analysis (very_early, early, closing)
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """MLB prediction grading specific validations"""

        logger.info("Running MLB Prediction Grading validations...")

        # Check 1: No stale ungraded records (CRITICAL)
        self._validate_no_stale_ungraded(start_date, end_date)

        # Check 2: Correctness validity
        self._validate_correctness_values(start_date, end_date)

        # Check 3: Actual strikeouts bounds
        self._validate_strikeouts_bounds(start_date, end_date)

        # Check 4: Actual vs line consistency
        self._validate_grading_logic(start_date, end_date)

        # Check 5: NULL handling for PASS
        self._validate_pass_handling(start_date, end_date)

        # Check 6: Graded timestamp validity
        self._validate_graded_timestamp(start_date, end_date)

        # Check 7: Volume per date
        self._validate_volume_per_date(start_date, end_date)

        # Check 8: Missing actuals percentage
        self._validate_missing_actuals(start_date, end_date)

        # Check 9: No duplicate predictions
        self._validate_no_duplicates(start_date, end_date)

        # Check 10: Data freshness
        self._validate_freshness(start_date, end_date)

        logger.info("Completed MLB Prediction Grading validations")

    def _validate_no_stale_ungraded(self, start_date: str, end_date: str):
        """Check for predictions that should be graded but aren't (CRITICAL)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            recommendation,
            actual_strikeouts,
            is_correct
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND game_date < CURRENT_DATE()  -- Past games only
          AND recommendation IN ('OVER', 'UNDER')  -- Should be graded
          AND is_correct IS NULL  -- Not yet graded
          AND actual_strikeouts IS NOT NULL  -- Has actual data
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            stale = [(str(row.game_date), row.pitcher_lookup, row.recommendation) for row in result]

            passed = len(stale) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="no_stale_ungraded_records",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="critical" if not passed else "info",
                message=f"Found {len(stale)} predictions with actuals but no grade" if not passed else "All graded predictions are up to date",
                affected_count=len(stale),
                affected_items=stale[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed stale ungraded validation: {e}")
            self._add_error_result("no_stale_ungraded_records", str(e))

    def _validate_correctness_values(self, start_date: str, end_date: str):
        """Check that is_correct is only TRUE, FALSE, or NULL"""

        check_start = time.time()

        # BigQuery BOOL can only be TRUE, FALSE, or NULL, so this mainly checks for data integrity
        query = f"""
        SELECT
            game_date,
            COUNT(*) as total,
            COUNTIF(is_correct = TRUE) as correct_count,
            COUNTIF(is_correct = FALSE) as incorrect_count,
            COUNTIF(is_correct IS NULL) as null_count
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        ORDER BY game_date DESC
        LIMIT 20
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))

            # Check if counts make sense
            invalid = []
            for row in result:
                if row.correct_count + row.incorrect_count + row.null_count != row.total:
                    invalid.append((str(row.game_date), row.total, row.correct_count + row.incorrect_count + row.null_count))

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="correctness_validity",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(invalid)} dates with inconsistent correctness counts" if not passed else "All correctness values are valid",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed correctness values validation: {e}")
            self._add_error_result("correctness_validity", str(e))

    def _validate_strikeouts_bounds(self, start_date: str, end_date: str):
        """Check that actual_strikeouts is in reasonable bounds (0-20)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            actual_strikeouts
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND actual_strikeouts IS NOT NULL
          AND (actual_strikeouts < 0 OR actual_strikeouts > 20)
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            out_of_bounds = [(str(row.game_date), row.pitcher_lookup, row.actual_strikeouts) for row in result]

            passed = len(out_of_bounds) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="strikeouts_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(out_of_bounds)} records with strikeouts outside 0-20 range" if not passed else "All strikeout values within expected bounds",
                affected_count=len(out_of_bounds),
                affected_items=out_of_bounds[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed strikeouts bounds validation: {e}")
            self._add_error_result("strikeouts_bounds", str(e))

    def _validate_grading_logic(self, start_date: str, end_date: str):
        """Check that is_correct matches actual vs line logic"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            recommendation,
            actual_strikeouts,
            strikeouts_line,
            is_correct
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND actual_strikeouts IS NOT NULL
          AND strikeouts_line IS NOT NULL
          AND is_correct IS NOT NULL
          AND (
            -- OVER should be correct when actual > line
            (recommendation = 'OVER' AND actual_strikeouts > strikeouts_line AND is_correct = FALSE) OR
            (recommendation = 'OVER' AND actual_strikeouts < strikeouts_line AND is_correct = TRUE) OR
            -- UNDER should be correct when actual < line
            (recommendation = 'UNDER' AND actual_strikeouts < strikeouts_line AND is_correct = FALSE) OR
            (recommendation = 'UNDER' AND actual_strikeouts > strikeouts_line AND is_correct = TRUE)
          )
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            inconsistent = [
                (str(row.game_date), row.pitcher_lookup, row.recommendation, row.actual_strikeouts, row.strikeouts_line, row.is_correct)
                for row in result
            ]

            passed = len(inconsistent) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="grading_logic_consistency",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(inconsistent)} records with incorrect grading logic" if not passed else "All grading logic is consistent",
                affected_count=len(inconsistent),
                affected_items=inconsistent[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed grading logic validation: {e}")
            self._add_error_result("grading_logic_consistency", str(e))

    def _validate_pass_handling(self, start_date: str, end_date: str):
        """Check that PASS recommendations have NULL is_correct"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            recommendation,
            is_correct
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND recommendation = 'PASS'
          AND is_correct IS NOT NULL
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.game_date), row.pitcher_lookup, row.is_correct) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="pass_handling",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} PASS records with non-NULL is_correct" if not passed else "All PASS recommendations have NULL is_correct",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed PASS handling validation: {e}")
            self._add_error_result("pass_handling", str(e))

    def _validate_graded_timestamp(self, start_date: str, end_date: str):
        """Check that graded_at is set when is_correct is set"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            is_correct,
            graded_at
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND is_correct IS NOT NULL
          AND graded_at IS NULL
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            missing_timestamp = [(str(row.game_date), row.pitcher_lookup, row.is_correct) for row in result]

            passed = len(missing_timestamp) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="graded_timestamp_validity",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(missing_timestamp)} graded records without graded_at timestamp" if not passed else "All graded records have timestamps",
                affected_count=len(missing_timestamp),
                affected_items=missing_timestamp[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed graded timestamp validation: {e}")
            self._add_error_result("graded_timestamp_validity", str(e))

    def _validate_volume_per_date(self, start_date: str, end_date: str):
        """Check that we have expected volume per MLB game date (8-15 starters)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            COUNT(*) as prediction_count
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        HAVING COUNT(*) < 5
        ORDER BY game_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            low_volume = [(str(row.game_date), row.prediction_count) for row in result]

            passed = len(low_volume) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="volume_per_date",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(low_volume)} dates with fewer than 5 predictions" if not passed else "All dates have adequate prediction volume",
                affected_count=len(low_volume),
                affected_items=low_volume[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed volume per date validation: {e}")
            self._add_error_result("volume_per_date", str(e))

    def _validate_missing_actuals(self, start_date: str, end_date: str):
        """Check that <5% of past predictions have missing actuals"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            COUNT(*) as total_predictions,
            COUNTIF(actual_strikeouts IS NULL) as missing_actuals,
            ROUND(COUNTIF(actual_strikeouts IS NULL) * 100.0 / COUNT(*), 2) as missing_pct
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND game_date < CURRENT_DATE()
        GROUP BY game_date
        HAVING ROUND(COUNTIF(actual_strikeouts IS NULL) * 100.0 / COUNT(*), 2) > 10
        ORDER BY game_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            high_missing = [(str(row.game_date), row.missing_actuals, row.missing_pct) for row in result]

            passed = len(high_missing) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="missing_actuals_percentage",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(high_missing)} dates with >10% missing actuals" if not passed else "All dates have <10% missing actuals",
                affected_count=len(high_missing),
                affected_items=high_missing[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed missing actuals validation: {e}")
            self._add_error_result("missing_actuals_percentage", str(e))

    def _validate_no_duplicates(self, start_date: str, end_date: str):
        """Check for duplicate (pitcher_lookup, game_date) entries"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            COUNT(*) as entry_count
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date, pitcher_lookup
        HAVING COUNT(*) > 1
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            duplicates = [(str(row.game_date), row.pitcher_lookup, row.entry_count) for row in result]

            passed = len(duplicates) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="no_duplicate_predictions",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(duplicates)} duplicate (pitcher, game_date) entries" if not passed else "No duplicate predictions found",
                affected_count=len(duplicates),
                affected_items=duplicates[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed duplicate validation: {e}")
            self._add_error_result("no_duplicate_predictions", str(e))

    def _validate_freshness(self, start_date: str, end_date: str):
        """Check that data is recent enough"""

        check_start = time.time()

        query = f"""
        SELECT
            MAX(game_date) as latest_date,
            DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_stale
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))

            if result and result[0].latest_date:
                days_stale = result[0].days_stale
                passed = days_stale <= 2
                message = f"Latest prediction is {days_stale} days old (threshold: 2 days)"
                severity = "info" if days_stale <= 1 else ("warning" if days_stale <= 2 else "error")
            else:
                passed = False
                message = "No data found in date range"
                severity = "error"

            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="data_freshness",
                check_type="freshness",
                layer="bigquery",
                passed=passed,
                severity=severity,
                message=message,
                affected_count=0 if passed else 1,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed freshness validation: {e}")
            self._add_error_result("data_freshness", str(e))

    def _add_error_result(self, check_name: str, error_msg: str):
        """Add an error result for failed checks"""
        self.results.append(ValidationResult(
            check_name=check_name,
            check_type="error",
            layer="bigquery",
            passed=False,
            severity="error",
            message=f"Validation check failed: {error_msg}",
            affected_count=0
        ))


if __name__ == "__main__":
    import argparse
    from datetime import datetime, timedelta

    parser = argparse.ArgumentParser(description="Validate MLB Prediction Grading")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")

    args = parser.parse_args()

    if args.start_date and args.end_date:
        start_date = args.start_date
        end_date = args.end_date
    else:
        end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    print(f"Validating pitcher_strikeouts from {start_date} to {end_date}")

    validator = MLBPredictionGradingValidator(
        config_path="validation/configs/grading/mlb_prediction_grading.yaml"
    )

    results = validator.run_validation(start_date, end_date)

    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.check_name}: {result.message}")

    print("=" * 60)
