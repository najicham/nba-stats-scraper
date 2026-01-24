"""
Pipeline Validation Module

Comprehensive validation for the NBA stats processing pipeline.
Validates data flow, completeness, and quality across all phases.

Usage:
    from shared.validation import validate_date, ValidationResult

    result = validate_date('2021-10-19')
    print(result.overall_status)

Historical Completeness (Jan 2026):
    from shared.validation.historical_completeness import assess_historical_completeness

    result = assess_historical_completeness(games_found=8, games_available=50)
    print(result.is_complete, result.is_bootstrap)
"""

from shared.validation.config import (
    EXPECTED_PREDICTION_SYSTEMS,
    PHASE2_SOURCES,
    PHASE3_TABLES,
    PHASE4_TABLES,
    QUALITY_TIERS,
)

# Historical Completeness Tracking (Data Cascade Architecture - Jan 2026)
from shared.validation.historical_completeness import (
    assess_historical_completeness,
    should_skip_feature_generation,
    HistoricalCompletenessResult,
    WINDOW_SIZE,
    MINIMUM_GAMES_THRESHOLD,
)

__all__ = [
    'EXPECTED_PREDICTION_SYSTEMS',
    'PHASE2_SOURCES',
    'PHASE3_TABLES',
    'PHASE4_TABLES',
    'QUALITY_TIERS',
    # Historical Completeness
    'assess_historical_completeness',
    'should_skip_feature_generation',
    'HistoricalCompletenessResult',
    'WINDOW_SIZE',
    'MINIMUM_GAMES_THRESHOLD',
]
