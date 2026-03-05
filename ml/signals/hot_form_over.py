"""Hot Form Over Signal — OVER picks when player is trending UP.

Form ratio = avg_last_5 / avg_last_10. When >= 1.10, the player's recent
scoring pace is 10%+ above their 10-game average — momentum favors OVER.

This is a contextual evaluator: it doesn't improve the model's prediction,
it identifies WHEN to trust the model's OVER recommendation.

Data source: feature_0_value (pts_avg_last_5), feature_1_value (pts_avg_last_10)
from ml_feature_store_v2 via book_stats CTE.

Created: Session 410
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class HotFormOverSignal(BaseSignal):
    tag = "hot_form_over"
    description = "Hot form (5g avg / 10g avg >= 1.10) OVER — trending UP players"

    MIN_FORM_RATIO = 1.10  # 10%+ scoring increase over last 5 vs 10 games
    MIN_LINE = 10.0  # Filter noise from very low lines
    CONFIDENCE_BASE = 0.75
    CONFIDENCE_MAX_RATIO = 1.30  # Form ratio at which confidence maxes

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE:
            return self._no_qualify()

        avg_5 = prediction.get('points_avg_last_5') or 0
        avg_10 = prediction.get('points_avg_last_10') or 0

        if avg_10 <= 0 or avg_5 <= 0:
            return self._no_qualify()

        form_ratio = avg_5 / avg_10
        if form_ratio < self.MIN_FORM_RATIO:
            return self._no_qualify()

        # Scale confidence: 1.10 → 0.75, 1.30+ → 0.85
        ratio_pct = min(1.0, (form_ratio - self.MIN_FORM_RATIO) /
                        (self.CONFIDENCE_MAX_RATIO - self.MIN_FORM_RATIO))
        confidence = self.CONFIDENCE_BASE + ratio_pct * 0.10

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'form_ratio': round(form_ratio, 3),
                'avg_last_5': round(avg_5, 1),
                'avg_last_10': round(avg_10, 1),
                'line_value': round(line, 1),
            }
        )
