"""FG Cold Continuation Signal — FG% last 3 below season - 1 std, predict UNDER."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class FGColdContinuationSignal(BaseSignal):
    tag = "fg_cold_continuation"
    description = "FG% last 3 < season - 1 std → UNDER (continuation, not reversion)"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Must be UNDER recommendation
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Need FG% stats
        if not supplemental or 'fg_stats' not in supplemental:
            return self._no_qualify()

        stats = supplemental['fg_stats']
        fg_last_3 = stats.get('fg_pct_last_3')
        fg_season = stats.get('fg_pct_season')
        fg_std = stats.get('fg_pct_std')

        if any(v is None for v in [fg_last_3, fg_season, fg_std]):
            return self._no_qualify()

        # Avoid division by zero
        if fg_std <= 0:
            return self._no_qualify()

        # Cold threshold: below season avg - 1 std
        threshold = fg_season - fg_std

        if fg_last_3 >= threshold:
            return self._no_qualify()

        # Confidence scales with how cold (z-score)
        z_score = (fg_season - fg_last_3) / fg_std
        confidence = min(1.0, 0.65 + (z_score - 1.0) / 3.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'fg_pct_last_3': round(fg_last_3, 3),
                'fg_pct_season': round(fg_season, 3),
                'z_score': round(z_score, 2),
                'note': 'Continuation signal from Session 242 research'
            }
        )
