"""Fast Pace Over Signal — OVER picks against fast-paced opponents.

Backtest: 81.5% HR (N=27) at best-bets level.
When opponent_pace >= 102, more possessions create more scoring opportunities.
Clear mechanism: pace drives volume, volume drives OVER.

Created: Session 374
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class FastPaceOverSignal(BaseSignal):
    tag = "fast_pace_over"
    description = "Fast opponent pace (102+) OVER — 81.5% HR, more possessions = more scoring"

    MIN_OPPONENT_PACE = 102.0
    CONFIDENCE = 0.80

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        pace = prediction.get('opponent_pace') or 0
        if pace < self.MIN_OPPONENT_PACE:
            return self._no_qualify()

        # Higher pace = higher confidence (102=0.80, 107=0.90, 112+=1.0)
        confidence = min(1.0, self.CONFIDENCE + (pace - self.MIN_OPPONENT_PACE) / 50.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'opponent_pace': round(pace, 1),
                'backtest_hr': 81.5,
            }
        )
