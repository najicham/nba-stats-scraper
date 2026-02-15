"""Model Consensus V9 V12 Signal — Both V9 and V12 agree with edge >= 3."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class ModelConsensusV9V12Signal(BaseSignal):
    tag = "model_consensus_v9_v12"
    description = "V9 + V12 same direction + both edge >= 3 (enhanced dual_agree)"

    MIN_EDGE = 3.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Need V12 prediction
        if not supplemental or 'v12_prediction' not in supplemental:
            return self._no_qualify()

        v12_data = supplemental['v12_prediction']
        v9_rec = prediction.get('recommendation')
        v12_rec = v12_data.get('recommendation')

        # Must agree on direction
        if v9_rec != v12_rec:
            return self._no_qualify()

        # Both must have edge >= 3
        v9_edge = abs(prediction.get('edge', 0))
        v12_edge = abs(v12_data.get('edge', 0))

        if v9_edge < self.MIN_EDGE or v12_edge < self.MIN_EDGE:
            return self._no_qualify()

        # Confidence scales with average edge
        avg_edge = (v9_edge + v12_edge) / 2.0
        confidence = min(1.0, 0.7 + (avg_edge - self.MIN_EDGE) / 10.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'v9_edge': round(v9_edge, 2),
                'v12_edge': round(v12_edge, 2),
                'avg_edge': round(avg_edge, 2),
                'recommendation': v9_rec
            }
        )
