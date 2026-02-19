"""Cross-Model Subset Materializer for Phase 6 Publishing.

Queries all active models' predictions for a game date, pivots by
(player_lookup, game_id) to see how models agree/disagree, and writes
cross-model observation subsets to current_subset_picks.

Design: observation-only subsets (system_id='cross_model').
Grading handled by existing SubsetGradingProcessor (agnostic to system_id).

Session 277: Initial creation.
Session 296: Dynamic model discovery — no more hardcoded system_ids.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import bigquery

from shared.clients.bigquery_pool import get_bigquery_client
from shared.config.gcp_config import get_project_id
from shared.config.subset_public_names import get_public_name
from shared.config.cross_model_subsets import (
    CROSS_MODEL_SUBSETS,
    DiscoveredModels,
    build_system_id_sql_filter,
    discover_models,
)

logger = logging.getLogger(__name__)

PROJECT_ID = get_project_id()
SUBSET_TABLE_ID = f'{PROJECT_ID}.nba_predictions.current_subset_picks'


class CrossModelSubsetMaterializer:
    """Compute cross-model observation subsets and write to BigQuery."""

    def __init__(self, project_id: str = None):
        self.project_id = project_id or PROJECT_ID
        self.bq_client = get_bigquery_client(project_id=self.project_id)

    def materialize(
        self,
        game_date: str,
        version_id: str,
        trigger_source: str = 'export',
    ) -> Dict[str, Any]:
        """Compute cross-model subsets and write to current_subset_picks.

        Args:
            game_date: Date string YYYY-MM-DD.
            version_id: Version ID from SubsetMaterializer (same batch).
            trigger_source: What triggered this materialization.

        Returns:
            Dict with subset counts summary.
        """
        computed_at = datetime.now(timezone.utc)

        # 1. Discover which models are active for this date
        discovered = discover_models(self.bq_client, game_date, self.project_id)
        if discovered.family_count < 2:
            logger.warning(
                f"Only {discovered.family_count} model families found for "
                f"{game_date} — need at least 2 for cross-model analysis. "
                f"Found: {sorted(discovered.family_to_id.keys())}"
            )
            return {'total_picks': 0, 'subsets': {}}

        # 2. Query all models' predictions for this date
        all_predictions = self._query_all_model_predictions(game_date, discovered)
        if not all_predictions:
            logger.info(f"No cross-model predictions for {game_date}")
            return {'total_picks': 0, 'subsets': {}}

        # 3. Pivot by (player_lookup, game_id) → list of model predictions
        player_models = self._pivot_by_player(all_predictions)
        logger.info(
            f"Cross-model: {len(player_models)} player-games across "
            f"{len(all_predictions)} predictions from "
            f"{discovered.family_count} model families"
        )

        # 4. Apply each cross-model filter
        rows = []
        subsets_summary = {}

        for subset_id, config in CROSS_MODEL_SUBSETS.items():
            matching = self._apply_filter(subset_id, config, player_models, discovered)

            # Apply top_n limit if specified (rank by avg_edge descending)
            top_n = config.get('top_n')
            if top_n and len(matching) > top_n:
                matching.sort(key=lambda x: x['avg_edge'], reverse=True)
                matching = matching[:top_n]

            public = get_public_name(subset_id)

            for rank, pick in enumerate(matching, 1):
                rows.append({
                    'game_date': game_date,
                    'subset_id': subset_id,
                    'player_lookup': pick['player_lookup'],
                    'prediction_id': None,
                    'game_id': pick['game_id'],
                    'rank_in_subset': rank,
                    'system_id': 'cross_model',
                    'version_id': version_id,
                    'computed_at': computed_at.isoformat(),
                    'trigger_source': trigger_source,
                    'batch_id': None,
                    # Use champion model's prediction for denormalized data
                    'player_name': pick.get('player_name', ''),
                    'team': pick.get('team', ''),
                    'opponent': pick.get('opponent', ''),
                    'predicted_points': pick.get('predicted_points'),
                    'current_points_line': pick.get('line_value'),
                    'recommendation': pick['majority_direction'],
                    'confidence_score': pick.get('confidence_score'),
                    'edge': pick.get('representative_edge'),
                    'composite_score': pick.get('avg_edge'),
                    # Cross-model provenance: repurpose signal columns
                    # signal_tags = list of agreeing model system_ids
                    # signal_count = number of agreeing models
                    'signal_tags': pick.get('agreeing_models', []),
                    'signal_count': pick.get('agreement_count', 0),
                    'matched_combo_id': f"feature_diversity_{pick.get('feature_set_diversity', 0)}",
                    'combo_classification': None,
                    'combo_hit_rate': None,
                    'model_health_status': None,
                    'warning_tags': [],
                    # Quality provenance
                    'feature_quality_score': None,
                    'default_feature_count': None,
                    'line_source': None,
                    'prediction_run_mode': None,
                    'prediction_made_before_game': None,
                    'quality_alert_level': None,
                    # Subset metadata
                    'subset_name': public['name'],
                    'min_edge': config.get('min_edge'),
                    'min_confidence': None,
                    'top_n': config.get('top_n'),
                    # Version-level context
                    'daily_signal': None,
                    'pct_over': None,
                    'total_predictions_available': len(player_models),
                })

            subsets_summary[subset_id] = len(matching)
            if matching:
                logger.info(
                    f"  {subset_id}: {len(matching)} picks"
                )

        # 5. Write to BigQuery
        if rows:
            self._write_rows(rows)

        total = len(rows)
        logger.info(
            f"Cross-model materialized {total} picks across "
            f"{len(subsets_summary)} subsets for {game_date}"
        )

        return {
            'total_picks': total,
            'subsets': subsets_summary,
        }

    def _query_all_model_predictions(
        self, game_date: str, discovered: DiscoveredModels,
    ) -> List[Dict[str, Any]]:
        """Query all discovered models' active predictions for a game date."""
        sql_filter = build_system_id_sql_filter()

        query = f"""
        SELECT
            player_lookup,
            game_id,
            system_id,
            CAST(predicted_points AS FLOAT64) AS predicted_points,
            CAST(current_points_line AS FLOAT64) AS line_value,
            recommendation,
            CAST(predicted_points - current_points_line AS FLOAT64) AS edge,
            CAST(confidence_score AS FLOAT64) AS confidence_score
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE game_date = @game_date
          AND {sql_filter}
          AND is_active = TRUE
          AND recommendation IN ('OVER', 'UNDER')
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
            ]
        )

        try:
            result = self.bq_client.query(query, job_config=job_config).result(
                timeout=60
            )
            return [dict(row) for row in result]
        except Exception as e:
            logger.error(f"Cross-model prediction query failed: {e}", exc_info=True)
            return []

    def _pivot_by_player(
        self, predictions: List[Dict],
    ) -> Dict[str, Dict[str, Any]]:
        """Pivot predictions into {player_lookup::game_id → model_predictions}.

        Returns dict keyed by 'player_lookup::game_id' with:
            - models: dict of system_id → prediction dict
            - player_lookup, game_id, player_name, team, opponent
        """
        pivot: Dict[str, Dict[str, Any]] = {}

        for pred in predictions:
            key = f"{pred['player_lookup']}::{pred['game_id']}"
            if key not in pivot:
                # Derive team/opponent from game_id (format: YYYYMMDD_AWAY_HOME)
                game_id = pred.get('game_id', '')
                parts = game_id.split('_') if game_id else []
                away_team = parts[1] if len(parts) >= 3 else ''
                home_team = parts[2] if len(parts) >= 3 else ''

                pivot[key] = {
                    'player_lookup': pred['player_lookup'],
                    'game_id': game_id,
                    'player_name': pred['player_lookup'],  # Best available
                    'team': '',
                    'opponent': '',
                    'away_team': away_team,
                    'home_team': home_team,
                    'models': {},
                }
            pivot[key]['models'][pred['system_id']] = {
                'recommendation': pred['recommendation'],
                'edge': pred['edge'],
                'predicted_points': pred['predicted_points'],
                'line_value': pred['line_value'],
                'confidence_score': pred['confidence_score'],
            }

        return pivot

    def _apply_filter(
        self,
        subset_id: str,
        config: Dict[str, Any],
        player_models: Dict[str, Dict[str, Any]],
        discovered: DiscoveredModels,
    ) -> List[Dict[str, Any]]:
        """Apply a cross-model filter and return qualifying picks."""
        results = []
        min_edge = config.get('min_edge', 0)
        min_agreeing = config.get('min_agreeing_models', 2)
        required_direction = config.get('direction')

        for key, data in player_models.items():
            models = data['models']

            # Count agreeing models per direction (with edge filter)
            over_models: List[str] = []
            under_models: List[str] = []

            for model_id, pred in models.items():
                if abs(pred['edge']) < min_edge:
                    continue
                if pred['recommendation'] == 'OVER':
                    over_models.append(model_id)
                elif pred['recommendation'] == 'UNDER':
                    under_models.append(model_id)

            # Determine majority direction
            if len(over_models) >= len(under_models):
                majority_dir = 'OVER'
                agreeing = over_models
            else:
                majority_dir = 'UNDER'
                agreeing = under_models

            # Direction filter
            if required_direction and majority_dir != required_direction:
                continue

            # Minimum agreeing models
            if len(agreeing) < min_agreeing:
                continue

            # All available quantile models must agree
            if config.get('require_all_quantile'):
                available_quantile = discovered.quantile_ids
                if len(available_quantile) < 2:
                    continue  # Need at least 2 quantile models
                if not all(m in agreeing for m in available_quantile):
                    continue

            # MAE + Quantile cross-loss requirement (family-based)
            if config.get('require_mae_and_quantile'):
                has_mae = any(m in discovered.mae_ids for m in agreeing)
                has_quantile = any(m in discovered.quantile_ids for m in agreeing)
                if not (has_mae and has_quantile):
                    continue

            # Feature diversity requirement (V9 and V12 feature sets)
            if config.get('require_feature_diversity'):
                has_v9 = any(m in discovered.v9_ids for m in agreeing)
                has_v12 = any(m in discovered.v12_ids for m in agreeing)
                if not (has_v9 and has_v12):
                    continue

            # Compute aggregate stats
            agreeing_edges = [
                abs(models[m]['edge']) for m in agreeing if m in models
            ]
            avg_edge = sum(agreeing_edges) / len(agreeing_edges) if agreeing_edges else 0

            # Feature set diversity count
            feature_sets = set()
            for m in agreeing:
                if m in discovered.v9_ids:
                    feature_sets.add('v9')
                if m in discovered.v12_ids:
                    feature_sets.add('v12')

            # Use first available model's prediction for representative data
            rep_model = agreeing[0] if agreeing else None
            rep_pred = models.get(rep_model, {}) if rep_model else {}

            results.append({
                'player_lookup': data['player_lookup'],
                'game_id': data['game_id'],
                'player_name': data.get('player_name', ''),
                'team': data.get('team', ''),
                'opponent': data.get('opponent', ''),
                'majority_direction': majority_dir,
                'agreement_count': len(agreeing),
                'agreeing_models': agreeing,
                'avg_edge': round(avg_edge, 2),
                'feature_set_diversity': len(feature_sets),
                'predicted_points': rep_pred.get('predicted_points'),
                'line_value': rep_pred.get('line_value'),
                'confidence_score': rep_pred.get('confidence_score'),
                'representative_edge': rep_pred.get('edge'),
            })

        # Sort by avg_edge descending
        results.sort(key=lambda x: x['avg_edge'], reverse=True)
        return results

    def _write_rows(self, rows: List[Dict[str, Any]]) -> None:
        """Write cross-model subset rows using streaming insert."""
        try:
            errors = self.bq_client.insert_rows_json(SUBSET_TABLE_ID, rows)
            if errors:
                logger.error(f"Errors writing cross-model subsets: {errors}")
            else:
                logger.info(
                    f"Wrote {len(rows)} cross-model subset rows to {SUBSET_TABLE_ID}"
                )
        except Exception as e:
            logger.error(
                f"Failed to write cross-model subsets: {e}", exc_info=True
            )
