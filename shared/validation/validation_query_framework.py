"""
Test-Driven Validation Framework

Key principle: Validation queries MUST be tested against KNOWN-BAD data
to verify they actually detect issues.

Session 123 Lesson: A validation query that returned "0 issues" was hiding
67% data pollution due to a logic error (wrong join condition).
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple
from datetime import date
import logging

logger = logging.getLogger(__name__)


@dataclass
class ValidationTestCase:
    """A test case for a validation query."""
    name: str
    description: str
    test_parameters: Dict  # Parameters to use for testing
    expected_result: str  # 'should_find_issues' or 'should_be_clean'
    minimum_issues: int = 0  # If 'should_find_issues', minimum count


@dataclass
class ValidationQuerySpec:
    """Specification for a validation query with test cases."""
    name: str
    description: str
    query_template: str
    data_model_assumptions: List[str]
    test_cases: List[ValidationTestCase]


class ValidationQueryTester:
    """Tests validation queries against known-good and known-bad data."""

    def __init__(self, bq_client):
        self.bq_client = bq_client

    def test_validation_query(
        self,
        spec: ValidationQuerySpec,
        run_integration_tests: bool = True
    ) -> Tuple[bool, List[str]]:
        """
        Test a validation query against all its test cases.

        Args:
            spec: Validation query specification
            run_integration_tests: If True, run against real BigQuery data

        Returns:
            (passed: bool, errors: List[str])
        """
        errors = []

        if not run_integration_tests:
            logger.info(f"Skipping integration tests for {spec.name}")
            return True, []

        for test_case in spec.test_cases:
            try:
                result = self._run_test_case(spec, test_case)

                if test_case.expected_result == 'should_find_issues':
                    if result['issue_count'] < test_case.minimum_issues:
                        errors.append(
                            f"FAILED: {test_case.name} - Expected at least "
                            f"{test_case.minimum_issues} issues, found {result['issue_count']}. "
                            f"Validation query may have logic errors!"
                        )
                elif test_case.expected_result == 'should_be_clean':
                    if result['issue_count'] > 0:
                        errors.append(
                            f"FAILED: {test_case.name} - Expected clean data, "
                            f"found {result['issue_count']} issues"
                        )

                # Check for suspicious "always zero" results
                if result['issue_count'] == 0 and test_case.expected_result == 'should_find_issues':
                    logger.warning(
                        f"⚠️  {test_case.name} returned 0 issues but should find issues. "
                        f"This may indicate a flawed validation query (Session 123)."
                    )

            except Exception as e:
                errors.append(f"ERROR: {test_case.name} - {str(e)}")

        passed = len(errors) == 0

        if not passed:
            logger.error(f"Validation query '{spec.name}' failed tests:\n" + "\n".join(errors))
        else:
            logger.info(f"✅ Validation query '{spec.name}' passed all tests")

        return passed, errors

    def _run_test_case(
        self,
        spec: ValidationQuerySpec,
        test_case: ValidationTestCase
    ) -> Dict:
        """Run a single test case and return results."""
        # Execute the validation query with test parameters
        query = spec.query_template.format(**test_case.test_parameters)

        logger.info(f"Running test case: {test_case.name}")
        logger.debug(f"Query:\n{query}")

        result = self.bq_client.query(query).to_dataframe()

        # Extract issue count from result
        # Validation queries should return a column indicating issue count/percentage
        if 'dnp_polluted' in result.columns:
            issue_count = result.iloc[0]['dnp_polluted'] if not result.empty else 0
        elif 'issue_count' in result.columns:
            issue_count = result.iloc[0]['issue_count'] if not result.empty else 0
        else:
            issue_count = len(result)  # Number of rows = number of issues

        return {'issue_count': int(issue_count), 'raw_result': result}


# Example: DNP Pollution Validation Spec
DNP_POLLUTION_VALIDATION_SPEC = ValidationQuerySpec(
    name='dnp_pollution_check',
    description='Check for DNP players polluting the player_daily_cache',
    query_template="""
    -- DNP Pollution Check (Session 123 Corrected)
    --
    -- DATA MODEL ASSUMPTIONS:
    -- - cache_date is the ANALYSIS date, not the game date
    -- - Cache contains games from BEFORE cache_date
    -- - LEFT JOIN ensures we count all cached players even if no PGS match
    --
    -- CRITICAL: If this query returns 0, verify the join is working correctly
    -- by checking join_count > 0

    SELECT
      pdc.cache_date,
      COUNT(DISTINCT pdc.player_lookup) as total_cached,
      COUNT(DISTINCT CASE
        WHEN pgs.is_dnp = TRUE
        THEN pdc.player_lookup
      END) as dnp_polluted,
      ROUND(100.0 * COUNT(DISTINCT CASE
        WHEN pgs.is_dnp = TRUE
        THEN pdc.player_lookup
      END) / NULLIF(COUNT(DISTINCT pdc.player_lookup), 0), 1) as dnp_pct,
      -- Meta field: number of non-null joins (should be > 0)
      COUNT(pgs.player_lookup) as join_count
    FROM `{project}.nba_precompute.player_daily_cache` pdc
    LEFT JOIN `{project}.nba_analytics.player_game_summary` pgs
      ON pdc.player_lookup = pgs.player_lookup
      AND pgs.game_date < pdc.cache_date  -- Games BEFORE cache date
      AND pgs.game_date >= DATE_SUB(pdc.cache_date, INTERVAL 30 DAY)
    WHERE pdc.cache_date = '{cache_date}'
    GROUP BY pdc.cache_date
    """,
    data_model_assumptions=[
        "cache_date is the analysis date, NOT the game date",
        "Cache aggregates data from games BEFORE cache_date",
        "LEFT JOIN ensures we count all cached players even if no PGS match",
        "join_count > 0 validates that the join is working correctly"
    ],
    test_cases=[
        ValidationTestCase(
            name='historical_known_polluted_feb4',
            description='Feb 4, 2026 cache known to have 67% DNP pollution (Session 123)',
            test_parameters={
                'project': 'nba-props-platform',
                'cache_date': '2026-02-04'
            },
            expected_result='should_find_issues',
            minimum_issues=100  # We know 146 players were polluted
        ),
        # Add more test cases for other known dates
    ]
)


def validate_dnp_pollution_query():
    """
    Quick validation function for DNP pollution check.
    Can be run standalone or as part of test suite.
    """
    from google.cloud import bigquery

    client = bigquery.Client()
    tester = ValidationQueryTester(client)

    passed, errors = tester.test_validation_query(DNP_POLLUTION_VALIDATION_SPEC)

    if not passed:
        print("❌ DNP Pollution validation query FAILED tests:")
        for error in errors:
            print(f"  - {error}")
        return False
    else:
        print("✅ DNP Pollution validation query PASSED all tests")
        return True


if __name__ == '__main__':
    import sys
    success = validate_dnp_pollution_query()
    sys.exit(0 if success else 1)
