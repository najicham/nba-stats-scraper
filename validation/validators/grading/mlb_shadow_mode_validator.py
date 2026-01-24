#!/usr/bin/env python3
# File: validation/validators/grading/mlb_shadow_mode_validator.py
# Description: Validator for MLB shadow mode prediction comparison
# Created: 2026-01-24
"""
Validator for MLB Shadow Mode Predictions table.

Validates mlb_predictions.shadow_mode_predictions which contains
V1.4 (champion) vs V1.6 (challenger) model comparison results.

Business key: pitcher_lookup + game_date

Comparison logic:
- v1_4_correct / v1_6_correct: OVER/UNDER evaluation
- v1_4_error / v1_6_error: predicted - actual (signed)
- closer_prediction: v1_4 / v1_6 / tie based on absolute error

Validation checks:
1. No ungraded comparisons (CRITICAL)
2. Both models graded
3. Correctness validity
4. Error calculations
5. Closer prediction logic
6. Tie detection accuracy
7. Actual strikeouts bounds
8. Win rate tracking
9. Closer prediction distribution
10. Timestamp validity
11. Data freshness
"""

import sys
import os
import time
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from validation.base_validator import BaseValidator, ValidationResult
import logging

logger = logging.getLogger(__name__)


class MLBShadowModeValidator(BaseValidator):
    """
    Validator for MLB Shadow Mode Predictions table.

    This table compares two model versions:
    - V1.4 (champion): current production model
    - V1.6 (challenger): candidate model being evaluated

    Used for A/B testing model performance before promotion.
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """MLB shadow mode specific validations"""

        logger.info("Running MLB Shadow Mode validations...")

        # Check 1: No ungraded comparisons (CRITICAL)
        self._validate_no_ungraded_comparisons(start_date, end_date)

        # Check 2: Both models graded
        self._validate_both_models_graded(start_date, end_date)

        # Check 3: Correctness validity
        self._validate_correctness_values(start_date, end_date)

        # Check 4: Error calculations
        self._validate_error_calculations(start_date, end_date)

        # Check 5: Closer prediction logic
        self._validate_closer_prediction_logic(start_date, end_date)

        # Check 6: Tie detection accuracy
        self._validate_tie_detection(start_date, end_date)

        # Check 7: Actual strikeouts bounds
        self._validate_strikeouts_bounds(start_date, end_date)

        # Check 8: Win rate tracking
        self._validate_win_rate_tracking(start_date, end_date)

        # Check 9: Closer prediction distribution
        self._validate_closer_distribution(start_date, end_date)

        # Check 10: Timestamp validity
        self._validate_timestamp(start_date, end_date)

        # Check 11: Data freshness
        self._validate_freshness(start_date, end_date)

        logger.info("Completed MLB Shadow Mode validations")

    def _validate_no_ungraded_comparisons(self, start_date: str, end_date: str):
        """Check for completed games without grading (CRITICAL)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            actual_strikeouts,
            v1_4_correct,
            v1_6_correct
        FROM `{self.project_id}.mlb_predictions.shadow_mode_predictions`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND game_date < CURRENT_DATE()  -- Past games only
          AND actual_strikeouts IS NOT NULL  -- Has actual data
          AND (v1_4_correct IS NULL AND v1_6_correct IS NULL)  -- Neither graded
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            ungraded = [(str(row.game_date), row.pitcher_lookup, row.actual_strikeouts) for row in result]

            passed = len(ungraded) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="no_ungraded_comparisons",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="critical" if not passed else "info",
                message=f"Found {len(ungraded)} comparisons with actuals but no grading" if not passed else "All comparisons are graded",
                affected_count=len(ungraded),
                affected_items=ungraded[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed ungraded comparisons validation: {e}")
            self._add_error_result("no_ungraded_comparisons", str(e))

    def _validate_both_models_graded(self, start_date: str, end_date: str):
        """Check that both v1_4 and v1_6 are graded together"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            v1_4_correct,
            v1_6_correct
        FROM `{self.project_id}.mlb_predictions.shadow_mode_predictions`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND actual_strikeouts IS NOT NULL
          AND (
            (v1_4_correct IS NOT NULL AND v1_6_correct IS NULL) OR
            (v1_4_correct IS NULL AND v1_6_correct IS NOT NULL)
          )
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            partial = [(str(row.game_date), row.pitcher_lookup, row.v1_4_correct, row.v1_6_correct) for row in result]

            passed = len(partial) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="both_models_graded",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(partial)} records with only one model graded" if not passed else "All records have both models graded",
                affected_count=len(partial),
                affected_items=partial[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed both models graded validation: {e}")
            self._add_error_result("both_models_graded", str(e))

    def _validate_correctness_values(self, start_date: str, end_date: str):
        """Check that correctness values are valid (TRUE/FALSE/NULL only)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            COUNT(*) as total,
            COUNTIF(v1_4_correct = TRUE) as v1_4_correct_true,
            COUNTIF(v1_4_correct = FALSE) as v1_4_correct_false,
            COUNTIF(v1_4_correct IS NULL) as v1_4_correct_null,
            COUNTIF(v1_6_correct = TRUE) as v1_6_correct_true,
            COUNTIF(v1_6_correct = FALSE) as v1_6_correct_false,
            COUNTIF(v1_6_correct IS NULL) as v1_6_correct_null
        FROM `{self.project_id}.mlb_predictions.shadow_mode_predictions`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        ORDER BY game_date DESC
        LIMIT 20
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))

            invalid = []
            for row in result:
                v1_4_sum = row.v1_4_correct_true + row.v1_4_correct_false + row.v1_4_correct_null
                v1_6_sum = row.v1_6_correct_true + row.v1_6_correct_false + row.v1_6_correct_null
                if v1_4_sum != row.total or v1_6_sum != row.total:
                    invalid.append((str(row.game_date), row.total, v1_4_sum, v1_6_sum))

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
            logger.error(f"Failed correctness validity validation: {e}")
            self._add_error_result("correctness_validity", str(e))

    def _validate_error_calculations(self, start_date: str, end_date: str):
        """Check that error = predicted - actual"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            v1_4_predicted,
            v1_6_predicted,
            actual_strikeouts,
            v1_4_error,
            v1_6_error
        FROM `{self.project_id}.mlb_predictions.shadow_mode_predictions`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND actual_strikeouts IS NOT NULL
          AND v1_4_predicted IS NOT NULL
          AND v1_6_predicted IS NOT NULL
          AND (
            (v1_4_error IS NOT NULL AND ABS(v1_4_error - (v1_4_predicted - actual_strikeouts)) > 0.5) OR
            (v1_6_error IS NOT NULL AND ABS(v1_6_error - (v1_6_predicted - actual_strikeouts)) > 0.5)
          )
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            inconsistent = [
                (str(row.game_date), row.pitcher_lookup, row.v1_4_error, row.v1_6_error)
                for row in result
            ]

            passed = len(inconsistent) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="error_calculations",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(inconsistent)} records with incorrect error calculation" if not passed else "All error calculations are correct",
                affected_count=len(inconsistent),
                affected_items=inconsistent[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed error calculations validation: {e}")
            self._add_error_result("error_calculations", str(e))

    def _validate_closer_prediction_logic(self, start_date: str, end_date: str):
        """Check that closer_prediction matches absolute error comparison"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            v1_4_error,
            v1_6_error,
            closer_prediction
        FROM `{self.project_id}.mlb_predictions.shadow_mode_predictions`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND v1_4_error IS NOT NULL
          AND v1_6_error IS NOT NULL
          AND closer_prediction IS NOT NULL
          AND (
            -- V1.4 should be closer when |v1_4_error| < |v1_6_error|
            (ABS(v1_4_error) < ABS(v1_6_error) AND closer_prediction != 'v1_4') OR
            -- V1.6 should be closer when |v1_6_error| < |v1_4_error|
            (ABS(v1_6_error) < ABS(v1_4_error) AND closer_prediction != 'v1_6') OR
            -- Should be tie when equal
            (ABS(v1_4_error) = ABS(v1_6_error) AND closer_prediction != 'tie')
          )
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            inconsistent = [
                (str(row.game_date), row.pitcher_lookup, row.v1_4_error, row.v1_6_error, row.closer_prediction)
                for row in result
            ]

            passed = len(inconsistent) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="closer_prediction_logic",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(inconsistent)} records with incorrect closer_prediction" if not passed else "All closer_prediction values are correct",
                affected_count=len(inconsistent),
                affected_items=inconsistent[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed closer prediction logic validation: {e}")
            self._add_error_result("closer_prediction_logic", str(e))

    def _validate_tie_detection(self, start_date: str, end_date: str):
        """Check that ties are correctly marked"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            v1_4_error,
            v1_6_error,
            closer_prediction
        FROM `{self.project_id}.mlb_predictions.shadow_mode_predictions`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND v1_4_error IS NOT NULL
          AND v1_6_error IS NOT NULL
          AND ABS(v1_4_error) = ABS(v1_6_error)
          AND closer_prediction != 'tie'
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            missed_ties = [
                (str(row.game_date), row.pitcher_lookup, row.v1_4_error, row.v1_6_error, row.closer_prediction)
                for row in result
            ]

            passed = len(missed_ties) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="tie_detection",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(missed_ties)} equal-error records not marked as tie" if not passed else "All ties are correctly detected",
                affected_count=len(missed_ties),
                affected_items=missed_ties[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed tie detection validation: {e}")
            self._add_error_result("tie_detection", str(e))

    def _validate_strikeouts_bounds(self, start_date: str, end_date: str):
        """Check that actual_strikeouts is in reasonable bounds (0-20)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            actual_strikeouts
        FROM `{self.project_id}.mlb_predictions.shadow_mode_predictions`
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

    def _validate_win_rate_tracking(self, start_date: str, end_date: str):
        """Check win rate difference between models"""

        check_start = time.time()

        query = f"""
        SELECT
            COUNTIF(v1_4_correct = TRUE) as v1_4_wins,
            COUNTIF(v1_4_correct = FALSE) as v1_4_losses,
            COUNTIF(v1_6_correct = TRUE) as v1_6_wins,
            COUNTIF(v1_6_correct = FALSE) as v1_6_losses,
            COUNT(*) as total_graded
        FROM `{self.project_id}.mlb_predictions.shadow_mode_predictions`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND actual_strikeouts IS NOT NULL
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))

            if result and result[0].total_graded > 0:
                row = result[0]
                v1_4_rate = row.v1_4_wins / (row.v1_4_wins + row.v1_4_losses) if (row.v1_4_wins + row.v1_4_losses) > 0 else 0
                v1_6_rate = row.v1_6_wins / (row.v1_6_wins + row.v1_6_losses) if (row.v1_6_wins + row.v1_6_losses) > 0 else 0
                delta = v1_6_rate - v1_4_rate

                passed = True
                message = f"V1.4: {v1_4_rate:.1%}, V1.6: {v1_6_rate:.1%}, Delta: {delta:+.1%}"
                severity = "info"

                # Warning if challenger is significantly worse
                if delta < -0.10:
                    severity = "warning"
                    message += " (V1.6 significantly underperforming)"
            else:
                passed = False
                message = "No graded comparisons found"
                severity = "error"

            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="win_rate_tracking",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity=severity,
                message=message,
                affected_count=0,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed win rate tracking validation: {e}")
            self._add_error_result("win_rate_tracking", str(e))

    def _validate_closer_distribution(self, start_date: str, end_date: str):
        """Check closer_prediction distribution is reasonable"""

        check_start = time.time()

        query = f"""
        SELECT
            closer_prediction,
            COUNT(*) as count
        FROM `{self.project_id}.mlb_predictions.shadow_mode_predictions`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND closer_prediction IS NOT NULL
        GROUP BY closer_prediction
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))

            distribution = {row.closer_prediction: row.count for row in result}
            total = sum(distribution.values())

            if total > 0:
                v1_4_pct = distribution.get('v1_4', 0) / total * 100
                v1_6_pct = distribution.get('v1_6', 0) / total * 100
                tie_pct = distribution.get('tie', 0) / total * 100

                # Check for extreme imbalance (one model >80%)
                passed = max(v1_4_pct, v1_6_pct) < 80
                message = f"V1.4: {v1_4_pct:.1f}%, V1.6: {v1_6_pct:.1f}%, Tie: {tie_pct:.1f}%"
                severity = "info" if passed else "warning"

                if not passed:
                    message += " (significant imbalance)"
            else:
                passed = False
                message = "No closer_prediction data found"
                severity = "error"

            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="closer_prediction_distribution",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity=severity,
                message=message,
                affected_count=0,
                affected_items=[(k, v) for k, v in distribution.items()][:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed closer distribution validation: {e}")
            self._add_error_result("closer_prediction_distribution", str(e))

    def _validate_timestamp(self, start_date: str, end_date: str):
        """Check that graded_at is set when grading is complete"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            v1_4_correct,
            v1_6_correct,
            graded_at
        FROM `{self.project_id}.mlb_predictions.shadow_mode_predictions`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND (v1_4_correct IS NOT NULL OR v1_6_correct IS NOT NULL)
          AND graded_at IS NULL
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            missing_timestamp = [(str(row.game_date), row.pitcher_lookup) for row in result]

            passed = len(missing_timestamp) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="timestamp_validity",
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
            logger.error(f"Failed timestamp validity validation: {e}")
            self._add_error_result("timestamp_validity", str(e))

    def _validate_freshness(self, start_date: str, end_date: str):
        """Check that data is recent enough"""

        check_start = time.time()

        query = f"""
        SELECT
            MAX(game_date) as latest_date,
            DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_stale
        FROM `{self.project_id}.mlb_predictions.shadow_mode_predictions`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))

            if result and result[0].latest_date:
                days_stale = result[0].days_stale
                passed = days_stale <= 2
                message = f"Latest shadow comparison is {days_stale} days old (threshold: 2 days)"
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

    parser = argparse.ArgumentParser(description="Validate MLB Shadow Mode Predictions")
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

    print(f"Validating shadow_mode_predictions from {start_date} to {end_date}")

    validator = MLBShadowModeValidator(
        config_path="validation/configs/grading/mlb_shadow_mode.yaml"
    )

    results = validator.run_validation(start_date, end_date)

    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.check_name}: {result.message}")

    print("=" * 60)
