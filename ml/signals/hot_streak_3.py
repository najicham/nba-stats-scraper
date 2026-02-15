"""Hot Streak 3 Signal — Player beat line in 3+ consecutive games."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class HotStreak3Signal(BaseSignal):
    tag = "hot_streak_3"
    description = "Player beat line in 3+ consecutive games (continuation signal)"

    MIN_STREAK = 3

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

        # Base confidence scales with streak length (cap at 5 games)
        base_confidence = min(1.0, consecutive_beats / 5.0)

        # Context-aware boost (if available)
        tier = prediction.get('player_tier', 'unknown')
        is_home = prediction.get('is_home', False)
        rest_days = prediction.get('rest_days', 1)

        context_boost = 0.0
        if tier in ['elite', 'stars']:
            context_boost += 0.1
        if is_home:
            context_boost += 0.05
        if rest_days >= 2:
            context_boost += 0.05

        confidence = min(1.0, base_confidence + context_boost)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'consecutive_beats': consecutive_beats,
                'player_tier': tier,
                'is_home': is_home,
                'rest_days': rest_days,
                'context_boost': round(context_boost, 3)
            }
        )
