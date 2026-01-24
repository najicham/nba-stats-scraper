# predictions/shared/__init__.py

"""
Shared utilities for NBA Props Platform prediction systems

This module contains shared code used by multiple prediction components:
- Batch staging writer for BigQuery DML operations
- Distributed lock for preventing race conditions
- Mock XGBoost model for testing
- Injury filter and integration for predictions
- Teammate impact calculations
- Shared data utilities (future)
- Common validation logic (future)
"""

__version__ = '2.1.0'

# Batch staging exports (consolidated from worker/coordinator)
from predictions.shared.batch_staging_writer import (
    BatchStagingWriter,
    BatchConsolidator,
    StagingWriteResult,
    ConsolidationResult,
    create_batch_id,
    get_worker_id,
)

# Distributed lock exports (consolidated from worker/coordinator)
from predictions.shared.distributed_lock import (
    DistributedLock,
    LockAcquisitionError,
    ConsolidationLock,  # Backward compatibility alias
)

# Injury handling exports
from predictions.shared.injury_filter import (
    InjuryFilter,
    InjuryStatus,
    TeammateImpact,
    get_injury_filter,
    check_injury_status
)

from predictions.shared.injury_integration import (
    InjuryIntegration,
    PlayerInjuryInfo,
    InjuryFilterResult,
    get_injury_integration,
    check_player_injury,
    get_teammate_impact,
    filter_out_injured
)

__all__ = [
    # Batch Staging Writer
    'BatchStagingWriter',
    'BatchConsolidator',
    'StagingWriteResult',
    'ConsolidationResult',
    'create_batch_id',
    'get_worker_id',

    # Distributed Lock
    'DistributedLock',
    'LockAcquisitionError',
    'ConsolidationLock',

    # Injury Filter (v1.0 - basic filtering)
    'InjuryFilter',
    'InjuryStatus',
    'TeammateImpact',
    'get_injury_filter',
    'check_injury_status',

    # Injury Integration (v2.0 - full integration)
    'InjuryIntegration',
    'PlayerInjuryInfo',
    'InjuryFilterResult',
    'get_injury_integration',
    'check_player_injury',
    'get_teammate_impact',
    'filter_out_injured',
]
