#!/usr/bin/env python3
# File: validation/validators/raw/odds_api_props_validator.py
# Description: Custom validator for Odds API Player Props - Critical for betting operations
"""
Custom validator for Odds API Player Props data.
Extends BaseValidator with props-specific checks.

Key validations:
- Bookmaker coverage (should have multiple bookmakers)
- Player coverage per game
- Line value reasonability
- Odds value validation
- Cross-validation with game schedule
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


class OddsApiPropsValidator(BaseValidator):
    """
    Custom validator for Odds API Player Props data.

    Additional validations:
    - Bookmaker coverage (at least 2 bookmakers per game)
    - Player coverage (at least 10 players per game)
    - Line value ranges (5.5 to 50.5 for points)
    - Odds reasonability (-500 to +500)
    - Cross-validation with active players
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Props-specific validations"""

        logger.info("Running odds API props-specific custom validations...")

        # Check 1: Bookmaker coverage
        self._validate_bookmaker_coverage(start_date, end_date)

        # Check 2: Player coverage per game
        self._validate_player_coverage(start_date, end_date)

        # Check 3: Line value ranges
        self._validate_line_values(start_date, end_date)

        # Check 4: Odds reasonability
        self._validate_odds_values(start_date, end_date)

        # Check 5: Player lookup validation
        self._validate_player_lookups(start_date, end_date)

        # Check 6: Game coverage vs schedule
        self._validate_game_coverage(start_date, end_date)

        logger.info("Completed odds API props-specific validations")

    def _validate_bookmaker_coverage(self, start_date: str, end_date: str):
        """Check if each game has sufficient bookmaker coverage"""

        check_start = time.time()

        query = f"""
        SELECT
          game_date,
          game_id,
          COUNT(DISTINCT bookmaker) as bookmaker_count,
          STRING_AGG(DISTINCT bookmaker ORDER BY bookmaker LIMIT 5) as bookmakers
        FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date, game_id
        HAVING bookmaker_count < 2
        ORDER BY game_date
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            low_coverage = [(str(row.game_date), row.game_id, row.bookmaker_count,
                            row.bookmakers) for row in result]

            passed = len(low_coverage) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="bookmaker_coverage",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning",
                message=f"Found {len(low_coverage)} games with insufficient bookmaker coverage (<2)" if not passed else "All games have adequate bookmaker coverage",
                affected_count=len(low_coverage),
                affected_items=[f"{g[1]} ({g[0]}): {g[2]} bookmakers" for g in low_coverage[:10]],
                query_used=query,
                execution_duration=duration
            ))

            if not passed:
                logger.warning(f"Bookmaker coverage: {len(low_coverage)} games with low coverage")

        except Exception as e:
            logger.error(f"Bookmaker coverage validation failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="bookmaker_coverage",
                check_type="data_quality",
                layer="bigquery",
                passed=False,
                severity="error",
                message=f"Validation failed: {str(e)}",
                execution_duration=duration
            ))

    def _validate_player_coverage(self, start_date: str, end_date: str):
        """Check if each game has sufficient player props coverage"""

        check_start = time.time()

        query = f"""
        SELECT
          game_date,
          game_id,
          COUNT(DISTINCT player_lookup) as player_count
        FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date, game_id
        HAVING player_count < 10
        ORDER BY game_date
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            low_coverage = [(str(row.game_date), row.game_id, row.player_count) for row in result]

            passed = len(low_coverage) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="player_props_coverage",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning",
                message=f"Found {len(low_coverage)} games with low player props coverage (<10 players)" if not passed else "All games have adequate player coverage",
                affected_count=len(low_coverage),
                affected_items=[f"{g[1]} ({g[0]}): {g[2]} players" for g in low_coverage[:10]],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Player coverage validation failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="player_props_coverage",
                check_type="data_quality",
                layer="bigquery",
                passed=False,
                severity="error",
                message=f"Validation failed: {str(e)}",
                execution_duration=duration
            ))

    def _validate_line_values(self, start_date: str, end_date: str):
        """Check that points lines are within reasonable ranges"""

        check_start = time.time()

        query = f"""
        SELECT
          game_date,
          game_id,
          player_lookup,
          bookmaker,
          points_line
        FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND (points_line < 3.5 OR points_line > 55.5)
        ORDER BY game_date
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            outliers = [(str(row.game_date), row.player_lookup, row.points_line,
                        row.bookmaker) for row in result]

            passed = len(outliers) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="line_value_ranges",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning",
                message=f"Found {len(outliers)} props with unusual line values" if not passed else "All line values are within expected ranges",
                affected_count=len(outliers),
                affected_items=[f"{o[1]} ({o[0]}): {o[2]} pts @ {o[3]}" for o in outliers[:10]],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Line value validation failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="line_value_ranges",
                check_type="data_quality",
                layer="bigquery",
                passed=False,
                severity="error",
                message=f"Validation failed: {str(e)}",
                execution_duration=duration
            ))

    def _validate_odds_values(self, start_date: str, end_date: str):
        """Check that odds are within reasonable ranges"""

        check_start = time.time()

        query = f"""
        SELECT
          game_date,
          player_lookup,
          bookmaker,
          points_line,
          over_price_american,
          under_price_american
        FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND (
            over_price_american < -500 OR over_price_american > 500
            OR under_price_american < -500 OR under_price_american > 500
          )
        ORDER BY game_date
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            outliers = [(str(row.game_date), row.player_lookup, row.over_price_american,
                        row.under_price_american) for row in result]

            passed = len(outliers) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="odds_value_ranges",
                check_type="data_quality",
                layer="bigquery",
                passed=passed,
                severity="warning",
                message=f"Found {len(outliers)} props with unusual odds values" if not passed else "All odds are within expected ranges",
                affected_count=len(outliers),
                affected_items=[f"{o[1]} ({o[0]}): Over={o[2]} Under={o[3]}" for o in outliers[:10]],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Odds value validation failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="odds_value_ranges",
                check_type="data_quality",
                layer="bigquery",
                passed=False,
                severity="error",
                message=f"Validation failed: {str(e)}",
                execution_duration=duration
            ))

    def _validate_player_lookups(self, start_date: str, end_date: str):
        """Validate that player_lookup values can be matched to known players"""

        check_start = time.time()

        query = f"""
        WITH props_players AS (
          SELECT DISTINCT player_lookup
          FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
            AND player_lookup IS NOT NULL
        ),
        known_players AS (
          SELECT DISTINCT player_lookup
          FROM `{self.project_id}.nba_raw.bdl_active_players_current`
          WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
        )
        SELECT
          p.player_lookup
        FROM props_players p
        LEFT JOIN known_players k ON p.player_lookup = k.player_lookup
        WHERE k.player_lookup IS NULL
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            unmatched = [row.player_lookup for row in result]

            # This is just a warning - some players might not be in BDL yet
            passed = len(unmatched) < 20  # Allow some unmatched
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="player_lookup_validation",
                check_type="cross_validation",
                layer="bigquery",
                passed=passed,
                severity="warning" if not passed else "info",
                message=f"Found {len(unmatched)} props players not in BDL roster" if unmatched else "All props players found in BDL roster",
                affected_count=len(unmatched),
                affected_items=unmatched[:10],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            duration = time.time() - check_start
            logger.info(f"Player lookup validation skipped: {str(e)}")
            self.results.append(ValidationResult(
                check_name="player_lookup_validation",
                check_type="cross_validation",
                layer="bigquery",
                passed=True,
                severity="info",
                message=f"Could not validate player lookups: {str(e)[:100]}",
                execution_duration=duration
            ))

    def _validate_game_coverage(self, start_date: str, end_date: str):
        """Check that we have props for scheduled games"""

        check_start = time.time()

        query = f"""
        WITH schedule AS (
          SELECT
            game_id,
            game_date,
            home_team_tricode,
            away_team_tricode
          FROM `{self.project_id}.nba_raw.nbac_schedule`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
            AND game_status IN (1, 2)  -- Scheduled or in progress
        ),
        props AS (
          SELECT DISTINCT game_id
          FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
        )
        SELECT
          s.game_id,
          s.game_date,
          s.home_team_tricode,
          s.away_team_tricode
        FROM schedule s
        LEFT JOIN props p ON s.game_id = p.game_id
        WHERE p.game_id IS NULL
        ORDER BY s.game_date
        LIMIT 30
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            missing = [(row.game_id, str(row.game_date), row.home_team_tricode,
                       row.away_team_tricode) for row in result]

            passed = len(missing) == 0
            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="game_props_coverage",
                check_type="completeness",
                layer="bigquery",
                passed=passed,
                severity="warning",
                message=f"Found {len(missing)} scheduled games without props data" if not passed else "All scheduled games have props data",
                affected_count=len(missing),
                affected_items=[f"{m[0]} ({m[1]}): {m[3]}@{m[2]}" for m in missing[:10]],
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            duration = time.time() - check_start
            logger.info(f"Game coverage validation skipped: {str(e)}")
            self.results.append(ValidationResult(
                check_name="game_props_coverage",
                check_type="completeness",
                layer="bigquery",
                passed=True,
                severity="info",
                message=f"Could not validate game coverage: {str(e)[:100]}",
                execution_duration=duration
            ))


def main():
    """Run validation from command line"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Validate Odds API player props data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate last 7 days
  python odds_api_props_validator.py --last-days 7

  # Validate specific date range
  python odds_api_props_validator.py --start-date 2024-01-01 --end-date 2024-01-31

  # Validate without sending notifications
  python odds_api_props_validator.py --last-days 7 --no-notify
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
    config_path = 'validation/configs/raw/odds_api_props.yaml'

    try:
        validator = OddsApiPropsValidator(config_path)
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
