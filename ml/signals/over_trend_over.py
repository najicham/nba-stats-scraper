"""Over Trend Over Signal — OVER picks when player went OVER 3+ of last 5 games.

When a player has recently been going OVER their prop line frequently (60%+),
there's momentum/matchup context favoring another OVER. This is a contextual
signal — it identifies when recent history aligns with the model's OVER call.

Data source: prev_over_1..5 from streak_data CTE in supplemental_data.py,
mapped to prediction dict.

Created: Session 410
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class OverTrendOverSignal(BaseSignal):
    tag = "over_trend_over"
    description = "Over trend (60%+ over rate last 5 games) OVER — momentum favors OVER"

    MIN_OVER_RATE = 0.60  # 3+ of 5 games over
    MIN_LINE = 10.0  # Filter noise from low lines
    MIN_GAMES = 3  # Need at least 3 of the 5 prev_over values to be non-null
    CONFIDENCE = 0.75

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE:
            return self._no_qualify()

        # Gather prev_over_1..5 from prediction dict
        prev_overs = []
        for i in range(1, 6):
            val = prediction.get(f'prev_over_{i}')
            if val is not None:
                prev_overs.append(int(val))

        if len(prev_overs) < self.MIN_GAMES:
            return self._no_qualify()

        over_rate = sum(prev_overs) / len(prev_overs)
        if over_rate < self.MIN_OVER_RATE:
            return self._no_qualify()

        # Higher over rate = higher confidence (0.60 → 0.75, 0.80 → 0.80, 1.0 → 0.85)
        confidence = min(0.85, self.CONFIDENCE + (over_rate - self.MIN_OVER_RATE) / 4.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'over_rate': round(over_rate, 2),
                'overs_in_window': sum(prev_overs),
                'games_in_window': len(prev_overs),
                'line_value': round(line, 1),
            }
        )
