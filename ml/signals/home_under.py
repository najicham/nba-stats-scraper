"""Home Under Signal — HOME team UNDER picks are structurally more predictable.

Backtest: 63.9% HR (N=1,386), Feb-resilient at 63.4%.
Home teams have more predictable rotations and minutes distribution,
making UNDER predictions more reliable.

Excludes low-line bench players (line < 15) since bench_under already covers those.

Created: Session 371
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class HomeUnderSignal(BaseSignal):
    tag = "home_under"
    description = "HOME team UNDER pick — 63.9% HR cross-season, Feb-resilient"

    CONFIDENCE = 0.80

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        if not prediction.get('is_home'):
            return self._no_qualify()

        # Bench players with low lines are already covered by bench_under
        line = prediction.get('line_value') or 0
        if line < 15:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'line': line,
                'backtest_hr': 63.9,
            }
        )
