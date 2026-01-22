"""
Phase Boundary Validator

Validates data quality and completeness at phase transitions to catch issues early
and prevent cascading failures.

Validates:
1. Game count (actual vs expected from schedule)
2. Processor completions (all expected processors ran)
3. Data quality metrics (average quality score, completeness %)

Created: January 21, 2026
Part of: Robustness Improvements Implementation
"""

import logging
import os
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ValidationSeverity(Enum):
    """Severity levels for validation issues."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ValidationMode(Enum):
    """Validation enforcement modes."""
    DISABLED = "disabled"  # No validation
    WARNING = "warning"    # Log warnings but don't block
    BLOCKING = "blocking"  # Raise errors and block pipeline


class PhaseValidationError(Exception):
    """Exception raised when phase validation fails in BLOCKING mode."""

    def __init__(self, message: str, validation_result: Optional['ValidationResult'] = None):
        super().__init__(message)
        self.validation_result = validation_result


@dataclass
class ValidationIssue:
    """A single validation issue."""
    validation_type: str
    severity: ValidationSeverity
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of phase boundary validation."""
    game_date: date
    phase_name: str
    is_valid: bool
    mode: ValidationMode
    issues: List[ValidationIssue] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def has_warnings(self) -> bool:
        """Check if result has any warnings."""
        return any(issue.severity == ValidationSeverity.WARNING for issue in self.issues)

    @property
    def has_errors(self) -> bool:
        """Check if result has any errors."""
        return any(issue.severity == ValidationSeverity.ERROR for issue in self.issues)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage."""
        return {
            'game_date': self.game_date.isoformat() if isinstance(self.game_date, date) else str(self.game_date),
            'phase_name': self.phase_name,
            'is_valid': self.is_valid,
            'mode': self.mode.value,
            'issues': [
                {
                    'validation_type': issue.validation_type,
                    'severity': issue.severity.value,
                    'message': issue.message,
                    'details': issue.details
                }
                for issue in self.issues
            ],
            'metrics': self.metrics,
            'timestamp': self.timestamp.isoformat()
        }


class PhaseBoundaryValidator:
    """
    Validates phase transitions to catch data quality issues early.

    Configuration via environment variables:
    - PHASE_VALIDATION_ENABLED: Enable validation (default: true)
    - PHASE_VALIDATION_MODE: Validation mode (warning|blocking, default: warning)
    - PHASE_VALIDATION_GAME_COUNT_THRESHOLD: Min game count ratio (default: 0.8)
    - PHASE_VALIDATION_QUALITY_THRESHOLD: Min quality score (default: 0.7)

    Usage:
        from google.cloud import bigquery

        validator = PhaseBoundaryValidator(
            bq_client=bigquery.Client(),
            project_id="nba-data-prod",
            phase_name="phase2"
        )

        result = validator.run_validation(
            game_date=date(2026, 1, 21),
            validation_config={
                'check_game_count': True,
                'expected_game_count': 10,
                'check_processors': True,
                'expected_processors': ['bdl_games', 'bdl_player_boxscores'],
                'check_data_quality': True
            }
        )

        if result.has_errors and result.mode == ValidationMode.BLOCKING:
            raise ValueError(f"Validation failed: {result}")
    """

    def __init__(
        self,
        bq_client,
        project_id: str,
        phase_name: str,
        mode: Optional[ValidationMode] = None
    ):
        """
        Initialize phase boundary validator.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
            phase_name: Name of phase (phase1, phase2, phase3, etc.)
            mode: Validation mode (overrides env var if provided)
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.phase_name = phase_name

        # Load configuration
        self.enabled = os.getenv('PHASE_VALIDATION_ENABLED', 'true').lower() == 'true'

        if mode is None:
            mode_str = os.getenv('PHASE_VALIDATION_MODE', 'warning').lower()
            self.mode = ValidationMode.BLOCKING if mode_str == 'blocking' else ValidationMode.WARNING
        else:
            self.mode = mode

        self.game_count_threshold = float(os.getenv('PHASE_VALIDATION_GAME_COUNT_THRESHOLD', '0.8'))
        self.quality_threshold = float(os.getenv('PHASE_VALIDATION_QUALITY_THRESHOLD', '0.7'))

        logger.info(
            f"PhaseBoundaryValidator initialized for {phase_name}: "
            f"enabled={self.enabled}, mode={self.mode.value}, "
            f"game_count_threshold={self.game_count_threshold}, "
            f"quality_threshold={self.quality_threshold}"
        )

    def validate_game_count(
        self,
        game_date: date,
        actual: int,
        expected: int
    ) -> Optional[ValidationIssue]:
        """
        Validate actual game count against expected.

        Args:
            game_date: Date of games
            actual: Actual number of games found
            expected: Expected number of games from schedule

        Returns:
            ValidationIssue if invalid, None if valid
        """
        if expected == 0:
            # No games expected, no validation needed
            return None

        ratio = actual / expected if expected > 0 else 0

        if ratio < self.game_count_threshold:
            severity = ValidationSeverity.ERROR if ratio < 0.5 else ValidationSeverity.WARNING

            return ValidationIssue(
                validation_type='game_count',
                severity=severity,
                message=f"Game count below threshold: {actual}/{expected} ({ratio:.1%})",
                details={
                    'game_date': game_date.isoformat(),
                    'actual_count': actual,
                    'expected_count': expected,
                    'ratio': ratio,
                    'threshold': self.game_count_threshold
                }
            )

        return None

    def validate_processor_completions(
        self,
        game_date: date,
        completed: List[str],
        expected: List[str]
    ) -> List[ValidationIssue]:
        """
        Validate that all expected processors completed.

        Args:
            game_date: Date of processing
            completed: List of processor names that completed
            expected: List of expected processor names

        Returns:
            List of ValidationIssues (one per missing processor)
        """
        issues = []
        completed_set = set(completed)
        expected_set = set(expected)

        missing = expected_set - completed_set

        for processor_name in missing:
            # Determine severity based on processor criticality
            # Could be enhanced with processor importance mapping
            severity = ValidationSeverity.ERROR

            issues.append(ValidationIssue(
                validation_type='processor_completion',
                severity=severity,
                message=f"Processor '{processor_name}' did not complete",
                details={
                    'game_date': game_date.isoformat(),
                    'processor_name': processor_name,
                    'completed_processors': list(completed),
                    'expected_processors': list(expected)
                }
            ))

        return issues

    def validate_data_quality(
        self,
        game_date: date,
        dataset: str,
        table: str
    ) -> Optional[ValidationIssue]:
        """
        Validate data quality metrics for a table.

        Checks average quality score if quality_score column exists.

        Args:
            game_date: Date of data
            dataset: BigQuery dataset name
            table: BigQuery table name

        Returns:
            ValidationIssue if quality too low, None if valid
        """
        try:
            # Query for average quality score
            query = f"""
            SELECT
                AVG(quality_score) as avg_quality_score,
                COUNT(*) as record_count
            FROM `{self.project_id}.{dataset}.{table}`
            WHERE DATE(created_at) = '{game_date.isoformat()}'
            """

            query_job = self.bq_client.query(query)
            results = list(query_job.result())

            if not results or results[0].record_count == 0:
                # No records found - this is an issue
                return ValidationIssue(
                    validation_type='data_quality',
                    severity=ValidationSeverity.ERROR,
                    message=f"No records found in {dataset}.{table} for {game_date}",
                    details={
                        'game_date': game_date.isoformat(),
                        'dataset': dataset,
                        'table': table
                    }
                )

            avg_quality = results[0].avg_quality_score
            record_count = results[0].record_count

            if avg_quality is None:
                # Table doesn't have quality_score column - skip quality check
                logger.debug(f"Table {dataset}.{table} has no quality_score column, skipping quality check")
                return None

            if avg_quality < self.quality_threshold:
                severity = ValidationSeverity.ERROR if avg_quality < 0.5 else ValidationSeverity.WARNING

                return ValidationIssue(
                    validation_type='data_quality',
                    severity=severity,
                    message=f"Data quality below threshold: {avg_quality:.2%} < {self.quality_threshold:.2%}",
                    details={
                        'game_date': game_date.isoformat(),
                        'dataset': dataset,
                        'table': table,
                        'avg_quality_score': avg_quality,
                        'record_count': record_count,
                        'threshold': self.quality_threshold
                    }
                )

            return None

        except Exception as e:
            logger.error(f"Error validating data quality for {dataset}.{table}: {e}")
            return ValidationIssue(
                validation_type='data_quality',
                severity=ValidationSeverity.WARNING,
                message=f"Failed to check data quality: {str(e)}",
                details={
                    'game_date': game_date.isoformat(),
                    'dataset': dataset,
                    'table': table,
                    'error': str(e)
                }
            )

    def get_actual_game_count(self, game_date: date, dataset: str, table: str) -> int:
        """
        Get actual game count from BigQuery table.

        Args:
            game_date: Date of games
            dataset: BigQuery dataset
            table: BigQuery table

        Returns:
            Number of games found
        """
        try:
            query = f"""
            SELECT COUNT(DISTINCT game_id) as game_count
            FROM `{self.project_id}.{dataset}.{table}`
            WHERE DATE(game_date) = '{game_date.isoformat()}'
            """

            query_job = self.bq_client.query(query)
            results = list(query_job.result())

            if results:
                return results[0].game_count

            return 0

        except Exception as e:
            logger.error(f"Error getting game count from {dataset}.{table}: {e}")
            return 0

    def get_completed_processors(self, game_date: date) -> List[str]:
        """
        Get list of processors that completed for a date.

        Queries nba_orchestration.phase1_runs table.

        Args:
            game_date: Date of processing

        Returns:
            List of processor names that completed
        """
        try:
            query = f"""
            SELECT DISTINCT scraper_name
            FROM `{self.project_id}.nba_orchestration.phase1_runs`
            WHERE DATE(run_timestamp) = '{game_date.isoformat()}'
            AND status = 'success'
            """

            query_job = self.bq_client.query(query)
            results = list(query_job.result())

            return [row.scraper_name for row in results]

        except Exception as e:
            logger.error(f"Error getting completed processors: {e}")
            return []

    def run_validation(
        self,
        game_date: date,
        validation_config: Dict[str, Any]
    ) -> ValidationResult:
        """
        Run all configured validations for a phase boundary.

        Args:
            game_date: Date to validate
            validation_config: Configuration dictionary with keys:
                - check_game_count: bool
                - expected_game_count: int (if check_game_count)
                - game_count_dataset: str (optional, default: nba_raw)
                - game_count_table: str (optional, default: bdl_games)
                - check_processors: bool
                - expected_processors: List[str] (if check_processors)
                - check_data_quality: bool
                - quality_tables: List[tuple[str, str]] (if check_data_quality, dataset/table pairs)

        Returns:
            ValidationResult with all issues found
        """
        if not self.enabled:
            logger.info(f"Phase validation disabled for {self.phase_name}, skipping")
            return ValidationResult(
                game_date=game_date,
                phase_name=self.phase_name,
                is_valid=True,
                mode=ValidationMode.DISABLED
            )

        logger.info(f"Running phase boundary validation for {self.phase_name} on {game_date}")

        issues = []
        metrics = {}

        # 1. Validate game count
        if validation_config.get('check_game_count', False):
            expected_count = validation_config.get('expected_game_count', 0)
            dataset = validation_config.get('game_count_dataset', 'nba_raw')
            table = validation_config.get('game_count_table', 'bdl_games')

            actual_count = self.get_actual_game_count(game_date, dataset, table)
            metrics['actual_game_count'] = actual_count
            metrics['expected_game_count'] = expected_count

            issue = self.validate_game_count(game_date, actual_count, expected_count)
            if issue:
                issues.append(issue)

        # 2. Validate processor completions
        if validation_config.get('check_processors', False):
            expected_processors = validation_config.get('expected_processors', [])
            completed_processors = self.get_completed_processors(game_date)

            metrics['completed_processors'] = completed_processors
            metrics['expected_processors'] = expected_processors

            processor_issues = self.validate_processor_completions(
                game_date, completed_processors, expected_processors
            )
            issues.extend(processor_issues)

        # 3. Validate data quality
        if validation_config.get('check_data_quality', False):
            quality_tables = validation_config.get('quality_tables', [])

            for dataset, table in quality_tables:
                issue = self.validate_data_quality(game_date, dataset, table)
                if issue:
                    issues.append(issue)

        # Determine overall validity
        is_valid = not any(issue.severity == ValidationSeverity.ERROR for issue in issues)

        result = ValidationResult(
            game_date=game_date,
            phase_name=self.phase_name,
            is_valid=is_valid,
            mode=self.mode,
            issues=issues,
            metrics=metrics
        )

        # Log results
        if issues:
            logger.warning(
                f"Phase boundary validation found {len(issues)} issues "
                f"for {self.phase_name} on {game_date}: "
                f"{[issue.message for issue in issues]}"
            )
        else:
            logger.info(f"Phase boundary validation passed for {self.phase_name} on {game_date}")

        return result

    def log_validation_to_bigquery(self, result: ValidationResult):
        """
        Log validation result to BigQuery for monitoring.

        Table: nba_monitoring.phase_boundary_validations

        Args:
            result: ValidationResult to log
        """
        try:
            table_id = f"{self.project_id}.nba_monitoring.phase_boundary_validations"

            rows_to_insert = []
            for issue in result.issues:
                rows_to_insert.append({
                    'validation_timestamp': result.timestamp.isoformat(),
                    'game_date': result.game_date.isoformat(),
                    'phase_name': result.phase_name,
                    'validation_type': issue.validation_type,
                    'is_valid': result.is_valid,
                    'severity': issue.severity.value,
                    'message': issue.message,
                    'details': str(issue.details),
                    'expected_value': issue.details.get('expected_count') or issue.details.get('threshold'),
                    'actual_value': issue.details.get('actual_count') or issue.details.get('avg_quality_score'),
                })

            if rows_to_insert:
                errors = self.bq_client.insert_rows_json(table_id, rows_to_insert)
                if errors:
                    logger.error(f"Failed to log validation to BigQuery: {errors}")
                else:
                    logger.info(f"Logged {len(rows_to_insert)} validation issues to BigQuery")

        except Exception as e:
            logger.error(f"Error logging validation to BigQuery: {e}")
