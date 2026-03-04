"""Minutes projection signal — RotoWire projected minutes vs season average.

If RotoWire projects more minutes than a player's season average, that's
independent confirmation of scoring upside. Our model uses historical minutes
averages but doesn't know about tonight's lineup situation (e.g., a teammate
is out, so this player will see extra minutes).

Signal:
- minutes_surge_over: RotoWire projected_minutes >= season_avg + 3

Created: Session 404.
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult

# Player must be projected at least this many minutes above season avg
MINUTES_SURGE_THRESHOLD = 3.0


class MinutesSurgeOverSignal(BaseSignal):
    """Minutes surge OVER: RotoWire projects 3+ more minutes than season avg."""

    tag = 'minutes_surge_over'
    description = (
        'RotoWire projects significantly more minutes than season average, '
        'suggesting lineup-driven scoring upside (e.g., teammate injury).'
    )

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        delta = prediction.get('minutes_projection_delta')
        if delta is None:
            return self._no_qualify()

        if delta >= MINUTES_SURGE_THRESHOLD:
            return SignalResult(
                qualifies=True,
                confidence=0.70,
                source_tag=self.tag,
                metadata={
                    'projected_minutes': prediction.get('rotowire_projected_minutes'),
                    'season_avg_minutes': prediction.get('rotowire_projected_minutes', 0) - delta,
                    'minutes_delta': round(delta, 1),
                },
            )

        return self._no_qualify()
