"""Line Drifted Down UNDER signal — BettingPros line movement confirms UNDER.

When BettingPros consensus line has drifted down (negative movement between
-0.5 and -0.1), smart money is nudging the line lower. Combined with
model UNDER prediction, this is a strong confirmation signal.

5-season cross-validated (2021-22 through 2025-26):
  - 59.8% HR (N=336), consistent all 5 seasons
  - Mechanism: Small negative line moves = smart money UNDER lean

Created: Session 462 (BB pipeline simulator validated)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class LineDriftedDownUnderSignal(BaseSignal):
    tag = "line_drifted_down_under"
    description = "BettingPros line drifted down [-0.5, -0.1) — smart money nudging UNDER (59.8% HR)"

    # Line movement bounds (BettingPros points_line - opening_line)
    MAX_MOVEMENT = -0.1   # Must be at least this negative
    MIN_MOVEMENT = -0.5   # But not more than this (larger drops = different signal)
    CONFIDENCE_BASE = 0.78

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Direction gate: UNDER only
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Need BettingPros line movement data
        bp_movement = prediction.get('bp_line_movement')
        if bp_movement is None:
            return self._no_qualify()

        # Core logic: line moved down slightly (smart money nudge)
        # Movement is (current_line - opening_line), so negative = line dropped
        if bp_movement >= self.MAX_MOVEMENT or bp_movement < self.MIN_MOVEMENT:
            return self._no_qualify()

        # Confidence scales with movement magnitude
        move_mag = abs(bp_movement)
        confidence = min(0.90, self.CONFIDENCE_BASE + move_mag * 0.2)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'bp_line_movement': round(bp_movement, 2),
                'backtest_hr': 59.8,
                'backtest_n': 336,
            },
        )
