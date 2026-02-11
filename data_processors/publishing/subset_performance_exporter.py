"""
Subset Performance Exporter for Phase 6 Publishing

Exports performance comparison across all subset groups.
Shows historical accuracy without revealing technical details.

Session 188: Multi-model support with 6 time windows grouped by model.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Any
from datetime import date, timedelta

from google.cloud import bigquery

from .base_exporter import BaseExporter
from shared.config.model_codenames import get_model_codename, get_model_display_info, CHAMPION_CODENAME
from shared.config.subset_public_names import get_public_name

logger = logging.getLogger(__name__)


class SubsetPerformanceExporter(BaseExporter):
    """
    Export subset performance metrics for comparison.

    Output file:
    - subsets/performance.json - Performance across all groups and time windows

    Session 188: model_groups structure with 6 time windows per model.

    JSON structure (v2):
    {
        "generated_at": "2026-02-10T...",
        "version": 2,
        "model_groups": [
            {
                "model_id": "926A",
                "model_name": "V9 Champion",
                "windows": {
                    "last_1_day": {"start_date": "...", "end_date": "...", "groups": [...]},
                    "last_3_days": {...},
                    "last_7_days": {...},
                    "last_14_days": {...},
                    "last_30_days": {...},
                    "season": {...}
                }
            }
        ]
    }
    """

    # Window definitions: (key, days_back) — season handled separately
    ROLLING_WINDOWS = [
        ('last_1_day', 1),
        ('last_3_days', 3),
        ('last_7_days', 7),
        ('last_14_days', 14),
        ('last_30_days', 30),
    ]

    def generate_json(self) -> Dict[str, Any]:
        """
        Generate subset performance JSON grouped by model.

        Returns:
            Dictionary ready for JSON serialization
        """
        today = date.today()

        # Query all subset definitions to know which models exist
        subset_defs = self._query_subset_definitions()

        # Group definitions by system_id
        models_with_subsets = defaultdict(set)
        for d in subset_defs:
            models_with_subsets[d['system_id']].add(d['subset_id'])

        # Build model_groups
        model_groups = []
        for system_id, subset_ids in models_with_subsets.items():
            display = get_model_display_info(system_id)

            windows = {}
            for window_key, days_back in self.ROLLING_WINDOWS:
                windows[window_key] = self._get_window_performance(today, days_back, subset_ids)
            windows['season'] = self._get_season_performance(today, subset_ids)

            model_groups.append({
                'model_id': display['codename'],
                'model_name': display['display_name'],
                'windows': windows,
            })

        # Sort: champion first, then by codename
        model_groups.sort(key=lambda x: (0 if x['model_id'] == CHAMPION_CODENAME else 1, x['model_id']))

        return {
            'generated_at': self.get_generated_at(),
            'version': 2,
            'model_groups': model_groups,
        }

    def _query_subset_definitions(self) -> List[Dict[str, Any]]:
        """Query active subset definitions to discover models."""
        query = """
        SELECT subset_id, system_id
        FROM `nba_predictions.dynamic_subset_definitions`
        WHERE is_active = TRUE
        ORDER BY system_id, subset_id
        """
        return self.query_to_list(query)

    def _get_window_performance(
        self,
        end_date: date,
        days_back: int,
        subset_ids: set,
    ) -> Dict[str, Any]:
        """
        Get performance for a rolling window, filtered to specific subsets.

        Args:
            end_date: End date of window (typically today)
            days_back: Number of days to look back
            subset_ids: Set of subset_ids belonging to this model

        Returns:
            Dictionary with window metadata and group performance
        """
        start_date = end_date - timedelta(days=days_back)

        perf_data = self._query_window_performance(
            start_date.isoformat(),
            end_date.isoformat()
        )

        # Filter to this model's subsets
        clean_groups = []
        for subset_perf in perf_data:
            if subset_perf['subset_id'] not in subset_ids:
                continue
            public = get_public_name(subset_perf['subset_id'])

            clean_groups.append({
                'id': public['id'],
                'name': public['name'],
                'stats': {
                    'hit_rate': round(subset_perf.get('hit_rate') or 0.0, 1),
                    'roi': round(subset_perf.get('roi_pct') or 0.0, 1),
                    'picks': subset_perf.get('total_picks') or 0
                }
            })

        clean_groups.sort(key=lambda x: int(x['id']) if x['id'].isdigit() else 999)

        return {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'groups': clean_groups,
        }

    def _get_season_performance(self, end_date: date, subset_ids: set) -> Dict[str, Any]:
        """
        Get season-to-date performance for specific subsets.

        Args:
            end_date: End date (typically today)
            subset_ids: Set of subset_ids belonging to this model

        Returns:
            Dictionary with season metadata and group performance
        """
        current_year = end_date.year
        season_start_year = current_year if end_date.month >= 11 else current_year - 1
        season_start = date(season_start_year, 11, 1)

        perf_data = self._query_window_performance(
            season_start.isoformat(),
            end_date.isoformat()
        )

        clean_groups = []
        for subset_perf in perf_data:
            if subset_perf['subset_id'] not in subset_ids:
                continue
            public = get_public_name(subset_perf['subset_id'])

            clean_groups.append({
                'id': public['id'],
                'name': public['name'],
                'stats': {
                    'hit_rate': round(subset_perf.get('hit_rate') or 0.0, 1),
                    'roi': round(subset_perf.get('roi_pct') or 0.0, 1),
                    'picks': subset_perf.get('total_picks') or 0
                }
            })

        clean_groups.sort(key=lambda x: int(x['id']) if x['id'].isdigit() else 999)

        return {
            'start_date': season_start.isoformat(),
            'end_date': end_date.isoformat(),
            'groups': clean_groups,
        }

    def _query_window_performance(
        self,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """
        Query aggregated performance for a date range (all subsets).

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            List of subset performance dictionaries
        """
        query = """
        SELECT
          subset_id,
          subset_name,
          SUM(graded_picks) as total_picks,
          SUM(wins) as total_wins,
          ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) as hit_rate,
          ROUND(SUM(wins * 0.909 - (graded_picks - wins)), 1) as profit_units,
          ROUND(
            100.0 * SUM(wins * 0.909 - (graded_picks - wins)) / NULLIF(SUM(graded_picks), 0),
            1
          ) as roi_pct
        FROM `nba_predictions.v_dynamic_subset_performance`
        WHERE game_date >= @start_date
          AND game_date <= @end_date
        GROUP BY subset_id, subset_name
        ORDER BY subset_id
        """

        params = [
            bigquery.ScalarQueryParameter('start_date', 'DATE', start_date),
            bigquery.ScalarQueryParameter('end_date', 'DATE', end_date)
        ]

        return self.query_to_list(query, params)

    def export(self) -> str:
        """
        Generate and upload subset performance to GCS.

        Returns:
            GCS path where file was uploaded
        """
        json_data = self.generate_json()

        # Upload to GCS (1 hour cache)
        gcs_path = self.upload_to_gcs(
            json_data=json_data,
            path='subsets/performance.json',
            cache_control='public, max-age=3600'  # 1 hour
        )

        model_count = len(json_data.get('model_groups', []))
        logger.info(
            f"Exported subset performance for {model_count} models to {gcs_path}"
        )

        return gcs_path
