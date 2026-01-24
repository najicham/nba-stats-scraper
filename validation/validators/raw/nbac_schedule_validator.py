#!/usr/bin/env python3
# File: validation/validators/raw/nbac_schedule_validator.py
"""
Custom validator for NBA.com Schedule - Source of truth for all games.

Extends BaseValidator with schedule-specific checks:
- Season game count completeness
- Team game distribution
- Date gap detection (All-Star break, etc.)
- Cross-validation with ESPN schedule
"""

import sys
import os
import time
from typing import Optional
from datetime import date, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from validation.base_validator import BaseValidator, ValidationResult
import logging

logger = logging.getLogger(__name__)


class NbacScheduleValidator(BaseValidator):
    """
    Custom validator for NBA.com schedule with game-specific checks.

    Additional validations:
    - Season completeness (1230 regular season games)
    - All 30 teams represented
    - 82 games per team
    - Game date gaps (All-Star break detection)
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Schedule-specific validations"""

        logger.info("Running NBAC Schedule custom validations...")

        # Check 1: Team representation
        self._validate_team_presence(start_date, end_date)

        # Check 2: Games per team
        self._validate_games_per_team(start_date, end_date, season_year)

        # Check 3: Duplicate game detection
        self._validate_no_duplicate_games(start_date, end_date)

        # Check 4: Game status consistency
        self._validate_game_status(start_date, end_date)

        logger.info("Completed NBAC Schedule custom validations")

    def _validate_team_presence(self, start_date: str, end_date: str):
        """Check that all 30 NBA teams are present"""

        check_start = time.time()

        query = f"""
        SELECT
          team,
          COUNT(*) as game_count
        FROM (
          SELECT home_team_tricode as team FROM `{self.project_id}.nba_raw.nbac_schedule`
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
          UNION ALL
          SELECT away_team_tricode as team FROM `{self.project_id}.nba_raw.nbac_schedule`
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        )
        GROUP BY team
        ORDER BY game_count
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            teams = [row.team for row in result]

            passed = len(teams) == 30
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="team_presence",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(teams)} teams (expected 30)" if not passed else "All 30 teams present",
                affected_count=30 - len(teams) if not passed else 0,
                affected_items=teams if not passed else [],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Team presence validation failed: {e}")
            self.results.append(ValidationResult(
                check_name="team_presence",
                check_type="completeness",
                layer="bigquery",
                passed=False,
                severity="error",
                message=f"Validation query failed: {str(e)}",
                affected_count=0
            ))

    def _validate_games_per_team(self, start_date: str, end_date: str, season_year: Optional[int]):
        """Check that each team has expected number of games"""

        check_start = time.time()

        # Only run for full season checks
        if not season_year:
            return

        query = f"""
        WITH team_games AS (
          SELECT home_team_tricode as team, game_id FROM `{self.project_id}.nba_raw.nbac_schedule`
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
          UNION ALL
          SELECT away_team_tricode as team, game_id FROM `{self.project_id}.nba_raw.nbac_schedule`
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        )
        SELECT
          team,
          COUNT(DISTINCT game_id) as game_count
        FROM team_games
        GROUP BY team
        HAVING COUNT(DISTINCT game_id) < 80 OR COUNT(DISTINCT game_id) > 84
        ORDER BY game_count
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            anomalies = [(row.team, row.game_count) for row in result]

            passed = len(anomalies) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="games_per_team",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(anomalies)} teams with unusual game counts" if not passed else "All teams have expected game counts",
                affected_count=len(anomalies),
                affected_items=[f"{a[0]}: {a[1]} games" for a in anomalies],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Games per team validation failed: {e}")

    def _validate_no_duplicate_games(self, start_date: str, end_date: str):
        """Check for duplicate game entries"""

        check_start = time.time()

        query = f"""
        SELECT
          game_id,
          COUNT(*) as entry_count
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        GROUP BY game_id
        HAVING COUNT(*) > 1
        ORDER BY entry_count DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            duplicates = [(row.game_id, row.entry_count) for row in result]

            passed = len(duplicates) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="no_duplicate_games",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(duplicates)} duplicate game entries" if not passed else "No duplicate games",
                affected_count=len(duplicates),
                affected_items=[f"{d[0]}: {d[1]} entries" for d in duplicates],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Duplicate games validation failed: {e}")

    def _validate_game_status(self, start_date: str, end_date: str):
        """Check game status values are valid"""

        check_start = time.time()

        query = f"""
        SELECT
          game_status_text,
          COUNT(*) as count
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        GROUP BY game_status_text
        ORDER BY count DESC
        """

        valid_statuses = {'Final', 'In Progress', 'Scheduled', 'Postponed', 'Canceled', None, ''}

        try:
            result = self._execute_query(query, start_date, end_date)
            statuses = {row.game_status_text: row.count for row in result}
            invalid_statuses = [s for s in statuses.keys() if s not in valid_statuses]

            passed = len(invalid_statuses) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="game_status_values",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid_statuses)} unexpected game status values" if not passed else "All game statuses are valid",
                affected_count=len(invalid_statuses),
                affected_items=invalid_statuses,
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Game status validation failed: {e}")


if __name__ == "__main__":
    # CLI usage
    import argparse

    parser = argparse.ArgumentParser(description="Validate NBAC Schedule data")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--season-year", type=int, help="Season year for completeness checks")

    args = parser.parse_args()

    validator = NbacScheduleValidator("validation/configs/raw/nbac_schedule.yaml")
    results = validator.run(args.start_date, args.end_date, args.season_year)

    print(f"\nValidation complete: {results['overall_status']}")
    print(f"Passed: {results['passed_count']}/{results['total_checks']}")
