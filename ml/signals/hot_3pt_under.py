"""Hot 3PT UNDER signal — hot 3PT shooter due for regression.

When a player's recent 3PT% exceeds their season average by 10%+,
books anchor to season average while the hot streak is temporary.
UNDER is profitable as shooting regresses to mean.

5-season cross-validated (2021-22 through 2025-26):
  - 62.5% HR (N=670), consistent all 5 seasons
  - Mechanism: 3PT% mean-reverts faster than books adjust lines

Created: Session 462 (BB pipeline simulator validated)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class Hot3ptUnderSignal(BaseSignal):
    tag = "hot_3pt_under"
    description = "Hot 3PT shooter UNDER — 3PT_last_3 exceeds season by 10%+, regression expected (62.5% HR)"

    # Minimum 3PT% differential (last_3 - season) to qualify
    MIN_3PT_DIFF = 0.10  # 10 percentage points
    # Minimum 3PT attempts per game to filter out low-volume noise
    MIN_THREE_PA = 3.0
    CONFIDENCE_BASE = 0.80

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Direction gate: UNDER only
        if prediction.get('recommendation') != 'UNDER':
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

        # Volume filter: must attempt enough 3s for the signal to be meaningful
        if tpa_per_game < self.MIN_THREE_PA:
            return self._no_qualify()

        # Core logic: recent 3PT% must exceed season average by threshold
        three_pt_diff = pct_last_3 - pct_season
        if three_pt_diff < self.MIN_3PT_DIFF:
            return self._no_qualify()

        # Confidence scales with how extreme the hot streak is
        confidence = min(0.95, self.CONFIDENCE_BASE + (three_pt_diff - self.MIN_3PT_DIFF) * 0.5)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'three_pct_last_3': round(pct_last_3, 3),
                'three_pct_season': round(pct_season, 3),
                'three_pt_diff': round(three_pt_diff, 3),
                'three_pa_per_game': round(tpa_per_game, 1),
                'backtest_hr': 62.5,
                'backtest_n': 670,
            },
        )
