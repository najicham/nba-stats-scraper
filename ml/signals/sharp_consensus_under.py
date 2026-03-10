"""Sharp consensus UNDER signal — line dropped + high book disagreement.

When the BettingPros line has dropped >= 0.5 points AND cross-book standard
deviation >= 1.0, sharp money is pushing the line down while soft books
haven't fully adjusted. UNDER is profitable in this scenario.

5-season cross-validated (2021-22 through 2025-26):
  - 69.3% HR (N=205), consistent all 5 seasons (64-73% per season)
  - Edge 3+: 74.3% HR (N=35)
  - Mechanism: sharp money + high disagreement = market inefficiency favoring UNDER

Created: Session 463 (sharp book disaggregation experiment)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class SharpConsensusUnderSignal(BaseSignal):
    tag = "sharp_consensus_under"
    description = "Sharp consensus UNDER — line dropped 0.5+ with high book disagreement (69.3% HR)"

    # Minimum line drop to qualify (negative = line went down)
    MIN_LINE_DROP = 0.5
    # Minimum cross-book standard deviation for "high disagreement"
    MIN_LINE_STD = 1.0
    CONFIDENCE_BASE = 0.85

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Direction gate: UNDER only
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Need BettingPros line movement and cross-book std
        bp_move = prediction.get('bp_line_movement')
        bp_std = prediction.get('multi_book_line_std')

        if bp_move is None or bp_std is None:
            return self._no_qualify()

        # Core logic: line must have dropped AND books must disagree
        # bp_line_movement < 0 means line dropped (bearish)
        if bp_move > -self.MIN_LINE_DROP:
            return self._no_qualify()

        if bp_std < self.MIN_LINE_STD:
            return self._no_qualify()

        # Confidence scales with disagreement magnitude
        confidence = min(0.95, self.CONFIDENCE_BASE + (bp_std - self.MIN_LINE_STD) * 0.1)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'bp_line_movement': round(bp_move, 2),
                'multi_book_line_std': round(bp_std, 2),
                'backtest_hr': 69.3,
                'backtest_n': 205,
            },
        )
