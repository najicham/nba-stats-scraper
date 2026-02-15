"""
Model Health Exporter for Phase 6 Publishing

Exports model performance state (HEALTHY/WATCH/DEGRADING/BLOCKED) to GCS
for frontend display. Enables model health banners and "sitting out" messaging
on playerprops.io.

Output: v1/systems/model-health.json

Created: 2026-02-15 (Session 267)
"""

import logging
from typing import Any, Dict, List

from google.cloud import bigquery

from .base_exporter import BaseExporter
from shared.config.model_selection import get_best_bets_model_id

logger = logging.getLogger(__name__)

# Public-facing state descriptions
STATE_DESCRIPTIONS = {
    'HEALTHY': 'Model performing well',
    'WATCH': 'Model performance dipping — monitoring closely',
    'DEGRADING': 'Model underperforming — reduced confidence',
    'BLOCKED': 'Model below breakeven — sitting out today',
    'INSUFFICIENT_DATA': 'Not enough recent data to assess',
}


class ModelHealthExporter(BaseExporter):
    """
    Export model health summary to GCS.

    Output file:
    - systems/model-health.json

    JSON structure:
    {
        "date": "2026-02-19",
        "generated_at": "...",
        "best_bets_model": "catboost_v12",
        "models": {
            "catboost_v9": {
                "state": "BLOCKED",
                "state_description": "Model below breakeven — sitting out today",
                "hr_7d": 39.9,
                "hr_14d": 42.1,
                "picks_7d": 85,
                "days_since_training": 38
            },
            "catboost_v12": {
                "state": "HEALTHY",
                "state_description": "Model performing well",
                "hr_7d": 56.0,
                "hr_14d": 55.2,
                "picks_7d": 50,
                "days_since_training": 15
            }
        },
        "active_model_state": "HEALTHY",
        "show_blocked_banner": false
    }
    """

    def generate_json(self, target_date: str = None) -> Dict[str, Any]:
        """Generate model health JSON for the latest available date."""
        model_data, data_date = self._query_model_health(target_date)
        best_bets_model = get_best_bets_model_id()

        if not model_data:
            return {
                'date': target_date or 'unknown',
                'generated_at': self.get_generated_at(),
                'best_bets_model': best_bets_model,
                'models': {},
                'active_model_state': 'INSUFFICIENT_DATA',
                'show_blocked_banner': False,
            }

        models = {}
        active_model_state = 'INSUFFICIENT_DATA'

        for row in model_data:
            model_id = row['model_id']
            state = row.get('state', 'INSUFFICIENT_DATA')

            models[model_id] = {
                'state': state,
                'state_description': STATE_DESCRIPTIONS.get(state, ''),
                'hr_7d': row.get('rolling_hr_7d'),
                'hr_14d': row.get('rolling_hr_14d'),
                'picks_7d': row.get('rolling_n_7d'),
                'days_since_training': row.get('days_since_training'),
            }

            if model_id == best_bets_model:
                active_model_state = state

        show_blocked = active_model_state == 'BLOCKED'

        return {
            'date': str(data_date),
            'generated_at': self.get_generated_at(),
            'best_bets_model': best_bets_model,
            'models': models,
            'active_model_state': active_model_state,
            'show_blocked_banner': show_blocked,
        }

    def _query_model_health(self, target_date: str = None):
        """Query model health from BigQuery.

        If target_date is None, uses the most recent date available.

        Returns:
            Tuple of (list of model dicts, date string)
        """
        if target_date:
            query = """
            SELECT model_id, state, rolling_hr_7d, rolling_hr_14d,
                   rolling_n_7d, days_since_training, game_date
            FROM `nba_predictions.model_performance_daily`
            WHERE game_date = @target_date
            ORDER BY model_id
            """
            params = [
                bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            ]
        else:
            query = """
            SELECT model_id, state, rolling_hr_7d, rolling_hr_14d,
                   rolling_n_7d, days_since_training, game_date
            FROM `nba_predictions.model_performance_daily`
            WHERE game_date = (
                SELECT MAX(game_date) FROM `nba_predictions.model_performance_daily`
            )
            ORDER BY model_id
            """
            params = None

        results = self.query_to_list(query, params)
        if not results:
            return [], target_date

        data_date = target_date or results[0].get('game_date', 'unknown')
        return results, data_date

    def export(self, target_date: str = None) -> str:
        """Generate and upload model health to GCS.

        Args:
            target_date: Optional date. If None, uses latest available.

        Returns:
            GCS path where file was uploaded.
        """
        json_data = self.generate_json(target_date)

        gcs_path = self.upload_to_gcs(
            json_data=json_data,
            path='systems/model-health.json',
            cache_control='public, max-age=300',
        )

        logger.info(
            f"Exported model health for {json_data['date']}: "
            f"active={json_data['active_model_state']}, "
            f"blocked={json_data['show_blocked_banner']}, "
            f"{len(json_data['models'])} models to {gcs_path}"
        )

        return gcs_path
