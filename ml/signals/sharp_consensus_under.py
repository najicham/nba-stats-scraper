"""Sharp consensus UNDER signal — line dropped + high book disagreement.

When the BettingPros line has dropped >= 0.5 points AND cross-book standard
deviation is sufficiently high, sharp money is pushing the line down while
soft books haven't fully adjusted. UNDER is profitable in this scenario.

5-season cross-validated (2021-22 through 2024-25, Odds API 4-5 books):
  - 69.3% HR (N=205), consistent all 5 seasons (64-73% per season)
  - Edge 3+: 74.3% HR (N=35)

BOOK-COUNT SCALING (Session 515/522):
  The 5-season backtest used Odds API data with 4-5 books per market. In that
  regime, std >= 1.0 is a meaningful signal. With BettingPros (12+ books),
  std distributions are fundamentally different — std >= 1.0 is noise (0-14 BB
  record in 2025-26). Thresholds scale by book count:
  - 4-6 books (Odds API): std >= 1.0 (original calibration)
  - 7-11 books: std >= 1.5 (transition regime)
  - 12+ books (BettingPros): std >= 2.0 (fully recalibrated)
  Falls back to std >= 1.5 when book_count is unknown.

Currently in SHADOW_SIGNALS. Graduate when live N >= 30 at BB level with HR >= 60%.

Created: Session 463 (sharp book disaggregation experiment)
Updated: Session 522 (book-count-aware threshold scaling)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class SharpConsensusUnderSignal(BaseSignal):
    tag = "sharp_consensus_under"
    description = "Sharp consensus UNDER — line dropped 0.5+ with book-count-scaled disagreement"

    # Minimum line drop to qualify (negative = line went down)
    MIN_LINE_DROP = 0.5
    CONFIDENCE_BASE = 0.85

    def _get_min_std(self, book_count: Optional[int]) -> float:
        """Return minimum std threshold scaled by book count.

        More books → higher std needed for meaningful disagreement.
        Thresholds calibrated: 4-5 books = 1.0 (Odds API backtest),
        12+ books = 2.0 (BettingPros 2025-26 regime).
        """
        if book_count is None:
            return 1.5  # Conservative unknown default
        if book_count >= 12:
            return 2.0
        if book_count >= 7:
            return 1.5
        return 1.0  # 4-6 books: original Odds API calibration

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Direction gate: UNDER only
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Need BettingPros line movement and cross-book std
        bp_move = prediction.get('bp_line_movement')
        bp_std = prediction.get('multi_book_line_std')

        if bp_move is None or bp_std is None:
            return self._no_qualify()

        # Core logic: line must have dropped AND books must disagree
        # bp_line_movement < 0 means line dropped (bearish)
        if bp_move > -self.MIN_LINE_DROP:
            return self._no_qualify()

        # Book-count-aware threshold (Session 522)
        book_count = None
        if supplemental:
            book_stats = supplemental.get('book_stats') or {}
            book_count = book_stats.get('book_count')
        if book_count is None:
            book_count = prediction.get('book_count')

        min_std = self._get_min_std(book_count)
        if bp_std < min_std:
            return self._no_qualify()

        # Confidence scales with disagreement magnitude above threshold
        confidence = min(0.95, self.CONFIDENCE_BASE + (bp_std - min_std) * 0.1)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'bp_line_movement': round(bp_move, 2),
                'multi_book_line_std': round(bp_std, 2),
                'book_count': book_count,
                'min_std_threshold': min_std,
                'backtest_hr': 69.3,
                'backtest_n': 205,
            },
        )
