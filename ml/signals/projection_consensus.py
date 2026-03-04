"""Projection consensus signal — external projections agree with model direction.

Session 401/403: When 2+ independent projection sources agree with our model's
OVER/UNDER direction relative to the prop line, the confluence of independent
models creates a strong consensus signal.

Sources (4 total, 3 working as of Session 403):
  - FantasyPros: consensus projections from 4+ experts (WORKING)
  - DailyFantasyFuel: independent DFS projections (WORKING)
  - Dimers: projected points model (WORKING)
  - NumberFire/FanDuel: FanDuel Research projections (BROKEN — needs Playwright)

Projection sources use different architectures (regression ensembles, Monte Carlo
simulations) with different feature weights — genuinely orthogonal to CatBoost.

Signals:
  - projection_consensus_over: Model says OVER AND 2+ projections above line
    Expected HR 65-70% based on consensus-beats-line research.
  - projection_consensus_under: Model says UNDER AND 2+ projections below line
  - projection_disagreement: Model says OVER but 0 projections agree
    Expected filter HR <50% — all external models disagree with our direction.

The signal reads from 4 projection BQ tables, joined to predictions via
player_lookup in supplemental_data.py.
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
    description = "2+ external projections above line + model OVER — consensus signal"

    CONFIDENCE = 0.75
    MIN_SOURCES_ABOVE = 2  # Number of external sources projecting above line

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
            }
        )


class ProjectionConsensusUnderSignal(BaseSignal):
    """UNDER signal when 2+ external projections project below the line.

    When independent projection models agree the player will score below the
    prop line AND our model predicts UNDER.
    """

    tag = "projection_consensus_under"
    description = "2+ external projections below line + model UNDER — consensus signal"

    CONFIDENCE = 0.70
    MIN_SOURCES_BELOW = 2

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
            }
        )
