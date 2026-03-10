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
    from ml.signals.b2b_boost_over import B2BBoostOverSignal
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

    # PropLineDropOverSignal REMOVED — disabled Session 374b, import dead code (cleaned Session 425)

    # Book disagreement signal (Session 303)
    from ml.signals.book_disagreement import BookDisagreementSignal

    # FT rate bench over signal (Session 336)
    from ml.signals.ft_rate_bench_over import FTRateBenchOverSignal

    # Session 371 signals
    from ml.signals.home_under import HomeUnderSignal
    from ml.signals.scoring_cold_streak_over import ScoringColdStreakOverSignal

    # Session 372 signals
    from ml.signals.extended_rest_under import ExtendedRestUnderSignal
    from ml.signals.starter_under import StarterUnderSignal

    # Session 373 signals
    from ml.signals.high_scoring_environment_over import HighScoringEnvironmentOverSignal

    # Session 374 signals
    from ml.signals.fast_pace_over import FastPaceOverSignal
    from ml.signals.volatile_scoring_over import VolatileScoringOverSignal
    from ml.signals.low_line_over import LowLineOverSignal

    # Session 374b signals
    from ml.signals.line_rising_over import LineRisingOverSignal

    # Session 380 signals
    from ml.signals.self_creation_over import SelfCreationOverSignal
    from ml.signals.sharp_line_move_over import SharpLineMoveOverSignal

    # Session 382C signals
    from ml.signals.sharp_line_drop_under import SharpLineDropUnderSignal

    # Session 397 signals
    from ml.signals.q4_scorer_over import Q4ScorerOverSignal

    # Session 398 signals
    from ml.signals.denver_visitor_over import DenverVisitorOverSignal
    from ml.signals.day_of_week_over import DayOfWeekOverSignal

    # Session 399 signals
    from ml.signals.sharp_book_lean import SharpBookLeanOverSignal, SharpBookLeanUnderSignal

    # Session 401 signals — new data source signals
    from ml.signals.projection_consensus import (
        ProjectionConsensusOverSignal,
        ProjectionConsensusUnderSignal,
        ProjectionDisagreementFilter,
    )
    from ml.signals.predicted_pace import PredictedPaceOverSignal
    from ml.signals.dvp_mismatch import DvpFavorableOverSignal
    from ml.signals.closing_line_value import (
        PositiveCLVOverSignal,
        PositiveCLVUnderSignal,
        NegativeCLVFilter,
    )

    # Session 404 signals — VSiN sharp money + RotoWire minutes projection
    from ml.signals.sharp_money import (
        SharpMoneyOverSignal,
        SharpMoneyUnderSignal,
        PublicFadeFilter,
    )
    from ml.signals.minutes_projection import MinutesSurgeOverSignal

    # Session 410: Derived feature signals (shadow mode — from experiment dead ends)
    from ml.signals.hot_form_over import HotFormOverSignal
    from ml.signals.consistent_scorer_over import ConsistentScorerOverSignal
    from ml.signals.over_trend_over import OverTrendOverSignal

    # Session 411: Feature store signals (shadow mode — from feature distributions)
    from ml.signals.usage_surge_over import UsageSurgeOverSignal
    from ml.signals.scoring_momentum_over import ScoringMomentumOverSignal
    from ml.signals.career_matchup_over import CareerMatchupOverSignal
    from ml.signals.minutes_load_over import MinutesLoadOverSignal
    from ml.signals.blowout_risk_under import BlowoutRiskUnderSignal

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
    # B2BFatigueUnderSignal DISABLED (Session 373) — boosts a losing pattern (39.5% Feb HR, N=410).
    # Fires only 3 times in best bets total (2-1). Signal is philosophically backwards:
    # encourages B2B UNDER but B2B UNDER collapsed from 66.7% (Dec) to 39.5% (Feb).
    # B2BBoostOverSignal (Session 396) — B2B is BULLISH for OVER (64.3% raw, 69.2% toxic window)
    registry.register(B2BBoostOverSignal())
    # RestAdvantage2DSignal DISABLED (Session 396) — 25% 30d HR (N=4), collapsed from
    # 80.6% Jan to 57.1% Feb. Post-ASB fewer rest differentials. Re-enable next October.
    # registry.register(RestAdvantage2DSignal())

    # Prototype signals - Batch 2 (8 removed Sessions 275+296, see import comments)

    # Market-pattern UNDER signals (Session 274)
    registry.register(BenchUnderSignal())
    # HighUsageUnderSignal, VolatileUnderSignal, HighFTUnderSignal, SelfCreatorUnderSignal removed (Session 326)

    # PropLineDropOverSignal DISABLED (Session 374b) — conceptually backward.
    # Line dropping is BEARISH for OVER (39.1% HR Feb N=23). Signal inflates SC
    # on losing OVER picks. OVER + line UP = 96.6% HR — replaced by LineRisingOverSignal.

    # Book disagreement signal (Session 303)
    registry.register(BookDisagreementSignal())

    # FT rate bench over signal (Session 336)
    registry.register(FTRateBenchOverSignal())

    # Session 371 signals
    registry.register(HomeUnderSignal())
    registry.register(ScoringColdStreakOverSignal())

    # Session 372 signals
    registry.register(ExtendedRestUnderSignal())
    registry.register(StarterUnderSignal())

    # Session 373 signals
    registry.register(HighScoringEnvironmentOverSignal())

    # Session 374 signals
    registry.register(FastPaceOverSignal())
    # VolatileScoringOverSignal RE-ENABLED (Session 411) — 77.8% HR (7-2) post-toxic.
    # Was disabled Session 391 at 50% (4-4) during toxic window (Jan 30 - Feb 25).
    # Post-ASB recovery confirms original 81.5% backtest signal is real.
    registry.register(VolatileScoringOverSignal())
    registry.register(LowLineOverSignal())

    # Session 374b signals
    registry.register(LineRisingOverSignal())

    # Session 380 signals
    registry.register(SelfCreationOverSignal())
    registry.register(SharpLineMoveOverSignal())

    # Session 382C signals
    registry.register(SharpLineDropUnderSignal())

    # Session 397 signals
    registry.register(Q4ScorerOverSignal())

    # Session 398 signals
    registry.register(DenverVisitorOverSignal())
    registry.register(DayOfWeekOverSignal())

    # Session 399 signals
    registry.register(SharpBookLeanOverSignal())
    registry.register(SharpBookLeanUnderSignal())

    # Session 401 signals — new data source signals (shadow mode until validated)
    # These signals depend on new scrapers being deployed and BQ tables populated.
    # They will gracefully return _no_qualify() when data is not yet available.
    registry.register(ProjectionConsensusOverSignal())
    registry.register(ProjectionConsensusUnderSignal())
    # ProjectionDisagreementFilter — register but NOT used as negative filter yet.
    # Needs BQ validation on 30+ picks before adding to aggregator.
    registry.register(ProjectionDisagreementFilter())
    registry.register(PredictedPaceOverSignal())
    registry.register(DvpFavorableOverSignal())
    registry.register(PositiveCLVOverSignal())
    registry.register(PositiveCLVUnderSignal())
    # NegativeCLVFilter — register but NOT used as negative filter yet.
    registry.register(NegativeCLVFilter())

    # Session 404: VSiN sharp money signals (shadow mode — not in aggregator yet)
    registry.register(SharpMoneyOverSignal())
    registry.register(SharpMoneyUnderSignal())
    # PublicFadeFilter — register but NOT used as negative filter yet.
    registry.register(PublicFadeFilter())

    # Session 404: RotoWire minutes projection signal (shadow mode)
    registry.register(MinutesSurgeOverSignal())

    # Session 410: Derived feature signals (shadow mode — accumulating data)
    # Failed as model features but conceptually perfect as contextual signals.
    registry.register(HotFormOverSignal())
    registry.register(ConsistentScorerOverSignal())
    registry.register(OverTrendOverSignal())

    # Session 411: Feature store signals (shadow mode — validating fire rates)
    # 4 OVER + 1 UNDER (fills UNDER gap). All use raw feature values from book_stats CTE.
    registry.register(UsageSurgeOverSignal())
    registry.register(ScoringMomentumOverSignal())
    registry.register(CareerMatchupOverSignal())
    registry.register(MinutesLoadOverSignal())
    registry.register(BlowoutRiskUnderSignal())

    # Session 413/417: Mean reversion UNDER — promoted to active (rescue + UNDER weight)
    # 77.8% HR (N=212), stable all months. Hot streak regression.
    from ml.signals.mean_reversion_under import MeanReversionUnderSignal
    registry.register(MeanReversionUnderSignal())

    # Session 414: Day-of-week UNDER (shadow mode — complements OVER signal)
    # Monday 60.3% (N=277), Thursday 59.4% (N=419).
    from ml.signals.day_of_week_under import DayOfWeekUnderSignal
    registry.register(DayOfWeekUnderSignal())

    # Session 418: Player profile signals (shadow mode — validating)
    # bounce_back_over: Bad miss (<70% of line) + AWAY = 56.2% raw, 60%+ with model (N=379)
    from ml.signals.bounce_back_over import BounceBackOverSignal
    registry.register(BounceBackOverSignal())
    # OverStreakReversionUnderSignal REMOVED Session 462: 51.6% HR 5-season cross-validated — harmful

    # Session 422c: New UNDER signals (shadow mode — filling UNDER signal vacuum)
    from ml.signals.volatile_starter_under import VolatileStarterUnderSignal
    from ml.signals.downtrend_under import DowntrendUnderSignal
    from ml.signals.star_favorite_under import StarFavoriteUnderSignal
    registry.register(VolatileStarterUnderSignal())
    registry.register(DowntrendUnderSignal())
    registry.register(StarFavoriteUnderSignal())

    # Session 423: Starter away overtrend UNDER (shadow mode)
    # Session 462: 48.2% HR 5-season — harmful, demoted to shadow. Keep registered for tracking.
    from ml.signals.starter_away_overtrend_under import StarterAwayOvertrendUnderSignal
    registry.register(StarterAwayOvertrendUnderSignal())

    # Session 462: BB pipeline simulator validated signals (shadow mode — accumulating BB data)
    # hot_3pt_under: 62.5% HR (N=670), 5-season cross-validated
    # cold_3pt_over: 60.2% HR (N=123), 5-season cross-validated
    # line_drifted_down_under: 59.8% HR (N=336), 5-season cross-validated
    from ml.signals.hot_3pt_under import Hot3ptUnderSignal
    from ml.signals.cold_3pt_over import Cold3ptOverSignal
    from ml.signals.line_drifted_down_under import LineDriftedDownUnderSignal
    registry.register(Hot3ptUnderSignal())
    registry.register(Cold3ptOverSignal())
    registry.register(LineDriftedDownUnderSignal())

    # Session 463: P0 simulator experiments (shadow mode — accumulating BB data)
    # ft_anomaly_under: 63.3% HR (N=278), 5-season cross-validated. FTA CV >= 0.5 + FTA >= 5/game
    # slow_pace_under: 56.6% HR (N=777), 5-season cross-validated. Opponent pace <= 99
    from ml.signals.ft_anomaly_under import FtAnomalyUnderSignal
    from ml.signals.slow_pace_under import SlowPaceUnderSignal
    registry.register(FtAnomalyUnderSignal())
    registry.register(SlowPaceUnderSignal())

    # Session 463: P1 simulator experiment — star overpricing
    # star_line_under: 57.6% HR (N=1,018), 5-season cross-validated. Line >= 25, edge 3-7
    from ml.signals.star_line_under import StarLineUnderSignal
    registry.register(StarLineUnderSignal())

    return registry
