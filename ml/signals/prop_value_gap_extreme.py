"""Prop Value Gap Extreme Signal — Model predicts 10+ points away from line.

STATUS: REJECTED (Session 255 backfill)
  - 12.5% HR on 8 graded picks, -76.1% ROI
  - Extreme edge picks are often model errors, not market inefficiency
  - NOT registered in build_default_registry()
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class PropValueGapExtremeSignal(BaseSignal):
    tag = "prop_value_gap_extreme"
    description = "Edge >= 10 points (extreme model conviction regardless of confidence)"

    MIN_EDGE = 10.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        edge = abs(prediction.get('edge', 0))

        if edge < self.MIN_EDGE:
            return self._no_qualify()

        # Very high confidence - edge this large indicates strong model signal
        # Even if model confidence is lower, the magnitude matters
        confidence = min(1.0, 0.85 + (edge - self.MIN_EDGE) / 20.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'edge': round(edge, 2),
                'model_confidence': prediction.get('confidence_score', 0),
                'extreme_divergence': True
            }
        )
