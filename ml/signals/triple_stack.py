"""Triple Stack Signal — Meta-signal that activates when 3+ other signals qualify."""

from typing import Dict, Optional, List
from ml.signals.base_signal import BaseSignal, SignalResult


class TripleStackSignal(BaseSignal):
    tag = "triple_stack"
    description = "3+ signals qualify (exponential overlap effect)"

    MIN_SIGNALS = 3

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # This signal is evaluated differently - it counts other qualifying signals
        # In practice, this would be computed by the aggregator or backtest script
        # For now, return not qualified (will be handled by post-processing)

        return self._no_qualify()

        # NOTE: The aggregator/backtest will identify triple_stack picks by:
        # picks_with_3plus_signals = [p for p in predictions if len(p['qualifying_signals']) >= 3]
