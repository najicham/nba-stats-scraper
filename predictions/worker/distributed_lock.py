# predictions/worker/distributed_lock.py
"""
BACKWARD COMPATIBILITY SHIM

This module has been consolidated into predictions/shared/distributed_lock.py.
This shim exists for backward compatibility with existing imports.

Please update imports to use:
    from predictions.shared.distributed_lock import DistributedLock, LockAcquisitionError

This shim will be removed in a future release.
"""

import warnings

warnings.warn(
    "predictions.worker.distributed_lock is deprecated. "
    "Use predictions.shared.distributed_lock instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export everything from the shared module
from predictions.shared.distributed_lock import (
    DistributedLock,
    LockAcquisitionError,
    ConsolidationLock,
    LOCK_TIMEOUT_SECONDS,
    MAX_ACQUIRE_ATTEMPTS,
    RETRY_DELAY_SECONDS,
)

__all__ = [
    'DistributedLock',
    'LockAcquisitionError',
    'ConsolidationLock',
    'LOCK_TIMEOUT_SECONDS',
    'MAX_ACQUIRE_ATTEMPTS',
    'RETRY_DELAY_SECONDS',
]
