"""Elite Line UNDER signal — very high prop lines are systematically overpriced.

61.3% UNDER HR (N=349), 4/5 seasons validated.

Relationship to high_line_under:
  - high_line_under: line >= 25 (59.9% HR, 5/5 seasons — the broader signal)
  - elite_line_under: line >= 28 (61.3% HR, 4/5 seasons — stricter, slightly higher HR)
  These fire on overlapping but distinct populations. Carry both in shadow to measure
  incremental value before deciding whether to consolidate.

Mechanism: at very high scoring lines (28+ pts/game, i.e., top ~10 scorers in the league),
book uncertainty is highest and lines are widest. Market anchors on peak performance;
variance at these levels means even stars miss the line 60%+ of the time when the model
already sees UNDER pressure.

Data source: pred['line_value'] — always present, no new queries needed.

Scanner: elite_line_UNDER, threshold=28 pts.
Created: 2026-07-01
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class EliteLineUnderSignal(BaseSignal):
    tag = "elite_line_under"
    description = (
        "Prop line >= 28 UNDER — elite scoring lines systematically overpriced "
        "(61.3% HR, N=349, 4/5 seasons)"
    )

    MIN_LINE = 28.0
    CONFIDENCE_BASE = 0.61

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        line = float(prediction.get('line_value') or prediction.get('current_points_line') or 0)
        if line < self.MIN_LINE:
            return self._no_qualify()

        confidence = min(0.80, self.CONFIDENCE_BASE + (line - self.MIN_LINE) / 20.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'line_value': round(line, 1),
                'threshold': self.MIN_LINE,
                'backtest_hr': 61.3,
                'backtest_n': 349,
                'seasons_consistent': '4/5',
            },
        )
