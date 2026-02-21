"""
Today Best Bets Exporter for Phase 6 Publishing

Exports a clean, frontend-friendly JSON with today's picks. Strips internal
metadata (composite_score, signal_tags, model IDs) and keeps only what end
users need: player, team, opponent, direction, line, edge, pick angles.

Output: v1/best-bets/today.json
Source: signal_best_bets_picks + prediction_accuracy (for record)

Created: 2026-02-21 (Session 319)
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

from google.cloud import bigquery

from data_processors.publishing.base_exporter import BaseExporter
from data_processors.publishing.exporter_utils import safe_float, safe_int
from ml.signals.aggregator import ALGORITHM_VERSION

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


class TodayBestBetsExporter(BaseExporter):
    """Export clean today's picks to GCS for end-user frontend."""

    def generate_json(self, target_date: str, **kwargs) -> Dict[str, Any]:
        """Generate today.json with clean picks + season record summary."""
        record = kwargs.get('record') or self._query_record(target_date)
        picks_raw = self._query_today_picks(target_date)

        picks = []
        for p in picks_raw:
            angles = p.get('pick_angles') or []
            picks.append({
                'rank': safe_int(p.get('rank')),
                'player': p.get('player_name') or '',
                'player_lookup': p.get('player_lookup') or '',
                'team': p.get('team_abbr') or '',
                'opponent': p.get('opponent_team_abbr') or '',
                'direction': p.get('recommendation') or '',
                'line': safe_float(p.get('line_value'), precision=1),
                'edge': safe_float(p.get('edge'), precision=1),
                'angles': list(angles)[:3],
            })

        return {
            'date': target_date,
            'generated_at': self.get_generated_at(),
            'algorithm_version': ALGORITHM_VERSION,
            'record': record,
            'picks': picks,
            'total_picks': len(picks),
        }

    def export(self, target_date: str, record: Dict = None) -> str:
        """Generate and upload today.json.

        Args:
            target_date: Date string YYYY-MM-DD
            record: Optional pre-computed record dict (avoids duplicate query
                    if BestBetsRecordExporter already ran).

        Returns:
            GCS path where file was uploaded.
        """
        json_data = self.generate_json(target_date, record=record)

        gcs_path = self.upload_to_gcs(
            json_data=json_data,
            path='best-bets/today.json',
            cache_control='public, max-age=300',
        )

        logger.info(
            f"Exported best-bets/today.json: {json_data['total_picks']} picks "
            f"for {target_date}"
        )
        return gcs_path

    def _query_today_picks(self, target_date: str) -> List[Dict]:
        """Query today's signal best bets picks from BQ."""
        query = """
        SELECT
          player_lookup,
          player_name,
          team_abbr,
          opponent_team_abbr,
          recommendation,
          line_value,
          edge,
          pick_angles,
          rank
        FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
        WHERE game_date = @target_date
        ORDER BY rank ASC
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]

        try:
            return self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query today's picks: {e}")
            return []

    def _query_record(self, target_date: str) -> Dict[str, Any]:
        """Query season W-L record summary. Lightweight fallback if record
        dict is not passed from BestBetsRecordExporter."""
        target = (
            date.fromisoformat(target_date) if isinstance(target_date, str)
            else target_date
        )
        season_start_year = target.year if target.month >= 11 else target.year - 1
        season_start = date(season_start_year, 11, 1)

        query = """
        SELECT
          COUNTIF(pa.prediction_correct) AS wins,
          COUNTIF(NOT pa.prediction_correct) AS losses,
          COUNT(*) AS total,
          ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNT(*), 0), 1) AS pct
        FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` b
        JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
          ON b.player_lookup = pa.player_lookup
          AND b.game_date = pa.game_date
          AND b.system_id = pa.system_id
        WHERE b.game_date >= @season_start
          AND b.game_date <= @target_date
          AND pa.prediction_correct IS NOT NULL
        """

        params = [
            bigquery.ScalarQueryParameter(
                'season_start', 'DATE', season_start.isoformat()
            ),
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]

        try:
            rows = self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query record for today.json: {e}")
            rows = []

        empty = {'wins': 0, 'losses': 0, 'pct': 0.0, 'total': 0}
        if not rows or rows[0].get('total') is None or rows[0]['total'] == 0:
            return {'season': empty}

        r = rows[0]
        return {
            'season': {
                'wins': safe_int(r.get('wins'), 0),
                'losses': safe_int(r.get('losses'), 0),
                'pct': safe_float(r.get('pct'), 0.0, 1),
                'total': safe_int(r.get('total'), 0),
            },
        }
