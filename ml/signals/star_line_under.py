"""Star line UNDER signal — high-line players systematically overpriced.

When a player has a prop line >= 25, UNDER bets win at 57.6% at edge 3-7.
The market anchors to star reputation, systematically overpricing scoring.
Edge 7+ drops to 50% (model overconfidence), so this signal gates at edge < 7.

5-season cross-validated (2021-22 through 2025-26):
  - Line >= 25, edge 3-7, UNDER: 57.6% HR (N=1,018)
  - Per-season: 54.4%, 55.2%, 59.8%, 56.6%, 62.3% — all above 54%
  - Mechanism: market anchors to star reputation → systematic overpricing

Created: Session 463 (P1 simulator experiments)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class StarLineUnderSignal(BaseSignal):
    tag = "star_line_under"
    description = "Star line UNDER — line >= 25 with edge 3-7, market overprices stars (57.6% HR)"

    # Minimum prop line to qualify as "star-level"
    MIN_LINE = 25.0
    # Edge cap — model overconfidence at 7+ drops to 50%
    MAX_EDGE = 7.0
    MIN_EDGE = 3.0
    CONFIDENCE_BASE = 0.75

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Direction gate: UNDER only
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Need prop line
        line = prediction.get('line_value') or prediction.get('current_points_line')
        if line is None:
            return self._no_qualify()

        line = float(line)
        if line < self.MIN_LINE:
            return self._no_qualify()

        # Edge gate: only 3-7 range is profitable
        pred_pts = prediction.get('predicted_points')
        if pred_pts is None:
            return self._no_qualify()

        edge = abs(float(pred_pts) - line)
        if edge < self.MIN_EDGE or edge >= self.MAX_EDGE:
            return self._no_qualify()

        # Confidence scales with line height (higher line = stronger overpricing)
        confidence = min(0.90, self.CONFIDENCE_BASE + (line - self.MIN_LINE) * 0.01)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'line_value': round(line, 1),
                'edge': round(edge, 1),
                'backtest_hr': 57.6,
                'backtest_n': 1018,
            },
        )
