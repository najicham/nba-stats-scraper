"""Edge Spread Optimal Signal — High edge with optimal confidence band (excludes 88-90% problem tier).

STATUS: REJECTED (Session 255 backfill)
  - 47.4% HR on 78 graded picks, -9.4% ROI
  - Below 52.4% breakeven — the confidence band filtering doesn't add value
  - NOT registered in build_default_registry()
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class EdgeSpreadOptimalSignal(BaseSignal):
    tag = "edge_spread_optimal"
    description = "Edge >= 5 + confidence 70-88% (exclude 88-90% problem tier identified in research)"

    MIN_EDGE = 5.0
    MIN_CONFIDENCE = 0.70
    MAX_CONFIDENCE_SAFE = 0.88  # Exclude 88-90% problem tier
    PROBLEM_TIER_MIN = 0.88
    PROBLEM_TIER_MAX = 0.90

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        edge = abs(prediction.get('edge', 0))
        confidence = prediction.get('confidence_score', 0)

        # Must have high edge
        if edge < self.MIN_EDGE:
            return self._no_qualify()

        # Must be in safe confidence range
        if confidence < self.MIN_CONFIDENCE:
            return self._no_qualify()

        # Exclude problem tier (88-90%)
        if self.PROBLEM_TIER_MIN <= confidence <= self.PROBLEM_TIER_MAX:
            return self._no_qualify()

        # Confidence calculation: higher edge + confidence in sweet spot = higher signal confidence
        # Sweet spot is 75-85%
        if 0.75 <= confidence <= 0.85:
            signal_confidence = 0.9
        elif confidence > 0.90:
            signal_confidence = 0.95  # Very high confidence is good
        else:
            signal_confidence = 0.75  # 70-75% or 85-88% is decent

        # Boost for extreme edge
        if edge >= 8.0:
            signal_confidence = min(1.0, signal_confidence + 0.05)

        return SignalResult(
            qualifies=True,
            confidence=signal_confidence,
            source_tag=self.tag,
            metadata={
                'edge': round(edge, 2),
                'model_confidence': round(confidence, 3),
                'excluded_problem_tier': False,
                'sweet_spot': 0.75 <= confidence <= 0.85
            }
        )
