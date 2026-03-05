"""Consistent Scorer Over Signal — OVER picks for low-variance scorers.

Complement to volatile_scoring_over (CV >= 0.50, 81.5% HR). When a player's
scoring CV (std / line) is LOW (<= 0.30), they consistently hit near their
line — the model's OVER prediction is safer because the floor is high.

Data source: feature_3_value (points_std_last_10) from ml_feature_store_v2.
line_value always available on prediction dict.

Created: Session 410
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class ConsistentScorerOverSignal(BaseSignal):
    tag = "consistent_scorer_over"
    description = "Consistent scorer (CV <= 0.30) OVER — low variance = reliable OVER"

    MAX_CV = 0.30  # std / line_value
    MIN_LINE = 12.0  # Need meaningful line to compute CV
    CONFIDENCE = 0.75

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE:
            return self._no_qualify()

        std = prediction.get('points_std_last_10') or 0
        if std <= 0:
            return self._no_qualify()

        cv = std / line
        if cv > self.MAX_CV:
            return self._no_qualify()

        # Lower CV = higher confidence (0.30 → 0.75, 0.15 → 0.81, 0.05 → 0.85)
        confidence = min(0.85, self.CONFIDENCE + (self.MAX_CV - cv) / 2.5)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'scoring_cv': round(cv, 3),
                'points_std': round(std, 1),
                'line_value': round(line, 1),
            }
        )
