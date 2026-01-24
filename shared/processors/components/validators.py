"""
Data validation components for the composable processor framework.

Validators check data quality and integrity:
- Required field presence
- Data type correctness
- Statistical anomaly detection
- Cross-field consistency

Quality issues are recorded in context.quality_issues for downstream handling.

Version: 1.0
Created: 2026-01-23
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Union

import pandas as pd

from .base import Validator, ComponentContext

logger = logging.getLogger(__name__)


@dataclass
class FieldSpec:
    """Specification for a data field."""
    name: str
    required: bool = True
    dtype: Optional[str] = None  # 'int', 'float', 'str', 'bool', 'date'
    nullable: bool = True
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    allowed_values: Optional[Set[Any]] = None


class FieldValidator(Validator):
    """
    Validate that required fields exist and have correct types.

    Records quality issues for:
    - Missing required fields
    - Missing optional fields (as warnings)
    - Type mismatches
    - Out-of-range values

    Example:
        validator = FieldValidator(
            required_fields=['game_id', 'player_id', 'points'],
            optional_fields=['plus_minus'],
            field_specs={
                'points': FieldSpec(name='points', dtype='int', min_value=0, max_value=100),
                'season_year': FieldSpec(name='season_year', dtype='int', min_value=2000, max_value=2030),
            }
        )
    """

    def __init__(
        self,
        required_fields: List[str] = None,
        optional_fields: List[str] = None,
        field_specs: Dict[str, FieldSpec] = None,
        name: Optional[str] = None,
    ):
        """
        Initialize field validator.

        Args:
            required_fields: List of required field names
            optional_fields: List of optional field names
            field_specs: Detailed specifications for fields
            name: Optional component name
        """
        super().__init__(name=name)
        self.required_fields = required_fields or []
        self.optional_fields = optional_fields or []
        self.field_specs = field_specs or {}

    def validate(
        self,
        data: pd.DataFrame,
        context: ComponentContext
    ) -> pd.DataFrame:
        """
        Validate field presence and types.

        Args:
            data: DataFrame to validate
            context: Processing context for recording issues

        Returns:
            Original DataFrame (validation is side-effect)
        """
        if data.empty:
            return data

        columns = set(data.columns)

        # Check required fields
        for field in self.required_fields:
            if field not in columns:
                context.add_quality_issue(
                    issue_type='missing_required_field',
                    severity='critical',
                    identifier=field,
                    details={'field': field, 'record_count': len(data)},
                )
                logger.error(f"Missing required field: {field}", exc_info=True)

        # Check optional fields
        for field in self.optional_fields:
            if field not in columns:
                context.add_quality_issue(
                    issue_type='missing_optional_field',
                    severity='warning',
                    identifier=field,
                    details={'field': field, 'record_count': len(data)},
                )
                logger.warning(f"Missing optional field: {field}")

        # Validate field specifications
        for field_name, spec in self.field_specs.items():
            if field_name in columns:
                self._validate_field_spec(data, field_name, spec, context)

        return data

    def _validate_field_spec(
        self,
        data: pd.DataFrame,
        field_name: str,
        spec: FieldSpec,
        context: ComponentContext,
    ) -> None:
        """Validate a field against its specification."""
        column = data[field_name]

        # Check nullability
        if not spec.nullable:
            null_count = column.isna().sum()
            if null_count > 0:
                context.add_quality_issue(
                    issue_type='unexpected_nulls',
                    severity='high',
                    identifier=field_name,
                    details={
                        'field': field_name,
                        'null_count': int(null_count),
                        'null_pct': float(null_count / len(data) * 100),
                    },
                )

        # Check value range for numeric fields
        if spec.min_value is not None:
            below_min = (column < spec.min_value).sum()
            if below_min > 0:
                context.add_quality_issue(
                    issue_type='value_below_minimum',
                    severity='high',
                    identifier=field_name,
                    details={
                        'field': field_name,
                        'min_value': spec.min_value,
                        'count_below': int(below_min),
                    },
                )

        if spec.max_value is not None:
            above_max = (column > spec.max_value).sum()
            if above_max > 0:
                context.add_quality_issue(
                    issue_type='value_above_maximum',
                    severity='high',
                    identifier=field_name,
                    details={
                        'field': field_name,
                        'max_value': spec.max_value,
                        'count_above': int(above_max),
                    },
                )

        # Check allowed values
        if spec.allowed_values is not None:
            invalid = ~column.isin(spec.allowed_values)
            invalid_count = invalid.sum()
            if invalid_count > 0:
                # Get sample of invalid values
                invalid_sample = column[invalid].unique()[:5].tolist()
                context.add_quality_issue(
                    issue_type='invalid_value',
                    severity='high',
                    identifier=field_name,
                    details={
                        'field': field_name,
                        'invalid_count': int(invalid_count),
                        'invalid_sample': invalid_sample,
                        'allowed_values': list(spec.allowed_values)[:10],
                    },
                )


class StatisticalValidator(Validator):
    """
    Detect statistical anomalies in data.

    Checks for:
    - FG makes > FG attempts (impossible stats)
    - Unrealistic point totals
    - Suspicious patterns

    Example:
        validator = StatisticalValidator(
            checks=[
                StatCheck('fg_makes', 'lte', 'fg_attempts', 'FG makes > attempts'),
                StatCheck('points', 'between', 0, 100, 'Points out of range'),
            ]
        )
    """

    def __init__(
        self,
        checks: List['StatCheck'] = None,
        name: Optional[str] = None,
    ):
        """
        Initialize statistical validator.

        Args:
            checks: List of statistical checks to perform
            name: Optional component name
        """
        super().__init__(name=name)
        self.checks = checks or []

    def validate(
        self,
        data: pd.DataFrame,
        context: ComponentContext
    ) -> pd.DataFrame:
        """
        Run statistical checks on data.

        Args:
            data: DataFrame to validate
            context: Processing context for recording issues

        Returns:
            Original DataFrame
        """
        if data.empty:
            return data

        for check in self.checks:
            violations = check.find_violations(data)
            if violations > 0:
                context.add_quality_issue(
                    issue_type='statistical_anomaly',
                    severity=check.severity,
                    identifier=check.name,
                    details={
                        'check': check.name,
                        'description': check.description,
                        'violation_count': violations,
                        'check_type': check.check_type,
                    },
                )
                logger.warning(
                    f"Statistical check failed: {check.description} "
                    f"({violations} violations)"
                )

        return data


@dataclass
class StatCheck:
    """
    A single statistical check.

    Supported check types:
    - 'lte': field1 <= field2
    - 'lt': field1 < field2
    - 'gte': field1 >= field2
    - 'gt': field1 > field2
    - 'between': min_val <= field <= max_val
    - 'custom': custom function
    """
    name: str
    check_type: str
    field1: str = ''
    field2_or_min: Union[str, int, float] = ''
    max_val: Optional[Union[int, float]] = None
    description: str = ''
    severity: str = 'high'
    custom_func: Optional[Callable[[pd.DataFrame], int]] = None

    def find_violations(self, data: pd.DataFrame) -> int:
        """Find number of rows violating this check."""
        try:
            if self.check_type == 'lte':
                # field1 should be <= field2
                if self.field1 not in data.columns or self.field2_or_min not in data.columns:
                    return 0
                mask = data[self.field1] > data[self.field2_or_min]
                return mask.sum()

            elif self.check_type == 'lt':
                # field1 should be < field2
                if self.field1 not in data.columns or self.field2_or_min not in data.columns:
                    return 0
                mask = data[self.field1] >= data[self.field2_or_min]
                return mask.sum()

            elif self.check_type == 'gte':
                # field1 should be >= field2
                if self.field1 not in data.columns or self.field2_or_min not in data.columns:
                    return 0
                mask = data[self.field1] < data[self.field2_or_min]
                return mask.sum()

            elif self.check_type == 'gt':
                # field1 should be > field2
                if self.field1 not in data.columns or self.field2_or_min not in data.columns:
                    return 0
                mask = data[self.field1] <= data[self.field2_or_min]
                return mask.sum()

            elif self.check_type == 'between':
                # field1 should be between min and max
                if self.field1 not in data.columns:
                    return 0
                min_val = self.field2_or_min
                max_val = self.max_val
                mask = (data[self.field1] < min_val) | (data[self.field1] > max_val)
                return mask.sum()

            elif self.check_type == 'custom':
                if self.custom_func:
                    return self.custom_func(data)
                return 0

            else:
                logger.warning(f"Unknown check type: {self.check_type}")
                return 0

        except Exception as e:
            logger.warning(f"Error running stat check {self.name}: {e}")
            return 0


class SchemaValidator(Validator):
    """
    Validate data against a BigQuery table schema.

    Ensures all output fields are present and have compatible types
    before attempting to write.

    Example:
        validator = SchemaValidator(
            table_id='project.dataset.table',
            strict=True,  # Fail on extra columns
        )
    """

    def __init__(
        self,
        table_id: Optional[str] = None,
        expected_columns: List[str] = None,
        strict: bool = False,
        name: Optional[str] = None,
    ):
        """
        Initialize schema validator.

        Args:
            table_id: BigQuery table ID to fetch schema from
            expected_columns: Alternative to table_id - list of expected columns
            strict: If True, fail on extra columns not in schema
            name: Optional component name
        """
        super().__init__(name=name)
        self.table_id = table_id
        self.expected_columns = expected_columns or []
        self.strict = strict
        self._schema_cache = None

    def validate(
        self,
        data: pd.DataFrame,
        context: ComponentContext
    ) -> pd.DataFrame:
        """
        Validate data against schema.

        Args:
            data: DataFrame to validate
            context: Processing context

        Returns:
            Original DataFrame
        """
        if data.empty:
            return data

        # Get expected columns
        expected = self._get_expected_columns(context)
        actual = set(data.columns)

        # Check for missing columns
        missing = expected - actual
        if missing:
            context.add_quality_issue(
                issue_type='schema_missing_columns',
                severity='high' if self.strict else 'warning',
                identifier='schema',
                details={'missing_columns': list(missing)},
            )
            logger.warning(f"Missing schema columns: {missing}")

        # Check for extra columns (in strict mode)
        if self.strict:
            extra = actual - expected
            if extra:
                context.add_quality_issue(
                    issue_type='schema_extra_columns',
                    severity='warning',
                    identifier='schema',
                    details={'extra_columns': list(extra)},
                )
                logger.warning(f"Extra columns not in schema: {extra}")

        return data

    def _get_expected_columns(self, context: ComponentContext) -> Set[str]:
        """Get expected column names from schema or configuration."""
        if self.expected_columns:
            return set(self.expected_columns)

        if self._schema_cache:
            return self._schema_cache

        if self.table_id and context.bq_client:
            try:
                table = context.bq_client.get_table(self.table_id)
                self._schema_cache = {field.name for field in table.schema}
                return self._schema_cache
            except Exception as e:
                logger.warning(f"Could not fetch schema for {self.table_id}: {e}")

        return set()


class CompositeValidator(Validator):
    """
    Combine multiple validators into a single validator.

    Runs all inner validators in order and aggregates their issues.

    Example:
        validator = CompositeValidator(
            validators=[
                FieldValidator(required_fields=['game_id', 'points']),
                StatisticalValidator(checks=[...]),
                SchemaValidator(table_id='...'),
            ]
        )
    """

    def __init__(
        self,
        validators: List[Validator],
        name: Optional[str] = None,
    ):
        """
        Initialize composite validator.

        Args:
            validators: List of validators to run
            name: Optional component name
        """
        super().__init__(name=name)
        self.validators = validators

    def validate(
        self,
        data: pd.DataFrame,
        context: ComponentContext
    ) -> pd.DataFrame:
        """
        Run all inner validators.

        Args:
            data: DataFrame to validate
            context: Processing context

        Returns:
            Original DataFrame
        """
        for validator in self.validators:
            data = validator.validate(data, context)

        return data

    def validate_config(self) -> List[str]:
        """Validate all inner validators."""
        errors = []
        for validator in self.validators:
            errors.extend(validator.validate_config())
        return errors
