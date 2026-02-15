"""3PT Bounce signal — shooter due for regression to mean after cold streak."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class ThreePtBounceSignal(BaseSignal):
    tag = "3pt_bounce"
    description = "3PT shooter in cold streak (< avg-1*std), high volume, model says OVER"

    MIN_THREE_PA_PER_GAME = 4.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        if not supplemental or 'three_pt_stats' not in supplemental:
            return self._no_qualify()

        # Must be an OVER recommendation
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        stats = supplemental['three_pt_stats']
        pct_last_3 = stats.get('three_pct_last_3')
        pct_season = stats.get('three_pct_season')
        pct_std = stats.get('three_pct_std')
        tpa_per_game = stats.get('three_pa_per_game')

        # Need all stats present and valid
        if any(v is None for v in [pct_last_3, pct_season, pct_std, tpa_per_game]):
            return self._no_qualify()

        # Volume filter: must attempt enough 3s
        if tpa_per_game < self.MIN_THREE_PA_PER_GAME:
            return self._no_qualify()

        # Avoid division by zero
        if pct_std <= 0:
            return self._no_qualify()

        # Cold streak: last 3 games below season_avg - 1*std
        threshold = pct_season - pct_std
        if pct_last_3 >= threshold:
            return self._no_qualify()

        z_score = (pct_season - pct_last_3) / pct_std

        return SignalResult(
            qualifies=True,
            confidence=min(1.0, z_score / 3.0),
            source_tag=self.tag,
            metadata={
                'three_pct_last_3': round(pct_last_3, 3),
                'three_pct_season': round(pct_season, 3),
                'z_score': round(z_score, 2),
                'three_pa_per_game': round(tpa_per_game, 1),
            },
        )
