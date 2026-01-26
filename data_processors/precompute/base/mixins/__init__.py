"""
Precompute processor base mixins.

Provides specialized functionality for Phase 4 precompute processors:
- QualityMixin: Date-level failure tracking and quality validation
- MetadataMixin: Source metadata tracking and dependency recording
- TemporalMixin: Date normalization and early season detection
- DependencyCheckingMixin: Table data validation and dependency queries
- OrchestrationHelpersMixin: Helper methods for run() orchestration

Version: 1.2
Created: 2026-01-25
Updated: 2026-01-25 - Added DependencyCheckingMixin, OrchestrationHelpersMixin
"""

from .quality_mixin import QualityMixin
from .metadata_mixin import MetadataMixin
from .temporal_mixin import TemporalMixin
from .dependency_checking_mixin import DependencyCheckingMixin
from .orchestration_helpers import OrchestrationHelpersMixin

__all__ = [
    'QualityMixin',
    'MetadataMixin',
    'TemporalMixin',
    'DependencyCheckingMixin',
    'OrchestrationHelpersMixin',
]
