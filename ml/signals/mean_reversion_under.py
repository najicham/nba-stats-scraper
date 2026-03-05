"""Mean Reversion Under Signal — UNDER picks when player is on a hot streak.

When a player's 3-game average is 2+ points above their line AND their scoring
trend is steeply upward (slope >= 2.0), the market overweights the hot streak
but the model correctly expects regression. This is the strongest UNDER-specific
signal discovered:

  77.8% HR (N=212, +18.9pp over UNDER baseline)
  Stable all months including toxic Feb (79.6% vs 48.0% baseline)
  Directionally validated: helps UNDER (+16pp), hurts OVER (-2pp)

Also supports a "core" variant (slope >= 1.0) at 68.0% HR (N=565).

Data sources:
- feature_44_value (trend_slope): scoring trend over 10 games, range -5.2 to 6.1
- feature_43_value (pts_avg_last_3): recent 3-game scoring average
- prediction['line_value']: current prop line

Created: Session 413
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class MeanReversionUnderSignal(BaseSignal):
    tag = "mean_reversion_under"
    description = "Mean reversion (trend 2+ AND 3g avg > line+2) UNDER — hot streak regression"

    MIN_SLOPE = 2.0  # Strong upward trend (top ~5% of distribution)
    MIN_ABOVE_LINE = 2.0  # 3-game avg must be 2+ pts above the line
    MIN_LINE = 12.0  # Filter noise from very low lines
    CONFIDENCE_BASE = 0.80
    CONFIDENCE_MAX_SLOPE = 4.0  # Slope at which confidence maxes

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE:
            return self._no_qualify()

        slope = prediction.get('trend_slope') or 0
        if slope < self.MIN_SLOPE:
            return self._no_qualify()

        avg_3 = prediction.get('pts_avg_last3') or 0
        if avg_3 <= 0:
            return self._no_qualify()

        above_line = avg_3 - line
        if above_line < self.MIN_ABOVE_LINE:
            return self._no_qualify()

        # Scale confidence: slope 2.0 → 0.80, 4.0+ → 0.90
        slope_pct = min(1.0, (slope - self.MIN_SLOPE) /
                        (self.CONFIDENCE_MAX_SLOPE - self.MIN_SLOPE))
        confidence = self.CONFIDENCE_BASE + slope_pct * 0.10

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'trend_slope': round(slope, 2),
                'pts_avg_last3': round(avg_3, 1),
                'line_value': round(line, 1),
                'above_line': round(above_line, 1),
            }
        )
