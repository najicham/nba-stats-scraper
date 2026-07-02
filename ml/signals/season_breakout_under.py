"""Season Breakout UNDER signal — player scoring significantly less than same point last season.

Captures role loss, post-trade usage drops, new star teammate stealing shots,
age-related decline being priced in slowly, and return-from-injury diminishment.
Books anchor on prior-season reputation; this signal fires when the model also
recommends UNDER, amplifying confidence.

Threshold: season_scoring_delta <= -3.0 PPG (current season avg through first-N games
vs prior season avg through first-N games).

Data source: pred['season_scoring_delta'], pred['cross_season_games'] —
same cross_season_map supplemental query as season_breakout_over.

NOTE: pre-registered hypothesis (no historical backtest). Shadow accumulation
from 2026-27 season open. Promote at N>=30 HR>=60%.

Created: 2026-07-01
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class SeasonBreakoutUnderSignal(BaseSignal):
    tag = "season_breakout_under"
    description = (
        "3+ PPG less vs same point last season + model UNDER — regression trajectory "
        "(shadow, no backtest; accumulates from 2026-27)"
    )

    MAX_DELTA = -7.0    # tightened 2026-07-01 (verified): -7.0 = 73.0% HR (N=407, 4/4 seasons); -5.0 = 65.7% (N=1,478); -3.0 = 63.7% (too loose, 2022-23 negative)
    MIN_LINE = 10.0
    MIN_GAMES = 20
    CONFIDENCE_BASE = 0.72
    CONFIDENCE_MAX = 0.88

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

        delta = prediction.get('season_scoring_delta')
        if delta is None:
            return self._no_qualify()

        n_games = int(prediction.get('cross_season_games') or 0)
        if n_games < self.MIN_GAMES:
            return self._no_qualify()

        if float(delta) > self.MAX_DELTA:
            return self._no_qualify()

        confidence = min(
            self.CONFIDENCE_MAX,
            self.CONFIDENCE_BASE + (abs(float(delta)) - abs(self.MAX_DELTA)) / 20.0,
        )

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'season_scoring_delta': round(float(delta), 2),
                'pts_current_season': round(float(prediction.get('pts_current_season_first_N') or 0), 1),
                'pts_prior_season': round(float(prediction.get('pts_prior_season_first_N') or 0), 1),
                'cross_season_games': n_games,
                'line_value': round(line, 1),
                'status': 'shadow_no_backtest',
            },
        )
