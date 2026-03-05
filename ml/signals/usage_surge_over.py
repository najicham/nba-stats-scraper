"""Usage Surge Over Signal — OVER picks for high-usage players.

When a player's recent 5-game usage rate is >= 25% (top quartile),
they're clearly getting more touches and shot attempts — favors OVER.

Data source: feature_48_value (usage_rate_last_5) from ml_feature_store_v2.
Raw values range 6.4-39.2, median 19.9. Threshold 25.0 ~= top quartile.

Created: Session 411
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class UsageSurgeOverSignal(BaseSignal):
    tag = "usage_surge_over"
    description = "High usage rate (25%+ last 5g) OVER — more touches = more scoring"

    MIN_USAGE = 25.0  # Top quartile usage rate
    MIN_LINE = 12.0  # Filter noise from low lines
    CONFIDENCE_BASE = 0.75

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE:
            return self._no_qualify()

        usage = prediction.get('usage_rate_l5') or 0
        if usage < self.MIN_USAGE:
            return self._no_qualify()

        # Scale confidence: 25% → 0.75, 35%+ → 0.85
        confidence = min(0.90, self.CONFIDENCE_BASE + (usage - self.MIN_USAGE) / 100.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'usage_rate_l5': round(usage, 1),
                'line_value': round(line, 1),
            }
        )
