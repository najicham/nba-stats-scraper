"""Volatile Scoring Over Signal — OVER picks for high-variance scorers.

Backtest: 81.5% HR (N=27) at best-bets level. Raw: 61.9% (N=845).
When scoring CV >= 50% (std/line > 0.50), upside variance favors OVER.
High-variance scorers have explosive game potential that drives OVER.

Created: Session 374
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class VolatileScoringOverSignal(BaseSignal):
    tag = "volatile_scoring_over"
    description = "High scoring variance (CV 50%+) OVER — 81.5% HR, upside variance favors OVER"

    MIN_CV = 0.50  # std / line_value
    MIN_LINE = 5.0  # Avoid noise on very low lines
    CONFIDENCE = 0.80

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE:
            return self._no_qualify()

        std = prediction.get('points_std_last_10') or 0
        if std <= 0:
            return self._no_qualify()

        cv = std / line
        if cv < self.MIN_CV:
            return self._no_qualify()

        # Higher CV = higher confidence (0.50=0.80, 0.70=0.84, 1.0+=0.90)
        confidence = min(1.0, self.CONFIDENCE + (cv - self.MIN_CV) / 5.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'scoring_cv': round(cv, 3),
                'points_std': round(std, 1),
                'line_value': round(line, 1),
                'backtest_hr': 81.5,
            }
        )
