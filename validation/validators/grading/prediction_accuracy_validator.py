#!/usr/bin/env python3
# File: validation/validators/grading/prediction_accuracy_validator.py
# Description: Validator for prediction_accuracy grading table
# Created: 2026-01-24
"""
Validator for NBA Prediction Accuracy table.

Validates nba_predictions.prediction_accuracy which contains
graded predictions with actual results and accuracy metrics.

This is the foundation for all grading layer validation:
- Drives downstream tables (system_daily_performance, performance_summary)
- Contains 45+ fields with complex validation requirements
- Business key: (player_lookup, game_id, system_id, line_value)

Validation checks:
1. No duplicate business keys (CRITICAL)
2. Core metrics populated (absolute_error, signed_error, prediction_correct)
3. Error value bounds (0-80 for absolute, -80 to +80 for signed)
4. Confidence score normalization (0-1)
5. Confidence decile alignment (1-10)
6. Voiding logic consistency
7. DNP detection accuracy
8. Margin calculation validity
9. Recommendation correctness
10. Line source consistency
11. Volume per system
12. Within-N-points consistency
13. System coverage (all 5 systems)
14. Missing actuals detection
15. Data freshness
"""

import sys
import os
import time
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from validation.base_validator import BaseValidator, ValidationResult
import logging

logger = logging.getLogger(__name__)


