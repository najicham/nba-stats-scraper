"""Points Surge 3 Signal — Player's points last 3 games significantly above season average."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class PointsSurge3Signal(BaseSignal):
    tag = "points_surge_3"
    description = "Points last 3 games > season avg + 5 points → OVER"

    MIN_SURGE = 5.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Must be OVER recommendation
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        # Need points_avg_last_3 and points_avg_season from supplemental
        if not supplemental or 'points_stats' not in supplemental:
            return self._no_qualify()

        stats = supplemental['points_stats']
        points_last_3 = stats.get('points_avg_last_3')
        points_season = stats.get('points_avg_season')

        if points_last_3 is None or points_season is None:
            return self._no_qualify()

        surge = points_last_3 - points_season

        if surge < self.MIN_SURGE:
            return self._no_qualify()

        # Confidence scales with surge magnitude
        confidence = min(1.0, 0.6 + (surge - self.MIN_SURGE) / 10.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'points_last_3': round(points_last_3, 1),
                'points_season': round(points_season, 1),
                'surge': round(surge, 1)
            }
        )
