#!/usr/bin/env python3
"""
File: validation/validators/mlb/mlb_schedule_validator.py

MLB Schedule Validator

Validates MLB schedule data including:
- Game completeness (all dates have games during season)
- Probable pitcher assignments
- Team presence (all 30 teams)
- Data quality (no duplicates, valid fields)

Usage:
    validator = MlbScheduleValidator('validation/configs/mlb/mlb_schedule.yaml')
    report = validator.validate(start_date='2025-08-01', end_date='2025-08-31')
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from validation.base_validator import BaseValidator, ValidationResult

logger = logging.getLogger(__name__)


class MlbScheduleValidator(BaseValidator):
    """
    Validator for MLB schedule data.

    Extends BaseValidator with MLB-specific checks:
    - Probable pitcher completeness
    - Team coverage (30 teams)
    - Game time validity
    - Duplicate detection
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """
        Run MLB schedule-specific validations.

        Args:
            start_date: Start date for validation
            end_date: End date for validation
            season_year: Season year (optional)
        """
        logger.info("Running MLB schedule custom validations...")

        # 1. Probable pitcher completeness
        self._validate_probable_pitchers(start_date, end_date)

        # 2. Team presence
        self._validate_team_presence(start_date, end_date)

        # 3. Duplicate detection
        self._validate_no_duplicates(start_date, end_date)

        # 4. Game time validity
        self._validate_game_times(start_date, end_date)

    def _validate_probable_pitchers(self, start_date: str, end_date: str):
        """Check that games have probable pitchers assigned."""
        import time
        check_start = time.time()

        query = f"""
        WITH games AS (
            SELECT
                game_date,
                game_pk,
                home_team_abbr as home_team,
                away_team_abbr as away_team,
                home_probable_pitcher_name,
                away_probable_pitcher_name
            FROM `{self.project_id}.mlb_raw.mlb_schedule`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
        )
        SELECT
            game_date,
            game_pk,
            home_team,
            away_team,
            CASE
                WHEN home_probable_pitcher_name IS NULL THEN 'home'
                WHEN away_probable_pitcher_name IS NULL THEN 'away'
                ELSE 'both'
            END as missing_side
        FROM games
        WHERE home_probable_pitcher_name IS NULL
           OR away_probable_pitcher_name IS NULL
        ORDER BY game_date
        """

        result = self._execute_query(query, start_date, end_date)
        missing = list(result)

        passed = len(missing) == 0
        duration = time.time() - check_start

        affected_items = [
            f"{row.game_date}: {row.away_team}@{row.home_team} ({row.missing_side})"
            for row in missing[:20]
        ]

        self.results.append(ValidationResult(
            check_name="probable_pitcher_completeness",
            check_type="data_quality",
            layer="bigquery",
            passed=passed,
            severity="warning",  # Not critical - pitchers announced close to game time
            message=f"Found {len(missing)} games without probable pitchers" if not passed else "All games have probable pitchers",
            affected_count=len(missing),
            affected_items=affected_items,
            execution_duration=duration
        ))

        if not passed:
            logger.warning(f"Probable pitcher check: {len(missing)} games missing pitchers")

    def _validate_team_presence(self, start_date: str, end_date: str):
        """Check that all 30 MLB teams appear in schedule."""
        import time
        check_start = time.time()

        expected_teams = 30

        query = f"""
        WITH all_teams AS (
            SELECT DISTINCT home_team_abbr as team
            FROM `{self.project_id}.mlb_raw.mlb_schedule`
            WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
            UNION DISTINCT
            SELECT DISTINCT away_team_abbr as team
            FROM `{self.project_id}.mlb_raw.mlb_schedule`
            WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        )
        SELECT team FROM all_teams ORDER BY team
        """

        result = self._execute_query(query, start_date, end_date)
        teams_found = [row.team for row in result]
        actual_count = len(teams_found)

        passed = actual_count >= expected_teams
        duration = time.time() - check_start

        self.results.append(ValidationResult(
            check_name="team_presence",
            check_type="completeness",
            layer="bigquery",
            passed=passed,
            severity="error" if actual_count < 25 else "warning",
            message=f"Found {actual_count}/{expected_teams} teams",
            affected_count=expected_teams - actual_count if not passed else 0,
            affected_items=teams_found,
            execution_duration=duration
        ))

    def _validate_no_duplicates(self, start_date: str, end_date: str):
        """Check for duplicate game records."""
        import time
        check_start = time.time()

        query = f"""
        SELECT
            game_pk,
            game_date,
            COUNT(*) as dup_count
        FROM `{self.project_id}.mlb_raw.mlb_schedule`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_pk, game_date
        HAVING COUNT(*) > 1
        ORDER BY dup_count DESC
        """

        result = self._execute_query(query, start_date, end_date)
        duplicates = list(result)

        passed = len(duplicates) == 0
        duration = time.time() - check_start

        affected_items = [
            f"game_pk {row.game_pk} on {row.game_date}: {row.dup_count} records"
            for row in duplicates[:20]
        ]

        self.results.append(ValidationResult(
            check_name="no_duplicates",
            check_type="data_quality",
            layer="bigquery",
            passed=passed,
            severity="error",
            message=f"Found {len(duplicates)} duplicate game records" if not passed else "No duplicate games",
            affected_count=len(duplicates),
            affected_items=affected_items,
            execution_duration=duration
        ))

    def _validate_game_times(self, start_date: str, end_date: str):
        """Check for valid game times."""
        import time
        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            game_pk,
            game_time_utc as game_time,
            home_team_abbr as home_team,
            away_team_abbr as away_team
        FROM `{self.project_id}.mlb_raw.mlb_schedule`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND game_time_utc IS NULL
        ORDER BY game_date
        """

        result = self._execute_query(query, start_date, end_date)
        missing_times = list(result)

        passed = len(missing_times) == 0
        duration = time.time() - check_start

        affected_items = [
            f"{row.game_date}: {row.away_team}@{row.home_team}"
            for row in missing_times[:20]
        ]

        self.results.append(ValidationResult(
            check_name="game_time_validity",
            check_type="data_quality",
            layer="bigquery",
            passed=passed,
            severity="warning",
            message=f"Found {len(missing_times)} games without times" if not passed else "All games have times",
            affected_count=len(missing_times),
            affected_items=affected_items,
            execution_duration=duration
        ))

    def _generate_backfill_commands(self, missing_dates: List[str]) -> List[str]:
        """Generate MLB-specific backfill commands."""
        if not missing_dates:
            return []

        date_groups = self._group_consecutive_dates(missing_dates)

        commands = []
        for start, end in date_groups:
            commands.append(
                f"# Backfill MLB schedule for {start} to {end}\n"
                f"PYTHONPATH=. python scripts/mlb/backfill_mlb_schedule.py "
                f"--start-date {start} --end-date {end}"
            )

        return commands


def main():
    """Main entry point for standalone validation."""
    import argparse
    import os

    parser = argparse.ArgumentParser(
        description='MLB Schedule Validator'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        required=True,
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        required=True,
        help='End date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--output-mode',
        type=str,
        default='summary',
        choices=['summary', 'detailed', 'quiet'],
        help='Output verbosity'
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Use config file if it exists
    config_path = 'validation/configs/mlb/mlb_schedule.yaml'
    if not os.path.exists(config_path):
        # Create default config
        config_path = None

    if config_path:
        validator = MlbScheduleValidator(config_path)
    else:
        # Create validator with inline config
        validator = MlbScheduleValidator.__new__(MlbScheduleValidator)
        validator.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        validator.processor_name = 'mlb_schedule'
        validator.processor_type = 'raw'
        validator.results = []
        validator._query_cache = {}
        validator.partition_handler = None

        from google.cloud import bigquery
        validator.bq_client = bigquery.Client(project=validator.project_id)

    report = validator.validate(
        start_date=args.start_date,
        end_date=args.end_date,
        output_mode=args.output_mode
    )

    return 0 if report.overall_status == 'pass' else 1


if __name__ == '__main__':
    exit(main())
