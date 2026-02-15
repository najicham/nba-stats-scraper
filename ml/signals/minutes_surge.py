"""Minutes Surge signal — player getting significantly more minutes recently."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class MinutesSurgeSignal(BaseSignal):
    tag = "minutes_surge"
    description = "Minutes avg last 3 games > season avg + 3, model says OVER"

    MIN_SURGE = 3.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        if not supplemental or 'minutes_stats' not in supplemental:
            return self._no_qualify()

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        stats = supplemental['minutes_stats']
        min_last_3 = stats.get('minutes_avg_last_3')
        min_season = stats.get('minutes_avg_season')

        if min_last_3 is None or min_season is None:
            return self._no_qualify()

        surge = min_last_3 - min_season
        if surge < self.MIN_SURGE:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=min(1.0, (surge - self.MIN_SURGE) / 5.0),
            source_tag=self.tag,
            metadata={
                'minutes_avg_last_3': round(min_last_3, 1),
                'minutes_avg_season': round(min_season, 1),
                'surge': round(surge, 1),
            },
        )
