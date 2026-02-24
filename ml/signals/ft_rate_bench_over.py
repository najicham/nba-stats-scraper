"""FT Rate Bench Over Signal — high FT-rate bench players go OVER more often.

Backtest finding (N=1,548, 58 players, controlled for edge):
  - Bench OVER + high FT rate (FTA/FGA >= 0.30): 72.5% HR (edge 5.2)
  - Bench OVER + low FT rate: 66.9% HR (edge 5.2)
  - 5.6pp gradient at same edge — real, not confounded

Status: WATCH — strong backtest but needs live validation before promotion.
This is a positive signal (annotates picks), NOT a negative filter.

Created: Session 336 (player profile signals pivot from V15 model experiment)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class FTRateBenchOverSignal(BaseSignal):
    tag = "ft_rate_bench_over"
    description = "Bench OVER + high FT rate (FTA/FGA >= 0.30): 72.5% HR (N=1,548)"

    BENCH_LINE_CEILING = 15.0   # Bench tier = line < 15
    MIN_FT_RATE = 0.30          # High FT rate threshold (~top 30%)
    CONFIDENCE = 0.80           # WATCH — needs live validation

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Gate 1: Must be OVER
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        # Gate 2: Must be bench tier (line < 15)
        line_value = prediction.get('line_value') or 0
        if line_value <= 0 or line_value >= self.BENCH_LINE_CEILING:
            return self._no_qualify()

        # Gate 3: Must have high FT rate
        ft_rate = prediction.get('ft_rate_season')
        if ft_rate is None:
            ft_rate = (supplemental or {}).get('player_profile', {}).get('ft_rate_season')
        if ft_rate is None or ft_rate < self.MIN_FT_RATE:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'ft_rate_season': round(ft_rate, 3),
                'line_value': float(line_value),
                'backtest_hr': 72.5,
                'backtest_n': 1548,
            }
        )
