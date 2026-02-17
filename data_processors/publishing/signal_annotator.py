"""
Signal Annotator for Phase 6 Publishing

Evaluates signals on ALL active predictions and writes signal tags to
the `pick_signal_tags` BigQuery table. This runs AFTER SubsetMaterializer
and BEFORE AllSubsetsPicksExporter, so the exporter can LEFT JOIN
signal tags onto every pick in every subset.

Fail-safe: if annotation fails, the exporter still works — picks just
don't have signal badges.

Design: batch load (not streaming) to avoid 90-min DML buffer.

Version: 1.0
Created: 2026-02-14 (Session 254)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import bigquery

from shared.clients.bigquery_pool import get_bigquery_client
from shared.config.gcp_config import get_project_id
from shared.config.model_selection import get_best_bets_model_id
from shared.config.subset_public_names import get_public_name
from ml.signals.registry import build_default_registry
from ml.signals.aggregator import BestBetsAggregator
from ml.signals.combo_registry import load_combo_registry, match_combo
from ml.signals.model_health import BREAKEVEN_HR
from ml.signals.signal_health import get_signal_health_summary
from ml.signals.cross_model_scorer import CrossModelScorer
from ml.signals.pick_angle_builder import build_pick_angles
from ml.signals.subset_membership_lookup import lookup_qualifying_subsets
from ml.signals.aggregator import ALGORITHM_VERSION
from ml.signals.supplemental_data import (
    query_model_health,
    query_predictions_with_supplements,
)

logger = logging.getLogger(__name__)

PROJECT_ID = get_project_id()
TABLE_ID = f'{PROJECT_ID}.nba_predictions.pick_signal_tags'
SUBSET_TABLE_ID = f'{PROJECT_ID}.nba_predictions.current_subset_picks'
SIGNAL_PICKS_SUBSET_ID = 'best_bets'


class SignalAnnotator:
    """Evaluate signals on all predictions and write to pick_signal_tags.

    Unlike the BestBetsAggregator (top 5 picks), this writes a row for
    EVERY active prediction — even those with signal_tags = [].
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.bq_client = get_bigquery_client(project_id=project_id)

    def annotate(
        self,
        target_date: str,
        version_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Evaluate signals on all predictions and write results.

        Args:
            target_date: Date string in YYYY-MM-DD format.
            version_id: Optional version_id to correlate with current_subset_picks.

        Returns:
            Dict with annotation summary.
        """
        # 1. Query model health
        model_health = query_model_health(self.bq_client)
        hr_7d = model_health.get('hit_rate_7d_edge3')

        health_status = 'unknown'
        if hr_7d is not None:
            if hr_7d < BREAKEVEN_HR:
                health_status = 'blocked'
            elif hr_7d < 58.0:
                health_status = 'watch'
            else:
                health_status = 'healthy'

        # 2. Query predictions + supplemental data
        predictions, supplemental_map = query_predictions_with_supplements(
            self.bq_client, target_date
        )

        if not predictions:
            logger.info(f"No predictions to annotate for {target_date}")
            return {
                'target_date': target_date,
                'total_predictions': 0,
                'annotated': 0,
                'with_signals': 0,
                'model_health': health_status,
            }

        # 3. Evaluate signals on every prediction
        registry = build_default_registry()
        combo_registry = load_combo_registry(bq_client=self.bq_client)
        rows_to_write: List[Dict[str, Any]] = []
        signal_results_map: Dict[str, List] = {}  # for aggregator bridge

        for pred in predictions:
            supplements = supplemental_map.get(pred['player_lookup'], {})
            supplements['model_health'] = {'hit_rate_7d_edge3': hr_7d}

            qualifying_tags = []
            all_results = []
            for signal in registry.all():
                result = signal.evaluate(pred, features=None, supplemental=supplements)
                all_results.append(result)
                if result.qualifies and signal.tag != 'model_health':
                    qualifying_tags.append(result.source_tag)

            key = f"{pred['player_lookup']}::{pred['game_id']}"
            signal_results_map[key] = all_results

            # Match combo from registry for annotation
            matched = match_combo(qualifying_tags, combo_registry) if qualifying_tags else None

            rows_to_write.append({
                'game_date': target_date,
                'player_lookup': pred['player_lookup'],
                'system_id': pred['system_id'],
                'game_id': pred.get('game_id'),
                'signal_tags': qualifying_tags,  # [] not None (ARRAY cannot be NULL)
                'signal_count': len(qualifying_tags),
                'matched_combo_id': matched.combo_id if matched else None,
                'combo_classification': matched.classification if matched else None,
                'combo_hit_rate': matched.hit_rate if matched else None,
                'model_health_status': health_status,
                'model_health_hr_7d': hr_7d,
                'evaluated_at': datetime.now(timezone.utc).isoformat(),
                'version_id': version_id,
            })

        # 4. Write annotations to BigQuery (batch load, not streaming)
        with_signals = sum(1 for r in rows_to_write if r['signal_count'] > 0)
        self._write_rows(rows_to_write)

        # 4b. Get signal health for aggregator weighting
        signal_health = get_signal_health_summary(self.bq_client, target_date)

        # 4c. Compute cross-model consensus factors (Session 277)
        cross_model_factors = {}
        try:
            scorer = CrossModelScorer()
            cross_model_factors = scorer.compute_factors(
                self.bq_client, target_date, self.project_id
            )
        except Exception as e:
            logger.warning(f"Cross-model scoring failed (non-fatal): {e}")

        # 4d. Look up qualifying subsets (Session 279 — pick provenance)
        qual_subsets = {}
        if version_id:
            try:
                qual_subsets = lookup_qualifying_subsets(
                    self.bq_client, target_date, version_id, self.project_id
                )
            except Exception as e:
                logger.warning(f"Qualifying subsets lookup failed (non-fatal): {e}")

        # 5. Bridge: run aggregator and write Signal Picks subset
        # Note: Health gate removed (Session 270) — always produce signal picks
        signal_picks_count = self._bridge_signal_picks(
            predictions, signal_results_map, target_date,
            version_id, health_status, combo_registry,
            signal_health=signal_health,
            cross_model_factors=cross_model_factors,
            qualifying_subsets=qual_subsets,
        )

        logger.info(
            f"Annotated {len(rows_to_write)} predictions for {target_date}: "
            f"{with_signals} with signals, {signal_picks_count} signal picks, "
            f"health={health_status}"
        )

        return {
            'target_date': target_date,
            'total_predictions': len(predictions),
            'annotated': len(rows_to_write),
            'with_signals': with_signals,
            'signal_picks': signal_picks_count,
            'model_health': health_status,
            'version_id': version_id,
        }

    def _write_rows(self, rows: List[Dict[str, Any]]) -> None:
        """Write annotation rows using batch load."""
        if not rows:
            return

        try:
            job_config = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
            )
            load_job = self.bq_client.load_table_from_json(
                rows, TABLE_ID, job_config=job_config
            )
            load_job.result(timeout=60)
            logger.info(f"Batch-loaded {len(rows)} signal annotations to {TABLE_ID}")
        except Exception as e:
            logger.error(
                f"Failed to write signal annotations to BigQuery: {e}",
                exc_info=True,
            )
            raise

    def _bridge_signal_picks(
        self,
        predictions: List[Dict],
        signal_results_map: Dict[str, List],
        target_date: str,
        version_id: Optional[str],
        health_status: str,
        combo_registry=None,
        signal_health: Optional[Dict] = None,
        cross_model_factors: Optional[Dict] = None,
        qualifying_subsets: Optional[Dict] = None,
    ) -> int:
        """Bridge aggregator's top picks into current_subset_picks as Signal Picks subset.

        Returns:
            Number of signal picks written.
        """
        aggregator = BestBetsAggregator(
            combo_registry=combo_registry,
            signal_health=signal_health,
            model_id=get_best_bets_model_id(),
            cross_model_factors=cross_model_factors,
            qualifying_subsets=qualifying_subsets,
        )
        top_picks = aggregator.aggregate(predictions, signal_results_map)

        if not top_picks:
            logger.info(f"No signal picks to bridge for {target_date}")
            return 0

        # Build pick angles (Session 278)
        for pick in top_picks:
            key = f"{pick['player_lookup']}::{pick['game_id']}"
            xm = cross_model_factors.get(key, {}) if cross_model_factors else {}
            pick['pick_angles'] = build_pick_angles(
                pick, signal_results_map.get(key, []), xm
            )

        public = get_public_name(SIGNAL_PICKS_SUBSET_ID)
        computed_at = datetime.now(timezone.utc)

        subset_rows = []
        for pick in top_picks:
            subset_rows.append({
                'game_date': target_date,
                'subset_id': SIGNAL_PICKS_SUBSET_ID,
                'player_lookup': pick['player_lookup'],
                'prediction_id': None,
                'game_id': pick.get('game_id'),
                'rank_in_subset': pick.get('rank'),
                'system_id': pick.get('system_id', get_best_bets_model_id()),
                'version_id': version_id or f"v_{computed_at.strftime('%Y%m%d_%H%M%S')}",
                'computed_at': computed_at.isoformat(),
                'trigger_source': 'signal_annotator',
                'batch_id': None,
                # Denormalized pick data
                'player_name': pick.get('player_name', ''),
                'team': pick.get('team_abbr', ''),
                'opponent': pick.get('opponent_team_abbr', ''),
                'predicted_points': pick.get('predicted_points'),
                'current_points_line': pick.get('line_value'),
                'recommendation': pick.get('recommendation', ''),
                'confidence_score': pick.get('confidence_score'),
                'edge': pick.get('edge'),
                'composite_score': pick.get('composite_score'),
                # Signal context (Session 270: why this pick was selected)
                'signal_tags': pick.get('signal_tags', []),
                'signal_count': pick.get('signal_count', 0),
                'matched_combo_id': pick.get('matched_combo_id'),
                'combo_classification': pick.get('combo_classification'),
                'combo_hit_rate': pick.get('combo_hit_rate'),
                'model_health_status': health_status,
                'warning_tags': pick.get('warning_tags', []),
                'pick_angles': pick.get('pick_angles', []),
                # Qualifying subsets provenance (Session 279)
                'qualifying_subsets': json.dumps(pick.get('qualifying_subsets', [])),
                'qualifying_subset_count': pick.get('qualifying_subset_count', 0),
                'algorithm_version': pick.get('algorithm_version', ALGORITHM_VERSION),
                # Quality provenance (not available here, set to None)
                'feature_quality_score': None,
                'default_feature_count': None,
                'line_source': None,
                'prediction_run_mode': None,
                'prediction_made_before_game': None,
                'quality_alert_level': None,
                # Subset metadata
                'subset_name': public['name'],
                'min_edge': None,
                'min_confidence': None,
                'top_n': BestBetsAggregator.MAX_PICKS_PER_DAY,
                # Version-level context
                'daily_signal': None,
                'pct_over': None,
                'total_predictions_available': len(predictions),
            })

        try:
            # Use streaming insert (same as SubsetMaterializer — append-only table)
            errors = self.bq_client.insert_rows_json(SUBSET_TABLE_ID, subset_rows)
            if errors:
                logger.error(f"Errors bridging signal picks to subsets: {errors}")
            else:
                logger.info(
                    f"Bridged {len(subset_rows)} signal picks to {SUBSET_TABLE_ID} "
                    f"for {target_date}"
                )
        except Exception as e:
            logger.error(
                f"Failed to bridge signal picks to subsets: {e}",
                exc_info=True,
            )
            return 0

        return len(subset_rows)
