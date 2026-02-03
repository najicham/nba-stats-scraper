"""
Subset Performance Exporter for Phase 6 Publishing

Exports performance comparison across all subset groups.
Shows historical accuracy without revealing technical details.
"""

import logging
from typing import Dict, List, Any
from datetime import date, timedelta

from google.cloud import bigquery

from .base_exporter import BaseExporter
from shared.config.model_codenames import get_model_codename
from shared.config.subset_public_names import get_public_name

logger = logging.getLogger(__name__)


class SubsetPerformanceExporter(BaseExporter):
    """
    Export subset performance metrics for comparison.

    Output file:
    - subsets/performance.json - Performance across all groups and time windows

    JSON structure (CLEAN - no technical details):
    {
        "generated_at": "2026-02-03T...",
        "model": "926A",
        "windows": {
            "last_7_days": {
                "start_date": "2026-01-27",
                "end_date": "2026-02-02",
                "groups": [
                    {
                        "id": "1",
                        "name": "Top Pick",
                        "stats": {
                            "hit_rate": 81.8,
                            "roi": 15.2,
                            "picks": 6
                        }
                    },
                    ...
                ]
            },
            "last_30_days": {...},
            "season": {...}
        }
    }
    """

    def generate_json(self) -> Dict[str, Any]:
        """
        Generate subset performance JSON.

        Returns:
            Dictionary ready for JSON serialization
        """
        # Get current date for window calculation
        today = date.today()

        # Build performance windows
        windows = {
            'last_7_days': self._get_window_performance(today, 7),
            'last_30_days': self._get_window_performance(today, 30),
            'season': self._get_season_performance(today)
        }

        return {
            'generated_at': self.get_generated_at(),
            'model': get_model_codename('catboost_v9'),
            'windows': windows
        }

    def _get_window_performance(
        self,
        end_date: date,
        days_back: int
    ) -> Dict[str, Any]:
        """
        Get performance for a rolling window.

        Args:
            end_date: End date of window (typically today)
            days_back: Number of days to look back

        Returns:
            Dictionary with window metadata and group performance
        """
        start_date = end_date - timedelta(days=days_back)

        # Query performance data
        perf_data = self._query_window_performance(
            start_date.isoformat(),
            end_date.isoformat()
        )

        # Build clean output
        clean_groups = []
        for subset_perf in perf_data:
            # Get public name
            public = get_public_name(subset_perf['subset_id'])

            clean_groups.append({
                'id': public['id'],
                'name': public['name'],
                'stats': {
                    'hit_rate': round(subset_perf.get('hit_rate', 0.0), 1),
                    'roi': round(subset_perf.get('roi_pct', 0.0), 1),
                    'picks': subset_perf.get('total_picks', 0)
                }
            })

        # Sort by ID
        clean_groups.sort(key=lambda x: int(x['id']))

        return {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'groups': clean_groups
        }

    def _get_season_performance(self, end_date: date) -> Dict[str, Any]:
        """
        Get season-to-date performance.

        Season start is Nov 1 for current season.

        Args:
            end_date: End date (typically today)

        Returns:
            Dictionary with season metadata and group performance
        """
        # NBA season starts Nov 1
        current_year = end_date.year
        season_start_year = current_year if end_date.month >= 11 else current_year - 1
        season_start = date(season_start_year, 11, 1)

        # Query performance data
        perf_data = self._query_window_performance(
            season_start.isoformat(),
            end_date.isoformat()
        )

        # Build clean output
        clean_groups = []
        for subset_perf in perf_data:
            # Get public name
            public = get_public_name(subset_perf['subset_id'])

            clean_groups.append({
                'id': public['id'],
                'name': public['name'],
                'stats': {
                    'hit_rate': round(subset_perf.get('hit_rate', 0.0), 1),
                    'roi': round(subset_perf.get('roi_pct', 0.0), 1),
                    'picks': subset_perf.get('total_picks', 0)
                }
            })

        # Sort by ID
        clean_groups.sort(key=lambda x: int(x['id']))

        return {
            'start_date': season_start.isoformat(),
            'end_date': end_date.isoformat(),
            'groups': clean_groups
        }

    def _query_window_performance(
        self,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """
        Query aggregated performance for a date range.

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

        windows = json_data.get('windows', {})
        logger.info(
            f"Exported subset performance with {len(windows)} windows to {gcs_path}"
        )

        return gcs_path
