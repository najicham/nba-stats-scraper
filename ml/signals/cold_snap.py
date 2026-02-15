"""Cold Snap signal — player went UNDER their line 3+ straight, regression to mean."""

from typing import Dict, List, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


def _count_streak(values: List[Optional[int]], target: int) -> int:
    """Count consecutive occurrences of target from most recent game backward."""
    count = 0
    for v in values:
        if v is None:
            break
        if int(v) == target:
            count += 1
        else:
            break
    return count


class ColdSnapSignal(BaseSignal):
    tag = "cold_snap"
    description = "Player UNDER their line 3+ straight games — regression to mean, OVER"

    MIN_COLD_STREAK = 3

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        if not supplemental or 'streak_stats' not in supplemental:
            return self._no_qualify()

        # Regression to mean play — only applies to OVER
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        stats = supplemental['streak_stats']
        prev_over = stats.get('prev_over', [])

        # Count consecutive UNDER outcomes (prev_over == 0)
        cold_streak = _count_streak(prev_over, 0)

        if cold_streak < self.MIN_COLD_STREAK:
            return self._no_qualify()

        # 3=0.6, 4=0.8, 5+=1.0
        confidence = min(1.0, cold_streak / 5.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={'cold_streak': cold_streak},
        )
