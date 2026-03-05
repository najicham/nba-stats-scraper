"""Blowout Risk Under Signal — UNDER picks for players who sit in blowouts.

When a player has high blowout minutes risk (40%+), they tend to get benched
in lopsided games, capping their scoring upside — favors UNDER.

Data source: feature_57_value (blowout_risk) from ml_feature_store_v2.
Raw values range 0.1-0.8, median 0.4. 0.40+ = player sits 40%+ of blowouts.

Only 5 UNDER signals exist — this fills a gap using feature store data.

Created: Session 411
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class BlowoutRiskUnderSignal(BaseSignal):
    tag = "blowout_risk_under"
    description = "High blowout benching risk (40%+) UNDER — gets pulled in blowouts"

    MIN_BLOWOUT_RISK = 0.40  # 40%+ blowout bench rate (~50th percentile)
    MIN_LINE = 15.0  # Only matters for mid-to-high lines
    CONFIDENCE_BASE = 0.72

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE:
            return self._no_qualify()

        blowout_risk = prediction.get('blowout_risk') or 0
        if blowout_risk < self.MIN_BLOWOUT_RISK:
            return self._no_qualify()

        # Scale confidence: 0.40 → 0.72, 0.70+ → 0.82
        confidence = min(0.85, self.CONFIDENCE_BASE + (blowout_risk - self.MIN_BLOWOUT_RISK) / 3.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'blowout_risk': round(blowout_risk, 3),
                'line_value': round(line, 1),
            }
        )
