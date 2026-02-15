"""Signal registry — discovers and instantiates all signal classes."""

from typing import Dict, List
from ml.signals.base_signal import BaseSignal


class SignalRegistry:
    """Registry that holds all available signal evaluators."""

    def __init__(self):
        self._signals: Dict[str, BaseSignal] = {}

    def register(self, signal: BaseSignal) -> None:
        self._signals[signal.tag] = signal

    def get(self, tag: str) -> BaseSignal:
        return self._signals[tag]

    def all(self) -> List[BaseSignal]:
        return list(self._signals.values())

    def tags(self) -> List[str]:
        return list(self._signals.keys())


def build_default_registry() -> SignalRegistry:
    """Build registry with all production signals."""
    from ml.signals.high_edge import HighEdgeSignal
    from ml.signals.dual_agree import DualAgreeSignal
    from ml.signals.three_pt_bounce import ThreePtBounceSignal
    from ml.signals.minutes_surge import MinutesSurgeSignal
    from ml.signals.pace_mismatch import PaceMismatchSignal
    from ml.signals.model_health import ModelHealthSignal

    registry = SignalRegistry()
    registry.register(ModelHealthSignal())
    registry.register(HighEdgeSignal())
    registry.register(DualAgreeSignal())
    registry.register(ThreePtBounceSignal())
    registry.register(MinutesSurgeSignal())
    registry.register(PaceMismatchSignal())
    return registry
