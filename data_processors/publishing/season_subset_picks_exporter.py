"""
Season Subset Picks Exporter for Phase 6 Publishing

Exports full-season subset picks in a single file for instant tab/date switching.
Includes W-L records per subset (season/month/week) and per-pick results.

Session 158: Created for new subset picks page with tabs per subset.
Session 191: Multi-model v2 — model_groups structure with per-model picks and records.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Any, Optional
from datetime import date, timedelta

from google.cloud import bigquery

from .base_exporter import BaseExporter
from shared.config.model_codenames import get_model_display_info, CHAMPION_CODENAME
from shared.config.subset_public_names import get_public_name

logger = logging.getLogger(__name__)

# Signal mapping: internal -> public
SIGNAL_MAP = {
    'GREEN': 'favorable',
    'YELLOW': 'neutral',
    'RED': 'challenging',
}

# Champion model — used for signal queries
CHAMPION_SYSTEM_ID = 'catboost_v9'


class SeasonSubsetPicksExporter(BaseExporter):
    """
    Export full-season subset picks in one file, grouped by model.

    Output file:
    - subsets/season.json

    Session 191: v2 multi-model structure.

    JSON structure (v2):
    {
        "generated_at": "2026-02-10T...",
        "version": 2,
        "season": "2025-26",
        "model_groups": [
            {
                "model_id": "phoenix",
                "model_name": "Phoenix",
                "model_type": "primary",
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
        """Generate full-season subset picks JSON with multi-model support."""
        today = date.today()
        season_start, season_label = self._get_season_bounds(today)

        # Get all picks with results for the season (all models)
        # Use tomorrow as exclusive upper bound to include today's picks
        end_date = (today + timedelta(days=1)).isoformat()
        all_picks = self._query_season_picks(season_start.isoformat(), end_date)

        if not all_picks:
            logger.warning(
                f"No current_subset_picks data found for season {season_label} "
                f"({season_start} to {end_date}). season.json will have empty model_groups."
            )

        # Get daily signals for the season
        signals = self._query_season_signals(season_start.isoformat(), end_date)

        # Get W-L records per subset (uses performance view)
        records = self._query_records(season_start, today)

        # Group picks: system_id -> subset_id -> date -> picks
        picks_by_model = self._group_picks_by_model(all_picks, signals)

        # Get subset definitions to know which model owns which subset
        subset_defs = self._query_subset_definitions()
        model_subsets = defaultdict(set)
        for d in subset_defs:
            model_subsets[d['system_id']].add(d['subset_id'])

        # Build model_groups
        model_groups = []
        for system_id, subset_ids in model_subsets.items():
            display = get_model_display_info(system_id)

            # Aggregate records across this model's subsets
            model_record = self._aggregate_records(records, subset_ids, season_start, today)

            # Build dates array from picks
            dates_data = picks_by_model.get(system_id, {})
            clean_dates = []
            for game_date in sorted(dates_data.keys(), reverse=True):
                day_data = dates_data[game_date]
                clean_dates.append({
                    'date': game_date,
                    'signal': day_data['signal'],
                    'picks': day_data['picks'],
                })

            model_groups.append({
                'model_id': display['codename'],
                'model_name': display['display_name'],
                'model_type': display['model_type'],
                'record': model_record,
                'dates': clean_dates,
            })

        # Sort: champion first, then by codename
        model_groups.sort(key=lambda x: (0 if x['model_id'] == CHAMPION_CODENAME else 1, x['model_id']))

        return {
            'generated_at': self.get_generated_at(),
            'version': 2,
            'season': season_label,
            'model_groups': model_groups,
        }

    def _query_season_picks(self, start_date: str, end_date: str) -> List[Dict]:
        """
        Query all subset picks with actual results for the season (all models).

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
          csp.system_id,
          csp.game_date,
          csp.player_name,
          csp.team,
          csp.opponent,
          ROUND(csp.predicted_points, 1) as predicted_points,
          ROUND(csp.current_points_line, 1) as current_points_line,
          csp.recommendation,
          pgs.points as actual_points,
          p.created_at as prediction_created_at
        FROM `nba_predictions.current_subset_picks` csp
        JOIN latest_versions lv
          ON csp.game_date = lv.game_date AND csp.version_id = lv.version_id
        LEFT JOIN `nba_analytics.player_game_summary` pgs
          ON csp.player_lookup = pgs.player_lookup
          AND csp.game_date = pgs.game_date
        LEFT JOIN `nba_predictions.player_prop_predictions` p
          ON csp.prediction_id = p.prediction_id
          AND csp.game_date = p.game_date
        WHERE csp.game_date >= @start_date
          AND csp.game_date < @end_date
        ORDER BY csp.game_date DESC, csp.system_id, csp.subset_id, csp.composite_score DESC
        """

        params = [
            bigquery.ScalarQueryParameter('start_date', 'DATE', start_date),
            bigquery.ScalarQueryParameter('end_date', 'DATE', end_date),
        ]

        try:
            results = self.query_to_list(query, params)
            logger.info(f"Season picks query returned {len(results)} rows for {start_date} to {end_date}")
            return results
        except Exception as e:
            logger.error(f"Failed to query season picks: {e}", exc_info=True)
            return []

    def _query_season_signals(self, start_date: str, end_date: str) -> Dict[str, str]:
        """Query daily signals for the season, return date -> public signal mapping."""
        query = """
        SELECT game_date, daily_signal
        FROM `nba_predictions.daily_prediction_signals`
        WHERE game_date >= @start_date
          AND game_date < @end_date
          AND system_id = @system_id
        """

        params = [
            bigquery.ScalarQueryParameter('start_date', 'DATE', start_date),
            bigquery.ScalarQueryParameter('end_date', 'DATE', end_date),
            bigquery.ScalarQueryParameter('system_id', 'STRING', CHAMPION_SYSTEM_ID),
        ]

        try:
            results = self.query_to_list(query, params)
            return {
                str(r['game_date']): SIGNAL_MAP.get(r.get('daily_signal', 'YELLOW'), 'neutral')
                for r in results
            }
        except Exception as e:
            logger.warning(f"Failed to query season signals: {e}", exc_info=True)
            return {}

    def _query_subset_definitions(self) -> List[Dict]:
        """Query active subset definitions to discover models."""
        query = """
        SELECT subset_id, system_id
        FROM `nba_predictions.dynamic_subset_definitions`
        WHERE is_active = TRUE
        ORDER BY system_id, subset_id
        """
        return self.query_to_list(query)

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
            logger.info(f"Records query returned {len(results)} subsets")
        except Exception as e:
            logger.warning(f"Failed to query records: {e}", exc_info=True)
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

    def _aggregate_records(
        self,
        records: Dict[str, Dict],
        subset_ids: set,
        season_start: date,
        today: date,
    ) -> Optional[Dict]:
        """
        Aggregate W-L records across a model's subsets.

        Uses the model's 'all picks' subset if available, otherwise sums across subsets.
        Returns None if no grading data exists (new model -> website shows "New" badge).
        """
        # Find the best representative subset for this model's overall record
        # Prefer the broadest subset (all picks / high_edge_all)
        broad_subsets = [sid for sid in subset_ids if 'all' in sid]
        representative = broad_subsets[0] if broad_subsets else (list(subset_ids)[0] if subset_ids else None)

        if representative and representative in records:
            return records[representative]

        # No grading data — return None so frontend shows "New" badge
        return None

    def _group_picks_by_model(
        self,
        all_picks: List[Dict],
        signals: Dict[str, str],
    ) -> Dict[str, Dict[str, Dict]]:
        """
        Group flat pick rows into system_id -> date -> picks structure.

        Returns:
            {system_id: {date_str: {'signal': str, 'picks': [...]}}}
        """
        groups = defaultdict(lambda: defaultdict(lambda: {'signal': 'neutral', 'picks': []}))

        for pick in all_picks:
            system_id = pick.get('system_id') or CHAMPION_SYSTEM_ID
            game_date = str(pick['game_date'])

            groups[system_id][game_date]['signal'] = signals.get(game_date, 'neutral')

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

            created_at = pick.get('prediction_created_at')
            if created_at and hasattr(created_at, 'isoformat'):
                clean_pick['created_at'] = created_at.isoformat()
            elif created_at:
                clean_pick['created_at'] = str(created_at)

            # Only include actual/result for graded games
            if actual is not None:
                clean_pick['actual'] = int(actual)
                clean_pick['result'] = result or 'push'
            else:
                clean_pick['actual'] = None
                clean_pick['result'] = None

            groups[system_id][game_date]['picks'].append(clean_pick)

        return dict(groups)

    def export(self, **kwargs) -> str:
        """Generate and upload season subset picks to GCS."""
        json_data = self.generate_json()

        if not json_data.get('model_groups'):
            logger.warning(
                "season.json has empty model_groups — no subset picks found for this season. "
                "Check current_subset_picks table and dynamic_subset_definitions."
            )

        gcs_path = self.upload_to_gcs(
            json_data=json_data,
            path='subsets/season.json',
            cache_control='public, max-age=3600'  # 1 hour cache
        )

        total_groups = len(json_data.get('model_groups', []))
        total_dates = sum(len(g.get('dates', [])) for g in json_data.get('model_groups', []))
        logger.info(
            f"Exported season subset picks: {total_groups} model groups, "
            f"{total_dates} total date entries to {gcs_path}"
        )

        return gcs_path


def _empty_record() -> Dict:
    """Return an empty record structure."""
    empty = {'wins': 0, 'losses': 0, 'pct': 0.0}
    return {'season': empty.copy(), 'month': empty.copy(), 'week': empty.copy()}
