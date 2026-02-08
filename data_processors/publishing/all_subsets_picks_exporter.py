"""
All Subsets Picks Exporter for Phase 6 Publishing

Exports all subset groups' picks in a single file with clean API.
Main endpoint for fetching daily picks without exposing technical details.

Session 152: Added subset snapshot recording for history tracking.
Session 153: Reads from materialized current_subset_picks table.
             Falls back to on-the-fly computation for old dates.
             Removed _record_snapshot (superseded by SubsetMaterializer).
"""

import logging
from typing import Dict, List, Any, Optional

from google.cloud import bigquery

from .base_exporter import BaseExporter
from shared.config.model_codenames import get_model_codename
from shared.config.subset_public_names import get_public_name

logger = logging.getLogger(__name__)


class AllSubsetsPicksExporter(BaseExporter):
    """
    Export all subset picks in one combined file.

    Output file:
    - picks/{date}.json - All groups in one file

    Session 153: Reads from materialized current_subset_picks table when available.
    Falls back to on-the-fly computation for dates without materialized data.

    JSON structure (CLEAN - no technical details):
    {
        "date": "2026-02-03",
        "generated_at": "2026-02-03T...",
        "model": "926A",
        "groups": [
            {
                "id": "1",
                "name": "Top Pick",
                "stats": {
                    "hit_rate": 81.8,
                    "roi": 15.2,
                    "days": 30
                },
                "picks": [
                    {
                        "player": "LeBron James",
                        "team": "LAL",
                        "opponent": "BOS",
                        "prediction": 26.1,
                        "line": 24.5,
                        "direction": "OVER"
                    },
                    ...
                ]
            },
            ...
        ]
    }
    """

    def generate_json(self, target_date: str) -> Dict[str, Any]:
        """
        Generate combined picks JSON for all subsets.

        Session 153: Tries to read from materialized current_subset_picks first.
        Falls back to on-the-fly computation if no materialized data exists.

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            Dictionary ready for JSON serialization with clean structure
        """
        # Try materialized table first (Session 153)
        materialized_picks = self._query_materialized_picks(target_date)

        if materialized_picks:
            logger.info(f"Using materialized picks for {target_date} ({len(materialized_picks)} rows)")
            return self._build_json_from_materialized(target_date, materialized_picks)

        # Fallback: compute on-the-fly (for old dates without materialized data)
        logger.info(f"No materialized picks for {target_date}, computing on-the-fly")
        return self._build_json_on_the_fly(target_date)

    def _query_materialized_picks(self, target_date: str) -> List[Dict[str, Any]]:
        """
        Query materialized subset picks from current_subset_picks table.

        Uses the latest version_id for the date (append-only design, no is_current flag).

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            List of pick dictionaries, or empty list if none found
        """
        query = """
        SELECT
          subset_id,
          subset_name,
          player_name,
          team,
          opponent,
          predicted_points,
          current_points_line,
          recommendation,
          composite_score
        FROM `nba_predictions.current_subset_picks`
        WHERE game_date = @target_date
          AND version_id = (
            SELECT MAX(version_id)
            FROM `nba_predictions.current_subset_picks`
            WHERE game_date = @target_date
          )
        ORDER BY subset_id, composite_score DESC
        """
        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
        try:
            return self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query materialized picks (table may not exist): {e}")
            return []

    def _build_json_from_materialized(
        self,
        target_date: str,
        materialized_picks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Build export JSON from materialized picks data.

        Args:
            target_date: Date string in YYYY-MM-DD format
            materialized_picks: Rows from current_subset_picks

        Returns:
            Dictionary ready for JSON serialization
        """
        # Get performance stats
        all_performance = self._get_all_subset_performance()

        # Group picks by subset_id
        picks_by_subset = {}
        for pick in materialized_picks:
            sid = pick['subset_id']
            if sid not in picks_by_subset:
                picks_by_subset[sid] = {
                    'subset_name': pick['subset_name'],
                    'picks': [],
                }
            picks_by_subset[sid]['picks'].append(pick)

        # Build clean groups
        clean_groups = []
        for subset_id, data in picks_by_subset.items():
            public = get_public_name(subset_id)
            stats = all_performance.get(subset_id, {'hit_rate': 0.0, 'roi': 0.0})

            clean_picks = []
            for pick in data['picks']:
                clean_picks.append({
                    'player': pick['player_name'],
                    'team': pick['team'],
                    'opponent': pick['opponent'],
                    'prediction': round(pick['predicted_points'], 1),
                    'line': round(pick['current_points_line'], 1),
                    'direction': pick['recommendation'],
                })

            clean_groups.append({
                'id': public['id'],
                'name': public['name'],
                'stats': {
                    'hit_rate': round(stats.get('hit_rate', 0.0), 1),
                    'roi': round(stats.get('roi', 0.0), 1),
                    'days': 30,
                },
                'picks': clean_picks,
            })

        # Sort by ID
        clean_groups.sort(key=lambda x: int(x['id']) if x['id'].isdigit() else 999)

        return {
            'date': target_date,
            'generated_at': self.get_generated_at(),
            'model': get_model_codename('catboost_v9'),
            'groups': clean_groups,
        }

    def _build_json_on_the_fly(self, target_date: str) -> Dict[str, Any]:
        """
        Fallback: compute subset picks on-the-fly (for dates without materialized data).

        This preserves the original generate_json logic from before Session 153.

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            Dictionary ready for JSON serialization
        """
        subsets = self._query_subset_definitions()
        predictions = self._query_all_predictions(target_date)
        daily_signal = self._query_daily_signal(target_date)
        all_performance = self._get_all_subset_performance()

        clean_groups = []
        for subset in subsets:
            subset_picks = self._filter_picks_for_subset(
                predictions, subset, daily_signal
            )
            public = get_public_name(subset['subset_id'])
            stats = all_performance.get(subset['subset_id'], {'hit_rate': 0.0, 'roi': 0.0})

            clean_picks = []
            for pick in subset_picks:
                clean_picks.append({
                    'player': pick['player_name'],
                    'team': pick['team'],
                    'opponent': pick['opponent'],
                    'prediction': round(pick['predicted_points'], 1),
                    'line': round(pick['current_points_line'], 1),
                    'direction': pick['recommendation'],
                })

            clean_groups.append({
                'id': public['id'],
                'name': public['name'],
                'stats': {
                    'hit_rate': round(stats.get('hit_rate', 0.0), 1),
                    'roi': round(stats.get('roi', 0.0), 1),
                    'days': 30,
                },
                'picks': clean_picks,
            })

        clean_groups.sort(key=lambda x: int(x['id']) if x['id'].isdigit() else 999)

        return {
            'date': target_date,
            'generated_at': self.get_generated_at(),
            'model': get_model_codename('catboost_v9'),
            'groups': clean_groups,
        }

    def _query_subset_definitions(self) -> List[Dict[str, Any]]:
        """
        Query all active subset definitions.

        Returns:
            List of subset definition dictionaries
        """
        query = """
        SELECT
          subset_id,
          subset_name,
          subset_description,
          system_id,
          use_ranking,
          top_n,
          min_edge,
          min_confidence,
          signal_condition,
          direction,
          pct_over_min,
          pct_over_max,
          is_active
        FROM `nba_predictions.dynamic_subset_definitions`
        WHERE is_active = TRUE
          AND system_id = 'catboost_v9'
        ORDER BY subset_id
        """

        return self.query_to_list(query)

    # Minimum feature quality score for picks to be included in exports
    # Session 94: Players with missing BDB shot zone data have quality ~82%
    # and hit at 51.9% vs 56.8% for high quality (85%+)
    MIN_FEATURE_QUALITY_SCORE = 85.0

    def _query_all_predictions(self, target_date: str) -> List[Dict[str, Any]]:
        """
        Query all predictions for a specific date (fallback path).

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            List of prediction dictionaries
        """
        query = """
        WITH player_names AS (
          -- Get player full names from registry
          SELECT player_lookup, player_name
          FROM `nba_reference.nba_players_registry`
          QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        )
        SELECT
          p.prediction_id,
          p.player_lookup,
          COALESCE(pn.player_name, p.player_lookup) as player_name,
          pgs.team_abbr as team,
          pgs.opponent_team_abbr as opponent,
          p.predicted_points,
          p.current_points_line,
          p.recommendation,
          p.confidence_score,
          ABS(p.predicted_points - p.current_points_line) as edge,
          (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) as composite_score,
          -- Session 94: Include feature quality for filtering
          COALESCE(f.feature_quality_score, 0) as feature_quality_score
        FROM `nba_predictions.player_prop_predictions` p
        LEFT JOIN player_names pn
          ON p.player_lookup = pn.player_lookup
        LEFT JOIN `nba_analytics.player_game_summary` pgs
          ON p.player_lookup = pgs.player_lookup
          AND p.game_date = pgs.game_date
        -- Session 94: Join feature store to get quality score
        LEFT JOIN `nba_predictions.ml_feature_store_v2` f
          ON p.player_lookup = f.player_lookup
          AND p.game_date = f.game_date
        WHERE p.game_date = @target_date
          AND p.system_id = 'catboost_v9'
          AND p.is_active = TRUE
          AND p.recommendation IN ('OVER', 'UNDER')  -- Exclude PASS (non-bets)
          AND p.current_points_line IS NOT NULL
          AND pgs.team_abbr IS NOT NULL  -- Only include picks with complete context
          -- Session 94: Filter out low-quality predictions (missing BDB data etc.)
          -- Players with quality < 85% have 51.9% hit rate vs 56.8% for 85%+
          AND COALESCE(f.feature_quality_score, 0) >= @min_quality
        ORDER BY composite_score DESC
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('min_quality', 'FLOAT64', self.MIN_FEATURE_QUALITY_SCORE)
        ]

        return self.query_to_list(query, params)

    def _query_daily_signal(self, target_date: str) -> Optional[Dict[str, Any]]:
        """
        Query daily signal for filtering (fallback path).

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            Signal dictionary or None
        """
        query = """
        SELECT
          game_date,
          daily_signal,
          pct_over
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

    def _filter_picks_for_subset(
        self,
        predictions: List[Dict[str, Any]],
        subset: Dict[str, Any],
        daily_signal: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Filter predictions based on subset criteria (fallback path).

        Args:
            predictions: List of all predictions
            subset: Subset definition dictionary
            daily_signal: Daily signal dictionary

        Returns:
            Filtered list of picks matching subset criteria
        """
        filtered = []

        # Get signal info
        signal = daily_signal.get('daily_signal') if daily_signal else None
        pct_over = daily_signal.get('pct_over') if daily_signal else None

        for pred in predictions:
            # Apply edge filter
            if subset.get('min_edge'):
                if pred['edge'] < float(subset['min_edge']):
                    continue

            # Apply confidence filter
            if subset.get('min_confidence'):
                if pred['confidence_score'] < float(subset['min_confidence']):
                    continue

            # Apply direction filter (OVER, UNDER, or ANY/None = no filter)
            direction = subset.get('direction')
            if direction and direction not in ('ANY', None):
                if pred['recommendation'] != direction:
                    continue

            # Apply signal condition filter (only when we have actual signal data)
            signal_condition = subset.get('signal_condition')
            if signal_condition and signal_condition != 'ANY' and signal:
                if signal_condition == 'GREEN_OR_YELLOW':
                    if signal not in ('GREEN', 'YELLOW'):
                        continue
                elif signal != signal_condition:
                    continue

            # Apply pct_over range filter
            if pct_over is not None:
                pct_over_min = subset.get('pct_over_min')
                pct_over_max = subset.get('pct_over_max')

                if pct_over_min is not None and pct_over < float(pct_over_min):
                    continue
                if pct_over_max is not None and pct_over > float(pct_over_max):
                    continue

            filtered.append(pred)

        # Apply ranking and limit if specified
        if subset.get('use_ranking'):
            # Already sorted by composite_score DESC in query
            pass

        # Apply top_n limit
        if subset.get('top_n'):
            top_n = int(subset['top_n'])
            filtered = filtered[:top_n]

        return filtered

    def _get_all_subset_performance(self) -> Dict[str, Dict[str, float]]:
        """
        Get 30-day performance stats for ALL subsets in one query.

        This replaces the N+1 query pattern with a single batch query.

        Returns:
            Dictionary mapping subset_id to {hit_rate, roi}
        """
        query = """
        SELECT
          subset_id,
          ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) as hit_rate,
          ROUND(
            100.0 * SUM(wins * 0.909 - (graded_picks - wins)) / NULLIF(SUM(graded_picks), 0),
            1
          ) as roi
        FROM `nba_predictions.v_dynamic_subset_performance`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
        GROUP BY subset_id
        """

        results = self.query_to_list(query)
        return {
            r['subset_id']: {
                'hit_rate': r.get('hit_rate') or 0.0,
                'roi': r.get('roi') or 0.0
            }
            for r in results
        }

    def export(self, target_date: str, trigger_source: str = 'unknown', batch_id: str = None) -> str:
        """
        Generate and upload all subsets picks to GCS.

        Args:
            target_date: Date string in YYYY-MM-DD format
            trigger_source: What triggered this export (overnight, same_day, line_check, manual)
            batch_id: Optional prediction batch ID that triggered this export

        Returns:
            GCS path where file was uploaded
        """
        json_data = self.generate_json(target_date)

        # Upload to GCS (5 minute cache for fresh data)
        gcs_path = self.upload_to_gcs(
            json_data=json_data,
            path=f'picks/{target_date}.json',
            cache_control='public, max-age=300'  # 5 minutes
        )

        total_picks = sum(len(g['picks']) for g in json_data.get('groups', []))
        logger.info(
            f"Exported {len(json_data.get('groups', []))} groups "
            f"with {total_picks} total picks for {target_date} to {gcs_path}"
        )

        return gcs_path
