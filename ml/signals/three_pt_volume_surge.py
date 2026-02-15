"""Three PT Volume Surge Signal — Player attempting more 3-pointers recently."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class ThreePtVolumeSurgeSignal(BaseSignal):
    tag = "three_pt_volume_surge"
    description = "3PA last 3 games > season avg + 2 attempts → more scoring opportunities"

    MIN_SURGE = 2.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if not supplemental or 'three_pt_stats' not in supplemental:
            return self._no_qualify()

        # Must be OVER recommendation
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        stats = supplemental['three_pt_stats']
        tpa_last_3 = stats.get('three_pa_avg_last_3')
        tpa_season = stats.get('three_pa_per_game')

        if tpa_last_3 is None or tpa_season is None:
            return self._no_qualify()

        surge = tpa_last_3 - tpa_season

        if surge < self.MIN_SURGE:
            return self._no_qualify()

        # Higher volume = more scoring chances
        confidence = min(1.0, 0.6 + (surge / 5.0))

        # Boost if player is also shooting well
        three_pct_last_3 = stats.get('three_pct_last_3', 0)
        if three_pct_last_3 > 0.35:  # Above average 3PT%
            confidence = min(1.0, confidence + 0.1)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'three_pa_last_3': round(tpa_last_3, 1),
                'three_pa_season': round(tpa_season, 1),
                'surge': round(surge, 1),
                'three_pct_last_3': round(three_pct_last_3, 3) if three_pct_last_3 else None
            }
        )
