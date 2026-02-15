"""Hot Streak 2 Signal — Player beat line in 2+ consecutive games."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class HotStreak2Signal(BaseSignal):
    tag = "hot_streak_2"
    description = "Player beat line in 2+ consecutive games (lighter continuation signal)"

    MIN_STREAK = 2

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if not supplemental or 'streak_data' not in supplemental:
            return self._no_qualify()

        player_key = f"{prediction['player_lookup']}::{prediction['game_date']}"
        streak_info = supplemental['streak_data'].get(player_key, {})

        consecutive_beats = streak_info.get('consecutive_line_beats', 0)

        if consecutive_beats < self.MIN_STREAK:
            return self._no_qualify()

        # Lower base confidence than hot_streak_3 (2 games vs 3)
        base_confidence = min(1.0, 0.55 + (consecutive_beats - 2) * 0.05)

        tier = prediction.get('player_tier', 'unknown')
        if tier in ['elite', 'stars']:
            base_confidence = min(1.0, base_confidence + 0.05)

        return SignalResult(
            qualifies=True,
            confidence=base_confidence,
            source_tag=self.tag,
            metadata={'consecutive_beats': consecutive_beats}
        )
