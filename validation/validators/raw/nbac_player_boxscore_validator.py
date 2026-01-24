#!/usr/bin/env python3
# File: validation/validators/raw/nbac_player_boxscore_validator.py
"""
Custom validator for NBA.com Player Boxscores - Official player stats.

Extends BaseValidator with boxscore-specific checks:
- Points calculation consistency (2P + 3P + FT)
- Stats reasonableness (no negative values, reasonable maxes)
- Cross-validation with BDL boxscores
- Game completeness (all final games have boxscores)
"""

import sys
import os
import time
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from validation.base_validator import BaseValidator, ValidationResult
import logging

logger = logging.getLogger(__name__)


class NbacPlayerBoxscoreValidator(BaseValidator):
    """
    Custom validator for NBA.com player boxscores.

    Additional validations:
    - Points = (FGM - FG3M) * 2 + FG3M * 3 + FTM
    - All stats >= 0
    - Reasonable stat maximums
    - Cross-validation with BDL
    - All completed games have boxscores
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Player boxscore-specific validations"""

        logger.info("Running NBAC Player Boxscore custom validations...")

        # Check 1: Points calculation consistency
        self._validate_points_calculation(start_date, end_date)

        # Check 2: Stats reasonableness
        self._validate_stats_range(start_date, end_date)

        # Check 3: Players per game
        self._validate_players_per_game(start_date, end_date)

        # Check 4: Game completeness
        self._validate_game_completeness(start_date, end_date)

        # Check 5: Cross-validation with BDL
        self._validate_against_bdl(start_date, end_date)

        logger.info("Completed NBAC Player Boxscore custom validations")

    def _validate_points_calculation(self, start_date: str, end_date: str):
        """Verify points = (FGM - FG3M) * 2 + FG3M * 3 + FTM"""

        check_start = time.time()

        query = f"""
        SELECT
          game_id,
          game_date,
          player_lookup,
          points,
          fgm,
          fg3m,
          ftm,
          ((fgm - fg3m) * 2 + fg3m * 3 + ftm) as calculated_points,
          ABS(points - ((fgm - fg3m) * 2 + fg3m * 3 + ftm)) as diff
        FROM `{self.project_id}.nba_raw.nbac_player_boxscore`
        WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
          AND minutes > 0
          AND fgm IS NOT NULL
          AND fg3m IS NOT NULL
          AND ftm IS NOT NULL
          AND points IS NOT NULL
        HAVING diff > 0
        ORDER BY diff DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            mismatches = [(row.player_lookup, str(row.game_date), row.points, row.diff) for row in result]

            passed = len(mismatches) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="points_calculation",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(mismatches)} players with points calculation mismatch" if not passed else "All points calculations correct",
                affected_count=len(mismatches),
                affected_items=[f"{m[0]} on {m[1]}: {m[2]} pts (diff: {m[3]})" for m in mismatches],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Points calculation validation failed: {e}")

    def _validate_stats_range(self, start_date: str, end_date: str):
        """Check stats are within reasonable ranges"""

        check_start = time.time()

        query = f"""
        SELECT
          game_id,
          game_date,
          player_lookup,
          points,
          assists,
          rebounds,
          minutes
        FROM `{self.project_id}.nba_raw.nbac_player_boxscore`
        WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
          AND (
            points < 0 OR points > 80 OR
            assists < 0 OR assists > 30 OR
            rebounds < 0 OR rebounds > 35 OR
            minutes < 0 OR minutes > 60
          )
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            anomalies = [(row.player_lookup, str(row.game_date), row.points, row.assists, row.rebounds) for row in result]

            passed = len(anomalies) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="stats_range",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(anomalies)} records with out-of-range stats" if not passed else "All stats within expected ranges",
                affected_count=len(anomalies),
                affected_items=[f"{a[0]} on {a[1]}: pts={a[2]}, ast={a[3]}, reb={a[4]}" for a in anomalies],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Stats range validation failed: {e}")

    def _validate_players_per_game(self, start_date: str, end_date: str):
        """Check reasonable number of players per game"""

        check_start = time.time()

        query = f"""
        SELECT
          game_id,
          game_date,
          COUNT(*) as player_count,
          COUNT(DISTINCT team_tricode) as team_count
        FROM `{self.project_id}.nba_raw.nbac_player_boxscore`
        WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        GROUP BY game_id, game_date
        HAVING player_count < 20 OR player_count > 40 OR team_count != 2
        ORDER BY game_date
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            anomalies = [(row.game_id, str(row.game_date), row.player_count, row.team_count) for row in result]

            passed = len(anomalies) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="players_per_game",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(anomalies)} games with unusual player counts" if not passed else "All games have expected player counts",
                affected_count=len(anomalies),
                affected_items=[f"{a[0]} on {a[1]}: {a[2]} players, {a[3]} teams" for a in anomalies],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Players per game validation failed: {e}")

    def _validate_game_completeness(self, start_date: str, end_date: str):
        """Check all completed games have boxscore data"""

        check_start = time.time()

        query = f"""
        SELECT
          s.game_id,
          s.game_date,
          s.home_team_tricode,
          s.away_team_tricode,
          s.game_status_text
        FROM `{self.project_id}.nba_raw.nbac_schedule` s
        LEFT JOIN (
          SELECT DISTINCT game_id
          FROM `{self.project_id}.nba_raw.nbac_player_boxscore`
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        ) b ON s.game_id = b.game_id
        WHERE s.game_date >= '{start_date}'
          AND s.game_date <= '{end_date}'
          AND s.game_status_text = 'Final'
          AND b.game_id IS NULL
        ORDER BY s.game_date
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            missing = [(row.game_id, str(row.game_date), row.home_team_tricode, row.away_team_tricode) for row in result]

            passed = len(missing) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="game_completeness",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(missing)} completed games without boxscore data" if not passed else "All completed games have boxscore data",
                affected_count=len(missing),
                affected_items=[f"{m[0]} on {m[1]}: {m[2]} vs {m[3]}" for m in missing],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Game completeness validation failed: {e}")

    def _validate_against_bdl(self, start_date: str, end_date: str):
        """Cross-validate points with BDL boxscores"""

        check_start = time.time()

        query = f"""
        SELECT
          n.game_id,
          n.game_date,
          n.player_lookup,
          n.points as nbac_points,
          b.pts as bdl_points,
          ABS(n.points - b.pts) as points_diff
        FROM `{self.project_id}.nba_raw.nbac_player_boxscore` n
        JOIN `{self.project_id}.nba_raw.bdl_player_boxscores` b
          ON n.player_lookup = b.player_lookup
          AND n.game_date = b.game_date
        WHERE n.game_date >= '{start_date}'
          AND n.game_date <= '{end_date}'
          AND n.points IS NOT NULL
          AND b.pts IS NOT NULL
          AND ABS(n.points - b.pts) > 0
        ORDER BY points_diff DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            mismatches = [(row.player_lookup, str(row.game_date), row.nbac_points, row.bdl_points) for row in result]

            passed = len(mismatches) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="bdl_cross_validation",
                check_type="cross_validation",
                layer="bigquery",
                passed=passed,
                severity="error" if not passed else "info",
                message=f"Found {len(mismatches)} points discrepancies with BDL" if not passed else "All points match BDL data",
                affected_count=len(mismatches),
                affected_items=[f"{m[0]} on {m[1]}: NBAC={m[2]}, BDL={m[3]}" for m in mismatches],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"BDL cross-validation failed: {e}")


if __name__ == "__main__":
    # CLI usage
    import argparse

    parser = argparse.ArgumentParser(description="Validate NBAC Player Boxscore data")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")

    args = parser.parse_args()

    validator = NbacPlayerBoxscoreValidator("validation/configs/raw/nbac_player_boxscore.yaml")
    results = validator.run(args.start_date, args.end_date)

    print(f"\nValidation complete: {results['overall_status']}")
    print(f"Passed: {results['passed_count']}/{results['total_checks']}")
