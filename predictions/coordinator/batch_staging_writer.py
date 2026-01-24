# predictions/coordinator/batch_staging_writer.py
"""
BACKWARD COMPATIBILITY SHIM

This module has been consolidated into predictions/shared/batch_staging_writer.py.
This shim exists for backward compatibility with existing imports.

Please update imports to use:
    from predictions.shared.batch_staging_writer import BatchStagingWriter, BatchConsolidator

This shim will be removed in a future release.
"""

import warnings

warnings.warn(
    "predictions.coordinator.batch_staging_writer is deprecated. "
    "Use predictions.shared.batch_staging_writer instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export everything from the shared module
from predictions.shared.batch_staging_writer import (
    BatchStagingWriter,
    BatchConsolidator,
    StagingWriteResult,
    ConsolidationResult,
    create_batch_id,
    get_worker_id,
    STAGING_DATASET,
    MAIN_PREDICTIONS_TABLE,
)

__all__ = [
    'BatchStagingWriter',
    'BatchConsolidator',
    'StagingWriteResult',
    'ConsolidationResult',
    'create_batch_id',
    'get_worker_id',
    'STAGING_DATASET',
    'MAIN_PREDICTIONS_TABLE',
]
