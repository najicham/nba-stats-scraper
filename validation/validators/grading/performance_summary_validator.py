#!/usr/bin/env python3
# File: validation/validators/grading/performance_summary_validator.py
# Description: Validator for prediction_performance_summary grading table
# Created: 2026-01-24
"""
Validator for Prediction Performance Summary table.

Validates nba_predictions.prediction_performance_summary which contains
pre-computed multi-dimensional summary slices for API optimization.

Dimensions:
- Player: individual player or NULL for aggregate
- Archetype: veteran_star, prime_star, young_star, ironman, role_player
- Confidence tier: high (>=70%), medium (55-69%), low (<55%)
- Situation: bounce_back, home, away, rest_3plus, b2b

Period types:
- rolling_7d, rolling_30d, month, season

Business key: summary_key (composite of all dimensions)

Validation checks:
1. Summary key uniqueness (CRITICAL)
2. No duplicate summary keys
3. Period value formats
4. Period date bounds
5. Hit rate bounds (0-1)
6. Win rate consistency (hits / total_recommendations)
7. Over/Under split bounds
8. Volume consistency
9. Archetype values
10. Confidence tier bounds
11. Situation values
12. Unique counts bounds
13. Data hash populated
14. Data freshness
"""

import sys
import os
import time
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from validation.base_validator import BaseValidator, ValidationResult
import logging

logger = logging.getLogger(__name__)


