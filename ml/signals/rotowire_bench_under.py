"""RotoWire Bench UNDER Signal — Pre-game bench status from RotoWire lineups.

Uses pre-game `rotowire_is_starter` from the RotoWire lineup scraper as a
clean (no look-ahead bias) proxy for bench player status. The existing
`bench_under` signal uses post-game `starter_flag` which is look-ahead.

5-season bench_under baseline: 76.6% UNDER rate (N=2,525).
This signal is the pre-game equivalent — will track convergence.

Created: 2026-06-29 (open items from Session 5 handoff)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class RotoWireBenchUnderSignal(BaseSignal):
    tag = "rotowire_bench_under"
    description = (
        "Pre-game RotoWire bench status + UNDER — clean proxy for bench_under "
        "without post-game look-ahead bias"
    )

    CONFIDENCE = 0.75  # Conservative until live cross-validation

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        supp = supplemental or {}
        rotowire = supp.get('rotowire_lineup') or {}
        rotowire_is_starter = rotowire.get('is_starter')

        # Only fire when we have explicit pre-game data saying NOT a starter
        if rotowire_is_starter is None or rotowire_is_starter is True:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'rotowire_is_starter': False,
                'note': 'pre-game bench status from RotoWire lineups',
            },
        )
