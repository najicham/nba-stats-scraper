"""Tight Consensus Under — fires when 6+ distinct bookmakers post a prop line for this player.

Why high book count matters:
  - A large number of books posting a line means the market is liquid and well-established.
    Six or more distinct bookmakers implies strong consensus: the line has been set, shopped,
    and stress-tested across many operators.
  - In a tight-consensus market the LINE itself is efficient and reliable — books have competed
    toward a shared price. This is distinct from the line being wrong; it means the reference
    price is firm rather than stale or soft.
  - Our model edge is MORE reliable in tight-consensus markets because we are comparing the
    model's predicted output against a firm, battle-tested price rather than a single book's
    initial (often soft) open. A +4-point edge vs. a firm 6-book consensus is a more durable
    edge than a +4-point edge vs. a single book's cold open.
  - Mechanism: books in consensus have already absorbed sharp action; a model disagreement
    persisting across 6+ books is therefore more likely to reflect a real structural gap
    than a soft-line artifact.

5-season hypothesis:
  Cannot backtest directly — `book_count_current` was not stored in the historical feature
  store. This signal is forward-looking: shadow accumulation starting 2026-27.

Status: SHADOW (registered + tracked, EXCLUDED from real_sc → zero pick impact).
Promote to UNDER_SIGNAL_WEIGHTS after live 2026-27 confirms N>=30 BB-level picks at HR>=58%.
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class TightConsensusUnderSignal(BaseSignal):
    tag = "tight_consensus_under"
    description = (
        "Tight market consensus UNDER — 6+ bookmakers posting the same line means "
        "model edge is more reliable against a firm price (shadow)"
    )

    MIN_BOOKS = 6
    CONFIDENCE_BASE = 0.58
    CONFIDENCE_PER_EXTRA_BOOK = 0.01
    CONFIDENCE_CAP = 0.63

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Direction gate: UNDER only
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Book count must be present and meet threshold
        book_count = prediction.get('book_count_current')
        if book_count is None:
            return self._no_qualify()

        try:
            book_count = int(book_count)
        except (TypeError, ValueError):
            return self._no_qualify()

        if book_count < self.MIN_BOOKS:
            return self._no_qualify()

        # Confidence scales with extra books above threshold
        extra = book_count - self.MIN_BOOKS
        confidence = min(self.CONFIDENCE_CAP,
                         self.CONFIDENCE_BASE + extra * self.CONFIDENCE_PER_EXTRA_BOOK)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'book_count_current': book_count,
                'books_above_threshold': extra,
                'status': 'shadow',
                'signal_mechanism': (
                    f'{book_count} books posting this line — tight consensus means model '
                    'edge is calibrated against a firm, stress-tested price'
                ),
            },
        )
