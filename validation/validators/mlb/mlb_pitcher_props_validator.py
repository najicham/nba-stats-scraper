#!/usr/bin/env python3
"""
File: validation/validators/mlb/mlb_pitcher_props_validator.py

MLB Pitcher Props Validator

Validates betting line data including:
- Prop availability (coverage of scheduled pitchers)
- Line reasonableness (strikeouts between 0.5 and 15)
- Sportsbook diversity
- Data quality

Usage:
    validator = MlbPitcherPropsValidator('validation/configs/mlb/mlb_pitcher_props.yaml')
    report = validator.validate(start_date='2025-08-01', end_date='2025-08-31')
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from validation.base_validator import BaseValidator, ValidationResult

logger = logging.getLogger(__name__)


class MlbPitcherPropsValidator(BaseValidator):
    """
    Validator for MLB pitcher props data.

    Validates:
    - Prop coverage (% of pitchers with lines)
    - Line reasonableness
    - Sportsbook variety
    - Data freshness
    """

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """
        Run MLB pitcher props-specific validations.

        Args:
            start_date: Start date for validation
            end_date: End date for validation
            season_year: Season year (optional)
        """
        logger.info("Running MLB pitcher props custom validations...")

        # 1. Coverage check
        self._validate_prop_coverage(start_date, end_date)

        # 2. Line reasonableness
        self._validate_line_reasonableness(start_date, end_date)

        # 3. Sportsbook diversity
        self._validate_sportsbook_diversity(start_date, end_date)

        # 4. Duplicate detection
        self._validate_no_duplicates(start_date, end_date)

    def _validate_prop_coverage(self, start_date: str, end_date: str):
        """Check coverage of pitcher props against scheduled games."""
        import time
        check_start = time.time()

        query = f"""
        WITH scheduled_pitchers AS (
            SELECT DISTINCT
                game_date,
                LOWER(REPLACE(home_probable_pitcher_name, ' ', '_')) as pitcher_lookup
            FROM `{self.project_id}.mlb_raw.mlb_schedule`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND home_probable_pitcher_name IS NOT NULL

            UNION DISTINCT

            SELECT DISTINCT
                game_date,
                LOWER(REPLACE(away_probable_pitcher_name, ' ', '_')) as pitcher_lookup
            FROM `{self.project_id}.mlb_raw.mlb_schedule`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND away_probable_pitcher_name IS NOT NULL
        ),
        pitchers_with_props AS (
            SELECT DISTINCT game_date, player_lookup as pitcher_lookup
            FROM `{self.project_id}.mlb_raw.bp_pitcher_props`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND player_lookup IS NOT NULL

            UNION DISTINCT

            SELECT DISTINCT game_date, player_lookup as pitcher_lookup
            FROM `{self.project_id}.mlb_raw.oddsa_pitcher_props`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
              AND player_lookup IS NOT NULL
        ),
        coverage AS (
            SELECT
                s.game_date,
                COUNT(DISTINCT s.pitcher_lookup) as scheduled,
                COUNT(DISTINCT p.pitcher_lookup) as with_props
            FROM scheduled_pitchers s
            LEFT JOIN pitchers_with_props p
                ON s.game_date = p.game_date
                AND s.pitcher_lookup = p.pitcher_lookup
            GROUP BY s.game_date
        )
        SELECT
            game_date,
            scheduled,
            with_props,
            ROUND(100.0 * with_props / NULLIF(scheduled, 0), 1) as coverage_pct
        FROM coverage
        WHERE with_props < scheduled * 0.8  -- Less than 80% coverage
        ORDER BY game_date
        """

        result = self._execute_query(query, start_date, end_date)
        low_coverage = list(result)

        passed = len(low_coverage) == 0
        duration = time.time() - check_start

        affected_items = [
            f"{row.game_date}: {row.with_props}/{row.scheduled} ({row.coverage_pct}%)"
            for row in low_coverage[:20]
        ]

        self.results.append(ValidationResult(
            check_name="prop_coverage",
            check_type="completeness",
            layer="bigquery",
            passed=passed,
            severity="warning",
            message=f"Found {len(low_coverage)} dates with low prop coverage (<80%)" if not passed else "Good prop coverage",
            affected_count=len(low_coverage),
            affected_items=affected_items,
            execution_duration=duration
        ))

    def _validate_line_reasonableness(self, start_date: str, end_date: str):
        """Check that strikeout lines are reasonable (0.5 to 15)."""
        import time
        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            strikeouts_line,
            sportsbook
        FROM `{self.project_id}.mlb_raw.bp_pitcher_props`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND (strikeouts_line < 0.5 OR strikeouts_line > 15)

        UNION ALL

        SELECT
            game_date,
            pitcher_lookup,
            strikeouts_line,
            sportsbook
        FROM `{self.project_id}.mlb_raw.oddsa_pitcher_props`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND (strikeouts_line < 0.5 OR strikeouts_line > 15)

        ORDER BY game_date
        """

        result = self._execute_query(query, start_date, end_date)
        unreasonable = list(result)

        passed = len(unreasonable) == 0
        duration = time.time() - check_start

        affected_items = [
            f"{row.game_date}: {row.pitcher_lookup} K={row.strikeouts_line} ({row.sportsbook})"
            for row in unreasonable[:20]
        ]

        self.results.append(ValidationResult(
            check_name="line_reasonableness",
            check_type="data_quality",
            layer="bigquery",
            passed=passed,
            severity="warning",
            message=f"Found {len(unreasonable)} unreasonable lines" if not passed else "All lines reasonable",
            affected_count=len(unreasonable),
            affected_items=affected_items,
            execution_duration=duration
        ))

    def _validate_sportsbook_diversity(self, start_date: str, end_date: str):
        """Check that multiple sportsbooks are present."""
        import time
        check_start = time.time()

        query = f"""
        WITH bp_books AS (
            SELECT DISTINCT sportsbook
            FROM `{self.project_id}.mlb_raw.bp_pitcher_props`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
        ),
        oddsa_books AS (
            SELECT DISTINCT sportsbook
            FROM `{self.project_id}.mlb_raw.oddsa_pitcher_props`
            WHERE game_date >= '{start_date}'
              AND game_date <= '{end_date}'
        )
        SELECT
            (SELECT COUNT(*) FROM bp_books) as bp_sportsbooks,
            (SELECT COUNT(*) FROM oddsa_books) as oddsa_sportsbooks
        """

        result = self._execute_query(query, start_date, end_date)
        row = next(result, None)
        if row is None:
            total_books = 0
        else:
            total_books = (row.bp_sportsbooks or 0) + (row.oddsa_sportsbooks or 0)
        passed = total_books >= 3  # At least 3 sportsbooks

        duration = time.time() - check_start

        self.results.append(ValidationResult(
            check_name="sportsbook_diversity",
            check_type="data_quality",
            layer="bigquery",
            passed=passed,
            severity="warning",
            message=f"Found {total_books} sportsbooks (BP: {row.bp_sportsbooks if row else 0}, ODDSA: {row.oddsa_sportsbooks if row else 0})",
            affected_count=0 if passed else 1,
            affected_items=[f"BP: {row.bp_sportsbooks if row else 0}", f"ODDSA: {row.oddsa_sportsbooks if row else 0}"],
            execution_duration=duration
        ))

    def _validate_no_duplicates(self, start_date: str, end_date: str):
        """Check for duplicate prop records."""
        import time
        check_start = time.time()

        query = f"""
        SELECT
            game_date,
            pitcher_lookup,
            sportsbook,
            COUNT(*) as dup_count
        FROM `{self.project_id}.mlb_raw.bp_pitcher_props`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date, pitcher_lookup, sportsbook
        HAVING COUNT(*) > 1
        ORDER BY dup_count DESC
        LIMIT 50
        """

        result = self._execute_query(query, start_date, end_date)
        duplicates = list(result)

        passed = len(duplicates) == 0
        duration = time.time() - check_start

        affected_items = [
            f"{row.game_date}: {row.pitcher_lookup} ({row.sportsbook}) x{row.dup_count}"
            for row in duplicates[:20]
        ]

        self.results.append(ValidationResult(
            check_name="no_duplicates",
            check_type="data_quality",
            layer="bigquery",
            passed=passed,
            severity="warning",
            message=f"Found {len(duplicates)} duplicate records" if not passed else "No duplicates",
            affected_count=len(duplicates),
            affected_items=affected_items,
            execution_duration=duration
        ))

    def _generate_backfill_commands(self, missing_dates: List[str]) -> List[str]:
        """Generate MLB props-specific backfill commands."""
        if not missing_dates:
            return []

        commands = []
        for date_str in missing_dates[:10]:
            commands.append(
                f"# Scrape MLB pitcher props for {date_str}\n"
                f"PYTHONPATH=. python scrapers/bettingpros/bp_mlb_player_props.py "
                f"--date {date_str}"
            )

        if len(missing_dates) > 10:
            commands.append(f"# ... and {len(missing_dates) - 10} more dates")

        return commands


def main():
    """Main entry point for standalone validation."""
    import argparse
    import os

    parser = argparse.ArgumentParser(
        description='MLB Pitcher Props Validator'
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
    config_path = 'validation/configs/mlb/mlb_pitcher_props.yaml'
    if not os.path.exists(config_path):
        # Create default config
        config_path = None

    if config_path:
        validator = MlbPitcherPropsValidator(config_path)
    else:
        # Create validator with inline config
        validator = MlbPitcherPropsValidator.__new__(MlbPitcherPropsValidator)
        validator.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        validator.processor_name = 'mlb_pitcher_props'
        validator.processor_type = 'raw'
        validator.results = []
        validator._query_cache = {}
        validator.partition_handler = None
        validator._start_time = 0

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
