"""Pace Mismatch signal — slow team facing fast-paced opponent, model says OVER."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class PaceMismatchSignal(BaseSignal):
    tag = "pace_up"
    description = "Opponent pace top-5 league, team pace bottom-15, model says OVER"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        if not features:
            return self._no_qualify()

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        opp_pace = features.get('opponent_pace')
        team_pace = features.get('team_pace')

        if opp_pace is None or team_pace is None:
            return self._no_qualify()

        # Use supplemental percentile thresholds if available,
        # otherwise use provided thresholds from backtest
        thresholds = (supplemental or {}).get('pace_thresholds', {})
        opp_top5 = thresholds.get('opp_pace_top5', 102.0)
        team_bottom15 = thresholds.get('team_pace_bottom15', 100.0)

        if opp_pace < opp_top5:
            return self._no_qualify()
        if team_pace > team_bottom15:
            return self._no_qualify()

        pace_diff = opp_pace - team_pace

        return SignalResult(
            qualifies=True,
            confidence=min(1.0, pace_diff / 8.0),
            source_tag=self.tag,
            metadata={
                'opponent_pace': round(float(opp_pace), 1),
                'team_pace': round(float(team_pace), 1),
                'pace_diff': round(float(pace_diff), 1),
            },
        )
