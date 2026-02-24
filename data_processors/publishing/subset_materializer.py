"""
Subset Materializer for Phase 6 Publishing

Computes subset membership and writes to BigQuery current_subset_picks table.
Extracted from AllSubsetsPicksExporter so subsets exist as queryable entities
before export, enabling proper grading of what was actually in each subset.

Design: APPEND-ONLY
  Every materialization INSERTs a new set of rows with a new version_id.
  No UPDATEs are performed (avoids BigQuery 90-min DML partition locks).
  Predictions regenerate 4-6x/day (early, overnight, retry, line checks, last call),
  so each creates a new version. Consumers select the version they need.

Session 153: Created to materialize subsets at prediction time.
Session 188: Multi-model support — queries all active models, writes system_id per row.
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Any, Optional

from google.cloud import bigquery

from shared.clients.bigquery_pool import get_bigquery_client
from shared.config.cross_model_subsets import classify_system_id
from shared.config.gcp_config import get_project_id
from shared.config.subset_public_names import get_public_name
from shared.utils.quality_filter import should_include_prediction  # Session 209

logger = logging.getLogger(__name__)

# Champion model — used as fallback for daily signal
from shared.config.model_selection import get_champion_model_id
CHAMPION_SYSTEM_ID = get_champion_model_id()

# Minimum feature quality score for picks to be included
# Session 94: Players with quality < 85% have 51.9% hit rate vs 56.8% for 85%+
MIN_FEATURE_QUALITY_SCORE = 85.0


class SubsetMaterializer:
    """
    Compute subset membership and write to BigQuery.

    Loads subset definitions, filters predictions per subset,
    and writes materialized results to current_subset_picks.
    Append-only: each call creates a new version_id, never updates existing rows.
    """

    def __init__(self, project_id: str = None):
        self.project_id = project_id or get_project_id()
        self.bq_client = get_bigquery_client(project_id=self.project_id)
        self.table_id = f"{self.project_id}.nba_predictions.current_subset_picks"

    def materialize(
        self,
        game_date: str,
        trigger_source: str = 'unknown',
        batch_id: str = None,
        active_system_ids: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Compute and write subset picks to BigQuery.

        Each call creates a new version (append-only). Previous versions
        are preserved for history. No rows are updated or deleted.

        Args:
            game_date: Date string in YYYY-MM-DD format
            trigger_source: What triggered this ('overnight', 'same_day', 'line_check', 'manual', 'export')
            batch_id: Optional prediction batch ID
            active_system_ids: Pre-discovered active system_ids (avoids redundant BQ query)

        Returns:
            Dictionary with version_id, total_picks, subsets summary
        """
        computed_at = datetime.now(timezone.utc)
        version_id = f"v_{computed_at.strftime('%Y%m%d_%H%M%S')}"

        logger.info(
            f"Materializing subsets for {game_date} "
            f"(version={version_id}, trigger={trigger_source})"
        )

        # 1. Load subset definitions (all active models)
        subsets = self._query_subset_definitions()
        if not subsets:
            logger.warning(f"No active subset definitions found")
            return {
                'version_id': version_id,
                'game_date': game_date,
                'total_picks': 0,
                'subsets': {},
                'status': 'no_definitions',
            }

        # 2. Resolve stale system_ids in definitions (Session 311)
        #    Definitions may reference old model names (e.g. *_train1102_0131)
        #    while predictions use newer names (e.g. *_train1102_0125).
        #    Fix: classify both into families, map definition → active system_id.
        if active_system_ids is None:
            active_system_ids = self._query_active_system_ids(game_date)
        if active_system_ids:
            subsets = self._resolve_stale_system_ids(subsets, active_system_ids)

        # 3. Group definitions by system_id
        subsets_by_model = defaultdict(list)
        for subset in subsets:
            subsets_by_model[subset['system_id']].append(subset)

        # 4. Load daily signal (champion model — signal is about market conditions)
        daily_signal = self._query_daily_signal(game_date)
        signal_value = daily_signal.get('daily_signal') if daily_signal else None
        pct_over_value = daily_signal.get('pct_over') if daily_signal else None

        # 5. Process each model's subsets
        rows = []
        subsets_summary = {}
        total_predictions_available = 0

        for system_id, model_subsets in subsets_by_model.items():
            # Split subsets into quality-filtered (regular) vs unfiltered (all_predictions)
            regular_subsets = [s for s in model_subsets if 'all_predictions' not in s['subset_id']]
            unfiltered_subsets = [s for s in model_subsets if 'all_predictions' in s['subset_id']]

            # Regular subsets: quality >= 85 filter (existing behavior, unchanged)
            if regular_subsets:
                predictions = self._query_all_predictions(game_date, system_id)
                if predictions:
                    total_predictions_available += len(predictions)
                    for subset in regular_subsets:
                        self._process_subset(
                            subset, predictions, daily_signal, signal_value, pct_over_value,
                            game_date, system_id, version_id, computed_at, trigger_source,
                            batch_id, rows, subsets_summary,
                        )
                else:
                    logger.info(f"No predictions for {game_date} from {system_id}")

            # All Predictions subsets: no quality filter (min_quality=0)
            if unfiltered_subsets:
                all_preds = self._query_all_predictions(game_date, system_id, min_quality=0)
                if all_preds:
                    if not regular_subsets:
                        total_predictions_available += len(all_preds)
                    for subset in unfiltered_subsets:
                        self._process_subset(
                            subset, all_preds, daily_signal, signal_value, pct_over_value,
                            game_date, system_id, version_id, computed_at, trigger_source,
                            batch_id, rows, subsets_summary,
                        )
                else:
                    logger.info(f"No unfiltered predictions for {game_date} from {system_id}")

        # 6. Write to BigQuery (append-only, no deletes or updates)
        if rows:
            self._write_rows(rows)

        total_picks = len(rows)
        logger.info(
            f"Materialized {total_picks} picks across {len(subsets_summary)} subsets "
            f"({len(subsets_by_model)} models) for {game_date} (version={version_id}, "
            f"predictions_available={total_predictions_available}, "
            f"signal={signal_value})"
        )

        return {
            'version_id': version_id,
            'game_date': game_date,
            'total_picks': total_picks,
            'total_predictions_available': total_predictions_available,
            'daily_signal': signal_value,
            'subsets': subsets_summary,
            'status': 'success',
        }

    def _write_rows(self, rows: List[Dict[str, Any]]) -> None:
        """Write rows to current_subset_picks using streaming insert (append-only)."""
        # Convert Decimal types to float for JSON serialization
        cleaned_rows = []
        for row in rows:
            cleaned = {}
            for k, v in row.items():
                cleaned[k] = float(v) if isinstance(v, Decimal) else v
            cleaned_rows.append(cleaned)

        errors = self.bq_client.insert_rows_json(self.table_id, cleaned_rows)
        if errors:
            logger.error(f"Errors inserting subset picks: {errors}")
            raise RuntimeError(f"BigQuery insert errors: {errors}")
        logger.info(f"Inserted {len(cleaned_rows)} rows to {self.table_id}")

    def _query_subset_definitions(self) -> List[Dict[str, Any]]:
        """Query all active subset definitions (all models)."""
        query = """
        SELECT
          subset_id,
          subset_name,
          subset_description,
          system_id,
          use_ranking,
          top_n,
          min_edge,
          min_confidence,
          signal_condition,
          direction,
          pct_over_min,
          pct_over_max,
          is_active
        FROM `nba_predictions.dynamic_subset_definitions`
        WHERE is_active = TRUE
        ORDER BY system_id, subset_id
        """
        job_config = bigquery.QueryJobConfig()
        result = self.bq_client.query(query, job_config=job_config).result(timeout=60)
        return [dict(row) for row in result]

    def _query_active_system_ids(self, game_date: str) -> List[str]:
        """Query distinct system_ids that have predictions for this game date."""
        query = """
        SELECT DISTINCT system_id
        FROM `nba_predictions.player_prop_predictions`
        WHERE game_date = @game_date
          AND is_active = TRUE
          AND recommendation IN ('OVER', 'UNDER')
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
            ]
        )
        try:
            result = self.bq_client.query(query, job_config=job_config).result(timeout=30)
            return [row['system_id'] for row in result]
        except Exception as e:
            logger.error(f"Failed to query active system_ids: {e}")
            return []

    def _resolve_stale_system_ids(
        self,
        subsets: List[Dict[str, Any]],
        active_system_ids: List[str],
    ) -> List[Dict[str, Any]]:
        """Resolve stale system_ids in definitions to currently active ones.

        Uses family-based classification: if a definition references
        'catboost_v9_q43_train1102_0131' but predictions use
        'catboost_v9_q43_train1102_0125', both classify to family 'v9_q43',
        so the definition is updated to use the active system_id.

        Session 311: Fixes Q43/Q45 subsets silently producing 0 picks.
        """
        # Build family → active_system_id map
        family_to_active = {}
        for sid in active_system_ids:
            family = classify_system_id(sid)
            if family:
                family_to_active[family] = sid

        active_set = set(active_system_ids)
        resolved_count = 0

        for subset in subsets:
            def_sid = subset['system_id']
            if def_sid in active_set:
                continue  # Already matches an active system_id

            # Classify the definition's system_id to a family
            family = classify_system_id(def_sid)
            if family and family in family_to_active:
                new_sid = family_to_active[family]
                logger.info(
                    f"Resolved stale system_id '{def_sid}' → '{new_sid}' "
                    f"(family={family}) for subset '{subset['subset_id']}'"
                )
                subset['system_id'] = new_sid
                resolved_count += 1

        if resolved_count:
            logger.info(f"Resolved {resolved_count} stale system_id(s) in subset definitions")

        return subsets

    def _query_all_predictions(self, game_date: str, system_id: str = CHAMPION_SYSTEM_ID, min_quality: float = None) -> List[Dict[str, Any]]:
        """
        Query all active predictions for a date and model with full provenance.

        Includes data quality fields from predictions for subset-level tracking.

        Args:
            game_date: Date string in YYYY-MM-DD format
            system_id: Model system_id to query
            min_quality: Minimum feature quality score. Defaults to MIN_FEATURE_QUALITY_SCORE (85).
                         Pass 0 for unfiltered "all predictions" subsets.
        """
        min_quality = min_quality if min_quality is not None else MIN_FEATURE_QUALITY_SCORE
        query = """
        WITH player_names AS (
          SELECT player_lookup, player_name
          FROM `nba_reference.nba_players_registry`
          QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        ),
        -- Session 191: Fall back to upcoming_player_game_context for pre-game dates
        -- Session 226: Use ROW_NUMBER to deduplicate — UNION ALL caused 2x duplication
        -- when player exists in both player_game_summary AND upcoming_player_game_context
        team_info AS (
          SELECT player_lookup, team_abbr, opponent_team_abbr, game_date
          FROM (
            SELECT player_lookup, team_abbr, opponent_team_abbr, game_date,
                   ROW_NUMBER() OVER (PARTITION BY player_lookup, game_date
                                      ORDER BY source_priority) as rn
            FROM (
              SELECT player_lookup, team_abbr, opponent_team_abbr, game_date,
                     1 as source_priority
              FROM `nba_analytics.player_game_summary`
              WHERE game_date = @game_date
              UNION ALL
              SELECT player_lookup, team_abbr, opponent_team_abbr, game_date,
                     2 as source_priority
              FROM `nba_analytics.upcoming_player_game_context`
              WHERE game_date = @game_date
            )
          )
          WHERE rn = 1
        )
        SELECT
          p.prediction_id,
          p.game_id,
          p.player_lookup,
          COALESCE(pn.player_name, p.player_lookup) as player_name,
          ti.team_abbr as team,
          ti.opponent_team_abbr as opponent,
          p.predicted_points,
          p.current_points_line,
          p.recommendation,
          p.confidence_score,
          ABS(p.predicted_points - p.current_points_line) as edge,
          (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) as composite_score,
          -- Quality provenance
          COALESCE(f.feature_quality_score, 0) as feature_quality_score,
          p.default_feature_count,
          p.line_source,
          p.prediction_run_mode,
          p.prediction_made_before_game,
          p.quality_alert_level
        FROM `nba_predictions.player_prop_predictions` p
        LEFT JOIN player_names pn
          ON p.player_lookup = pn.player_lookup
        LEFT JOIN team_info ti
          ON p.player_lookup = ti.player_lookup
          AND p.game_date = ti.game_date
        LEFT JOIN `nba_predictions.ml_feature_store_v2` f
          ON p.player_lookup = f.player_lookup
          AND p.game_date = f.game_date
        WHERE p.game_date = @game_date
          AND p.system_id = @system_id
          AND p.is_active = TRUE
          AND p.recommendation IN ('OVER', 'UNDER')
          AND p.current_points_line IS NOT NULL
          AND ti.team_abbr IS NOT NULL
          AND COALESCE(f.feature_quality_score, 0) >= @min_quality
          -- Session 170: Filter to current model_version to prevent stale predictions leaking
          AND p.model_version = (
            SELECT model_version
            FROM `nba_predictions.player_prop_predictions`
            WHERE game_date = @game_date AND system_id = @system_id
              AND is_active = TRUE AND current_points_line IS NOT NULL
            GROUP BY model_version ORDER BY COUNT(*) DESC LIMIT 1
          )
        ORDER BY composite_score DESC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
                bigquery.ScalarQueryParameter('system_id', 'STRING', system_id),
                bigquery.ScalarQueryParameter('min_quality', 'FLOAT64', min_quality),
            ]
        )
        result = self.bq_client.query(query, job_config=job_config).result(timeout=60)
        return [dict(row) for row in result]

    def _query_daily_signal(self, game_date: str) -> Optional[Dict[str, Any]]:
        """Query daily signal from champion model (signal reflects market conditions, not model-specific)."""
        query = """
        SELECT game_date, daily_signal, pct_over
        FROM `nba_predictions.daily_prediction_signals`
        WHERE game_date = @game_date
          AND system_id = @system_id
        LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
                bigquery.ScalarQueryParameter('system_id', 'STRING', CHAMPION_SYSTEM_ID),
            ]
        )
        result = self.bq_client.query(query, job_config=job_config).result(timeout=60)
        rows = [dict(row) for row in result]
        return rows[0] if rows else None

    def _filter_picks_for_subset(
        self,
        predictions: List[Dict[str, Any]],
        subset: Dict[str, Any],
        daily_signal: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Filter predictions based on subset criteria.

        Same logic as AllSubsetsPicksExporter._filter_picks_for_subset.
        """
        filtered = []

        signal = daily_signal.get('daily_signal') if daily_signal else None
        pct_over = daily_signal.get('pct_over') if daily_signal else None

        for pred in predictions:
            if subset.get('min_edge'):
                if pred['edge'] < float(subset['min_edge']):
                    continue

            if subset.get('min_confidence'):
                if pred['confidence_score'] < float(subset['min_confidence']):
                    continue

            # Direction filter (OVER, UNDER, or ANY/None = no filter)
            direction = subset.get('direction')
            if direction and direction not in ('ANY', None):
                if pred['recommendation'] != direction:
                    continue

            # Signal filter (only applied when we have both a condition and actual signal data)
            signal_condition = subset.get('signal_condition')
            if signal_condition and signal_condition != 'ANY' and signal:
                if signal_condition == 'GREEN_OR_YELLOW':
                    if signal not in ('GREEN', 'YELLOW'):
                        continue
                elif signal != signal_condition:
                    continue

            if pct_over is not None:
                pct_over_min = subset.get('pct_over_min')
                pct_over_max = subset.get('pct_over_max')

                if pct_over_min is not None and pct_over < float(pct_over_min):
                    continue
                if pct_over_max is not None and pct_over > float(pct_over_max):
                    continue

            # Session 209: Quality filter using shared utility
            # Predictions with yellow/red quality alerts have 12.1% hit rate vs 50.3% for green
            if not should_include_prediction(pred, subset):
                continue

            filtered.append(pred)

        if subset.get('top_n'):
            top_n = int(subset['top_n'])
            filtered = filtered[:top_n]

        # Add rank_in_subset (1-indexed position within this subset)
        for i, pick in enumerate(filtered):
            pick['rank_in_subset'] = i + 1

        return filtered

    def _process_subset(
        self,
        subset: Dict[str, Any],
        predictions: List[Dict[str, Any]],
        daily_signal: Optional[Dict[str, Any]],
        signal_value: Optional[str],
        pct_over_value: Optional[float],
        game_date: str,
        system_id: str,
        version_id: str,
        computed_at: datetime,
        trigger_source: str,
        batch_id: Optional[str],
        rows: List[Dict[str, Any]],
        subsets_summary: Dict[str, Any],
    ) -> None:
        """Filter predictions for a subset and append materialized rows."""
        subset_id = subset['subset_id']
        filtered = self._filter_picks_for_subset(predictions, subset, daily_signal)

        public = get_public_name(subset_id)

        for pick in filtered:
            rows.append({
                'game_date': game_date,
                'subset_id': subset_id,
                'player_lookup': pick['player_lookup'],
                'prediction_id': pick.get('prediction_id'),
                'game_id': pick.get('game_id'),
                'rank_in_subset': pick.get('rank_in_subset'),
                'system_id': system_id,
                'version_id': version_id,
                'computed_at': computed_at.isoformat(),
                'trigger_source': trigger_source,
                'batch_id': batch_id,
                # Denormalized pick data
                'player_name': pick['player_name'],
                'team': pick['team'],
                'opponent': pick['opponent'],
                'predicted_points': pick['predicted_points'],
                'current_points_line': pick['current_points_line'],
                'recommendation': pick['recommendation'],
                'confidence_score': pick['confidence_score'],
                'edge': pick['edge'],
                'composite_score': pick['composite_score'],
                # Data quality provenance
                'feature_quality_score': pick['feature_quality_score'],
                'default_feature_count': pick.get('default_feature_count'),
                'line_source': pick.get('line_source'),
                'prediction_run_mode': pick.get('prediction_run_mode'),
                'prediction_made_before_game': pick.get('prediction_made_before_game'),
                'quality_alert_level': pick.get('quality_alert_level'),
                # Subset metadata
                'subset_name': public['name'],
                'min_edge': float(subset['min_edge']) if subset.get('min_edge') else None,
                'min_confidence': float(subset['min_confidence']) if subset.get('min_confidence') else None,
                'top_n': int(subset['top_n']) if subset.get('top_n') else None,
                # Version-level context
                'daily_signal': signal_value,
                'pct_over': pct_over_value,
                'total_predictions_available': len(predictions),
            })

        subsets_summary[subset_id] = {
            'name': public['name'],
            'picks': len(filtered),
            'system_id': system_id,
        }
