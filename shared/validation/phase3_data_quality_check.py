"""
Phase 3 Data Quality Check for Phase Boundary Validation

Validates data quality BEFORE triggering Phase 4 to prevent cascade failures
from incomplete or low-quality Phase 3 analytics data.

Checks performed:
1. NULL rates for critical fields (blocks if > threshold)
2. Field completeness (all required fields present)
3. Minutes coverage (blocks if < 80% of expected players have minutes data)
4. Game coverage (actual games vs scheduled games)
5. Record count validation (minimum expected records)

Usage:
    from shared.validation.phase3_data_quality_check import Phase3DataQualityChecker

    checker = Phase3DataQualityChecker(
        bq_client=bigquery.Client(),
        project_id='nba-props-platform'
    )

    result = checker.run_quality_check(game_date='2026-01-28')

    if not result.passed:
        # Block Phase 4 transition
        raise ValueError(f"Quality check failed: {result.blocking_issues}")

Version: 1.0
Created: January 28, 2026
Part of: Pipeline Resilience Improvements
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class CheckSeverity(Enum):
    """Severity levels for quality check issues."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"  # Blocking issue - will prevent Phase 4


class CheckCategory(Enum):
    """Categories of quality checks."""
    NULL_RATE = "null_rate"
    FIELD_COMPLETENESS = "field_completeness"
    MINUTES_COVERAGE = "minutes_coverage"
    GAME_COVERAGE = "game_coverage"
    RECORD_COUNT = "record_count"


