"""Dual Agree signal — V9 and V12 models agree on direction with edge >= 3."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class DualAgreeSignal(BaseSignal):
    tag = "dual_agree"
    description = "V9 and V12 models agree on OVER/UNDER, both at edge >= 3"

    MIN_EDGE = 3.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        if not supplemental or 'v12_prediction' not in supplemental:
            return self._no_qualify()

        v12 = supplemental['v12_prediction']
        v9_rec = prediction.get('recommendation')
        v9_edge = abs(prediction.get('edge') or 0)
        v12_rec = v12.get('recommendation')
        v12_edge = abs(v12.get('edge') or 0)

        if not v9_rec or not v12_rec:
            return self._no_qualify()

        # Both must recommend same direction with sufficient edge
        if v9_rec != v12_rec:
            return self._no_qualify()
        if v9_edge < self.MIN_EDGE or v12_edge < self.MIN_EDGE:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=min(1.0, min(v9_edge, v12_edge) / 10.0),
            source_tag=self.tag,
            metadata={
                'v9_edge': v9_edge,
                'v12_edge': v12_edge,
                'direction': v9_rec,
            },
        )
