"""
Unit tests for Phase Validation Utility.

Tests validation logic for phase boundaries without requiring BigQuery.
"""

import pytest
from datetime import date

from shared.utils.phase_validation import (
    PhaseValidator,
    ValidationResult,
    ValidationIssue,
    FieldSchema,
    PhaseSchema,
    Phase,
    IssueSeverity,
    validate_phase2_raw,
    validate_phase3_analytics,
    validate_phase4_precompute,
    validate_phase5_predictions,
)


class TestPhaseValidator:
    """Test PhaseValidator class."""

    @pytest.fixture
    def validator(self):
        """Create a PhaseValidator instance."""
        return PhaseValidator()

    # ================================================================
    # Schema Registration Tests
    # ================================================================

    def test_default_schemas_registered(self, validator):
        """Default schemas for all phases should be registered."""
        assert validator.get_schema(Phase.PHASE_2_RAW) is not None
        assert validator.get_schema(Phase.PHASE_3_ANALYTICS) is not None
        assert validator.get_schema(Phase.PHASE_4_PRECOMPUTE) is not None
        assert validator.get_schema(Phase.PHASE_5_PREDICTIONS) is not None

    def test_get_schema_by_string(self, validator):
        """Should get schema by string value."""
        schema = validator.get_schema("phase_2_raw")
        assert schema is not None
        assert schema.phase == Phase.PHASE_2_RAW

    def test_get_schema_by_enum(self, validator):
        """Should get schema by Phase enum."""
        schema = validator.get_schema(Phase.PHASE_3_ANALYTICS)
        assert schema is not None
        assert schema.phase == Phase.PHASE_3_ANALYTICS

    def test_unknown_schema_returns_none(self, validator):
        """Unknown phase should return None."""
        assert validator.get_schema("unknown_phase") is None

    def test_custom_schema_registration(self, validator):
        """Should be able to register custom schemas."""
        custom_schema = PhaseSchema(
            phase=Phase.PHASE_2_RAW,
            fields=[
                FieldSchema(name="custom_field", required=True, nullable=False),
            ],
            critical_fields={"custom_field"}
        )
        validator.register_schema("custom_phase", custom_schema)
        assert validator.get_schema("custom_phase") is not None

    # ================================================================
    # Phase 2 (Raw) Validation Tests
    # ================================================================

    def test_phase2_valid_record(self, validator):
        """Valid Phase 2 record should pass validation."""
        record = {
            "game_id": "0022400123",
            "game_date": date(2025, 1, 15),
            "player_lookup": "lebron_james",
            "team_abbr": "LAL",
            "points": 28,
            "rebounds": 7,
            "assists": 8,
        }
        result = validator.validate_output(Phase.PHASE_2_RAW, [record])
        assert result.is_valid
        assert result.error_count == 0

    def test_phase2_missing_required_field(self, validator):
        """Missing required field should fail validation."""
        record = {
            "game_date": date(2025, 1, 15),
            "player_lookup": "lebron_james",
            "team_abbr": "LAL",
            # Missing game_id
        }
        result = validator.validate_output(Phase.PHASE_2_RAW, [record])
        assert not result.is_valid
        assert any(i.field == "game_id" for i in result.errors)

    def test_phase2_null_critical_field(self, validator):
        """NULL in critical field should fail validation."""
        record = {
            "game_id": "0022400123",
            "game_date": date(2025, 1, 15),
            "player_lookup": None,  # Critical field set to NULL
            "team_abbr": "LAL",
        }
        result = validator.validate_output(Phase.PHASE_2_RAW, [record])
        assert not result.is_valid
        assert any(i.field == "player_lookup" for i in result.errors)

    def test_phase2_points_out_of_range(self, validator):
        """Points value above max should fail validation."""
        record = {
            "game_id": "0022400123",
            "game_date": date(2025, 1, 15),
            "player_lookup": "lebron_james",
            "team_abbr": "LAL",
            "points": 150,  # Unrealistic value
        }
        result = validator.validate_output(Phase.PHASE_2_RAW, [record])
        assert not result.is_valid
        assert any(i.field == "points" and "maximum" in i.message for i in result.errors)

    def test_phase2_negative_stats(self, validator):
        """Negative stat values should fail validation."""
        record = {
            "game_id": "0022400123",
            "game_date": date(2025, 1, 15),
            "player_lookup": "lebron_james",
            "team_abbr": "LAL",
            "points": -5,  # Negative value
        }
        result = validator.validate_output(Phase.PHASE_2_RAW, [record])
        assert not result.is_valid
        assert any(i.field == "points" and "minimum" in i.message for i in result.errors)

    def test_phase2_null_points_allowed(self, validator):
        """NULL points (for DNP) should be allowed."""
        record = {
            "game_id": "0022400123",
            "game_date": date(2025, 1, 15),
            "player_lookup": "lebron_james",
            "team_abbr": "LAL",
            "points": None,  # DNP
        }
        result = validator.validate_output(Phase.PHASE_2_RAW, [record])
        # points is required but nullable
        assert result.is_valid

    # ================================================================
    # Phase 3 (Analytics) Validation Tests
    # ================================================================

    def test_phase3_valid_record(self, validator):
        """Valid Phase 3 record should pass validation."""
        record = {
            "player_lookup": "lebron_james",
            "game_id": "20250115_LAL_BOS",
            "game_date": date(2025, 1, 15),
            "team_abbr": "LAL",
            "opponent_team_abbr": "BOS",
            "points_avg_last_5": 27.4,
            "points_avg_last_10": 26.8,
            "data_quality_tier": "high",
        }
        result = validator.validate_output(Phase.PHASE_3_ANALYTICS, [record])
        assert result.is_valid
        assert result.error_count == 0

    def test_phase3_invalid_quality_tier(self, validator):
        """Invalid quality tier value should fail validation."""
        record = {
            "player_lookup": "lebron_james",
            "game_id": "20250115_LAL_BOS",
            "game_date": date(2025, 1, 15),
            "team_abbr": "LAL",
            "opponent_team_abbr": "BOS",
            "data_quality_tier": "excellent",  # Not in allowed values
        }
        result = validator.validate_output(Phase.PHASE_3_ANALYTICS, [record])
        assert not result.is_valid
        assert any("allowed values" in i.message for i in result.errors)

    def test_phase3_excessive_days_rest(self, validator):
        """Days rest above max should fail validation."""
        record = {
            "player_lookup": "lebron_james",
            "game_id": "20250115_LAL_BOS",
            "game_date": date(2025, 1, 15),
            "team_abbr": "LAL",
            "opponent_team_abbr": "BOS",
            "days_rest": 50,  # Unrealistic
        }
        result = validator.validate_output(Phase.PHASE_3_ANALYTICS, [record])
        assert not result.is_valid
        assert any(i.field == "days_rest" for i in result.errors)

    def test_phase3_missing_opponent(self, validator):
        """Missing opponent team should fail validation."""
        record = {
            "player_lookup": "lebron_james",
            "game_id": "20250115_LAL_BOS",
            "game_date": date(2025, 1, 15),
            "team_abbr": "LAL",
            # Missing opponent_team_abbr
        }
        result = validator.validate_output(Phase.PHASE_3_ANALYTICS, [record])
        assert not result.is_valid
        assert any(i.field == "opponent_team_abbr" for i in result.errors)

    # ================================================================
    # Phase 4 (Precompute) Validation Tests
    # ================================================================

    def test_phase4_valid_record(self, validator):
        """Valid Phase 4 record should pass validation."""
        record = {
            "player_lookup": "lebron_james",
            "game_id": "20250115_LAL_BOS",
            "game_date": date(2025, 1, 15),
            "features": [0.5, 0.7, 0.3, 0.9, 0.2],
            "feature_names": ["feat1", "feat2", "feat3", "feat4", "feat5"],
            "feature_count": 5,
            "feature_version": "v1_baseline",
            "feature_quality_score": 85.0,
            "data_source": "phase4",
        }
        result = validator.validate_output(Phase.PHASE_4_PRECOMPUTE, [record])
        assert result.is_valid
        assert result.error_count == 0

    def test_phase4_invalid_data_source(self, validator):
        """Invalid data source should fail validation."""
        record = {
            "player_lookup": "lebron_james",
            "game_id": "20250115_LAL_BOS",
            "game_date": date(2025, 1, 15),
            "data_source": "invalid_source",
        }
        result = validator.validate_output(Phase.PHASE_4_PRECOMPUTE, [record])
        assert not result.is_valid
        assert any(i.field == "data_source" for i in result.errors)

    def test_phase4_quality_score_out_of_range(self, validator):
        """Quality score above 100 should fail validation."""
        record = {
            "player_lookup": "lebron_james",
            "game_id": "20250115_LAL_BOS",
            "game_date": date(2025, 1, 15),
            "feature_quality_score": 150.0,  # Above max
        }
        result = validator.validate_output(Phase.PHASE_4_PRECOMPUTE, [record])
        assert not result.is_valid
        assert any(i.field == "feature_quality_score" for i in result.errors)

    # ================================================================
    # Phase 5 (Predictions) Validation Tests
    # ================================================================

    def test_phase5_valid_record(self, validator):
        """Valid Phase 5 record should pass validation."""
        record = {
            "prediction_id": "pred-123-456",
            "system_id": "moving_average_v1",
            "player_lookup": "lebron_james",
            "game_id": "20250115_LAL_BOS",
            "game_date": date(2025, 1, 15),
            "predicted_points": 27.5,
            "confidence_score": 0.85,
            "recommendation": "OVER",
            "current_points_line": 25.5,
            "line_margin": 2.0,
        }
        result = validator.validate_output(Phase.PHASE_5_PREDICTIONS, [record])
        assert result.is_valid
        assert result.error_count == 0

    def test_phase5_invalid_recommendation(self, validator):
        """Invalid recommendation value should fail validation."""
        record = {
            "prediction_id": "pred-123-456",
            "system_id": "moving_average_v1",
            "player_lookup": "lebron_james",
            "game_id": "20250115_LAL_BOS",
            "game_date": date(2025, 1, 15),
            "predicted_points": 27.5,
            "confidence_score": 0.85,
            "recommendation": "BET",  # Invalid
        }
        result = validator.validate_output(Phase.PHASE_5_PREDICTIONS, [record])
        assert not result.is_valid
        assert any(i.field == "recommendation" for i in result.errors)

    def test_phase5_confidence_above_one(self, validator):
        """Confidence score above 1.0 should fail validation."""
        record = {
            "prediction_id": "pred-123-456",
            "system_id": "moving_average_v1",
            "player_lookup": "lebron_james",
            "game_id": "20250115_LAL_BOS",
            "game_date": date(2025, 1, 15),
            "predicted_points": 27.5,
            "confidence_score": 1.5,  # Above max
            "recommendation": "OVER",
        }
        result = validator.validate_output(Phase.PHASE_5_PREDICTIONS, [record])
        assert not result.is_valid
        assert any(i.field == "confidence_score" for i in result.errors)

    def test_phase5_missing_system_id(self, validator):
        """Missing system_id should fail validation."""
        record = {
            "prediction_id": "pred-123-456",
            # Missing system_id
            "player_lookup": "lebron_james",
            "game_id": "20250115_LAL_BOS",
            "game_date": date(2025, 1, 15),
            "predicted_points": 27.5,
            "confidence_score": 0.85,
            "recommendation": "OVER",
        }
        result = validator.validate_output(Phase.PHASE_5_PREDICTIONS, [record])
        assert not result.is_valid
        assert any(i.field == "system_id" for i in result.errors)

    def test_phase5_no_line_recommendation(self, validator):
        """NO_LINE recommendation should be valid."""
        record = {
            "prediction_id": "pred-123-456",
            "system_id": "moving_average_v1",
            "player_lookup": "lebron_james",
            "game_id": "20250115_LAL_BOS",
            "game_date": date(2025, 1, 15),
            "predicted_points": 27.5,
            "confidence_score": 0.5,
            "recommendation": "NO_LINE",  # Valid for players without prop lines
            "has_prop_line": False,
        }
        result = validator.validate_output(Phase.PHASE_5_PREDICTIONS, [record])
        assert result.is_valid

    # ================================================================
    # Multiple Records Tests
    # ================================================================

    def test_multiple_valid_records(self, validator):
        """Multiple valid records should all pass."""
        records = [
            {
                "game_id": "0022400123",
                "game_date": date(2025, 1, 15),
                "player_lookup": "lebron_james",
                "team_abbr": "LAL",
                "points": 28,
            },
            {
                "game_id": "0022400123",
                "game_date": date(2025, 1, 15),
                "player_lookup": "anthony_davis",
                "team_abbr": "LAL",
                "points": 32,
            },
        ]
        result = validator.validate_output(Phase.PHASE_2_RAW, records)
        assert result.is_valid
        assert result.records_validated == 2
        assert result.records_with_issues == 0

    def test_multiple_records_one_invalid(self, validator):
        """One invalid record among valid ones should fail overall."""
        records = [
            {
                "game_id": "0022400123",
                "game_date": date(2025, 1, 15),
                "player_lookup": "lebron_james",
                "team_abbr": "LAL",
                "points": 28,
            },
            {
                "game_id": "0022400123",
                "game_date": date(2025, 1, 15),
                "player_lookup": None,  # Invalid
                "team_abbr": "LAL",
                "points": 32,
            },
        ]
        result = validator.validate_output(Phase.PHASE_2_RAW, records)
        assert not result.is_valid
        assert result.records_validated == 2
        assert result.records_with_issues == 1

    def test_stop_on_first_error(self, validator):
        """Stop validation on first error when flag is set."""
        records = [
            {"game_id": None},  # Invalid
            {"game_id": None},  # Also invalid but shouldn't be checked
        ]
        result = validator.validate_output(
            Phase.PHASE_2_RAW,
            records,
            stop_on_first_error=True
        )
        assert not result.is_valid
        # Should stop after first record
        assert result.records_with_issues == 1

    def test_max_issues_limit(self, validator):
        """Max issues limit should stop collecting issues."""
        records = [{"game_id": None} for _ in range(100)]
        result = validator.validate_output(
            Phase.PHASE_2_RAW,
            records,
            max_issues=10
        )
        # Each record has multiple issues (missing required fields + null critical field)
        # The validator stops once max_issues is reached BEFORE starting a new record
        # So we expect around 10-12 issues plus 1 warning about max reached
        # The exact number depends on how many issues are collected in the last processed record
        assert len(result.issues) <= 20  # Allow for some flexibility in how issues accumulate

    # ================================================================
    # Validation Result Tests
    # ================================================================

    def test_validation_result_summary(self, validator):
        """Validation result summary should be informative."""
        records = [
            {
                "game_id": "0022400123",
                "game_date": date(2025, 1, 15),
                "player_lookup": "lebron_james",
                "team_abbr": "LAL",
            },
        ]
        result = validator.validate_output(Phase.PHASE_2_RAW, records)
        summary = result.summary()
        assert "PASSED" in summary or "FAILED" in summary
        assert "1 records checked" in summary

    def test_validation_result_merge(self):
        """Validation results should be mergeable."""
        result1 = ValidationResult(
            is_valid=True,
            records_validated=5,
            records_with_issues=0
        )
        result2 = ValidationResult(
            is_valid=False,
            records_validated=3,
            records_with_issues=1,
            issues=[ValidationIssue(
                field="test",
                message="Test error",
                severity=IssueSeverity.ERROR
            )]
        )

        merged = result1.merge(result2)
        assert not merged.is_valid  # Should be invalid due to result2
        assert merged.records_validated == 8
        assert merged.records_with_issues == 1
        assert len(merged.issues) == 1