@dataclass
class QualityIssue:
    """A single quality issue found during validation."""
    category: CheckCategory
    severity: CheckSeverity
    table_name: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QualityCheckResult:
    """Result of Phase 3 data quality check."""
    game_date: str
    passed: bool
    check_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    issues: List[QualityIssue] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def blocking_issues(self) -> List[QualityIssue]:
        """Return only ERROR severity issues that block Phase 4."""
        return [i for i in self.issues if i.severity == CheckSeverity.ERROR]

    @property
    def warnings(self) -> List[QualityIssue]:
        """Return WARNING severity issues."""
        return [i for i in self.issues if i.severity == CheckSeverity.WARNING]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage."""
        return {
            'game_date': self.game_date,
            'passed': self.passed,
            'check_timestamp': self.check_timestamp.isoformat(),
            'blocking_issues_count': len(self.blocking_issues),
            'warnings_count': len(self.warnings),
            'issues': [
                {
                    'category': issue.category.value,
                    'severity': issue.severity.value,
                    'table_name': issue.table_name,
                    'message': issue.message,
                    'details': issue.details
                }
                for issue in self.issues
            ],
            'metrics': self.metrics
        }


# Configuration for Phase 3 analytics tables
PHASE3_ANALYTICS_TABLES = [
    {
        'table': 'player_game_summary',
        'dataset': 'nba_analytics',
        'date_column': 'game_date',
        'critical_fields': ['player_lookup', 'game_id', 'team_abbrev', 'minutes_played', 'points'],
        'required_fields': ['assists', 'rebounds_total', 'turnovers', 'fg_made', 'fg_attempted'],
        'has_minutes': True,
        'scope': 'players',
    },
    {
        'table': 'team_defense_game_summary',
        'dataset': 'nba_analytics',
        'date_column': 'game_date',
        'critical_fields': ['team_abbrev', 'game_id', 'opponent_abbrev'],
        'required_fields': ['points_allowed', 'fg_pct_allowed'],
        'has_minutes': False,
        'scope': 'teams',
    },
    {
        'table': 'team_offense_game_summary',
        'dataset': 'nba_analytics',
        'date_column': 'game_date',
        'critical_fields': ['team_abbrev', 'game_id', 'opponent_abbrev'],
        'required_fields': ['points_scored', 'fg_pct'],
        'has_minutes': False,
        'scope': 'teams',
    },
    {
        'table': 'upcoming_player_game_context',
        'dataset': 'nba_analytics',
        'date_column': 'game_date',
        'critical_fields': ['player_lookup', 'game_id', 'team_abbrev'],
        'required_fields': ['opponent_abbrev', 'is_home'],
        'has_minutes': False,
        'scope': 'players',
    },
    {
        'table': 'upcoming_team_game_context',
        'dataset': 'nba_analytics',
        'date_column': 'game_date',
        'critical_fields': ['team_abbrev', 'game_id', 'opponent_abbrev'],
        'required_fields': ['is_home'],
        'has_minutes': False,
        'scope': 'teams',
    },
]


class Phase3DataQualityChecker:
    """
    Validates Phase 3 analytics data quality before Phase 4 transition.

    Configuration via environment variables:
    - PHASE3_QUALITY_CHECK_ENABLED: Enable/disable checks (default: true)
    - PHASE3_NULL_RATE_THRESHOLD: Max NULL rate for critical fields (default: 5.0%)
    - PHASE3_MINUTES_COVERAGE_THRESHOLD: Min minutes coverage (default: 80.0%)
    - PHASE3_GAME_COVERAGE_THRESHOLD: Min game coverage (default: 80.0%)
    """

    def __init__(
        self,
        bq_client: bigquery.Client,
        project_id: str,
        null_rate_threshold: Optional[float] = None,
        minutes_coverage_threshold: Optional[float] = None,
        game_coverage_threshold: Optional[float] = None,
    ):
        """
        Initialize the Phase 3 data quality checker.

        Args:
            bq_client: BigQuery client
            project_id: GCP project ID
            null_rate_threshold: Max NULL rate for critical fields (overrides env)
            minutes_coverage_threshold: Min minutes coverage (overrides env)
            game_coverage_threshold: Min game coverage (overrides env)
        """
        self.bq_client = bq_client
        self.project_id = project_id

        # Load configuration from environment with defaults
        self.enabled = os.getenv('PHASE3_QUALITY_CHECK_ENABLED', 'true').lower() == 'true'

        self.null_rate_threshold = null_rate_threshold or float(
            os.getenv('PHASE3_NULL_RATE_THRESHOLD', '5.0')
        )

        self.minutes_coverage_threshold = minutes_coverage_threshold or float(
            os.getenv('PHASE3_MINUTES_COVERAGE_THRESHOLD', '80.0')
        )

        self.game_coverage_threshold = game_coverage_threshold or float(
            os.getenv('PHASE3_GAME_COVERAGE_THRESHOLD', '80.0')
        )

        logger.info(
            f"Phase3DataQualityChecker initialized: enabled={self.enabled}, "
            f"null_rate_threshold={self.null_rate_threshold}%, "
            f"minutes_coverage_threshold={self.minutes_coverage_threshold}%, "
            f"game_coverage_threshold={self.game_coverage_threshold}%"
        )

    def run_quality_check(self, game_date: str) -> QualityCheckResult:
        """
        Run all quality checks for a game date.

        Args:
            game_date: Date to check in YYYY-MM-DD format

        Returns:
            QualityCheckResult with pass/fail status and detailed issues
        """
        if not self.enabled:
            logger.info("Phase 3 quality check disabled, returning pass")
            return QualityCheckResult(
                game_date=game_date,
                passed=True,
                metrics={'check_disabled': True}
            )

        logger.info(f"Running Phase 3 data quality check for {game_date}")

        issues: List[QualityIssue] = []
        metrics: Dict[str, Any] = {}

        # Get expected game count from schedule
        expected_games = self._get_expected_game_count(game_date)
        metrics['expected_games'] = expected_games

        # Run checks for each table
        for table_config in PHASE3_ANALYTICS_TABLES:
            table_name = table_config['table']

            # 1. Check NULL rates for critical fields
            null_issues = self._check_null_rates(game_date, table_config)
            issues.extend(null_issues)

            # 2. Check field completeness
            completeness_issues = self._check_field_completeness(game_date, table_config)
            issues.extend(completeness_issues)

            # 3. Check record count
            record_count, count_issues = self._check_record_count(
                game_date, table_config, expected_games
            )
            issues.extend(count_issues)
            metrics[f'{table_name}_record_count'] = record_count

            # 4. Check game coverage (for team tables)
            if table_config['scope'] == 'teams':
                game_coverage, coverage_issues = self._check_game_coverage(
                    game_date, table_config, expected_games
                )
                issues.extend(coverage_issues)
                metrics[f'{table_name}_game_coverage_pct'] = game_coverage

        # 5. Check minutes coverage for player_game_summary
        minutes_coverage, minutes_issues = self._check_minutes_coverage(game_date)
        issues.extend(minutes_issues)
        metrics['minutes_coverage_pct'] = minutes_coverage

        # Determine overall pass/fail
        has_blocking_issues = any(i.severity == CheckSeverity.ERROR for i in issues)
        passed = not has_blocking_issues

        result = QualityCheckResult(
            game_date=game_date,
            passed=passed,
            issues=issues,
            metrics=metrics
        )

        if passed:
            logger.info(
                f"Phase 3 quality check PASSED for {game_date} "
                f"(warnings: {len(result.warnings)})"
            )
        else:
            logger.warning(
                f"Phase 3 quality check FAILED for {game_date} "
                f"(blocking issues: {len(result.blocking_issues)}, "
                f"warnings: {len(result.warnings)})"
            )
            for issue in result.blocking_issues:
                logger.error(f"  BLOCKING: {issue.message}")

        return result

    def _get_expected_game_count(self, game_date: str) -> int:
        """Get expected number of games from schedule."""
        try:
            query = f"""
            SELECT COUNT(DISTINCT game_id) as game_count
            FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
            WHERE game_date = '{game_date}'
              AND game_status_text NOT IN ('Postponed', 'Cancelled')
            """

            result = list(self.bq_client.query(query).result())
            return result[0].game_count if result else 0

        except Exception as e:
            logger.warning(f"Failed to get expected game count: {e}")
            return 0

    def _check_null_rates(
        self,
        game_date: str,
        table_config: Dict[str, Any]
    ) -> List[QualityIssue]:
        """Check NULL rates for critical fields in a table."""
        issues = []
        table_name = table_config['table']
        dataset = table_config['dataset']
        date_column = table_config['date_column']
        critical_fields = table_config['critical_fields']

        try:
            # Build query to check NULL rates for all critical fields at once
            null_checks = ', '.join([
                f"COUNTIF({field} IS NULL) * 100.0 / COUNT(*) as {field}_null_pct"
                for field in critical_fields
            ])

            query = f"""
            SELECT
                COUNT(*) as total_records,
                {null_checks}
            FROM `{self.project_id}.{dataset}.{table_name}`
            WHERE {date_column} = '{game_date}'
            """

            result = list(self.bq_client.query(query).result())

            if not result or result[0].total_records == 0:
                issues.append(QualityIssue(
                    category=CheckCategory.RECORD_COUNT,
                    severity=CheckSeverity.ERROR,
                    table_name=table_name,
                    message=f"No records found in {table_name} for {game_date}",
                    details={'game_date': game_date}
                ))
                return issues

            row = result[0]
            total_records = row.total_records

            for field in critical_fields:
                null_pct = getattr(row, f'{field}_null_pct', 0) or 0

                if null_pct > self.null_rate_threshold:
                    severity = CheckSeverity.ERROR if null_pct > 50 else CheckSeverity.WARNING

                    issues.append(QualityIssue(
                        category=CheckCategory.NULL_RATE,
                        severity=severity,
                        table_name=table_name,
                        message=(
                            f"High NULL rate for {field} in {table_name}: "
                            f"{null_pct:.1f}% > {self.null_rate_threshold}%"
                        ),
                        details={
                            'field': field,
                            'null_pct': null_pct,
                            'threshold': self.null_rate_threshold,
                            'total_records': total_records
                        }
                    ))

        except Exception as e:
            logger.error(f"Error checking NULL rates for {table_name}: {e}", exc_info=True)
            issues.append(QualityIssue(
                category=CheckCategory.NULL_RATE,
                severity=CheckSeverity.WARNING,
                table_name=table_name,
                message=f"Failed to check NULL rates: {str(e)}",
                details={'error': str(e)}
            ))

        return issues

    def _check_field_completeness(
        self,
        game_date: str,
        table_config: Dict[str, Any]
    ) -> List[QualityIssue]:
        """Check that all required fields exist and have some data."""
        issues = []
        table_name = table_config['table']
        dataset = table_config['dataset']
        date_column = table_config['date_column']
        required_fields = table_config.get('required_fields', [])

        if not required_fields:
            return issues

        try:
            # Check which columns exist
            table_ref = f"{self.project_id}.{dataset}.{table_name}"
            table = self.bq_client.get_table(table_ref)
            existing_columns = {field.name for field in table.schema}

            # Check for missing columns
            for field in required_fields:
                if field not in existing_columns:
                    issues.append(QualityIssue(
                        category=CheckCategory.FIELD_COMPLETENESS,
                        severity=CheckSeverity.WARNING,
                        table_name=table_name,
                        message=f"Required field '{field}' missing from {table_name} schema",
                        details={'missing_field': field}
                    ))

        except Exception as e:
            logger.error(f"Error checking field completeness for {table_name}: {e}", exc_info=True)

        return issues

    def _check_record_count(
        self,
        game_date: str,
        table_config: Dict[str, Any],
        expected_games: int
    ) -> Tuple[int, List[QualityIssue]]:
        """Check that table has expected number of records."""
        issues = []
        table_name = table_config['table']
        dataset = table_config['dataset']
        date_column = table_config['date_column']
        scope = table_config['scope']

        try:
            query = f"""
            SELECT COUNT(*) as record_count
            FROM `{self.project_id}.{dataset}.{table_name}`
            WHERE {date_column} = '{game_date}'
            """

            result = list(self.bq_client.query(query).result())
            record_count = result[0].record_count if result else 0

            # Determine expected minimum records
            if scope == 'teams':
                # 2 teams per game (home and away)
                min_expected = expected_games * 2
            else:
                # Players - expect at least 10 per game average
                min_expected = expected_games * 10

            if record_count == 0:
                issues.append(QualityIssue(
                    category=CheckCategory.RECORD_COUNT,
                    severity=CheckSeverity.ERROR,
                    table_name=table_name,
                    message=f"No records in {table_name} for {game_date}",
                    details={
                        'record_count': record_count,
                        'expected_games': expected_games
                    }
                ))
            elif record_count < min_expected * 0.5:
                # Less than 50% of expected is an error
                issues.append(QualityIssue(
                    category=CheckCategory.RECORD_COUNT,
                    severity=CheckSeverity.ERROR,
                    table_name=table_name,
                    message=(
                        f"Very low record count in {table_name}: "
                        f"{record_count} < {min_expected * 0.5:.0f} (50% of expected)"
                    ),
                    details={
                        'record_count': record_count,
                        'min_expected': min_expected
                    }
                ))
            elif record_count < min_expected * 0.8:
                # Less than 80% is a warning
                issues.append(QualityIssue(
                    category=CheckCategory.RECORD_COUNT,
                    severity=CheckSeverity.WARNING,
                    table_name=table_name,
                    message=(
                        f"Low record count in {table_name}: "
                        f"{record_count} < {min_expected * 0.8:.0f} (80% of expected)"
                    ),
                    details={
                        'record_count': record_count,
                        'min_expected': min_expected
                    }
                ))

            return record_count, issues

        except Exception as e:
            logger.error(f"Error checking record count for {table_name}: {e}", exc_info=True)
            return 0, [QualityIssue(
                category=CheckCategory.RECORD_COUNT,
                severity=CheckSeverity.WARNING,
                table_name=table_name,
                message=f"Failed to check record count: {str(e)}",
                details={'error': str(e)}
            )]

    def _check_game_coverage(
        self,
        game_date: str,
        table_config: Dict[str, Any],
        expected_games: int
    ) -> Tuple[float, List[QualityIssue]]:
        """Check game coverage for team tables."""
        issues = []
        table_name = table_config['table']
        dataset = table_config['dataset']
        date_column = table_config['date_column']

        if expected_games == 0:
            return 100.0, issues

        try:
            query = f"""
            SELECT COUNT(DISTINCT game_id) as actual_games
            FROM `{self.project_id}.{dataset}.{table_name}`
            WHERE {date_column} = '{game_date}'
            """

            result = list(self.bq_client.query(query).result())
            actual_games = result[0].actual_games if result else 0

            coverage_pct = (actual_games / expected_games) * 100 if expected_games > 0 else 0

            if coverage_pct < self.game_coverage_threshold:
                severity = CheckSeverity.ERROR if coverage_pct < 50 else CheckSeverity.WARNING

                issues.append(QualityIssue(
                    category=CheckCategory.GAME_COVERAGE,
                    severity=severity,
                    table_name=table_name,
                    message=(
                        f"Low game coverage in {table_name}: "
                        f"{actual_games}/{expected_games} games ({coverage_pct:.1f}%) "
                        f"< {self.game_coverage_threshold}%"
                    ),
                    details={
                        'actual_games': actual_games,
                        'expected_games': expected_games,
                        'coverage_pct': coverage_pct,
                        'threshold': self.game_coverage_threshold
                    }
                ))

            return coverage_pct, issues

        except Exception as e:
            logger.error(f"Error checking game coverage for {table_name}: {e}", exc_info=True)
            return 0.0, [QualityIssue(
                category=CheckCategory.GAME_COVERAGE,
                severity=CheckSeverity.WARNING,
                table_name=table_name,
                message=f"Failed to check game coverage: {str(e)}",
                details={'error': str(e)}
            )]

    def _check_minutes_coverage(
        self,
        game_date: str
    ) -> Tuple[float, List[QualityIssue]]:
        """
        Check minutes coverage in player_game_summary.

        Minutes data is critical for predictions - blocks if below threshold.
        """
        issues = []
        table_name = 'player_game_summary'

        try:
            query = f"""
            WITH scheduled_players AS (
                -- Get expected players from schedule/rosters
                SELECT COUNT(DISTINCT player_lookup) as expected_players
                FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
                WHERE game_date = '{game_date}'
            ),
            actual_players AS (
                -- Get players with valid minutes data
                SELECT
                    COUNT(*) as total_players,
                    COUNTIF(minutes_played IS NOT NULL AND minutes_played > 0) as players_with_minutes
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date = '{game_date}'
            )
            SELECT
                s.expected_players,
                a.total_players,
                a.players_with_minutes,
                SAFE_DIVIDE(a.players_with_minutes, a.total_players) * 100 as minutes_coverage_pct
            FROM scheduled_players s
            CROSS JOIN actual_players a
            """

            result = list(self.bq_client.query(query).result())

            if not result:
                return 0.0, [QualityIssue(
                    category=CheckCategory.MINUTES_COVERAGE,
                    severity=CheckSeverity.WARNING,
                    table_name=table_name,
                    message="Could not calculate minutes coverage",
                    details={}
                )]

            row = result[0]
            coverage_pct = row.minutes_coverage_pct or 0.0
            total_players = row.total_players or 0
            players_with_minutes = row.players_with_minutes or 0

            if coverage_pct < self.minutes_coverage_threshold:
                severity = CheckSeverity.ERROR  # Always blocking - minutes are critical

                issues.append(QualityIssue(
                    category=CheckCategory.MINUTES_COVERAGE,
                    severity=severity,
                    table_name=table_name,
                    message=(
                        f"Minutes coverage below threshold: "
                        f"{players_with_minutes}/{total_players} players ({coverage_pct:.1f}%) "
                        f"< {self.minutes_coverage_threshold}%"
                    ),
                    details={
                        'total_players': total_players,
                        'players_with_minutes': players_with_minutes,
                        'coverage_pct': coverage_pct,
                        'threshold': self.minutes_coverage_threshold
                    }
                ))

            return coverage_pct, issues

        except Exception as e:
            logger.error(f"Error checking minutes coverage: {e}", exc_info=True)
            # Non-blocking on query errors - don't want infra issues to block pipeline
            return 100.0, [QualityIssue(
                category=CheckCategory.MINUTES_COVERAGE,
                severity=CheckSeverity.WARNING,
                table_name=table_name,
                message=f"Failed to check minutes coverage: {str(e)}",
                details={'error': str(e)}
            )]

    def generate_report(self, result: QualityCheckResult) -> str:
        """Generate a human-readable report from check results."""
        lines = [
            f"Phase 3 Data Quality Report for {result.game_date}",
            "=" * 60,
            f"Status: {'PASSED' if result.passed else 'FAILED'}",
            f"Check Time: {result.check_timestamp.isoformat()}",
            "",
        ]

        # Metrics summary
        lines.append("Metrics:")
        for key, value in result.metrics.items():
            if isinstance(value, float):
                lines.append(f"  {key}: {value:.1f}")
            else:
                lines.append(f"  {key}: {value}")
        lines.append("")

        # Blocking issues
        if result.blocking_issues:
            lines.append(f"BLOCKING ISSUES ({len(result.blocking_issues)}):")
            for issue in result.blocking_issues:
                lines.append(f"  [ERROR] {issue.table_name}: {issue.message}")
            lines.append("")

        # Warnings
        if result.warnings:
            lines.append(f"Warnings ({len(result.warnings)}):")
            for issue in result.warnings:
                lines.append(f"  [WARN] {issue.table_name}: {issue.message}")
            lines.append("")

        if not result.issues:
            lines.append("No issues found.")

        return "\n".join(lines)


# Convenience function for quick checks
def check_phase3_quality(
    game_date: str,
    project_id: str = None,
    bq_client: bigquery.Client = None
) -> QualityCheckResult:
    """
    Convenience function to run Phase 3 quality check.

    Args:
        game_date: Date to check (YYYY-MM-DD)
        project_id: GCP project ID (defaults to env or config)
        bq_client: BigQuery client (creates new one if not provided)

    Returns:
        QualityCheckResult
    """
    if project_id is None:
        from shared.config.gcp_config import get_project_id
        project_id = get_project_id()

    if bq_client is None:
        bq_client = bigquery.Client(project=project_id)

    checker = Phase3DataQualityChecker(
        bq_client=bq_client,
        project_id=project_id
    )

    return checker.run_quality_check(game_date)


# CLI interface for testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    if len(sys.argv) < 2:
        print("Usage: python phase3_data_quality_check.py <game_date>")
        print("Example: python phase3_data_quality_check.py 2026-01-28")
        sys.exit(1)

    game_date = sys.argv[1]

    result = check_phase3_quality(game_date)

    # Generate and print report
    checker = Phase3DataQualityChecker(
        bq_client=bigquery.Client(),
        project_id='nba-props-platform'
    )
    print(checker.generate_report(result))

    # Exit with appropriate code
    sys.exit(0 if result.passed else 1)
