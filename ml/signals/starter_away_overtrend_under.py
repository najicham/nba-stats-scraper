"""Starter Away Overtrend Under Signal — UNDER on away starters with high recent over rate.

When a starter (line 18-25) is playing AWAY and has been going OVER
frequently (over_rate > 50%), UNDER predictions are highly reliable.
The market overweights the recent hot streak but doesn't account for
the away game regression.

Backtest: 68.1% HR (N=213), +9.4pp over UNDER baseline (58.7%).
Monthly stable: Dec 73.1%, Jan 64.6%, Feb 67.2%, Mar 66.7%.

Data sources:
- prediction['line_value']: current prop line (18-25 = starter tier)
- prediction['is_home']: False for away games
- prediction['over_rate_last_10']: feature 55 from feature store (0-1 scale)

Created: Session 423 (shadow mode)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class StarterAwayOvertrendUnderSignal(BaseSignal):
    tag = "starter_away_overtrend_under"
    description = "Starter AWAY + over_rate > 50% UNDER — mean reversion away from home"

    MIN_LINE = 18.0
    MAX_LINE = 25.0
    MIN_OVER_RATE = 0.50  # > 50% of last 10 games went over
    CONFIDENCE = 0.80

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Away games only
        if prediction.get('is_home', False):
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE or line > self.MAX_LINE:
            return self._no_qualify()

        over_rate = prediction.get('over_rate_last_10')
        if over_rate is None or over_rate <= self.MIN_OVER_RATE:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'line_value': round(line, 1),
                'over_rate_last_10': round(over_rate, 2),
                'is_away': True,
                'backtest_hr': 68.1,
            }
        )
