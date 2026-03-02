"""Sharp Line Drop Under Signal — UNDER picks where DraftKings line dropped 2+ pts intra-day.

When DraftKings moves a player's prop line DOWN by 2+ points on game day
(closing < opening), it signals sharp/informed money expects lower scoring.
Combined with an UNDER prediction from the model, both market and model agree.

BQ validation (Dec-Feb):
  - Line down 2+, UNDER: 72.4% HR (N=293)
    - Dec-Jan: 80.5% (N=185)
    - Feb: 58.3% (N=108) — above breakeven
  - Line down 2+, OVER: 45.8% (N=225) — bearish for OVER
  - By line range: Mid 74.7%, High 74.8%, Low 55.6%

Mirror of sharp_line_move_over (line UP 2+ → OVER, 67.8% HR).
Uses same dk_line_move_direction from supplemental_data.py.

Created: Session 382C
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class SharpLineDropUnderSignal(BaseSignal):
    tag = "sharp_line_drop_under"
    description = "DraftKings line dropped 2+ pts intra-day + UNDER — 72.4% HR, Feb 58.3%"

    MAX_LINE_MOVE = -2.0  # Line must drop by at least 2.0 points (negative direction)
    CONFIDENCE = 0.85

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        dk_move = prediction.get('dk_line_move_direction')
        if dk_move is None:
            return self._no_qualify()

        if dk_move > self.MAX_LINE_MOVE:
            return self._no_qualify()

        # Larger drop = higher confidence (2.0=0.85, 4.0=0.90, 6.0+=0.92)
        drop_magnitude = abs(dk_move)
        confidence = min(0.92, self.CONFIDENCE + (drop_magnitude - abs(self.MAX_LINE_MOVE)) * 0.025)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'dk_line_move': round(dk_move, 1),
                'backtest_hr': 72.4,
                'feb_hr': 58.3,
            }
        )
