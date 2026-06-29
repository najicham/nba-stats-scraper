"""Dense Schedule Grind UNDER signal — cumulative fatigue when a player has played 4+
games in the last 7 days suppresses scoring output.

Background: `games_in_last_7_days` is populated in `upcoming_player_game_context` and
flows through Phase 4 → ml_feature_store_v2 (feature index 4). The per_model_pipeline
surfaces it as the `games_in_last_7_days` column in the prediction dict.

Mechanism: Late-season grind stretches (Feb+) accumulate in compressed schedules where
teams play 4-5 games in 7 days. Unlike a single B2B, cumulative load across the week
(minutes, travel, recovery) suppresses performance in ways that books do not fully price.
This is conceptually distinct from `b2b_fatigue_under` (rest_days == 1), which fires
on any second night; this signal fires when the WEEKLY schedule is dense regardless of
whether today is a B2B.

Status: SHADOW (registered + tracked, EXCLUDED from real_sc via SHADOW_SIGNALS → zero
pick impact). Promote to UNDER_SIGNAL_WEIGHTS at season open after live 2026-27 once it
accrues N>=30 BB-level picks at HR>=58%. Before promoting, check overlap with
`b2b_fatigue_under` — some 4-in-7 stretches include a B2B; confirm the signal adds value
beyond the B2B component.
"""

from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult


class DenseScheduleGrindUnderSignal(BaseSignal):
    tag = "dense_schedule_grind_under"
    description = (
        "Dense schedule grind UNDER — 4+ games in the last 7 days, "
        "cumulative fatigue suppresses scoring (shadow)"
    )

    # Minimum games-in-7 to qualify
    MIN_GAMES_IN_7 = 4
    # Base confidence — moderate, needs live validation
    CONFIDENCE_BASE = 0.60

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:
        # Direction gate: UNDER only
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Read games_in_last_7_days directly from the prediction dict.
        # This field is populated by per_model_pipeline via feature_4_value from
        # ml_feature_store_v2 and is surfaced as the `games_in_last_7_days` column
        # in the final SELECT.
        games_in_7 = prediction.get('games_in_last_7_days')
        if games_in_7 is None:
            return self._no_qualify()

        try:
            games_in_7 = int(games_in_7)
        except (TypeError, ValueError):
            return self._no_qualify()

        if games_in_7 < self.MIN_GAMES_IN_7:
            return self._no_qualify()

        # Confidence scales modestly with density (5+ games is a tighter grind).
        confidence = min(0.75, self.CONFIDENCE_BASE + (games_in_7 - self.MIN_GAMES_IN_7) * 0.05)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'games_in_last_7_days': games_in_7,
                'status': 'shadow',
                'signal_mechanism': 'cumulative weekly schedule density suppresses scoring',
            },
        )
