"""B2B Fatigue Under Signal — High-minute player on back-to-back games, predict UNDER."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class B2BFatigueUnderSignal(BaseSignal):
    tag = "b2b_fatigue_under"
    description = "High-minute player (35+ mpg) on back-to-back, predict UNDER due to fatigue"

    MIN_MINUTES_AVG = 35.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Must be back-to-back (0 rest days)
        rest_days = prediction.get('rest_days')
        if rest_days is None or rest_days != 0:
            return self._no_qualify()

        # Must be UNDER recommendation
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Must be high-minute player
        if not supplemental or 'minutes_stats' not in supplemental:
            return self._no_qualify()

        minutes_avg = supplemental['minutes_stats'].get('minutes_avg_season', 0)

        if minutes_avg < self.MIN_MINUTES_AVG:
            return self._no_qualify()

        # Confidence scales with minutes load (higher minutes = more fatigue)
        # 35 min = 0.6, 38 min = 0.8, 40+ min = 0.9+
        confidence = min(1.0, 0.5 + (minutes_avg - self.MIN_MINUTES_AVG) / 10.0)

        # Extra boost if player is elite (stars feel fatigue more on B2B)
        tier = prediction.get('player_tier', 'unknown')
        if tier in ['elite', 'stars']:
            confidence = min(1.0, confidence + 0.1)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'minutes_avg_season': round(minutes_avg, 1),
                'rest_days': 0,
                'player_tier': tier
            }
        )
