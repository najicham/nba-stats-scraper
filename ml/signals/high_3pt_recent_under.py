"""High Recent 3PT% UNDER signal — absolute hot recent shooting regresses.

62.9% UNDER HR (N=197), 3/3 seasons validated.

Mechanism: when recent 3PT% (last 3 games) is absolutely elite (>= 45.5%),
regression to the mean is almost certain. The book's line doesn't fully
compress to account for variance at extreme shooting levels.

Distinct from hot_3pt_under (which requires three_pct_last_3 - three_pct_season >= 10pp):
this fires on ABSOLUTE recent shooting quality. Captures players who are always
efficient AND are running hot — hot_3pt_under misses them because the differential
is small when the season baseline is also high.

Overlap note: some picks will fire both this signal and hot_3pt_under. That overlap
is acceptable and harmless in shadow mode. Quantify overlap before promoting to
active — if >60% of fires are shared with hot_3pt_under at similar HR, retire this
in favor of hot_3pt_under's lower threshold.

Data source: pred['three_pct_last_3'] — already in pred dict (supplemental_data.py).
Volume gate: requires three_pa_per_game >= 3.

Scanner: three_pct_last_3_gte_p75_UNDER, threshold=0.4545 (p75).
Created: 2026-07-01
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class High3ptRecentUnderSignal(BaseSignal):
    tag = "high_3pt_recent_under"
    description = (
        "Recent 3PT% (last 3g) >= 45.5% UNDER — extreme shooting regresses "
        "(62.9% HR, N=197, 3/3 seasons)"
    )

    MIN_3PT_RECENT_PCT = 0.4545   # scanner p75 threshold
    MIN_THREE_PA = 3.0
    CONFIDENCE_BASE = 0.63

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        three_pct_last_3 = prediction.get('three_pct_last_3')
        if three_pct_last_3 is None:
            return self._no_qualify()

        if float(three_pct_last_3) < self.MIN_3PT_RECENT_PCT:
            return self._no_qualify()

        three_pa = None
        if supplemental and 'three_pt_stats' in supplemental:
            three_pa = supplemental['three_pt_stats'].get('three_pa_per_game')
        if three_pa is not None and float(three_pa) < self.MIN_THREE_PA:
            return self._no_qualify()

        confidence = min(0.82, self.CONFIDENCE_BASE + (float(three_pct_last_3) - self.MIN_3PT_RECENT_PCT) * 0.5)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'three_pct_last_3': round(float(three_pct_last_3), 3),
                'three_pa_per_game': round(float(three_pa), 1) if three_pa is not None else None,
                'threshold': self.MIN_3PT_RECENT_PCT,
                'backtest_hr': 62.9,
                'backtest_n': 197,
                'seasons_consistent': '3/3',
            },
        )
