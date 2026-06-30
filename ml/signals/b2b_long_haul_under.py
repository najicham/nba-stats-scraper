"""B2B Long-Haul Under — back-to-back game PLUS long-distance travel (>=1000 miles).

Why the combination is more impactful than either factor alone:
  - `b2b_fatigue_under` is already validated at 63.2% HR over 5 seasons (BH-FDR p=0.0035).
    That covers ALL back-to-back UNDER picks, regardless of travel.
  - Long-haul travel (>=1000 miles) adds a compounding stressor: disrupted sleep on the
    road, time-zone shift, reduced recovery time, and no home environment. When a player
    is already playing on 1 rest day AND flew 1000+ miles the night before, the fatigue
    stack is materially higher than a short bus-hop b2b.
  - JCSM 2021: B2B + travel produces −2.33 team margin vs. +0.6 for non-travel b2b.
    The marginal effect of distance is monotonic above ~500 miles (cross-country amplifies
    further).
  - At 2000+ miles (true cross-country, e.g. BOS→LAL or MIA→GSW), the time-zone penalty
    compounds the physical fatigue — sleep onset is delayed, cortisol rhythm misaligned.

How away_travel_miles is sourced:
  Populated from `nba_static.travel_distances` (column: `distance_miles`) on away-team
  players by supplemental_data.py. Value is the great-circle distance in miles between
  the previous game's city and tonight's arena city.

This is DISTINCT from:
  - `b2b_fatigue_under` — all b2b UNDER (regardless of distance). This signal is the
    high-travel subset, expected to be stronger but lower volume.
  - `long_road_trip_under` — 3+ consecutive road games regardless of b2b or distance.
  - `westward_road_trip_under` — westward direction regardless of b2b or mileage.

rest_days lookup pattern: read from prediction dict first, fall back to
supplemental['rest_stats']['rest_days'] — same as b2b_fatigue_under.

Status: SHADOW (registered + tracked, EXCLUDED from real_sc → zero pick impact).
Promote to UNDER_SIGNAL_WEIGHTS after live 2026-27 confirms N>=30 BB-level picks at HR>=62%.
Higher threshold than b2b_fatigue_under (62% vs 58%) because the N will be lower and
the backtest parent (b2b) is 63.2% — the long-haul subset should beat that floor.

Sources:
  - Literature: JCSM 2021 — B2B + travel: −2.33 team margin vs. +0.6 non-travel b2b.
  - Parent signal `b2b_fatigue_under`: 63.2% HR, 5/5 seasons above breakeven (p=0.0035).
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class B2BLongHaulUnderSignal(BaseSignal):
    tag = "b2b_long_haul_under"
    description = (
        "B2B long-haul UNDER — back-to-back game with 1000+ miles of travel compounds "
        "fatigue beyond the already-validated b2b UNDER effect (shadow)"
    )

    MIN_TRAVEL_MILES = 1000
    CROSS_COUNTRY_MILES = 2000
    CONFIDENCE_BASE = 0.65
    CONFIDENCE_CAP = 0.75

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

        # Must be back-to-back (1 rest day)
        rest_days = prediction.get('rest_days')
        if rest_days is None and supplemental:
            rest_days = (supplemental.get('rest_stats') or {}).get('rest_days')
        if rest_days is None or rest_days != 1:
            return self._no_qualify()

        # Must have traveled long-haul
        travel_miles = prediction.get('away_travel_miles')
        if travel_miles is None:
            return self._no_qualify()

        try:
            travel_miles = float(travel_miles)
        except (TypeError, ValueError):
            return self._no_qualify()

        if travel_miles < self.MIN_TRAVEL_MILES:
            return self._no_qualify()

        # Confidence scales with distance above threshold (cross-country amplifies)
        # Formula: 0.65 + (miles - 1000) / 10000, capped at 0.75
        confidence = min(self.CONFIDENCE_CAP,
                         self.CONFIDENCE_BASE + (travel_miles - self.MIN_TRAVEL_MILES) / 10000.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'rest_days': 1,
                'away_travel_miles': round(travel_miles, 0),
                'is_cross_country': travel_miles >= self.CROSS_COUNTRY_MILES,
                'status': 'shadow',
                'signal_mechanism': (
                    f'b2b ({int(travel_miles)}-mile travel) — compounded fatigue from '
                    'consecutive games + long-haul flight (JCSM 2021: −2.33 margin vs. '
                    'non-travel b2b); parent signal b2b_fatigue_under = 63.2% 5-season'
                ),
            },
        )
