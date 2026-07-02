"""Drive Volume UNDER signal — market overpriced drive-heavy scorers.

Shadow accumulation signal. No backtest possible (nba_tracking_stats data
starts 2026-03-04; full season data accumulates from 2026-27 season open).

Mechanism: drive-heavy players (7+ drives/game season average) are priced
with their drive-volume upside already baked into the line. When the model
recommends UNDER on such a player, it means the model sees mean-reversion
pressure against a line the market has inflated with drive-volume optimism.
The signal amplifies model UNDER confidence on drive-heavy players — it is
NOT a naive "drives → more scoring" signal. The UNDER fires specifically
because the line was set with that assumption and the model disagrees.

Threshold: 7.0 drives/game captures the top ~20% of drive-heavy rotation
players. NBA.com distributions:
  Bench/role players: 0-2 drives/game
  Average rotation: 3-5 drives/game
  Drive-heavy wings/guards: 7-10 drives/game
  Elite ball-handlers (Luka, Trae): 10-15 drives/game

Data source: pred['drives_avg_season'] — season-average drives/game from
nba_raw.nba_tracking_stats (most recent scrape before game date).
NOTE: this is a season running average, not a true rolling 10-game window,
because NBA.com tracking API returns only season-to-date cumulative stats.

Promote when: N>=30 live 2026-27 at HR>=58%. Verify threshold=7.0 fires at
5-10 picks/week. Check overlap with high_line_under.

Created: 2026-07-01
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult

DRIVES_THRESHOLD = 7.0


class DriveVolumeUnderSignal(BaseSignal):
    tag = "drive_volume_under"
    description = (
        "Season avg drives/game >= 7 + model UNDER — market overpriced drive-inflated "
        "scoring (shadow, no prior backtest; data from 2026-27)"
    )

    def evaluate(
        self,
        prediction: Dict,
        features: Optional[Dict] = None,
        supplemental: Optional[Dict] = None,
    ) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        drives_avg = prediction.get('drives_avg_season')
        if drives_avg is None:
            return self._no_qualify()

        if float(drives_avg) < DRIVES_THRESHOLD:
            return self._no_qualify()

        confidence = min(0.70, 0.58 + (float(drives_avg) - DRIVES_THRESHOLD) / 20.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'drives_avg_season': round(float(drives_avg), 1),
                'threshold': DRIVES_THRESHOLD,
                'status': 'shadow_no_backtest',
            },
        )
