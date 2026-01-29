"""
Shared processor mixins for cross-cutting concerns.

Mixins available:
- RunHistoryMixin: Logs processor runs to processor_run_history table
- ProcessorVersionMixin: Tracks processor and schema versions
- DeploymentFreshnessMixin: Warns when processing with stale deployments
"""

from .run_history_mixin import RunHistoryMixin
from .version_tracking_mixin import ProcessorVersionMixin
from .deployment_freshness_mixin import DeploymentFreshnessMixin

__all__ = ['RunHistoryMixin', 'ProcessorVersionMixin', 'DeploymentFreshnessMixin']
