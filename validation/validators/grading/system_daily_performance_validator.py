#!/usr/bin/env python3
# File: validation/validators/grading/system_daily_performance_validator.py
# Description: Validator for system_daily_performance grading table
# Created: 2026-01-24
"""
Validator for System Daily Performance table.

Validates nba_predictions.system_daily_performance which contains
aggregated prediction accuracy metrics by (game_date, system_id).

This is the second-level grading validator:
- Depends on prediction_accuracy upstream
- Used by Phase 6 export for daily reports
- Business key: (game_date, system_id)

Validation checks:
1. No duplicate business keys (CRITICAL)
2. One record per system per date
3. Win rate bounds (0-1)
4. Volume consistency (recommendations <= predictions)
5. Correct count logic
6. OVER + UNDER = recommendations
7. Percentage metrics bounds
8. Confidence bounds
9. Source data alignment
10. System coverage (all 5 systems)
11. High confidence subset logic
12. Data freshness
"""

import sys
import os
import time
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from validation.base_validator import BaseValidator, ValidationResult
import logging

logger = logging.getLogger(__name__)


class SystemDailyPerformanceValidator(BaseValidator):
    """
    Validator for System Daily Performance grading table.

    This table contains daily aggregated metrics per prediction system:
    - Volume metrics (predictions, recommendations, correct counts)
    - Win rates (overall, OVER-only, UNDER-only)
    - Accuracy (MAE, avg_bias, within_3_pct, within_5_pct)
    - Confidence analysis (avg_confidence, high_confidence_win_rate)
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
        """System daily performance specific validations"""

        logger.info("Running System Daily Performance validations...")

        # Check 1: No duplicate business keys (CRITICAL)
        self._validate_no_duplicates(start_date, end_date)

        # Check 2: One record per system per date
        self._validate_record_count(start_date, end_date)

        # Check 3: Win rate bounds (0-1)
        self._validate_win_rate_bounds(start_date, end_date)

        # Check 4: Volume consistency
        self._validate_volume_consistency(start_date, end_date)

        # Check 5: Correct count logic
        self._validate_correct_count_logic(start_date, end_date)

        # Check 6: OVER + UNDER = recommendations
        self._validate_over_under_sum(start_date, end_date)

        # Check 7: Percentage metrics bounds
        self._validate_percentage_bounds(start_date, end_date)

        # Check 8: Confidence bounds
        self._validate_confidence_bounds(start_date, end_date)

        # Check 9: Source data alignment with prediction_accuracy
        self._validate_source_alignment(start_date, end_date)

        # Check 10: System coverage (all 5 systems per date)
        self._validate_system_coverage(start_date, end_date)

        # Check 11: High confidence subset logic
        self._validate_high_confidence_logic(start_date, end_date)

        # Check 12: Data freshness
        self._validate_freshness(start_date, end_date)

        logger.info("Completed System Daily Performance validations")

    def _validate_no_duplicates(self, start_date: str, end_date: str):
        """Check for duplicate business keys (game_date, system_id)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            system_id,
            COUNT(*) as entry_count
        FROM `{self.project_id}.nba_predictions.system_daily_performance`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date, system_id
        HAVING COUNT(*) > 1
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            duplicates = [(str(row.game_date), row.system_id, row.entry_count) for row in result]

            passed = len(duplicates) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="no_duplicate_business_keys",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="critical" if not passed else "info",
                message=f"Found {len(duplicates)} duplicate (game_date, system_id) keys" if not passed else "No duplicate business keys found",
                affected_count=len(duplicates),
                affected_items=duplicates[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed duplicate validation: {e}")
            self._add_error_result("no_duplicate_business_keys", str(e))

    def _validate_record_count(self, start_date: str, end_date: str):
        """Check that we have exactly 5 records per date (one per system)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            COUNT(*) as system_count
        FROM `{self.project_id}.nba_predictions.system_daily_performance`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        HAVING COUNT(*) != 5
        ORDER BY game_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            incorrect = [(str(row.game_date), row.system_count) for row in result]

            passed = len(incorrect) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="record_count_per_date",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(incorrect)} dates without exactly 5 system records" if not passed else "All dates have exactly 5 system records",
                affected_count=len(incorrect),
                affected_items=incorrect[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed record count validation: {e}")
            self._add_error_result("record_count_per_date", str(e))

    def _validate_win_rate_bounds(self, start_date: str, end_date: str):
        """Check that win rates are in 0-1 range"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            system_id,
            win_rate,
            over_win_rate,
            under_win_rate
        FROM `{self.project_id}.nba_predictions.system_daily_performance`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND (
            (win_rate IS NOT NULL AND (win_rate < 0 OR win_rate > 1)) OR
            (over_win_rate IS NOT NULL AND (over_win_rate < 0 OR over_win_rate > 1)) OR
            (under_win_rate IS NOT NULL AND (under_win_rate < 0 OR under_win_rate > 1))
          )
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.game_date), row.system_id, row.win_rate) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="win_rate_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(invalid)} records with win rates outside 0-1 range" if not passed else "All win rates within valid bounds",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed win rate bounds validation: {e}")
            self._add_error_result("win_rate_bounds", str(e))

    def _validate_volume_consistency(self, start_date: str, end_date: str):
        """Check that recommendations_count <= predictions_count"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            system_id,
            predictions_count,
            recommendations_count
        FROM `{self.project_id}.nba_predictions.system_daily_performance`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND recommendations_count > predictions_count
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.game_date), row.system_id, row.predictions_count, row.recommendations_count) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="volume_consistency",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records where recommendations > predictions" if not passed else "Volume consistency OK",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed volume consistency validation: {e}")
            self._add_error_result("volume_consistency", str(e))

    def _validate_correct_count_logic(self, start_date: str, end_date: str):
        """Check that correct_count <= recommendations_count"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            system_id,
            recommendations_count,
            correct_count
        FROM `{self.project_id}.nba_predictions.system_daily_performance`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND correct_count > recommendations_count
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.game_date), row.system_id, row.correct_count, row.recommendations_count) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="correct_count_logic",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records where correct_count > recommendations_count" if not passed else "Correct count logic OK",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed correct count logic validation: {e}")
            self._add_error_result("correct_count_logic", str(e))

    def _validate_over_under_sum(self, start_date: str, end_date: str):
        """Check that over_count + under_count = recommendations_count"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            system_id,
            recommendations_count,
            over_count,
            under_count,
            (COALESCE(over_count, 0) + COALESCE(under_count, 0)) as sum_count
        FROM `{self.project_id}.nba_predictions.system_daily_performance`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND recommendations_count IS NOT NULL
          AND ABS(recommendations_count - COALESCE(over_count, 0) - COALESCE(under_count, 0)) > 1
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [
                (str(row.game_date), row.system_id, row.recommendations_count, row.sum_count)
                for row in result
            ]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="over_under_sum",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records where OVER + UNDER != recommendations" if not passed else "OVER + UNDER = recommendations OK",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed over/under sum validation: {e}")
            self._add_error_result("over_under_sum", str(e))

    def _validate_percentage_bounds(self, start_date: str, end_date: str):
        """Check that percentage metrics (within_3_pct, within_5_pct) are in 0-1 range"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            system_id,
            within_3_pct,
            within_5_pct
        FROM `{self.project_id}.nba_predictions.system_daily_performance`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND (
            (within_3_pct IS NOT NULL AND (within_3_pct < 0 OR within_3_pct > 1)) OR
            (within_5_pct IS NOT NULL AND (within_5_pct < 0 OR within_5_pct > 1))
          )
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.game_date), row.system_id, row.within_3_pct, row.within_5_pct) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="percentage_metrics_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records with percentage metrics outside 0-1 range" if not passed else "All percentage metrics within valid bounds",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed percentage bounds validation: {e}")
            self._add_error_result("percentage_metrics_bounds", str(e))

    def _validate_confidence_bounds(self, start_date: str, end_date: str):
        """Check that confidence metrics are in valid ranges"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            system_id,
            avg_confidence,
            high_confidence_win_rate
        FROM `{self.project_id}.nba_predictions.system_daily_performance`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND (
            (avg_confidence IS NOT NULL AND (avg_confidence < 0 OR avg_confidence > 1)) OR
            (high_confidence_win_rate IS NOT NULL AND (high_confidence_win_rate < 0 OR high_confidence_win_rate > 1))
          )
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.game_date), row.system_id, row.avg_confidence) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="confidence_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records with confidence metrics outside 0-1 range" if not passed else "All confidence metrics within valid bounds",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed confidence bounds validation: {e}")
            self._add_error_result("confidence_bounds", str(e))

    def _validate_source_alignment(self, start_date: str, end_date: str):
        """Check that summary totals roughly match prediction_accuracy source"""

        check_start = time.time()

        query = f"""
        WITH source_counts AS (
            SELECT
                game_date,
                system_id,
                COUNT(*) as source_predictions
            FROM `{self.project_id}.nba_predictions.prediction_accuracy`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
            GROUP BY game_date, system_id
        ),
        summary_counts AS (
            SELECT
                game_date,
                system_id,
                predictions_count
            FROM `{self.project_id}.nba_predictions.system_daily_performance`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
        )
        SELECT
            s.game_date,
            s.system_id,
            s.predictions_count as summary_count,
            c.source_predictions,
            ABS(s.predictions_count - c.source_predictions) as diff
        FROM summary_counts s
        JOIN source_counts c USING (game_date, system_id)
        WHERE ABS(s.predictions_count - c.source_predictions) > 5
        ORDER BY s.game_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            misaligned = [
                (str(row.game_date), row.system_id, row.summary_count, row.source_predictions)
                for row in result
            ]

            passed = len(misaligned) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="source_data_alignment",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(misaligned)} records where summary differs from source by >5" if not passed else "Summary aligns with source prediction_accuracy",
                affected_count=len(misaligned),
                affected_items=misaligned[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed source alignment validation: {e}")
            self._add_error_result("source_data_alignment", str(e))

    def _validate_system_coverage(self, start_date: str, end_date: str):
        """Check that all 5 expected systems are present each date"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            ARRAY_AGG(DISTINCT system_id) as systems_present,
            COUNT(DISTINCT system_id) as system_count
        FROM `{self.project_id}.nba_predictions.system_daily_performance`
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
                message=f"Found {len(incomplete)} dates missing prediction systems (expected 5)" if not passed else "All 5 prediction systems present each date",
                affected_count=len(incomplete),
                affected_items=incomplete[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed system coverage validation: {e}")
            self._add_error_result("system_coverage", str(e))

    def _validate_high_confidence_logic(self, start_date: str, end_date: str):
        """Check high confidence subset logic (should have data if avg_confidence exists)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            system_id,
            avg_confidence,
            high_confidence_win_rate
        FROM `{self.project_id}.nba_predictions.system_daily_performance`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND avg_confidence IS NOT NULL
          AND avg_confidence > 0.5
          AND high_confidence_win_rate IS NULL
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            missing = [(str(row.game_date), row.system_id, row.avg_confidence) for row in result]

            passed = len(missing) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="high_confidence_subset_logic",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="info" if not passed else "info",
                message=f"Found {len(missing)} records with high avg_confidence but no high_confidence_win_rate" if not passed else "High confidence subset logic OK",
                affected_count=len(missing),
                affected_items=missing[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed high confidence logic validation: {e}")
            self._add_error_result("high_confidence_subset_logic", str(e))

    def _validate_freshness(self, start_date: str, end_date: str):
        """Check that data is recent enough"""

        check_start = time.time()

        query = f"""
        SELECT
            MAX(game_date) as latest_date,
            DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_stale
        FROM `{self.project_id}.nba_predictions.system_daily_performance`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))

            if result and result[0].latest_date:
                days_stale = result[0].days_stale
                passed = days_stale <= 2
                message = f"Latest daily summary is {days_stale} days old (threshold: 2 days)"
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

    parser = argparse.ArgumentParser(description="Validate System Daily Performance")
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

    print(f"Validating system_daily_performance from {start_date} to {end_date}")

    validator = SystemDailyPerformanceValidator(
        config_path="validation/configs/grading/system_daily_performance.yaml"
    )

    results = validator.run_validation(start_date, end_date)

    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.check_name}: {result.message}")

    print("=" * 60)
