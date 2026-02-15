"""Pluggable decision strategies for the replay engine.

Each strategy implements `decide(date, model_metrics)` and returns
which model to use, what action to take, and why.

Created: 2026-02-15 (Session 262)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional


@dataclass
class ModelMetrics:
    """Rolling metrics for a single model on a single date."""
    model_id: str
    rolling_hr_7d: Optional[float]
    rolling_hr_14d: Optional[float]
    rolling_hr_30d: Optional[float]
    rolling_n_7d: int
    rolling_n_14d: int
    rolling_n_30d: int
    daily_picks: int
    daily_wins: int
    daily_hr: Optional[float]


@dataclass
class Decision:
    """Output of a strategy's decide() call."""
    selected_model: Optional[str]  # None = block all picks
    action: str  # NO_CHANGE, SWITCHED, BLOCKED, RECOVERED
    reason: str
    state: str  # HEALTHY, WATCH, DEGRADING, BLOCKED


class DecisionStrategy(ABC):
    """Base class for model selection strategies."""

    @abstractmethod
    def decide(self, current_date: date,
               model_metrics: Dict[str, ModelMetrics],
               current_model: Optional[str] = None) -> Decision:
        """Decide which model to use today.

        Args:
            current_date: The date being evaluated.
            model_metrics: Dict of model_id -> ModelMetrics for this date.
            current_model: Currently active model (from previous day's decision).

        Returns:
            Decision with selected model, action, reason, and state.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...


class ThresholdStrategy(DecisionStrategy):
    """Switch/block based on rolling HR thresholds with consecutive-day gates.

    Logic:
    - WATCH: 7d HR < watch_threshold for 2+ days
    - DEGRADING: 7d HR < alert_threshold for 3+ days → try switching to challenger
    - BLOCKED: 7d HR < block_threshold → no picks
    - Recovery: 7d HR > watch_threshold for 2+ days → restore champion
    """

    def __init__(self, champion_id: str,
                 challenger_ids: Optional[List[str]] = None,
                 watch_threshold: float = 58.0,
                 alert_threshold: float = 55.0,
                 block_threshold: float = 52.4,
                 min_sample: int = 20,
                 challenger_min_hr: float = 56.0):
        self.champion_id = champion_id
        self.challenger_ids = challenger_ids or []
        self.watch_threshold = watch_threshold
        self.alert_threshold = alert_threshold
        self.block_threshold = block_threshold
        self.min_sample = min_sample
        self.challenger_min_hr = challenger_min_hr
        self._consecutive_below_watch = 0
        self._consecutive_below_alert = 0
        self._consecutive_above_watch = 0

    @property
    def name(self) -> str:
        return (f"Threshold(watch={self.watch_threshold}%, "
                f"alert={self.alert_threshold}%, block={self.block_threshold}%)")

    def decide(self, current_date: date,
               model_metrics: Dict[str, ModelMetrics],
               current_model: Optional[str] = None) -> Decision:
        if current_model is None:
            current_model = self.champion_id

        champ_metrics = model_metrics.get(self.champion_id)
        current_metrics = model_metrics.get(current_model)

        # If no data for champion, continue with current
        if not champ_metrics or champ_metrics.rolling_n_7d < self.min_sample:
            return Decision(current_model, 'NO_CHANGE',
                            'Insufficient champion data', 'INSUFFICIENT_DATA')

        hr = champ_metrics.rolling_hr_7d
        if hr is None:
            return Decision(current_model, 'NO_CHANGE',
                            'No HR data', 'INSUFFICIENT_DATA')

        # Track consecutive days
        if hr < self.watch_threshold:
            self._consecutive_below_watch += 1
            self._consecutive_above_watch = 0
        else:
            self._consecutive_below_watch = 0
            self._consecutive_above_watch += 1

        if hr < self.alert_threshold:
            self._consecutive_below_alert += 1
        else:
            self._consecutive_below_alert = 0

        # BLOCKED: below breakeven
        if hr < self.block_threshold:
            # Try to find a challenger above breakeven
            best_challenger = self._find_best_challenger(model_metrics)
            if best_challenger:
                return Decision(
                    best_challenger.model_id, 'SWITCHED',
                    f'Champion {hr:.1f}% HR blocked. Switched to {best_challenger.model_id} '
                    f'({best_challenger.rolling_hr_7d:.1f}% HR, N={best_challenger.rolling_n_7d})',
                    'BLOCKED')
            return Decision(None, 'BLOCKED',
                            f'Champion {hr:.1f}% HR below breakeven, no viable challenger',
                            'BLOCKED')

        # DEGRADING: below alert for 3+ days
        if self._consecutive_below_alert >= 3:
            best_challenger = self._find_best_challenger(model_metrics)
            if best_challenger:
                return Decision(
                    best_challenger.model_id, 'SWITCHED',
                    f'Champion degrading ({hr:.1f}% HR, {self._consecutive_below_alert}d). '
                    f'Switched to {best_challenger.model_id} '
                    f'({best_challenger.rolling_hr_7d:.1f}% HR)',
                    'DEGRADING')
            return Decision(current_model, 'NO_CHANGE',
                            f'Champion degrading ({hr:.1f}% HR) but no viable challenger',
                            'DEGRADING')

        # WATCH: below watch for 2+ days
        if self._consecutive_below_watch >= 2:
            return Decision(current_model, 'NO_CHANGE',
                            f'Champion at {hr:.1f}% HR for '
                            f'{self._consecutive_below_watch}d — watching',
                            'WATCH')

        # RECOVERY: if we're on a challenger and champion recovered
        if current_model != self.champion_id and self._consecutive_above_watch >= 2:
            return Decision(self.champion_id, 'SWITCHED',
                            f'Champion recovered to {hr:.1f}% HR — restoring',
                            'HEALTHY')

        return Decision(current_model, 'NO_CHANGE',
                        f'Champion {hr:.1f}% HR — healthy', 'HEALTHY')

    def _find_best_challenger(self, metrics: Dict[str, ModelMetrics]
                              ) -> Optional[ModelMetrics]:
        """Find the best challenger model that meets minimum requirements."""
        candidates = []
        for cid in self.challenger_ids:
            m = metrics.get(cid)
            if not m or m.rolling_n_7d < self.min_sample:
                continue
            if m.rolling_hr_7d is not None and m.rolling_hr_7d >= self.challenger_min_hr:
                candidates.append(m)

        if not candidates:
            return None
        return max(candidates, key=lambda m: m.rolling_hr_7d)


class BestOfNStrategy(DecisionStrategy):
    """Always use the model with the highest rolling HR.

    Pure "best performer wins" — switches daily. Upper bound on
    what perfect model selection could achieve.
    """

    def __init__(self, min_sample: int = 20):
        self.min_sample = min_sample

    @property
    def name(self) -> str:
        return f"BestOfN(min_sample={self.min_sample})"

    def decide(self, current_date: date,
               model_metrics: Dict[str, ModelMetrics],
               current_model: Optional[str] = None) -> Decision:
        eligible = [
            m for m in model_metrics.values()
            if m.rolling_n_7d >= self.min_sample
            and m.rolling_hr_7d is not None
        ]

        if not eligible:
            return Decision(current_model, 'NO_CHANGE',
                            'No models with sufficient sample', 'INSUFFICIENT_DATA')

        best = max(eligible, key=lambda m: m.rolling_hr_7d)

        if best.model_id == current_model:
            return Decision(best.model_id, 'NO_CHANGE',
                            f'Best model: {best.model_id} ({best.rolling_hr_7d:.1f}% HR)',
                            'HEALTHY')
        else:
            return Decision(
                best.model_id, 'SWITCHED',
                f'Switched to {best.model_id} ({best.rolling_hr_7d:.1f}% HR, '
                f'N={best.rolling_n_7d})',
                'HEALTHY')


class ConservativeStrategy(DecisionStrategy):
    """Only switch after N consecutive days below threshold.

    Reduces false positives from daily variance by requiring sustained
    underperformance before acting.
    """

    def __init__(self, champion_id: str,
                 consecutive_days: int = 5,
                 threshold: float = 55.0,
                 block_threshold: float = 52.4,
                 min_sample: int = 20):
        self.champion_id = champion_id
        self.consecutive_days = consecutive_days
        self.threshold = threshold
        self.block_threshold = block_threshold
        self.min_sample = min_sample
        self._consecutive_below = 0

    @property
    def name(self) -> str:
        return (f"Conservative(days={self.consecutive_days}, "
                f"threshold={self.threshold}%)")

    def decide(self, current_date: date,
               model_metrics: Dict[str, ModelMetrics],
               current_model: Optional[str] = None) -> Decision:
        if current_model is None:
            current_model = self.champion_id

        champ = model_metrics.get(self.champion_id)
        if not champ or champ.rolling_n_7d < self.min_sample:
            return Decision(current_model, 'NO_CHANGE',
                            'Insufficient data', 'INSUFFICIENT_DATA')

        hr = champ.rolling_hr_7d
        if hr is None:
            return Decision(current_model, 'NO_CHANGE', 'No HR', 'INSUFFICIENT_DATA')

        if hr < self.threshold:
            self._consecutive_below += 1
        else:
            self._consecutive_below = 0

        if hr < self.block_threshold and self._consecutive_below >= self.consecutive_days:
            return Decision(None, 'BLOCKED',
                            f'Champion {hr:.1f}% for {self._consecutive_below}d',
                            'BLOCKED')

        if self._consecutive_below >= self.consecutive_days:
            return Decision(current_model, 'NO_CHANGE',
                            f'Champion {hr:.1f}% for {self._consecutive_below}d — degrading',
                            'DEGRADING')

        return Decision(current_model, 'NO_CHANGE',
                        f'Champion {hr:.1f}% HR', 'HEALTHY')


class OracleStrategy(DecisionStrategy):
    """Perfect hindsight: always pick the model with best daily HR.

    Upper bound on achievable P&L with perfect foresight.
    Cannot be used in real-time — only for calibration.
    """

    @property
    def name(self) -> str:
        return "Oracle(perfect_hindsight)"

    def decide(self, current_date: date,
               model_metrics: Dict[str, ModelMetrics],
               current_model: Optional[str] = None) -> Decision:
        eligible = [
            m for m in model_metrics.values()
            if m.daily_picks > 0 and m.daily_hr is not None
        ]

        if not eligible:
            return Decision(current_model, 'NO_CHANGE',
                            'No daily data', 'INSUFFICIENT_DATA')

        best = max(eligible, key=lambda m: m.daily_hr)
        return Decision(best.model_id, 'SWITCHED',
                        f'Oracle: {best.model_id} ({best.daily_hr:.1f}% daily HR)',
                        'HEALTHY')


STRATEGIES = {
    'threshold': ThresholdStrategy,
    'best_of_n': BestOfNStrategy,
    'conservative': ConservativeStrategy,
    'oracle': OracleStrategy,
}
