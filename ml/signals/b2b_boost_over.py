"""B2B Boost Over Signal — Player on back-to-back games with OVER recommendation.

Session 396: B2B OVER shows strong performance across all periods:
- Raw HR: 64.3% (N=300)
- Best bets HR: 71.4% (N=7)
- Toxic window (Jan 30 - Feb 25): 69.2% — outperforms rested OVER at 49.1%
- Normal period: 63.9% = rested OVER 63.7% (neutral — no harm outside toxic)

B2B players maintain scoring aggression despite fatigue. This is the inverse of the
disabled b2b_fatigue_under signal — B2B is bullish for OVER, not bearish for UNDER.
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class B2BBoostOverSignal(BaseSignal):
    tag = "b2b_boost_over"
    description = "Player on back-to-back with OVER recommendation — maintained scoring aggression"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Must be OVER recommendation
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        # Must be back-to-back (1 rest day = consecutive game days)
        rest_days = prediction.get('rest_days')
        if rest_days is None and supplemental:
            rest_days = (supplemental.get('rest_stats') or {}).get('rest_days')
        if rest_days is None or rest_days != 1:
            return self._no_qualify()

        # Confidence is fixed — B2B OVER effect is consistent across tiers
        # 64.3% raw, 69.2% toxic, 63.9% normal = stable signal
        confidence = 0.70

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'rest_days': 1,
                'backtest_hr_raw': 0.643,
                'backtest_hr_toxic': 0.692,
                'signal_mechanism': 'B2B players maintain scoring aggression'
            }
        )