class PredictionAccuracyValidator(BaseValidator):
    """
    Validator for NBA Prediction Accuracy grading table.

    This table contains graded predictions with:
    - Accuracy metrics (absolute_error, signed_error)
    - Betting evaluation (prediction_correct, margins)
    - DNP voiding (is_voided, void_reason)
    - Confidence calibration (confidence_score, confidence_decile)
    """

    EXPECTED_SYSTEMS = [
        'moving_average_baseline_v1',
        'zone_matchup_v1',
        'similarity_balanced_v1',
        'xgboost_v1',
        'meta_ensemble_v1'
    ]

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Prediction accuracy specific validations"""

        logger.info("Running Prediction Accuracy validations...")

        # Check 1: No duplicate business keys (CRITICAL)
        self._validate_no_duplicates(start_date, end_date)

        # Check 2: Core metrics populated
        self._validate_core_metrics(start_date, end_date)

        # Check 3: Error value bounds
        self._validate_error_bounds(start_date, end_date)

        # Check 4: Confidence score normalization (0-1)
        self._validate_confidence_score(start_date, end_date)

        # Check 5: Confidence decile alignment (1-10)
        self._validate_confidence_decile(start_date, end_date)

        # Check 6: Voiding logic consistency
        self._validate_voiding_logic(start_date, end_date)

        # Check 7: DNP detection accuracy
        self._validate_dnp_detection(start_date, end_date)

        # Check 8: Margin calculation validity
        self._validate_margin_calculations(start_date, end_date)

        # Check 9: Recommendation correctness logic
        self._validate_recommendation_logic(start_date, end_date)

        # Check 10: Line source consistency
        self._validate_line_source(start_date, end_date)

        # Check 11: Volume per system per date
        self._validate_volume_per_system(start_date, end_date)

        # Check 12: Within-N-points consistency
        self._validate_within_points_consistency(start_date, end_date)

        # Check 13: System coverage (all 5 systems)
        self._validate_system_coverage(start_date, end_date)

        # Check 14: Missing actuals detection
        self._validate_missing_actuals(start_date, end_date)

        # Check 15: Data freshness
        self._validate_freshness(start_date, end_date)

        logger.info("Completed Prediction Accuracy validations")

    def _validate_no_duplicates(self, start_date: str, end_date: str):
        """Check for duplicate business keys (CRITICAL)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            game_id,
            system_id,
            CAST(COALESCE(line_value, -1) AS INT64) as line_value,
            COUNT(*) as entry_count
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date, player_lookup, game_id, system_id, CAST(COALESCE(line_value, -1) AS INT64)
        HAVING COUNT(*) > 1
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            duplicates = [
                (str(row.game_date), row.player_lookup, row.system_id, row.entry_count)
                for row in result
            ]

            passed = len(duplicates) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="no_duplicate_business_keys",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="critical" if not passed else "info",
                message=f"Found {len(duplicates)} duplicate business keys (race condition evidence)" if not passed else "No duplicate business keys found",
                affected_count=len(duplicates),
                affected_items=duplicates[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed duplicate validation: {e}")
            self._add_error_result("no_duplicate_business_keys", str(e))

    def _validate_core_metrics(self, start_date: str, end_date: str):
        """Check that core metrics are populated for non-voided predictions"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            system_id,
            absolute_error,
            signed_error
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND COALESCE(is_voided, FALSE) = FALSE
          AND (
            absolute_error IS NULL OR
            signed_error IS NULL
          )
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            missing = [(str(row.game_date), row.player_lookup, row.system_id) for row in result]

            passed = len(missing) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="core_metrics_populated",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(missing)} non-voided records missing core metrics" if not passed else "All non-voided records have core metrics",
                affected_count=len(missing),
                affected_items=missing[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed core metrics validation: {e}")
            self._add_error_result("core_metrics_populated", str(e))

    def _validate_error_bounds(self, start_date: str, end_date: str):
        """Check that error values are within expected bounds"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            system_id,
            absolute_error,
            signed_error
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND (
            -- Absolute error should be 0-80 (max realistic points swing)
            (absolute_error IS NOT NULL AND (absolute_error < 0 OR absolute_error > 80)) OR
            -- Signed error should be -80 to +80
            (signed_error IS NOT NULL AND (signed_error < -80 OR signed_error > 80))
          )
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            out_of_bounds = [
                (str(row.game_date), row.player_lookup, row.absolute_error, row.signed_error)
                for row in result
            ]

            passed = len(out_of_bounds) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="error_value_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(out_of_bounds)} records with error values outside bounds (0-80)" if not passed else "All error values within expected bounds",
                affected_count=len(out_of_bounds),
                affected_items=out_of_bounds[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed error bounds validation: {e}")
            self._add_error_result("error_value_bounds", str(e))

    def _validate_confidence_score(self, start_date: str, end_date: str):
        """Check that confidence scores are normalized to 0-1 range"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            system_id,
            confidence_score
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND confidence_score IS NOT NULL
          AND (confidence_score < 0 OR confidence_score > 1)
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.game_date), row.player_lookup, row.confidence_score) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="confidence_score_normalized",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records with confidence scores outside 0-1 range" if not passed else "All confidence scores properly normalized",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed confidence score validation: {e}")
            self._add_error_result("confidence_score_normalized", str(e))

    def _validate_confidence_decile(self, start_date: str, end_date: str):
        """Check that confidence deciles are in 1-10 range"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            system_id,
            confidence_decile
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND confidence_decile IS NOT NULL
          AND (confidence_decile < 1 OR confidence_decile > 10)
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.game_date), row.player_lookup, row.confidence_decile) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="confidence_decile_range",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records with confidence deciles outside 1-10 range" if not passed else "All confidence deciles in valid range",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed confidence decile validation: {e}")
            self._add_error_result("confidence_decile_range", str(e))

    def _validate_voiding_logic(self, start_date: str, end_date: str):
        """Check that voiding logic is consistent (is_voided implies void_reason)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            system_id,
            is_voided,
            void_reason
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND is_voided = TRUE
          AND (void_reason IS NULL OR void_reason = '')
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            inconsistent = [(str(row.game_date), row.player_lookup, row.system_id) for row in result]

            passed = len(inconsistent) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="voiding_logic_consistency",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(inconsistent)} voided records without void_reason" if not passed else "All voided records have void_reason",
                affected_count=len(inconsistent),
                affected_items=inconsistent[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed voiding logic validation: {e}")
            self._add_error_result("voiding_logic_consistency", str(e))

    def _validate_dnp_detection(self, start_date: str, end_date: str):
        """Check that players with 0 actual points are properly voided"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            system_id,
            actual_points,
            minutes_played,
            is_voided
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND actual_points = 0
          AND COALESCE(minutes_played, 0) = 0
          AND COALESCE(is_voided, FALSE) = FALSE
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            unvoided_dnp = [(str(row.game_date), row.player_lookup, row.system_id) for row in result]

            passed = len(unvoided_dnp) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="dnp_detection_accuracy",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(unvoided_dnp)} DNP records (0 pts, 0 min) not marked as voided" if not passed else "All DNP records properly voided",
                affected_count=len(unvoided_dnp),
                affected_items=unvoided_dnp[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed DNP detection validation: {e}")
            self._add_error_result("dnp_detection_accuracy", str(e))

    def _validate_margin_calculations(self, start_date: str, end_date: str):
        """Check that margin calculations are mathematically correct"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            system_id,
            predicted_points,
            actual_points,
            line_value,
            predicted_margin,
            actual_margin
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND line_value IS NOT NULL
          AND predicted_points IS NOT NULL
          AND actual_points IS NOT NULL
          AND (
            -- predicted_margin should equal predicted_points - line_value
            (predicted_margin IS NOT NULL AND ABS(predicted_margin - (predicted_points - line_value)) > 0.1) OR
            -- actual_margin should equal actual_points - line_value
            (actual_margin IS NOT NULL AND ABS(actual_margin - (actual_points - line_value)) > 0.1)
          )
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.game_date), row.player_lookup, row.predicted_margin, row.actual_margin) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="margin_calculation_validity",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records with incorrect margin calculations" if not passed else "All margin calculations are valid",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed margin calculation validation: {e}")
            self._add_error_result("margin_calculation_validity", str(e))

    def _validate_recommendation_logic(self, start_date: str, end_date: str):
        """Check that PASS/HOLD/NO_LINE recommendations have NULL prediction_correct"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            system_id,
            recommendation,
            prediction_correct
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND recommendation IN ('PASS', 'HOLD', 'NO_LINE')
          AND prediction_correct IS NOT NULL
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.game_date), row.player_lookup, row.recommendation) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="recommendation_correctness_logic",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} PASS/HOLD/NO_LINE records with non-NULL prediction_correct" if not passed else "All non-actionable recommendations have NULL prediction_correct",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed recommendation logic validation: {e}")
            self._add_error_result("recommendation_correctness_logic", str(e))

    def _validate_line_source(self, start_date: str, end_date: str):
        """Check line source consistency"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            COUNT(*) as total_records,
            COUNTIF(line_value IS NULL) as no_line,
            COUNTIF(line_value IS NOT NULL) as has_line
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        HAVING COUNTIF(line_value IS NULL) > COUNTIF(line_value IS NOT NULL) * 0.5
        ORDER BY game_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            low_coverage = [(str(row.game_date), row.no_line, row.has_line) for row in result]

            passed = len(low_coverage) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="line_source_consistency",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="info" if not passed else "info",
                message=f"Found {len(low_coverage)} dates with >50% missing line values" if not passed else "Line coverage is adequate",
                affected_count=len(low_coverage),
                affected_items=low_coverage[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed line source validation: {e}")
            self._add_error_result("line_source_consistency", str(e))

    def _validate_volume_per_system(self, start_date: str, end_date: str):
        """Check that each system has adequate predictions per date (50+)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            system_id,
            COUNT(*) as prediction_count
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date, system_id
        HAVING COUNT(*) < 30
        ORDER BY game_date DESC, prediction_count ASC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            low_volume = [(str(row.game_date), row.system_id, row.prediction_count) for row in result]

            passed = len(low_volume) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="volume_per_system",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(low_volume)} system-date combinations with <30 predictions" if not passed else "All systems have adequate volume",
                affected_count=len(low_volume),
                affected_items=low_volume[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed volume validation: {e}")
            self._add_error_result("volume_per_system", str(e))

    def _validate_within_points_consistency(self, start_date: str, end_date: str):
        """Check that within_3_points implies within_5_points"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            system_id,
            within_3_points,
            within_5_points,
            absolute_error
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND within_3_points = TRUE
          AND within_5_points = FALSE
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            inconsistent = [(str(row.game_date), row.player_lookup, row.absolute_error) for row in result]

            passed = len(inconsistent) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="within_points_consistency",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="info" if not passed else "info",
                message=f"Found {len(inconsistent)} records where within_3 but not within_5 (logic error)" if not passed else "Within-N-points consistency OK",
                affected_count=len(inconsistent),
                affected_items=inconsistent[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed within-points consistency validation: {e}")
            self._add_error_result("within_points_consistency", str(e))

    def _validate_system_coverage(self, start_date: str, end_date: str):
        """Check that all 5 expected systems are present"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            ARRAY_AGG(DISTINCT system_id) as systems_present,
            COUNT(DISTINCT system_id) as system_count
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        HAVING COUNT(DISTINCT system_id) < 5
        ORDER BY game_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            incomplete = [(str(row.game_date), row.system_count) for row in result]

            passed = len(incomplete) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="system_coverage",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(incomplete)} dates missing systems (expected 5)" if not passed else "All 5 prediction systems present",
                affected_count=len(incomplete),
                affected_items=incomplete[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed system coverage validation: {e}")
            self._add_error_result("system_coverage", str(e))

    def _validate_missing_actuals(self, start_date: str, end_date: str):
        """Check for predictions without actual results (should be minimal)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            COUNT(*) as total_predictions,
            COUNTIF(actual_points IS NULL) as missing_actuals,
            ROUND(COUNTIF(actual_points IS NULL) * 100.0 / COUNT(*), 2) as missing_pct
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        HAVING ROUND(COUNTIF(actual_points IS NULL) * 100.0 / COUNT(*), 2) > 5
        ORDER BY game_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            high_missing = [(str(row.game_date), row.missing_actuals, row.missing_pct) for row in result]

            passed = len(high_missing) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="missing_actuals_detection",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(high_missing)} dates with >5% missing actual results" if not passed else "All dates have <5% missing actuals",
                affected_count=len(high_missing),
                affected_items=high_missing[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed missing actuals validation: {e}")
            self._add_error_result("missing_actuals_detection", str(e))

    def _validate_freshness(self, start_date: str, end_date: str):
        """Check that data is recent enough"""

        check_start = time.time()

        query = f"""
        SELECT
            MAX(game_date) as latest_date,
            DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_stale
        FROM `{self.project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))

            if result and result[0].latest_date:
                days_stale = result[0].days_stale
                passed = days_stale <= 3
                message = f"Latest graded data is {days_stale} days old (threshold: 3 days)"
                severity = "info" if days_stale <= 1 else ("warning" if days_stale <= 3 else "error")
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

    parser = argparse.ArgumentParser(description="Validate Prediction Accuracy")
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

    print(f"Validating prediction_accuracy from {start_date} to {end_date}")

    validator = PredictionAccuracyValidator(
        config_path="validation/configs/grading/prediction_accuracy.yaml"
    )

    results = validator.run_validation(start_date, end_date)

    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.check_name}: {result.message}")

    print("=" * 60)
