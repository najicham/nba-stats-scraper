"""Blowout Recovery signal — previous game minutes way below average, bounce back."""

from datetime import date
from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult
from shared.config.calendar_regime import detect_regime


class BlowoutRecoverySignal(BaseSignal):
    tag = "blowout_recovery"
    description = "Previous game minutes 6+ below season avg — bounce back, OVER"

    MIN_MINUTES_DEFICIT = 6.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        if not supplemental or 'recovery_stats' not in supplemental:
            return self._no_qualify()

        # Low minutes → bounce back → OVER
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        # Session 431: Suppress during toxic window (75%→33% collapse, -41.7pp)
        game_date = prediction.get('game_date')
        if game_date:
            if isinstance(game_date, str):
                game_date = date.fromisoformat(game_date)
            regime = detect_regime(game_date)
            if regime.is_toxic:
                return self._no_qualify()

        # Exclude Centers: 20.0% HR (Session 257)
        player_ctx = supplemental.get('player_context', {})
        pos = (player_ctx.get('position') or '').upper()
        if pos and 'C' in pos.split('-'):
            return self._no_qualify()

        # Exclude B2B: 46.2% HR (Session 257)
        rest_stats = supplemental.get('rest_stats', {})
        rest_days = rest_stats.get('rest_days')
        if rest_days is not None and rest_days < 2:
            return self._no_qualify()

        stats = supplemental['recovery_stats']
        prev_minutes = stats.get('prev_minutes')
        avg_minutes = stats.get('minutes_avg_season')

        if prev_minutes is None or avg_minutes is None:
            return self._no_qualify()

        deficit = avg_minutes - prev_minutes
        if deficit < self.MIN_MINUTES_DEFICIT:
            return self._no_qualify()

        # 6=0.0, 10=0.4, 16+=1.0
        confidence = min(1.0, deficit / 16.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'prev_minutes': round(prev_minutes, 1),
                'minutes_avg_season': round(avg_minutes, 1),
                'deficit': round(deficit, 1),
            },
        )
