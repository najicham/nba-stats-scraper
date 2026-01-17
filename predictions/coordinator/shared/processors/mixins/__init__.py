"""
Shared processor mixins for cross-cutting concerns.

Mixins available:
- RunHistoryMixin: Logs processor runs to processor_run_history table
"""

from .run_history_mixin import RunHistoryMixin

__all__ = ['RunHistoryMixin']
