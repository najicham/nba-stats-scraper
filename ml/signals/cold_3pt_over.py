"""Cold 3PT OVER signal — cold 3PT shooter due for bounce-back.

When a player's recent 3PT% is 15%+ below their season average,
scoring bounce-back is likely as shooting regresses to mean.
OVER is profitable as the cold streak ends.

5-season cross-validated (2021-22 through 2025-26):
  - 60.2% HR (N=123), consistent all 5 seasons
  - Mechanism: 3PT% mean-reverts — extreme cold is temporary

Created: Session 462 (BB pipeline simulator validated)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class Cold3ptOverSignal(BaseSignal):
    tag = "cold_3pt_over"
    description = "Cold 3PT shooter OVER — 3PT_last_3 below season by 15%+, bounce-back expected (60.2% HR)"

    # Minimum 3PT% differential (season - last_3) to qualify
    MIN_3PT_DEFICIT = 0.15  # 15 percentage points below season avg
    # Minimum 3PT attempts per game to filter out low-volume noise
    MIN_THREE_PA = 3.0
    CONFIDENCE_BASE = 0.75

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Direction gate: OVER only
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        # Need 3PT stats from supplemental data
        if not supplemental or 'three_pt_stats' not in supplemental:
            return self._no_qualify()

        stats = supplemental['three_pt_stats']
        pct_last_3 = stats.get('three_pct_last_3')
        pct_season = stats.get('three_pct_season')
        tpa_per_game = stats.get('three_pa_per_game')

        # Need all stats present
        if any(v is None for v in [pct_last_3, pct_season, tpa_per_game]):
            return self._no_qualify()

        # Volume filter: must attempt enough 3s
        if tpa_per_game < self.MIN_THREE_PA:
            return self._no_qualify()

        # Core logic: recent 3PT% must be well below season average
        three_pt_deficit = pct_season - pct_last_3
        if three_pt_deficit < self.MIN_3PT_DEFICIT:
            return self._no_qualify()

        # Confidence scales with how extreme the cold streak is
        confidence = min(0.95, self.CONFIDENCE_BASE + (three_pt_deficit - self.MIN_3PT_DEFICIT) * 0.5)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'three_pct_last_3': round(pct_last_3, 3),
                'three_pct_season': round(pct_season, 3),
                'three_pt_deficit': round(three_pt_deficit, 3),
                'three_pa_per_game': round(tpa_per_game, 1),
                'backtest_hr': 60.2,
                'backtest_n': 123,
            },
        )
