"""
All Subsets Picks Exporter for Phase 6 Publishing

Exports all subset groups' picks in a single consolidated file.
Includes daily signal and W-L records per subset (season/month/week).

Session 152: Added subset snapshot recording for history tracking.
Session 153: Reads from materialized current_subset_picks table.
Session 158: Consolidated export — signal + W-L records + picks in one file.
Session 188: Multi-model support — model_groups structure, QUANT subsets.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Any, Optional
from datetime import date, timedelta

from google.cloud import bigquery

from .base_exporter import BaseExporter
from shared.config.cross_model_subsets import classify_system_id
from shared.config.model_codenames import get_model_codename, get_model_display_info, CHAMPION_CODENAME
from shared.config.subset_public_names import get_public_name
from shared.utils.quality_filter import should_include_prediction  # Session 209

logger = logging.getLogger(__name__)

# Champion model — used for signal and as fallback
from shared.config.model_selection import get_champion_model_id
CHAMPION_SYSTEM_ID = get_champion_model_id()


class AllSubsetsPicksExporter(BaseExporter):
    """
    Export all subset picks, signal, and records in one combined file.

    Output file:
    - picks/{date}.json - Consolidated daily export

    Session 188: model_groups structure with nested subsets per model.

    JSON structure (v2):
    {
        "date": "2026-02-10",
        "generated_at": "...",
        "version": 2,
        "model_groups": [
            {
                "model_id": "926A",
                "model_name": "V9 Champion",
                "model_type": "standard",
                "description": "Primary prediction model",
                "signal": "favorable",
                "subsets": [
                    {
                        "id": "1",
                        "name": "Top Pick",
                        "record": {"season": {...}, "month": {...}, "week": {...}},
                        "picks": [{"player": "...", "team": "...", ...}]
                    }
                ]
            }
        ]
    }
    """

    def generate_json(self, target_date: str) -> Dict[str, Any]:
        """
        Generate consolidated JSON with signal, records, and picks.

        Session 188: Multi-model model_groups structure.

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            Dictionary ready for JSON serialization
        """
        # Get signal for this date (champion model — signal is market-level)
        signal = self._get_public_signal(target_date)

        # Get W-L records per subset (season/month/week)
        records = self._get_subset_records(target_date)

        # Try materialized table first (Session 153)
        materialized_picks = self._query_materialized_picks(target_date)

        if materialized_picks:
            logger.info(f"Using materialized picks for {target_date} ({len(materialized_picks)} rows)")
            return self._build_json_from_materialized(target_date, materialized_picks, signal, records)

        # Fallback: compute on-the-fly (for old dates without materialized data)
        logger.info(f"No materialized picks for {target_date}, computing on-the-fly")
        return self._build_json_on_the_fly(target_date, signal, records)

    def _query_materialized_picks(self, target_date: str) -> List[Dict[str, Any]]:
        """
        Query materialized subset picks from current_subset_picks table (all models).

        Uses the latest version_id for the date (append-only design, no is_current flag).

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            List of pick dictionaries, or empty list if none found
        """
        query = """
        SELECT
          csp.subset_id,
          csp.subset_name,
          csp.system_id,
          csp.player_lookup,
          csp.player_name,
          csp.team,
          csp.opponent,
          csp.predicted_points,
          csp.current_points_line,
          csp.recommendation,
          csp.composite_score,
          p.created_at as prediction_created_at,
          pgs.points as actual_points,
          gb.player_status as gamebook_status,
          pst.signal_tags
        FROM `nba_predictions.current_subset_picks` csp
        LEFT JOIN `nba_predictions.player_prop_predictions` p
          ON csp.prediction_id = p.prediction_id
          AND csp.game_date = p.game_date
        LEFT JOIN `nba_analytics.player_game_summary` pgs
          ON csp.player_lookup = pgs.player_lookup
          AND csp.game_date = pgs.game_date
        LEFT JOIN `nba_raw.nbac_gamebook_player_stats` gb
          ON csp.player_lookup = gb.player_lookup
          AND csp.game_date = gb.game_date
        LEFT JOIN `nba_predictions.pick_signal_tags` pst
          ON csp.player_lookup = pst.player_lookup
          AND csp.game_date = pst.game_date
          AND csp.system_id = pst.system_id
        WHERE csp.game_date = @target_date
          AND csp.version_id = (
            SELECT MAX(version_id)
            FROM `nba_predictions.current_subset_picks`
            WHERE game_date = @target_date
          )
        ORDER BY csp.system_id, csp.subset_id, csp.composite_score DESC
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
        signal: str = 'neutral',
        records: Optional[Dict[str, Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Build export JSON from materialized picks data.

        Session 188: Groups picks by model, then by subset within each model.

        Args:
            target_date: Date string in YYYY-MM-DD format
            materialized_picks: Rows from current_subset_picks
            signal: Public signal string (favorable/neutral/challenging)
            records: Per-subset W-L records by window

        Returns:
            Dictionary ready for JSON serialization
        """
        records = records or {}

        # Group picks by system_id -> subset_id
        # Session 226: Deduplicate by player_lookup within each (system_id, subset_id)
        # to handle historical data with UNION ALL duplication bug
        picks_by_model = defaultdict(lambda: defaultdict(list))
        seen_keys = set()
        for pick in materialized_picks:
            system_id = pick.get('system_id') or CHAMPION_SYSTEM_ID
            dedup_key = (system_id, pick['subset_id'], pick['player_lookup'])
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            picks_by_model[system_id][pick['subset_id']].append(pick)

        # Build model_groups
        model_groups = []
        for system_id, subsets_data in picks_by_model.items():
            display = get_model_display_info(system_id)

            clean_subsets = []
            for subset_id, picks in subsets_data.items():
                public = get_public_name(subset_id)
                subset_record = records.get(subset_id)
                if subset_record is None:
                    subset_record = None  # New models: null record -> website shows "New"

                clean_picks = []
                for pick in picks:
                    pick_data = {
                        'player_lookup': pick['player_lookup'],
                        'player': pick['player_name'],
                        'team': pick['team'],
                        'opponent': pick['opponent'],
                        'prediction': round(pick['predicted_points'], 1),
                        'line': round(pick['current_points_line'], 1),
                        'direction': pick['recommendation'],
                        'signals': pick.get('signal_tags') or [],
                    }
                    created_at = pick.get('prediction_created_at')
                    if created_at and hasattr(created_at, 'isoformat'):
                        pick_data['created_at'] = created_at.isoformat()
                    elif created_at:
                        pick_data['created_at'] = str(created_at)

                    # Add actual/result if game has been played
                    actual = pick.get('actual_points')
                    line = pick.get('current_points_line')
                    direction = pick.get('recommendation')
                    gamebook_status = pick.get('gamebook_status')
                    if actual is not None:
                        pick_data['actual'] = int(actual)
                        if direction == 'OVER':
                            pick_data['result'] = 'hit' if actual > line else ('push' if actual == line else 'miss')
                        elif direction == 'UNDER':
                            pick_data['result'] = 'hit' if actual < line else ('push' if actual == line else 'miss')
                        else:
                            pick_data['result'] = None
                    elif gamebook_status in ('dnp', 'inactive'):
                        pick_data['actual'] = None
                        pick_data['result'] = 'dnp'
                    else:
                        pick_data['actual'] = None
                        pick_data['result'] = None

                    clean_picks.append(pick_data)

                clean_subsets.append({
                    'id': public['id'],
                    'name': public['name'],
                    'record': subset_record,
                    'picks': clean_picks,
                })

            clean_subsets.sort(key=lambda x: int(x['id']) if x['id'].isdigit() else 999)

            model_groups.append({
                'model_id': display['codename'],
                'model_name': display['display_name'],
                'model_type': display['model_type'],
                'description': display['description'],
                'signal': signal,
                'subsets': clean_subsets,
            })

        # Sort: champion first, then by codename
        model_groups.sort(key=lambda x: (0 if x['model_id'] == CHAMPION_CODENAME else 1, x['model_id']))

        return {
            'date': target_date,
            'generated_at': self.get_generated_at(),
            'version': 2,
            'model_groups': model_groups,
        }

    def _build_json_on_the_fly(
        self,
        target_date: str,
        signal: str = 'neutral',
        records: Optional[Dict[str, Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Fallback: compute subset picks on-the-fly (for dates without materialized data).

        Session 188: Multi-model support. Groups subsets by model.

        Args:
            target_date: Date string in YYYY-MM-DD format
            signal: Public signal string
            records: Per-subset W-L records by window

        Returns:
            Dictionary ready for JSON serialization
        """
        records = records or {}
        subsets = self._query_subset_definitions()
        daily_signal = self._query_daily_signal(target_date)

        # Session 311B: Resolve stale system_ids in fallback path
        # Same fix as SubsetMaterializer — definitions may reference old model names
        active_ids = self._query_active_system_ids(target_date)
        if active_ids:
            subsets = self._resolve_stale_system_ids(subsets, active_ids)

        # Group definitions by system_id
        subsets_by_model = defaultdict(list)
        for subset in subsets:
            subsets_by_model[subset['system_id']].append(subset)

        model_groups = []
        for system_id, model_subsets in subsets_by_model.items():
            # Split subsets into quality-filtered (regular) vs unfiltered (all_predictions)
            regular_subsets = [s for s in model_subsets if 'all_predictions' not in s['subset_id']]
            unfiltered_subsets = [s for s in model_subsets if 'all_predictions' in s['subset_id']]

            display = get_model_display_info(system_id)
            clean_subsets = []

            # Regular subsets: quality >= 85 filter (existing behavior)
            if regular_subsets:
                predictions = self._query_all_predictions(target_date, system_id)
                for subset in regular_subsets:
                    clean_subsets.append(
                        self._build_subset_json(subset, predictions, daily_signal, records)
                    )

            # All Predictions subsets: no quality filter
            if unfiltered_subsets:
                all_preds = self._query_all_predictions(target_date, system_id, min_quality=0)
                for subset in unfiltered_subsets:
                    clean_subsets.append(
                        self._build_subset_json(subset, all_preds, daily_signal, records)
                    )

            clean_subsets.sort(key=lambda x: int(x['id']) if x['id'].isdigit() else 999)

            model_groups.append({
                'model_id': display['codename'],
                'model_name': display['display_name'],
                'model_type': display['model_type'],
                'description': display['description'],
                'signal': signal,
                'subsets': clean_subsets,
            })

        model_groups.sort(key=lambda x: (0 if x['model_id'] == CHAMPION_CODENAME else 1, x['model_id']))

        return {
            'date': target_date,
            'generated_at': self.get_generated_at(),
            'version': 2,
            'model_groups': model_groups,
        }

    def _query_subset_definitions(self) -> List[Dict[str, Any]]:
        """
        Query all active subset definitions (all models).

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
        ORDER BY system_id, subset_id
        """

        return self.query_to_list(query)

    # Minimum feature quality score for picks to be included in exports
    # Session 94: Players with missing BDB shot zone data have quality ~82%
    # and hit at 51.9% vs 56.8% for high quality (85%+)
    MIN_FEATURE_QUALITY_SCORE = 85.0

    def _query_all_predictions(self, target_date: str, system_id: str = CHAMPION_SYSTEM_ID, min_quality: float = None) -> List[Dict[str, Any]]:
        """
        Query all predictions for a specific date and model (fallback path).

        Args:
            target_date: Date string in YYYY-MM-DD format
            system_id: Model system_id to query
            min_quality: Minimum feature quality score. Defaults to MIN_FEATURE_QUALITY_SCORE (85).
                         Pass 0 for unfiltered "all predictions" subsets.

        Returns:
            List of prediction dictionaries
        """
        min_quality = min_quality if min_quality is not None else self.MIN_FEATURE_QUALITY_SCORE
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
          COALESCE(f.feature_quality_score, 0) as feature_quality_score,
          p.created_at as prediction_created_at,
          pgs.points as actual_points
        FROM `nba_predictions.player_prop_predictions` p
        LEFT JOIN player_names pn
          ON p.player_lookup = pn.player_lookup
        LEFT JOIN `nba_analytics.player_game_summary` pgs
          ON p.player_lookup = pgs.player_lookup
          AND p.game_date = pgs.game_date
        LEFT JOIN `nba_predictions.ml_feature_store_v2` f
          ON p.player_lookup = f.player_lookup
          AND p.game_date = f.game_date
        WHERE p.game_date = @target_date
          AND p.system_id = @system_id
          AND p.is_active = TRUE
          AND p.recommendation IN ('OVER', 'UNDER')
          AND p.current_points_line IS NOT NULL
          AND pgs.team_abbr IS NOT NULL
          AND COALESCE(f.feature_quality_score, 0) >= @min_quality
        ORDER BY composite_score DESC
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('system_id', 'STRING', system_id),
            bigquery.ScalarQueryParameter('min_quality', 'FLOAT64', min_quality),
        ]

        return self.query_to_list(query, params)

    def _query_daily_signal(self, target_date: str) -> Optional[Dict[str, Any]]:
        """
        Query daily signal from champion model (signal reflects market conditions).

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
          AND system_id = @system_id
        LIMIT 1
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('system_id', 'STRING', CHAMPION_SYSTEM_ID),
        ]

        results = self.query_to_list(query, params)
        return results[0] if results else None

    def _build_subset_json(
        self,
        subset: Dict[str, Any],
        predictions: List[Dict[str, Any]],
        daily_signal: Optional[Dict[str, Any]],
        records: Dict[str, Dict],
    ) -> Dict[str, Any]:
        """Build a single subset's JSON output from predictions."""
        subset_picks = self._filter_picks_for_subset(predictions, subset, daily_signal)
        public = get_public_name(subset['subset_id'])
        subset_record = records.get(subset['subset_id'])

        clean_picks = []
        for pick in subset_picks:
            pick_data = {
                'player_lookup': pick['player_lookup'],
                'player': pick['player_name'],
                'team': pick['team'],
                'opponent': pick['opponent'],
                'prediction': round(pick['predicted_points'], 1),
                'line': round(pick['current_points_line'], 1),
                'direction': pick['recommendation'],
            }
            created_at = pick.get('prediction_created_at')
            if created_at and hasattr(created_at, 'isoformat'):
                pick_data['created_at'] = created_at.isoformat()
            elif created_at:
                pick_data['created_at'] = str(created_at)

            # Add actual/result if game has been played
            actual = pick.get('actual_points')
            line = pick.get('current_points_line')
            direction = pick.get('recommendation')
            gamebook_status = pick.get('gamebook_status')
            if actual is not None:
                pick_data['actual'] = int(actual)
                if direction == 'OVER':
                    pick_data['result'] = 'hit' if actual > line else ('push' if actual == line else 'miss')
                elif direction == 'UNDER':
                    pick_data['result'] = 'hit' if actual < line else ('push' if actual == line else 'miss')
                else:
                    pick_data['result'] = None
            elif gamebook_status in ('dnp', 'inactive'):
                pick_data['actual'] = None
                pick_data['result'] = 'dnp'
            else:
                pick_data['actual'] = None
                pick_data['result'] = None

            clean_picks.append(pick_data)

        return {
            'id': public['id'],
            'name': public['name'],
            'record': subset_record,
            'picks': clean_picks,
        }

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

            # Session 209: Quality filter using shared utility
            # Predictions with yellow/red quality alerts have 12.1% hit rate vs 50.3% for green
            if not should_include_prediction(pred, subset):
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

    # ========================================================================
    # STALE SYSTEM_ID RESOLUTION (Session 311B - Fallback path)
    # ========================================================================

    def _query_active_system_ids(self, game_date: str) -> List[str]:
        """Query distinct system_ids with predictions for this date (fallback path)."""
        query = """
        SELECT DISTINCT system_id
        FROM `nba_predictions.player_prop_predictions`
        WHERE game_date = @target_date
          AND is_active = TRUE
          AND recommendation IN ('OVER', 'UNDER')
        """
        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', game_date),
        ]
        try:
            return [r['system_id'] for r in self.query_to_list(query, params)]
        except Exception as e:
            logger.warning(f"Failed to query active system_ids: {e}")
            return []

    def _resolve_stale_system_ids(
        self,
        subsets: List[Dict[str, Any]],
        active_system_ids: List[str],
    ) -> List[Dict[str, Any]]:
        """Resolve stale system_ids in definitions to currently active ones.

        Session 311B: Same logic as SubsetMaterializer._resolve_stale_system_ids.
        """
        family_to_active = {}
        for sid in active_system_ids:
            family = classify_system_id(sid)
            if family:
                family_to_active[family] = sid

        active_set = set(active_system_ids)
        for subset in subsets:
            def_sid = subset['system_id']
            if def_sid in active_set:
                continue
            family = classify_system_id(def_sid)
            if family and family in family_to_active:
                new_sid = family_to_active[family]
                logger.info(
                    f"Fallback: resolved stale system_id '{def_sid}' → '{new_sid}' "
                    f"for subset '{subset['subset_id']}'"
                )
                subset['system_id'] = new_sid
        return subsets

    # ========================================================================
    # SIGNAL + RECORDS (Session 158 - Consolidated Export)
    # ========================================================================

    def _get_public_signal(self, target_date: str) -> str:
        """
        Get the public-facing signal for a date.

        Returns:
            One of: "favorable", "neutral", "challenging"
        """
        signal_mapping = {
            'GREEN': 'favorable',
            'YELLOW': 'neutral',
            'RED': 'challenging',
        }

        signal_data = self._query_daily_signal(target_date)
        if not signal_data:
            return 'neutral'

        internal = signal_data.get('daily_signal', 'YELLOW')
        return signal_mapping.get(internal, 'neutral')

    def _get_subset_records(self, target_date: str) -> Dict[str, Dict]:
        """
        Get W-L records for all subsets across season/month/week windows.

        Calendar-aligned windows:
        - season: Nov 1 of current season through yesterday
        - month: 1st of current month through yesterday
        - week: Monday of current week through yesterday

        Args:
            target_date: The date we're exporting picks for

        Returns:
            Dict mapping subset_id to {season: {wins, losses, pct}, month: {...}, week: {...}}
        """
        target = date.fromisoformat(target_date) if isinstance(target_date, str) else target_date

        # Calculate calendar-aligned window boundaries
        # Season start: Nov 1 of current NBA season
        season_start_year = target.year if target.month >= 11 else target.year - 1
        season_start = date(season_start_year, 11, 1)

        # Month start: 1st of current month
        month_start = target.replace(day=1)

        # Week start: Monday of current week
        week_start = target - timedelta(days=target.weekday())

        # Query all three windows in a single query
        records = self._query_records_multi_window(
            season_start.isoformat(),
            month_start.isoformat(),
            week_start.isoformat(),
            target_date,
        )

        return records

    def _query_records_multi_window(
        self,
        season_start: str,
        month_start: str,
        week_start: str,
        end_date: str,
    ) -> Dict[str, Dict]:
        """
        Query W-L records for all subsets across three windows in one query.

        Returns:
            Dict mapping subset_id to record dict with season/month/week windows
        """
        query = """
        WITH base AS (
          SELECT
            subset_id,
            game_date,
            wins,
            graded_picks
          FROM `nba_predictions.v_dynamic_subset_performance`
          WHERE game_date >= @season_start
            AND game_date < @end_date
        )
        SELECT
          subset_id,
          -- Season
          SUM(wins) as season_wins,
          SUM(graded_picks - wins) as season_losses,
          ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) as season_pct,
          -- Month
          SUM(CASE WHEN game_date >= @month_start THEN wins ELSE 0 END) as month_wins,
          SUM(CASE WHEN game_date >= @month_start THEN graded_picks - wins ELSE 0 END) as month_losses,
          ROUND(100.0 *
            SUM(CASE WHEN game_date >= @month_start THEN wins ELSE 0 END) /
            NULLIF(SUM(CASE WHEN game_date >= @month_start THEN graded_picks ELSE 0 END), 0),
          1) as month_pct,
          -- Week
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
            bigquery.ScalarQueryParameter('season_start', 'DATE', season_start),
            bigquery.ScalarQueryParameter('month_start', 'DATE', month_start),
            bigquery.ScalarQueryParameter('week_start', 'DATE', week_start),
            bigquery.ScalarQueryParameter('end_date', 'DATE', end_date),
        ]

        try:
            results = self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query subset records: {e}")
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

    @staticmethod
    def _empty_record() -> Dict:
        """Return an empty record structure for subsets with no grading data."""
        empty_window = {'wins': 0, 'losses': 0, 'pct': 0.0}
        return {
            'season': empty_window.copy(),
            'month': empty_window.copy(),
            'week': empty_window.copy(),
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

        total_picks = sum(
            len(p) for mg in json_data.get('model_groups', [])
            for s in mg.get('subsets', [])
            for p in [s.get('picks', [])]
        )
        total_models = len(json_data.get('model_groups', []))
        logger.info(
            f"Exported {total_models} model groups "
            f"with {total_picks} total picks for {target_date} to {gcs_path}"
        )

        return gcs_path
