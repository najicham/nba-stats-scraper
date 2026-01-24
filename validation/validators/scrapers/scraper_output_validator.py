#!/usr/bin/env python3
# File: validation/validators/scrapers/scraper_output_validator.py
# Description: Scraper output validation using YAML schemas
"""
Scraper Output Validator

Validates scraper output data immediately after scraping using YAML schemas.
This is Layer 0 validation - catching issues before data reaches GCS.

Key validations:
- Schema structure validation
- Field type checking
- Value range validation
- Row count validation
- Custom business logic validation

Usage:
    validator = ScraperOutputValidator('espn_boxscore')
    result = validator.validate(scraper_data)
    if not result.passed:
        logger.error(f"Validation failed: {result.issues}")
"""

import os
import yaml
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Path to scraper validation configs
CONFIGS_DIR = Path(__file__).parent.parent.parent / 'configs' / 'scrapers'


@dataclass
class ValidationIssue:
    """Single validation issue"""
    check_name: str
    severity: str  # "info", "warning", "error", "critical"
    message: str
    field: Optional[str] = None
    expected: Optional[Any] = None
    actual: Optional[Any] = None


@dataclass
class ValidationResult:
    """Result of validation run"""
    scraper_name: str
    passed: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    warnings: int = 0
    errors: int = 0
    row_count: int = 0

    def add_issue(self, issue: ValidationIssue):
        """Add a validation issue"""
        self.issues.append(issue)
        if issue.severity in ('error', 'critical'):
            self.errors += 1
            self.passed = False
        elif issue.severity == 'warning':
            self.warnings += 1


