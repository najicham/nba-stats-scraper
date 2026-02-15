"""Home Dog Signal — Home underdog with high edge (narrative + market inefficiency)."""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class HomeDogSignal(BaseSignal):
    tag = "home_dog"
    description = "Home underdog + high edge (5+) → motivated performance"

    MIN_EDGE = 5.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Must have high edge
        edge = abs(prediction.get('edge', 0))
        if edge < self.MIN_EDGE:
            return self._no_qualify()

        # Must be home game
        is_home = prediction.get('is_home', False)
        if not is_home:
            return self._no_qualify()

        # Must be underdog (if we have spread data)
        is_underdog = prediction.get('is_underdog', None)

        # If we don't have underdog status, use edge + OVER as proxy
        # (home underdog players often get OVER picks due to motivation)
        if is_underdog is None:
            if prediction.get('recommendation') != 'OVER':
                return self._no_qualify()
            base_confidence = 0.65  # Lower confidence without spread data
        else:
            if not is_underdog:
                return self._no_qualify()
            base_confidence = 0.75

        # Boost for extreme edge (market really disagrees)
        if edge >= 8.0:
            base_confidence = min(1.0, base_confidence + 0.1)

        return SignalResult(
            qualifies=True,
            confidence=base_confidence,
            source_tag=self.tag,
            metadata={
                'edge': round(edge, 2),
                'is_home': True,
                'is_underdog': is_underdog
            }
        )
