"""Self-Creation Over Signal — OVER picks on high self-creators.

Players who create 50%+ of their own shots (unassisted FG) are volume
generators less dependent on assists/team scheme. On OVER picks, their
scoring is more predictable and likely to exceed the line.

BQ validation (Dec-Feb): 59.1% HR at SCR 0.50-0.54 (N=93), but
Feb-specific HR drops to 37% tracking the general OVER collapse.
Marked CONDITIONAL — signal concept is sound but NOT Feb-resilient.

IMPORTANT: SelfCreatorUnderSignal was tried in Session 274 and REMOVED
in Session 326 at 36.4% HR. This is directionally opposite (OVER, not UNDER).

Created: Session 380
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class SelfCreationOverSignal(BaseSignal):
    tag = "self_creation_over"
    description = "High self-creator (50%+ unassisted FG) on OVER — CONDITIONAL"

    MIN_SELF_CREATION_RATE = 0.50  # 50%+ unassisted FG rate
    MIN_LINE = 15  # Exclude bench players
    CONFIDENCE = 0.72  # Conservative — not Feb-resilient

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE:
            return self._no_qualify()

        scr = prediction.get('self_creation_rate_last_10') or 0
        if scr < self.MIN_SELF_CREATION_RATE:
            return self._no_qualify()

        # Higher self-creation = higher confidence (0.50=0.72, 0.65=0.78, 0.80+=0.82)
        confidence = min(0.82, self.CONFIDENCE + (scr - self.MIN_SELF_CREATION_RATE) * 0.3)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'self_creation_rate': round(scr, 3),
                'line': line,
                'backtest_hr': 59.1,
                'status': 'CONDITIONAL',
            }
        )
