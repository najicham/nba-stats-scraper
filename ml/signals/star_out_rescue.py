"""Star-OUT Vacated-Touches OVER signal (shadow accumulation mode).

When a team's lead scorer (>=18 ppg trailing 30d) is OUT, teammates ranked
2-7 on the team see a structural scoring spike that the market underprices.

EVIDENCE (docs/08-projects/current/star-out-vacated-touches-discovery/):
  Raw scoring spike: +2.14 pts actual vs +1.73 pts priced in by books (+0.25 residual)
  Combined edge 3+ OVER: 79.4% HR (N=509, 4 seasons)
  Incremental (not in current pipeline): 71.7% HR (N=357, CI [66.7%, 76.2%])
  ROI at -110: ~+50% per bet in the combined cohort

  Edge breakdown:
    edge 3-5 early announce: 73.3% HR (N=146)
    edge 3-5 late (>=17:00): 65.4% HR (N=78)
    edge 5+ early:           86.3% HR (N=182)
    edge 5+ late:            86.4% HR (N=103)

  Rank extension (ranks 5-7 validated 2026-05-23): full rotation benefits.
  B2B: FAVORABLE (68.5%/85.4% edge 3-5/5+), no B2B filter needed.

SHADOW MODE: this signal is in SHADOW_SIGNALS (zero real_sc contribution).
It tracks which picks WOULD qualify and accumulates live HR data.

TO ACTIVATE as a rescue signal (bypasses OVER floor 6.0→3.0):
  1. Check live N>=30 at HR>=65% in signal_health_daily / pick_signal_tags
  2. Get explicit user sign-off
  3. Add 'star_out_rescue' to rescue_tags in aggregator.py (line ~677)
  4. Add to OVER_SIGNAL_WEIGHTS at weight 2.5
  5. Remove from SHADOW_SIGNALS
  See: PRODUCTION-PLAN.md in the discovery doc folder for full checklist.

Data sources (supplemental_data.py _query_star_out_context()):
  pred['is_star_teammate_out'] — bool, True iff own team lead scorer is OUT today
  pred['target_team_scorer_rank'] — int 1-15, player's rank by trailing-30d ppg

Created: 2026-07-01
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class StarOutRescueSignal(BaseSignal):
    tag = "star_out_rescue"
    description = (
        "Lead scorer (>=18 ppg) OUT — rank 2-7 teammate OVER. "
        "79.4% HR (N=509, 4-season). Shadow accumulation only."
    )

    MIN_EDGE = 3.0
    ELIGIBLE_RANKS = frozenset({2, 3, 4, 5, 6, 7})
    CONFIDENCE_BASE = 0.80
    CONFIDENCE_HIGH_EDGE = 0.90

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        edge = abs(float(prediction.get('edge') or 0))
        if edge < self.MIN_EDGE:
            return self._no_qualify()

        if not prediction.get('is_star_teammate_out'):
            return self._no_qualify()

        rank = prediction.get('target_team_scorer_rank')
        if rank not in self.ELIGIBLE_RANKS:
            return self._no_qualify()

        if edge >= 5.0:
            confidence = self.CONFIDENCE_HIGH_EDGE
        else:
            confidence = self.CONFIDENCE_BASE + (edge - self.MIN_EDGE) / 2.0 * 0.10

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'target_team_scorer_rank': rank,
                'model_edge': round(edge, 2),
                'backtest_hr_combined': 79.4,
                'backtest_n_combined': 509,
                'backtest_hr_incremental': 71.7,
                'backtest_n_incremental': 357,
                'status': 'shadow_accumulation',
            },
        )
