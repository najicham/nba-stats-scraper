"""
Signal Best Bets Exporter for Phase 6 Publishing

Runs the Signal Discovery Framework against today's predictions and exports
a curated list of up to 5 best bets to GCS. Also writes picks to
the `signal_best_bets_picks` BigQuery table for grading.

Pipeline: Phase 5 → Phase 6 Export → signal-best-bets
Output: v1/signal-best-bets/{date}.json

Version: 1.0
Created: 2026-02-14 (Session 254)
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import bigquery

from data_processors.publishing.base_exporter import BaseExporter
from ml.signals.registry import build_default_registry
from ml.signals.aggregator import BestBetsAggregator
from ml.signals.combo_registry import load_combo_registry
from ml.signals.model_health import BREAKEVEN_HR
from ml.signals.signal_health import get_signal_health_summary
from ml.signals.supplemental_data import (
    query_model_health,
    query_predictions_with_supplements,
)
from shared.config.model_selection import get_best_bets_model_id

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


class SignalBestBetsExporter(BaseExporter):
    """
    Export signal-curated best bets to GCS and BigQuery.

    Steps:
    1. Query model health (rolling 7d HR)
    2. If model healthy, query today's predictions + supplemental data
    3. Run all signals via registry
    4. Aggregate to top 5 picks
    5. Write to BigQuery `signal_best_bets_picks`
    6. Export to GCS `v1/signal-best-bets/{date}.json`
    """

    def generate_json(self, target_date: str, **kwargs) -> Dict[str, Any]:
        """Generate signal best bets JSON for a specific date."""
        # Step 1: Query model health
        model_health = self._query_model_health()
        hr_7d = model_health.get('hit_rate_7d_edge3')

        health_status = 'unknown'
        if hr_7d is not None:
            if hr_7d < BREAKEVEN_HR:
                health_status = 'blocked'
            elif hr_7d < 58.0:
                health_status = 'watch'
            else:
                health_status = 'healthy'

        # Note: Health gate removed (Session 270). Model health is informational
        # only — the 2-signal minimum provides sufficient quality filtering.
        if health_status == 'blocked':
            logger.info(
                f"Model health below breakeven for {target_date}: "
                f"HR 7d = {hr_7d:.1f}% < {BREAKEVEN_HR}% — picks still generated"
            )

        # Step 2: Query predictions and supplemental data
        predictions, supplemental_map = self._query_predictions_and_supplements(
            target_date
        )

        if not predictions:
            logger.info(f"No predictions found for {target_date}")
            return {
                'date': target_date,
                'generated_at': self.get_generated_at(),
                'model_health': {
                    'status': health_status,
                    'hit_rate_7d': hr_7d,
                    'graded_count': model_health.get('graded_count', 0),
                },
                'picks': [],
                'total_picks': 0,
                'signals_evaluated': [],
            }

        # Step 4: Evaluate all signals
        registry = build_default_registry()
        signal_results = {}

        for pred in predictions:
            key = f"{pred['player_lookup']}::{pred['game_id']}"
            supplements = supplemental_map.get(pred['player_lookup'], {})
            # Inject model health into supplemental for the gate signal
            supplements['model_health'] = {
                'hit_rate_7d_edge3': hr_7d,
            }

            results_for_pred = []
            for signal in registry.all():
                result = signal.evaluate(pred, features=None, supplemental=supplements)
                results_for_pred.append(result)
            signal_results[key] = results_for_pred

        # Step 5: Get signal health (non-blocking — empty if table doesn't exist yet)
        signal_health = get_signal_health_summary(self.bq_client, target_date)

        # Step 6: Aggregate to top picks (with combo registry + signal health weighting)
        combo_registry = load_combo_registry(bq_client=self.bq_client)
        aggregator = BestBetsAggregator(
            combo_registry=combo_registry,
            signal_health=signal_health,
            model_id=get_best_bets_model_id(),
        )
        top_picks = aggregator.aggregate(predictions, signal_results)

        # Step 7: Format for JSON
        picks_json = []
        for pick in top_picks:
            picks_json.append({
                'rank': pick['rank'],
                'player': pick.get('player_name', ''),
                'player_lookup': pick['player_lookup'],
                'game_id': pick.get('game_id', ''),
                'team': pick.get('team_abbr', ''),
                'opponent': pick.get('opponent_team_abbr', ''),
                'prediction': pick.get('predicted_points'),
                'line': pick.get('line_value'),
                'direction': pick.get('recommendation', ''),
                'edge': pick.get('edge'),
                'confidence': pick.get('confidence_score'),
                'signals': pick.get('signal_tags', []),
                'signal_count': pick.get('signal_count', 0),
                'composite_score': pick.get('composite_score'),
                'matched_combo_id': pick.get('matched_combo_id'),
                'combo_classification': pick.get('combo_classification'),
                'combo_hit_rate': pick.get('combo_hit_rate'),
                'warnings': pick.get('warning_tags', []),
                'actual': None,
                'result': None,
            })

        return {
            'date': target_date,
            'generated_at': self.get_generated_at(),
            'min_signal_count': BestBetsAggregator.MIN_SIGNAL_COUNT,
            'model_health': {
                'status': health_status,
                'hit_rate_7d': hr_7d,
                'graded_count': model_health.get('graded_count', 0),
            },
            'signal_health': signal_health,
            'picks': picks_json,
            'total_picks': len(picks_json),
            'signals_evaluated': [
                s.tag for s in registry.all() if s.tag != 'model_health'
            ],
        }

    def export(self, target_date: str) -> str:
        """
        Generate signal best bets, write to BigQuery, and upload to GCS.

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            GCS path where file was uploaded
        """
        json_data = self.generate_json(target_date)

        # Write picks to BigQuery for grading tracking
        if json_data['picks']:
            self._write_to_bigquery(target_date, json_data['picks'])

        # Upload to GCS (date-specific)
        gcs_path = self.upload_to_gcs(
            json_data=json_data,
            path=f'signal-best-bets/{target_date}.json',
            cache_control='public, max-age=300',
        )

        # Also write latest.json for stable frontend URL
        try:
            self.upload_to_gcs(
                json_data=json_data,
                path='signal-best-bets/latest.json',
                cache_control='public, max-age=60',
            )
            logger.info("Wrote signal-best-bets/latest.json")
        except Exception as e:
            logger.warning(f"Failed to write latest.json (non-fatal): {e}")

        logger.info(
            f"Exported {json_data['total_picks']} signal best bets for {target_date} "
            f"(health={json_data['model_health']['status']}) to {gcs_path}"
        )

        return gcs_path

    # ── Private helpers ──────────────────────────────────────────────────

    def _query_model_health(self) -> Dict[str, Any]:
        """Query rolling 7-day hit rate for edge 3+ picks."""
        return query_model_health(self.bq_client)

    def _query_predictions_and_supplements(self, target_date: str) -> tuple:
        """Query today's active predictions with supplemental signal data."""
        return query_predictions_with_supplements(self.bq_client, target_date)

    def _write_to_bigquery(self, target_date: str, picks: List[Dict]) -> None:
        """Write signal best bets to BigQuery using batch load (not streaming).

        Uses load_table_from_json with WRITE_APPEND to avoid 90-min streaming
        buffer that blocks DML operations (codebase best practice).
        """
        table_ref = f'{PROJECT_ID}.nba_predictions.signal_best_bets_picks'

        rows_to_insert = []
        model_id = get_best_bets_model_id()
        for pick in picks:
            rows_to_insert.append({
                'player_lookup': pick['player_lookup'],
                'game_id': pick.get('game_id', ''),
                'game_date': target_date,
                'system_id': model_id,
                'player_name': pick.get('player', ''),
                'team_abbr': pick.get('team', ''),
                'opponent_team_abbr': pick.get('opponent', ''),
                'predicted_points': pick.get('prediction'),
                'line_value': pick.get('line'),
                'recommendation': pick.get('direction', ''),
                'edge': pick.get('edge'),
                'confidence_score': pick.get('confidence'),
                'signal_tags': pick.get('signals', []),
                'signal_count': pick.get('signal_count', 0),
                'composite_score': pick.get('composite_score'),
                'matched_combo_id': pick.get('matched_combo_id'),
                'combo_classification': pick.get('combo_classification'),
                'combo_hit_rate': pick.get('combo_hit_rate'),
                'warning_tags': pick.get('warnings', []),
                'rank': pick.get('rank'),
                'created_at': datetime.now(timezone.utc).isoformat(),
            })

        if not rows_to_insert:
            return

        try:
            job_config = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
            )
            load_job = self.bq_client.load_table_from_json(
                rows_to_insert, table_ref, job_config=job_config
            )
            load_job.result(timeout=60)
            logger.info(
                f"Batch-loaded {len(rows_to_insert)} rows into {table_ref} "
                f"for {target_date}"
            )
        except Exception as e:
            logger.error(
                f"Failed to write signal best bets to BigQuery: {e}",
                exc_info=True,
            )
