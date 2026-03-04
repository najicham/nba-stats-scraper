"""Q4 Scorer Over Signal — Player with high Q4 scoring ratio + OVER recommendation.

Session 397: Players who score disproportionately in Q4 (35%+ of points in Q4)
favor OVER at 64.4% HR (N=292, edge 3+). The 18.4pp spread between High Q4 OVER
and High Q4 UNDER (42.2%) is massive — these "closers" systematically exceed
the model's season-average-based prediction.

Also used with q4_scorer_under_block aggregator filter (34.0% HR on UNDER).
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class Q4ScorerOverSignal(BaseSignal):
    tag = "q4_scorer_over"
    description = "Player scores 35%+ of points in Q4 (last 5 games) — late-game closer favors OVER"

    # Threshold from BQ analysis: 35%+ Q4 ratio = 34.0% UNDER HR (N=359)
    Q4_RATIO_THRESHOLD = 0.35

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Must be OVER recommendation
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        # Check Q4 scoring ratio (set by supplemental_data.py from BDL PBP)
        q4_ratio = prediction.get('q4_scoring_ratio') or 0
        if q4_ratio < self.Q4_RATIO_THRESHOLD:
            return self._no_qualify()

        # Confidence scales with Q4 ratio strength
        # 0.35 → 0.65, 0.50+ → 0.80
        confidence = min(0.80, 0.50 + q4_ratio)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'q4_scoring_ratio': round(q4_ratio, 3),
                'backtest_hr_over': 0.644,
                'backtest_hr_under': 0.340,
                'signal_mechanism': 'Late-game closer exceeds season averages'
            }
        )
