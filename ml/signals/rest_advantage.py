"""Rest Advantage signal — player with 3+ days since last game.

STATUS: REJECTED (Session 255 backtest)
  - AVG HR: 50.8% across W2-W4 (below 52.4% breakeven)
  - W2: 60.2% looked good, but collapsed to 46.5% W3, 45.7% W4
  - Stars: 50.0% (N=10), Mid: 45.2%, Role: 51.9% — no tier profitable
  - Starter minutes (25-32) showed 54.8% but inconsistent across windows
  - Hypothesis: market already prices rest advantage well
  - NOT registered in build_default_registry()
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class RestAdvantageSignal(BaseSignal):
    tag = "rest_advantage"
    description = "Player has 3+ days since last game — rested, OVER"

    MIN_REST_DAYS = 3

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        if not supplemental or 'rest_stats' not in supplemental:
            return self._no_qualify()

        # Rest advantage should boost production → OVER
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        rest_days = supplemental['rest_stats'].get('rest_days')
        if rest_days is None or rest_days < self.MIN_REST_DAYS:
            return self._no_qualify()

        # 3 days=0.33, 4=0.67, 5+=1.0
        confidence = min(1.0, (rest_days - 2) / 3.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={'rest_days': rest_days},
        )