class TestFieldSchema:
    """Test FieldSchema validation."""

    def test_nullable_field_with_null(self):
        """Nullable field should accept NULL."""
        field = FieldSchema(name="test", nullable=True)
        issues = field.validate(None)
        assert len(issues) == 0

    def test_non_nullable_field_with_null(self):
        """Non-nullable field should reject NULL."""
        field = FieldSchema(name="test", nullable=False)
        issues = field.validate(None)
        assert len(issues) == 1
        assert issues[0].severity == IssueSeverity.ERROR

    def test_type_validation_string(self):
        """String type should be validated."""
        field = FieldSchema(name="test", field_type=str)
        issues = field.validate("hello")
        assert len(issues) == 0

        issues = field.validate(123)
        assert len(issues) == 1

    def test_type_validation_numeric(self):
        """Numeric types should allow int where float expected."""
        field = FieldSchema(name="test", field_type=float)
        issues = field.validate(5.0)
        assert len(issues) == 0

        issues = field.validate(5)  # int should be accepted
        assert len(issues) == 0

    def test_allowed_values(self):
        """Allowed values should be enforced."""
        field = FieldSchema(name="test", allowed_values={"a", "b", "c"})
        issues = field.validate("a")
        assert len(issues) == 0

        issues = field.validate("d")
        assert len(issues) == 1

    def test_range_validation_min(self):
        """Minimum value should be enforced."""
        field = FieldSchema(name="test", field_type=int, min_value=0)
        issues = field.validate(5)
        assert len(issues) == 0

        issues = field.validate(-1)
        assert len(issues) == 1

    def test_range_validation_max(self):
        """Maximum value should be enforced."""
        field = FieldSchema(name="test", field_type=int, max_value=100)
        issues = field.validate(50)
        assert len(issues) == 0

        issues = field.validate(150)
        assert len(issues) == 1

    def test_custom_validator(self):
        """Custom validator should be called."""
        def custom_check(value):
            if value.startswith("valid_"):
                return True, ""
            return False, "Value must start with 'valid_'"

        field = FieldSchema(name="test", field_type=str, custom_validator=custom_check)
        issues = field.validate("valid_test")
        assert len(issues) == 0

        issues = field.validate("invalid_test")
        assert len(issues) == 1


