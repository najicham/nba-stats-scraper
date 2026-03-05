"""Minutes Load Over Signal — OVER picks for heavy-workload players.

When a player has 100+ total minutes in the last 7 days, they're playing
heavy minutes across multiple games — engaged and in rhythm for OVER.

Data source: feature_40_value (minutes_load_last_7d) from ml_feature_store_v2.
Raw values range 0-177, median 26. 100+ = ~3 games of 33+ min.

Created: Session 411
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class MinutesLoadOverSignal(BaseSignal):
    tag = "minutes_load_over"
    description = "Heavy minutes load (100+ in 7d) OVER — engaged and in rhythm"

    MIN_MINUTES_LOAD = 100.0  # ~3 games of 33+ min in a week
    MIN_LINE = 12.0
    CONFIDENCE_BASE = 0.75

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE:
            return self._no_qualify()

        minutes_load = prediction.get('minutes_load_7d') or 0
        if minutes_load < self.MIN_MINUTES_LOAD:
            return self._no_qualify()

        # Scale confidence: 100 → 0.75, 150+ → 0.80
        confidence = min(0.85, self.CONFIDENCE_BASE + (minutes_load - self.MIN_MINUTES_LOAD) / 1000.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'minutes_load_7d': round(minutes_load, 1),
                'line_value': round(line, 1),
            }
        )
