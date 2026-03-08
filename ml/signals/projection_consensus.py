"""Projection alignment signal — external projection agrees with model direction.

Session 401/403: Originally designed as multi-source consensus (2+ sources agree).
Session 407: Switched to single-source mode using NumberFire only.
Session 434: Added ESPN Fantasy projections as second source (shadow validation).

Sources:
  - NumberFire/FanDuel: FanDuel Research GraphQL projections (120+ players/day)
  - ESPN Fantasy: Season-average per-game projections (~500 players/day, shadow)
  - FantasyPros: EXCLUDED — Dead (Playwright timeout, wrong data type: DFS season totals)
  - Dimers: EXCLUDED — Page shows generic projections, NOT game-date-specific
  - DailyFantasyFuel: EXCLUDED — only provides DraftKings fantasy points (FPTS)

NumberFire uses regression ensembles with different feature weights — genuinely
orthogonal to our CatBoost models. ESPN provides season-average projections as a
fallback when NumberFire is unavailable.

Signals:
  - projection_consensus_over: Model says OVER AND 1+ projection above line
    (renamed intent: "projection aligned" but tag kept for backwards compat)
  - projection_consensus_under: Model says UNDER AND 1+ projection below line
  - projection_disagreement: Model says OVER but 0 projections agree (needs 2+ sources)

MIN_SOURCES remains at 1 — ESPN needs shadow validation before raising to 2.
"""

from typing import Dict, Optional

from ml.signals.base_signal import BaseSignal, SignalResult


class ProjectionConsensusOverSignal(BaseSignal):
    """OVER signal when 2+ external projections also project above the line.

    When independent projection models agree the player will score above the
    prop line AND our model predicts OVER, the confluence of orthogonal
    methodologies creates a strong consensus signal.
    """

    tag = "projection_consensus_over"
    description = "External projection above line + model OVER — aligned signal"

    CONFIDENCE = 0.70  # Session 407: lowered from 0.75 for single-source mode
    MIN_SOURCES_ABOVE = 1  # Session 407: lowered from 2 for single-source mode

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        sources_above = prediction.get('projection_sources_above_line', 0)
        total_sources = prediction.get('projection_sources_total', 0)

        if total_sources < 1:
            return self._no_qualify()

        if sources_above < self.MIN_SOURCES_ABOVE:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'sources_above_line': sources_above,
                'total_sources': total_sources,
                'numberfire_proj': prediction.get('numberfire_projected_points'),
                'fantasypros_proj': prediction.get('fantasypros_projected_points'),
                'dailyfantasyfuel_proj': prediction.get('dailyfantasyfuel_projected_points'),
                'dimers_proj': prediction.get('dimers_projected_points'),
                'espn_proj': prediction.get('espn_projected_points'),
            }
        )


class ProjectionConsensusUnderSignal(BaseSignal):
    """UNDER signal when 2+ external projections project below the line.

    When independent projection models agree the player will score below the
    prop line AND our model predicts UNDER.
    """

    tag = "projection_consensus_under"
    description = "External projection below line + model UNDER — aligned signal"

    CONFIDENCE = 0.65  # Session 407: lowered from 0.70 for single-source mode
    MIN_SOURCES_BELOW = 1  # Session 407: lowered from 2 for single-source mode

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        sources_below = prediction.get('projection_sources_below_line', 0)
        total_sources = prediction.get('projection_sources_total', 0)

        if total_sources < 1:
            return self._no_qualify()

        if sources_below < self.MIN_SOURCES_BELOW:
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'sources_below_line': sources_below,
                'total_sources': total_sources,
                'numberfire_proj': prediction.get('numberfire_projected_points'),
                'fantasypros_proj': prediction.get('fantasypros_projected_points'),
                'dailyfantasyfuel_proj': prediction.get('dailyfantasyfuel_projected_points'),
                'dimers_proj': prediction.get('dimers_projected_points'),
                'espn_proj': prediction.get('espn_projected_points'),
            }
        )


class ProjectionDisagreementFilter(BaseSignal):
    """Negative filter: model says OVER but 0 external projections agree.

    When our model predicts OVER but NO external projection source projects
    above the line, it indicates our model may be an outlier. Expected HR <50%.
    """

    tag = "projection_disagreement"
    description = "Model says OVER but 0 external projections agree — negative filter"

    CONFIDENCE = 0.60

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        total_sources = prediction.get('projection_sources_total', 0)
        sources_above = prediction.get('projection_sources_above_line', 0)

        if total_sources < 2:
            # Need at least 2 sources to be meaningful disagreement
            return self._no_qualify()

        if sources_above > 0:
            # At least one source agrees, not full disagreement
            return self._no_qualify()

        return SignalResult(
            qualifies=True,
            confidence=self.CONFIDENCE,
            source_tag=self.tag,
            metadata={
                'total_sources': total_sources,
                'sources_above_line': 0,
                'numberfire_proj': prediction.get('numberfire_projected_points'),
                'fantasypros_proj': prediction.get('fantasypros_projected_points'),
                'dailyfantasyfuel_proj': prediction.get('dailyfantasyfuel_projected_points'),
                'dimers_proj': prediction.get('dimers_projected_points'),
                'espn_proj': prediction.get('espn_projected_points'),
            }
        )
