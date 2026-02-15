"""High Edge + Minutes Surge combo signal — two strong indicators aligned.

SESSION 257 FINDING: 68.8% HR (16 picks), +33.5% ROI
  - Edge >= 5 AND minutes surge >= 3 AND OVER direction
  - Both conditions checked internally (no dependency on other signal instances)
  - Synergistic: minutes surge confirms the edge is backed by real playing time increase

See: docs/08-projects/current/signal-testing/SESSION-257-RESULTS.md
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class HighEdgeMinutesSurgeComboSignal(BaseSignal):
    tag = "combo_he_ms"
    description = "Edge >= 5 + minutes surge >= 3 + OVER — two strong indicators aligned"

    MIN_EDGE = 5.0
    MIN_SURGE = 3.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # OVER only — combo validated on OVER picks
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        # Check edge >= 5
        edge = abs(prediction.get('edge') or 0)
        if edge < self.MIN_EDGE:
            return self._no_qualify()

        # Check minutes surge >= 3
        if not supplemental or 'minutes_stats' not in supplemental:
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
            confidence=0.85,
            source_tag=self.tag,
            metadata={
                'edge': round(edge, 2),
                'minutes_surge': round(surge, 1),
            },
        )
