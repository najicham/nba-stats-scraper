"""Slow pace UNDER signal — opponent pace <= 99 favors UNDER.

When a player faces a slow-paced opponent (pace <= 99 possessions/game),
fewer possessions = fewer scoring opportunities = UNDER is favored.

5-season cross-validated (2021-22 through 2025-26):
  - Pace <= 99, edge 3+, UNDER: 56.6% HR (N=777), consistent all 5 seasons
  - Pace <= 99, edge 5+, UNDER: 58.9% HR (N=185), consistent

Created: Session 463 (P0 simulator experiments)
2026-08-22: source column corrected. Both live query paths aliased
  feature_18_value (pct_paint, 0-1) AS opponent_pace instead of
  feature_14_value (raw pace). On a 0-1 variable the `opp_pace > 99.0`
  disqualifier can never trigger, so this signal fired on EVERY UNDER at a
  pinned 0.90 confidence and its recorded hit rate was just the all-UNDER base
  rate. The 99.0 threshold and the confidence curve were always correct for raw
  pace and are unchanged. All tag history before this date is void; the
  promotion gate (live N>=30) counts from 2026-27 only.
  Guarded by tests/unit/signals/test_feature_alias_contract.py.
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class SlowPaceUnderSignal(BaseSignal):
    tag = "slow_pace_under"
    description = "Slow pace UNDER — opponent pace <= 99, fewer possessions favors UNDER (56.6% HR)"

    # Maximum opponent pace for "slow" classification
    MAX_OPPONENT_PACE = 99.0
    # Scale guard. NBA team pace has never been below ~90 possessions/game, so a
    # value under this is a unit error, not a slow team — most likely a 0-1
    # normalized column wired in by mistake (which is exactly what happened
    # between Session 463 and 2026-08-22). Fail closed: a "slow pace" gate fed a
    # 0-1 variable qualifies EVERY pick silently, which is the worst outcome.
    MIN_PLAUSIBLE_PACE = 80.0
    CONFIDENCE_BASE = 0.70

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Direction gate: UNDER only
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Opponent pace from pred dict
        opp_pace = prediction.get('opponent_pace')
        if opp_pace is None:
            return self._no_qualify()

        # Scale guard before the comparison — see MIN_PLAUSIBLE_PACE.
        if opp_pace < self.MIN_PLAUSIBLE_PACE:
            return self._no_qualify()

        # Core logic: opponent must be slow-paced
        if opp_pace > self.MAX_OPPONENT_PACE:
            return self._no_qualify()

        # Confidence scales with how slow (lower pace = stronger signal)
        confidence = min(0.90, self.CONFIDENCE_BASE + (self.MAX_OPPONENT_PACE - opp_pace) * 0.02)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'opponent_pace': round(opp_pace, 1),
                'backtest_hr': 56.6,
                'backtest_n': 777,
            },
        )
