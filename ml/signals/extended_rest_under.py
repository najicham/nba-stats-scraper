"""Extended Rest Under Signal — UNDER picks on players with 4+ days rest.

Players returning from extended rest (All-Star break, injury, scheduled rest)
tend to have predictable scoring patterns, making UNDER more reliable.

Distinct from rest_advantage_2d which requires opponent rest comparison
and only covers 2-day rest advantage in the OVER direction.

Backtest: 61.8% HR (N=76) overall, 87.5% in Feb (N=8).
Uses pred['rest_days'] from supplemental_data.py DATE_DIFF computation.

Created: Session 372
"""
from ml.signals.base_signal import BaseSignal, SignalResult


class ExtendedRestUnderSignal(BaseSignal):
    tag = "extended_rest_under"
    description = "Extended rest (4+ days) UNDER — predictable scoring on return"
    CONFIDENCE = 0.75
    MIN_REST_DAYS = 4
    MIN_LINE = 15  # Exclude bench (covered by bench_under)

    def evaluate(self, prediction, features=None, supplemental=None):
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        rest_days = prediction.get('rest_days') or 0
        if rest_days < self.MIN_REST_DAYS:
            return self._no_qualify()

        line = prediction.get('line_value') or 0
        if line < self.MIN_LINE:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'rest_days': rest_days,
                'line': line,
                'backtest_hr': 61.8,
            }
        )
