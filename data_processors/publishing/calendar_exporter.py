"""
Calendar Game Counts Exporter for Phase 6 Publishing

Exports game counts per date for calendar widget.
"""

import logging
from typing import Dict

from google.cloud import bigquery

from .base_exporter import BaseExporter

logger = logging.getLogger(__name__)


class CalendarExporter(BaseExporter):
    """
    Export game counts per date for calendar widget.

    Output file:
    - calendar/game-counts.json - Game counts for past N days

    JSON structure:
    {
        "2026-02-11": 14,
        "2026-02-10": 4,
        "2026-02-09": 12,
        ...
    }
    """

    def generate_json(self, days_back: int = 30) -> Dict[str, int]:
        """
        Generate calendar game counts.

        Args:
            days_back: Number of days to include (default 30)

        Returns:
            Dictionary mapping date strings to game counts
        """
        query = """
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as game_count
        FROM `nba-props-platform.nba_raw.nbac_schedule`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days_back DAY)
          AND game_date <= DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)
        GROUP BY game_date
        ORDER BY game_date DESC
        """
        params = [
            bigquery.ScalarQueryParameter('days_back', 'INT64', days_back)
        ]
        results = self.query_to_list(query, params)

        # Convert to {date: count} dict
        game_counts = {}
        for row in results:
            date_str = row['game_date'].strftime('%Y-%m-%d')
            game_counts[date_str] = row['game_count']

        return game_counts

    def export(self, days_back: int = 30) -> str:
        """
        Generate and upload calendar game counts.

        Args:
            days_back: Number of days to include

        Returns:
            GCS path of exported file
        """
        logger.info(f"Exporting calendar game counts ({days_back} days)")

        json_data = self.generate_json(days_back)

        # Upload with short cache (schedule can change)
        path = 'calendar/game-counts.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=1800')

        logger.info(f"Exported {len(json_data)} dates to {path}")
        return gcs_path
