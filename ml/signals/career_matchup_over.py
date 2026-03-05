"""Career Matchup Over Signal — OVER when player historically dominates opponent.

When a player's career average vs a specific opponent exceeds the current
line AND they've faced them 3+ times, the matchup history favors OVER.

Data sources:
- feature_29_value (avg_pts_vs_opponent): range 0-51, median 8.4
- feature_30_value (games_vs_opponent): range 0-10, median 2.0

Created: Session 411
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class CareerMatchupOverSignal(BaseSignal):
    tag = "career_matchup_over"
    description = "Career avg vs opponent > line (3+ games) OVER — matchup dominator"

    MIN_GAMES_VS_OPP = 3  # Need decent sample size
    CONFIDENCE_BASE = 0.75

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line <= 0:
            return self._no_qualify()

        avg_vs_opp = prediction.get('avg_pts_vs_opp') or 0
        games_vs_opp = prediction.get('games_vs_opp') or 0

        if games_vs_opp < self.MIN_GAMES_VS_OPP:
            return self._no_qualify()

        if avg_vs_opp <= line:
            return self._no_qualify()

        margin = avg_vs_opp - line
        # Scale confidence: 0pt margin → 0.75, 5+ pt margin → 0.85
        confidence = min(0.90, self.CONFIDENCE_BASE + margin / 50.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'avg_pts_vs_opp': round(avg_vs_opp, 1),
                'games_vs_opp': int(games_vs_opp),
                'line_value': round(line, 1),
                'margin_over_line': round(margin, 1),
            }
        )
