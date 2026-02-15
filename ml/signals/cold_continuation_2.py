"""Cold Continuation 2 Signal — After 2+ consecutive misses, bet continuation (not reversion)."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class ColdContinuation2Signal(BaseSignal):
    tag = "cold_continuation_2"
    description = "2+ consecutive line misses, bet continuation of direction (research: 90% win rate)"

    MIN_STREAK = 2

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if not supplemental or 'streak_data' not in supplemental:
            return self._no_qualify()

        player_key = f"{prediction['player_lookup']}::{prediction['game_date']}"
        streak_info = supplemental['streak_data'].get(player_key, {})

        consecutive_misses = streak_info.get('consecutive_line_misses', 0)
        last_direction = streak_info.get('last_miss_direction', None)  # 'UNDER' or 'OVER'

        if consecutive_misses < self.MIN_STREAK:
            return self._no_qualify()

        # Only qualify if our recommendation matches the continuation direction
        # If they went UNDER twice, we should predict UNDER (continuation)
        recommendation = prediction.get('recommendation')

        if last_direction and recommendation != last_direction:
            return self._no_qualify()

        # High confidence - research showed 90% win rate for 2+ under continuation
        base_confidence = min(1.0, 0.75 + (consecutive_misses - 2) * 0.05)

        return SignalResult(
            qualifies=True,
            confidence=base_confidence,
            source_tag=self.tag,
            metadata={
                'consecutive_misses': consecutive_misses,
                'last_direction': last_direction,
                'recommendation': recommendation,
                'note': 'Continuation, not reversion (Session 242 research)'
            }
        )
