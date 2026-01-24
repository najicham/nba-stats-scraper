#!/usr/bin/env python3
# File: validation/validators/analytics/team_defense_game_summary_validator.py
# Description: Custom validator for Team Defense Game Summary analytics table
# Created: 2026-01-24
"""
Custom validator for Team Defense Game Summary analytics.

This validator checks the nba_analytics.team_defense_game_summary table for:
- Teams per game (should be exactly 2)
- No duplicate team-game entries
- Defensive rating bounds (80-150)
- Points allowed consistency
- Cross-validation with player_game_summary
"""

import sys
import os
import time
from typing import Optional

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from validation.base_validator import BaseValidator, ValidationResult
import logging

logger = logging.getLogger(__name__)


class TeamDefenseGameSummaryValidator(BaseValidator):
    """
    Custom validator for Team Defense Game Summary analytics.

    Validates the nba_analytics.team_defense_game_summary table which aggregates
    team defensive performance data per game.
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Team defense game summary specific validations"""

        logger.info("Running Team Defense Game Summary custom validations...")

        # Check 1: Teams per game (should be exactly 2)
        self._validate_teams_per_game(start_date, end_date)

        # Check 2: No duplicate team-game entries
        self._validate_no_duplicates(start_date, end_date)

        # Check 3: Defensive rating bounds (80-150)
        self._validate_defensive_rating_bounds(start_date, end_date)

        # Check 4: Points allowed reasonability
        self._validate_points_allowed_bounds(start_date, end_date)

        # Check 5: Cross-validate with schedule
        self._validate_against_schedule(start_date, end_date)

        # Check 6: Team abbreviation validity
        self._validate_team_abbreviations(start_date, end_date)

        logger.info("Completed Team Defense Game Summary validations")

    def _validate_teams_per_game(self, start_date: str, end_date: str):
        """Check if each game has exactly 2 teams"""

        check_start = time.time()

        query = f"""
        SELECT
            game_id,
            game_date,
            COUNT(DISTINCT team_abbr) as team_count
        FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_id, game_date
        HAVING COUNT(DISTINCT team_abbr) != 2
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            anomalies = [(row.game_id, str(row.game_date), row.team_count) for row in result]

            passed = len(anomalies) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="teams_per_game",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="critical" if not passed else "info",
                message=f"Found {len(anomalies)} games without exactly 2 teams" if not passed else "All games have exactly 2 teams",
                affected_count=len(anomalies),
                affected_items=anomalies[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed teams per game validation: {e}")
            self._add_error_result("teams_per_game", str(e))

    def _validate_no_duplicates(self, start_date: str, end_date: str):
        """Check for duplicate team-game entries"""

        check_start = time.time()

        query = f"""
        SELECT
            game_id,
            team_abbr,
            COUNT(*) as entry_count
        FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_id, team_abbr
        HAVING COUNT(*) > 1
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            duplicates = [(row.game_id, row.team_abbr, row.entry_count) for row in result]

            passed = len(duplicates) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="no_duplicate_entries",
                check_type="data_integrity",
                layer="bigquery",
                passed=passed,
                severity="critical" if not passed else "info",
                message=f"Found {len(duplicates)} duplicate team-game entries" if not passed else "No duplicate entries found",
                affected_count=len(duplicates),
                affected_items=duplicates[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed duplicate validation: {e}")
            self._add_error_result("no_duplicate_entries", str(e))

    def _validate_defensive_rating_bounds(self, start_date: str, end_date: str):
        """Check that defensive rating is within valid bounds (80-150)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_id,
            team_abbr,
            game_date,
            defensive_rating
        FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND defensive_rating IS NOT NULL
          AND (defensive_rating < 80 OR defensive_rating > 150)
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(row.game_id, row.team_abbr, row.defensive_rating) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="defensive_rating_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records with defensive rating outside bounds (80-150)" if not passed else "All defensive ratings within valid bounds",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed defensive rating bounds validation: {e}")
            self._add_error_result("defensive_rating_bounds", str(e))

    def _validate_points_allowed_bounds(self, start_date: str, end_date: str):
        """Check that points allowed is within reasonable bounds (50-200)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_id,
            team_abbr,
            game_date,
            points_allowed
        FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND points_allowed IS NOT NULL
          AND (points_allowed < 50 OR points_allowed > 200)
        ORDER BY game_date DESC
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(row.game_id, row.team_abbr, row.points_allowed) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="points_allowed_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid)} records with points allowed outside bounds (50-200)" if not passed else "All points allowed within valid bounds",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed points allowed bounds validation: {e}")
            self._add_error_result("points_allowed_bounds", str(e))

    def _validate_against_schedule(self, start_date: str, end_date: str):
        """Cross-validate game counts with schedule"""

        check_start = time.time()

        query = f"""
        WITH schedule_games AS (
            SELECT
                game_date,
                COUNT(*) as scheduled_games
            FROM `{self.project_id}.nba_raw.nbac_schedule`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND game_status = 3  -- Final games only
            GROUP BY game_date
        ),
        defense_games AS (
            SELECT
                game_date,
                COUNT(DISTINCT game_id) as defense_games
            FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
            GROUP BY game_date
        )
        SELECT
            s.game_date,
            s.scheduled_games,
            COALESCE(d.defense_games, 0) as defense_games,
            s.scheduled_games - COALESCE(d.defense_games, 0) as missing_games
        FROM schedule_games s
        LEFT JOIN defense_games d ON s.game_date = d.game_date
        WHERE COALESCE(d.defense_games, 0) < s.scheduled_games
        ORDER BY s.game_date DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            mismatches = [(str(row.game_date), row.scheduled_games, row.defense_games, row.missing_games) for row in result]

            passed = len(mismatches) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="schedule_cross_validation",
                check_type="cross_source",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(mismatches)} dates with missing team defense data vs schedule" if not passed else "Team defense data matches scheduled games",
                affected_count=len(mismatches),
                affected_items=mismatches[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed schedule cross-validation: {e}")
            self._add_error_result("schedule_cross_validation", str(e))

    def _validate_team_abbreviations(self, start_date: str, end_date: str):
        """Check that team abbreviations are valid NBA teams"""

        check_start = time.time()

        # Valid NBA team abbreviations
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
        FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
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

    parser = argparse.ArgumentParser(description="Validate Team Defense Game Summary analytics")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")

    args = parser.parse_args()

    # Calculate date range
    if args.start_date and args.end_date:
        start_date = args.start_date
        end_date = args.end_date
    else:
        end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    print(f"Validating team_defense_game_summary from {start_date} to {end_date}")

    # Load config and run validation
    validator = TeamDefenseGameSummaryValidator(
        config_path="validation/configs/analytics/team_defense_game_summary.yaml"
    )

    results = validator.run_validation(start_date, end_date)

    # Print summary
    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.check_name}: {result.message}")

    print("=" * 60)
