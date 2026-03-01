"""Starter Under Signal — UNDER picks on starter-tier players.

Starters (season avg 15-24 points, line 15+) are the most predictable
tier for UNDER predictions. Not as volatile as stars, not as noisy as bench.

Backtest: Dec 68.1%, Jan 56.5%, Feb 54.8% (line 15-25, edge 3+).
Still profitable but declining trend. The signal helps starter UNDER picks
accumulate sufficient signal count to pass the MIN_SIGNAL_COUNT gate.

Distinct from bench_under (line < 12) and star_under filter (season_avg >= 25).

Created: Session 372
"""
from ml.signals.base_signal import BaseSignal, SignalResult


class StarterUnderSignal(BaseSignal):
    tag = "starter_under"
    description = "Starter tier UNDER — most predictable scoring tier"
    CONFIDENCE = 0.70
    MIN_SEASON_AVG = 15.0
    MAX_SEASON_AVG = 24.9
    MIN_LINE = 15

    def evaluate(self, prediction, features=None, supplemental=None):
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        season_avg = prediction.get('points_avg_season') or 0
        if season_avg < self.MIN_SEASON_AVG or season_avg > self.MAX_SEASON_AVG:
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'season_avg': season_avg,
                'line': line,
                'backtest_hr_dec': 68.1,
                'backtest_hr_feb': 54.8,
            }
        )
