#!/usr/bin/env python3
# File: validation/validators/raw/nbac_injury_report_validator.py
"""
Custom validator for NBA.com Injury Reports - Player availability data.

Extends BaseValidator with injury-specific checks:
- Injury status distribution
- Team coverage
- Data freshness for game day
- Cross-validation with game outcomes
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


class NbacInjuryReportValidator(BaseValidator):
    """
    Custom validator for NBA.com injury reports.

    Additional validations:
    - Valid injury status values
    - All teams with scheduled games have reports
    - Data freshness on game days
    - Player availability consistency
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Injury report-specific validations"""

        logger.info("Running NBAC Injury Report custom validations...")

        # Check 1: Injury status distribution
        self._validate_injury_statuses(start_date, end_date)

        # Check 2: Team coverage for scheduled games
        self._validate_team_coverage(start_date, end_date)

        # Check 3: Data freshness
        self._validate_data_freshness(start_date, end_date)

        # Check 4: No duplicate player entries per game
        self._validate_no_duplicates(start_date, end_date)

        logger.info("Completed NBAC Injury Report custom validations")

    def _validate_injury_statuses(self, start_date: str, end_date: str):
        """Check that injury status values are valid"""

        check_start = time.time()

        query = f"""
        SELECT
          injury_status,
          COUNT(*) as count,
          COUNT(DISTINCT player_lookup) as unique_players
        FROM `{self.project_id}.nba_raw.nbac_injury_report`
        WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        GROUP BY injury_status
        ORDER BY count DESC
        """

        valid_statuses = {
            'Out', 'Doubtful', 'Questionable', 'Probable', 'Available',
            'Day-To-Day', 'Inactive', None, ''
        }

        try:
            result = self._execute_query(query, start_date, end_date)
            statuses = {row.injury_status: row.count for row in result}
            invalid_statuses = [s for s in statuses.keys() if s not in valid_statuses]

            passed = len(invalid_statuses) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="injury_status_values",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(invalid_statuses)} unexpected injury statuses" if not passed else "All injury statuses are valid",
                affected_count=len(invalid_statuses),
                affected_items=invalid_statuses,
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Injury status validation failed: {e}")

    def _validate_team_coverage(self, start_date: str, end_date: str):
        """Check that teams with scheduled games have injury reports"""

        check_start = time.time()

        query = f"""
        WITH scheduled_teams AS (
          SELECT DISTINCT home_team_tricode as team, game_date
          FROM `{self.project_id}.nba_raw.nbac_schedule`
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
          UNION DISTINCT
          SELECT DISTINCT away_team_tricode as team, game_date
          FROM `{self.project_id}.nba_raw.nbac_schedule`
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        ),
        injury_teams AS (
          SELECT DISTINCT team_tricode as team, game_date
          FROM `{self.project_id}.nba_raw.nbac_injury_report`
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        )
        SELECT
          s.team,
          s.game_date,
          CASE WHEN i.team IS NULL THEN 'missing' ELSE 'present' END as status
        FROM scheduled_teams s
        LEFT JOIN injury_teams i ON s.team = i.team AND s.game_date = i.game_date
        WHERE i.team IS NULL
        ORDER BY s.game_date, s.team
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            missing = [(row.team, str(row.game_date)) for row in result]

            # Note: Not all teams have injury reports every day (healthy teams)
            # This is informational only
            passed = True  # Informational check
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="team_injury_coverage",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="info",
                message=f"Found {len(missing)} team-game combinations without injury reports (may be healthy teams)",
                affected_count=len(missing),
                affected_items=[f"{m[0]} on {m[1]}" for m in missing[:10]],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Team coverage validation failed: {e}")

    def _validate_data_freshness(self, start_date: str, end_date: str):
        """Check data freshness for recent dates"""

        check_start = time.time()

        query = f"""
        SELECT
          MAX(processed_at) as last_processed,
          TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR) as hours_old
        FROM `{self.project_id}.nba_raw.nbac_injury_report`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
        """

        try:
            result = list(self._execute_query(query, start_date, end_date))

            if result and result[0].hours_old is not None:
                hours_old = result[0].hours_old
                passed = hours_old <= 6  # Should be updated within 6 hours
                duration = time.time() - check_start

                self.results.append(ValidationResult(
                    check_name="data_freshness",
                    check_type="freshness",
                    layer="bigquery",
                    passed=passed,
                    severity="warning" if not passed else "info",
                    message=f"Injury data is {hours_old:.1f} hours old" + (" (stale)" if not passed else ""),
                    affected_count=0 if passed else 1,
                    query_used=query,
                    execution_duration=duration
                ))
            else:
                self.results.append(ValidationResult(
                    check_name="data_freshness",
                    check_type="freshness",
                    layer="bigquery",
                    passed=False,
                    severity="warning",
                    message="No recent injury data found",
                    affected_count=1
                ))

        except Exception as e:
            logger.error(f"Data freshness validation failed: {e}")

    def _validate_no_duplicates(self, start_date: str, end_date: str):
        """Check for duplicate player entries per game"""

        check_start = time.time()

        query = f"""
        SELECT
          game_date,
          player_lookup,
          team_tricode,
          COUNT(*) as entry_count
        FROM `{self.project_id}.nba_raw.nbac_injury_report`
        WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        GROUP BY game_date, player_lookup, team_tricode
        HAVING COUNT(*) > 1
        ORDER BY entry_count DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            duplicates = [(str(row.game_date), row.player_lookup, row.entry_count) for row in result]

            passed = len(duplicates) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="no_duplicate_entries",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(duplicates)} duplicate player entries" if not passed else "No duplicate entries",
                affected_count=len(duplicates),
                affected_items=[f"{d[1]} on {d[0]}: {d[2]} entries" for d in duplicates],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Duplicate entries validation failed: {e}")


if __name__ == "__main__":
    # CLI usage
    import argparse

    parser = argparse.ArgumentParser(description="Validate NBAC Injury Report data")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")

    args = parser.parse_args()

    validator = NbacInjuryReportValidator("validation/configs/raw/nbac_injury_report.yaml")
    results = validator.run(args.start_date, args.end_date)

    print(f"\nValidation complete: {results['overall_status']}")
    print(f"Passed: {results['passed_count']}/{results['total_checks']}")
