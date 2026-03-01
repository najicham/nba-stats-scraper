"""Line Rising Over Signal — OVER picks where the prop line went UP.

Backtest: 96.6% HR (29/30) across Jan+Feb. Feb-resilient at 100% (5/5).
When the market raises a player's line AND the model predicts OVER,
both market and model agree the player is trending up. This is the
strongest single predictor found in Session 374b analysis.

Replaces prop_line_drop_over (DISABLED — conceptually backward,
line drops are bearish for OVER at 39.1% HR in Feb).

Created: Session 374b
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class LineRisingOverSignal(BaseSignal):
    tag = "line_rising_over"
    description = "Line rose from previous game + OVER — 96.6% HR, market and model agree"

    MIN_LINE_RISE = 0.5  # Line must have risen by at least 0.5 points
    CONFIDENCE = 0.90

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        line_delta = prediction.get('prop_line_delta')
        if line_delta is None:
            return self._no_qualify()

        # Line must have RISEN (positive delta = current > previous)
        if line_delta < self.MIN_LINE_RISE:
            return self._no_qualify()

        # Higher rise = higher confidence (0.5=0.90, 2.0=0.93, 5.0+=1.0)
        confidence = min(1.0, self.CONFIDENCE + (line_delta - self.MIN_LINE_RISE) / 50.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'line_delta': round(line_delta, 1),
                'backtest_hr': 96.6,
            }
        )
