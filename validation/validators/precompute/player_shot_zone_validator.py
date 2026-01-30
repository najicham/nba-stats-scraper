#!/usr/bin/env python3
# File: validation/validators/precompute/player_shot_zone_validator.py
# Description: Validator for player_shot_zone_analysis precompute table
# Created: 2026-01-24
"""
Validator for Player Shot Zone Analysis precompute table.

Validates nba_precompute.player_shot_zone_analysis which contains
player shot distribution and efficiency by court zone.

Validation checks:
- Player count (400+ active players expected)
- No duplicate player-date entries
- Shot zone rates sum to ~100%
- Percentage bounds (0-100 for rates, 0-1 for efficiency)
- Primary scoring zone validity
- Sample quality alignment with games
"""

import sys
import os
import time
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from validation.base_validator import BaseValidator, ValidationResult
import logging

logger = logging.getLogger(__name__)


class PlayerShotZoneValidator(BaseValidator):
    """
    Validator for Player Shot Zone Analysis precompute table.

    This table contains player shooting patterns by zone,
    used for shot zone mismatch calculations in composite factors.
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Player shot zone specific validations"""

        logger.info("Running Player Shot Zone Analysis validations...")

        # Check 1: Expected player count (400+ active players)
        self._validate_player_count(start_date, end_date)

        # Check 2: No duplicate player-date entries
        self._validate_no_duplicates(start_date, end_date)

        # Check 3: Shot zone rates sum to approximately 100%
        self._validate_zone_rate_sum(start_date, end_date)

        # Check 4: Percentage bounds
        self._validate_percentage_bounds(start_date, end_date)

        # Check 5: Primary scoring zone validity
        self._validate_primary_zone(start_date, end_date)

        # Check 6: Sample quality matches game count
        self._validate_sample_quality(start_date, end_date)

        # Check 7: Freshness check
        self._validate_freshness(start_date, end_date)

        # Check 8: Domain-specific range validation (NEW - Session 38)
        self._validate_domain_specific_ranges(start_date, end_date)

        logger.info("Completed Player Shot Zone Analysis validations")

    def _validate_player_count(self, start_date: str, end_date: str):
        """Check if each date has expected number of players (400+)"""

        check_start = time.time()

        query = f"""
        SELECT
            analysis_date,
            COUNT(DISTINCT player_lookup) as player_count
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date >= '{start_date}'
          AND analysis_date <= '{end_date}'
        GROUP BY analysis_date
        HAVING COUNT(DISTINCT player_lookup) < 300
        ORDER BY analysis_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            low_count = [(str(row.analysis_date), row.player_count) for row in result]

            passed = len(low_count) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="player_count",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(low_count)} dates with fewer than 300 players" if not passed else "All dates have adequate player coverage",
                affected_count=len(low_count),
                affected_items=low_count[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed player count validation: {e}")
            self._add_error_result("player_count", str(e))

    def _validate_no_duplicates(self, start_date: str, end_date: str):
        """Check for duplicate player-date entries"""

        check_start = time.time()

        query = f"""
        SELECT
            analysis_date,
            player_lookup,
            COUNT(*) as entry_count
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date >= '{start_date}'
          AND analysis_date <= '{end_date}'
        GROUP BY analysis_date, player_lookup
        HAVING COUNT(*) > 1
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            duplicates = [(str(row.analysis_date), row.player_lookup, row.entry_count) for row in result]

            passed = len(duplicates) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="no_duplicate_entries",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="critical" if not passed else "info",
                message=f"Found {len(duplicates)} duplicate player-date entries" if not passed else "No duplicate entries found",
                affected_count=len(duplicates),
                affected_items=duplicates[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed duplicate validation: {e}")
            self._add_error_result("no_duplicate_entries", str(e))

    def _validate_zone_rate_sum(self, start_date: str, end_date: str):
        """Check that shot zone rates sum to approximately 100%"""

        check_start = time.time()

        query = f"""
        SELECT
            analysis_date,
            player_lookup,
            paint_rate_last_10,
            mid_range_rate_last_10,
            three_pt_rate_last_10,
            (paint_rate_last_10 + mid_range_rate_last_10 + three_pt_rate_last_10) as total_rate
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date >= '{start_date}'
          AND analysis_date <= '{end_date}'
          AND paint_rate_last_10 IS NOT NULL
          AND mid_range_rate_last_10 IS NOT NULL
          AND three_pt_rate_last_10 IS NOT NULL
          AND ABS((paint_rate_last_10 + mid_range_rate_last_10 + three_pt_rate_last_10) - 100) > 2
        ORDER BY analysis_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.analysis_date), row.player_lookup, round(row.total_rate, 2)) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="zone_rate_sum",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records with zone rates not summing to 100% (+/-2%)" if not passed else "All zone rates sum correctly",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed zone rate sum validation: {e}")
            self._add_error_result("zone_rate_sum", str(e))

    def _validate_percentage_bounds(self, start_date: str, end_date: str):
        """Check that percentages are within valid bounds"""

        check_start = time.time()

        query = f"""
        SELECT
            analysis_date,
            player_lookup,
            paint_rate_last_10,
            mid_range_rate_last_10,
            three_pt_rate_last_10,
            paint_pct_last_10,
            mid_range_pct_last_10,
            three_pt_pct_last_10
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date >= '{start_date}'
          AND analysis_date <= '{end_date}'
          AND (
            -- Rates should be 0-100
            paint_rate_last_10 < 0 OR paint_rate_last_10 > 100 OR
            mid_range_rate_last_10 < 0 OR mid_range_rate_last_10 > 100 OR
            three_pt_rate_last_10 < 0 OR three_pt_rate_last_10 > 100 OR
            -- Efficiencies should be 0-1.5 (TS% can exceed 1.0)
            paint_pct_last_10 < 0 OR paint_pct_last_10 > 1.5 OR
            mid_range_pct_last_10 < 0 OR mid_range_pct_last_10 > 1.5 OR
            three_pt_pct_last_10 < 0 OR three_pt_pct_last_10 > 1.5
          )
        ORDER BY analysis_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.analysis_date), row.player_lookup) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="percentage_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(invalid)} records with percentages outside valid bounds" if not passed else "All percentages within valid bounds",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed percentage bounds validation: {e}")
            self._add_error_result("percentage_bounds", str(e))

    def _validate_primary_zone(self, start_date: str, end_date: str):
        """Check that primary scoring zone is valid"""

        check_start = time.time()

        valid_zones = ['paint', 'mid_range', 'perimeter', 'balanced']
        zones_list = "', '".join(valid_zones)

        query = f"""
        SELECT
            analysis_date,
            player_lookup,
            primary_scoring_zone
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date >= '{start_date}'
          AND analysis_date <= '{end_date}'
          AND primary_scoring_zone IS NOT NULL
          AND primary_scoring_zone NOT IN ('{zones_list}')
        ORDER BY analysis_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.analysis_date), row.player_lookup, row.primary_scoring_zone) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="primary_zone_validity",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(invalid)} records with invalid primary scoring zone" if not passed else "All primary zones are valid",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed primary zone validation: {e}")
            self._add_error_result("primary_zone_validity", str(e))

    def _validate_sample_quality(self, start_date: str, end_date: str):
        """Check that sample quality aligns with games in sample"""

        check_start = time.time()

        query = f"""
        SELECT
            analysis_date,
            player_lookup,
            games_in_sample_10,
            sample_quality_10
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date >= '{start_date}'
          AND analysis_date <= '{end_date}'
          AND (
            -- Games in sample should be 0-10
            games_in_sample_10 < 0 OR games_in_sample_10 > 10 OR
            -- Sample quality validation
            (games_in_sample_10 >= 8 AND sample_quality_10 = 'insufficient') OR
            (games_in_sample_10 <= 2 AND sample_quality_10 = 'excellent')
          )
        ORDER BY analysis_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.analysis_date), row.player_lookup, row.games_in_sample_10, row.sample_quality_10) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="sample_quality",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records with mismatched sample quality" if not passed else "Sample quality aligned with game counts",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed sample quality validation: {e}")
            self._add_error_result("sample_quality", str(e))

    def _validate_freshness(self, start_date: str, end_date: str):
        """Check that data is recent enough"""

        check_start = time.time()

        query = f"""
        SELECT
            MAX(analysis_date) as latest_date,
            DATE_DIFF(CURRENT_DATE(), MAX(analysis_date), DAY) as days_stale
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date >= '{start_date}'
          AND analysis_date <= '{end_date}'
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))

            if result and result[0].latest_date:
                days_stale = result[0].days_stale
                passed = days_stale <= 7
                message = f"Latest data is {days_stale} days old (threshold: 7 days)"
                severity = "info" if days_stale <= 2 else ("warning" if days_stale <= 7 else "error")
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

    def _validate_domain_specific_ranges(self, start_date: str, end_date: str):
        """
        Validate shot zone percentages match basketball domain expectations.

        Added in Session 38 to catch the January 2026 feature drift where:
        - paint_rate dropped from 40% to 20% (should be 20-60%)
        - three_pt_rate spiked to 70% (should be 15-55%)

        These bounds are based on NBA shooting patterns:
        - Paint (restricted area + paint): typically 25-55%
        - Mid-range: typically 5-35%
        - Three-point: typically 15-55%
        """
        check_start = time.time()

        # Domain bounds based on NBA shooting patterns
        # Widened slightly to avoid false positives but catch extreme anomalies
        query = f"""
        SELECT
            analysis_date,
            player_lookup,
            paint_rate_last_10,
            mid_range_rate_last_10,
            three_pt_rate_last_10,
            CASE
                WHEN paint_rate_last_10 < 15 THEN 'paint_too_low'
                WHEN paint_rate_last_10 > 65 THEN 'paint_too_high'
                WHEN mid_range_rate_last_10 < 3 THEN 'mid_too_low'
                WHEN mid_range_rate_last_10 > 40 THEN 'mid_too_high'
                WHEN three_pt_rate_last_10 < 10 THEN 'three_too_low'
                WHEN three_pt_rate_last_10 > 60 THEN 'three_too_high'
                ELSE 'unknown'
            END as violation_type
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date >= '{start_date}'
          AND analysis_date <= '{end_date}'
          AND (
            -- Paint should be 15-65% (widened from typical 25-55%)
            paint_rate_last_10 < 15 OR paint_rate_last_10 > 65 OR
            -- Mid-range should be 3-40% (widened from typical 10-30%)
            mid_range_rate_last_10 < 3 OR mid_range_rate_last_10 > 40 OR
            -- Three-point should be 10-60% (widened from typical 20-50%)
            three_pt_rate_last_10 < 10 OR three_pt_rate_last_10 > 60
          )
        ORDER BY analysis_date DESC
        LIMIT 100
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            violations = [
                (str(row.analysis_date), row.player_lookup, row.violation_type,
                 f"paint={row.paint_rate_last_10:.1f}%, mid={row.mid_range_rate_last_10:.1f}%, three={row.three_pt_rate_last_10:.1f}%")
                for row in result
            ]

            # Group by violation type for summary
            violation_counts = {}
            for v in violations:
                vtype = v[2]
                violation_counts[vtype] = violation_counts.get(vtype, 0) + 1

            passed = len(violations) == 0
            duration = time.time() - check_start

            # Determine severity based on count
            # >50 violations is critical (systemic issue like Jan 2026)
            # 10-50 is warning (some players with unusual patterns)
            # <10 is acceptable (edge cases)
            if len(violations) > 50:
                severity = "critical"
            elif len(violations) > 10:
                severity = "warning"
            else:
                severity = "info"

            message = (
                f"Found {len(violations)} records with domain-specific violations: {violation_counts}"
                if not passed
                else "All shot zone rates within expected basketball ranges (paint 15-65%, mid 3-40%, three 10-60%)"
            )

            self.results.append(ValidationResult(
                check_name="domain_specific_ranges",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity=severity if not passed else "info",
                message=message,
                affected_count=len(violations),
                affected_items=violations[:15],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed domain-specific ranges validation: {e}")
            self._add_error_result("domain_specific_ranges", str(e))

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

    parser = argparse.ArgumentParser(description="Validate Player Shot Zone Analysis")
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

    print(f"Validating player_shot_zone_analysis from {start_date} to {end_date}")

    validator = PlayerShotZoneValidator(
        config_path="validation/configs/precompute/player_shot_zone_analysis.yaml"
    )

    results = validator.validate(start_date, end_date)

    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.check_name}: {result.message}")

    print("=" * 60)
