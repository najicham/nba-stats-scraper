"""Over-Streak Reversion Under Signal — UNDER on players with 4+ overs in last 5.

Progressive mean reversion: when a player has gone OVER their prop line
in 4+ of their last 5 games, the UNDER rate next game is 56% (N=366).
At 3+ consecutive overs, it's 46.8% over rate (53.2% UNDER).

This is the mirror of scoring_cold_streak_over — hot streaks revert too.

Requires: prev_over_1..5 from streak_data CTE (already in supplemental_data).

Created: Session 418
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class OverStreakReversionUnderSignal(BaseSignal):
    tag = "over_streak_reversion_under"
    description = "UNDER after 4+ overs in last 5 games — 56% UNDER reversion (Session 418)"

    CONFIDENCE = 0.70
    MIN_OVERS_IN_5 = 4

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Count overs in last 5 games from prev_over_1..5
        overs_count = 0
        games_with_data = 0
        for i in range(1, 6):
            val = prediction.get(f'prev_over_{i}')
            if val is not None:
                games_with_data += 1
                if val == 1 or val is True:
                    overs_count += 1

        # Need at least 5 games of data
        if games_with_data < 5:
            return self._no_qualify()

        if overs_count < self.MIN_OVERS_IN_5:
            return self._no_qualify()

        # Stronger confidence when all 5 are overs
        confidence = 0.80 if overs_count == 5 else self.CONFIDENCE

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'overs_in_last_5': overs_count,
                'backtest_hr': 56.0,
                'backtest_n': 366,
            }
        )
