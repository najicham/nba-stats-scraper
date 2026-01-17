"""
Pipeline Validation Module

Comprehensive validation for the NBA stats processing pipeline.
Validates data flow, completeness, and quality across all phases.

Usage:
    from shared.validation import validate_date, ValidationResult

    result = validate_date('2021-10-19')
    print(result.overall_status)
"""

from shared.validation.config import (
    EXPECTED_PREDICTION_SYSTEMS,
    PHASE2_SOURCES,
    PHASE3_TABLES,
    PHASE4_TABLES,
    QUALITY_TIERS,
)

__all__ = [
    'EXPECTED_PREDICTION_SYSTEMS',
    'PHASE2_SOURCES',
    'PHASE3_TABLES',
    'PHASE4_TABLES',
    'QUALITY_TIERS',
]
