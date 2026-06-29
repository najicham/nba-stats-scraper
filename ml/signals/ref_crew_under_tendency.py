"""Referee crew UNDER tendency signal — crew's historical O/U record leans UNDER.

BACKGROUND:
Game referees influence game pace and foul-calling patterns in ways that correlate with
whether games and individual player totals go OVER or UNDER. When a referee crew's
historical games have gone UNDER more often than OVER (avg over_percentage < 48%), it
signals that this crew's calling patterns favor UNDER outcomes on player props.

DATA SOURCES:
  - `nba_raw.nbac_referee_game_pivot` — one row per game: chief_referee, crew_referee_1,
    crew_referee_2 (from nbac_referee_game_assignments scraper).
  - `nba_raw.covers_referee_stats` — per-referee O/U record: referee_name, over_record,
    under_record, over_percentage.

DATA AVAILABILITY:
  ⚠️  covers_referee_stats was broken before 2026-27 season and will accumulate data from
  2026-27 onward. This signal will fire rarely until sufficient historical data is available.
  The signal gracefully returns _no_qualify() when crew data is unavailable.
  Requires at least 2 of 3 crew members to have Covers data (`crew_under_data_available`).

JOINING STRATEGY:
  Predictions use game_id format YYYYMMDD_AWAY_HOME. The referee pivot uses NBA.com 10-digit
  game_id (e.g. 0012400123). Join via game_date + home_team_abbr + away_team_abbr instead.
  Lookup is keyed by (away_team_abbr, home_team_abbr) — the same pattern as vsin_map and
  schedule_tv_map in supplemental_data.py.

THRESHOLD:
  crew_avg_over_pct < 0.48 (below 48% OVER → more UNDER games historically). Chosen
  conservatively: the breakeven for NBA player props is ~52.4% after vig, and a crew at
  <48% OVER implies their calling patterns meaningfully favor UNDER outcomes.

STATUS: SHADOW (zero pick impact — excluded from real_sc via SHADOW_SIGNALS, NOT in
UNDER_SIGNAL_WEIGHTS). Promote at 2026-27 season close after live N>=30 at HR>=58%.
Pre-requisite: covers_referee_stats must accumulate 2+ seasons of data for reliable averages.

Detail: docs/09-handoff/2026-06-29-ref-crew-under-tendency.md
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class RefCrewUnderTendencySignal(BaseSignal):
    tag = "ref_crew_under_tendency"
    description = (
        "Referee crew UNDER tendency — crew avg O/U% < 48%, UNDER reversion "
        "(shadow, Covers data accumulates from 2026-27)"
    )

    # Threshold: crew avg over_pct below this → UNDER lean
    OVER_PCT_THRESHOLD = 0.48
    CONFIDENCE = 0.60   # conservative until multi-season validation available
    # Minimum number of crew members that must have Covers data
    MIN_CREW_DATA_MEMBERS = 2

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:
        # Direction gate: UNDER only
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Data availability gate — graceful degradation when Covers data is absent
        if not prediction.get('crew_under_data_available'):
            return self._no_qualify()

        crew_avg_over_pct = prediction.get('crew_avg_over_pct')
        if crew_avg_over_pct is None:
            return self._no_qualify()

        crew_avg_over_pct = float(crew_avg_over_pct)

        # UNDER tendency gate: crew has historically gone UNDER more than expected
        if crew_avg_over_pct >= self.OVER_PCT_THRESHOLD:
            return self._no_qualify()

        # Confidence scales with how far below the threshold (more extreme = stronger signal)
        gap = self.OVER_PCT_THRESHOLD - crew_avg_over_pct  # 0..0.48
        confidence = min(0.70, self.CONFIDENCE + gap * 0.5)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'crew_avg_over_pct': round(crew_avg_over_pct, 3),
                'crew_under_pct': round(1.0 - crew_avg_over_pct, 3),
                'threshold': self.OVER_PCT_THRESHOLD,
                'status': 'shadow',
                'data_source': 'covers_referee_stats',
                'data_note': 'Covers data accumulates from 2026-27 — low coverage initially',
            },
        )
