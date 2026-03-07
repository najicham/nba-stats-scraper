"""Bounce-Back Over Signal — OVER on players after a bad miss, AWAY only.

After a player badly misses their prop line (<70% of it), the market
over-corrects the line downward for road games. The bounce-back
effect is strong on the road (56.2% over rate, N=379) but completely
disappears at home (47.8%).

Combined with model OVER confirmation: 60%+ HR (N=178 at edge 3+).

Session 427 enhancement — shooting quality tiers (cross-season validated):
  Severe miss (<50%) + bad shooting (<30% FG) = 77.7% HR (N=103) — strongest
  Moderate miss (50-70%) = ~69% HR regardless of FG% (N=150)
  Severe miss (<50%) + OK shooting (>=30% FG) = 47.4% HR (N=57) — SUPPRESS
  The severe+OK case is a low-minutes miss (blowout/foul trouble), not
  shooting noise, so no true reversion expected.

Also acts as an anti-signal: UNDER after bad miss = 45.2% HR (N=334).
The under_after_bad_miss filter in the aggregator handles suppression.

Requires: prev_game_ratio, prev_game_fg_pct (from prev_game_context CTE
          in supplemental_data), is_home (from prediction enrichment).

Created: Session 418
Updated: Session 427 — shooting quality confidence tiers
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class BounceBackOverSignal(BaseSignal):
    tag = "bounce_back_over"
    description = "OVER after bad miss (<70% of line) + AWAY game — shooting-quality tiered confidence (Session 427)"

    CONFIDENCE_BASE = 0.75
    CONFIDENCE_SEVERE_BAD_SHOOTING = 0.90
    MAX_MISS_RATIO = 0.70  # scored < 70% of line
    SEVERE_MISS_RATIO = 0.50  # scored < 50% of line
    BAD_SHOOTING_THRESHOLD = 0.30  # FG% < 30%
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

        prev_fg_pct = prediction.get('prev_game_fg_pct') or 0
        is_severe_miss = prev_ratio < self.SEVERE_MISS_RATIO
        is_bad_shooting = prev_fg_pct > 0 and prev_fg_pct < self.BAD_SHOOTING_THRESHOLD

        # Severe miss + OK shooting = low-minutes miss (47.4% HR) — suppress
        if is_severe_miss and prev_fg_pct > 0 and not is_bad_shooting:
            return self._no_qualify()

        # Determine confidence tier
        if is_severe_miss and is_bad_shooting:
            # Severe miss + bad shooting = strongest bounce (77.7% HR)
            confidence = self.CONFIDENCE_SEVERE_BAD_SHOOTING
            miss_tier = 'severe_bad_shooting'
        else:
            # Moderate miss (any shooting) = solid bounce (~69% HR)
            miss_severity = self.MAX_MISS_RATIO - prev_ratio
            confidence = min(0.85, self.CONFIDENCE_BASE + miss_severity)
            miss_tier = 'moderate_miss'

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'prev_game_ratio': round(prev_ratio, 2),
                'prev_game_fg_pct': round(prev_fg_pct, 3),
                'prev_game_line': prev_line,
                'prev_game_points': prediction.get('prev_game_points', 0),
                'miss_tier': miss_tier,
                'backtest_hr_severe_bad': 77.7,
                'backtest_hr_moderate': 69.0,
            }
        )
