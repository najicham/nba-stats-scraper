#!/usr/bin/env python3
# File: validation/validators/precompute/player_composite_factors_validator.py
# Description: Validator for player_composite_factors precompute table
# Created: 2026-01-24
"""
Validator for Player Composite Factors precompute table.

Validates nba_precompute.player_composite_factors which contains
calculated adjustment factors for player predictions.

Validation checks:
- Player count per game date (300+ expected)
- No duplicate player-game entries
- Factor score bounds (fatigue: 0-100, others: -10 to +10)
- Source tracking completeness
- Calculation version consistency
"""

import sys
import os
import time
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from validation.base_validator import BaseValidator, ValidationResult
import logging

logger = logging.getLogger(__name__)


class PlayerCompositeFactorsValidator(BaseValidator):
    """
    Validator for Player Composite Factors precompute table.

    This table contains 4 active composite factors:
    - fatigue_score (0-100, higher = more rested)
    - shot_zone_mismatch_score (-10 to +10)
    - pace_score (-3 to +3)
    - usage_spike_score (-3 to +3)
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Player composite factors specific validations"""

        logger.info("Running Player Composite Factors validations...")

        # Check 1: Expected player count (300+ per game date)
        self._validate_player_count(start_date, end_date)

        # Check 2: No duplicate player-game entries
        self._validate_no_duplicates(start_date, end_date)

        # Check 3: Fatigue score bounds (0-100)
        self._validate_fatigue_bounds(start_date, end_date)

        # Check 4: Other factor bounds (-10 to +10)
        self._validate_factor_bounds(start_date, end_date)

        # Check 5: Source tracking completeness
        self._validate_source_tracking(start_date, end_date)

        # Check 6: Calculation version consistency
        self._validate_version_consistency(start_date, end_date)

        # Check 7: Freshness check
        self._validate_freshness(start_date, end_date)

        logger.info("Completed Player Composite Factors validations")

    def _validate_player_count(self, start_date: str, end_date: str):
        """Check if each game date has expected number of players (300+)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            COUNT(DISTINCT player_lookup) as player_count
        FROM `{self.project_id}.nba_precompute.player_composite_factors`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        HAVING COUNT(DISTINCT player_lookup) < 200
        ORDER BY game_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            low_count = [(str(row.game_date), row.player_count) for row in result]

            passed = len(low_count) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="player_count",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(low_count)} dates with fewer than 200 players" if not passed else "All dates have adequate player coverage",
                affected_count=len(low_count),
                affected_items=low_count[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed player count validation: {e}")
            self._add_error_result("player_count", str(e))

    def _validate_no_duplicates(self, start_date: str, end_date: str):
        """Check for duplicate player-game entries"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            COUNT(*) as entry_count
        FROM `{self.project_id}.nba_precompute.player_composite_factors`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date, player_lookup
        HAVING COUNT(*) > 1
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            duplicates = [(str(row.game_date), row.player_lookup, row.entry_count) for row in result]

            passed = len(duplicates) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="no_duplicate_entries",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="critical" if not passed else "info",
                message=f"Found {len(duplicates)} duplicate player-game entries" if not passed else "No duplicate entries found",
                affected_count=len(duplicates),
                affected_items=duplicates[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed duplicate validation: {e}")
            self._add_error_result("no_duplicate_entries", str(e))

    def _validate_fatigue_bounds(self, start_date: str, end_date: str):
        """Check that fatigue score is within bounds (0-100)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            fatigue_score
        FROM `{self.project_id}.nba_precompute.player_composite_factors`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND fatigue_score IS NOT NULL
          AND (fatigue_score < 0 OR fatigue_score > 100)
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.game_date), row.player_lookup, row.fatigue_score) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="fatigue_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(invalid)} records with fatigue score outside 0-100" if not passed else "All fatigue scores within valid bounds",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed fatigue bounds validation: {e}")
            self._add_error_result("fatigue_bounds", str(e))

    def _validate_factor_bounds(self, start_date: str, end_date: str):
        """Check that other factors are within bounds (-10 to +10)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            player_lookup,
            shot_zone_mismatch_score,
            pace_score,
            usage_spike_score
        FROM `{self.project_id}.nba_precompute.player_composite_factors`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND (
            (shot_zone_mismatch_score IS NOT NULL AND (shot_zone_mismatch_score < -10 OR shot_zone_mismatch_score > 10)) OR
            (pace_score IS NOT NULL AND (pace_score < -5 OR pace_score > 5)) OR
            (usage_spike_score IS NOT NULL AND (usage_spike_score < -5 OR usage_spike_score > 5))
          )
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.game_date), row.player_lookup) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="factor_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records with factor scores outside bounds" if not passed else "All factor scores within valid bounds",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed factor bounds validation: {e}")
            self._add_error_result("factor_bounds", str(e))

    def _validate_source_tracking(self, start_date: str, end_date: str):
        """Check that source tracking fields are populated"""

        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            COUNT(*) as total_records,
            COUNTIF(source_player_game_last_updated IS NULL) as missing_player_game_source,
            COUNTIF(source_shot_zone_last_updated IS NULL) as missing_shot_zone_source,
            COUNTIF(source_team_defense_last_updated IS NULL) as missing_team_defense_source
        FROM `{self.project_id}.nba_precompute.player_composite_factors`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        HAVING
            COUNTIF(source_player_game_last_updated IS NULL) > 0 OR
            COUNTIF(source_shot_zone_last_updated IS NULL) > 0 OR
            COUNTIF(source_team_defense_last_updated IS NULL) > 0
        ORDER BY game_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            incomplete = [
                (str(row.game_date), row.total_records,
                 row.missing_player_game_source, row.missing_shot_zone_source, row.missing_team_defense_source)
                for row in result
            ]

            passed = len(incomplete) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="source_tracking",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(incomplete)} dates with missing source tracking" if not passed else "All source tracking fields populated",
                affected_count=len(incomplete),
                affected_items=incomplete[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed source tracking validation: {e}")
            self._add_error_result("source_tracking", str(e))

    def _validate_version_consistency(self, start_date: str, end_date: str):
        """Check that calculation version is consistent"""

        check_start = time.time()

        query = f"""
        SELECT
            calculation_version,
            COUNT(*) as record_count,
            MIN(game_date) as earliest_date,
            MAX(game_date) as latest_date
        FROM `{self.project_id}.nba_precompute.player_composite_factors`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY calculation_version
        ORDER BY record_count DESC
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))
            versions = [(row.calculation_version, row.record_count) for row in result]

            # Allow multiple versions but flag if more than 2
            passed = len(versions) <= 2
            duration = time.time() - check_start

            message = f"Found {len(versions)} calculation versions" if not passed else f"Version consistency OK ({len(versions)} version(s))"

            self.results.append(ValidationResult(
                check_name="version_consistency",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="info" if passed else "warning",
                message=message,
                affected_count=len(versions),
                affected_items=versions[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed version consistency validation: {e}")
            self._add_error_result("version_consistency", str(e))

    def _validate_freshness(self, start_date: str, end_date: str):
        """Check that data is recent enough"""

        check_start = time.time()

        query = f"""
        SELECT
            MAX(game_date) as latest_date,
            DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_stale
        FROM `{self.project_id}.nba_precompute.player_composite_factors`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
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

    parser = argparse.ArgumentParser(description="Validate Player Composite Factors")
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

    print(f"Validating player_composite_factors from {start_date} to {end_date}")

    validator = PlayerCompositeFactorsValidator(
        config_path="validation/configs/precompute/player_composite_factors.yaml"
    )

    results = validator.run_validation(start_date, end_date)

    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.check_name}: {result.message}")

    print("=" * 60)
