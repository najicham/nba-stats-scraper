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
    # DualAgreeSignal REMOVED — 44.8% HR, below breakeven (Session 296)
    from ml.signals.three_pt_bounce import ThreePtBounceSignal
    # MinutesSurgeSignal REMOVED — 53.7% AVG HR, W4 decay (Session 318)
    # PaceMismatchSignal REMOVED — N=0 all windows, never fires (Session 275)
    from ml.signals.model_health import ModelHealthSignal
    # ColdSnapSignal REMOVED — N=0 in all backtest windows (Session 318)
    from ml.signals.blowout_recovery import BlowoutRecoverySignal

    # Combo signals (Session 258)
    from ml.signals.combo_he_ms import HighEdgeMinutesSurgeComboSignal
    from ml.signals.combo_3way import ThreeWayComboSignal
    # ESO re-registered for anti-pattern detection in aggregator (Session 258)
    from ml.signals.edge_spread_optimal import EdgeSpreadOptimalSignal

    # Prototype signals - Batch 1 (Session 255)
    # HotStreak3Signal REMOVED — 47.5% AVG HR, below breakeven (Session 275)
    # ColdContinuation2Signal REMOVED — 45.8% AVG HR, never above breakeven (Session 275)
    from ml.signals.b2b_fatigue_under import B2BFatigueUnderSignal
    from ml.signals.rest_advantage_2d import RestAdvantage2DSignal

    # Prototype signals - Batch 2 (Session 255)
    # HotStreak2Signal REMOVED — 45.8% AVG HR, N=416 false qualifier (Session 275)
    # PointsSurge3Signal REMOVED — N=0 all windows, never fires (Session 275)
    # HomeDogSignal REMOVED — N=0 all windows, never fires (Session 275)
    # PropValueGapExtremeSignal REMOVED — 12.5% HR, -76.1% ROI (Session 255)
    # MinutesSurge5Signal REMOVED — N=0 all windows, never fires (Session 275)
    # ThreePtVolumeSurgeSignal REMOVED — N=0 all windows, never fires (Session 275)
    # ModelConsensusV9V12Signal REMOVED — 45.5% HR, below breakeven (Session 296)
    # FGColdContinuationSignal REMOVED — 49.6% AVG HR, catastrophic decay (Session 275)
    # TripleStackSignal REMOVED — meta-signal with broken logic (Session 256)
    # ScoringAccelerationSignal REMOVED — N=0 all windows, never fires (Session 275)

    # Market-pattern UNDER signals (Session 274)
    from ml.signals.bench_under import BenchUnderSignal
    # HighUsageUnderSignal REMOVED — 40.0% HR on best bets (Session 326)
    # VolatileUnderSignal REMOVED — 33.3% HR on best bets (Session 326)
    # HighFTUnderSignal REMOVED — 33.3% HR on best bets (Session 326)
    # SelfCreatorUnderSignal REMOVED — 36.4% HR on best bets (Session 326)

    # Prop line delta signal (Session 294)
    from ml.signals.prop_line_drop_over import PropLineDropOverSignal

    # Book disagreement signal (Session 303)
    from ml.signals.book_disagreement import BookDisagreementSignal

    # FT rate bench over signal (Session 336)
    from ml.signals.ft_rate_bench_over import FTRateBenchOverSignal

    # Session 371 signals
    from ml.signals.home_under import HomeUnderSignal
    from ml.signals.scoring_cold_streak_over import ScoringColdStreakOverSignal

    registry = SignalRegistry()
    registry.register(ModelHealthSignal())
    registry.register(HighEdgeSignal())
    # DualAgreeSignal removed (Session 296)
    registry.register(ThreePtBounceSignal())
    # MinutesSurgeSignal removed (Session 318)
    # PaceMismatchSignal removed (Session 275)
    # ColdSnapSignal removed (Session 318)
    # BlowoutRecoverySignal DISABLED (Session 349) — 50% HR, harmful signal

    # Combo signals (Session 258)
    registry.register(HighEdgeMinutesSurgeComboSignal())
    registry.register(ThreeWayComboSignal())
    # ESO: 47.4% standalone, but needed for anti-pattern detection in aggregator
    registry.register(EdgeSpreadOptimalSignal())

    # Prototype signals - Batch 1
    # HotStreak3Signal, ColdContinuation2Signal removed (Session 275)
    registry.register(B2BFatigueUnderSignal())
    registry.register(RestAdvantage2DSignal())

    # Prototype signals - Batch 2 (8 removed Sessions 275+296, see import comments)

    # Market-pattern UNDER signals (Session 274)
    registry.register(BenchUnderSignal())
    # HighUsageUnderSignal, VolatileUnderSignal, HighFTUnderSignal, SelfCreatorUnderSignal removed (Session 326)

    # Prop line delta signal (Session 294)
    registry.register(PropLineDropOverSignal())

    # Book disagreement signal (Session 303)
    registry.register(BookDisagreementSignal())

    # FT rate bench over signal (Session 336)
    registry.register(FTRateBenchOverSignal())

    # Session 371 signals
    registry.register(HomeUnderSignal())
    registry.register(ScoringColdStreakOverSignal())

    return registry
