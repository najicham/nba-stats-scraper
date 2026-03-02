"""Fast Pace Over Signal — OVER picks against fast-paced opponents.

Backtest: 81.5% HR (N=27) at best-bets level.
When opponent has fast pace, more possessions create more scoring opportunities.
Clear mechanism: pace drives volume, volume drives OVER.

Feature 18 (opponent_pace) is normalized 0-1 in the feature store.
P75=0.49, P90=0.76. Threshold 0.75 ≈ raw pace 102+ (top ~25% of teams).

Created: Session 374
Fixed: Session 387 — was checking normalized 0-1 against raw 102, could never fire.
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class FastPaceOverSignal(BaseSignal):
    tag = "fast_pace_over"
    description = "Fast opponent pace (normalized 0.75+) OVER — 81.5% HR, more possessions = more scoring"

    MIN_OPPONENT_PACE = 0.75  # Normalized 0-1 scale; ~top 25% of teams by pace
    CONFIDENCE = 0.80

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        pace = prediction.get('opponent_pace') or 0
        if pace < self.MIN_OPPONENT_PACE:
            return self._no_qualify()

        # Higher pace = higher confidence (0.75=0.80, 0.90=0.86, 1.0+=0.90)
        confidence = min(1.0, self.CONFIDENCE + (pace - self.MIN_OPPONENT_PACE) / 2.5)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'opponent_pace': round(pace, 1),
                'backtest_hr': 81.5,
            }
        )
