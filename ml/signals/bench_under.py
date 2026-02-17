"""Bench Under Signal — Bench players systematically go UNDER their points line.

Cross-season validation: 76.6% UNDER rate (N=2,525 across 2 seasons).
Bench players get inconsistent minutes, face more defensive variability,
and have prop lines set based on limited recent data.

Created: Session 274 (market-pattern signals)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class BenchUnderSignal(BaseSignal):
    tag = "bench_under"
    description = "Bench player (non-starter) with UNDER recommendation — 76.6% UNDER rate cross-season"

    CONFIDENCE = 0.85  # Strong cross-season evidence

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Must be UNDER recommendation
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Check starter_flag — must be non-starter (False)
        starter_flag = prediction.get('starter_flag')
        if starter_flag is None and supplemental:
            starter_flag = (supplemental.get('player_profile') or {}).get('starter_flag')

        if starter_flag is None or starter_flag is True:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'starter_flag': False,
                'cross_season_under_rate': 76.6,
            }
        )