class ScraperOutputValidator:
    """
    Validates scraper output data against YAML schema definitions.

    Provides immediate validation at scraper output level (Layer 0)
    before data is exported to GCS.
    """

    def __init__(self, scraper_name: str, config_path: Optional[str] = None):
        """
        Initialize validator for a specific scraper.

        Args:
            scraper_name: Name of the scraper (e.g., 'espn_boxscore')
            config_path: Optional custom config path (defaults to standard location)
        """
        self.scraper_name = scraper_name

        if config_path:
            self.config_path = Path(config_path)
        else:
            self.config_path = CONFIGS_DIR / f'{scraper_name}.yaml'

        self.config = self._load_config()
        self._schema = self.config.get('schema', {})

    def _load_config(self) -> Dict:
        """Load YAML validation config"""
        if not self.config_path.exists():
            logger.debug(f"No validation config found for {self.scraper_name}")
            return {}

        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
                logger.debug(f"Loaded validation config: {self.config_path}")
                return config or {}
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in validation config: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error loading validation config: {e}")
            return {}

    def validate(self, data: Any, opts: Optional[Dict] = None) -> ValidationResult:
        """
        Validate scraper output data.

        Args:
            data: The scraper output data to validate
            opts: Optional scraper options for context

        Returns:
            ValidationResult with pass/fail status and issues
        """
        result = ValidationResult(
            scraper_name=self.scraper_name,
            passed=True
        )

        if not self.config:
            # No config = no validation (pass through)
            logger.debug(f"No validation config for {self.scraper_name}, skipping")
            return result

        opts = opts or {}

        try:
            # 1. Schema structure validation
            self._validate_schema(data, result)

            # 2. Row count validation
            self._validate_row_count(data, result)

            # 3. Field type validation
            self._validate_field_types(data, result)

            # 4. Value range validation
            self._validate_value_ranges(data, result)

            # 5. Custom validations
            self._run_custom_validations(data, result, opts)

            # 6. Zero row handling
            if result.row_count == 0:
                self._handle_zero_rows(data, result, opts)

        except Exception as e:
            logger.error(f"Validation error: {e}")
            result.add_issue(ValidationIssue(
                check_name="validation_execution",
                severity="error",
                message=f"Validation failed with error: {str(e)}"
            ))

        return result

    def _validate_schema(self, data: Any, result: ValidationResult):
        """Validate data matches expected schema structure"""
        schema = self._schema

        if not schema:
            return

        # Check data type
        expected_type = schema.get('type')
        if expected_type == 'object' and not isinstance(data, dict):
            result.add_issue(ValidationIssue(
                check_name="schema_type",
                severity="error",
                message=f"Expected object, got {type(data).__name__}",
                expected="object",
                actual=type(data).__name__
            ))
            return

        if expected_type == 'array' and not isinstance(data, list):
            result.add_issue(ValidationIssue(
                check_name="schema_type",
                severity="error",
                message=f"Expected array, got {type(data).__name__}",
                expected="array",
                actual=type(data).__name__
            ))
            return

        # Check required fields
        required_fields = schema.get('required_fields', [])
        if isinstance(data, dict):
            for field_name in required_fields:
                if field_name not in data:
                    result.add_issue(ValidationIssue(
                        check_name="required_field",
                        severity="error",
                        message=f"Missing required field: {field_name}",
                        field=field_name
                    ))

    def _validate_row_count(self, data: Any, result: ValidationResult):
        """Validate row count is within expected range"""
        row_count_config = self.config.get('row_count', {})

        if not row_count_config:
            return

        # Determine row count from data
        count_field = row_count_config.get('field')
        if count_field and isinstance(data, dict):
            count = data.get(count_field, 0)
        elif isinstance(data, dict):
            # Try common patterns
            if 'records' in data:
                count = len(data['records'])
            elif 'games' in data:
                count = len(data['games'])
            elif 'players' in data:
                count = len(data['players'])
            elif 'props' in data:
                count = len(data['props'])
            else:
                count = 0
        elif isinstance(data, list):
            count = len(data)
        else:
            count = 0

        result.row_count = count

        min_count = row_count_config.get('min', 0)
        max_count = row_count_config.get('max', float('inf'))
        severity = row_count_config.get('severity', 'warning')

        if count < min_count:
            result.add_issue(ValidationIssue(
                check_name="row_count_min",
                severity=severity,
                message=row_count_config.get('message', f"Row count {count} below minimum {min_count}"),
                field=count_field,
                expected=f">= {min_count}",
                actual=count
            ))

        if count > max_count:
            result.add_issue(ValidationIssue(
                check_name="row_count_max",
                severity=severity,
                message=row_count_config.get('message', f"Row count {count} above maximum {max_count}"),
                field=count_field,
                expected=f"<= {max_count}",
                actual=count
            ))

    def _validate_field_types(self, data: Any, result: ValidationResult):
        """Validate field types match expected types"""
        field_types = self._schema.get('field_types', {})

        if not field_types or not isinstance(data, dict):
            return

        type_map = {
            'string': str,
            'integer': int,
            'number': (int, float),
            'boolean': bool,
            'array': list,
            'object': dict,
        }

        for field_name, expected_type in field_types.items():
            if field_name not in data:
                continue  # Missing field handled by required_fields check

            value = data[field_name]
            if value is None:
                continue  # Allow None (null) values

            python_types = type_map.get(expected_type)
            if python_types and not isinstance(value, python_types):
                result.add_issue(ValidationIssue(
                    check_name="field_type",
                    severity="warning",
                    message=f"Field {field_name} has wrong type: expected {expected_type}, got {type(value).__name__}",
                    field=field_name,
                    expected=expected_type,
                    actual=type(value).__name__
                ))

    def _validate_value_ranges(self, data: Any, result: ValidationResult):
        """Validate numeric values are within expected ranges"""
        value_ranges = self.config.get('value_ranges', [])

        if not value_ranges:
            return

        # Handle both list and dict formats
        if isinstance(value_ranges, dict):
            # Dict format for market-specific ranges
            market_type = data.get('market_type') if isinstance(data, dict) else None
            if market_type and market_type in value_ranges:
                ranges = [value_ranges[market_type]]
            else:
                ranges = []
        else:
            ranges = value_ranges

        for range_config in ranges:
            field_name = range_config.get('field')
            if not field_name:
                continue

            # Get the value (supports nested fields with dots)
            value = self._get_nested_value(data, field_name)
            if value is None or not isinstance(value, (int, float)):
                continue

            min_val = range_config.get('min')
            max_val = range_config.get('max')
            severity = range_config.get('severity', 'warning')

            if min_val is not None and value < min_val:
                result.add_issue(ValidationIssue(
                    check_name="value_range_min",
                    severity=severity,
                    message=range_config.get('message', f"Value {value} below minimum {min_val}"),
                    field=field_name,
                    expected=f">= {min_val}",
                    actual=value
                ))

            if max_val is not None and value > max_val:
                result.add_issue(ValidationIssue(
                    check_name="value_range_max",
                    severity=severity,
                    message=range_config.get('message', f"Value {value} above maximum {max_val}"),
                    field=field_name,
                    expected=f"<= {max_val}",
                    actual=value
                ))

    def _run_custom_validations(self, data: Any, result: ValidationResult, opts: Dict):
        """Run custom validation checks defined in config"""
        custom_validations = self.config.get('custom_validations', [])

        for validation in custom_validations:
            name = validation.get('name')
            if not name:
                continue

            # Dispatch to specific validation methods
            method_name = f'_validate_{name}'
            if hasattr(self, method_name):
                try:
                    getattr(self, method_name)(data, result, validation, opts)
                except Exception as e:
                    logger.warning(f"Custom validation {name} failed: {e}")
            else:
                # Log that validation is defined but not implemented
                logger.debug(f"Custom validation {name} not implemented")

    def _handle_zero_rows(self, data: Any, result: ValidationResult, opts: Dict):
        """Handle zero row case - determine if acceptable"""
        zero_config = self.config.get('zero_row_handling', {})

        if not zero_config:
            return

        acceptable_reasons = zero_config.get('acceptable_reasons', [])
        severity = zero_config.get('severity', 'warning')

        # Check for acceptable conditions
        reason = self._diagnose_zero_rows(data, opts, zero_config)

        if reason in acceptable_reasons:
            result.add_issue(ValidationIssue(
                check_name="zero_rows_acceptable",
                severity="info",
                message=f"Zero rows is acceptable: {reason}"
            ))
        else:
            result.add_issue(ValidationIssue(
                check_name="zero_rows",
                severity=severity,
                message=f"Unexpected zero rows: {reason or 'unknown reason'}"
            ))

    def _diagnose_zero_rows(self, data: Any, opts: Dict, config: Dict) -> Optional[str]:
        """Diagnose why there are zero rows"""
        # Check common patterns
        if opts.get('off_day'):
            return 'off_day'

        if opts.get('preseason'):
            return 'preseason_game'

        if opts.get('all_star'):
            return 'all_star_game'

        # Add more diagnosis logic as needed
        return None

    def _get_nested_value(self, data: Any, field_path: str) -> Any:
        """Get value from nested field path (e.g., 'teams.home.points')"""
        if not isinstance(data, dict):
            return None

        parts = field_path.split('.')
        value = data

        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None

        return value

    # Custom validation implementations

    def _validate_two_teams_present(self, data: Any, result: ValidationResult, config: Dict, opts: Dict):
        """Validate exactly 2 teams in boxscore"""
        if not isinstance(data, dict):
            return

        teams = data.get('teams', {})
        if len(teams) != 2:
            result.add_issue(ValidationIssue(
                check_name="two_teams_present",
                severity=config.get('severity', 'error'),
                message=f"Expected 2 teams, found {len(teams)}",
                expected=2,
                actual=len(teams)
            ))

    def _validate_unique_game_ids(self, data: Any, result: ValidationResult, config: Dict, opts: Dict):
        """Validate all game IDs are unique"""
        if not isinstance(data, dict):
            return

        games = data.get('games', [])
        game_ids = [g.get('gameId') for g in games if isinstance(g, dict)]

        if len(game_ids) != len(set(game_ids)):
            duplicates = [gid for gid in game_ids if game_ids.count(gid) > 1]
            result.add_issue(ValidationIssue(
                check_name="unique_game_ids",
                severity=config.get('severity', 'error'),
                message=f"Duplicate game IDs found: {set(duplicates)}",
                actual=duplicates
            ))

    def _validate_balanced_player_count(self, data: Any, result: ValidationResult, config: Dict, opts: Dict):
        """Validate each team has balanced player count"""
        if not isinstance(data, dict):
            return

        players = data.get('players', [])
        teams = {}

        for player in players:
            if not isinstance(player, dict):
                continue
            team = player.get('team')
            if team:
                teams[team] = teams.get(team, 0) + 1

        min_per_team = config.get('min_per_team', 8)
        max_per_team = config.get('max_per_team', 15)

        for team, count in teams.items():
            if count < min_per_team or count > max_per_team:
                result.add_issue(ValidationIssue(
                    check_name="balanced_player_count",
                    severity=config.get('severity', 'warning'),
                    message=f"Team {team} has {count} players (expected {min_per_team}-{max_per_team})",
                    field=f"team_{team}",
                    expected=f"{min_per_team}-{max_per_team}",
                    actual=count
                ))

    def _validate_line_consistency(self, data: Any, result: ValidationResult, config: Dict, opts: Dict):
        """Validate lines for same player are consistent across bookmakers"""
        if not isinstance(data, dict):
            return

        props = data.get('props', [])
        max_variance = config.get('max_variance', 3.0)

        # Group lines by player
        player_lines = {}
        for prop in props:
            if not isinstance(prop, dict):
                continue

            player_name = prop.get('player_name')
            if not player_name:
                continue

            # Extract lines from over/under selections
            over = prop.get('over', {})
            for book in over.get('sportsbooks', []):
                line = book.get('line')
                if line is not None:
                    if player_name not in player_lines:
                        player_lines[player_name] = []
                    player_lines[player_name].append(line)

        # Check variance
        for player, lines in player_lines.items():
            if len(lines) < 2:
                continue

            variance = max(lines) - min(lines)
            if variance > max_variance:
                result.add_issue(ValidationIssue(
                    check_name="line_consistency",
                    severity=config.get('severity', 'warning'),
                    message=f"High line variance for {player}: {min(lines)}-{max(lines)} ({variance:.1f})",
                    field=player,
                    expected=f"<= {max_variance}",
                    actual=variance
                ))


def get_validator(scraper_name: str) -> ScraperOutputValidator:
    """Factory function to get validator for a scraper"""
    return ScraperOutputValidator(scraper_name)


def validate_scraper_output(scraper_name: str, data: Any, opts: Optional[Dict] = None) -> ValidationResult:
    """
    Convenience function to validate scraper output.

    Args:
        scraper_name: Name of the scraper
        data: Output data to validate
        opts: Optional scraper options

    Returns:
        ValidationResult
    """
    validator = get_validator(scraper_name)
    return validator.validate(data, opts)
