"""Cross-Model Scorer — computes consensus factors from all active models.

Runs ONCE at the start of the aggregator pipeline. Single batch query
returns all models' predictions for the target date, then computes
per-player consensus factors used by the aggregator for scoring.

Session 277: Initial creation.
Session 296: Dynamic model discovery — queries actual system_ids
  instead of relying on hardcoded lists that go stale after retrains.
"""

import logging
from typing import Any, Dict, List, Optional

from google.cloud import bigquery

from shared.config.cross_model_subsets import (
    DiscoveredModels,
    build_system_id_sql_filter,
    discover_models,
)

logger = logging.getLogger(__name__)


class CrossModelScorer:
    """Compute cross-model consensus factors for aggregator scoring."""

    def compute_factors(
        self,
        bq_client: bigquery.Client,
        target_date: str,
        project_id: str = 'nba-props-platform',
    ) -> Dict[str, Dict[str, Any]]:
        """Query all models and compute per-player consensus factors.

        Args:
            bq_client: BigQuery client.
            target_date: Date string YYYY-MM-DD.
            project_id: GCP project ID.

        Returns:
            Dict keyed by 'player_lookup::game_id' with consensus factors:
                model_agreement_count: int (how many models agree on majority dir)
                majority_direction: str ('OVER' or 'UNDER')
                feature_set_diversity: int (1 or 2 feature sets represented)
                quantile_consensus_under: bool (all available quantile models agree UNDER)
                avg_edge_agreeing: float (avg edge of agreeing models)
                consensus_bonus: float (pre-computed score adjustment)
                agreeing_model_ids: list[str] (system_ids of agreeing models)
        """
        # Discover which models are active for this date
        discovered = discover_models(bq_client, target_date, project_id)
        if discovered.family_count < 2:
            logger.warning(
                f"Only {discovered.family_count} model families for "
                f"{target_date} — skipping cross-model scoring"
            )
            return {}

        predictions = self._query_predictions(
            bq_client, target_date, project_id,
        )
        if not predictions:
            return {}

        # Pivot by player-game
        pivoted = self._pivot(predictions)

        # Compute factors for each player-game
        factors = {}
        for key, data in pivoted.items():
            factor = self._compute_player_factor(data, discovered)
            if factor:
                factors[key] = factor

        if factors:
            with_bonus = sum(1 for f in factors.values() if f['consensus_bonus'] > 0)
            logger.info(
                f"Cross-model factors: {len(factors)} player-games, "
                f"{with_bonus} with consensus bonus "
                f"({discovered.family_count} model families)"
            )

        return factors

    def _query_predictions(
        self,
        bq_client: bigquery.Client,
        target_date: str,
        project_id: str,
    ) -> List[Dict]:
        """Query all known model families' predictions for target date."""
        sql_filter = build_system_id_sql_filter()

        query = f"""
        SELECT
            player_lookup,
            game_id,
            system_id,
            recommendation,
            CAST(predicted_points - current_points_line AS FLOAT64) AS edge,
            CAST(confidence_score AS FLOAT64) AS confidence_score
        FROM `{project_id}.nba_predictions.player_prop_predictions`
        WHERE game_date = @target_date
          AND {sql_filter}
          AND is_active = TRUE
          AND recommendation IN ('OVER', 'UNDER')
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            ]
        )

        try:
            result = bq_client.query(query, job_config=job_config).result(timeout=60)
            return [dict(row) for row in result]
        except Exception as e:
            logger.error(f"Cross-model scorer query failed: {e}", exc_info=True)
            return []

    def _pivot(self, predictions: List[Dict]) -> Dict[str, Dict]:
        """Pivot predictions by player-game key."""
        pivoted: Dict[str, Dict] = {}
        for pred in predictions:
            key = f"{pred['player_lookup']}::{pred['game_id']}"
            if key not in pivoted:
                pivoted[key] = {'models': {}}
            pivoted[key]['models'][pred['system_id']] = {
                'recommendation': pred['recommendation'],
                'edge': pred['edge'],
            }
        return pivoted

    def _compute_player_factor(
        self, data: Dict, discovered: DiscoveredModels,
    ) -> Optional[Dict[str, Any]]:
        """Compute consensus factors for a single player-game."""
        models = data['models']
        if len(models) < 2:
            return None

        # Count per-direction (edge >= 3 only for agreement)
        over_models = []
        under_models = []
        for model_id, pred in models.items():
            if abs(pred['edge']) < 3.0:
                continue
            if pred['recommendation'] == 'OVER':
                over_models.append(model_id)
            else:
                under_models.append(model_id)

        if not over_models and not under_models:
            return None

        # Majority direction
        if len(over_models) >= len(under_models):
            majority_dir = 'OVER'
            agreeing = over_models
        else:
            majority_dir = 'UNDER'
            agreeing = under_models

        n_agreeing = len(agreeing)

        # Feature set diversity (using discovered classifications)
        has_v9 = any(m in discovered.v9_ids for m in agreeing)
        has_v12 = any(m in discovered.v12_ids for m in agreeing)
        feature_diversity = (1 if has_v9 else 0) + (1 if has_v12 else 0)

        # Quantile consensus UNDER — all *available* quantile models agree
        available_quantile = discovered.quantile_ids
        quantile_under = (
            majority_dir == 'UNDER'
            and len(available_quantile) >= 2
            and all(m in agreeing for m in available_quantile)
        )

        # Average edge of agreeing models
        agreeing_edges = [abs(models[m]['edge']) for m in agreeing]
        avg_edge = sum(agreeing_edges) / len(agreeing_edges) if agreeing_edges else 0

        # Consensus bonus formula (Session 297: removed diversity_mult)
        # V9+V12 agreement is ANTI-correlated with winning:
        #   OVER + V12 agrees: 33.3% HR vs V12 no pick: 66.8%
        #   UNDER + V12 agrees: 46.5% HR vs V12 no pick: 53.5%
        # Agreement bonus is only for model COUNT, not feature-set diversity.
        agreement_base = 0.05 * (n_agreeing - 2) if n_agreeing >= 3 else 0
        quantile_bonus = 0.10 if quantile_under else 0
        consensus_bonus = round(agreement_base + quantile_bonus, 4)

        return {
            'model_agreement_count': n_agreeing,
            'majority_direction': majority_dir,
            'feature_set_diversity': feature_diversity,
            'quantile_consensus_under': quantile_under,
            'avg_edge_agreeing': round(avg_edge, 2),
            'consensus_bonus': consensus_bonus,
            'agreeing_model_ids': agreeing,
        }
