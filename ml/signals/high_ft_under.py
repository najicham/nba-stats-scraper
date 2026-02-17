"""High FT Under Signal — High free-throw volume players tend to go UNDER.

Cross-season validation: 53.5% UNDER rate (N=1,141), V9 edge 3+ HR 66.7%.
Players who depend on free throws for scoring are vulnerable to UNDER outcomes
because FT volume is referee-dependent and less predictable than field goals.

Created: Session 274 (market-pattern signals)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class HighFTUnderSignal(BaseSignal):
    tag = "high_ft_under"
    description = "High FT volume (7+ FTA/game) with UNDER recommendation — 66.7% edge 3+ HR"

    MIN_FTA = 7.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Must be UNDER recommendation
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Get season FTA average
        fta = prediction.get('fta_season')
        if fta is None and supplemental:
            fta = (supplemental.get('player_profile') or {}).get('fta_season')

        if fta is None or fta < self.MIN_FTA:
            return self._no_qualify()

        # Confidence scales with FTA: 7=0.70, 8.5=0.775, 10=0.85
        confidence = min(1.0, 0.70 + (fta - self.MIN_FTA) * 0.05)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'fta_season': round(fta, 1),
                'cross_season_under_rate': 53.5,
            }
        )
