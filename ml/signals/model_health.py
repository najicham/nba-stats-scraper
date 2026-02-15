"""Model Health gate signal — blocks picks when champion model is decaying.

This is a GATE, not a pick signal. When the champion model's rolling 7-day
hit rate on edge 3+ picks drops below breakeven (52.4%), the gate blocks
ALL signal best bets for that day.

Impact: In W4 (Feb 1-13), champion HR was ~39.9%. This gate would have
produced 0 signal best bets, preventing all losses from model decay.
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


# Breakeven HR at -110 odds: need to win 52.4% of bets
BREAKEVEN_HR = 52.4

# Warning zone: model is working but may be declining
WARNING_HR = 58.0


class ModelHealthSignal(BaseSignal):
    tag = "model_health"
    description = "Gate: blocks picks when champion model HR below breakeven"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        supplemental = supplemental or {}
        health = supplemental.get('model_health', {})
        hr_7d = health.get('hit_rate_7d_edge3')

        if hr_7d is None:
            # No grading data yet — allow (model is new/fresh)
            return SignalResult(
                qualifies=True,
                confidence=1.0,
                source_tag=self.tag,
                metadata={'health_tier': 'unknown', 'reason': 'no_grading_data'},
            )

        if hr_7d < BREAKEVEN_HR:
            return SignalResult(
                qualifies=False,
                confidence=0.0,
                source_tag=self.tag,
                metadata={
                    'health_tier': 'blocked',
                    'reason': 'model_decay',
                    'hr_7d': hr_7d,
                    'threshold': BREAKEVEN_HR,
                },
            )

        if hr_7d < WARNING_HR:
            return SignalResult(
                qualifies=True,
                confidence=0.7,
                source_tag=self.tag,
                metadata={'health_tier': 'watch', 'hr_7d': hr_7d},
            )

        return SignalResult(
            qualifies=True,
            confidence=1.0,
            source_tag=self.tag,
            metadata={'health_tier': 'healthy', 'hr_7d': hr_7d},
        )
