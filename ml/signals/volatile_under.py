"""Volatile Under Signal — High-variance scorers tend to go UNDER their points line.

Cross-season validation: 54.0% UNDER rate (N=1,825), V9 edge 3+ HR 73.1%.
Players with high scoring variance have prop lines set near their mean,
but variance means more extreme low games that push outcomes UNDER.

Created: Session 274 (market-pattern signals)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class VolatileUnderSignal(BaseSignal):
    tag = "volatile_under"
    description = "Volatile scorer (std >= 10 last 5) with UNDER recommendation — 73.1% edge 3+ HR"

    MIN_STD = 10.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Must be UNDER recommendation
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Get points standard deviation (last 5 games)
        points_std = prediction.get('points_std_last_5')
        if points_std is None and supplemental:
            points_std = (supplemental.get('player_profile') or {}).get('points_std_last_5')

        if points_std is None or points_std < self.MIN_STD:
            return self._no_qualify()

        # Confidence scales with std: 10=0.70, 12.5=0.775, 15=0.85
        confidence = min(1.0, 0.70 + (points_std - self.MIN_STD) * 0.03)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'points_std_last_5': round(points_std, 1),
                'cross_season_under_rate': 54.0,
            }
        )
