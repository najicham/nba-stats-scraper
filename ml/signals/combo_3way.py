"""Three-Way Combo signal — high edge + minutes surge + edge-spread-optimal quality gate.

SESSION 257 FINDING: 88.9% HR (17 picks), +19.4% synergy over 2-way combo
  - Edge >= 5 AND minutes surge >= 3 AND ESO-quality gate (confidence >= 70%, not in 88-90% problem tier)
  - The ESO gate acts as a quality filter that eliminates false positives

SESSION 295 FIX: OVER-only direction filter.
  - OVER: 95.5% HR (N=22), UNDER: 20.0% HR (N=5) — catastrophic gap.
  - Full-season audit confirmed UNDER picks with this combo are anti-pattern.

See: docs/08-projects/current/signal-testing/SESSION-257-RESULTS.md
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class ThreeWayComboSignal(BaseSignal):
    tag = "combo_3way"
    description = "Edge >= 5 + minutes surge >= 3 + ESO quality gate — premium 3-way combo"

    MIN_EDGE = 5.0
    MIN_SURGE = 3.0
    MIN_CONFIDENCE = 0.70
    PROBLEM_TIER_MIN = 0.88
    PROBLEM_TIER_MAX = 0.90

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Session 295: OVER-only — UNDER = 20.0% HR (N=5), catastrophic
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        # Check edge >= 5
        edge = abs(prediction.get('edge') or 0)
        if edge < self.MIN_EDGE:
            return self._no_qualify()

        # Check minutes surge >= 3
        if not supplemental or 'minutes_stats' not in supplemental:
            return self._no_qualify()

        stats = supplemental['minutes_stats']
        min_last_3 = stats.get('minutes_avg_last_3')
        min_season = stats.get('minutes_avg_season')

        if min_last_3 is None or min_season is None:
            return self._no_qualify()

        surge = min_last_3 - min_season
        if surge < self.MIN_SURGE:
            return self._no_qualify()

        # Check ESO quality gate: confidence >= 70%, not in 88-90% problem tier
        confidence = prediction.get('confidence_score') or 0
        if confidence < self.MIN_CONFIDENCE:
            return self._no_qualify()

        if self.PROBLEM_TIER_MIN <= confidence <= self.PROBLEM_TIER_MAX:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=0.95,
            source_tag=self.tag,
            metadata={
                'edge': round(edge, 2),
                'minutes_surge': round(surge, 1),
                'model_confidence': round(confidence, 3),
            },
        )
