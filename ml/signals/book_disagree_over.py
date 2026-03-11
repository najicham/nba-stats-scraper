"""Book Disagree OVER Signal — high cross-book disagreement on OVER picks.

Discovery found direction-specific book_disagreement is much stronger
for OVER than the direction-neutral version:
  - book_disagree_over: 79.6% HR (N=211, 5-season cross-validated)
  - Direction-neutral: 93.0% HR but N=43 (inflated by small sample)

When sportsbooks heavily disagree AND the model says OVER, the line
uncertainty creates exploitable OVER opportunities.

Created: Session 469 (direction-specific split from book_disagreement)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class BookDisagreeOverSignal(BaseSignal):
    tag = "book_disagree_over"
    description = "High cross-book disagreement on OVER — 79.6% HR (N=211, 5-season)"

    MIN_LINE_STD = 1.5
    CONFIDENCE = 0.85

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Direction gate: OVER only
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        line_std = None
        book_count = None

        if supplemental:
            book_stats = supplemental.get('book_stats') or {}
            line_std = book_stats.get('multi_book_line_std')
            book_count = book_stats.get('book_count')

        if line_std is None:
            line_std = prediction.get('multi_book_line_std')
        if book_count is None:
            book_count = prediction.get('book_count')

        if line_std is None or line_std < self.MIN_LINE_STD:
            return self._no_qualify()

        if book_count is not None and book_count < 5:
            return self._no_qualify()

        confidence = min(0.95, self.CONFIDENCE + (line_std - self.MIN_LINE_STD) * 0.10)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'multi_book_line_std': round(line_std, 2),
                'book_count': book_count,
                'backtest_hr': 79.6,
                'backtest_n': 211,
            }
        )
