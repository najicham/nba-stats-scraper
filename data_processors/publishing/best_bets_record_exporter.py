"""
Best Bets Record Exporter for Phase 6 Publishing

Exports two GCS endpoints for playerprops.io:
  - v1/best-bets/record.json — aggregate W-L stats + streak
  - v1/best-bets/history.json — full graded pick history by week/day

Data source: signal_best_bets_picks LEFT JOIN prediction_accuracy

Created: 2026-02-21 (Session 317)
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from google.cloud import bigquery

from data_processors.publishing.base_exporter import BaseExporter
from data_processors.publishing.exporter_utils import safe_float, safe_int
from ml.signals.aggregator import ALGORITHM_VERSION

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


class BestBetsRecordExporter(BaseExporter):
    """Export best bets W-L record and pick history to GCS."""

    def generate_json(self, target_date: str, **kwargs) -> Dict[str, Any]:
        """Not used directly — use export() instead."""
        return self._build_record(target_date)

    def export(self, target_date: str) -> Dict[str, str]:
        """Generate and upload both record.json and history.json.

        Returns:
            Dict with 'record' and 'history' GCS paths.
        """
        paths = {}

        # Build and upload record.json
        record_data = self._build_record(target_date)
        paths['record'] = self.upload_to_gcs(
            json_data=record_data,
            path='best-bets/record.json',
            cache_control='public, max-age=300',
        )
        logger.info(f"Exported best-bets/record.json: {record_data['record']['season']}")

        # Build and upload history.json
        history_data = self._build_history(target_date)
        paths['history'] = self.upload_to_gcs(
            json_data=history_data,
            path='best-bets/history.json',
            cache_control='public, max-age=300',
        )
        logger.info(
            f"Exported best-bets/history.json: "
            f"{history_data['total_picks']} picks, {history_data['graded']} graded"
        )

        return paths

    def _build_record(self, target_date: str) -> Dict[str, Any]:
        """Build record.json with season/month/week W-L and streaks."""
        target = (
            date.fromisoformat(target_date) if isinstance(target_date, str)
            else target_date
        )
        season_start_year = target.year if target.month >= 11 else target.year - 1
        season_start = date(season_start_year, 11, 1)
        month_start = target.replace(day=1)
        week_start = target - timedelta(days=target.weekday())

        query = """
        WITH graded AS (
          SELECT
            b.game_date,
            pa.prediction_correct
          FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` b
          JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
            ON b.player_lookup = pa.player_lookup
            AND b.game_date = pa.game_date
            AND b.system_id = pa.system_id
          WHERE b.game_date >= @season_start
            AND b.game_date <= @target_date
            AND pa.prediction_correct IS NOT NULL
        )
        SELECT
          -- Season
          COUNTIF(prediction_correct) AS season_wins,
          COUNTIF(NOT prediction_correct) AS season_losses,
          COUNT(*) AS season_total,
          ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNT(*), 0), 1)
            AS season_pct,
          -- Month
          COUNTIF(prediction_correct AND game_date >= @month_start) AS month_wins,
          COUNTIF(NOT prediction_correct AND game_date >= @month_start) AS month_losses,
          COUNTIF(game_date >= @month_start) AS month_total,
          ROUND(100.0 *
            COUNTIF(prediction_correct AND game_date >= @month_start) /
            NULLIF(COUNTIF(game_date >= @month_start), 0), 1) AS month_pct,
          -- Week
          COUNTIF(prediction_correct AND game_date >= @week_start) AS week_wins,
          COUNTIF(NOT prediction_correct AND game_date >= @week_start) AS week_losses,
          COUNTIF(game_date >= @week_start) AS week_total,
          ROUND(100.0 *
            COUNTIF(prediction_correct AND game_date >= @week_start) /
            NULLIF(COUNTIF(game_date >= @week_start), 0), 1) AS week_pct,
          -- Last 10
          (SELECT COUNTIF(prediction_correct) FROM (
            SELECT prediction_correct FROM graded ORDER BY game_date DESC LIMIT 10
          )) AS last10_wins
        FROM graded
        """

        params = [
            bigquery.ScalarQueryParameter(
                'season_start', 'DATE', season_start.isoformat()
            ),
            bigquery.ScalarQueryParameter(
                'month_start', 'DATE', month_start.isoformat()
            ),
            bigquery.ScalarQueryParameter(
                'week_start', 'DATE', week_start.isoformat()
            ),
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]

        try:
            rows = self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query best bets record: {e}")
            rows = []

        empty = {'wins': 0, 'losses': 0, 'pct': 0.0, 'total': 0}
        if not rows or rows[0].get('season_total') is None or rows[0]['season_total'] == 0:
            return {
                'date': target_date,
                'generated_at': self.get_generated_at(),
                'algorithm_version': ALGORITHM_VERSION,
                'record': {
                    'season': empty.copy(),
                    'month': empty.copy(),
                    'week': empty.copy(),
                    'last_10': {'wins': 0, 'losses': 0, 'pct': 0.0},
                },
                'streak': {'type': 'N/A', 'count': 0},
                'best_streak': {'type': 'N/A', 'count': 0, 'start': None, 'end': None},
            }

        r = rows[0]
        last10_wins = safe_int(r.get('last10_wins'), 0)
        last10_losses = 10 - last10_wins if r['season_total'] >= 10 else (
            safe_int(r.get('season_total'), 0) - last10_wins
        )

        record = {
            'season': {
                'wins': safe_int(r.get('season_wins'), 0),
                'losses': safe_int(r.get('season_losses'), 0),
                'pct': safe_float(r.get('season_pct'), 0.0, 1),
                'total': safe_int(r.get('season_total'), 0),
            },
            'month': {
                'wins': safe_int(r.get('month_wins'), 0),
                'losses': safe_int(r.get('month_losses'), 0),
                'pct': safe_float(r.get('month_pct'), 0.0, 1),
                'total': safe_int(r.get('month_total'), 0),
            },
            'week': {
                'wins': safe_int(r.get('week_wins'), 0),
                'losses': safe_int(r.get('week_losses'), 0),
                'pct': safe_float(r.get('week_pct'), 0.0, 1),
                'total': safe_int(r.get('week_total'), 0),
            },
            'last_10': {
                'wins': last10_wins,
                'losses': last10_losses,
                'pct': safe_float(
                    100.0 * last10_wins / max(last10_wins + last10_losses, 1),
                    0.0, 1,
                ),
            },
        }

        # Compute current streak and best streak
        streak, best_streak = self._compute_streaks(target_date, season_start.isoformat())

        return {
            'date': target_date,
            'generated_at': self.get_generated_at(),
            'algorithm_version': ALGORITHM_VERSION,
            'record': record,
            'streak': streak,
            'best_streak': best_streak,
        }

    def _compute_streaks(
        self, target_date: str, season_start: str
    ) -> tuple:
        """Compute current streak and best W streak from graded picks."""
        query = """
        SELECT
          b.game_date,
          pa.prediction_correct
        FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` b
        JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
          ON b.player_lookup = pa.player_lookup
          AND b.game_date = pa.game_date
          AND b.system_id = pa.system_id
        WHERE b.game_date >= @season_start
          AND b.game_date <= @target_date
          AND pa.prediction_correct IS NOT NULL
        ORDER BY b.game_date DESC, b.created_at DESC
        """

        params = [
            bigquery.ScalarQueryParameter('season_start', 'DATE', season_start),
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]

        try:
            rows = self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query streaks: {e}")
            return (
                {'type': 'N/A', 'count': 0},
                {'type': 'N/A', 'count': 0, 'start': None, 'end': None},
            )

        if not rows:
            return (
                {'type': 'N/A', 'count': 0},
                {'type': 'N/A', 'count': 0, 'start': None, 'end': None},
            )

        # Current streak (rows are sorted newest first)
        current_type = 'W' if rows[0]['prediction_correct'] else 'L'
        current_count = 0
        for row in rows:
            is_win = row['prediction_correct']
            if (is_win and current_type == 'W') or (not is_win and current_type == 'L'):
                current_count += 1
            else:
                break

        # Best W streak (iterate chronologically)
        best_w_count = 0
        best_w_start = None
        best_w_end = None
        curr_w_count = 0
        curr_w_start = None

        for row in reversed(rows):
            if row['prediction_correct']:
                if curr_w_count == 0:
                    curr_w_start = row['game_date']
                curr_w_count += 1
                if curr_w_count > best_w_count:
                    best_w_count = curr_w_count
                    best_w_start = curr_w_start
                    best_w_end = row['game_date']
            else:
                curr_w_count = 0

        best_streak = {
            'type': 'W',
            'count': best_w_count,
            'start': (
                best_w_start.isoformat() if hasattr(best_w_start, 'isoformat')
                else str(best_w_start) if best_w_start else None
            ),
            'end': (
                best_w_end.isoformat() if hasattr(best_w_end, 'isoformat')
                else str(best_w_end) if best_w_end else None
            ),
        }

        return {'type': current_type, 'count': current_count}, best_streak

    def _build_history(self, target_date: str) -> Dict[str, Any]:
        """Build history.json with picks grouped by week and day."""
        target = (
            date.fromisoformat(target_date) if isinstance(target_date, str)
            else target_date
        )
        season_start_year = target.year if target.month >= 11 else target.year - 1
        season_start = date(season_start_year, 11, 1)

        query = """
        SELECT
          b.game_date,
          b.player_name,
          b.player_lookup,
          b.team_abbr,
          b.opponent_team_abbr,
          b.recommendation,
          b.line_value,
          b.edge,
          b.predicted_points,
          b.signal_tags,
          pa.prediction_correct,
          pa.actual_points
        FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` b
        LEFT JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
          ON b.player_lookup = pa.player_lookup
          AND b.game_date = pa.game_date
          AND b.system_id = pa.system_id
        WHERE b.game_date >= @season_start
          AND b.game_date <= @target_date
        ORDER BY b.game_date DESC, b.edge DESC
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
            logger.warning(f"Failed to query best bets history: {e}")
            rows = []

        # Group by week then day
        weeks_map: Dict[str, Dict[str, List]] = {}
        total_picks = 0
        graded = 0

        for row in rows:
            game_date = row['game_date']
            if hasattr(game_date, 'isoformat'):
                game_date_str = game_date.isoformat()
                gd = game_date
            else:
                game_date_str = str(game_date)
                gd = date.fromisoformat(game_date_str)

            # Monday-aligned week start
            week_start = gd - timedelta(days=gd.weekday())
            week_key = week_start.isoformat()

            if week_key not in weeks_map:
                weeks_map[week_key] = {}
            if game_date_str not in weeks_map[week_key]:
                weeks_map[week_key][game_date_str] = []

            result = None
            if row.get('prediction_correct') is not None:
                result = 'WIN' if row['prediction_correct'] else 'LOSS'
                graded += 1

            signal_tags = row.get('signal_tags') or []

            weeks_map[week_key][game_date_str].append({
                'player': row.get('player_name') or '',
                'player_lookup': row.get('player_lookup') or '',
                'team': row.get('team_abbr') or '',
                'opponent': row.get('opponent_team_abbr') or '',
                'direction': row.get('recommendation') or '',
                'line': safe_float(row.get('line_value'), precision=1),
                'edge': safe_float(row.get('edge'), precision=1),
                'prediction': safe_float(row.get('predicted_points'), precision=1),
                'actual': safe_float(row.get('actual_points'), precision=1),
                'result': result,
                'signals': list(signal_tags),
            })
            total_picks += 1

        # Build weeks array
        weeks = []
        for week_key in sorted(weeks_map.keys(), reverse=True):
            days_map = weeks_map[week_key]
            week_wins = 0
            week_losses = 0
            days = []

            for day_key in sorted(days_map.keys(), reverse=True):
                picks = days_map[day_key]
                days.append({'date': day_key, 'picks': picks})
                for p in picks:
                    if p['result'] == 'WIN':
                        week_wins += 1
                    elif p['result'] == 'LOSS':
                        week_losses += 1

            week_total = week_wins + week_losses
            weeks.append({
                'week_start': week_key,
                'record': {
                    'wins': week_wins,
                    'losses': week_losses,
                    'pct': round(
                        100.0 * week_wins / max(week_total, 1), 1
                    ),
                },
                'days': days,
            })

        return {
            'date': target_date,
            'generated_at': self.get_generated_at(),
            'total_picks': total_picks,
            'graded': graded,
            'weeks': weeks,
        }
