"""Registry — single source of truth for signal + filter names.

Loaded by ml/signals/aggregator.py and ml/signals/per_model_pipeline.py at
import time. Documentation files (CLAUDE.md, .claude/skills/, docs/) are
validated against this registry by .pre-commit-hooks/validate_signal_references.py.

Pipeline-state-redesign Phase H.
"""

from .loader import (
    SignalSpec,
    FilterSpec,
    load_signal_registry,
    load_filter_registry,
    is_known_signal,
    is_known_filter,
)

__all__ = [
    'SignalSpec',
    'FilterSpec',
    'load_signal_registry',
    'load_filter_registry',
    'is_known_signal',
    'is_known_filter',
]
