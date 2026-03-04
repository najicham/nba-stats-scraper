"""Denver altitude OVER signal for visiting players.

Session 398: BQ validation showed visiting players at Denver score OVER
at 67.8% HR (N=118, edge 3+) vs 58.9% baseline — +8.9pp above baseline.

Academic research (25,016 NBA games) confirms altitude effect: thin air
at 5,280 ft reduces oxygen availability, increasing pace and scoring.
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class DenverVisitorOverSignal(BaseSignal):
    """OVER signal for visiting players at Denver.

    Altitude at Mile High creates a measurable scoring boost for visitors.
    67.8% HR on edge 3+ predictions (N=118, Nov 2025 — Mar 2026).
    """

    tag = "denver_visitor_over"
    description = "Visiting player at Denver (altitude effect) OVER — 67.8% HR"

    CONFIDENCE = 0.78

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        # Must be an away player
        if prediction.get('is_home'):
            return self._no_qualify()

        # Opponent must be Denver (visiting AT Denver)
        opponent = prediction.get('opponent_team_abbr', '')
        if opponent != 'DEN':
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'opponent': 'DEN',
                'altitude_ft': 5280,
                'backtest_hr': 67.8,
                'backtest_n': 118,
            }
        )
