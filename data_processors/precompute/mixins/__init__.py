"""
File: data_processors/precompute/mixins/__init__.py

Exports for precompute-specific mixins.

These mixins provide specialized functionality for Phase 4 precompute processors:
- BackfillModeMixin: Backfill mode detection and validation

Version: 1.0
Created: 2026-01-25
"""

from .backfill_mode_mixin import BackfillModeMixin

__all__ = [
    'BackfillModeMixin',
]
