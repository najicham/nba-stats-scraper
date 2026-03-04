"""Day-of-week OVER boost signal.

Session 398: BQ validation showed strong day-of-week OVER patterns:
  - Monday OVER: 69.9% HR (N=326, edge 3+) — strongest
  - Saturday OVER: 67.5% HR (N=400) — large sample
  - Thursday OVER: 66.2% HR (N=376)
  - Wednesday OVER: 51.7% HR (N=408) — worst
  - Friday OVER: 53.0% HR raw, 37.5% at best bets (N=8)

Pattern survives pre-toxic/toxic calendar split. Monday effect
persists across all models.
"""

from datetime import date as date_type, datetime
from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


# BQ-validated OVER boost days (edge 3+, Nov 2025 — Mar 2026)
# Day numbers: 0=Monday, 1=Tuesday, ..., 6=Sunday (Python weekday())
STRONG_OVER_DAYS = {
    0: {'name': 'Monday', 'hr': 69.9, 'n': 326},
    3: {'name': 'Thursday', 'hr': 66.2, 'n': 376},
    5: {'name': 'Saturday', 'hr': 67.5, 'n': 400},
}


class DayOfWeekOverSignal(BaseSignal):
    """OVER boost on Monday, Thursday, Saturday.

    These days show 66-70% OVER HR at the raw prediction level (edge 3+).
    Monday effect is the strongest at 69.9% (N=326).
    """

    tag = "day_of_week_over"
    description = "OVER on Monday/Thursday/Saturday — 66-70% HR"

    CONFIDENCE = 0.75

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
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

        if day_num not in STRONG_OVER_DAYS:
            return self._no_qualify()

        day_info = STRONG_OVER_DAYS[day_num]

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
