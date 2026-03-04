"""Sharp money signals — VSiN handle vs ticket divergence.

When handle% (money) diverges from ticket% (bets), sharp bettors are on the
money side. This is the classic sharp money indicator in sports betting.

VSiN provides game-level total O/U splits:
- over_money_pct / under_money_pct = % of handle
- over_ticket_pct / under_ticket_pct = % of tickets

Signals:
- sharp_money_over: Handle heavily OVER while public tickets lean UNDER
- sharp_money_under: Handle heavily UNDER while public tickets lean OVER
- public_fade_filter: Public overwhelmingly on OVER (>=80% tickets) = negative signal

Created: Session 404.
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult

# Thresholds for sharp money divergence
SHARP_HANDLE_THRESHOLD = 65.0   # Handle % on one side
PUBLIC_TICKET_THRESHOLD = 45.0  # Ticket % on OPPOSITE side (i.e., public is fading)
PUBLIC_FADE_THRESHOLD = 80.0    # Extreme public one-sidedness


class SharpMoneyOverSignal(BaseSignal):
    """Sharp money on OVER: handle >= 65% OVER while tickets <= 45% OVER."""

    tag = 'sharp_money_over'
    description = (
        'Sharp money (handle) favors OVER while public (tickets) leans UNDER. '
        'Handle-ticket divergence is a classic sharp indicator.'
    )

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        over_money = prediction.get('vsin_over_money_pct')
        over_tickets = prediction.get('vsin_over_ticket_pct')

        if over_money is None or over_tickets is None:
            return self._no_qualify()

        if over_money >= SHARP_HANDLE_THRESHOLD and over_tickets <= PUBLIC_TICKET_THRESHOLD:
            return SignalResult(
                qualifies=True,
                confidence=0.75,
                source_tag=self.tag,
                metadata={
                    'over_money_pct': over_money,
                    'over_ticket_pct': over_tickets,
                    'divergence': round(over_money - over_tickets, 1),
                },
            )

        return self._no_qualify()


class SharpMoneyUnderSignal(BaseSignal):
    """Sharp money on UNDER: handle >= 65% UNDER while tickets <= 45% UNDER."""

    tag = 'sharp_money_under'
    description = (
        'Sharp money (handle) favors UNDER while public (tickets) leans OVER. '
        'Handle-ticket divergence is a classic sharp indicator.'
    )

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        under_money = prediction.get('vsin_under_money_pct')
        under_tickets = prediction.get('vsin_under_ticket_pct')

        if under_money is None or under_tickets is None:
            return self._no_qualify()

        if under_money >= SHARP_HANDLE_THRESHOLD and under_tickets <= PUBLIC_TICKET_THRESHOLD:
            return SignalResult(
                qualifies=True,
                confidence=0.75,
                source_tag=self.tag,
                metadata={
                    'under_money_pct': under_money,
                    'under_ticket_pct': under_tickets,
                    'divergence': round(under_money - under_tickets, 1),
                },
            )

        return self._no_qualify()


class PublicFadeFilter(BaseSignal):
    """Negative filter: extreme public consensus on OVER (>=80% tickets).

    When the public overwhelmingly backs OVER, fading the public is
    historically profitable in sports betting. This is a negative filter
    that flags picks where the model agrees with extreme public sentiment.
    """

    tag = 'public_fade_filter'
    description = (
        'Extreme public consensus (80%+ tickets) on OVER — contrarian '
        'indicator that the public side tends to lose.'
    )

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        over_tickets = prediction.get('vsin_over_ticket_pct')
        if over_tickets is None:
            return self._no_qualify()

        if over_tickets >= PUBLIC_FADE_THRESHOLD:
            return SignalResult(
                qualifies=True,
                confidence=0.60,
                source_tag=self.tag,
                metadata={
                    'over_ticket_pct': over_tickets,
                    'threshold': PUBLIC_FADE_THRESHOLD,
                },
            )

        return self._no_qualify()