class PerformanceSummaryValidator(BaseValidator):
    """
    Validator for Prediction Performance Summary table.

    This table contains pre-computed aggregations sliced by:
    - System ID (5 prediction systems)
    - Period type (rolling_7d, rolling_30d, month, season)
    - Player, archetype, confidence tier, situation dimensions
    """

    VALID_PERIOD_TYPES = ['rolling_7d', 'rolling_30d', 'month', 'season']
    VALID_ARCHETYPES = ['veteran_star', 'prime_star', 'young_star', 'ironman', 'role_player']
    VALID_CONFIDENCE_TIERS = ['high', 'medium', 'low']
    VALID_SITUATIONS = ['bounce_back', 'home', 'away', 'rest_3plus', 'b2b']

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Performance summary specific validations"""

        logger.info("Running Performance Summary validations...")

        # Check 1: Summary key uniqueness (CRITICAL)
        self._validate_summary_key_uniqueness(start_date, end_date)

        # Check 2: No duplicate summary keys per computation
        self._validate_no_duplicates(start_date, end_date)

        # Check 3: Period value formats
        self._validate_period_formats(start_date, end_date)

        # Check 4: Period date bounds
        self._validate_period_date_bounds(start_date, end_date)

        # Check 5: Hit rate bounds (0-1)
        self._validate_hit_rate_bounds(start_date, end_date)

        # Check 6: Win rate consistency
        self._validate_win_rate_consistency(start_date, end_date)

        # Check 7: Over/Under split bounds
        self._validate_over_under_bounds(start_date, end_date)

        # Check 8: Volume consistency
        self._validate_volume_consistency(start_date, end_date)

        # Check 9: Archetype values
        self._validate_archetype_values(start_date, end_date)

        # Check 10: Confidence tier bounds
        self._validate_confidence_tier_values(start_date, end_date)

        # Check 11: Situation values
        self._validate_situation_values(start_date, end_date)

        # Check 12: Unique counts bounds
        self._validate_unique_counts(start_date, end_date)

        # Check 13: Data hash populated
        self._validate_data_hash(start_date, end_date)

        # Check 14: Data freshness
        self._validate_freshness(start_date, end_date)

        logger.info("Completed Performance Summary validations")

    def _validate_summary_key_uniqueness(self, start_date: str, end_date: str):
        """Check that summary_key is unique within same computation"""

        check_start = time.time()

        query = f"""
        SELECT
            summary_key,
            DATE(computed_at) as compute_date,
            COUNT(*) as entry_count
        FROM `{self.project_id}.nba_predictions.prediction_performance_summary`
        WHERE DATE(computed_at) >= '{start_date}'
          AND DATE(computed_at) <= '{end_date}'
        GROUP BY summary_key, DATE(computed_at)
        HAVING COUNT(*) > 1
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            duplicates = [(row.summary_key[:50], str(row.compute_date), row.entry_count) for row in result]

            passed = len(duplicates) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="summary_key_uniqueness",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="critical" if not passed else "info",
                message=f"Found {len(duplicates)} duplicate summary keys" if not passed else "All summary keys are unique",
                affected_count=len(duplicates),
                affected_items=duplicates[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed summary key uniqueness validation: {e}")
            self._add_error_result("summary_key_uniqueness", str(e))

    def _validate_no_duplicates(self, start_date: str, end_date: str):
        """Check for duplicate summary keys across computations"""

        check_start = time.time()

        query = f"""
        SELECT
            summary_key,
            COUNT(DISTINCT DATE(computed_at)) as compute_dates,
            COUNT(*) as total_entries
        FROM `{self.project_id}.nba_predictions.prediction_performance_summary`
        WHERE DATE(computed_at) >= '{start_date}'
          AND DATE(computed_at) <= '{end_date}'
        GROUP BY summary_key
        HAVING COUNT(*) > COUNT(DISTINCT DATE(computed_at))
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            duplicates = [(row.summary_key[:50], row.compute_dates, row.total_entries) for row in result]

            passed = len(duplicates) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="no_duplicate_entries",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(duplicates)} summary keys with duplicate entries" if not passed else "No duplicate entries found",
                affected_count=len(duplicates),
                affected_items=duplicates[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed duplicate validation: {e}")
            self._add_error_result("no_duplicate_entries", str(e))

    def _validate_period_formats(self, start_date: str, end_date: str):
        """Check that period_value formats match period_type"""

        check_start = time.time()

        query = f"""
        SELECT
            period_type,
            period_value,
            COUNT(*) as record_count
        FROM `{self.project_id}.nba_predictions.prediction_performance_summary`
        WHERE DATE(computed_at) >= '{start_date}'
          AND DATE(computed_at) <= '{end_date}'
          AND (
            -- rolling periods should be YYYY-MM-DD
            (period_type IN ('rolling_7d', 'rolling_30d') AND NOT REGEXP_CONTAINS(period_value, r'^\\d{{4}}-\\d{{2}}-\\d{{2}}$')) OR
            -- month should be YYYY-MM
            (period_type = 'month' AND NOT REGEXP_CONTAINS(period_value, r'^\\d{{4}}-\\d{{2}}$')) OR
            -- season should be YYYY-YY
            (period_type = 'season' AND NOT REGEXP_CONTAINS(period_value, r'^\\d{{4}}-\\d{{2}}$'))
          )
        GROUP BY period_type, period_value
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(row.period_type, row.period_value, row.record_count) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="period_value_formats",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(invalid)} records with invalid period_value format" if not passed else "All period values have correct format",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed period format validation: {e}")
            self._add_error_result("period_value_formats", str(e))

    def _validate_period_date_bounds(self, start_date: str, end_date: str):
        """Check that period_start_date <= period_end_date"""

        check_start = time.time()

        query = f"""
        SELECT
            summary_key,
            period_type,
            period_start_date,
            period_end_date
        FROM `{self.project_id}.nba_predictions.prediction_performance_summary`
        WHERE DATE(computed_at) >= '{start_date}'
          AND DATE(computed_at) <= '{end_date}'
          AND period_start_date IS NOT NULL
          AND period_end_date IS NOT NULL
          AND period_start_date > period_end_date
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(row.period_type, str(row.period_start_date), str(row.period_end_date)) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="period_date_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(invalid)} records where start_date > end_date" if not passed else "All period date bounds are valid",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed period date bounds validation: {e}")
            self._add_error_result("period_date_bounds", str(e))

    def _validate_hit_rate_bounds(self, start_date: str, end_date: str):
        """Check that hit_rate is in 0-1 range"""

        check_start = time.time()

        query = f"""
        SELECT
            summary_key,
            hit_rate,
            over_hit_rate,
            under_hit_rate
        FROM `{self.project_id}.nba_predictions.prediction_performance_summary`
        WHERE DATE(computed_at) >= '{start_date}'
          AND DATE(computed_at) <= '{end_date}'
          AND (
            (hit_rate IS NOT NULL AND (hit_rate < 0 OR hit_rate > 1)) OR
            (over_hit_rate IS NOT NULL AND (over_hit_rate < 0 OR over_hit_rate > 1)) OR
            (under_hit_rate IS NOT NULL AND (under_hit_rate < 0 OR under_hit_rate > 1))
          )
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(row.summary_key[:40], row.hit_rate, row.over_hit_rate, row.under_hit_rate) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="hit_rate_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(invalid)} records with hit rates outside 0-1 range" if not passed else "All hit rates within valid bounds",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed hit rate bounds validation: {e}")
            self._add_error_result("hit_rate_bounds", str(e))

    def _validate_win_rate_consistency(self, start_date: str, end_date: str):
        """Check that hit_rate = hits / total_recommendations"""

        check_start = time.time()

        query = f"""
        SELECT
            summary_key,
            hits,
            total_recommendations,
            hit_rate,
            SAFE_DIVIDE(hits, total_recommendations) as calculated_rate
        FROM `{self.project_id}.nba_predictions.prediction_performance_summary`
        WHERE DATE(computed_at) >= '{start_date}'
          AND DATE(computed_at) <= '{end_date}'
          AND total_recommendations > 0
          AND hit_rate IS NOT NULL
          AND ABS(hit_rate - SAFE_DIVIDE(hits, total_recommendations)) > 0.01
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            inconsistent = [(row.summary_key[:40], row.hit_rate, row.calculated_rate) for row in result]

            passed = len(inconsistent) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="win_rate_consistency",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(inconsistent)} records with inconsistent hit_rate calculation" if not passed else "All hit rates are consistent",
                affected_count=len(inconsistent),
                affected_items=inconsistent[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed win rate consistency validation: {e}")
            self._add_error_result("win_rate_consistency", str(e))

    def _validate_over_under_bounds(self, start_date: str, end_date: str):
        """Check over/under hit rate bounds"""

        check_start = time.time()

        query = f"""
        SELECT
            summary_key,
            over_recommendations,
            under_recommendations,
            total_recommendations
        FROM `{self.project_id}.nba_predictions.prediction_performance_summary`
        WHERE DATE(computed_at) >= '{start_date}'
          AND DATE(computed_at) <= '{end_date}'
          AND total_recommendations IS NOT NULL
          AND (over_recommendations + under_recommendations) > total_recommendations + 1
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [
                (row.summary_key[:40], row.over_recommendations, row.under_recommendations, row.total_recommendations)
                for row in result
            ]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="over_under_bounds",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records where OVER + UNDER > total" if not passed else "Over/Under counts are valid",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed over/under bounds validation: {e}")
            self._add_error_result("over_under_bounds", str(e))

    def _validate_volume_consistency(self, start_date: str, end_date: str):
        """Check that hits + misses <= total_recommendations"""

        check_start = time.time()

        query = f"""
        SELECT
            summary_key,
            hits,
            misses,
            total_recommendations
        FROM `{self.project_id}.nba_predictions.prediction_performance_summary`
        WHERE DATE(computed_at) >= '{start_date}'
          AND DATE(computed_at) <= '{end_date}'
          AND total_recommendations IS NOT NULL
          AND (COALESCE(hits, 0) + COALESCE(misses, 0)) > total_recommendations + 1
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(row.summary_key[:40], row.hits, row.misses, row.total_recommendations) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="volume_consistency",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records where hits + misses > total" if not passed else "Volume counts are consistent",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed volume consistency validation: {e}")
            self._add_error_result("volume_consistency", str(e))

    def _validate_archetype_values(self, start_date: str, end_date: str):
        """Check that archetype values are valid"""

        check_start = time.time()

        valid_archetypes = "', '".join(self.VALID_ARCHETYPES)
        query = f"""
        SELECT
            archetype,
            COUNT(*) as record_count
        FROM `{self.project_id}.nba_predictions.prediction_performance_summary`
        WHERE DATE(computed_at) >= '{start_date}'
          AND DATE(computed_at) <= '{end_date}'
          AND archetype IS NOT NULL
          AND archetype NOT IN ('{valid_archetypes}')
        GROUP BY archetype
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(row.archetype, row.record_count) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="archetype_values",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(invalid)} invalid archetype values" if not passed else "All archetype values are valid",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed archetype values validation: {e}")
            self._add_error_result("archetype_values", str(e))

    def _validate_confidence_tier_values(self, start_date: str, end_date: str):
        """Check that confidence_tier values are valid"""

        check_start = time.time()

        valid_tiers = "', '".join(self.VALID_CONFIDENCE_TIERS)
        query = f"""
        SELECT
            confidence_tier,
            COUNT(*) as record_count
        FROM `{self.project_id}.nba_predictions.prediction_performance_summary`
        WHERE DATE(computed_at) >= '{start_date}'
          AND DATE(computed_at) <= '{end_date}'
          AND confidence_tier IS NOT NULL
          AND confidence_tier NOT IN ('{valid_tiers}')
        GROUP BY confidence_tier
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(row.confidence_tier, row.record_count) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="confidence_tier_values",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(invalid)} invalid confidence_tier values" if not passed else "All confidence tiers are valid",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed confidence tier validation: {e}")
            self._add_error_result("confidence_tier_values", str(e))

    def _validate_situation_values(self, start_date: str, end_date: str):
        """Check that situation values are valid"""

        check_start = time.time()

        valid_situations = "', '".join(self.VALID_SITUATIONS)
        query = f"""
        SELECT
            situation,
            COUNT(*) as record_count
        FROM `{self.project_id}.nba_predictions.prediction_performance_summary`
        WHERE DATE(computed_at) >= '{start_date}'
          AND DATE(computed_at) <= '{end_date}'
          AND situation IS NOT NULL
          AND situation NOT IN ('{valid_situations}')
        GROUP BY situation
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(row.situation, row.record_count) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="situation_values",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} invalid situation values" if not passed else "All situation values are valid",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed situation values validation: {e}")
            self._add_error_result("situation_values", str(e))

    def _validate_unique_counts(self, start_date: str, end_date: str):
        """Check that unique_players and unique_games are positive"""

        check_start = time.time()

        query = f"""
        SELECT
            summary_key,
            unique_players,
            unique_games,
            total_predictions
        FROM `{self.project_id}.nba_predictions.prediction_performance_summary`
        WHERE DATE(computed_at) >= '{start_date}'
          AND DATE(computed_at) <= '{end_date}'
          AND total_predictions > 0
          AND (
            (unique_players IS NOT NULL AND unique_players <= 0) OR
            (unique_games IS NOT NULL AND unique_games <= 0)
          )
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(row.summary_key[:40], row.unique_players, row.unique_games) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="unique_counts_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records with non-positive unique counts" if not passed else "All unique counts are positive",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed unique counts validation: {e}")
            self._add_error_result("unique_counts_bounds", str(e))

    def _validate_data_hash(self, start_date: str, end_date: str):
        """Check that data_hash is populated for idempotency"""

        check_start = time.time()

        query = f"""
        SELECT
            DATE(computed_at) as compute_date,
            COUNT(*) as total_records,
            COUNTIF(data_hash IS NULL OR data_hash = '') as missing_hash
        FROM `{self.project_id}.nba_predictions.prediction_performance_summary`
        WHERE DATE(computed_at) >= '{start_date}'
          AND DATE(computed_at) <= '{end_date}'
        GROUP BY DATE(computed_at)
        HAVING COUNTIF(data_hash IS NULL OR data_hash = '') > 0
        ORDER BY compute_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            missing = [(str(row.compute_date), row.total_records, row.missing_hash) for row in result]

            passed = len(missing) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="data_hash_populated",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(missing)} dates with missing data hashes" if not passed else "All records have data hashes",
                affected_count=len(missing),
                affected_items=missing[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed data hash validation: {e}")
            self._add_error_result("data_hash_populated", str(e))

    def _validate_freshness(self, start_date: str, end_date: str):
        """Check that data is recent enough"""

        check_start = time.time()

        query = f"""
        SELECT
            MAX(computed_at) as latest_computed,
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(computed_at), HOUR) as hours_stale
        FROM `{self.project_id}.nba_predictions.prediction_performance_summary`
        WHERE DATE(computed_at) >= '{start_date}'
          AND DATE(computed_at) <= '{end_date}'
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))

            if result and result[0].latest_computed:
                hours_stale = result[0].hours_stale
                passed = hours_stale <= 24
                message = f"Latest summary computed {hours_stale} hours ago (threshold: 24 hours)"
                severity = "info" if hours_stale <= 12 else ("warning" if hours_stale <= 24 else "error")
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

    parser = argparse.ArgumentParser(description="Validate Performance Summary")
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

    print(f"Validating prediction_performance_summary from {start_date} to {end_date}")

    validator = PerformanceSummaryValidator(
        config_path="validation/configs/grading/performance_summary.yaml"
    )

    results = validator.run_validation(start_date, end_date)

    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.check_name}: {result.message}")

    print("=" * 60)
