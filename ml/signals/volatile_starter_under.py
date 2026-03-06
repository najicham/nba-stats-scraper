"""Volatile Starter Under Signal — UNDER on volatile starters at high edge.

Starters (line 18-25) with high scoring variance (std > 8) at edge 5+
are reliable UNDER targets. The model exploits variance better than the
market, and volatile players' lines are set conservatively high.

Backtest: 65.5% HR (N=637), +6.8pp over UNDER baseline (58.7%).
Monthly stable: Nov 63.6%, Dec 70.5%, Jan 61.9%, Feb 63.4%.

Data sources:
- prediction['line_value']: current prop line (18-25 = starter tier)
- prediction['points_std_last_10']: scoring std dev from feature store (f3)
- prediction['edge']: model edge (>= 5.0)

Created: Session 422c (shadow mode)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class VolatileStarterUnderSignal(BaseSignal):
    tag = "volatile_starter_under"
    description = "Volatile starter UNDER — line 18-25, std > 8, edge 5+"

    MIN_LINE = 18.0
    MAX_LINE = 25.0
    MIN_STD = 8.0
    MIN_EDGE = 5.0
    CONFIDENCE = 0.80

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE or line > self.MAX_LINE:
            return self._no_qualify()

        std = prediction.get('points_std_last_10') or 0
        if std < self.MIN_STD:
            return self._no_qualify()

        edge = abs(prediction.get('edge') or 0)
        if edge < self.MIN_EDGE:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'line_value': round(line, 1),
                'points_std': round(std, 1),
                'edge': round(edge, 1),
                'backtest_hr': 65.5,
            }
        )
