#!/usr/bin/env python3
"""
Validate Pipeline Replay - Check that replay outputs are correct.

This script validates the outputs of a pipeline replay by checking:
- Record counts meet expected thresholds
- No duplicate records exist
- Data completeness across phases
- Optional comparison with production data

Usage:
    python bin/testing/validate_replay.py 2024-12-15
    python bin/testing/validate_replay.py 2024-12-15 --prefix=test_
    python bin/testing/validate_replay.py 2024-12-15 --compare-production

Created: 2025-12-31
Part of Pipeline Replay System
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

try:
    from google.cloud import bigquery
except ImportError:
    print("Missing google-cloud-bigquery. Run: pip install google-cloud-bigquery")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# =============================================================================
# Validation Configuration
# =============================================================================

# Minimum expected record counts per table
MIN_RECORDS = {
    # Phase 2 (Raw)
    'nba_raw.bdl_player_boxscores': 30,  # Variable based on games
    'nba_raw.nbac_gamebook_player_stats': 20,  # Gamebook may have fewer records

    # Phase 3 (Analytics)
    'nba_analytics.player_game_summary': 30,
    'nba_analytics.team_defense_game_summary': 0,  # May not run daily
    'nba_analytics.team_offense_game_summary': 2,

    # Phase 4 (Precompute)
    'nba_precompute.player_composite_factors': 0,  # Only runs on game days

    # Phase 5 (Predictions)
    'nba_predictions.player_prop_predictions': 50,
}

# Tables to check for duplicates (key columns that should be unique)
DUPLICATE_CHECK_TABLES = {
    'nba_predictions.player_prop_predictions': [
        'prediction_id'  # Primary key
    ],
    'nba_analytics.player_game_summary': [
        'game_id', 'player_lookup'
    ],
}


@dataclass
class ValidationResult:
    """Result of a single validation check."""
    check_name: str
    passed: bool
    message: str
    details: Optional[Dict] = None


@dataclass
class ValidationReport:
    """Complete validation report."""
    replay_date: str
    dataset_prefix: str
    validation_time: datetime
    results: List[ValidationResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def to_dict(self) -> Dict:
        return {
            'replay_date': self.replay_date,
            'dataset_prefix': self.dataset_prefix,
            'validation_time': self.validation_time.isoformat(),
            'all_passed': self.all_passed,
            'passed_count': self.passed_count,
            'failed_count': self.failed_count,
            'results': [
                {
                    'check_name': r.check_name,
                    'passed': r.passed,
                    'message': r.message,
                    'details': r.details,
                }
                for r in self.results
            ]
        }


class ReplayValidator:
    """Validates pipeline replay outputs."""

    def __init__(
        self,
        replay_date: str,
        dataset_prefix: str = 'test_',
        compare_production: bool = False,
    ):
        self.replay_date = replay_date
        self.dataset_prefix = dataset_prefix
        self.compare_production = compare_production
        self.bq_client = bigquery.Client()

        self.report = ValidationReport(
            replay_date=replay_date,
            dataset_prefix=dataset_prefix,
            validation_time=datetime.now()
        )

    def add_result(self, check_name: str, passed: bool, message: str, details: Optional[Dict] = None):
        """Add a validation result."""
        result = ValidationResult(
            check_name=check_name,
            passed=passed,
            message=message,
            details=details
        )
        self.report.results.append(result)
        status = "✅" if passed else "❌"
        logger.info(f"{status} {check_name}: {message}")

    def check_record_count(self, table: str, min_count: int) -> bool:
        """Check that a table has at least min_count records."""
        full_table = f"{self.dataset_prefix}{table}"

        query = f"""
        SELECT COUNT(*) as count
        FROM `{full_table}`
        WHERE game_date = '{self.replay_date}'
        """

        try:
            result = self.bq_client.query(query).result()
            row = list(result)[0]
            count = row.count

            passed = count >= min_count
            self.add_result(
                check_name=f"count_{table.replace('.', '_')}",
                passed=passed,
                message=f"{count} records (min: {min_count})",
                details={'count': count, 'min_required': min_count}
            )
            return passed

        except Exception as e:
            self.add_result(
                check_name=f"count_{table.replace('.', '_')}",
                passed=False,
                message=f"Query failed: {e}",
            )
            return False

    def check_duplicates(self, table: str, key_columns: List[str]) -> bool:
        """Check that a table has no duplicate records for the key columns."""
        full_table = f"{self.dataset_prefix}{table}"
        key_concat = ', '.join(key_columns)

        query = f"""
        SELECT
            COUNT(*) as total,
            COUNT(DISTINCT CONCAT({key_concat})) as unique_count
        FROM `{full_table}`
        WHERE game_date = '{self.replay_date}'
        """

        try:
            result = self.bq_client.query(query).result()
            row = list(result)[0]

            has_duplicates = row.total != row.unique_count
            duplicate_count = row.total - row.unique_count

            passed = not has_duplicates
            self.add_result(
                check_name=f"duplicates_{table.replace('.', '_')}",
                passed=passed,
                message=f"{'No duplicates' if passed else f'{duplicate_count} duplicates found'}",
                details={
                    'total': row.total,
                    'unique': row.unique_count,
                    'duplicates': duplicate_count
                }
            )
            return passed

        except Exception as e:
            self.add_result(
                check_name=f"duplicates_{table.replace('.', '_')}",
                passed=False,
                message=f"Query failed: {e}",
            )
            return False

    def check_predictions_coverage(self) -> bool:
        """Check that predictions cover all expected games."""
        query = f"""
        SELECT
            COUNT(DISTINCT game_id) as games_with_predictions,
            COUNT(DISTINCT player_lookup) as players_with_predictions,
            COUNT(*) as total_predictions
        FROM `{self.dataset_prefix}nba_predictions.player_prop_predictions`
        WHERE game_date = '{self.replay_date}'
        """

        try:
            result = self.bq_client.query(query).result()
            row = list(result)[0]

            # Check reasonable coverage
            passed = row.games_with_predictions > 0 and row.players_with_predictions >= 10

            self.add_result(
                check_name="predictions_coverage",
                passed=passed,
                message=f"{row.games_with_predictions} games, {row.players_with_predictions} players, {row.total_predictions} predictions",
                details={
                    'games': row.games_with_predictions,
                    'players': row.players_with_predictions,
                    'predictions': row.total_predictions
                }
            )
            return passed

        except Exception as e:
            self.add_result(
                check_name="predictions_coverage",
                passed=False,
                message=f"Query failed: {e}",
            )
            return False

    def compare_with_production(self) -> bool:
        """Compare test results with production data."""
        if not self.compare_production:
            return True

        tables_to_compare = [
            'nba_predictions.player_prop_predictions',
            'nba_analytics.player_game_summary',
        ]

        all_match = True

        for table in tables_to_compare:
            # Get test count
            test_query = f"""
            SELECT COUNT(*) as count
            FROM `{self.dataset_prefix}{table}`
            WHERE game_date = '{self.replay_date}'
            """

            # Get production count
            prod_query = f"""
            SELECT COUNT(*) as count
            FROM `{table}`
            WHERE game_date = '{self.replay_date}'
            """

            try:
                test_result = list(self.bq_client.query(test_query).result())[0]
                prod_result = list(self.bq_client.query(prod_query).result())[0]

                test_count = test_result.count
                prod_count = prod_result.count

                # Allow 5% variance
                variance = abs(test_count - prod_count) / max(prod_count, 1)
                passed = variance < 0.05

                self.add_result(
                    check_name=f"compare_{table.replace('.', '_')}",
                    passed=passed,
                    message=f"Test: {test_count}, Prod: {prod_count} ({variance*100:.1f}% variance)",
                    details={
                        'test_count': test_count,
                        'prod_count': prod_count,
                        'variance_pct': variance * 100
                    }
                )

                if not passed:
                    all_match = False

            except Exception as e:
                self.add_result(
                    check_name=f"compare_{table.replace('.', '_')}",
                    passed=False,
                    message=f"Comparison failed: {e}",
                )
                all_match = False

        return all_match

    def validate(self) -> ValidationReport:
        """Run all validation checks."""
        logger.info("=" * 60)
        logger.info("  REPLAY VALIDATION")
        logger.info("=" * 60)
        logger.info(f"Date:           {self.replay_date}")
        logger.info(f"Dataset Prefix: {self.dataset_prefix}")
        logger.info(f"Compare Prod:   {self.compare_production}")
        logger.info("=" * 60)

        # Record count checks
        logger.info("\n📊 Record Count Checks:")
        for table, min_count in MIN_RECORDS.items():
            self.check_record_count(table, min_count)

        # Duplicate checks
        logger.info("\n🔍 Duplicate Checks:")
        for table, key_columns in DUPLICATE_CHECK_TABLES.items():
            self.check_duplicates(table, key_columns)

        # Predictions coverage
        logger.info("\n🎯 Predictions Coverage:")
        self.check_predictions_coverage()

        # Production comparison (if requested)
        if self.compare_production:
            logger.info("\n📈 Production Comparison:")
            self.compare_with_production()

        # Print summary
        self.print_summary()

        return self.report

    def print_summary(self):
        """Print validation summary."""
        logger.info("\n")
        logger.info("=" * 60)
        logger.info("  VALIDATION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Passed: {self.report.passed_count}")
        logger.info(f"Failed: {self.report.failed_count}")
        logger.info(f"Status: {'PASSED ✅' if self.report.all_passed else 'FAILED ❌'}")
        logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description='Validate pipeline replay outputs'
    )

    parser.add_argument(
        'date',
        help='Date that was replayed (YYYY-MM-DD)'
    )

    parser.add_argument(
        '--prefix',
        type=str,
        default=os.environ.get('DATASET_PREFIX', 'test_'),
        help='Dataset prefix used during replay (default: test_)'
    )

    parser.add_argument(
        '--compare-production',
        action='store_true',
        help='Compare test results with production data'
    )

    parser.add_argument(
        '--output-json',
        type=str,
        help='Write report to JSON file'
    )

    args = parser.parse_args()

    validator = ReplayValidator(
        replay_date=args.date,
        dataset_prefix=args.prefix,
        compare_production=args.compare_production,
    )

    report = validator.validate()

    # Write JSON report if requested
    if args.output_json:
        with open(args.output_json, 'w') as f:
            json.dump(report.to_dict(), f, indent=2)
        logger.info(f"Report written to {args.output_json}")

    # Exit with appropriate code
    sys.exit(0 if report.all_passed else 1)


if __name__ == '__main__':
    main()
