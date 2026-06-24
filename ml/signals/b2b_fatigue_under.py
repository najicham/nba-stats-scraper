"""B2B Fatigue Under Signal — player on a back-to-back (1 rest day), predict UNDER.

REINSTATED 2026-06-23 (SHADOW) after a 5-season walk-forward re-validation overturned the
Session-373 disablement, which was a small-sample error.

Why it was wrongly disabled (Session 373): the original signal was evaluated on a single bad
month (Feb 2026, 39.5% HR) and on the `is_b2b` feature — which is populated 0 times in
2021-22…2024-25 and ONLY in 2025-26 (b2b UNDER's single weakest season). So every prior
evaluation could only ever see the worst slice.

5-season walk-forward truth (via days_rest=1, CatBoost V12_NOVEG, edge>=3 UNDER):
  - HR = 63.2% (N=174), ABOVE breakeven in ALL 5 seasons (60/56/73/56/54).
  - Passes the formal discovery gate: BH-FDR adj p=0.0035 (reject), block-bootstrap
    CI [56.7%, 70.0%] (entirely above breakeven), cross-season consistency PASS (cv=0.14).
  - NOT a 2025-26 artifact — it is WEAKEST in 2025-26 (54%), the opposite of the OVER signals.
  - High-minute (35+ mpg) subset is even stronger (69.8%) but low N; the broad all-b2b UNDER
    signal is the validated, higher-volume version, so the original 35-mpg hard gate is removed
    (minutes now only scale confidence).

Mechanism: fatigue on the second night of a b2b suppresses scoring → UNDER. This is the
cross-season-true direction. NOTE the active `b2b_boost_over` signal claims the opposite
("B2B is bullish for OVER") — but that is itself a 2025-26 OVER artifact (b2b OVER edge>=3 is
44/53/47/62/70 by season, 2/5 above breakeven; Session-396 evidence was 2025-26-era). Flag
`b2b_boost_over` for the OVER decay watch.

Status: SHADOW (registered + tracked, EXCLUDED from real_sc → zero pick impact) pending live
2026-27 confirmation. Promote to UNDER_SIGNAL_WEIGHTS at season open with sign-off once it
accrues N>=30 BB-level picks at HR>=58% in the new season.
Detail: docs/09-handoff/2026-06-23-broad-research-findings.md.
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class B2BFatigueUnderSignal(BaseSignal):
    tag = "b2b_fatigue_under"
    description = "Player on a back-to-back (1 rest day) with UNDER recommendation — fatigue suppresses scoring"

    # Minutes no longer gate the signal (the broad all-b2b UNDER edge is the validated one).
    # Minutes, when available, only scale confidence (higher load = more fatigue).
    MINUTES_CONF_FLOOR = 35.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Must be UNDER recommendation
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Must be back-to-back (1 rest day = consecutive game days)
        rest_days = prediction.get('rest_days')
        if rest_days is None and supplemental:
            rest_days = (supplemental.get('rest_stats') or {}).get('rest_days')
        if rest_days is None or rest_days != 1:
            return self._no_qualify()

        # Base confidence ~ the 5-season HR (0.62). Scale up modestly with minutes load when
        # available, since high-minute b2b UNDER is even stronger (~0.70) — but minutes are
        # optional and never required to qualify.
        confidence = 0.62
        minutes_avg = None
        if supplemental and 'minutes_stats' in supplemental:
            minutes_avg = (supplemental['minutes_stats'] or {}).get('minutes_avg_season')
        if minutes_avg is not None and minutes_avg >= self.MINUTES_CONF_FLOOR:
            confidence = min(0.85, 0.62 + (minutes_avg - self.MINUTES_CONF_FLOOR) / 25.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'rest_days': 1,
                'minutes_avg_season': round(minutes_avg, 1) if minutes_avg is not None else None,
                'backtest_hr_5season': 0.632,
                'status': 'shadow',
                'signal_mechanism': 'b2b fatigue suppresses scoring (5-season validated)',
            }
        )
