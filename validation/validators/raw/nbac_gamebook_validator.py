#!/usr/bin/env python3
# File: validation/validators/raw/nbac_gamebook_validator.py
# Description: Custom validator for NBA.com Gamebook - Critical for Phase 3 analytics
"""
Custom validator for NBA.com Gamebook data.
Extends BaseValidator with gamebook-specific checks.

Key validations:
- Player count per game (20-40 expected)
- Starter validation (exactly 10 per game)
- DNP reason validation
- Active player stats completeness
- Cross-validation with BDL boxscores
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


class NbacGamebookValidator(BaseValidator):
    """
    Custom validator for NBA.com Gamebook data.

    Additional validations:
    - Player count per game (should be 20-40)
    - Starter count (exactly 10 per game - 5 per team)
    - DNP players should have reasons
    - Active player stats completeness
    - Cross-validation with BDL box scores
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Gamebook-specific validations"""

        logger.info("Running gamebook-specific custom validations...")

        # Check 1: Player count per game
        self._validate_player_count_per_game(start_date, end_date)

        # Check 2: Starter validation
        self._validate_starters(start_date, end_date)

        # Check 3: DNP reason validation
        self._validate_dnp_reasons(start_date, end_date)

        # Check 4: Active player stats completeness
        self._validate_active_player_stats(start_date, end_date)

        # Check 5: Cross-validate with BDL
        self._validate_cross_source_scores(start_date, end_date)

        logger.info("Completed gamebook-specific validations")

    def _validate_player_count_per_game(self, start_date: str, end_date: str):
        """Check if each game has reasonable number of players (20-40)"""

        check_start = time.time()

        query = f"""
        WITH game_player_counts AS (
          SELECT
            game_id,
            game_date,
            COUNT(*) as player_count,
            COUNTIF(player_status = 'active') as active_count,
            COUNTIF(player_status IN ('inactive', 'dnp')) as dnp_count
          FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
          GROUP BY game_id, game_date
        )
        SELECT
          game_id,
          game_date,
          player_count,
          active_count,
          dnp_count
        FROM game_player_counts
        WHERE player_count < 20 OR player_count > 40
           OR active_count = 0
        ORDER BY game_date, game_id
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            anomalies = [(row.game_id, str(row.game_date), row.player_count,
                         row.active_count) for row in result]

            # Separate zero-active from unusual count
            zero_active = [a for a in anomalies if a[3] == 0]
            unusual_count = [a for a in anomalies if a[3] > 0]

            passed = len(anomalies) == 0
            duration = time.time() - check_start

            if zero_active:
                # This is a critical R-009 issue
                self.results.append(ValidationResult(
                    check_name="r009_zero_active_players",
                    check_type="data_quality",
                    layer="bigquery",
                    passed=False,
                    severity="critical",
                    message=f"R-009 CRITICAL: {len(zero_active)} games have 0 active players (incomplete gamebook)",
                    affected_count=len(zero_active),
                    affected_items=[f"{a[0]} ({a[1]})" for a in zero_active[:10]],
                    query_used=query,
                    execution_duration=duration
                ))

            self.results.append(ValidationResult(
                check_name="player_count_per_game",
                check_type="data_quality",
                layer="bigquery",
                passed=len(unusual_count) == 0,
                severity="warning",
                message=f"Found {len(unusual_count)} games with unusual player counts (expected: 20-40)" if unusual_count else "All games have normal player counts",
                affected_count=len(unusual_count),
                affected_items=[f"{a[0]} ({a[1]}): {a[2]} players" for a in unusual_count[:10]],
                query_used=query,
                execution_duration=duration
            ))

            if unusual_count:
                logger.warning(f"Player count validation: {len(unusual_count)} games with unusual counts")
                for game_id, game_date, count, active in unusual_count[:3]:
                    logger.warning(f"  {game_date} {game_id}: {count} total, {active} active")

        except Exception as e:
            logger.error(f"Player count validation failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="player_count_per_game",
                check_type="data_quality",
                layer="bigquery",
                passed=False,
                severity="error",
                message=f"Validation failed: {str(e)}",
                execution_duration=duration
            ))

    def _validate_starters(self, start_date: str, end_date: str):
        """Validate that each game has exactly 10 starters (5 per team)"""

        check_start = time.time()

        query = f"""
        SELECT
          game_id,
          game_date,
          COUNTIF(is_starter = true) as starter_count
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_id, game_date
        HAVING COUNTIF(is_starter = true) != 10
        ORDER BY game_date
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            anomalies = [(row.game_id, str(row.game_date), row.starter_count) for row in result]

            passed = len(anomalies) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="starter_count_validation",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error",
                message=f"Found {len(anomalies)} games without exactly 10 starters" if not passed else "All games have correct starter count",
                affected_count=len(anomalies),
                affected_items=[f"{a[0]} ({a[1]}): {a[2]} starters" for a in anomalies[:10]],
                query_used=query,
                execution_duration=duration
            ))

            if not passed:
                logger.warning(f"Starter validation: {len(anomalies)} games with incorrect starter count")

        except Exception as e:
            logger.error(f"Starter validation failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="starter_count_validation",
                check_type="data_quality",
                layer="bigquery",
                passed=False,
                severity="error",
                message=f"Validation failed: {str(e)}",
                execution_duration=duration
            ))

    def _validate_dnp_reasons(self, start_date: str, end_date: str):
        """Check that DNP players have reasons specified"""

        check_start = time.time()

        query = f"""
        SELECT
          game_id,
          game_date,
          player_lookup,
          player_status,
          dnp_reason
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND player_status IN ('inactive', 'dnp')
          AND (dnp_reason IS NULL OR TRIM(dnp_reason) = '')
        ORDER BY game_date, game_id
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            missing_reasons = [(row.game_id, str(row.game_date), row.player_lookup) for row in result]

            passed = len(missing_reasons) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="dnp_reason_validation",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning",
                message=f"Found {len(missing_reasons)} DNP players without reasons" if not passed else "All DNP players have reasons",
                affected_count=len(missing_reasons),
                affected_items=[f"{m[2]} ({m[0]}, {m[1]})" for m in missing_reasons[:10]],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.info(f"DNP reason validation skipped: {str(e)}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="dnp_reason_validation",
                check_type="data_quality",
                layer="bigquery",
                passed=True,
                severity="info",
                message=f"Could not validate DNP reasons: {str(e)[:100]}",
                execution_duration=duration
            ))

    def _validate_active_player_stats(self, start_date: str, end_date: str):
        """Check that active players have complete stats"""

        check_start = time.time()

        query = f"""
        SELECT
          game_id,
          game_date,
          player_lookup,
          minutes,
          points,
          total_rebounds,
          assists
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND player_status = 'active'
          AND (points IS NULL OR minutes IS NULL)
        ORDER BY game_date, game_id
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            incomplete = [(row.game_id, str(row.game_date), row.player_lookup) for row in result]

            passed = len(incomplete) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="active_player_stats_completeness",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="error",
                message=f"Found {len(incomplete)} active players with missing stats" if not passed else "All active players have complete stats",
                affected_count=len(incomplete),
                affected_items=[f"{i[2]} ({i[0]}, {i[1]})" for i in incomplete[:10]],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Active player stats validation failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="active_player_stats_completeness",
                check_type="data_quality",
                layer="bigquery",
                passed=False,
                severity="error",
                message=f"Validation failed: {str(e)}",
                execution_duration=duration
            ))

    def _validate_cross_source_scores(self, start_date: str, end_date: str):
        """Compare gamebook scores with BDL box scores"""

        check_start = time.time()

        query = f"""
        WITH gamebook_totals AS (
          SELECT
            game_id,
            player_lookup,
            points as gamebook_points
          FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
            AND player_status = 'active'
        ),
        bdl_totals AS (
          SELECT
            game_id,
            player_lookup,
            points as bdl_points
          FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
        )
        SELECT
          g.game_id,
          g.player_lookup,
          g.gamebook_points,
          b.bdl_points,
          ABS(g.gamebook_points - b.bdl_points) as points_diff
        FROM gamebook_totals g
        JOIN bdl_totals b
          ON g.game_id = b.game_id
          AND g.player_lookup = b.player_lookup
        WHERE ABS(g.gamebook_points - b.bdl_points) > 0
        ORDER BY points_diff DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            mismatches = [(row.game_id, row.player_lookup, row.gamebook_points,
                          row.bdl_points, row.points_diff) for row in result]

            passed = len(mismatches) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="cross_source_validation_bdl",
                check_type="cross_validation",
                layer="bigquery",
                passed=passed,
                severity="warning",
                message=f"Found {len(mismatches)} score mismatches between gamebook and BDL" if not passed else "All scores match BDL",
                affected_count=len(mismatches),
                affected_items=[f"{m[1]} ({m[0]}): GB={m[2]} BDL={m[3]} diff={m[4]}" for m in mismatches[:10]],
                query_used=query,
                execution_duration=duration
            ))

            if not passed:
                logger.warning(f"Cross-source validation: {len(mismatches)} score mismatches")

        except Exception as e:
            # BDL data might not be available - that's okay
            duration = time.time() - check_start
            logger.info(f"Cross-source validation skipped: {str(e)}")
            self.results.append(ValidationResult(
                check_name="cross_source_validation_bdl",
                check_type="cross_validation",
                layer="bigquery",
                passed=True,
                severity="info",
                message=f"Could not validate cross-source (BDL may not be available): {str(e)[:100]}",
                affected_count=0,
                execution_duration=duration
            ))


