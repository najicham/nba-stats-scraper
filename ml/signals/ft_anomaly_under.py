"""FT anomaly UNDER signal — high FTA variance predicts UNDER.

When a player's FTA rate is volatile (CV >= 0.5) and they average 5+ FTA/game,
their recent scoring was likely inflated by unsustainable free throw volume.
Books anchor to inflated recent scoring; FT regression pulls them under.

5-season cross-validated (2021-22 through 2025-26):
  - FTA>=5, CV>=0.6: 63.3% HR (N=278), consistent all 5 seasons
  - FTA>=5, CV>=0.5: 58.7% HR (N=530), consistent all 5 seasons
  - Also a FILTER: same conditions on OVER = 37.5% HR (N=56)

Created: Session 463 (P0 simulator experiments)
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class FtAnomalyUnderSignal(BaseSignal):
    tag = "ft_anomaly_under"
    description = "FT anomaly UNDER — FTA CV >= 0.5 with 5+ FTA/game, scoring regression expected (63.3% HR)"

    # Minimum FTA per game to filter out low-volume noise
    MIN_FTA_AVG = 5.0
    # Minimum FTA coefficient of variation for "high volatility"
    MIN_FTA_CV = 0.5
    CONFIDENCE_BASE = 0.75

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Direction gate: UNDER only
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # FTA data comes from pred dict (supplemental_data.py populates it)
        fta_avg = prediction.get('fta_avg_last_10')
        fta_cv = prediction.get('fta_cv_last_10')

        if fta_avg is None or fta_cv is None:
            return self._no_qualify()

        # Volume filter: must attempt enough FTs for signal to be meaningful
        if fta_avg < self.MIN_FTA_AVG:
            return self._no_qualify()

        # Core logic: FTA variance must be high enough
        if fta_cv < self.MIN_FTA_CV:
            return self._no_qualify()

        # Confidence scales with CV (higher variance = stronger signal)
        confidence = min(0.95, self.CONFIDENCE_BASE + (fta_cv - self.MIN_FTA_CV) * 0.4)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'fta_avg_last_10': round(fta_avg, 1),
                'fta_cv_last_10': round(fta_cv, 3),
                'backtest_hr': 63.3,
                'backtest_n': 278,
            },
        )
