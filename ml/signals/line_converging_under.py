"""Line converging UNDER signal — DK intraday line rose ≥ 0.5, market agrees with UNDER pick.

DISCOVERED 2026-06-29 via CLV Phase 2 research (T-3h snapshot analysis, 2025-26 season).

Evidence:
  - UNDER + DK line rose ≥ 0.5 by T-3h (market converging with UNDER): HR 62.4%
  - UNDER + DK line dropped ≥ 0.5 by T-3h (market diverging from UNDER): HR 46.6%
  - Gap: +15.8pp (p=5e-26, N=1,155 from true 2025-26 near-close snapshots)
  - Single-season only — 2025-26 is the first year with sufficient intraday snapshot density.
    Cross-season confirmation needed at live N≥30 in 2026-27.

Mechanism: When the DK line rises intraday (closing > opening), books are moving the target
upward — making UNDER easier to hit AND signaling that sharp/volume OVER action came in (which
our model didn't agree with). Either the market is wrong about the upward revision, or our
UNDER edge is being validated by the fact that the book didn't move the line our direction.
Both interpretations converge on: rising line + model UNDER edge = durable UNDER pick.

Two complementary wires:
  (1) THIS FILE — positive signal (agree direction: line rose ≥ 0.5 → SHADOW boost)
  (2) aggregator.py inline filter `clv_diverge_under_block` — block direction (line
      dropped ≥ 0.5 → ACTIVE block). UNDER picks where DK line dropped by game day = 46.6%
      HR (well below breakeven).

NOTE: dk_line_move_direction is computed in supplemental_data.py as (closing - opening)
using the latest available DK snapshot. For T-3h precision, the Phase 6 best-bets export
should be re-triggered at ~4:30 PM ET via Cloud Scheduler (see CLAUDE.md Task list).
Without the T-3h re-export, the signal uses the morning-to-noon drift (still directional
but weaker than T-3h).

Status: SHADOW (zero pick impact via SHADOW_SIGNALS). Promote to UNDER_SIGNAL_WEIGHTS
at season open after live N≥30 at HR≥60% in 2026-27.

Ancestor: ml/signals/closing_line_value.py (positive_clv_under) — removed Session 514 for
41.4% BB HR. The key difference: that signal used full-day opening-to-close CLV across all
seasons, while this is specifically T-3h validated with a direction-agreement filter.

Detail: docs/09-handoff/2026-06-29-3-session-handoff.md
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class LineConvergingUnderSignal(BaseSignal):
    tag = "line_converging_under"
    description = (
        "DK intraday line rose ≥ 0.5 + model UNDER — market converging with UNDER thesis "
        "(62.4% agree vs 46.6% disagree, T-3h, 2025-26, shadow)"
    )

    CONFIDENCE = 0.65
    MIN_LINE_RISE = 0.5

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        dk_move = prediction.get('dk_line_move_direction')
        if dk_move is None:
            return self._no_qualify()

        # Line rose intraday: market making UNDER easier = converging with UNDER thesis
        if float(dk_move) < self.MIN_LINE_RISE:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'dk_line_move_direction': round(float(dk_move), 2),
                'mechanism': 'line_rose_market_converges_with_under',
                'validated_hr_agree': 0.624,
                'validated_hr_disagree': 0.466,
                'status': 'shadow',
            },
        )
