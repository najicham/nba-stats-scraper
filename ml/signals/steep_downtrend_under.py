"""Steep Downtrend UNDER signal — sharper scoring decline than downtrend_under.

62.4% UNDER HR (N=213), 3/3 seasons validated.

Relationship to existing downtrend_under:
  - downtrend_under: slope band -1.5 to -0.5 (slight-to-moderate decline, N=1,654)
  - steep_downtrend_under: slope <= -0.82 (steeper decline, no upper cap)
  Overlap: picks with slope in [-1.5, -0.82] fire BOTH signals.
  Incremental value: picks with slope < -1.5 fire ONLY this signal (downtrend_under
  excludes them with its MIN_SLOPE gate). This captures accelerating collapses that
  the market hasn't fully repriced.

Mechanism: a very steep negative slope (losing 0.82+ pts per game each game over 7 games)
means the player's recent production is in rapid decline. The book's line still reflects
prior-week scoring, not the current trajectory. The model catches this ahead of the market.

Data source: pred['trend_slope'] — feature_44_value (OLS slope last 7 games).
Already in pred dict (supplemental_data.py).

Scanner: scoring_trend_slope_lte_p25_UNDER, threshold=-0.8214 (p25).
Created: 2026-07-01
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class SteepDowntrendUnderSignal(BaseSignal):
    tag = "steep_downtrend_under"
    description = (
        "Scoring slope <= -0.82 pts/g/g UNDER — rapid decline, model ahead of market "
        "(62.4% HR, N=213, 3/3 seasons)"
    )

    MAX_TREND_SLOPE = -0.8214    # scanner p25 threshold (no lower bound — steeper = stronger)
    MIN_LINE = 12.0              # exclude bench noise
    CONFIDENCE_BASE = 0.62

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        line = float(prediction.get('line_value') or 0)
        if line < self.MIN_LINE:
            return self._no_qualify()

        trend_slope = prediction.get('trend_slope')
        if trend_slope is None:
            return self._no_qualify()

        try:
            trend_slope = float(trend_slope)
        except (TypeError, ValueError):
            return self._no_qualify()

        if trend_slope > self.MAX_TREND_SLOPE:
            return self._no_qualify()

        confidence = min(0.80, self.CONFIDENCE_BASE + abs(trend_slope - self.MAX_TREND_SLOPE) * 0.05)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'trend_slope': round(trend_slope, 3),
                'threshold': self.MAX_TREND_SLOPE,
                'line_value': round(line, 1),
                'backtest_hr': 62.4,
                'backtest_n': 213,
                'seasons_consistent': '3/3',
            },
        )
