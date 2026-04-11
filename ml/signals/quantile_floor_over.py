"""Quantile Floor OVER — p25 > line means even the pessimistic prediction clears.

When a MultiQuantile model's p25 (pessimistic, bottom quartile) prediction
still clears the line, OVER should win with high confidence. Mirror of
quantile_ceiling_under.

First test (V12 NOVEG MQ, 56-day window, N=485 eval predictions):
  - QUANTILE_FLOOR_OVER: 0.0% HR (N=1) — insufficient sample, start in shadow
  - Coverage is very low (~0.2%) — this condition is rare

Starts in SHADOW_SIGNALS pending live validation (N >= 30 at BB level).
When p25 > line, the bar is extremely high — model thinks ~75% chance actual
exceeds the line. Expected to be strong once sample accumulates.

Requires: prediction['quantile_p25'] present (only fires for MultiQuantile models).
Complement: quantile_ceiling_under (p75 < line → UNDER confidence signal).

Created: Session 522
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class QuantileFloorOverSignal(BaseSignal):
    tag = "quantile_floor_over"
    description = "Quantile floor OVER — p25 > line (shadow mode, accumulating live data)"

    CONFIDENCE_BASE = 0.85

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Direction gate: OVER only
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        # Only fires when MultiQuantile model data is present
        p25 = prediction.get('quantile_p25')
        if p25 is None:
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line <= 0:
            return self._no_qualify()

        # Core condition: even pessimistic p25 prediction clears the line
        if p25 <= line:
            return self._no_qualify()

        # IQR width as confidence modifier (narrow = more certain)
        p75 = prediction.get('quantile_p75')
        iqr_width = (p75 - p25) if p75 is not None else None
        narrow_iqr = iqr_width is not None and iqr_width < line * 0.5

        confidence = min(0.95, self.CONFIDENCE_BASE + (0.05 if narrow_iqr else 0.0))

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'p25': round(p25, 2),
                'line': line,
                'floor_gap': round(p25 - line, 2),
                'narrow_iqr': narrow_iqr,
                'iqr_width': round(iqr_width, 2) if iqr_width is not None else None,
                'backtest_hr': 0.0,  # N=1 in first test — shadow until live data
                'backtest_n': 1,
            }
        )
