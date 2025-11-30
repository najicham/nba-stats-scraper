"""
Shared backfill utilities.

Provides:
- BackfillCheckpoint: Progress persistence for long-running backfills
"""

from .checkpoint import BackfillCheckpoint

__all__ = ['BackfillCheckpoint']
