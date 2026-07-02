"""High Season Minutes UNDER signal — heavy-minute players face inflated lines.

STRONGEST cross-season consistency of all 61 scanner-validated UNDER signals:
above breakeven 5/5 seasons, N=362, 61.3% HR, +9.8pp effect.

Mechanism: books price high-minute players on peak-load assumptions. Rest,
rotation changes, blowouts, and foul trouble suppress production more than
the line allows. The market anchors on the player's reputation as a workhorse
without fully discounting the nights that load management kicks in.

Data source: supplemental['minutes_stats']['minutes_avg_season'] — same path
used by b2b_fatigue_under.py. Already computed by the minutes_stats CTE.

Scanner: minutes_avg_season_gte_p75_UNDER, threshold=34.47 (p75, 2025-26 data).
Created: 2026-07-01
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class HighMinutesUnderSignal(BaseSignal):
    tag = "high_minutes_under"
    description = (
        "Season avg minutes >= 34.5 mpg UNDER — heavy-minute players face inflated lines "
        "(5/5 seasons, 61.3% HR, N=362)"
    )

    MIN_MINUTES_SEASON = 34.47   # scanner p75 threshold
    CONFIDENCE_BASE = 0.61

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        minutes_avg = None
        if supplemental:
            minutes_avg = (supplemental.get('minutes_stats') or {}).get('minutes_avg_season')
            if minutes_avg is None:
                minutes_avg = (supplemental.get('recovery_stats') or {}).get('minutes_avg_season')

        if minutes_avg is None:
            return self._no_qualify()

        if float(minutes_avg) < self.MIN_MINUTES_SEASON:
            return self._no_qualify()

        confidence = min(0.80, self.CONFIDENCE_BASE + (float(minutes_avg) - self.MIN_MINUTES_SEASON) / 30.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'minutes_avg_season': round(float(minutes_avg), 1),
                'threshold': self.MIN_MINUTES_SEASON,
                'backtest_hr': 61.3,
                'backtest_n': 362,
                'seasons_consistent': '5/5',
            },
        )
