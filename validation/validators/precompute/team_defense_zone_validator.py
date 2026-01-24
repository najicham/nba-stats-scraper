#!/usr/bin/env python3
# File: validation/validators/precompute/team_defense_zone_validator.py
# Description: Validator for team_defense_zone_analysis precompute table
# Created: 2026-01-24
"""
Validator for Team Defense Zone Analysis precompute table.

Validates nba_precompute.team_defense_zone_analysis which aggregates
team defensive performance by court zone (paint, mid-range, three-point).

Validation checks:
- Team count (should be 30 NBA teams per date)
- No duplicate team entries
- Defensive percentage bounds (0-1.0)
- Zone coverage completeness
- Freshness (analysis_date recent)
"""

import sys
import os
import time
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from validation.base_validator import BaseValidator, ValidationResult
import logging

logger = logging.getLogger(__name__)


class TeamDefenseZoneValidator(BaseValidator):
    """
    Validator for Team Defense Zone Analysis precompute table.

    This table contains team defensive efficiency by zone,
    used by player_shot_zone_analysis for matchup calculations.
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Team defense zone specific validations"""

        logger.info("Running Team Defense Zone Analysis validations...")

        # Check 1: Expected team count (30 NBA teams)
        self._validate_team_count(start_date, end_date)

        # Check 2: No duplicate team-date entries
        self._validate_no_duplicates(start_date, end_date)

        # Check 3: Defensive percentages in valid range (0-1.0)
        self._validate_percentage_bounds(start_date, end_date)

        # Check 4: Zone coverage (all zones have data)
        self._validate_zone_coverage(start_date, end_date)

        # Check 5: Freshness check
        self._validate_freshness(start_date, end_date)

        # Check 6: Team abbreviation validity
        self._validate_team_abbreviations(start_date, end_date)

        logger.info("Completed Team Defense Zone Analysis validations")

    def _validate_team_count(self, start_date: str, end_date: str):
        """Check if each date has expected number of teams (30)"""

        check_start = time.time()

        query = f"""
        SELECT
            analysis_date,
            COUNT(DISTINCT team_abbr) as team_count
        FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
        WHERE analysis_date >= '{start_date}'
          AND analysis_date <= '{end_date}'
        GROUP BY analysis_date
        HAVING COUNT(DISTINCT team_abbr) < 30
        ORDER BY analysis_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            incomplete = [(str(row.analysis_date), row.team_count) for row in result]

            passed = len(incomplete) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="team_count",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(incomplete)} dates with fewer than 30 teams" if not passed else "All dates have 30 teams",
                affected_count=len(incomplete),
                affected_items=incomplete[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed team count validation: {e}")
            self._add_error_result("team_count", str(e))

    def _validate_no_duplicates(self, start_date: str, end_date: str):
        """Check for duplicate team-date entries"""

        check_start = time.time()

        query = f"""
        SELECT
            analysis_date,
            team_abbr,
            COUNT(*) as entry_count
        FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
        WHERE analysis_date >= '{start_date}'
          AND analysis_date <= '{end_date}'
        GROUP BY analysis_date, team_abbr
        HAVING COUNT(*) > 1
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            duplicates = [(str(row.analysis_date), row.team_abbr, row.entry_count) for row in result]

            passed = len(duplicates) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="no_duplicate_entries",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="critical" if not passed else "info",
                message=f"Found {len(duplicates)} duplicate team-date entries" if not passed else "No duplicate entries found",
                affected_count=len(duplicates),
                affected_items=duplicates[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed duplicate validation: {e}")
            self._add_error_result("no_duplicate_entries", str(e))

    def _validate_percentage_bounds(self, start_date: str, end_date: str):
        """Check that defensive percentages are within valid range (0-1.0)"""

        check_start = time.time()

        query = f"""
        SELECT
            analysis_date,
            team_abbr,
            paint_pct_allowed_last_15,
            mid_range_pct_allowed,
            three_pt_pct_allowed
        FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
        WHERE analysis_date >= '{start_date}'
          AND analysis_date <= '{end_date}'
          AND (
            paint_pct_allowed_last_15 < 0 OR paint_pct_allowed_last_15 > 1.0 OR
            mid_range_pct_allowed < 0 OR mid_range_pct_allowed > 1.0 OR
            three_pt_pct_allowed < 0 OR three_pt_pct_allowed > 1.0
          )
        ORDER BY analysis_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(str(row.analysis_date), row.team_abbr) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="percentage_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(invalid)} records with percentages outside 0-1.0 range" if not passed else "All percentages within valid bounds",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed percentage bounds validation: {e}")
            self._add_error_result("percentage_bounds", str(e))

    def _validate_zone_coverage(self, start_date: str, end_date: str):
        """Check that all defensive zones have data"""

        check_start = time.time()

        query = f"""
        SELECT
            analysis_date,
            team_abbr,
            paint_pct_allowed_last_15,
            mid_range_pct_allowed,
            three_pt_pct_allowed,
            weakest_zone,
            strongest_zone
        FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
        WHERE analysis_date >= '{start_date}'
          AND analysis_date <= '{end_date}'
          AND (
            paint_pct_allowed_last_15 IS NULL OR
            mid_range_pct_allowed IS NULL OR
            three_pt_pct_allowed IS NULL OR
            weakest_zone IS NULL OR
            strongest_zone IS NULL
          )
        ORDER BY analysis_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            incomplete = [(str(row.analysis_date), row.team_abbr) for row in result]

            passed = len(incomplete) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="zone_coverage",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(incomplete)} records with missing zone data" if not passed else "All zone fields populated",
                affected_count=len(incomplete),
                affected_items=incomplete[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed zone coverage validation: {e}")
            self._add_error_result("zone_coverage", str(e))

    def _validate_freshness(self, start_date: str, end_date: str):
        """Check that data is recent enough"""

        check_start = time.time()

        query = f"""
        SELECT
            MAX(analysis_date) as latest_date,
            DATE_DIFF(CURRENT_DATE(), MAX(analysis_date), DAY) as days_stale
        FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
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

    def _validate_team_abbreviations(self, start_date: str, end_date: str):
        """Check that team abbreviations are valid NBA teams"""

        check_start = time.time()

        valid_teams = [
            'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
            'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
            'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
        ]
        teams_list = "', '".join(valid_teams)

        query = f"""
        SELECT DISTINCT
            team_abbr,
            COUNT(*) as record_count
        FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
        WHERE analysis_date >= '{start_date}'
          AND analysis_date <= '{end_date}'
          AND team_abbr NOT IN ('{teams_list}')
        GROUP BY team_abbr
        ORDER BY record_count DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(row.team_abbr, row.record_count) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="valid_team_abbreviations",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(invalid)} invalid team abbreviations" if not passed else "All team abbreviations are valid",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed team abbreviation validation: {e}")
            self._add_error_result("valid_team_abbreviations", str(e))

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

    parser = argparse.ArgumentParser(description="Validate Team Defense Zone Analysis")
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

    print(f"Validating team_defense_zone_analysis from {start_date} to {end_date}")

    validator = TeamDefenseZoneValidator(
        config_path="validation/configs/precompute/team_defense_zone_analysis.yaml"
    )

    results = validator.run_validation(start_date, end_date)

    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.check_name}: {result.message}")

    print("=" * 60)
