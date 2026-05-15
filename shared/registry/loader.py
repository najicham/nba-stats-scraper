"""Registry loader — read signals.yaml + filters.yaml; expose helpers.

The YAML files are the source of truth. Code imports from here. Docs are
validated against here. When code changes a signal/filter, update the YAML
in the same commit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Set

try:
    import yaml
except ImportError:  # pragma: no cover — yaml is in requirements
    yaml = None  # type: ignore

REGISTRY_DIR = Path(__file__).parent


@dataclass(frozen=True)
class SignalSpec:
    """One row in signals.yaml."""
    tag: str
    status: str  # 'active' | 'shadow' | 'removed'
    weight: float
    direction: str  # 'over' | 'under' | 'both'
    rescue_priority: Optional[int]
    description: str
    introduced_session: Optional[int] = None
    deprecated_session: Optional[int] = None


@dataclass(frozen=True)
class FilterSpec:
    """One row in filters.yaml."""
    tag: str
    status: str  # 'active' | 'observation' | 'removed'
    blocks_direction: str  # 'over' | 'under' | 'both'
    description: str
    introduced_session: Optional[int] = None
    deprecated_session: Optional[int] = None


def _read_yaml(path: Path) -> Dict:
    if yaml is None:
        raise RuntimeError("PyYAML is required for shared.registry — install pyyaml")
    if not path.exists():
        raise FileNotFoundError(f"Registry file missing: {path}")
    with path.open('r') as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def load_signal_registry() -> Dict[str, SignalSpec]:
    """Load all signals from signals.yaml. Keyed by signal tag."""
    raw = _read_yaml(REGISTRY_DIR / 'signals.yaml')
    out: Dict[str, SignalSpec] = {}
    for entry in raw.get('signals', []):
        spec = SignalSpec(
            tag=entry['tag'],
            status=entry.get('status', 'active'),
            # Default 0.0 (not 1.0): a missing `weight:` field implies the
            # signal doesn't contribute to ranking, not that it does at full
            # strength. Active-weighted signals must declare `weight:` explicitly.
            weight=float(entry.get('weight', 0.0)),
            direction=entry.get('direction', 'both'),
            rescue_priority=entry.get('rescue_priority'),
            description=entry.get('description', ''),
            introduced_session=entry.get('introduced_session'),
            deprecated_session=entry.get('deprecated_session'),
        )
        out[spec.tag] = spec
    return out


@lru_cache(maxsize=1)
def load_filter_registry() -> Dict[str, FilterSpec]:
    """Load all filters from filters.yaml. Keyed by filter tag."""
    raw = _read_yaml(REGISTRY_DIR / 'filters.yaml')
    out: Dict[str, FilterSpec] = {}
    for entry in raw.get('filters', []):
        spec = FilterSpec(
            tag=entry['tag'],
            status=entry.get('status', 'active'),
            blocks_direction=entry.get('blocks_direction', 'both'),
            description=entry.get('description', ''),
            introduced_session=entry.get('introduced_session'),
            deprecated_session=entry.get('deprecated_session'),
        )
        out[spec.tag] = spec
    return out


def is_known_signal(tag: str, allow_removed: bool = False) -> bool:
    reg = load_signal_registry()
    if tag not in reg:
        return False
    if not allow_removed and reg[tag].status == 'removed':
        return False
    return True


def is_known_filter(tag: str, allow_removed: bool = False) -> bool:
    reg = load_filter_registry()
    if tag not in reg:
        return False
    if not allow_removed and reg[tag].status == 'removed':
        return False
    return True
