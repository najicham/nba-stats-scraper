"""High Edge signal — picks where model edge >= 5.0 points."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class HighEdgeSignal(BaseSignal):
    tag = "high_edge"
    description = "Model predicts 5+ points away from the line"

    MIN_EDGE = 5.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        edge = abs(prediction.get('edge') or 0)
        if edge < self.MIN_EDGE:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=min(1.0, edge / 10.0),
            source_tag=self.tag,
            metadata={'edge': edge},
        )
