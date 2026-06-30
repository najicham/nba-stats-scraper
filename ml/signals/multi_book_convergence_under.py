"""Multi-Book Convergence Under — 3+ distinct bookmakers all independently lowered their
prop line today, and net convergence is downward (more lowering books than raising books).

Why coordinated downward movement is a signal:
  - `books_converging_down` = count of distinct bookmakers that lowered their prop line
    intraday (comparing first snapshot to last snapshot), requiring at least 2 snapshots
    per book (must have moved, not just opened).
  - `books_converging_up` = count that raised the line.
  - When 3+ independent books all lower the same player's line on the same day, and
    more are lowering than raising, the market is converging collectively toward UNDER
    value. Books don't coordinate — this is independent signal aggregation.
  - Mechanism: sharp action hits one book, the line moves. Sharps shop to the next book;
    it also moves. When 3+ books chain-react in the same direction, the signal is
    durable. The "net downward" gate (down > up) filters for clean convergence rather
    than noisy mixed movement.
  - Books that lower a line are effectively saying: the true expected value is lower than
    where they opened. An UNDER bet on a lowered line is betting WITH the market's
    revised view.

How books_converging_down / books_converging_up are sourced:
  Populated from intraday `odds_api_player_points_props` snapshots. The CLV pipeline
  (Phase 4:30 PM ET re-export) computes per-book first-vs-last comparisons and sets
  these fields on the prediction dict at export time. snap_count >= 2 per book is
  required (books that posted only one snapshot cannot be said to have "moved").

This is DISTINCT from:
  - `line_drifted_down_under` — uses only DraftKings line movement (single book).
  - `book_disagreement` — measures standard deviation of lines across books (spread,
    not movement direction). A high-std snapshot is different from coordinated movement.
  - `sharp_line_drop_under` — an older single-book drop signal.

Status: SHADOW (registered + tracked, EXCLUDED from real_sc → zero pick impact).
Promote to UNDER_SIGNAL_WEIGHTS after live 2026-27 confirms N>=30 BB-level picks at HR>=58%.
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class MultiBookConvergenceUnderSignal(BaseSignal):
    tag = "multi_book_convergence_under"
    description = (
        "Multi-book convergence UNDER — 3+ independent bookmakers all lowered their line "
        "today (net downward), coordinated intraday signal of UNDER value (shadow)"
    )

    MIN_BOOKS_CONVERGING_DOWN = 3
    CONFIDENCE_BASE = 0.60
    CONFIDENCE_PER_EXTRA_BOOK = 0.03
    CONFIDENCE_CAP = 0.72

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Direction gate: UNDER only
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # books_converging_down must be present and meet threshold
        books_down = prediction.get('books_converging_down')
        if books_down is None:
            return self._no_qualify()

        try:
            books_down = int(books_down)
        except (TypeError, ValueError):
            return self._no_qualify()

        if books_down < self.MIN_BOOKS_CONVERGING_DOWN:
            return self._no_qualify()

        # books_converging_up — net convergence must be downward
        books_up = prediction.get('books_converging_up') or 0
        try:
            books_up = int(books_up)
        except (TypeError, ValueError):
            books_up = 0

        if books_down <= books_up:
            return self._no_qualify()

        # Confidence scales with extra books above the threshold
        extra = books_down - self.MIN_BOOKS_CONVERGING_DOWN
        confidence = min(self.CONFIDENCE_CAP,
                         self.CONFIDENCE_BASE + extra * self.CONFIDENCE_PER_EXTRA_BOOK)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'books_converging_down': books_down,
                'books_converging_up': books_up,
                'net_convergence': books_down - books_up,
                'status': 'shadow',
                'signal_mechanism': (
                    f'{books_down} books independently lowered this line today vs. '
                    f'{books_up} raising — coordinated intraday convergence toward UNDER'
                ),
            },
        )
