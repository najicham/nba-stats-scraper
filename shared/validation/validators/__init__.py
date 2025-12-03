"""
Phase Validators

Validators for each phase of the pipeline:
- Phase 1: GCS raw JSON files (scraper output)
- Phase 2: Raw data in BigQuery (processor output)
- Phase 3: Analytics validation
- Phase 4: Precompute validation
- Phase 5: Predictions validation
"""

from shared.validation.validators.base import (
    PhaseValidationResult,
    TableValidation,
    ValidationStatus,
    DataIntegrityResult,
    check_data_integrity,
    check_cross_table_consistency,
    query_duplicate_count,
    query_null_critical_fields,
)
from shared.validation.validators.phase1_validator import validate_phase1
from shared.validation.validators.phase2_validator import validate_phase2
from shared.validation.validators.phase3_validator import validate_phase3
from shared.validation.validators.phase4_validator import validate_phase4
from shared.validation.validators.phase5_validator import validate_phase5

__all__ = [
    'PhaseValidationResult',
    'TableValidation',
    'ValidationStatus',
    'DataIntegrityResult',
    'check_data_integrity',
    'check_cross_table_consistency',
    'query_duplicate_count',
    'query_null_critical_fields',
    'validate_phase1',
    'validate_phase2',
    'validate_phase3',
    'validate_phase4',
    'validate_phase5',
]
