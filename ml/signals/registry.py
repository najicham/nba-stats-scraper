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
    from ml.signals.cold_snap import ColdSnapSignal
    from ml.signals.blowout_recovery import BlowoutRecoverySignal

    # Combo signals (Session 258)
    from ml.signals.combo_he_ms import HighEdgeMinutesSurgeComboSignal
    from ml.signals.combo_3way import ThreeWayComboSignal
    # ESO re-registered for anti-pattern detection in aggregator (Session 258)
    from ml.signals.edge_spread_optimal import EdgeSpreadOptimalSignal

    # Prototype signals - Batch 1 (Session 255)
    from ml.signals.hot_streak_3 import HotStreak3Signal
    from ml.signals.cold_continuation_2 import ColdContinuation2Signal
    from ml.signals.b2b_fatigue_under import B2BFatigueUnderSignal
    from ml.signals.rest_advantage_2d import RestAdvantage2DSignal

    # Prototype signals - Batch 2 (Session 255)
    from ml.signals.hot_streak_2 import HotStreak2Signal
    from ml.signals.points_surge_3 import PointsSurge3Signal
    from ml.signals.home_dog import HomeDogSignal
    # PropValueGapExtremeSignal REMOVED — 12.5% HR, -76.1% ROI (Session 255)
    from ml.signals.minutes_surge_5 import MinutesSurge5Signal
    from ml.signals.three_pt_volume_surge import ThreePtVolumeSurgeSignal
    from ml.signals.model_consensus_v9_v12 import ModelConsensusV9V12Signal
    from ml.signals.fg_cold_continuation import FGColdContinuationSignal
    # TripleStackSignal REMOVED — meta-signal with broken logic (Session 256)
    from ml.signals.scoring_acceleration import ScoringAccelerationSignal

    # Market-pattern UNDER signals (Session 274)
    from ml.signals.bench_under import BenchUnderSignal
    from ml.signals.high_usage_under import HighUsageUnderSignal
    from ml.signals.volatile_under import VolatileUnderSignal
    from ml.signals.high_ft_under import HighFTUnderSignal
    from ml.signals.self_creator_under import SelfCreatorUnderSignal

    registry = SignalRegistry()
    registry.register(ModelHealthSignal())
    registry.register(HighEdgeSignal())
    registry.register(DualAgreeSignal())
    registry.register(ThreePtBounceSignal())
    registry.register(MinutesSurgeSignal())
    registry.register(PaceMismatchSignal())
    registry.register(ColdSnapSignal())
    registry.register(BlowoutRecoverySignal())

    # Combo signals (Session 258)
    registry.register(HighEdgeMinutesSurgeComboSignal())
    registry.register(ThreeWayComboSignal())
    # ESO: 47.4% standalone, but needed for anti-pattern detection in aggregator
    registry.register(EdgeSpreadOptimalSignal())

    # Prototype signals - Batch 1
    registry.register(HotStreak3Signal())
    registry.register(ColdContinuation2Signal())
    registry.register(B2BFatigueUnderSignal())
    registry.register(RestAdvantage2DSignal())

    # Prototype signals - Batch 2
    registry.register(HotStreak2Signal())
    registry.register(PointsSurge3Signal())
    registry.register(HomeDogSignal())
    # PropValueGapExtremeSignal removed (12.5% HR)
    registry.register(MinutesSurge5Signal())
    registry.register(ThreePtVolumeSurgeSignal())
    registry.register(ModelConsensusV9V12Signal())
    registry.register(FGColdContinuationSignal())
    # TripleStackSignal removed (meta-signal, broken logic)
    registry.register(ScoringAccelerationSignal())

    # Market-pattern UNDER signals (Session 274)
    registry.register(BenchUnderSignal())
    registry.register(HighUsageUnderSignal())
    registry.register(VolatileUnderSignal())
    registry.register(HighFTUnderSignal())
    registry.register(SelfCreatorUnderSignal())

    return registry
