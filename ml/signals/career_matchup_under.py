"""Career Matchup UNDER signal — player historically underperforms vs this opponent (3yr).

Companion to career_matchup_over (Session 411). Uses a 3-year lookback window
via a separate supplemental query (matchup_3yr_map), bypassing the feature store's
1-year cap (Session 143 performance tradeoff).

Why 3-year vs 1-year: a 1-year window yields only 2-4 games per player-team matchup,
which is insufficient for statistical reliability. A 3-year window yields 6-12 games
for established players, capturing scheme and positional matchup continuity (e.g.,
a lockdown defender who consistently guards this scorer is likely still on that team).

Threshold: career_avg_vs_opp_3yr < current_line by >= 2.0 pts.
The shortfall must be meaningful — small gaps (< 2 pts) are within normal variance.

Data source: supplemental['career_matchup_3yr'] — populated by matchup_3yr_map
in supplemental_data.py. Keys: 'career_avg_vs_opp_3yr', 'career_games_vs_opp_3yr'.
Requires >= 3 career games vs opponent in 3-year window.

NOTE: career_matchup_over has 0% BB HR (N=1) — insufficient to validate direction.
Both signals are fresh hypotheses in shadow. Do not promote until N>=30 at HR>=60%.

Created: 2026-07-01
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class CareerMatchupUnderSignal(BaseSignal):
    tag = "career_matchup_under"
    description = (
        "Career avg vs opponent (3yr) < current line by 2+ pts — matchup suppressor UNDER "
        "(shadow; companion to career_matchup_over)"
    )

    MIN_GAMES_VS_OPP = 3
    MARGIN_THRESHOLD = 2.0
    CONFIDENCE_BASE = 0.62

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        line = float(prediction.get('line_value') or prediction.get('current_points_line') or 0)
        if line <= 0:
            return self._no_qualify()

        matchup_3yr = (supplemental or {}).get('career_matchup_3yr') or {}
        career_avg = matchup_3yr.get('career_avg_vs_opp_3yr')
        career_games = int(matchup_3yr.get('career_games_vs_opp_3yr') or 0)

        if career_avg is None or career_games < self.MIN_GAMES_VS_OPP:
            return self._no_qualify()

        shortfall = line - float(career_avg)
        if shortfall < self.MARGIN_THRESHOLD:
            return self._no_qualify()

        confidence = min(0.80, self.CONFIDENCE_BASE + shortfall / 50.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'career_avg_vs_opp_3yr': round(float(career_avg), 1),
                'career_games_vs_opp_3yr': career_games,
                'line_value': round(line, 1),
                'shortfall_below_line': round(shortfall, 1),
                'lookback_years': 3,
            },
        )
