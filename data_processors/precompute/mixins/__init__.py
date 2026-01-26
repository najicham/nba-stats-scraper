"""
File: data_processors/precompute/mixins/__init__.py

Exports for precompute-specific mixins.

These mixins provide specialized functionality for Phase 4 precompute processors:
- BackfillModeMixin: Backfill mode detection and validation
- DefensiveCheckMixin: Defensive checks for upstream data validation

Version: 1.1
Created: 2026-01-25
Updated: 2026-01-25 - Added DefensiveCheckMixin
"""

from .backfill_mode_mixin import BackfillModeMixin
from .defensive_check_mixin import DefensiveCheckMixin

__all__ = [
    'BackfillModeMixin',
    'DefensiveCheckMixin',
]
