"""High Season 3PT% UNDER signal — elite shooters face inflated lines.

65.2% UNDER HR (N=230), 3/3 seasons, highest HR of all scanner-validated signals.

Mechanism: market sets lines assuming elite 3PT shooters will sustain their
efficiency. But 3PT shooting has high game-to-game variance even for elite
shooters. A player shooting 40%+ season average will revert toward 33% on any
given night — but the book already priced in the hot-shooter premium.

Distinct from hot_3pt_under (which requires last_3 > season + 10pp differential):
this fires on SEASON baseline excellence regardless of recent form. Captures
the "always overpriced" shooter archetype, not just the hot-streak mean-reversion.

Data source: pred['three_pct_season'] — already in pred dict (supplemental_data.py).
Volume gate: requires three_pa_per_game >= 3 to exclude incidental 3PT shooters.

Scanner: three_pct_season_gte_p75_UNDER, threshold=0.4022 (p75).
Created: 2026-07-01
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class High3ptSeasonUnderSignal(BaseSignal):
    tag = "high_3pt_season_under"
    description = (
        "Season 3PT% >= 40.2% UNDER — elite shooters have inflated lines "
        "(65.2% HR, N=230, 3/3 seasons)"
    )

    MIN_3PT_SEASON_PCT = 0.4022   # scanner p75 threshold
    MIN_THREE_PA = 3.0            # volume gate: meaningful 3PT shooter only
    CONFIDENCE_BASE = 0.65

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        three_pct_season = prediction.get('three_pct_season')
        if three_pct_season is None:
            return self._no_qualify()

        if float(three_pct_season) < self.MIN_3PT_SEASON_PCT:
            return self._no_qualify()

        three_pa = None
        if supplemental and 'three_pt_stats' in supplemental:
            three_pa = supplemental['three_pt_stats'].get('three_pa_per_game')
        if three_pa is not None and float(three_pa) < self.MIN_THREE_PA:
            return self._no_qualify()

        confidence = min(0.85, self.CONFIDENCE_BASE + (float(three_pct_season) - self.MIN_3PT_SEASON_PCT) * 0.5)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'three_pct_season': round(float(three_pct_season), 3),
                'three_pa_per_game': round(float(three_pa), 1) if three_pa is not None else None,
                'threshold': self.MIN_3PT_SEASON_PCT,
                'backtest_hr': 65.2,
                'backtest_n': 230,
                'seasons_consistent': '3/3',
            },
        )
