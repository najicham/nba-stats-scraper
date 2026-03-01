"""Sharp Line Move Over Signal — OVER picks where DraftKings line moved UP 2+ pts intra-day.

When DraftKings moves a player's prop line UP by 2+ points on game day
(closing > opening), it signals sharp/informed money expects higher scoring.
Combined with an OVER prediction from the model, both market and model agree.

BQ validation (Dec-Feb):
  - Line up 2.0+: 67.8% HR (N=577), Feb-resilient at 69.0% (N=42)
  - Line up 1.0:  55.6% overall but drops to 42.6% Feb — NOT resilient at 1.0
  - Line down:    50.6% HR (N=694) — bearish for OVER

Threshold set at >= 2.0 for Feb-resilience. This complements line_rising_over
(inter-game line changes from prop_line_delta). This signal uses INTRA-DAY
movement — same-day DraftKings opening->closing.

Created: Session 380
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class SharpLineMoveOverSignal(BaseSignal):
    tag = "sharp_line_move_over"
    description = "DraftKings line moved UP 2+ pts intra-day + OVER — 67.8% HR, Feb-resilient"

    MIN_LINE_MOVE = 2.0  # Line must move UP by at least 2.0 points
    CONFIDENCE = 0.85

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        dk_move = prediction.get('dk_line_move_direction')
        if dk_move is None:
            return self._no_qualify()

        if dk_move < self.MIN_LINE_MOVE:
            return self._no_qualify()

        # Higher move = higher confidence (2.0=0.85, 4.0=0.90, 6.0+=0.92)
        confidence = min(0.92, self.CONFIDENCE + (dk_move - self.MIN_LINE_MOVE) * 0.025)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'dk_line_move': round(dk_move, 1),
                'backtest_hr': 67.8,
                'feb_hr': 69.0,
            }
        )
