"""High Usage Under Signal — High-usage players tend to go UNDER their points line.

Cross-season validation: 53.2% UNDER rate (N=1,938), V9 edge 3+ HR 68.1%.
High-usage players face more defensive attention and fatigue effects,
while prop lines are set optimistically based on volume.

Created: Session 274 (market-pattern signals)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class HighUsageUnderSignal(BaseSignal):
    tag = "high_usage_under"
    description = "High-usage player (30%+ USG) with UNDER recommendation — 68.1% edge 3+ HR"

    MIN_USAGE = 30.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Must be UNDER recommendation
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Get usage rate
        usage = prediction.get('usage_avg_season')
        if usage is None and supplemental:
            usage = (supplemental.get('player_profile') or {}).get('usage_avg_season')

        if usage is None or usage < self.MIN_USAGE:
            return self._no_qualify()

        # Confidence scales with usage: 30%=0.70, 35%=0.80, 40%=0.90
        confidence = min(1.0, 0.70 + (usage - self.MIN_USAGE) * 0.02)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'usage_avg_season': round(usage, 1),
                'cross_season_under_rate': 53.2,
            }
        )
