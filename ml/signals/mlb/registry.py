"""MLB Signal Registry — discovers and instantiates all MLB signal classes.

Ports the NBA ml/signals/registry.py pattern for MLB pitcher strikeouts.
18 active signals + 32 shadow/observation signals + 6 negative filters = 56 total.
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
    from ml.signals.mlb.signals import (  # noqa: E501
        # Active signals (19) — 8 original + 3 walk-forward (433) + 3 regressor (441) + 3 promoted (460) + 2 promoted (464)
        HighEdgeSignal,
        SwStrSurgeSignal,
        VelocityDropUnderSignal,
        OpponentKProneSignal,
        ShortRestUnderSignal,
        HighVarianceUnderSignal,
        BallparkKBoostSignal,
        UmpireKFriendlySignal,
        ProjectionAgreesOverSignal,
        KTrendingOverSignal,
        RecentKAboveLineSignal,
        RegressorProjectionAgreesSignal,
        HomePitcherSignal,
        LongRestSignal,
        # Shadow signals (6 original) + observation filters (2)
        LineMovementOverSignal,
        WeatherColdUnderSignal,
        PlatoonAdvantageSignal,
        AcePitcherOverSignal,
        CatcherFramingOverSignal,
        PitchCountLimitUnderSignal,
        BadOpponentObservationFilter,
        BadVenueObservationFilter,
        # Session 460 — shadow signals (research-backed)
        ColdWeatherKOverSignal,
        LineupKSpikeOverSignal,
        PitchEfficiencyDepthOverSignal,
        ShortStarterUnderSignal,
        HighCSWOverSignal,
        ElitePeripheralsOverSignal,
        GameTotalLowOverSignal,
        HeavyFavoriteOverSignal,
        BottomUpAgreesOverSignal,
        CatcherFramingPoorUnderSignal,
        # Session 460 round 2 — more research-backed signals
        DayGameShadowOverSignal,
        RematchFamiliarityUnderSignal,
        CumulativeArmStressUnderSignal,
        TaxedBullpenOverSignal,
        # Session 464 — new shadow signals (features already available)
        KRateReversionUnderSignal,
        KRateBounceOverSignal,
        UmpireCSWComboOverSignal,
        RestWorkloadStressUnderSignal,
        LowEraHighKComboOverSignal,
        PitcherOnRollOverSignal,
        # Session 464 round 2 — research-backed (FanGraphs + weather)
        ChaseRateOverSignal,
        ContactSpecialistUnderSignal,
        HumidityOverSignal,
        FreshOpponentOverSignal,
        # Session 465 — combo signals (4-season replay validated pairs)
        DayGameHighCSWComboOverSignal,
        DayGameElitePeripheralsComboOverSignal,
        HighCSWLowEraHighKComboOverSignal,
        # Session 465 — xFIP regression signal
        XfipEliteOverSignal,
        # Negative filters (6)
        BullpenGameFilter,
        ILReturnFilter,
        PitchCountCapFilter,
        InsufficientDataFilter,
        PitcherBlacklistFilter,
        WholeLineOverFilter,
    )

    registry = MLBSignalRegistry()

    # Active signals (17) — affect pick selection and ranking
    registry.register(HighEdgeSignal())
    registry.register(SwStrSurgeSignal())
    registry.register(VelocityDropUnderSignal())
    registry.register(OpponentKProneSignal())
    registry.register(ShortRestUnderSignal())
    registry.register(HighVarianceUnderSignal())
    registry.register(BallparkKBoostSignal())
    registry.register(UmpireKFriendlySignal())
    # Walk-forward validated OVER signals (Session 433)
    registry.register(ProjectionAgreesOverSignal())
    registry.register(KTrendingOverSignal())
    registry.register(RecentKAboveLineSignal())
    # Regressor-transition signals (Session 441)
    registry.register(RegressorProjectionAgreesSignal())
    registry.register(HomePitcherSignal())
    registry.register(LongRestSignal())
    # Session 460 promoted signals (cross-season validated)
    registry.register(HighCSWOverSignal())
    registry.register(ElitePeripheralsOverSignal())
    registry.register(PitchEfficiencyDepthOverSignal())
    # Session 464 promoted signals (4-season replay validated)
    registry.register(DayGameShadowOverSignal())
    registry.register(PitcherOnRollOverSignal())

    # Shadow signals (6) — accumulate data, don't affect picks yet
    registry.register(LineMovementOverSignal())
    registry.register(WeatherColdUnderSignal())
    registry.register(PlatoonAdvantageSignal())
    registry.register(AcePitcherOverSignal())
    registry.register(CatcherFramingOverSignal())
    registry.register(PitchCountLimitUnderSignal())
    # Observation filters (2) — demoted from active (Session 443, cross-season unstable)
    registry.register(BadOpponentObservationFilter())
    registry.register(BadVenueObservationFilter())

    # Session 460 — remaining shadow signals (accumulating data)
    registry.register(ColdWeatherKOverSignal())
    registry.register(LineupKSpikeOverSignal())
    registry.register(ShortStarterUnderSignal())
    registry.register(GameTotalLowOverSignal())
    registry.register(HeavyFavoriteOverSignal())
    registry.register(BottomUpAgreesOverSignal())
    registry.register(CatcherFramingPoorUnderSignal())
    # Session 460 round 2
    # DayGameShadowOverSignal — PROMOTED to active (Session 464)
    registry.register(RematchFamiliarityUnderSignal())
    registry.register(CumulativeArmStressUnderSignal())
    registry.register(TaxedBullpenOverSignal())
    # Session 464 — new shadow signals (features already available in replay SQL)
    registry.register(KRateReversionUnderSignal())
    registry.register(KRateBounceOverSignal())
    registry.register(UmpireCSWComboOverSignal())
    registry.register(RestWorkloadStressUnderSignal())
    registry.register(LowEraHighKComboOverSignal())
    # PitcherOnRollOverSignal — PROMOTED to active (Session 464)
    # Session 464 round 2 — research-backed shadow signals
    registry.register(ChaseRateOverSignal())
    registry.register(ContactSpecialistUnderSignal())
    registry.register(HumidityOverSignal())
    registry.register(FreshOpponentOverSignal())
    # Session 465 — combo signals (4-season replay validated pairs)
    registry.register(DayGameHighCSWComboOverSignal())
    registry.register(DayGameElitePeripheralsComboOverSignal())
    registry.register(HighCSWLowEraHighKComboOverSignal())
    # Session 465 — xFIP regression
    registry.register(XfipEliteOverSignal())

    # Negative filters (6) — block picks
    registry.register(BullpenGameFilter())
    registry.register(ILReturnFilter())
    registry.register(PitchCountCapFilter())
    registry.register(InsufficientDataFilter())
    registry.register(PitcherBlacklistFilter())
    # Session 443: Whole-number line filter (p<0.001, +9.6pp structural edge)
    registry.register(WholeLineOverFilter())

    return registry
