"""Rest Advantage 2D Signal — Player on 2+ rest days while opponent fatigued.

Session 318: Capped at MAX_SEASON_WEEKS=15 (~first week of Feb).
    Data: W2-W3=83% HR, W6=63.6%, W7=40% — clear mid-season decay.
    Rest advantage matters early-season, diminishes as teams settle rotations.
"""

from datetime import date
from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult
from shared.config.nba_season_dates import get_season_start_date, get_season_year_from_date


class RestAdvantage2DSignal(BaseSignal):
    tag = "rest_advantage_2d"
    description = "Player on 2+ rest days, opponent on 0-1 rest days (rest advantage)"

    MIN_PLAYER_REST = 2
    MAX_OPPONENT_REST = 1
    MAX_SEASON_WEEKS = 15  # ~15 weeks from season start (Oct→early Feb). W6+ decays to 40%.

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Session 318: Cap at MAX_SEASON_WEEKS — signal decays mid-season
        game_date = prediction.get('game_date')
        if game_date:
            if isinstance(game_date, str):
                game_date = date.fromisoformat(game_date)
            season_year = get_season_year_from_date(game_date)
            season_start = get_season_start_date(season_year, use_schedule_service=False)
            weeks_into_season = (game_date - season_start).days // 7
            if weeks_into_season > self.MAX_SEASON_WEEKS:
                return self._no_qualify()

        # Player must have 2+ days rest
        player_rest = prediction.get('rest_days')
        if player_rest is None or player_rest < self.MIN_PLAYER_REST:
            return self._no_qualify()

        # Opponent must be on 0-1 days rest (if available)
        opponent_rest = prediction.get('opponent_rest_days')

        # If we don't have opponent rest data, use a weaker qualification
        # (just player being rested is still valuable)
        if opponent_rest is None:
            # Require OVER recommendation + higher edge threshold
            if prediction.get('recommendation') != 'OVER':
                return self._no_qualify()
            if abs(prediction.get('edge', 0)) < 4.0:
                return self._no_qualify()

            base_confidence = 0.6  # Lower confidence without opponent data
        else:
            # Have opponent data - check for rest disadvantage
            if opponent_rest > self.MAX_OPPONENT_REST:
                return self._no_qualify()

            # Must predict OVER (rest advantage = more energy)
            if prediction.get('recommendation') != 'OVER':
                return self._no_qualify()

            # Confidence scales with rest gap
            rest_gap = player_rest - opponent_rest
            base_confidence = min(1.0, 0.65 + (rest_gap * 0.1))

        # Boost for stars (they benefit more from rest)
        tier = prediction.get('player_tier', 'unknown')
        if tier in ['elite', 'stars']:
            base_confidence = min(1.0, base_confidence + 0.1)

        return SignalResult(
            qualifies=True,
            confidence=base_confidence,
            source_tag=self.tag,
            metadata={
                'player_rest_days': player_rest,
                'opponent_rest_days': opponent_rest,
                'rest_gap': player_rest - opponent_rest if opponent_rest is not None else None,
                'player_tier': tier
            }
        )
