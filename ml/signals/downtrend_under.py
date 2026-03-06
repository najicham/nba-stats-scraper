"""Downtrend Under Signal — UNDER on players in a slight scoring decline.

When a player's scoring trend is slightly negative (slope -1.5 to -0.5),
UNDER predictions are more reliable. The model catches the trend before
the line adjusts. Too steep a decline (< -1.5) means the line may have
already adjusted.

Backtest: 63.9% HR (N=1,654), +5.2pp over UNDER baseline (58.7%).
Highest-volume profitable UNDER segment found in research.

Data sources:
- prediction['trend_slope']: 10-game scoring trend from feature store (f44)

Created: Session 422c (shadow mode)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class DowntrendUnderSignal(BaseSignal):
    tag = "downtrend_under"
    description = "Slight downtrend UNDER — trend_slope -1.5 to -0.5"

    MAX_SLOPE = -0.5
    MIN_SLOPE = -1.5
    MIN_LINE = 12.0  # Filter bench noise
    CONFIDENCE = 0.78

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE:
            return self._no_qualify()

        slope = prediction.get('trend_slope')
        if slope is None:
            return self._no_qualify()

        if slope < self.MIN_SLOPE or slope > self.MAX_SLOPE:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'trend_slope': round(slope, 2),
                'line_value': round(line, 1),
                'backtest_hr': 63.9,
            }
        )
