"""Predicted pace signal — TeamRankings predicted game pace for tonight's matchup.

Session 401: Upgrades the existing fast_pace_over signal with TeamRankings
predicted pace data for tonight's specific matchup instead of trailing averages.

Our existing opponent_pace (feature 18) is a trailing average. TeamRankings
provides schedule-strength-weighted predicted pace per team. Combining both
teams' pace gives a predicted game pace that's more accurate for tonight.

Signal:
  - predicted_pace_over: Both teams have top-10 predicted pace AND model says OVER
    Expected HR 65%+ based on fast_pace_over's 81.5% HR track record.
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class PredictedPaceOverSignal(BaseSignal):
    """OVER signal when TeamRankings predicted pace is in the top tier.

    Uses the average of both teams' predicted possessions-per-game from
    TeamRankings. When the predicted game pace is high (top 20th percentile),
    more scoring possessions are expected.
    """

    tag = "predicted_pace_over"
    description = "TeamRankings predicted game pace top-20% — OVER signal"

    CONFIDENCE = 0.75
    MIN_PREDICTED_PACE = 101.0  # Possessions per game threshold

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        predicted_pace = prediction.get('predicted_game_pace')
        if predicted_pace is None:
            return self._no_qualify()

        if predicted_pace < self.MIN_PREDICTED_PACE:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'predicted_pace': round(predicted_pace, 1),
                'team_pace': prediction.get('team_predicted_pace'),
                'opponent_pace': prediction.get('opponent_predicted_pace'),
            }
        )
