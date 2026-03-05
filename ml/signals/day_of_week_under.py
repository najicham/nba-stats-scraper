"""Day-of-week UNDER boost signal.

Session 414: BQ validation showed strong day-of-week UNDER patterns:
  - Monday UNDER: 60.3% HR (N=277, edge 3+)
  - Thursday UNDER: 59.4% HR (N=419)
  - Other days: not significant for UNDER

Complements day_of_week_over.py (Monday/Thursday/Saturday OVER boost).
Monday is strong for BOTH directions — different players.
"""

from datetime import date as date_type, datetime
from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


# BQ-validated UNDER boost days (edge 3+, Nov 2025 — Mar 2026)
# Day numbers: 0=Monday, 1=Tuesday, ..., 6=Sunday (Python weekday())
STRONG_UNDER_DAYS = {
    0: {'name': 'Monday', 'hr': 60.3, 'n': 277},
    3: {'name': 'Thursday', 'hr': 59.4, 'n': 419},
}


class DayOfWeekUnderSignal(BaseSignal):
    """UNDER boost on Monday and Thursday.

    These days show 59-60% UNDER HR at the raw prediction level (edge 3+).
    Monday effect is the strongest at 60.3% (N=277).
    """

    tag = "day_of_week_under"
    description = "UNDER on Monday/Thursday — 59-60% HR"

    CONFIDENCE = 0.70

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        game_date_raw = prediction.get('game_date')
        if not game_date_raw:
            return self._no_qualify()

        # Parse game date
        if isinstance(game_date_raw, str):
            try:
                game_date = datetime.strptime(game_date_raw, '%Y-%m-%d').date()
            except ValueError:
                return self._no_qualify()
        elif isinstance(game_date_raw, date_type):
            game_date = game_date_raw
        else:
            return self._no_qualify()

        day_num = game_date.weekday()  # 0=Monday, ..., 6=Sunday

        if day_num not in STRONG_UNDER_DAYS:
            return self._no_qualify()

        day_info = STRONG_UNDER_DAYS[day_num]

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'day_name': day_info['name'],
                'backtest_hr': day_info['hr'],
                'backtest_n': day_info['n'],
            }
        )
