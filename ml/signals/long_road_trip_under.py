"""Long Road Trip UNDER signal — away team on its 3rd+ consecutive road game shows
cumulative travel fatigue that suppresses player scoring.

Background: Literature (JCSM 2021) finds that B2B games with travel show a −2.33 point
team margin vs +0.6 without travel. The effect accumulates: by the 5th away game, win
rate collapses. This is DISTINCT from `b2b_fatigue_under` (which fires only when
rest_days == 1 regardless of location context). This signal fires when the player's team
has been on an extended road trip (3+ consecutive away games), regardless of whether
today is a B2B.

How consecutive_road_games is computed: supplemental_data.py queries nbac_schedule to
count how many consecutive away games the AWAY team has played immediately before
tonight's game. The count resets to 1 whenever the team plays a home game. A player on
tonight's away team gets that team's consecutive road game count.

Signal logic:
  - recommendation == 'UNDER' (road fatigue suppresses scoring → UNDER)
  - player is on the away team (is_home == False)
  - consecutive_road_games >= 3

Confidence:
  - Base 0.62 at 3 consecutive away games
  - Scales up to 0.72 at 5+ (each extra game adds ~0.05 confidence, cap at 0.72)
  - Gracefully returns no-qualify when field absent

Status: SHADOW (registered + tracked, EXCLUDED from real_sc via SHADOW_SIGNALS → zero
pick impact). Promote to UNDER_SIGNAL_WEIGHTS at season open after live 2026-27 once it
accrues N>=30 BB-level picks at HR>=58%.

Sources:
  - Literature: JCSM 2021 — back-to-back games with travel: −2.33 team margin vs +0.6
  - Mechanism: 3rd+ consecutive road game = cumulative sleep disruption, time zone
    fatigue, no home-court prep. Books price the opponent's rest advantage but under-
    weight the road-team's multi-game accumulated fatigue.
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class LongRoadTripUnderSignal(BaseSignal):
    tag = "long_road_trip_under"
    description = (
        "Long road trip UNDER — away team on 3rd+ consecutive road game, "
        "cumulative travel fatigue suppresses scoring (shadow)"
    )

    MIN_CONSECUTIVE_ROAD = 3
    CONFIDENCE_BASE = 0.62
    CONFIDENCE_CAP = 0.72

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Direction gate: UNDER only
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Must be the away team — road trip only applies to the traveling team
        is_home = prediction.get('is_home')
        if is_home is None or bool(is_home):
            return self._no_qualify()

        # consecutive_road_games is set on the away team's players by supplemental_data
        road_games = prediction.get('consecutive_road_games')
        if road_games is None:
            return self._no_qualify()

        try:
            road_games = int(road_games)
        except (TypeError, ValueError):
            return self._no_qualify()

        if road_games < self.MIN_CONSECUTIVE_ROAD:
            return self._no_qualify()

        # Confidence scales with trip length (more games = more fatigue)
        extra = road_games - self.MIN_CONSECUTIVE_ROAD
        confidence = min(self.CONFIDENCE_CAP, self.CONFIDENCE_BASE + extra * 0.05)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'consecutive_road_games': road_games,
                'status': 'shadow',
                'signal_mechanism': (
                    f'team on {road_games}-game road trip — cumulative travel fatigue '
                    'suppresses scoring (literature: JCSM 2021 −2.33 B2B+travel margin)'
                ),
            },
        )
