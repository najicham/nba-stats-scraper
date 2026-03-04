"""Closing Line Value (CLV) signal — market alignment with line movement.

Session 401: CLV is the single best predictor of long-term betting profitability
per market research (Pinnacle: 1.5% edge for opening-line bets).

Uses a second Odds API snapshot (evening ~6 PM ET, in addition to morning run)
to compute CLV = opening_line - closing_line per player. When our prediction
direction aligns with how the line moved (market agrees), expected HR improves.

Signals:
  - positive_clv_over: Line dropped (books moved toward UNDER) but model says
    OVER → we had positive CLV → expected HR 60-65%
  - negative_clv_filter: Line moved AGAINST our prediction direction → filter

Note: CLV is available for grading PREVIOUS day's picks. The market_aligned
signal uses historical CLV-direction agreement to boost same-direction picks.
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class PositiveCLVOverSignal(BaseSignal):
    """OVER signal when closing line moved in our favor (line dropped).

    When the line drops from opening to closing (books expect lower scoring)
    but our model still projects OVER, we captured positive CLV. The market
    moved toward UNDER after opening, making our OVER bet more valuable.
    """

    tag = "positive_clv_over"
    description = "Line dropped (positive CLV) + model OVER — market alignment signal"

    CONFIDENCE = 0.70
    MIN_LINE_DROP = 0.5  # Minimum line movement to consider significant

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        clv = prediction.get('closing_line_value')
        if clv is None:
            return self._no_qualify()

        # Positive CLV for OVER: opening line was higher than closing line
        # (line dropped → market moved toward UNDER → our OVER has value)
        if clv < self.MIN_LINE_DROP:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'clv': round(clv, 2),
                'opening_line': prediction.get('opening_line'),
                'closing_line': prediction.get('closing_line'),
            }
        )


class PositiveCLVUnderSignal(BaseSignal):
    """UNDER signal when closing line moved in our favor (line rose).

    When the line rises from opening to closing (books expect higher scoring)
    but our model still projects UNDER, we captured positive CLV.
    """

    tag = "positive_clv_under"
    description = "Line rose (positive CLV) + model UNDER — market alignment signal"

    CONFIDENCE = 0.70
    MIN_LINE_RISE = 0.5

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        clv = prediction.get('closing_line_value')
        if clv is None:
            return self._no_qualify()

        # Positive CLV for UNDER: closing line higher than opening
        # (line rose → market moved toward OVER → our UNDER has value)
        if clv > -self.MIN_LINE_RISE:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'clv': round(clv, 2),
                'opening_line': prediction.get('opening_line'),
                'closing_line': prediction.get('closing_line'),
            }
        )


class NegativeCLVFilter(BaseSignal):
    """Negative filter: line moved AGAINST our prediction direction.

    When the market strongly disagrees with our direction (line moved 1+
    against us), the bet is more likely to lose.
    """

    tag = "negative_clv_filter"
    description = "Line moved against prediction direction — negative CLV filter"

    CONFIDENCE = 0.60
    MIN_ADVERSE_MOVE = 1.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        clv = prediction.get('closing_line_value')
        if clv is None:
            return self._no_qualify()

        recommendation = prediction.get('recommendation')

        # For OVER: negative CLV means line rose (market expects more scoring)
        # → our OVER was "priced in" by market movement
        if recommendation == 'OVER' and clv < -self.MIN_ADVERSE_MOVE:
            return SignalResult(
                qualifies=True,
                confidence=self.CONFIDENCE,
                source_tag=self.tag,
                metadata={
                    'clv': round(clv, 2),
                    'direction': 'OVER',
                    'adverse_move': round(-clv, 2),
                }
            )

        # For UNDER: positive CLV (line dropped) means market expects less scoring
        # → our UNDER was "priced in"
        if recommendation == 'UNDER' and clv > self.MIN_ADVERSE_MOVE:
            return SignalResult(
                qualifies=True,
                confidence=self.CONFIDENCE,
                source_tag=self.tag,
                metadata={
                    'clv': round(clv, 2),
                    'direction': 'UNDER',
                    'adverse_move': round(clv, 2),
                }
            )

        return self._no_qualify()
