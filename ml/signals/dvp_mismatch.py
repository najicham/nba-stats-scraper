"""Defense vs Position mismatch signal — opponent weak at defending player's position.

Session 401: Uses Hashtag Basketball DvP data to identify favorable matchups.
When a player faces a team that's bottom-5 at defending their position
AND our model says OVER, the positional mismatch provides an orthogonal signal.

A PG facing a team that allows 28 PPG to PGs vs league average 22 has a
6-point scoring differential that the model may underweight.

Signal:
  - dvp_favorable_over: Opponent is bottom-5 at defending player's position
    AND model says OVER → expected HR 60-65%
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class DvpFavorableOverSignal(BaseSignal):
    """OVER signal when opponent is weak at defending player's position.

    DvP data shows how many points each team allows to each position.
    Bottom-5 defensive ranking at the player's position creates a favorable
    scoring environment.
    """

    tag = "dvp_favorable_over"
    description = "Opponent bottom-5 at defending player's position — OVER signal"

    CONFIDENCE = 0.70
    MAX_DVP_RANK = 5  # Bottom 5 = worst defenders (rank 26-30 → top 5 in points allowed)

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        dvp_rank = prediction.get('opponent_dvp_rank')
        dvp_points_allowed = prediction.get('opponent_dvp_points_allowed')

        if dvp_rank is None:
            return self._no_qualify()

        # Bottom-5 means rank >= 26 (30 teams, ranked 1=best defense, 30=worst)
        # OR we can store as "rank among worst" where 1-5 = worst defenders
        if dvp_rank > self.MAX_DVP_RANK:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'dvp_rank': dvp_rank,
                'points_allowed': dvp_points_allowed,
                'player_position': prediction.get('player_position', ''),
                'opponent': prediction.get('opponent_team_abbr', ''),
            }
        )
