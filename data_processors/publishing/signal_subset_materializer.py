"""Signal Subset Materializer for Phase 6 Publishing.

Materializes pick-level signal subsets to current_subset_picks. Unlike the
regular SubsetMaterializer (which filters on edge/confidence/direction), this
filters on which signals fired for each pick.

Only curated for the strongest signals — NOT one subset per signal.

Session 311: Initial creation.

Design:
    - Called AFTER signal evaluation (in signal_best_bets_exporter flow)
    - Takes pre-computed signal_results (from registry evaluation)
    - Writes to same current_subset_picks table as other materializers
    - Graded by existing SubsetGradingProcessor (agnostic to system_id)

Signal Subsets:
    - signal_combo_he_ms: High Edge + Minutes Surge combo (94.9% HR)
    - signal_combo_3way: ESO + HE + MS triple combo (95.5% HR, OVER only)
    - signal_bench_under: Bench UNDER pattern (76.9% HR)
    - signal_high_count: 4+ qualifying signals (85.7% HR)
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from google.cloud import bigquery

from shared.clients.bigquery_pool import get_bigquery_client
from shared.config.gcp_config import get_project_id
from shared.config.subset_public_names import get_public_name

logger = logging.getLogger(__name__)

PROJECT_ID = get_project_id()
SUBSET_TABLE_ID = f'{PROJECT_ID}.nba_predictions.current_subset_picks'

# Signal subset definitions — curated for strongest patterns only
SIGNAL_SUBSETS = {
    'signal_combo_he_ms': {
        'name': 'Combo HE+MS',
        'description': 'Picks where combo_he_ms fires (High Edge + Minutes Surge). 94.9% HR.',
        'required_signals': {'combo_he_ms'},
        'min_edge': 5.0,
        'direction': None,  # ANY
        'top_n': None,
    },
    'signal_combo_3way': {
        'name': 'Combo 3-Way',
        'description': 'Picks where combo_3way fires (ESO + HE + MS). 95.5% HR, OVER only.',
        'required_signals': {'combo_3way'},
        'min_edge': 5.0,
        'direction': 'OVER',
        'top_n': None,
    },
    'signal_bench_under': {
        'name': 'Bench UNDER',
        'description': 'Picks where bench_under fires + edge >= 5. 76.9% HR.',
        'required_signals': {'bench_under'},
        'min_edge': 5.0,
        'direction': 'UNDER',
        'top_n': None,
    },
    'signal_high_count': {
        'name': 'High Signal Count',
        'description': 'Picks with 4+ qualifying signals + edge >= 5. 85.7% HR.',
        'required_signals': set(),  # No specific signal required
        'min_signal_count': 4,
        'min_edge': 5.0,
        'direction': None,
        'top_n': None,
    },
}


class SignalSubsetMaterializer:
    """Compute signal-based subsets and write to current_subset_picks.

    Runs AFTER signal evaluation. Takes the signal_results dict from
    registry evaluation and the predictions list, applies signal-based
    filters, and writes qualifying picks to current_subset_picks.
    """

    def __init__(self, project_id: str = None):
        self.project_id = project_id or PROJECT_ID
        self.bq_client = get_bigquery_client(project_id=self.project_id)

    def materialize(
        self,
        game_date: str,
        version_id: str,
        predictions: List[Dict[str, Any]],
        signal_results: Dict[str, List],
        trigger_source: str = 'signal_best_bets',
    ) -> Dict[str, Any]:
        """Compute signal subsets and write to current_subset_picks.

        Args:
            game_date: Date string YYYY-MM-DD.
            version_id: Version ID from SubsetMaterializer (same batch).
            predictions: List of prediction dicts (from supplemental query).
            signal_results: Dict keyed by 'player_lookup::game_id' with list
                of SignalResult objects from signal evaluation.
            trigger_source: What triggered this materialization.

        Returns:
            Dict with subset counts summary.
        """
        computed_at = datetime.now(timezone.utc)
        rows = []
        subsets_summary = {}

        for subset_id, config in SIGNAL_SUBSETS.items():
            matching = self._apply_filter(
                subset_id, config, predictions, signal_results
            )

            public = get_public_name(subset_id)

            for rank, pick in enumerate(matching, 1):
                rows.append({
                    'game_date': game_date,
                    'subset_id': subset_id,
                    'player_lookup': pick['player_lookup'],
                    'prediction_id': None,
                    'game_id': pick.get('game_id', ''),
                    'rank_in_subset': rank,
                    'system_id': pick.get('system_id', 'signal_subset'),
                    'version_id': version_id,
                    'computed_at': computed_at.isoformat(),
                    'trigger_source': trigger_source,
                    'batch_id': None,
                    'player_name': pick.get('player_name', ''),
                    'team': pick.get('team_abbr', ''),
                    'opponent': pick.get('opponent_team_abbr', ''),
                    'predicted_points': pick.get('predicted_points'),
                    'current_points_line': pick.get('line_value'),
                    'recommendation': pick.get('recommendation', ''),
                    'confidence_score': pick.get('confidence_score'),
                    'edge': pick.get('edge'),
                    'composite_score': abs(pick.get('edge') or 0),
                    'signal_tags': pick.get('_signal_tags', []),
                    'signal_count': pick.get('_signal_count', 0),
                    'matched_combo_id': None,
                    'combo_classification': None,
                    'combo_hit_rate': None,
                    'model_health_status': None,
                    'warning_tags': [],
                    'feature_quality_score': pick.get('feature_quality_score'),
                    'default_feature_count': None,
                    'line_source': None,
                    'prediction_run_mode': None,
                    'prediction_made_before_game': None,
                    'quality_alert_level': None,
                    'subset_name': public['name'],
                    'min_edge': config.get('min_edge'),
                    'min_confidence': None,
                    'top_n': config.get('top_n'),
                    'daily_signal': None,
                    'pct_over': None,
                    'total_predictions_available': len(predictions),
                })

            subsets_summary[subset_id] = len(matching)
            if matching:
                logger.info(f"  signal_subset {subset_id}: {len(matching)} picks")

        # Delete existing signal subset rows for this date, then write new ones
        if rows:
            self._delete_existing(game_date)
            self._write_rows(rows)

        total = len(rows)
        logger.info(
            f"Signal subsets materialized {total} picks across "
            f"{len([v for v in subsets_summary.values() if v > 0])} subsets "
            f"for {game_date}"
        )

        return {
            'total_picks': total,
            'subsets': subsets_summary,
        }

    def _apply_filter(
        self,
        subset_id: str,
        config: Dict[str, Any],
        predictions: List[Dict[str, Any]],
        signal_results: Dict[str, List],
    ) -> List[Dict[str, Any]]:
        """Apply a signal-based filter and return qualifying picks."""
        results = []
        min_edge = config.get('min_edge', 0)
        required_signals = config.get('required_signals', set())
        min_signal_count = config.get('min_signal_count', 0)
        required_direction = config.get('direction')

        for pred in predictions:
            # Edge filter
            pred_edge = abs(pred.get('edge') or 0)
            if pred_edge < min_edge:
                continue

            # Direction filter
            if required_direction and pred.get('recommendation') != required_direction:
                continue

            # Get signal results for this pick
            key = f"{pred['player_lookup']}::{pred['game_id']}"
            pick_signals = signal_results.get(key, [])
            qualifying_tags = {r.source_tag for r in pick_signals if r.qualifies}

            # Required signals filter
            if required_signals and not required_signals.issubset(qualifying_tags):
                continue

            # Min signal count filter
            if min_signal_count > 0 and len(qualifying_tags) < min_signal_count:
                continue

            # Enrich pick with signal metadata for storage
            pick = {**pred, '_signal_tags': sorted(qualifying_tags), '_signal_count': len(qualifying_tags)}
            results.append(pick)

        # Sort by edge descending
        results.sort(key=lambda x: abs(x.get('edge') or 0), reverse=True)

        # Apply top_n limit
        top_n = config.get('top_n')
        if top_n and len(results) > top_n:
            results = results[:top_n]

        return results

    def _delete_existing(self, game_date: str) -> None:
        """Delete existing signal subset rows for this date."""
        signal_subset_ids = list(SIGNAL_SUBSETS.keys())
        placeholders = ', '.join(f"'{sid}'" for sid in signal_subset_ids)
        try:
            query = f"""
            DELETE FROM `{SUBSET_TABLE_ID}`
            WHERE game_date = @game_date
              AND subset_id IN ({placeholders})
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
                ]
            )
            job = self.bq_client.query(query, job_config=job_config)
            job.result(timeout=30)
            deleted = job.num_dml_affected_rows or 0
            if deleted > 0:
                logger.info(
                    f"Deleted {deleted} existing signal subset rows for {game_date}"
                )
        except Exception as e:
            logger.warning(
                f"Failed to delete existing signal subset rows for {game_date}: {e}"
            )

    def _write_rows(self, rows: List[Dict[str, Any]]) -> None:
        """Write signal subset rows using streaming insert."""
        from decimal import Decimal
        try:
            # Convert Decimal types to float for JSON serialization
            cleaned_rows = [
                {k: float(v) if isinstance(v, Decimal) else v for k, v in row.items()}
                for row in rows
            ]
            errors = self.bq_client.insert_rows_json(SUBSET_TABLE_ID, cleaned_rows)
            if errors:
                logger.error(f"Errors writing signal subsets: {errors}")
            else:
                logger.info(
                    f"Wrote {len(rows)} signal subset rows to {SUBSET_TABLE_ID}"
                )
        except Exception as e:
            logger.error(
                f"Failed to write signal subsets: {e}", exc_info=True
            )
