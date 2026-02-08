"""
Season Subset Picks Exporter for Phase 6 Publishing

Exports full-season subset picks in a single file for instant tab/date switching.
Includes W-L records per subset (season/month/week) and per-pick results.

Session 158: Created for new subset picks page with tabs per subset.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date, timedelta

from google.cloud import bigquery

from .base_exporter import BaseExporter
from shared.config.model_codenames import get_model_codename
from shared.config.subset_public_names import get_public_name

logger = logging.getLogger(__name__)

# Signal mapping: internal → public
SIGNAL_MAP = {
    'GREEN': 'favorable',
    'YELLOW': 'neutral',
    'RED': 'challenging',
}


class SeasonSubsetPicksExporter(BaseExporter):
    """
    Export full-season subset picks in one file.

    Output file:
    - subsets/season.json

    JSON structure:
    {
        "generated_at": "2026-02-08T...",
        "model": "926A",
        "season": "2025-26",
        "groups": [
            {
                "id": "1",
                "name": "Top Pick",
                "record": {
                    "season": {"wins": 42, "losses": 18, "pct": 70.0},
                    "month": {"wins": 8, "losses": 3, "pct": 72.7},
                    "week": {"wins": 3, "losses": 1, "pct": 75.0}
                },
                "dates": [
                    {
                        "date": "2026-02-07",
                        "signal": "favorable",
                        "picks": [
                            {
                                "player": "LeBron James",
                                "team": "LAL",
                                "opponent": "BOS",
                                "prediction": 26.1,
                                "line": 24.5,
                                "direction": "OVER",
                                "actual": 28,
                                "result": "hit"
                            }
                        ]
                    }
                ]
            }
        ]
    }
    """

    def _get_season_bounds(self, ref_date: Optional[date] = None) -> tuple:
        """Get season start date and season label."""
        ref = ref_date or date.today()
        start_year = ref.year if ref.month >= 11 else ref.year - 1
        season_start = date(start_year, 11, 1)
        season_label = f"{start_year}-{str(start_year + 1)[-2:]}"
        return season_start, season_label

    def generate_json(self, **kwargs) -> Dict[str, Any]:
        """Generate full-season subset picks JSON."""
        today = date.today()
        season_start, season_label = self._get_season_bounds(today)

        # Get all picks with results for the season
        all_picks = self._query_season_picks(season_start.isoformat(), today.isoformat())

        # Get daily signals for the season
        signals = self._query_season_signals(season_start.isoformat(), today.isoformat())

        # Get W-L records per subset
        records = self._query_records(season_start, today)

        # Build grouped structure: subset → date → picks
        groups_data = self._group_picks(all_picks, signals)

        # Build clean output
        clean_groups = []
        for subset_id in sorted(groups_data.keys()):
            dates_data = groups_data[subset_id]
            public = get_public_name(subset_id)
            subset_record = records.get(subset_id, _empty_record())

            # Build dates array (newest first)
            clean_dates = []
            for game_date in sorted(dates_data.keys(), reverse=True):
                day_data = dates_data[game_date]
                clean_dates.append({
                    'date': game_date,
                    'signal': day_data['signal'],
                    'picks': day_data['picks'],
                })

            clean_groups.append({
                'id': public['id'],
                'name': public['name'],
                'record': subset_record,
                'dates': clean_dates,
            })

        # Sort groups by ID
        clean_groups.sort(key=lambda x: int(x['id']) if x['id'].isdigit() else 999)

        return {
            'generated_at': self.get_generated_at(),
            'model': get_model_codename('catboost_v9'),
            'season': season_label,
            'groups': clean_groups,
        }

    def _query_season_picks(self, start_date: str, end_date: str) -> List[Dict]:
        """
        Query all subset picks with actual results for the season.

        Joins current_subset_picks with player_game_summary for actuals.
        Uses latest version_id per date.
        """
        query = """
        WITH latest_versions AS (
          SELECT game_date, MAX(version_id) as version_id
          FROM `nba_predictions.current_subset_picks`
          WHERE game_date >= @start_date AND game_date < @end_date
          GROUP BY game_date
        )
        SELECT
          csp.subset_id,
          csp.game_date,
          csp.player_name,
          csp.team,
          csp.opponent,
          ROUND(csp.predicted_points, 1) as predicted_points,
          ROUND(csp.current_points_line, 1) as current_points_line,
          csp.recommendation,
          pgs.points as actual_points
        FROM `nba_predictions.current_subset_picks` csp
        JOIN latest_versions lv
          ON csp.game_date = lv.game_date AND csp.version_id = lv.version_id
        LEFT JOIN `nba_analytics.player_game_summary` pgs
          ON csp.player_lookup = pgs.player_lookup
          AND csp.game_date = pgs.game_date
        WHERE csp.game_date >= @start_date
          AND csp.game_date < @end_date
        ORDER BY csp.game_date DESC, csp.subset_id, csp.composite_score DESC
        """

        params = [
            bigquery.ScalarQueryParameter('start_date', 'DATE', start_date),
            bigquery.ScalarQueryParameter('end_date', 'DATE', end_date),
        ]

        try:
            return self.query_to_list(query, params)
        except Exception as e:
            logger.error(f"Failed to query season picks: {e}")
            return []

    def _query_season_signals(self, start_date: str, end_date: str) -> Dict[str, str]:
        """Query daily signals for the season, return date → public signal mapping."""
        query = """
        SELECT game_date, daily_signal
        FROM `nba_predictions.daily_prediction_signals`
        WHERE game_date >= @start_date
          AND game_date < @end_date
          AND system_id = 'catboost_v9'
        """

        params = [
            bigquery.ScalarQueryParameter('start_date', 'DATE', start_date),
            bigquery.ScalarQueryParameter('end_date', 'DATE', end_date),
        ]

        try:
            results = self.query_to_list(query, params)
            return {
                str(r['game_date']): SIGNAL_MAP.get(r.get('daily_signal', 'YELLOW'), 'neutral')
                for r in results
            }
        except Exception as e:
            logger.warning(f"Failed to query season signals: {e}")
            return {}

    def _query_records(self, season_start: date, today: date) -> Dict[str, Dict]:
        """Query W-L records for all subsets across season/month/week windows."""
        month_start = today.replace(day=1)
        week_start = today - timedelta(days=today.weekday())

        query = """
        WITH base AS (
          SELECT subset_id, game_date, wins, graded_picks
          FROM `nba_predictions.v_dynamic_subset_performance`
          WHERE game_date >= @season_start AND game_date < @end_date
        )
        SELECT
          subset_id,
          SUM(wins) as season_wins,
          SUM(graded_picks - wins) as season_losses,
          ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) as season_pct,
          SUM(CASE WHEN game_date >= @month_start THEN wins ELSE 0 END) as month_wins,
          SUM(CASE WHEN game_date >= @month_start THEN graded_picks - wins ELSE 0 END) as month_losses,
          ROUND(100.0 *
            SUM(CASE WHEN game_date >= @month_start THEN wins ELSE 0 END) /
            NULLIF(SUM(CASE WHEN game_date >= @month_start THEN graded_picks ELSE 0 END), 0),
          1) as month_pct,
          SUM(CASE WHEN game_date >= @week_start THEN wins ELSE 0 END) as week_wins,
          SUM(CASE WHEN game_date >= @week_start THEN graded_picks - wins ELSE 0 END) as week_losses,
          ROUND(100.0 *
            SUM(CASE WHEN game_date >= @week_start THEN wins ELSE 0 END) /
            NULLIF(SUM(CASE WHEN game_date >= @week_start THEN graded_picks ELSE 0 END), 0),
          1) as week_pct
        FROM base
        GROUP BY subset_id
        """

        params = [
            bigquery.ScalarQueryParameter('season_start', 'DATE', season_start.isoformat()),
            bigquery.ScalarQueryParameter('month_start', 'DATE', month_start.isoformat()),
            bigquery.ScalarQueryParameter('week_start', 'DATE', week_start.isoformat()),
            bigquery.ScalarQueryParameter('end_date', 'DATE', today.isoformat()),
        ]

        try:
            results = self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query records: {e}")
            return {}

        records = {}
        for r in results:
            records[r['subset_id']] = {
                'season': {
                    'wins': int(r.get('season_wins') or 0),
                    'losses': int(r.get('season_losses') or 0),
                    'pct': float(r.get('season_pct') or 0),
                },
                'month': {
                    'wins': int(r.get('month_wins') or 0),
                    'losses': int(r.get('month_losses') or 0),
                    'pct': float(r.get('month_pct') or 0),
                },
                'week': {
                    'wins': int(r.get('week_wins') or 0),
                    'losses': int(r.get('week_losses') or 0),
                    'pct': float(r.get('week_pct') or 0),
                },
            }
        return records

    def _group_picks(
        self,
        all_picks: List[Dict],
        signals: Dict[str, str],
    ) -> Dict[str, Dict[str, Dict]]:
        """
        Group flat pick rows into subset → date → picks structure.

        Returns:
            {subset_id: {date_str: {'signal': str, 'picks': [...]}}
        """
        groups = {}

        for pick in all_picks:
            subset_id = pick['subset_id']
            game_date = str(pick['game_date'])

            if subset_id not in groups:
                groups[subset_id] = {}

            if game_date not in groups[subset_id]:
                groups[subset_id][game_date] = {
                    'signal': signals.get(game_date, 'neutral'),
                    'picks': [],
                }

            # Determine result
            actual = pick.get('actual_points')
            line = pick.get('current_points_line')
            direction = pick.get('recommendation')
            result = None

            if actual is not None and line is not None and actual != line:
                if direction == 'OVER':
                    result = 'hit' if actual > line else 'miss'
                elif direction == 'UNDER':
                    result = 'hit' if actual < line else 'miss'

            clean_pick = {
                'player': pick['player_name'],
                'team': pick['team'],
                'opponent': pick['opponent'],
                'prediction': float(pick['predicted_points']),
                'line': float(pick['current_points_line']),
                'direction': direction,
            }

            # Only include actual/result for graded games
            if actual is not None:
                clean_pick['actual'] = int(actual)
                clean_pick['result'] = result or 'push'
            else:
                clean_pick['actual'] = None
                clean_pick['result'] = None

            groups[subset_id][game_date]['picks'].append(clean_pick)

        return groups

    def export(self, **kwargs) -> str:
        """Generate and upload season subset picks to GCS."""
        json_data = self.generate_json()

        gcs_path = self.upload_to_gcs(
            json_data=json_data,
            path='subsets/season.json',
            cache_control='public, max-age=3600'  # 1 hour cache
        )

        total_groups = len(json_data.get('groups', []))
        total_dates = sum(len(g.get('dates', [])) for g in json_data.get('groups', []))
        logger.info(
            f"Exported season subset picks: {total_groups} groups, "
            f"{total_dates} total date entries to {gcs_path}"
        )

        return gcs_path


def _empty_record() -> Dict:
    """Return an empty record structure."""
    empty = {'wins': 0, 'losses': 0, 'pct': 0.0}
    return {'season': empty.copy(), 'month': empty.copy(), 'week': empty.copy()}
