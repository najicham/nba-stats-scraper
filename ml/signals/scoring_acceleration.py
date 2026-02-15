"""Scoring Acceleration Signal — Points trending up (last 3 > last 5 > season)."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class ScoringAccelerationSignal(BaseSignal):
    tag = "scoring_acceleration"
    description = "Points trending upward: last 3 > last 5 > season → OVER"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Must be OVER recommendation
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        # Need tiered points averages
        if not supplemental or 'points_stats' not in supplemental:
            return self._no_qualify()

        stats = supplemental['points_stats']
        pts_last_3 = stats.get('points_avg_last_3')
        pts_last_5 = stats.get('points_avg_last_5')
        pts_season = stats.get('points_avg_season')

        if any(v is None for v in [pts_last_3, pts_last_5, pts_season]):
            return self._no_qualify()

        # Must have clear upward trend
        if not (pts_last_3 > pts_last_5 > pts_season):
            return self._no_qualify()

        # Confidence scales with acceleration magnitude
        accel_3_to_5 = pts_last_3 - pts_last_5
        accel_5_to_season = pts_last_5 - pts_season

        total_accel = accel_3_to_5 + accel_5_to_season
        confidence = min(1.0, 0.6 + (total_accel / 10.0))

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'points_last_3': round(pts_last_3, 1),
                'points_last_5': round(pts_last_5, 1),
                'points_season': round(pts_season, 1),
                'total_acceleration': round(total_accel, 1)
            }
        )
