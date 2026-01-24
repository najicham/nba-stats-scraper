#!/usr/bin/env python3
# File: validation/validators/precompute/player_daily_cache_validator.py
# Description: Validator for player_daily_cache precompute table
# Created: 2026-01-24
"""
Validator for Player Daily Cache precompute table.

Validates nba_precompute.player_daily_cache which caches static daily
player data for prediction optimization.

Validation checks:
- Player count per cache date (50-500 expected)
- No duplicate player-date entries
- Performance metric bounds
- 4-window completeness (last_5, last_10, last_7_days, last_14_days)
- Source tracking completeness (4 sources)
- Early season flag alignment
- Production readiness validation
"""

import sys
import os
import time
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from validation.base_validator import BaseValidator, ValidationResult
import logging

logger = logging.getLogger(__name__)


class PlayerDailyCacheValidator(BaseValidator):
    """
    Validator for Player Daily Cache precompute table.

    This table caches 40+ fields per player per day including:
    - Performance metrics (points, minutes, ts%)
    - Fatigue metrics
    - Team context
    - Shot zone data (from upstream)
    - 4 source tracking fields
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Player daily cache specific validations"""

        logger.info("Running Player Daily Cache validations...")

        # Check 1: Expected player count (50-500 per date)
        self._validate_player_count(start_date, end_date)

        # Check 2: No duplicate player-date entries
        self._validate_no_duplicates(start_date, end_date)

        # Check 3: Performance metric bounds
        self._validate_performance_bounds(start_date, end_date)

        # Check 4: Minutes bounds (0-48)
        self._validate_minutes_bounds(start_date, end_date)

        # Check 5: Window completeness
        self._validate_window_completeness(start_date, end_date)

        # Check 6: Source tracking completeness
        self._validate_source_tracking(start_date, end_date)

        # Check 7: Early season flag alignment
        self._validate_early_season_flags(start_date, end_date)

        # Check 8: Production readiness
        self._validate_production_readiness(start_date, end_date)

        # Check 9: Freshness check
        self._validate_freshness(start_date, end_date)

        logger.info("Completed Player Daily Cache validations")

    def _validate_player_count(self, start_date: str, end_date: str):
        """Check if each cache date has expected player count (50-500)"""

        check_start = time.time()

        query = f"""
        SELECT
            cache_date,
            COUNT(DISTINCT player_lookup) as player_count
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date >= '{start_date}'
          AND cache_date <= '{end_date}'
        GROUP BY cache_date
        HAVING COUNT(DISTINCT player_lookup) < 50 OR COUNT(DISTINCT player_lookup) > 600
        ORDER BY cache_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            outliers = [(str(row.cache_date), row.player_count) for row in result]

            passed = len(outliers) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="player_count",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(outliers)} dates with player count outside 50-600 range" if not passed else "All dates have expected player counts",
                affected_count=len(outliers),
                affected_items=outliers[:10],
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
            cache_date,
            player_lookup,
            COUNT(*) as entry_count
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date >= '{start_date}'
          AND cache_date <= '{end_date}'
        GROUP BY cache_date, player_lookup
        HAVING COUNT(*) > 1
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            duplicates = [(str(row.cache_date), row.player_lookup, row.entry_count) for row in result]

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

    def _validate_performance_bounds(self, start_date: str, end_date: str):
        """Check that performance metrics are within valid bounds"""

        check_start = time.time()

        query = f"""
        SELECT
            cache_date,
            player_lookup,
            points_avg_last_10,
            ts_pct_last_10,
            games_played_season
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date >= '{start_date}'
          AND cache_date <= '{end_date}'
          AND (
            (points_avg_last_10 IS NOT NULL AND (points_avg_last_10 < 0 OR points_avg_last_10 > 60)) OR
            (ts_pct_last_10 IS NOT NULL AND (ts_pct_last_10 < 0 OR ts_pct_last_10 > 1.5)) OR
            (games_played_season IS NOT NULL AND (games_played_season < 0 OR games_played_season > 82))
          )
        ORDER BY cache_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.cache_date), row.player_lookup) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="performance_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(invalid)} records with performance metrics outside bounds" if not passed else "All performance metrics within valid bounds",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed performance bounds validation: {e}")
            self._add_error_result("performance_bounds", str(e))

    def _validate_minutes_bounds(self, start_date: str, end_date: str):
        """Check that minutes are within valid bounds (0-48)"""

        check_start = time.time()

        query = f"""
        SELECT
            cache_date,
            player_lookup,
            minutes_avg_last_10
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date >= '{start_date}'
          AND cache_date <= '{end_date}'
          AND minutes_avg_last_10 IS NOT NULL
          AND (minutes_avg_last_10 < 0 OR minutes_avg_last_10 > 53)  -- OT can push above 48
        ORDER BY cache_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.cache_date), row.player_lookup, row.minutes_avg_last_10) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="minutes_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records with minutes outside 0-53 range" if not passed else "All minutes within valid bounds",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed minutes bounds validation: {e}")
            self._add_error_result("minutes_bounds", str(e))

    def _validate_window_completeness(self, start_date: str, end_date: str):
        """Check that all 4 time windows have data where expected"""

        check_start = time.time()

        query = f"""
        SELECT
            cache_date,
            COUNT(*) as total_records,
            COUNTIF(games_in_last_5 IS NULL) as missing_last_5,
            COUNTIF(games_in_last_10 IS NULL) as missing_last_10,
            COUNTIF(games_in_last_7_days IS NULL) as missing_last_7_days,
            COUNTIF(games_in_last_14_days IS NULL) as missing_last_14_days
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date >= '{start_date}'
          AND cache_date <= '{end_date}'
        GROUP BY cache_date
        HAVING
            COUNTIF(games_in_last_5 IS NULL) > total_records * 0.2 OR
            COUNTIF(games_in_last_10 IS NULL) > total_records * 0.2
        ORDER BY cache_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            incomplete = [
                (str(row.cache_date), row.total_records, row.missing_last_5, row.missing_last_10)
                for row in result
            ]

            passed = len(incomplete) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="window_completeness",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(incomplete)} dates with >20% missing window data" if not passed else "All windows have adequate coverage",
                affected_count=len(incomplete),
                affected_items=incomplete[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed window completeness validation: {e}")
            self._add_error_result("window_completeness", str(e))

    def _validate_source_tracking(self, start_date: str, end_date: str):
        """Check that all 4 source tracking fields are populated"""

        check_start = time.time()

        query = f"""
        SELECT
            cache_date,
            COUNT(*) as total_records,
            COUNTIF(source_player_game_last_updated IS NULL) as missing_player_game,
            COUNTIF(source_composite_last_updated IS NULL) as missing_composite,
            COUNTIF(source_shot_zones_last_updated IS NULL) as missing_shot_zones,
            COUNTIF(source_team_defense_last_updated IS NULL) as missing_team_defense
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date >= '{start_date}'
          AND cache_date <= '{end_date}'
        GROUP BY cache_date
        HAVING
            COUNTIF(source_player_game_last_updated IS NULL) > 0 OR
            COUNTIF(source_composite_last_updated IS NULL) > 0 OR
            COUNTIF(source_shot_zones_last_updated IS NULL) > 0 OR
            COUNTIF(source_team_defense_last_updated IS NULL) > 0
        ORDER BY cache_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            incomplete = [
                (str(row.cache_date), row.total_records,
                 row.missing_player_game, row.missing_composite,
                 row.missing_shot_zones, row.missing_team_defense)
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
                message=f"Found {len(incomplete)} dates with missing source tracking" if not passed else "All 4 source tracking fields populated",
                affected_count=len(incomplete),
                affected_items=incomplete[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed source tracking validation: {e}")
            self._add_error_result("source_tracking", str(e))

    def _validate_early_season_flags(self, start_date: str, end_date: str):
        """Check that early season flags are properly set"""

        check_start = time.time()

        query = f"""
        SELECT
            cache_date,
            player_lookup,
            games_played_season,
            early_season_flag
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date >= '{start_date}'
          AND cache_date <= '{end_date}'
          AND (
            -- Should be flagged if <10 games but isn't
            (games_played_season IS NOT NULL AND games_played_season < 10 AND early_season_flag = FALSE) OR
            -- Should not be flagged if 10+ games but is
            (games_played_season IS NOT NULL AND games_played_season >= 10 AND early_season_flag = TRUE)
          )
        ORDER BY cache_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            misaligned = [(str(row.cache_date), row.player_lookup, row.games_played_season, row.early_season_flag) for row in result]

            passed = len(misaligned) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="early_season_flags",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(misaligned)} records with misaligned early season flags" if not passed else "All early season flags properly set",
                affected_count=len(misaligned),
                affected_items=misaligned[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed early season flag validation: {e}")
            self._add_error_result("early_season_flags", str(e))

    def _validate_production_readiness(self, start_date: str, end_date: str):
        """Check production readiness rate"""

        check_start = time.time()

        query = f"""
        SELECT
            cache_date,
            COUNT(*) as total_records,
            COUNTIF(is_production_ready = TRUE) as production_ready,
            COUNTIF(is_production_ready = FALSE) as not_ready,
            ROUND(COUNTIF(is_production_ready = TRUE) * 100.0 / COUNT(*), 2) as ready_pct
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date >= '{start_date}'
          AND cache_date <= '{end_date}'
        GROUP BY cache_date
        HAVING ROUND(COUNTIF(is_production_ready = TRUE) * 100.0 / COUNT(*), 2) < 70
        ORDER BY cache_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            low_readiness = [
                (str(row.cache_date), row.total_records, row.production_ready, row.ready_pct)
                for row in result
            ]

            passed = len(low_readiness) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="production_readiness",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(low_readiness)} dates with <70% production ready records" if not passed else "All dates have adequate production readiness",
                affected_count=len(low_readiness),
                affected_items=low_readiness[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed production readiness validation: {e}")
            self._add_error_result("production_readiness", str(e))

    def _validate_freshness(self, start_date: str, end_date: str):
        """Check that data is recent enough"""

        check_start = time.time()

        query = f"""
        SELECT
            MAX(cache_date) as latest_date,
            DATE_DIFF(CURRENT_DATE(), MAX(cache_date), DAY) as days_stale
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date >= '{start_date}'
          AND cache_date <= '{end_date}'
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

    parser = argparse.ArgumentParser(description="Validate Player Daily Cache")
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

    print(f"Validating player_daily_cache from {start_date} to {end_date}")

    validator = PlayerDailyCacheValidator(
        config_path="validation/configs/precompute/player_daily_cache.yaml"
    )

    results = validator.run_validation(start_date, end_date)

    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.check_name}: {result.message}")

    print("=" * 60)
