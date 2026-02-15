"""Model Health signal — reports champion model decay state.

Tracks the champion model's rolling 7-day hit rate on edge 3+ picks.
Always qualifies (does not block picks) — the 2-signal minimum and
combo registry provide sufficient quality filtering even during decay.

Session 270: Removed gate behavior. Replay showed the health gate cost
$1,110 in profit (Jan 9 – Feb 12) while the signal system's 2-signal
minimum kept quality high (58.2% HR without gate vs 57.0% with gate).
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


# Breakeven HR at -110 odds: need to win 52.4% of bets
BREAKEVEN_HR = 52.4

# Warning zone: model is working but may be declining
WARNING_HR = 58.0


class ModelHealthSignal(BaseSignal):
    tag = "model_health"
    description = "Reports champion model health state (informational, does not block)"

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
                qualifies=True,
                confidence=0.3,
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
