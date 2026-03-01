"""Low Line Over Signal — OVER picks on low prop lines.

Backtest: 78.1% HR (N=32) at best-bets level.
When line < 12 and model predicts OVER, role players and bench players
on low lines have high OVER conversion. Small absolute gaps are easier
to clear, and low lines are more often set conservatively by books.

Created: Session 374
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class LowLineOverSignal(BaseSignal):
    tag = "low_line_over"
    description = "Low prop line (<12) OVER — 78.1% HR, conservative lines easier to clear"

    MAX_LINE = 12.0
    CONFIDENCE = 0.75

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line <= 0 or line >= self.MAX_LINE:
            return self._no_qualify()

        # Lower line = higher confidence (11=0.75, 8=0.81, 5=0.87)
        confidence = min(1.0, self.CONFIDENCE + (self.MAX_LINE - line) / 50.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'line_value': round(line, 1),
                'backtest_hr': 78.1,
            }
        )
