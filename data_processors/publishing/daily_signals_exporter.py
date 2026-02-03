"""
Daily Signals Exporter for Phase 6 Publishing

Exports daily market signal indicating favorable/neutral/challenging conditions.
Simplified version without technical details.
"""

import logging
from typing import Dict, Any, Optional
from datetime import date, datetime

from google.cloud import bigquery

from .base_exporter import BaseExporter
from shared.config.model_codenames import get_model_codename

logger = logging.getLogger(__name__)


class DailySignalsExporter(BaseExporter):
    """
    Export daily market signals with simplified categories.

    Output file:
    - signals/{date}.json - Daily signal for specific date

    JSON structure (CLEAN - no technical thresholds):
    {
        "date": "2026-02-03",
        "generated_at": "2026-02-03T...",
        "model": "926A",
        "signal": "favorable",  # or "neutral", "challenging"
        "metrics": {
            "conditions": "balanced",  # or "over_heavy", "under_heavy"
            "picks": 28  # Total high-edge picks
        }
    }

    Signal mapping:
    - GREEN → "favorable"
    - YELLOW → "neutral"
    - RED → "challenging"
    """

    def generate_json(self, target_date: str) -> Dict[str, Any]:
        """
        Generate daily signal JSON for a specific date.

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            Dictionary ready for JSON serialization
        """
        # Query signal data from database
        signal_data = self._query_daily_signal(target_date)

        if not signal_data:
            # No signal data for this date
            return {
                'date': target_date,
                'generated_at': self.get_generated_at(),
                'model': get_model_codename('catboost_v9'),
                'signal': 'neutral',
                'metrics': {
                    'conditions': 'unknown',
                    'picks': 0
                },
                'note': 'No data available for this date'
            }

        # Map internal signal to user-facing terms
        internal_signal = signal_data.get('daily_signal', 'YELLOW')
        public_signal = self._map_signal_to_public(internal_signal)

        # Map skew category to user-facing conditions
        skew_category = signal_data.get('skew_category', 'BALANCED')
        conditions = self._map_skew_to_conditions(skew_category)

        return {
            'date': target_date,
            'generated_at': self.get_generated_at(),
            'model': get_model_codename('catboost_v9'),
            'signal': public_signal,
            'metrics': {
                'conditions': conditions,
                'picks': signal_data.get('high_edge_picks', 0)
            }
        }

    def _query_daily_signal(self, target_date: str) -> Optional[Dict[str, Any]]:
        """
        Query daily signal from BigQuery.

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            Signal dictionary or None if not found
        """
        query = """
        SELECT
          game_date,
          system_id,
          total_picks,
          high_edge_picks,
          pct_over,
          pct_under,
          skew_category,
          daily_signal,
          signal_explanation
        FROM `nba_predictions.daily_prediction_signals`
        WHERE game_date = @target_date
          AND system_id = 'catboost_v9'
        LIMIT 1
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date)
        ]

        results = self.query_to_list(query, params)
        return results[0] if results else None

    def _map_signal_to_public(self, internal_signal: str) -> str:
        """
        Map internal signal (GREEN/YELLOW/RED) to public terms.

        Args:
            internal_signal: GREEN, YELLOW, or RED

        Returns:
            Public signal: "favorable", "neutral", or "challenging"
        """
        mapping = {
            'GREEN': 'favorable',
            'YELLOW': 'neutral',
            'RED': 'challenging'
        }
        return mapping.get(internal_signal, 'neutral')

    def _map_skew_to_conditions(self, skew_category: str) -> str:
        """
        Map skew category to user-facing conditions.

        Args:
            skew_category: OVER_HEAVY, UNDER_HEAVY, or BALANCED

        Returns:
            Public conditions: "balanced", "over_heavy", or "under_heavy"
        """
        mapping = {
            'BALANCED': 'balanced',
            'OVER_HEAVY': 'over_heavy',
            'UNDER_HEAVY': 'under_heavy'
        }
        return mapping.get(skew_category, 'balanced')

    def export(self, target_date: str) -> str:
        """
        Generate and upload daily signal to GCS.

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            GCS path where file was uploaded
        """
        json_data = self.generate_json(target_date)

        # Upload to GCS (5 minute cache for fresh data)
        gcs_path = self.upload_to_gcs(
            json_data=json_data,
            path=f'signals/{target_date}.json',
            cache_control='public, max-age=300'  # 5 minutes
        )

        logger.info(
            f"Exported daily signal for {target_date}: "
            f"{json_data['signal']} ({json_data['metrics']['picks']} picks) "
            f"to {gcs_path}"
        )

        return gcs_path
