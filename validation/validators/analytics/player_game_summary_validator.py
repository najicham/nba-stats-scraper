#!/usr/bin/env python3
# File: validation/validators/analytics/player_game_summary_validator.py
# Description: Custom validator for Player Game Summary analytics table
# Created: 2026-01-24 (Session 3 improvements)
"""
Custom validator for Player Game Summary analytics.

This validator checks the nba_analytics.player_game_summary table for:
- Player count per game (should match raw data)
- Stats consistency (points = 2*FGM + 3PM + FTM)
- No duplicate player-game entries
- Minutes bounds validation (0-60)
- Cross-validation with raw gamebook data
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


class PlayerGameSummaryValidator(BaseValidator):
    """
    Custom validator for Player Game Summary analytics.

    Validates the nba_analytics.player_game_summary table which aggregates
    player performance data from multiple raw sources.
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Player game summary specific validations"""

        logger.info("Running Player Game Summary custom validations...")

        # Check 1: Player count per game (should be 20-40)
        self._validate_player_count_per_game(start_date, end_date)

        # Check 2: No duplicate player-game entries
        self._validate_no_duplicates(start_date, end_date)

        # Check 3: Points calculation consistency
        self._validate_points_consistency(start_date, end_date)

        # Check 4: Minutes bounds (0-60)
        self._validate_minutes_bounds(start_date, end_date)

        # Check 5: Cross-validate with raw gamebook
        self._validate_against_gamebook(start_date, end_date)

        # Check 6: R-009 - No games with 0 active players
        self._validate_active_players(start_date, end_date)

        logger.info("Completed Player Game Summary validations")

    def _validate_player_count_per_game(self, start_date: str, end_date: str):
        """Check if each game has reasonable number of players (20-40)"""

        check_start = time.time()

        query = f"""
        WITH game_player_counts AS (
            SELECT
                game_id,
                game_date,
                COUNT(*) as player_count
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
            GROUP BY game_id, game_date
        )
        SELECT
            game_id,
            game_date,
            player_count
        FROM game_player_counts
        WHERE player_count < 20 OR player_count > 40
        ORDER BY game_date, game_id
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            anomalies = [(row.game_id, str(row.game_date), row.player_count) for row in result]

            passed = len(anomalies) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="player_count_per_game",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(anomalies)} games with unusual player count" if not passed else "All games have expected player count (20-40)",
                affected_count=len(anomalies),
                affected_items=anomalies[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed player count validation: {e}")
            self._add_error_result("player_count_per_game", str(e))

    def _validate_no_duplicates(self, start_date: str, end_date: str):
        """Check for duplicate player-game entries"""

        check_start = time.time()

        query = f"""
        SELECT
            game_id,
            player_lookup,
            COUNT(*) as entry_count
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_id, player_lookup
        HAVING COUNT(*) > 1
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            duplicates = [(row.game_id, row.player_lookup, row.entry_count) for row in result]

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

    def _validate_points_consistency(self, start_date: str, end_date: str):
        """Check that points = 2*FGM + 3PM + FTM (approximately)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_id,
            player_lookup,
            points,
            field_goals_made,
            three_pointers_made,
            free_throws_made,
            (field_goals_made * 2 + three_pointers_made + free_throws_made) AS calculated_points,
            ABS(points - (field_goals_made * 2 + three_pointers_made + free_throws_made)) AS diff
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND points IS NOT NULL
          AND field_goals_made IS NOT NULL
          AND ABS(points - (field_goals_made * 2 + three_pointers_made + free_throws_made)) > 1
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            inconsistent = [(row.game_id, row.player_lookup, row.points, row.calculated_points) for row in result]

            passed = len(inconsistent) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="points_consistency",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(inconsistent)} records with inconsistent point totals" if not passed else "All point totals are consistent with shooting stats",
                affected_count=len(inconsistent),
                affected_items=inconsistent[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed points consistency validation: {e}")
            self._add_error_result("points_consistency", str(e))

    def _validate_minutes_bounds(self, start_date: str, end_date: str):
        """Check that minutes are within valid bounds (0-60)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_id,
            player_lookup,
            minutes
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND (minutes < 0 OR minutes > 60)
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            invalid = [(row.game_id, row.player_lookup, row.minutes) for row in result]

            passed = len(invalid) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="minutes_bounds",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(invalid)} records with invalid minutes" if not passed else "All minutes within valid bounds (0-60)",
                affected_count=len(invalid),
                affected_items=invalid[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed minutes bounds validation: {e}")
            self._add_error_result("minutes_bounds", str(e))

    def _validate_against_gamebook(self, start_date: str, end_date: str):
        """Cross-validate player counts with raw gamebook data"""

        check_start = time.time()

        query = f"""
        WITH summary_counts AS (
            SELECT game_id, COUNT(*) as summary_count
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
            GROUP BY game_id
        ),
        gamebook_counts AS (
            SELECT game_id, COUNT(*) as gamebook_count
            FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
            WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
            GROUP BY game_id
        )
        SELECT
            COALESCE(s.game_id, g.game_id) as game_id,
            s.summary_count,
            g.gamebook_count,
            ABS(COALESCE(s.summary_count, 0) - COALESCE(g.gamebook_count, 0)) as diff
        FROM summary_counts s
        FULL OUTER JOIN gamebook_counts g ON s.game_id = g.game_id
        WHERE ABS(COALESCE(s.summary_count, 0) - COALESCE(g.gamebook_count, 0)) > 5
        ORDER BY diff DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            mismatches = [(row.game_id, row.summary_count, row.gamebook_count) for row in result]

            passed = len(mismatches) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="gamebook_cross_validation",
                check_type="cross_source",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(mismatches)} games with significant player count difference vs gamebook" if not passed else "Player counts match gamebook data",
                affected_count=len(mismatches),
                affected_items=mismatches[:10],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed gamebook cross-validation: {e}")
            self._add_error_result("gamebook_cross_validation", str(e))

    def _validate_active_players(self, start_date: str, end_date: str):
        """R-009: Check for games with 0 active players (incomplete data)"""

        check_start = time.time()

        query = f"""
        SELECT
            game_id,
            game_date,
            COUNT(*) as total_records,
            COUNTIF(minutes > 0) as active_count
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_id, game_date
        HAVING COUNTIF(minutes > 0) = 0
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            incomplete = [(row.game_id, str(row.game_date), row.total_records) for row in result]

            passed = len(incomplete) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="r009_active_players",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="critical" if not passed else "info",
                message=f"R-009: Found {len(incomplete)} games with 0 active players (incomplete data)" if not passed else "All games have active player data",
                affected_count=len(incomplete),
                affected_items=incomplete[:10],
                remediation=["Re-process affected games from raw data"] if not passed else [],
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Failed R-009 active players validation: {e}")
            self._add_error_result("r009_active_players", str(e))

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

    parser = argparse.ArgumentParser(description="Validate Player Game Summary analytics")
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

    print(f"Validating player_game_summary from {start_date} to {end_date}")

    # Load config and run validation
    validator = PlayerGameSummaryValidator(
        config_path="validation/configs/analytics/player_game_summary.yaml"
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
