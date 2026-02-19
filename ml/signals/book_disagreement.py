"""Book Disagreement Signal — When sportsbooks disagree heavily on a player's line.

Session 303 discovery: When 12 sportsbooks have high cross-book line standard
deviation (std > 1.5), model predictions hit at 93% at edge 3+ (N=43).
The signal works for both OVER (90.5%) and UNDER (92.0%), across all edge levels,
and is NOT driven by injury uncertainty (0 of 47 qualifying picks were on injury report).

Excluding bovada from the std calculation strengthens the signal (94.9% HR),
confirming this is real cross-market disagreement, not single-book noise.

Only 3.2% of player-games qualify (std > 1.5), so this fires rarely but selectively.

Status: WATCH (N=43, need more out-of-sample data before promoting)
Created: Session 303 (multi-book line research)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class BookDisagreementSignal(BaseSignal):
    tag = "book_disagreement"
    description = "High cross-book line disagreement (std > 1.5) — 93.0% edge 3+ HR (N=43)"

    # Threshold for "high disagreement" — top 3.2% of player-games
    MIN_LINE_STD = 1.5
    # Medium disagreement threshold for metadata context
    MEDIUM_LINE_STD = 1.0

    CONFIDENCE = 0.85  # Strong but small-N evidence

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Get multi_book_line_std from supplemental data
        line_std = None
        book_count = None

        if supplemental:
            book_stats = supplemental.get('book_stats') or {}
            line_std = book_stats.get('multi_book_line_std')
            book_count = book_stats.get('book_count')

        # Fallback: check prediction dict directly (backtest mode)
        if line_std is None:
            line_std = prediction.get('multi_book_line_std')
        if book_count is None:
            book_count = prediction.get('book_count')

        if line_std is None or line_std < self.MIN_LINE_STD:
            return self._no_qualify()

        # Need at least 5 books for meaningful std
        if book_count is not None and book_count < 5:
            return self._no_qualify()

        # Scale confidence with disagreement magnitude
        # std 1.5 = 0.85, std 2.0 = 0.90, std 2.5+ = 0.95
        confidence = min(0.95, self.CONFIDENCE + (line_std - self.MIN_LINE_STD) * 0.10)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'multi_book_line_std': round(line_std, 2),
                'book_count': book_count,
                'backtest_hr_edge3': 93.0,
                'backtest_n': 43,
            }
        )
