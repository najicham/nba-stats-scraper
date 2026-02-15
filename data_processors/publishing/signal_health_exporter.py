"""
Signal Health Exporter for Phase 6 Publishing

Exports per-signal health regime (HOT/NORMAL/COLD) to GCS for frontend display.
Enables signal health badges and performance transparency on playerprops.io.

Output: v1/systems/signal-health.json

Created: 2026-02-15 (Session 267)
"""

import logging
from typing import Any, Dict

from google.cloud import bigquery

from .base_exporter import BaseExporter

logger = logging.getLogger(__name__)


class SignalHealthExporter(BaseExporter):
    """
    Export signal health summary to GCS.

    Output file:
    - systems/signal-health.json

    JSON structure:
    {
        "date": "2026-02-19",
        "generated_at": "...",
        "signals": {
            "high_edge": {
                "regime": "HOT",
                "hr_7d": 75.0,
                "hr_season": 62.3,
                "picks_7d": 45,
                "is_model_dependent": true
            },
            ...
        },
        "summary": {
            "total_signals": 6,
            "hot": 2,
            "normal": 3,
            "cold": 1
        }
    }
    """

    def generate_json(self, target_date: str = None) -> Dict[str, Any]:
        """Generate signal health JSON for the latest available date."""
        signal_data, data_date = self._query_signal_health(target_date)

        if not signal_data:
            return {
                'date': target_date or 'unknown',
                'generated_at': self.get_generated_at(),
                'signals': {},
                'summary': {
                    'total_signals': 0,
                    'hot': 0,
                    'normal': 0,
                    'cold': 0,
                },
            }

        signals = {}
        hot = normal = cold = 0
        for row in signal_data:
            regime = row.get('regime', 'NORMAL')
            if regime == 'HOT':
                hot += 1
            elif regime == 'COLD':
                cold += 1
            else:
                normal += 1

            signals[row['signal_tag']] = {
                'regime': regime,
                'hr_7d': row.get('hr_7d'),
                'hr_season': row.get('hr_season'),
                'picks_7d': row.get('picks_7d'),
                'is_model_dependent': row.get('is_model_dependent', False),
            }

        return {
            'date': str(data_date),
            'generated_at': self.get_generated_at(),
            'signals': signals,
            'summary': {
                'total_signals': len(signals),
                'hot': hot,
                'normal': normal,
                'cold': cold,
            },
        }

    def _query_signal_health(self, target_date: str = None):
        """Query signal health from BigQuery.

        If target_date is None, uses the most recent date available.

        Returns:
            Tuple of (list of signal dicts, date string)
        """
        if target_date:
            query = """
            SELECT signal_tag, regime, hr_7d, hr_season, picks_7d, is_model_dependent
            FROM `nba_predictions.signal_health_daily`
            WHERE game_date = @target_date
            ORDER BY signal_tag
            """
            params = [
                bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            ]
        else:
            query = """
            SELECT signal_tag, regime, hr_7d, hr_season, picks_7d, is_model_dependent,
                   game_date
            FROM `nba_predictions.signal_health_daily`
            WHERE game_date = (
                SELECT MAX(game_date) FROM `nba_predictions.signal_health_daily`
            )
            ORDER BY signal_tag
            """
            params = None

        results = self.query_to_list(query, params)
        if not results:
            return [], target_date

        data_date = target_date or results[0].get('game_date', 'unknown')
        return results, data_date

    def export(self, target_date: str = None) -> str:
        """Generate and upload signal health to GCS.

        Args:
            target_date: Optional date. If None, uses latest available.

        Returns:
            GCS path where file was uploaded.
        """
        json_data = self.generate_json(target_date)

        gcs_path = self.upload_to_gcs(
            json_data=json_data,
            path='systems/signal-health.json',
            cache_control='public, max-age=300',
        )

        summary = json_data.get('summary', {})
        logger.info(
            f"Exported signal health for {json_data['date']}: "
            f"{summary.get('total_signals', 0)} signals "
            f"({summary.get('hot', 0)} HOT, {summary.get('cold', 0)} COLD) "
            f"to {gcs_path}"
        )

        return gcs_path
