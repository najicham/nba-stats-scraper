"""Hot Streak signal — model correct on player 3+ consecutive games.

STATUS: REJECTED (Session 255 backtest)
  - AVG HR: 47.5% across W2-W4 (below 52.4% breakeven)
  - Stars: 42.1%, Mid: 50.0%, Role: 49.5% — no tier profitable
  - Starter minutes (25-32) showed 54.7% but inconsistent across windows
  - Hypothesis: model already captures recent performance via rolling features,
    so a streak signal adds no value and may be anti-correlated
  - NOT registered in build_default_registry()
"""

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


class HotStreakSignal(BaseSignal):
    tag = "hot_streak"
    description = "Model correct on player 3+ consecutive games — momentum play"

    MIN_STREAK = 3

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        if not supplemental or 'streak_stats' not in supplemental:
            return self._no_qualify()

        stats = supplemental['streak_stats']
        prev_correct = stats.get('prev_correct', [])

        streak = _count_streak(prev_correct, 1)

        if streak < self.MIN_STREAK:
            return self._no_qualify()

        # 3=0.6, 4=0.8, 5+=1.0
        confidence = min(1.0, streak / 5.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={'win_streak': streak},
        )
