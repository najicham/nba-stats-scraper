"""Westward Road Trip Under — away team traveling WESTWARD shows greater fatigue than
eastward travel, suppressing player scoring.

Why direction matters:
  - Westward travel means the body clock runs AHEAD of local tip-off time. A player who
    flew from New York to Los Angeles arrives with their circadian clock still set 3 hours
    later — their body believes it is midnight when the game tips at 9 PM local. This
    mismatch suppresses alertness, reaction time, and sustained output.
  - Eastward travel is physiologically EASIER for evening games: the body clock runs
    BEHIND local time, meaning the player's internal alarm fires earlier than the game
    starts — they feel primed rather than dragged.
  - JCSM 2021 (Journal of Clinical Sleep Medicine): westward-traveling teams show greater
    fatigue and larger performance declines than eastward-traveling teams. The B2B +
    westward combination produces a −2.33 team margin vs. +0.6 without travel.

How travel_direction is sourced:
  `away_travel_direction` is populated via `nba_static.travel_distances` table
  (column `travel_direction`, values: 'west' / 'east' / 'neutral'). Set on away-team
  players by supplemental_data.py. `away_travel_tz_crossed` counts integer time zones
  crossed (0–3 for continental US games).

This is DISTINCT from:
  - `long_road_trip_under` — fires on 3+ consecutive road games regardless of direction
  - `b2b_fatigue_under` — fires on rest_days==1 regardless of travel
  The westward signal fires on a single away game if direction is westward; it stacks
  additively with b2b_fatigue_under when both apply.

Status: SHADOW (registered + tracked, EXCLUDED from real_sc → zero pick impact).
Promote to UNDER_SIGNAL_WEIGHTS after live 2026-27 confirms N>=30 BB-level picks at HR>=58%.

Sources:
  - Literature: JCSM 2021 — westward travel teams: greater fatigue + larger performance
    decline than eastward; −2.33 team margin in B2B+travel scenarios.
  - Circadian mechanism: westward crossing delays body-clock reset vs. local time for
    evening tip-offs; eastward crossing accelerates it (favourable for night games).
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class WestwardRoadTripUnderSignal(BaseSignal):
    tag = "westward_road_trip_under"
    description = (
        "Westward road trip UNDER — away team traveling west crosses time zones in the "
        "harder direction (body clock runs ahead), suppressing scoring (shadow)"
    )

    CONFIDENCE_BASE = 0.60
    CONFIDENCE_CAP = 0.70
    TZ_THRESHOLD_FOR_BOOST = 2

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Direction gate: UNDER only
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Must be the away (traveling) team
        is_home = prediction.get('is_home')
        if is_home is None or bool(is_home):
            return self._no_qualify()

        # Must be traveling westward
        travel_direction = prediction.get('away_travel_direction')
        if travel_direction != 'west':
            return self._no_qualify()

        # Confidence scales with time zones crossed (more zones = harder disruption)
        confidence = self.CONFIDENCE_BASE
        tz_crossed = prediction.get('away_travel_tz_crossed')
        if tz_crossed is not None:
            try:
                tz_crossed = int(tz_crossed)
                if tz_crossed >= self.TZ_THRESHOLD_FOR_BOOST:
                    # Scale from 0.60 → up to 0.70 based on zones crossed (cap at 3)
                    extra_zones = min(tz_crossed - self.TZ_THRESHOLD_FOR_BOOST + 1, 2)
                    confidence = min(self.CONFIDENCE_CAP,
                                     self.CONFIDENCE_BASE + extra_zones * 0.05)
            except (TypeError, ValueError):
                tz_crossed = None

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'away_travel_direction': 'west',
                'away_travel_tz_crossed': tz_crossed,
                'status': 'shadow',
                'signal_mechanism': (
                    'westward travel — body clock runs ahead of local tip-off time '
                    '(JCSM 2021: greater fatigue + performance decline vs. eastward)'
                ),
            },
        )
