"""Prop Line Drop OVER signal — line dropped from previous game, market overreaction.

Session 293 backtest: OVER + line dropped 3+ from previous game = 79.0% HR (N=81).
The market drops lines reactively after bad games, creating OVER value when players
revert to their mean. This is a market inefficiency signal, not a model signal.

Session 294: Implemented as signal + aggregator pre-filter (block OVER + line jumped 3+).
Session 305: Threshold lowered from 3.0 to 2.0. At edge 3+: 71.6% HR (N=109) vs
77.9% HR (N=86) at 3.0 — 27% more qualifying picks with HR still well above breakeven.
Previous threshold produced zero production firings (too restrictive).
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class PropLineDropOverSignal(BaseSignal):
    tag = "prop_line_drop_over"
    description = "OVER pick where prop line dropped 2+ pts from previous game — 71.6% HR (N=109, edge 3+)"

    MIN_LINE_DROP = 2.0  # Line must have dropped by at least 2 points (Session 305: lowered from 3.0)
    CONFIDENCE = 0.85  # Adjusted for lower threshold

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Must be OVER recommendation
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        # Get prop line delta from supplemental data or prediction dict
        line_delta = prediction.get('prop_line_delta')
        if line_delta is None and supplemental:
            prop_stats = supplemental.get('prop_line_stats') or {}
            line_delta = prop_stats.get('line_delta')

        if line_delta is None:
            return self._no_qualify()

        # Line must have DROPPED by at least MIN_LINE_DROP
        # line_delta = current - previous, so a drop is negative
        if line_delta > -self.MIN_LINE_DROP:
            return self._no_qualify()

        drop_size = abs(line_delta)
        # Scale confidence with drop size (2pt drop = 0.85, 5+ = 1.0)
        confidence = min(1.0, self.CONFIDENCE + (drop_size - self.MIN_LINE_DROP) * 0.05)

        metadata = {
            'line_delta': round(line_delta, 1),
            'drop_size': round(drop_size, 1),
        }

        # Add previous line if available
        if supplemental and 'prop_line_stats' in supplemental:
            metadata['prev_line_value'] = supplemental['prop_line_stats'].get('prev_line_value')
            metadata['current_line_value'] = supplemental['prop_line_stats'].get('current_line_value')

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata=metadata,
        )