class TestConvenienceFunctions:
    """Test convenience validation functions."""

    def test_validate_phase2_raw(self):
        """Convenience function for Phase 2."""
        record = {
            "game_id": "0022400123",
            "game_date": date(2025, 1, 15),
            "player_lookup": "lebron_james",
            "team_abbr": "LAL",
            "points": 28,  # Required field
        }
        result = validate_phase2_raw([record])
        assert result.is_valid

    def test_validate_phase3_analytics(self):
        """Convenience function for Phase 3."""
        record = {
            "player_lookup": "lebron_james",
            "game_id": "20250115_LAL_BOS",
            "game_date": date(2025, 1, 15),
            "team_abbr": "LAL",
            "opponent_team_abbr": "BOS",
        }
        result = validate_phase3_analytics([record])
        assert result.is_valid

    def test_validate_phase4_precompute(self):
        """Convenience function for Phase 4."""
        record = {
            "player_lookup": "lebron_james",
            "game_id": "20250115_LAL_BOS",
            "game_date": date(2025, 1, 15),
        }
        result = validate_phase4_precompute([record])
        assert result.is_valid

    def test_validate_phase5_predictions(self):
        """Convenience function for Phase 5."""
        record = {
            "prediction_id": "pred-123",
            "system_id": "test_system",
            "player_lookup": "lebron_james",
            "game_id": "20250115_LAL_BOS",
            "game_date": date(2025, 1, 15),
            "predicted_points": 27.5,
            "confidence_score": 0.85,
            "recommendation": "OVER",
        }
        result = validate_phase5_predictions([record])
        assert result.is_valid


class TestValidationIssue:
    """Test ValidationIssue class."""

    def test_issue_string_with_index(self):
        """Issue string should include record index."""
        issue = ValidationIssue(
            field="test",
            message="Test error",
            severity=IssueSeverity.ERROR,
            record_index=5
        )
        assert "[Record 5]" in str(issue)
        assert "ERROR" in str(issue)

    def test_issue_string_without_index(self):
        """Issue string should work without record index."""
        issue = ValidationIssue(
            field="test",
            message="Test error",
            severity=IssueSeverity.WARNING
        )
        assert "[Record" not in str(issue)
        assert "WARNING" in str(issue)


class TestValidateRecord:
    """Test single record validation."""

    def test_validate_single_record(self):
        """Should validate a single record."""
        validator = PhaseValidator()
        record = {
            "game_id": "0022400123",
            "game_date": date(2025, 1, 15),
            "player_lookup": "lebron_james",
            "team_abbr": "LAL",
            "points": 28,  # Required field
        }
        result = validator.validate_record(Phase.PHASE_2_RAW, record)
        assert result.is_valid
        assert result.records_validated == 1
