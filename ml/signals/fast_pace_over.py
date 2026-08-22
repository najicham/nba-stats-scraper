"""Fast Pace Over Signal — OVER picks against fast-paced opponents.

Backtest: 81.5% HR (N=27) at best-bets level.
When opponent has fast pace, more possessions create more scoring opportunities.
Clear mechanism: pace drives volume, volume drives OVER.

Opponent pace is feature 14, stored RAW (possessions/game, ~92-108).
Threshold 102.0 ≈ top ~25% of teams by pace.

Created: Session 374
Session 387: threshold was lowered 102 -> 0.75 because the signal "could never
  fire". The real cause was the source column, not the threshold: both live
  query paths aliased feature_18_value (pct_paint, 0-1) AS opponent_pace, so
  the signal was actually asking "are >=75% of this player's shots in the
  paint". Session 387 fitted the threshold to the wrong variable.
2026-08-22: alias corrected to feature_14_value and the threshold restored to
  raw pace. All tag history before this date measured paint share, not pace —
  the promotion gate (live N>=30) counts from 2026-27 only.
  Guarded by tests/unit/signals/test_feature_alias_contract.py.
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class FastPaceOverSignal(BaseSignal):
    tag = "fast_pace_over"
    description = "Fast opponent pace (102+ poss/game) OVER — 81.5% HR, more possessions = more scoring"

    MIN_OPPONENT_PACE = 102.0  # Raw possessions/game; ~top 25% of teams by pace
    CONFIDENCE = 0.80

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        pace = prediction.get('opponent_pace') or 0
        if pace < self.MIN_OPPONENT_PACE:
            return self._no_qualify()

        # Higher pace = higher confidence (102=0.80, 106=0.85, 110+=0.90).
        # Mirrors slow_pace_under's per-possession slope; capped at 0.90 so a
        # single extreme opponent cannot pin every pick at maximum confidence.
        confidence = min(0.90, self.CONFIDENCE + (pace - self.MIN_OPPONENT_PACE) * 0.0125)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'opponent_pace': round(pace, 1),
                'backtest_hr': 81.5,
            }
        )
