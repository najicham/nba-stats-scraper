"""
Precompute Operations

Extracted operations from PrecomputeProcessorBase for better modularity.

Modules:
- bigquery_save_ops: BigQuery save operations (save_precompute, MERGE strategies)
- failure_tracking: Failure classification and persistence
- metadata_ops: Source tracking and metadata field building

Created: 2026-01-25
"""

from .bigquery_save_ops import BigQuerySaveOpsMixin
from .failure_tracking import FailureTrackingMixin
from .metadata_ops import PrecomputeMetadataOpsMixin

__all__ = [
    'BigQuerySaveOpsMixin',
    'FailureTrackingMixin',
    'PrecomputeMetadataOpsMixin',
]
