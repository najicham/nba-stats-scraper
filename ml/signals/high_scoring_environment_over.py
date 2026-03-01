"""High Scoring Environment Over Signal — OVER picks in high implied team total games.

Backtest: 70.2% HR (N=329), Feb-resilient at 64.3% (N=28).
When implied_team_total >= 120, high-scoring game environments favor OVER.
Clear monotonic relationship: higher ITT = better OVER HR.

Edge 7+: 81.8% HR (N=99). Feb-resilient — outperforms baseline OVER by +14.2pp.

Created: Session 373
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class HighScoringEnvironmentOverSignal(BaseSignal):
    tag = "high_scoring_environment_over"
    description = "High implied team total (120+) OVER — 70.2% HR, Feb-resilient"

    MIN_IMPLIED_TEAM_TOTAL = 120.0
    CONFIDENCE = 0.80

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        itt = prediction.get('implied_team_total') or 0
        if itt < self.MIN_IMPLIED_TEAM_TOTAL:
            return self._no_qualify()

        # Higher ITT = higher confidence (120=0.80, 125=0.90, 130+=1.0)
        confidence = min(1.0, self.CONFIDENCE + (itt - self.MIN_IMPLIED_TEAM_TOTAL) / 50.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'implied_team_total': round(itt, 1),
                'backtest_hr': 70.2,
            }
        )
