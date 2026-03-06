"""Star Favorite Under Signal — UNDER on star players whose team is favored.

Star players (line 25+) on teams favored by 3+ points go UNDER because
starters get pulled in blowouts, reducing scoring opportunities in Q4.

Backtest: ~73% HR (N=88 combined star + spread 3+).
Star + spread 6-10: 86.1% (N=36). Star + spread 3-6: 67.3% (N=52).

Data sources:
- prediction['line_value']: current prop line (>= 25 = star tier)
- prediction['spread_magnitude']: team spread from feature store (f41)

Created: Session 422c (shadow mode — N=88 borderline for production)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class StarFavoriteUnderSignal(BaseSignal):
    tag = "star_favorite_under"
    description = "Star favorite UNDER — line 25+, team favored by 3+"

    MIN_LINE = 25.0
    MIN_SPREAD = 3.0
    CONFIDENCE_BASE = 0.78
    CONFIDENCE_HIGH_SPREAD = 0.85  # For spread 6+

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE:
            return self._no_qualify()

        spread = prediction.get('spread_magnitude') or 0
        if spread < self.MIN_SPREAD:
            return self._no_qualify()

        confidence = (self.CONFIDENCE_HIGH_SPREAD if spread >= 6.0
                      else self.CONFIDENCE_BASE)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'line_value': round(line, 1),
                'spread_magnitude': round(spread, 1),
                'backtest_hr': 73.0,
            }
        )
