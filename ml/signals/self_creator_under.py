"""Self-Creator Under Signal — Self-creating scorers tend to go UNDER.

Cross-season validation: 53.6% UNDER rate (N=1,901), V9 edge 3+ HR 66.7%.
Players who score primarily off their own creation (high unassisted FG) have
more volatile scoring because they rely on individual shot-making rather than
team-generated looks.

Created: Session 274 (market-pattern signals)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class SelfCreatorUnderSignal(BaseSignal):
    tag = "self_creator_under"
    description = "Self-creator (5+ unassisted FG/game) with UNDER recommendation — 66.7% edge 3+ HR"

    MIN_UNASSISTED = 5.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Must be UNDER recommendation
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Get season unassisted FG average
        unassisted = prediction.get('unassisted_fg_season')
        if unassisted is None and supplemental:
            unassisted = (supplemental.get('player_profile') or {}).get('unassisted_fg_season')

        if unassisted is None or unassisted < self.MIN_UNASSISTED:
            return self._no_qualify()

        # Confidence scales with volume: 5=0.70, 6=0.775, 7=0.85
        confidence = min(1.0, 0.70 + (unassisted - self.MIN_UNASSISTED) * 0.075)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'unassisted_fg_season': round(unassisted, 1),
                'cross_season_under_rate': 53.6,
            }
        )
