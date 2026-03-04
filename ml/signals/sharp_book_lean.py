"""Sharp book lean signal — direction based on sharp vs soft book line divergence.

Session 399: BQ validation across Dec 2025 — Mar 2026:
  - Sharp higher 1.5+: OVER 70.3% HR (N=508), UNDER 50.4% (N=1486)
  - Soft higher 1.5+: OVER 41.0% (N=134), UNDER 84.7% (N=202)

Sharp books (FanDuel, DraftKings) move first and set efficient lines.
Soft books (BetRivers, Bovada, Fliff) lag behind. When sharp books set
a higher line than soft books, they expect more scoring → OVER signal.
When soft books have a higher line, the sharp market has corrected down
but soft hasn't followed → UNDER signal.

The signal is computed from the supplemental data query which pulls
the latest per-book lines from odds_api_player_points_props.
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


SHARP_BOOKS = frozenset({'fanduel', 'draftkings'})
SOFT_BOOKS = frozenset({'betrivers', 'bovada', 'fliff'})


class SharpBookLeanOverSignal(BaseSignal):
    """OVER signal when sharp books have higher line than soft books.

    Sharp books set the line 1.5+ higher than soft books → the efficient
    market expects more scoring. 70.3% HR on OVER (N=508).
    """

    tag = "sharp_book_lean_over"
    description = "Sharp books (FD/DK) line 1.5+ higher than soft books — OVER 70.3% HR"

    CONFIDENCE = 0.80
    MIN_LEAN = 1.5  # sharp_line - soft_line threshold

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        sharp_lean = prediction.get('sharp_book_lean')
        if sharp_lean is None:
            return self._no_qualify()

        if sharp_lean < self.MIN_LEAN:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'sharp_lean': round(sharp_lean, 2),
                'backtest_hr': 70.3,
                'backtest_n': 508,
            }
        )


class SharpBookLeanUnderSignal(BaseSignal):
    """UNDER signal when soft books have higher line than sharp books.

    Soft books set the line 1.5+ higher than sharp books → the efficient
    market has corrected down but soft hasn't followed. 84.7% HR on UNDER (N=202).
    """

    tag = "sharp_book_lean_under"
    description = "Soft books line 1.5+ higher than sharp (FD/DK) — UNDER 84.7% HR"

    CONFIDENCE = 0.85
    MIN_LEAN = 1.5  # soft_line - sharp_line threshold (stored as negative sharp_lean)

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        sharp_lean = prediction.get('sharp_book_lean')
        if sharp_lean is None:
            return self._no_qualify()

        # sharp_lean is sharp - soft. Negative means soft is higher.
        if sharp_lean > -self.MIN_LEAN:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'sharp_lean': round(sharp_lean, 2),
                'soft_lean': round(-sharp_lean, 2),
                'backtest_hr': 84.7,
                'backtest_n': 202,
            }
        )
