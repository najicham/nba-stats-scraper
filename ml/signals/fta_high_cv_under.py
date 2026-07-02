"""FTA High Coefficient-of-Variation UNDER signal — volatile foul-drawers regress.

Players with high FTA average (>=5/game) AND high FTA variance (CV>=0.4) have
inconsistent scoring because their points depend heavily on foul-drawing, which
is volatile game-to-game. The market prices their line on peak foul-drawing
frequency; when variance is high, the UNDER hits more reliably than the book allows.

BACKTEST (2021-22 through 2024-25, 4 pre-anomaly seasons):
  2021-22: 61.4% HR
  2022-23: 62.3% HR
  2023-24: 63.2% HR
  2024-25: 63.9% HR — monotonically improving, same 2025-26 anomaly collapse as b2b_fatigue_under
  2025-26: 50.9% (anomaly season — do not use for promotion gate)

Pattern mirrors b2b_fatigue_under: real 4-season structural edge, 2025-26 inversion
from the scoring-environment anomaly. Promote after live 2026-27 N>=30 at HR>=58%.

Data source: pred['fta_avg_last_10'], pred['fta_cv_last_10'] — already in pred dict
from the fta_variance CTE in supplemental_data.py (Session 451).

NOTE: The removed filter `ft_variance_under` (Session 494: CF HR=56%, blocking winners)
was measuring something different — it BLOCKED UNDER when FTA was volatile (opposite
direction). This signal TAKES UNDER when FTA is volatile. Different thesis.

Created: 2026-07-01 (backtest-validated, 4/4 pre-anomaly seasons)
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class FtaHighCvUnderSignal(BaseSignal):
    tag = "fta_high_cv_under"
    description = (
        "High FTA avg (>=5/g) + high FTA CV (>=0.4) UNDER — volatile foul-drawing "
        "regresses; 61-64% HR 4 pre-anomaly seasons"
    )

    MIN_FTA_AVG = 5.0    # meaningful foul-drawer
    MIN_FTA_CV = 0.4     # high variance threshold (scanner: CV >= 0.4)
    CONFIDENCE_BASE = 0.62

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        fta_avg = float(prediction.get('fta_avg_last_10') or 0)
        fta_cv = float(prediction.get('fta_cv_last_10') or 0)

        if fta_avg < self.MIN_FTA_AVG:
            return self._no_qualify()

        if fta_cv < self.MIN_FTA_CV:
            return self._no_qualify()

        confidence = min(0.80, self.CONFIDENCE_BASE + (fta_cv - self.MIN_FTA_CV) * 0.2)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'fta_avg_last_10': round(fta_avg, 1),
                'fta_cv_last_10': round(fta_cv, 3),
                'thresholds': {'fta_avg': self.MIN_FTA_AVG, 'fta_cv': self.MIN_FTA_CV},
                'backtest_hr_range': '61.4-63.9% (4 pre-anomaly seasons)',
            },
        )
