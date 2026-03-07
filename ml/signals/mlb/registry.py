"""MLB Signal Registry — discovers and instantiates all MLB signal classes.

Ports the NBA ml/signals/registry.py pattern for MLB pitcher strikeouts.
8 active signals + 6 shadow signals + 4 negative filters.
"""

from typing import Dict, List
from ml.signals.mlb.base_signal import BaseMLBSignal


class MLBSignalRegistry:
    """Registry that holds all available MLB signal evaluators."""

    def __init__(self):
        self._signals: Dict[str, BaseMLBSignal] = {}

    def register(self, signal: BaseMLBSignal) -> None:
        self._signals[signal.tag] = signal

    def get(self, tag: str) -> BaseMLBSignal:
        return self._signals[tag]

    def all(self) -> List[BaseMLBSignal]:
        return list(self._signals.values())

    def tags(self) -> List[str]:
        return list(self._signals.keys())

    def active_signals(self) -> List[BaseMLBSignal]:
        """Get only active (non-shadow, non-filter) signals."""
        return [s for s in self._signals.values()
                if not s.is_shadow and not s.is_negative_filter]

    def shadow_signals(self) -> List[BaseMLBSignal]:
        """Get shadow signals (accumulating data)."""
        return [s for s in self._signals.values() if s.is_shadow]

    def negative_filters(self) -> List[BaseMLBSignal]:
        """Get negative filter signals."""
        return [s for s in self._signals.values() if s.is_negative_filter]


def build_mlb_registry() -> MLBSignalRegistry:
    """Build registry with all MLB production signals."""
    from ml.signals.mlb.signals import (
        # Active signals (8)
        HighEdgeSignal,
        SwStrSurgeSignal,
        VelocityDropUnderSignal,
        OpponentKProneSignal,
        ShortRestUnderSignal,
        HighVarianceUnderSignal,
        BallparkKBoostSignal,
        UmpireKFriendlySignal,
        # Shadow signals (6)
        LineMovementOverSignal,
        WeatherColdUnderSignal,
        PlatoonAdvantageSignal,
        AcePitcherOverSignal,
        CatcherFramingOverSignal,
        PitchCountLimitUnderSignal,
        # Negative filters (4)
        BullpenGameFilter,
        ILReturnFilter,
        PitchCountCapFilter,
        InsufficientDataFilter,
    )

    registry = MLBSignalRegistry()

    # Active signals (8) — affect pick selection and ranking
    registry.register(HighEdgeSignal())
    registry.register(SwStrSurgeSignal())
    registry.register(VelocityDropUnderSignal())
    registry.register(OpponentKProneSignal())
    registry.register(ShortRestUnderSignal())
    registry.register(HighVarianceUnderSignal())
    registry.register(BallparkKBoostSignal())
    registry.register(UmpireKFriendlySignal())

    # Shadow signals (6) — accumulate data, don't affect picks yet
    # Need 30+ days of data before promotion to active (NBA lesson)
    registry.register(LineMovementOverSignal())
    registry.register(WeatherColdUnderSignal())
    registry.register(PlatoonAdvantageSignal())
    registry.register(AcePitcherOverSignal())
    registry.register(CatcherFramingOverSignal())
    registry.register(PitchCountLimitUnderSignal())

    # Negative filters (4) — block picks
    registry.register(BullpenGameFilter())
    registry.register(ILReturnFilter())
    registry.register(PitchCountCapFilter())
    registry.register(InsufficientDataFilter())

    return registry
