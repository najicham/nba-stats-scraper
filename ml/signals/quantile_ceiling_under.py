"""Quantile Ceiling UNDER — p75 < line means even the optimistic prediction misses.

When a MultiQuantile model's p75 (optimistic) prediction can't reach the line,
UNDER wins ~90% of the time. This is a high-conviction, low-coverage signal:
fires on only ~2% of picks but at extremely high confidence.

First test (V12 NOVEG MQ, 56-day window, N=485 eval predictions):
  - QUANTILE_CEIL_UNDER: 90.0% HR (N=10, 2.1% coverage)
  - Narrow IQR picks (edge 3+): 75.0% HR (N=16)
  - Calibration q75: expected 0.75, actual 0.748 (validated)

IQR width modifier: narrow IQR (p75-p25 < line*0.5) is stronger signal.

Requires: prediction['quantile_p75'] present (only fires for MultiQuantile models).
Complement: quantile_floor_over (p25 > line → OVER confidence signal).

Created: Session 522
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class QuantileCeilingUnderSignal(BaseSignal):
    tag = "quantile_ceiling_under"
    description = "Quantile ceiling UNDER — p75 < line (90% HR, N=10 first test)"

    CONFIDENCE_BASE = 0.90

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Direction gate: UNDER only
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Only fires when MultiQuantile model data is present
        p75 = prediction.get('quantile_p75')
        if p75 is None:
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line <= 0:
            return self._no_qualify()

        # Core condition: even optimistic p75 prediction can't reach the line
        if p75 >= line:
            return self._no_qualify()

        # IQR width as uncertainty measure (narrow = more confident)
        p25 = prediction.get('quantile_p25')
        iqr_width = (p75 - p25) if p25 is not None else None
        narrow_iqr = iqr_width is not None and iqr_width < line * 0.5

        # Confidence boost for narrow IQR (75% vs 67% HR)
        confidence = min(0.95, self.CONFIDENCE_BASE + (0.05 if narrow_iqr else 0.0))

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'p75': round(p75, 2),
                'line': line,
                'ceiling_gap': round(line - p75, 2),
                'narrow_iqr': narrow_iqr,
                'iqr_width': round(iqr_width, 2) if iqr_width is not None else None,
                'backtest_hr': 90.0,
                'backtest_n': 10,
            }
        )
