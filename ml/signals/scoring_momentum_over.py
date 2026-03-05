"""Scoring Momentum Over Signal — OVER picks for players with upward trend.

Combines two momentum indicators:
1. Trend slope > 1.0 (scoring increasing ~1+ pt/game over 10 games)
2. 3-game avg > 10-game avg (short-term outperforming medium-term)

Data sources:
- feature_44_value (trend_slope): range -5.2 to 6.1, median 0.0
- feature_43_value (pts_avg_last_3): range 0-38
- feature_1_value (points_avg_last_10): existing in pred dict

Created: Session 411
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class ScoringMomentumOverSignal(BaseSignal):
    tag = "scoring_momentum_over"
    description = "Scoring momentum (slope > 1.0 + 3g avg > 10g avg) OVER — upward trend"

    MIN_SLOPE = 1.0  # ~1 pt/game upward trend (median is 0.0)
    MIN_LINE = 10.0
    CONFIDENCE_BASE = 0.75

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE:
            return self._no_qualify()

        slope = prediction.get('trend_slope') or 0
        if slope < self.MIN_SLOPE:
            return self._no_qualify()

        avg_3 = prediction.get('pts_avg_last3') or 0
        avg_10 = prediction.get('points_avg_last_10') or 0

        if avg_10 <= 0 or avg_3 <= 0:
            return self._no_qualify()

        # Short-term must outperform medium-term
        if avg_3 <= avg_10:
            return self._no_qualify()

        # Scale confidence: slope 1.0 → 0.75, 3.0+ → 0.85
        confidence = min(0.90, self.CONFIDENCE_BASE + (slope - self.MIN_SLOPE) / 20.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'trend_slope': round(slope, 2),
                'pts_avg_last3': round(avg_3, 1),
                'points_avg_last_10': round(avg_10, 1),
                'line_value': round(line, 1),
            }
        )
