"""
Season Game Counts Exporter for Phase 6 Publishing

Exports full season game counts with break detection metadata.
Used by frontend calendar widget and break detection.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from google.cloud import bigquery

from .base_exporter import BaseExporter

logger = logging.getLogger(__name__)


class SeasonGameCountsExporter(BaseExporter):
    """
    Export full season game counts for calendar and break detection.

    Output file:
    - schedule/game-counts.json - Full season game counts

    JSON structure:
    {
        "season": "2025-26",
        "updated_at": "2026-02-13T20:00:00Z",
        "last_game_date": "2026-02-07",
        "next_game_date": "2026-02-19",
        "dates": {
            "2025-10-22": 2,
            "2025-10-23": 12,
            ...
        }
    }
    """

    def generate_json(self, season_start: str = "2025-10-01") -> Dict[str, Any]:
        """
        Generate full season game counts.

        Args:
            season_start: Season start date for filtering (default: 2025-10-01)

        Returns:
            Dictionary with season metadata and game counts
        """
        # Query all game dates and counts for the season
        query = """
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as game_count
        FROM `nba-props-platform.nba_raw.nbac_schedule`
        WHERE game_date >= @season_start
        GROUP BY game_date
        ORDER BY game_date
        """
        params = [
            bigquery.ScalarQueryParameter('season_start', 'DATE', season_start)
        ]
        results = self.query_to_list(query, params)

        # Build dates dictionary
        dates = {}
        for row in results:
            date_str = row['game_date'].strftime('%Y-%m-%d')
            dates[date_str] = row['game_count']

        # Find last game date (most recent date with games <= today)
        last_game_date = None
        for date_str in sorted(dates.keys(), reverse=True):
            if date_str <= datetime.utcnow().strftime('%Y-%m-%d') and dates[date_str] > 0:
                last_game_date = date_str
                break

        # Find next game date (next upcoming date with games > today)
        next_game_date = None
        today = datetime.utcnow().strftime('%Y-%m-%d')
        for date_str in sorted(dates.keys()):
            if date_str > today and dates[date_str] > 0:
                next_game_date = date_str
                break

        return {
            'season': '2025-26',
            'updated_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'last_game_date': last_game_date,
            'next_game_date': next_game_date,
            'dates': dates
        }

    def export(self, season_start: str = "2025-10-01") -> str:
        """
        Generate and upload season game counts.

        Args:
            season_start: Season start date for filtering

        Returns:
            GCS path of exported file
        """
        logger.info(f"Exporting season game counts (season_start={season_start})")

        json_data = self.generate_json(season_start)

        # Upload with 30min cache (schedule rarely changes, but breaks need timely updates)
        path = 'schedule/game-counts.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=1800')

        logger.info(
            f"Exported {len(json_data['dates'])} dates to {path} "
            f"(last={json_data['last_game_date']}, next={json_data['next_game_date']})"
        )
        return gcs_path
