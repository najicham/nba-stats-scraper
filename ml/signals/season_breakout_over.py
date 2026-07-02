"""Season Breakout OVER signal — player scoring significantly more than same point last season.

Captures breakout seasons, new starting roles, post-trade usage gains, and
return-from-injury re-establishment. Books anchor lines on prior-season reputation;
this signal fires when the model also recommends OVER, amplifying confidence.

Threshold: season_scoring_delta >= +3.0 PPG (current season avg through first-N games
vs prior season avg through first-N games, where N = games played this season).
+3 PPG is roughly one tier shift (e.g., 15 → 18) and exceeds normal line-setting
variance between seasons (~0.5-1.5 PPG).

Data source: pred['season_scoring_delta'], pred['cross_season_games'] —
injected by cross_season_map in supplemental_data.py.
Requires >= 20 games played this season AND >= 20 comparable games last season.
Rookies and players absent last season get None → signal gates out cleanly.

NOTE: pre-registered hypothesis (no historical backtest). Shadow accumulation
from 2026-27 season open. Promote at N>=30 HR>=60%.

Created: 2026-07-01
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class SeasonBreakoutOverSignal(BaseSignal):
    tag = "season_breakout_over"
    description = (
        "3+ PPG more vs same point last season + model OVER — breakout trajectory "
        "(shadow, no backtest; accumulates from 2026-27)"
    )

    MIN_DELTA = 3.0
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

        if prediction.get('recommendation') != 'OVER':
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

        if float(delta) < self.MIN_DELTA:
            return self._no_qualify()

        confidence = min(
            self.CONFIDENCE_MAX,
            self.CONFIDENCE_BASE + (float(delta) - self.MIN_DELTA) / 20.0,
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
