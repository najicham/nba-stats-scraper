"""
Phase Boundary Validation Utility
=================================
Validates records at phase boundaries in the data pipeline to ensure
data quality and schema compliance.

Phases:
- Phase 2 (raw): Raw scraped data (game_id, player_id, points, rebounds, etc.)
- Phase 3 (analytics): Aggregated analytics (player_lookup, game_date, quality_tier, etc.)
- Phase 4 (precompute): ML features and precomputed data
- Phase 5 (predictions): Final predictions (player_lookup, game_date, prop_type, etc.)

Usage:
    from shared.utils.phase_validation import PhaseValidator, ValidationResult

    validator = PhaseValidator()
    result = validator.validate_output('phase_2_raw', records)
    if not result.is_valid:
        logger.error(f"Validation failed: {result.issues}")

Version: 1.0
Created: 2026-01-29
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
import logging

logger = logging.getLogger(__name__)


class Phase(Enum):
    """Data pipeline phases."""
    PHASE_2_RAW = "phase_2_raw"
    PHASE_3_ANALYTICS = "phase_3_analytics"
    PHASE_4_PRECOMPUTE = "phase_4_precompute"
    PHASE_5_PREDICTIONS = "phase_5_predictions"


class IssueSeverity(Enum):
    """Severity levels for validation issues."""
    ERROR = "error"      # Critical - blocks processing
    WARNING = "warning"  # Non-critical - may indicate data quality issues
    INFO = "info"        # Informational - no action needed


@dataclass
class ValidationIssue:
    """A single validation issue found in a record."""
    field: str
    message: str
    severity: IssueSeverity
    record_index: Optional[int] = None
    value: Any = None

    def __str__(self) -> str:
        prefix = f"[Record {self.record_index}] " if self.record_index is not None else ""
        return f"{prefix}{self.severity.value.upper()}: {self.field} - {self.message}"


@dataclass
class ValidationResult:
    """Result of validating records at a phase boundary."""
    is_valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    records_validated: int = 0
    records_with_issues: int = 0

    @property
    def errors(self) -> List[ValidationIssue]:
        """Get only error-level issues."""
        return [i for i in self.issues if i.severity == IssueSeverity.ERROR]

    @property
    def warnings(self) -> List[ValidationIssue]:
        """Get only warning-level issues."""
        return [i for i in self.issues if i.severity == IssueSeverity.WARNING]

    @property
    def error_count(self) -> int:
        """Count of error-level issues."""
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        """Count of warning-level issues."""
        return len(self.warnings)

    def add_issue(self, issue: ValidationIssue) -> None:
        """Add an issue to the result."""
        self.issues.append(issue)
        if issue.severity == IssueSeverity.ERROR:
            self.is_valid = False

    def merge(self, other: 'ValidationResult') -> 'ValidationResult':
        """Merge another validation result into this one."""
        self.issues.extend(other.issues)
        self.records_validated += other.records_validated
        self.records_with_issues += other.records_with_issues
        if not other.is_valid:
            self.is_valid = False
        return self

    def summary(self) -> str:
        """Generate a summary string."""
        status = "PASSED" if self.is_valid else "FAILED"
        return (
            f"Validation {status}: {self.records_validated} records checked, "
            f"{self.records_with_issues} with issues, "
            f"{self.error_count} errors, {self.warning_count} warnings"
        )


@dataclass
class FieldSchema:
    """Schema definition for a single field."""
    name: str
    required: bool = True
    nullable: bool = True
    field_type: Optional[type] = None
    allowed_values: Optional[Set[Any]] = None
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    custom_validator: Optional[Callable[[Any], Tuple[bool, str]]] = None

    def validate(self, value: Any, record_index: int = None) -> List[ValidationIssue]:
        """Validate a value against this field schema."""
        issues = []

        # Check for NULL when not allowed
        if value is None:
            if not self.nullable:
                issues.append(ValidationIssue(
                    field=self.name,
                    message="Field cannot be NULL",
                    severity=IssueSeverity.ERROR,
                    record_index=record_index,
                    value=value
                ))
            return issues  # No further validation needed for NULL values

        # Type validation
        if self.field_type is not None and not isinstance(value, self.field_type):
            # Allow int where float is expected
            if not (self.field_type == float and isinstance(value, (int, float))):
                issues.append(ValidationIssue(
                    field=self.name,
                    message=f"Expected type {self.field_type.__name__}, got {type(value).__name__}",
                    severity=IssueSeverity.ERROR,
                    record_index=record_index,
                    value=value
                ))
                return issues  # Don't continue with invalid type

        # Allowed values check
        if self.allowed_values is not None and value not in self.allowed_values:
            issues.append(ValidationIssue(
                field=self.name,
                message=f"Value '{value}' not in allowed values: {self.allowed_values}",
                severity=IssueSeverity.ERROR,
                record_index=record_index,
                value=value
            ))

        # Range validation (for numeric types)
        if isinstance(value, (int, float)):
            if self.min_value is not None and value < self.min_value:
                issues.append(ValidationIssue(
                    field=self.name,
                    message=f"Value {value} below minimum {self.min_value}",
                    severity=IssueSeverity.ERROR,
                    record_index=record_index,
                    value=value
                ))
            if self.max_value is not None and value > self.max_value:
                issues.append(ValidationIssue(
                    field=self.name,
                    message=f"Value {value} above maximum {self.max_value}",
                    severity=IssueSeverity.ERROR,
                    record_index=record_index,
                    value=value
                ))

        # Custom validation
        if self.custom_validator is not None:
            is_valid, message = self.custom_validator(value)
            if not is_valid:
                issues.append(ValidationIssue(
                    field=self.name,
                    message=message,
                    severity=IssueSeverity.ERROR,
                    record_index=record_index,
                    value=value
                ))

        return issues


@dataclass
class PhaseSchema:
    """Schema definition for a phase boundary."""
    phase: Phase
    fields: List[FieldSchema]
    critical_fields: Set[str] = field(default_factory=set)  # Fields that must not be NULL

    def get_required_fields(self) -> Set[str]:
        """Get set of required field names."""
        return {f.name for f in self.fields if f.required}

    def get_field(self, name: str) -> Optional[FieldSchema]:
        """Get field schema by name."""
        for f in self.fields:
            if f.name == name:
                return f
        return None


class PhaseValidator:
    """
    Validates records at phase boundaries in the data pipeline.

    Ensures data quality by checking:
    - Required fields are present
    - No unexpected NULLs in critical fields
    - Values are within expected ranges
    - Field types are correct

    Example:
        validator = PhaseValidator()

        # Validate Phase 2 raw data
        result = validator.validate_output('phase_2_raw', raw_records)

        # Validate with custom options
        result = validator.validate_output(
            'phase_3_analytics',
            analytics_records,
            max_issues=100,
            stop_on_first_error=False
        )
    """

    def __init__(self):
        """Initialize the validator with phase schemas."""
        self._schemas: Dict[str, PhaseSchema] = {}
        self._register_default_schemas()

    def _register_default_schemas(self) -> None:
        """Register default schemas for all phases."""

        # Phase 2: Raw data schema
        self._schemas[Phase.PHASE_2_RAW.value] = PhaseSchema(
            phase=Phase.PHASE_2_RAW,
            fields=[
                # Core identifiers
                FieldSchema(name="game_id", required=True, nullable=False, field_type=str),
                FieldSchema(name="game_date", required=True, nullable=False),
                FieldSchema(name="player_lookup", required=True, nullable=False, field_type=str),
                FieldSchema(name="player_full_name", required=False, nullable=True, field_type=str),
                FieldSchema(name="team_abbr", required=True, nullable=False, field_type=str),

                # Core stats (required but can be NULL for DNP)
                FieldSchema(name="points", required=True, nullable=True, field_type=(int, float), min_value=0, max_value=100),
                FieldSchema(name="rebounds", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=50),
                FieldSchema(name="assists", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=50),
                FieldSchema(name="steals", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=20),
                FieldSchema(name="blocks", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=20),
                FieldSchema(name="turnovers", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=25),

                # Shooting stats
                FieldSchema(name="field_goals_made", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=50),
                FieldSchema(name="field_goals_attempted", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=60),
                FieldSchema(name="three_pointers_made", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=20),
                FieldSchema(name="three_pointers_attempted", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=30),
                FieldSchema(name="free_throws_made", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=30),
                FieldSchema(name="free_throws_attempted", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=35),

                # Minutes (can be string like "32:45" or int)
                FieldSchema(name="minutes", required=False, nullable=True),

                # Processing metadata
                FieldSchema(name="processed_at", required=False, nullable=True),
            ],
            critical_fields={"game_id", "game_date", "player_lookup", "team_abbr"}
        )

        # Phase 3: Analytics schema
        self._schemas[Phase.PHASE_3_ANALYTICS.value] = PhaseSchema(
            phase=Phase.PHASE_3_ANALYTICS,
            fields=[
                # Core identifiers
                FieldSchema(name="player_lookup", required=True, nullable=False, field_type=str),
                FieldSchema(name="universal_player_id", required=False, nullable=True, field_type=str),
                FieldSchema(name="game_id", required=True, nullable=False, field_type=str),
                FieldSchema(name="game_date", required=True, nullable=False),
                FieldSchema(name="team_abbr", required=True, nullable=False, field_type=str),
                FieldSchema(name="opponent_team_abbr", required=True, nullable=False, field_type=str),

                # Prop line context
                FieldSchema(name="has_prop_line", required=False, nullable=True, field_type=bool),
                FieldSchema(name="current_points_line", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=60),
                FieldSchema(name="line_movement", required=False, nullable=True, field_type=(int, float), min_value=-15, max_value=15),

                # Game context
                FieldSchema(name="game_spread", required=False, nullable=True, field_type=(int, float), min_value=-30, max_value=30),
                FieldSchema(name="game_total", required=False, nullable=True, field_type=(int, float), min_value=180, max_value=280),
                FieldSchema(name="home_game", required=False, nullable=True, field_type=bool),
                FieldSchema(name="back_to_back", required=False, nullable=True, field_type=bool),

                # Recent performance
                FieldSchema(name="points_avg_last_5", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=60),
                FieldSchema(name="points_avg_last_10", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=60),

                # Fatigue metrics
                FieldSchema(name="days_rest", required=False, nullable=True, field_type=int, min_value=0, max_value=30),
                FieldSchema(name="games_in_last_7_days", required=False, nullable=True, field_type=int, min_value=0, max_value=7),
                FieldSchema(name="games_in_last_14_days", required=False, nullable=True, field_type=int, min_value=0, max_value=14),
                FieldSchema(name="minutes_in_last_7_days", required=False, nullable=True, field_type=int, min_value=0, max_value=400),

                # Quality tracking
                FieldSchema(name="data_quality_tier", required=False, nullable=True, field_type=str,
                           allowed_values={"high", "medium", "low"}),
                FieldSchema(name="is_production_ready", required=False, nullable=True, field_type=bool),

                # Processing metadata
                FieldSchema(name="processed_at", required=False, nullable=True),
                FieldSchema(name="data_hash", required=False, nullable=True, field_type=str),
            ],
            critical_fields={"player_lookup", "game_id", "game_date", "team_abbr", "opponent_team_abbr"}
        )

        # Phase 4: Precompute schema (ML features)
        self._schemas[Phase.PHASE_4_PRECOMPUTE.value] = PhaseSchema(
            phase=Phase.PHASE_4_PRECOMPUTE,
            fields=[
                # Core identifiers
                FieldSchema(name="player_lookup", required=True, nullable=False, field_type=str),
                FieldSchema(name="universal_player_id", required=False, nullable=True, field_type=str),
                FieldSchema(name="game_id", required=True, nullable=False, field_type=str),
                FieldSchema(name="game_date", required=True, nullable=False),

                # Feature arrays (flexible feature store)
                FieldSchema(name="features", required=False, nullable=True, field_type=list),
                FieldSchema(name="feature_names", required=False, nullable=True, field_type=list),
                FieldSchema(name="feature_count", required=False, nullable=True, field_type=int, min_value=0, max_value=200),
                FieldSchema(name="feature_version", required=False, nullable=True, field_type=str),

                # Player context
                FieldSchema(name="opponent_team_abbr", required=False, nullable=True, field_type=str),
                FieldSchema(name="is_home", required=False, nullable=True, field_type=bool),
                FieldSchema(name="days_rest", required=False, nullable=True, field_type=int, min_value=0, max_value=30),

                # Quality metrics
                FieldSchema(name="feature_quality_score", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=100),
                FieldSchema(name="data_source", required=False, nullable=True, field_type=str,
                           allowed_values={"phase4", "phase3", "mixed", "early_season"}),
                FieldSchema(name="early_season_flag", required=False, nullable=True, field_type=bool),

                # Completeness tracking
                FieldSchema(name="completeness_percentage", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=100),
                FieldSchema(name="is_production_ready", required=False, nullable=True, field_type=bool),

                # Processing metadata
                FieldSchema(name="created_at", required=False, nullable=True),
                FieldSchema(name="updated_at", required=False, nullable=True),
                FieldSchema(name="data_hash", required=False, nullable=True, field_type=str),
            ],
            critical_fields={"player_lookup", "game_id", "game_date"}
        )

        # Phase 5: Predictions schema
        self._schemas[Phase.PHASE_5_PREDICTIONS.value] = PhaseSchema(
            phase=Phase.PHASE_5_PREDICTIONS,
            fields=[
                # Core identifiers
                FieldSchema(name="prediction_id", required=True, nullable=False, field_type=str),
                FieldSchema(name="system_id", required=True, nullable=False, field_type=str),
                FieldSchema(name="player_lookup", required=True, nullable=False, field_type=str),
                FieldSchema(name="universal_player_id", required=False, nullable=True, field_type=str),
                FieldSchema(name="game_id", required=True, nullable=False, field_type=str),
                FieldSchema(name="game_date", required=True, nullable=False),

                # Core prediction
                FieldSchema(name="predicted_points", required=True, nullable=False, field_type=(int, float), min_value=0, max_value=80),
                FieldSchema(name="confidence_score", required=True, nullable=False, field_type=(int, float), min_value=0.0, max_value=1.0),
                FieldSchema(name="recommendation", required=True, nullable=False, field_type=str,
                           allowed_values={"OVER", "UNDER", "PASS", "NO_LINE"}),
                FieldSchema(name="has_prop_line", required=False, nullable=True, field_type=bool),

                # Line context
                FieldSchema(name="current_points_line", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=60),
                FieldSchema(name="line_margin", required=False, nullable=True, field_type=(int, float), min_value=-30, max_value=30),

                # Prediction adjustments
                FieldSchema(name="fatigue_adjustment", required=False, nullable=True, field_type=(int, float), min_value=-20, max_value=20),
                FieldSchema(name="pace_adjustment", required=False, nullable=True, field_type=(int, float), min_value=-15, max_value=15),
                FieldSchema(name="shot_zone_adjustment", required=False, nullable=True, field_type=(int, float), min_value=-15, max_value=15),
                FieldSchema(name="home_away_adjustment", required=False, nullable=True, field_type=(int, float), min_value=-10, max_value=10),

                # Supporting metadata
                FieldSchema(name="similar_games_count", required=False, nullable=True, field_type=int, min_value=0, max_value=1000),
                FieldSchema(name="avg_similarity_score", required=False, nullable=True, field_type=(int, float), min_value=0, max_value=100),

                # Status
                FieldSchema(name="is_active", required=False, nullable=True, field_type=bool),
                FieldSchema(name="is_production_ready", required=False, nullable=True, field_type=bool),

                # Processing metadata
                FieldSchema(name="created_at", required=False, nullable=True),
                FieldSchema(name="updated_at", required=False, nullable=True),
            ],
            critical_fields={"prediction_id", "system_id", "player_lookup", "game_id", "game_date",
                           "predicted_points", "confidence_score", "recommendation"}
        )

    def get_schema(self, phase: Union[str, Phase]) -> Optional[PhaseSchema]:
        """
        Get the schema for a phase.

        Args:
            phase: Phase enum or string (e.g., 'phase_2_raw')

        Returns:
            PhaseSchema or None if not found
        """
        if isinstance(phase, Phase):
            phase = phase.value
        return self._schemas.get(phase)

    def register_schema(self, phase: Union[str, Phase], schema: PhaseSchema) -> None:
        """
        Register a custom schema for a phase.

        Args:
            phase: Phase enum or string
            schema: PhaseSchema to register
        """
        if isinstance(phase, Phase):
            phase = phase.value
        self._schemas[phase] = schema

    def validate_output(
        self,
        phase: Union[str, Phase],
        records: List[Dict[str, Any]],
        max_issues: int = 1000,
        stop_on_first_error: bool = False
    ) -> ValidationResult:
        """
        Validate records at a phase boundary.

        Args:
            phase: Phase to validate against (e.g., 'phase_2_raw')
            records: List of records to validate
            max_issues: Maximum number of issues to collect
            stop_on_first_error: Stop validation on first error

        Returns:
            ValidationResult with issues found
        """
        if isinstance(phase, Phase):
            phase = phase.value

        schema = self.get_schema(phase)
        if schema is None:
            return ValidationResult(
                is_valid=False,
                issues=[ValidationIssue(
                    field="_schema",
                    message=f"Unknown phase: {phase}",
                    severity=IssueSeverity.ERROR
                )],
                records_validated=0,
                records_with_issues=0
            )

        result = ValidationResult(is_valid=True, records_validated=len(records))
        records_with_issues_set: Set[int] = set()

        for i, record in enumerate(records):
            if len(result.issues) >= max_issues:
                result.add_issue(ValidationIssue(
                    field="_validation",
                    message=f"Maximum issues ({max_issues}) reached, stopping validation",
                    severity=IssueSeverity.WARNING
                ))
                break

            record_issues = self._validate_record(record, schema, i)

            for issue in record_issues:
                result.add_issue(issue)
                records_with_issues_set.add(i)

                if stop_on_first_error and issue.severity == IssueSeverity.ERROR:
                    result.records_with_issues = len(records_with_issues_set)
                    return result

        result.records_with_issues = len(records_with_issues_set)
        return result

    def _validate_record(
        self,
        record: Dict[str, Any],
        schema: PhaseSchema,
        record_index: int
    ) -> List[ValidationIssue]:
        """Validate a single record against a schema."""
        issues = []

        # Check for missing required fields
        required_fields = schema.get_required_fields()
        for field_name in required_fields:
            if field_name not in record:
                issues.append(ValidationIssue(
                    field=field_name,
                    message="Required field is missing",
                    severity=IssueSeverity.ERROR,
                    record_index=record_index
                ))

        # Check critical fields for NULL
        for field_name in schema.critical_fields:
            if field_name in record and record[field_name] is None:
                issues.append(ValidationIssue(
                    field=field_name,
                    message="Critical field cannot be NULL",
                    severity=IssueSeverity.ERROR,
                    record_index=record_index,
                    value=None
                ))

        # Validate each field present in the record
        for field_name, value in record.items():
            field_schema = schema.get_field(field_name)
            if field_schema is not None:
                field_issues = field_schema.validate(value, record_index)
                issues.extend(field_issues)

        return issues

    def validate_record(
        self,
        phase: Union[str, Phase],
        record: Dict[str, Any]
    ) -> ValidationResult:
        """
        Validate a single record at a phase boundary.

        Convenience method for validating one record at a time.

        Args:
            phase: Phase to validate against
            record: Single record to validate

        Returns:
            ValidationResult
        """
        return self.validate_output(phase, [record])


# =============================================================================
# Convenience Functions
# =============================================================================

def validate_phase2_raw(records: List[Dict[str, Any]], **kwargs) -> ValidationResult:
    """
    Validate Phase 2 (raw) records.

    Args:
        records: Raw records from scrapers
        **kwargs: Additional validation options

    Returns:
        ValidationResult
    """
    return PhaseValidator().validate_output(Phase.PHASE_2_RAW, records, **kwargs)


def validate_phase3_analytics(records: List[Dict[str, Any]], **kwargs) -> ValidationResult:
    """
    Validate Phase 3 (analytics) records.

    Args:
        records: Analytics records
        **kwargs: Additional validation options

    Returns:
        ValidationResult
    """
    return PhaseValidator().validate_output(Phase.PHASE_3_ANALYTICS, records, **kwargs)


def validate_phase4_precompute(records: List[Dict[str, Any]], **kwargs) -> ValidationResult:
    """
    Validate Phase 4 (precompute) records.

    Args:
        records: Precompute/ML feature records
        **kwargs: Additional validation options

    Returns:
        ValidationResult
    """
    return PhaseValidator().validate_output(Phase.PHASE_4_PRECOMPUTE, records, **kwargs)


def validate_phase5_predictions(records: List[Dict[str, Any]], **kwargs) -> ValidationResult:
    """
    Validate Phase 5 (predictions) records.

    Args:
        records: Prediction records
        **kwargs: Additional validation options

    Returns:
        ValidationResult
    """
    return PhaseValidator().validate_output(Phase.PHASE_5_PREDICTIONS, records, **kwargs)


# =============================================================================
# Module exports
# =============================================================================

__all__ = [
    # Classes
    "PhaseValidator",
    "ValidationResult",
    "ValidationIssue",
    "FieldSchema",
    "PhaseSchema",
    "Phase",
    "IssueSeverity",
    # Convenience functions
    "validate_phase2_raw",
    "validate_phase3_analytics",
    "validate_phase4_precompute",
    "validate_phase5_predictions",
]
