"""
Pre-Write Validation for BigQuery Operations
=============================================
Validates records against business logic rules BEFORE writing to BigQuery.
Blocks records that would corrupt downstream data (e.g., DNP with points=0).

This module provides:
1. ValidationRule - Define individual validation rules
2. PreWriteValidator - Validate records against rules for a target table
3. Pre-built rules for player_game_summary, player_composite_factors, ml_feature_store_v2

Usage:
    from shared.validation.pre_write_validator import PreWriteValidator

    validator = PreWriteValidator('player_game_summary')
    valid_records, invalid_records = validator.validate(records)

    if invalid_records:
        logger.error(f"Blocked {len(invalid_records)} invalid records")
        # Log to validation_failures table

    # Only write valid records
    write_to_bigquery(valid_records)

Version: 1.0
Created: 2026-01-30
Part of: Data Quality Self-Healing System
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid

logger = logging.getLogger(__name__)


@dataclass
class ValidationRule:
    """A single validation rule with condition and error message."""
    name: str
    condition: Callable[[dict], bool]  # Returns True if record is VALID
    error_message: str
    severity: str = "ERROR"  # ERROR blocks write, WARNING logs only

    def validate(self, record: dict) -> Optional[str]:
        """
        Validate a record against this rule.

        Returns:
            None if valid, error message string if invalid
        """
        try:
            if not self.condition(record):
                return f"{self.name}: {self.error_message}"
        except Exception as e:
            logger.warning(f"Rule {self.name} raised exception: {e}")
            return f"{self.name}: Validation error - {e}"
        return None


@dataclass
class ValidationResult:
    """Result of pre-write validation."""
    is_valid: bool
    valid_records: List[dict] = field(default_factory=list)
    invalid_records: List[dict] = field(default_factory=list)
    violations: List[dict] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len([v for v in self.violations if v.get('severity') == 'ERROR'])

    @property
    def warning_count(self) -> int:
        return len([v for v in self.violations if v.get('severity') == 'WARNING'])


# =============================================================================
# BUSINESS RULES BY TABLE
# =============================================================================

BUSINESS_RULES: Dict[str, List[ValidationRule]] = {

    # -------------------------------------------------------------------------
    # player_game_summary - Phase 3 Analytics
    # -------------------------------------------------------------------------
    'player_game_summary': [
        # DNP players must have NULL stats (not 0)
        # This is the EXACT bug that caused the January 2026 incident
        ValidationRule(
            name='dnp_null_points',
            condition=lambda r: not r.get('is_dnp') or r.get('points') is None,
            error_message="DNP players must have NULL points, not 0 or any value"
        ),
        ValidationRule(
            name='dnp_null_minutes',
            condition=lambda r: not r.get('is_dnp') or r.get('minutes') is None,
            error_message="DNP players must have NULL minutes"
        ),
        ValidationRule(
            name='dnp_null_rebounds',
            condition=lambda r: not r.get('is_dnp') or r.get('rebounds') is None,
            error_message="DNP players must have NULL rebounds"
        ),
        ValidationRule(
            name='dnp_null_assists',
            condition=lambda r: not r.get('is_dnp') or r.get('assists') is None,
            error_message="DNP players must have NULL assists"
        ),

        # Active players must have valid stats
        ValidationRule(
            name='active_non_negative_points',
            condition=lambda r: r.get('is_dnp') or (r.get('points') is None or r.get('points', 0) >= 0),
            error_message="Active players cannot have negative points"
        ),
        ValidationRule(
            name='active_non_negative_minutes',
            condition=lambda r: r.get('is_dnp') or (r.get('minutes') is None or r.get('minutes', 0) >= 0),
            error_message="Active players cannot have negative minutes"
        ),

        # Required fields for identity
        ValidationRule(
            name='required_player_lookup',
            condition=lambda r: r.get('player_lookup') is not None,
            error_message="player_lookup is required"
        ),
        ValidationRule(
            name='required_game_date',
            condition=lambda r: r.get('game_date') is not None,
            error_message="game_date is required"
        ),
        ValidationRule(
            name='required_game_id',
            condition=lambda r: r.get('game_id') is not None,
            error_message="game_id is required"
        ),

        # Stat ranges (when not NULL)
        ValidationRule(
            name='points_range',
            condition=lambda r: r.get('points') is None or 0 <= r.get('points', 0) <= 100,
            error_message="points must be 0-100 (or NULL)",
            severity="WARNING"
        ),
        ValidationRule(
            name='minutes_range',
            condition=lambda r: r.get('minutes') is None or 0 <= r.get('minutes', 0) <= 60,
            error_message="minutes must be 0-60 (or NULL)",
            severity="WARNING"
        ),
    ],

    # -------------------------------------------------------------------------
    # player_composite_factors - Phase 4 Precompute
    # -------------------------------------------------------------------------
    'player_composite_factors': [
        # Fatigue score must be in valid range
        # This catches the parallel processing bug from January 2026
        ValidationRule(
            name='fatigue_score_range',
            condition=lambda r: r.get('fatigue_score') is None or 0 <= r.get('fatigue_score', 0) <= 100,
            error_message="fatigue_score must be 0-100"
        ),

        # Context scores ranges
        ValidationRule(
            name='matchup_difficulty_range',
            condition=lambda r: r.get('matchup_difficulty_score') is None or -50 <= r.get('matchup_difficulty_score', 0) <= 50,
            error_message="matchup_difficulty_score must be -50 to 50"
        ),
        ValidationRule(
            name='pace_score_range',
            condition=lambda r: r.get('pace_score') is None or 70 <= r.get('pace_score', 100) <= 130,
            error_message="pace_score must be 70-130",
            severity="WARNING"
        ),

        # Required fields
        ValidationRule(
            name='required_player_lookup',
            condition=lambda r: r.get('player_lookup') is not None,
            error_message="player_lookup is required"
        ),
        ValidationRule(
            name='required_game_date',
            condition=lambda r: r.get('game_date') is not None,
            error_message="game_date is required"
        ),
    ],

    # -------------------------------------------------------------------------
    # ml_feature_store_v2 - Phase 4 Precompute (ML Features)
    # -------------------------------------------------------------------------
    'ml_feature_store_v2': [
        # Feature array must have correct count
        ValidationRule(
            name='feature_array_length',
            condition=lambda r: r.get('features') is None or len(r.get('features', [])) == 34,
            error_message="features array must have exactly 34 elements"
        ),

        # No NaN or Inf in features
        ValidationRule(
            name='no_nan_features',
            condition=lambda r: r.get('features') is None or not any(
                str(f).lower() in ('nan', 'inf', '-inf', 'none')
                for f in r.get('features', [])
            ),
            error_message="features array cannot contain NaN or Inf values"
        ),

        # Required fields
        ValidationRule(
            name='required_player_lookup',
            condition=lambda r: r.get('player_lookup') is not None,
            error_message="player_lookup is required"
        ),
        ValidationRule(
            name='required_game_date',
            condition=lambda r: r.get('game_date') is not None,
            error_message="game_date is required"
        ),

        # Feature ranges (for key features at known indices)
        # Index 0: points_avg (0-50 typical)
        ValidationRule(
            name='feature_points_avg_range',
            condition=lambda r: (
                r.get('features') is None or
                len(r.get('features', [])) < 1 or
                r.get('features')[0] is None or
                0 <= r.get('features')[0] <= 60
            ),
            error_message="features[0] (points_avg) should be 0-60",
            severity="WARNING"
        ),
        # Index 5: fatigue_score (0-100)
        ValidationRule(
            name='feature_fatigue_range',
            condition=lambda r: (
                r.get('features') is None or
                len(r.get('features', [])) < 6 or
                r.get('features')[5] is None or
                0 <= r.get('features')[5] <= 100
            ),
            error_message="features[5] (fatigue_score) must be 0-100"
        ),
    ],

    # -------------------------------------------------------------------------
    # prediction_accuracy - Phase 5 Grading
    # -------------------------------------------------------------------------
    'prediction_accuracy': [
        ValidationRule(
            name='required_prediction_id',
            condition=lambda r: r.get('prediction_id') is not None,
            error_message="prediction_id is required"
        ),
        ValidationRule(
            name='required_game_date',
            condition=lambda r: r.get('game_date') is not None,
            error_message="game_date is required"
        ),
        ValidationRule(
            name='actual_points_range',
            condition=lambda r: r.get('actual_points') is None or 0 <= r.get('actual_points', 0) <= 100,
            error_message="actual_points must be 0-100",
            severity="WARNING"
        ),
    ],
}


class PreWriteValidator:
    """
    Validates records against business rules before BigQuery write.

    Usage:
        validator = PreWriteValidator('player_game_summary')
        valid, invalid = validator.validate(records)
    """

    def __init__(self, table_name: str, custom_rules: List[ValidationRule] = None):
        """
        Initialize validator for a specific table.

        Args:
            table_name: Target BigQuery table name
            custom_rules: Optional additional rules to apply
        """
        self.table_name = table_name
        self.rules = BUSINESS_RULES.get(table_name, []).copy()

        if custom_rules:
            self.rules.extend(custom_rules)

        if not self.rules:
            logger.warning(f"No validation rules defined for table: {table_name}")

    def validate(self, records: List[dict]) -> Tuple[List[dict], List[dict]]:
        """
        Validate records, returning (valid_records, invalid_records).

        Invalid records include a '_validation_violations' key with list of errors.

        Args:
            records: List of record dicts to validate

        Returns:
            Tuple of (valid_records, invalid_records)
        """
        if not records:
            return [], []

        valid_records = []
        invalid_records = []

        for i, record in enumerate(records):
            violations = self._check_rules(record, i)
            error_violations = [v for v in violations if v.get('severity') == 'ERROR']

            if error_violations:
                # Add violations to record for debugging
                record_copy = record.copy()
                record_copy['_validation_violations'] = violations
                record_copy['_validation_timestamp'] = datetime.now(timezone.utc).isoformat()
                invalid_records.append(record_copy)
                self._log_violations(record, violations)
            else:
                valid_records.append(record)
                # Log warnings but don't block
                warning_violations = [v for v in violations if v.get('severity') == 'WARNING']
                if warning_violations:
                    self._log_warnings(record, warning_violations)

        return valid_records, invalid_records

    def validate_single(self, record: dict) -> ValidationResult:
        """
        Validate a single record with detailed result.

        Args:
            record: Single record dict

        Returns:
            ValidationResult with details
        """
        violations = self._check_rules(record, 0)
        error_violations = [v for v in violations if v.get('severity') == 'ERROR']

        result = ValidationResult(
            is_valid=len(error_violations) == 0,
            valid_records=[record] if len(error_violations) == 0 else [],
            invalid_records=[record] if len(error_violations) > 0 else [],
            violations=violations
        )

        return result

    def _check_rules(self, record: dict, record_index: int) -> List[dict]:
        """Check all rules against a record."""
        violations = []

        for rule in self.rules:
            error_msg = rule.validate(record)
            if error_msg:
                violations.append({
                    'rule_name': rule.name,
                    'error_message': error_msg,
                    'severity': rule.severity,
                    'record_index': record_index,
                    'field_values': self._extract_relevant_fields(record, rule.name)
                })

        return violations

    def _extract_relevant_fields(self, record: dict, rule_name: str) -> dict:
        """Extract fields relevant to a rule for debugging."""
        # Map rule names to relevant fields
        field_map = {
            'dnp_null_points': ['is_dnp', 'points', 'player_lookup', 'game_date'],
            'dnp_null_minutes': ['is_dnp', 'minutes', 'player_lookup', 'game_date'],
            'dnp_null_rebounds': ['is_dnp', 'rebounds', 'player_lookup', 'game_date'],
            'dnp_null_assists': ['is_dnp', 'assists', 'player_lookup', 'game_date'],
            'fatigue_score_range': ['fatigue_score', 'player_lookup', 'game_date'],
            'feature_array_length': ['player_lookup', 'game_date'],
        }

        fields = field_map.get(rule_name, ['player_lookup', 'game_date', 'game_id'])
        return {f: record.get(f) for f in fields if f in record}

    def _log_violations(self, record: dict, violations: List[dict]) -> None:
        """Log validation violations."""
        player = record.get('player_lookup', 'unknown')
        game_date = record.get('game_date', 'unknown')

        for v in violations:
            if v.get('severity') == 'ERROR':
                logger.error(
                    f"PRE_WRITE_VALIDATION_BLOCKED: table={self.table_name} "
                    f"player={player} date={game_date} rule={v['rule_name']} "
                    f"error={v['error_message']} fields={v.get('field_values')}"
                )

    def _log_warnings(self, record: dict, violations: List[dict]) -> None:
        """Log validation warnings (non-blocking)."""
        player = record.get('player_lookup', 'unknown')
        game_date = record.get('game_date', 'unknown')

        for v in violations:
            logger.warning(
                f"PRE_WRITE_VALIDATION_WARNING: table={self.table_name} "
                f"player={player} date={game_date} rule={v['rule_name']} "
                f"warning={v['error_message']}"
            )

    def add_rule(self, rule: ValidationRule) -> None:
        """Add a custom rule at runtime."""
        self.rules.append(rule)

    def disable_rule(self, rule_name: str) -> None:
        """Disable a rule by name (for testing/migration)."""
        self.rules = [r for r in self.rules if r.name != rule_name]


def create_validation_failure_record(
    table_name: str,
    record: dict,
    violations: List[dict],
    processor_name: str = None,
    session_id: str = None
) -> dict:
    """
    Create a record for the validation_failures table.

    Args:
        table_name: Target table that was being written to
        record: The record that failed validation
        violations: List of violation dicts
        processor_name: Name of the processor (optional)
        session_id: Processing session ID (optional)

    Returns:
        Dict ready to insert into validation_failures table
    """
    import json

    return {
        'failure_id': str(uuid.uuid4()),
        'failure_timestamp': datetime.now(timezone.utc).isoformat(),
        'table_name': table_name,
        'processor_name': processor_name,
        'game_date': str(record.get('game_date')) if record.get('game_date') else None,
        'player_lookup': record.get('player_lookup'),
        'game_id': record.get('game_id'),
        'violations': [v.get('error_message', str(v)) for v in violations],
        'record_json': json.dumps(record, default=str)[:10000],  # Truncate large records
        'session_id': session_id,
        'environment': 'production'
    }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def validate_player_game_summary(records: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Validate player_game_summary records."""
    validator = PreWriteValidator('player_game_summary')
    return validator.validate(records)


def validate_composite_factors(records: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Validate player_composite_factors records."""
    validator = PreWriteValidator('player_composite_factors')
    return validator.validate(records)


def validate_ml_features(records: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Validate ml_feature_store_v2 records."""
    validator = PreWriteValidator('ml_feature_store_v2')
    return validator.validate(records)
