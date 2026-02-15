"""Prop Value Gap Extreme Signal — Model predicts 10+ points away from line.

STATUS: COMBO-ONLY (Session 256 comprehensive analysis)
  - Standalone: 46.7% HR (60 picks), below breakeven
  - **Combo (high_edge + prop_value):** 73.7% HR (38 picks), +11.7% synergy
  - **Best segment:** 89.3% HR on line < 15 + OVER (28 picks)
  - **Verdict:** Beneficial refinement filter for high_edge
  - Appears as strict subset (never standalone, only with high_edge)
  - Identifies top 16% of high_edge picks with +11.7% HR improvement
  - Detects all-stars with underpriced lines (LeBron @ 7.9, Embiid @ 8.4)
  - TOXIC on UNDER (16.7% HR) and mid-tier 15-25 line (6.5% HR)
  - NOT registered in build_default_registry() — combo-only logic in Best Bets aggregator

See: docs/08-projects/current/signal-discovery-framework/COMPREHENSIVE-SIGNAL-ANALYSIS.md
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
