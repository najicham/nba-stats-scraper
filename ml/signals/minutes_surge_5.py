"""Minutes Surge 5 Signal — Minutes average last 5 games significantly above season."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class MinutesSurge5Signal(BaseSignal):
    tag = "minutes_surge_5"
    description = "Minutes avg last 5 games > season avg + 3 (sustained increase)"

    MIN_SURGE = 3.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if not supplemental or 'minutes_stats' not in supplemental:
            return self._no_qualify()

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        stats = supplemental['minutes_stats']
        min_last_5 = stats.get('minutes_avg_last_5')
        min_season = stats.get('minutes_avg_season')

        if min_last_5 is None or min_season is None:
            return self._no_qualify()

        surge = min_last_5 - min_season
        if surge < self.MIN_SURGE:
            return self._no_qualify()

        # Sustained surge (5 games) = higher confidence than 3-game surge
        confidence = min(1.0, 0.65 + (surge - self.MIN_SURGE) / 5.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'minutes_avg_last_5': round(min_last_5, 1),
                'minutes_avg_season': round(min_season, 1),
                'surge': round(surge, 1),
                'sustained': True
            }
        )
