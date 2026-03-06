"""Bounce-Back Over Signal — OVER on players after a bad miss, AWAY only.

After a player badly misses their prop line (<70% of it), the market
over-corrects the line downward for road games. The bounce-back
effect is strong on the road (56.2% over rate, N=379) but completely
disappears at home (47.8%).

Combined with model OVER confirmation: 60%+ HR (N=178 at edge 3+).

Also acts as an anti-signal: UNDER after bad miss = 45.2% HR (N=334).
The under_after_bad_miss filter in the aggregator handles suppression.

Requires: prev_game_ratio (from prev_game_context CTE in supplemental_data),
          is_home (from prediction enrichment).

Created: Session 418
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class BounceBackOverSignal(BaseSignal):
    tag = "bounce_back_over"
    description = "OVER after bad miss (<70% of line) + AWAY game — 56.2% raw, 60%+ with model (Session 418)"

    CONFIDENCE = 0.75
    MAX_MISS_RATIO = 0.70  # scored < 70% of line
    MIN_LINE = 10.0  # filter noise from low lines

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        # Must be an AWAY game — bounce-back disappears at home
        if prediction.get('is_home', False):
            return self._no_qualify()

        # Check previous game miss ratio
        prev_ratio = prediction.get('prev_game_ratio') or 0
        prev_line = prediction.get('prev_game_line') or 0

        if prev_ratio <= 0 or prev_line < self.MIN_LINE:
            return self._no_qualify()

        if prev_ratio >= self.MAX_MISS_RATIO:
            return self._no_qualify()

        # Stronger confidence for worse misses
        miss_severity = self.MAX_MISS_RATIO - prev_ratio
        confidence = min(0.90, self.CONFIDENCE + miss_severity)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'prev_game_ratio': round(prev_ratio, 2),
                'prev_game_line': prev_line,
                'prev_game_points': prediction.get('prev_game_points', 0),
                'miss_severity': round(miss_severity, 2),
                'backtest_hr': 56.2,
                'backtest_n': 379,
            }
        )
