"""Cross-Model Scorer — computes consensus factors from all 6 models.

Runs ONCE at the start of the aggregator pipeline. Single batch query
returns all models' predictions for the target date, then computes
per-player consensus factors used by the aggregator for scoring.

Session 277: Initial creation.
"""

import logging
from typing import Any, Dict, List, Optional

from google.cloud import bigquery

from shared.config.cross_model_subsets import (
    ALL_MODELS,
    MAE_MODELS,
    QUANTILE_MODELS,
    V9_FEATURE_SET,
    V12_FEATURE_SET,
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
                quantile_consensus_under: bool (all 4 quantile models agree UNDER)
                avg_edge_agreeing: float (avg edge of agreeing models)
                consensus_bonus: float (pre-computed score adjustment)
        """
        predictions = self._query_predictions(bq_client, target_date, project_id)
        if not predictions:
            return {}

        # Pivot by player-game
        pivoted = self._pivot(predictions)

        # Compute factors for each player-game
        factors = {}
        for key, data in pivoted.items():
            factor = self._compute_player_factor(data)
            if factor:
                factors[key] = factor

        if factors:
            with_bonus = sum(1 for f in factors.values() if f['consensus_bonus'] > 0)
            logger.info(
                f"Cross-model factors: {len(factors)} player-games, "
                f"{with_bonus} with consensus bonus"
            )

        return factors

    def _query_predictions(
        self,
        bq_client: bigquery.Client,
        target_date: str,
        project_id: str,
    ) -> List[Dict]:
        """Query all models' predictions for target date."""
        model_list = ', '.join(f"'{m}'" for m in ALL_MODELS)

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
          AND system_id IN ({model_list})
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

    def _compute_player_factor(self, data: Dict) -> Optional[Dict[str, Any]]:
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

        # Feature set diversity
        has_v9 = any(m in V9_FEATURE_SET for m in agreeing)
        has_v12 = any(m in V12_FEATURE_SET for m in agreeing)
        feature_diversity = (1 if has_v9 else 0) + (1 if has_v12 else 0)

        # Quantile consensus UNDER
        quantile_under = (
            majority_dir == 'UNDER'
            and all(m in agreeing for m in QUANTILE_MODELS)
        )

        # Average edge of agreeing models
        agreeing_edges = [abs(models[m]['edge']) for m in agreeing]
        avg_edge = sum(agreeing_edges) / len(agreeing_edges) if agreeing_edges else 0

        # Consensus bonus formula
        agreement_base = 0.05 * (n_agreeing - 2) if n_agreeing >= 3 else 0
        diversity_mult = 1.3 if (has_v9 and has_v12) else 1.0
        quantile_bonus = 0.10 if quantile_under else 0
        consensus_bonus = round(agreement_base * diversity_mult + quantile_bonus, 4)

        return {
            'model_agreement_count': n_agreeing,
            'majority_direction': majority_dir,
            'feature_set_diversity': feature_diversity,
            'quantile_consensus_under': quantile_under,
            'avg_edge_agreeing': round(avg_edge, 2),
            'consensus_bonus': consensus_bonus,
        }
