"""Scoring Cold Streak Over Signal — OVER picks on players in a cold streak.

Players who have gone UNDER their prop line 3+ consecutive games tend to
regress back toward their mean, making OVER a strong contrarian signal.

Backtest: 65.1% HR (N=304) overall. Drops to ~50% in Feb (seasonal),
but as a conditional signal it adds signal count without being sole decider.

Requires: feature_52_value (prop_under_streak) from feature store,
          points_avg_season >= 10 (filters noise from low-scoring players).

Created: Session 371
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class ScoringColdStreakOverSignal(BaseSignal):
    tag = "scoring_cold_streak_over"
    description = "OVER on player with 3+ consecutive games under prop line — 65.1% HR regression signal"

    CONFIDENCE = 0.75
    MIN_UNDER_STREAK = 3
    MIN_POINTS_AVG = 10.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        # Check prop_under_streak (feature 52) — 3+ consecutive under games
        streak = prediction.get('prop_under_streak') or 0
        if streak < self.MIN_UNDER_STREAK:
            return self._no_qualify()

        # Filter out low-scoring players (noise)
        points_avg = prediction.get('points_avg_season') or 0
        if points_avg < self.MIN_POINTS_AVG:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'prop_under_streak': streak,
                'points_avg_season': points_avg,
                'backtest_hr': 65.1,
            }
        )