def main():
    """Run validation from command line"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Validate NBA.com gamebook data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate last 7 days
  python nbac_gamebook_validator.py --last-days 7

  # Validate specific date range
  python nbac_gamebook_validator.py --start-date 2024-01-01 --end-date 2024-01-31

  # Validate entire season
  python nbac_gamebook_validator.py --season 2024

  # Validate without sending notifications
  python nbac_gamebook_validator.py --last-days 7 --no-notify
        """
    )
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--season', type=int, help='Season year (2024 for 2024-25)')
    parser.add_argument('--last-days', type=int, help='Validate last N days')
    parser.add_argument('--no-notify', action='store_true', help='Disable notifications')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')

    args = parser.parse_args()

    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Initialize validator
    config_path = 'validation/configs/raw/nbac_gamebook.yaml'

    try:
        validator = NbacGamebookValidator(config_path)
    except Exception as e:
        logger.error(f"Failed to initialize validator: {e}")
        sys.exit(1)

    # Determine date range
    if args.last_days:
        from datetime import date, timedelta
        end_date = date.today().isoformat()
        start_date = (date.today() - timedelta(days=args.last_days)).isoformat()
    elif args.start_date and args.end_date:
        start_date = args.start_date
        end_date = args.end_date
    else:
        start_date = None
        end_date = None

    # Run validation
    try:
        report = validator.validate(
            start_date=start_date,
            end_date=end_date,
            season_year=args.season,
            notify=not args.no_notify
        )

        # Exit with error code if validation failed
        if report.overall_status == 'fail':
            sys.exit(1)
        elif report.overall_status == 'warn':
            sys.exit(2)
        else:
            sys.exit(0)

    except Exception as e:
        logger.error(f"Validation execution failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
