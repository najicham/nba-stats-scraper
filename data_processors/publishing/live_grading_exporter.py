"""
Live Grading Exporter for Phase 6 Publishing

Multi-source live prediction grading: real-time during games, confirmed after.

Score Sources:
  1. BDL Live API — real-time stats for in-progress games (ephemeral, drops off after final)
  2. BigQuery (NBA.com) — confirmed official stats for final games (authoritative)

Resolution order per player:
  - Final games: always use BigQuery (nba_analytics.player_game_summary)
  - In-progress games: prefer BDL live API, fall back to BigQuery if BDL unavailable
  - Each prediction carries a `score_source` field for transparency

Designed to run every 2-5 minutes during games via Cloud Scheduler.
"""

import logging
import os
import requests
from typing import Dict, List, Any, Optional, Tuple
from datetime import date, datetime, timezone
from collections import defaultdict

from google.cloud import bigquery

from .base_exporter import BaseExporter
from .exporter_utils import compute_display_confidence

# Retry logic for API resilience (prevents live grading failures during games)
try:
    from shared.utils.retry_with_jitter import retry_with_jitter
except ImportError:
    logger.warning("Could not import retry_with_jitter, BDL API calls will not retry on failure")
    def retry_with_jitter(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

logger = logging.getLogger(__name__)

# BallDontLie API configuration
BDL_API_URL = "https://api.balldontlie.io/v1/box_scores/live"
BDL_API_TIMEOUT = 30


class LiveGradingExporter(BaseExporter):
    """
    Export live prediction grading to JSON for real-time accuracy display.

    Output files:
    - live-grading/{date}.json - Current live grading (short cache TTL)
    - live-grading/latest.json - Always points to most recent

    JSON structure:
    {
        "updated_at": "2024-12-25T21:30:00Z",
        "game_date": "2024-12-25",
        "summary": {
            "total_predictions": 45,
            "graded": 30,
            "pending": 15,
            "correct": 22,
            "incorrect": 8,
            "win_rate": 0.733,
            "avg_error": 3.2,
            "games_in_progress": 2,
            "games_final": 3
        },
        "predictions": [
            {
                "player_lookup": "lebron-james",
                "player_name": "LeBron James",
                "team": "LAL",
                "opponent": "HOU",
                "game_status": "in_progress",
                "predicted": 27.5,
                "line": 24.5,
                "recommendation": "OVER",
                "actual": 20,
                "minutes": "28:30",
                "status": "pending",  // pending | correct | incorrect
                "error": -7.5,
                "margin_vs_line": -4.5,
                "confidence": 72,
                "score_source": "nba_official"  // nba_official | bdl_live | null
            }
        ]
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._player_lookup_cache: Dict[int, str] = {}

    def generate_json(self, target_date: str) -> Dict[str, Any]:
        """
        Generate JSON for live prediction grading using multi-source scores.

        Source strategy:
        - Final games → BigQuery (NBA.com official stats, authoritative)
        - In-progress games → BDL live API (real-time), BigQuery fallback
        - Scheduled games → no scores yet (pending)

        Each graded prediction includes `score_source` for transparency.
        """
        predictions = self._query_predictions(target_date)
        if not predictions:
            logger.info(f"No predictions found for {target_date}")
            return self._empty_response(target_date)

        # 1. Check game statuses from schedule (cheap, always available)
        game_status_counts = self._query_game_statuses(target_date)
        games_final = game_status_counts.get('final', 0)
        games_in_progress = game_status_counts.get('in_progress', 0)

        # 2. Source A: BigQuery for confirmed final game stats (authoritative)
        bq_scores = {}
        if games_final > 0 or games_in_progress > 0:
            bq_scores, game_status_counts = self._fetch_bigquery_scores(target_date)
            logger.info(f"BigQuery (NBA.com): {len(bq_scores)} players")

        # 3. Source B: BDL live API for real-time in-progress stats
        bdl_scores = {}
        live_data = []  # Raw BDL response (kept for compatibility)
        if games_in_progress > 0:
            try:
                self._build_player_lookup_cache()
                live_data = self._fetch_live_box_scores()
                bdl_scores = self._build_live_scores_map(live_data, target_date)
                logger.info(f"BDL live API: {len(bdl_scores)} players matched")
            except Exception as e:
                logger.warning(f"BDL live API failed (BigQuery will cover): {e}")

        # 4. Merge: BDL for in-progress, BigQuery for final + fallback
        merged_scores = self._merge_scores(bdl_scores, bq_scores)
        logger.info(
            f"Merged scores: {len(merged_scores)} players "
            f"(BDL: {sum(1 for s in merged_scores.values() if s.get('score_source') == 'bdl_live')}, "
            f"NBA.com: {sum(1 for s in merged_scores.values() if s.get('score_source') == 'nba_official')})"
        )

        # 5. Grade and summarize
        graded_predictions = self._grade_predictions(predictions, merged_scores)
        summary = self._compute_summary(graded_predictions, live_data)

        # Use schedule-derived game counts (more reliable than BDL)
        summary['games_final'] = game_status_counts.get('final', 0)
        summary['games_in_progress'] = game_status_counts.get('in_progress', 0)

        return {
            'updated_at': self.get_generated_at(),
            'game_date': target_date,
            'summary': summary,
            'predictions': graded_predictions
        }

    def _query_predictions(self, target_date: str) -> List[Dict]:
        """
        Query tonight's predictions from BigQuery.
        Uses the catboost_v8 system (production system).

        NOTE: Handles two game_id formats for backward compatibility:
        1. Official NBA format: '0022500441' (nbac_schedule)
        2. Date-based format: 'YYYYMMDD_AWAY_HOME' (legacy from odds_api/gamebook)
        """
        query = """
        WITH player_names AS (
            SELECT player_lookup, player_name
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        ),
        latest_predictions AS (
            SELECT
                p.player_lookup,
                p.game_id,
                p.predicted_points,
                p.confidence_score,
                p.recommendation,
                p.current_points_line as line_value,
                p.has_prop_line,
                p.line_source
            FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
            WHERE p.game_date = @target_date
              AND p.system_id = 'catboost_v9'
              AND p.is_active = TRUE
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY p.player_lookup
                ORDER BY p.prediction_version DESC, p.updated_at DESC
            ) = 1
        ),
        game_info AS (
            -- Include both NBA official game_id and date-based format
            SELECT DISTINCT
                game_id,
                -- Also create date-based lookup: YYYYMMDD_AWAY_HOME
                CONCAT(
                    REPLACE(CAST(game_date AS STRING), '-', ''),
                    '_',
                    away_team_tricode,
                    '_',
                    home_team_tricode
                ) as date_based_game_id,
                home_team_tricode as home_team,
                away_team_tricode as away_team
            FROM `nba-props-platform.nba_raw.nbac_schedule`
            WHERE game_date = @target_date
        )
        SELECT
            lp.player_lookup,
            COALESCE(pn.player_name, lp.player_lookup) as player_name,
            lp.game_id,
            COALESCE(gi.home_team, gi2.home_team) as home_team,
            COALESCE(gi.away_team, gi2.away_team) as away_team,
            ROUND(lp.predicted_points, 1) as predicted_points,
            ROUND(lp.confidence_score, 3) as confidence_score,
            lp.recommendation,
            ROUND(lp.line_value, 1) as line_value,
            lp.has_prop_line,
            lp.line_source
        FROM latest_predictions lp
        LEFT JOIN player_names pn ON lp.player_lookup = pn.player_lookup
        -- Try official NBA game_id first
        LEFT JOIN game_info gi ON lp.game_id = gi.game_id
        -- Fallback: try date-based format (YYYYMMDD_AWAY_HOME)
        LEFT JOIN game_info gi2 ON lp.game_id = gi2.date_based_game_id
        -- Include all predictions (OVER, UNDER, NO_LINE, PASS)
        -- NO_LINE predictions still have predicted points that can be graded
        ORDER BY lp.confidence_score DESC
        """

        params = [
            bigquery.ScalarQueryParameter("target_date", "DATE", target_date)
        ]

        try:
            results = self.query_to_list(query, params)
            logger.info(f"Found {len(results)} predictions for {target_date}")
            return results
        except Exception as e:
            logger.error(f"Failed to query predictions: {e}", exc_info=True)
            return []

    def _build_player_lookup_cache(self) -> None:
        """
        Build mapping of BDL player IDs to player_lookup values.

        Uses full season of historical data (not just 30 days) so the cache
        works even when BDL scrapers are disabled. BDL player IDs are stable
        across a season, so historical mappings remain valid.

        The name-based fallback in _add_player_to_map handles any players
        not found in the cache.
        """
        if self._player_lookup_cache:
            return

        query = """
        SELECT DISTINCT
            bdl_player_id,
            player_lookup
        FROM `nba_raw.bdl_player_boxscores`
        WHERE bdl_player_id IS NOT NULL
          AND game_date >= '2025-10-01'
        """

        try:
            results = self.query_to_list(query)
            for row in results:
                bdl_id = row.get('bdl_player_id')
                if bdl_id:
                    self._player_lookup_cache[bdl_id] = row.get('player_lookup')
            logger.info(f"Built player lookup cache with {len(self._player_lookup_cache)} players")
        except Exception as e:
            logger.warning(f"BDL lookup cache unavailable (name fallback will be used): {e}")

    def _fetch_live_box_scores(self) -> List[Dict]:
        """Fetch live box scores from BallDontLie API with retry logic."""
        api_key = os.getenv("BDL_API_KEY")

        headers = {
            "User-Agent": "nba-live-grading/1.0",
            "Accept": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            # Use retry-wrapped fetch for resilience
            data = self._fetch_bdl_with_retry(headers)
            live_boxes = data.get("data", [])

            logger.info(f"Fetched {len(live_boxes)} games from BDL API")
            return live_boxes

        except requests.RequestException as e:
            logger.error(f"Failed to fetch live box scores after retries: {e}", exc_info=True)
            return []

    def _fetch_bdl_with_retry(self, headers: Dict[str, str]) -> Dict[str, Any]:
        """
        Fetch BDL live API with automatic retry on transient failures.

        Retry strategy:
        - 3 attempts with short backoff (CF has 120s timeout)
        - Handles: Network errors, timeouts, server errors (5xx)

        Args:
            headers: HTTP headers including API key

        Returns:
            JSON response from API

        Raises:
            requests.RequestException: After all retries exhausted
        """
        @retry_with_jitter(
            max_attempts=3,
            base_delay=2.0,
            max_delay=15.0,
            exceptions=(requests.exceptions.RequestException,)
        )
        def _do_fetch():
            response = requests.get(
                BDL_API_URL,
                headers=headers,
                timeout=BDL_API_TIMEOUT
            )
            response.raise_for_status()
            return response.json()

        return _do_fetch()

    def _build_live_scores_map(self, live_data: List[Dict], target_date: str) -> Dict[str, Dict]:
        """
        Build a map of player_lookup -> live stats from BDL data.

        Args:
            live_data: Raw BDL API response data
            target_date: Target date for filtering (YYYY-MM-DD)

        Returns dict with structure:
        {
            'lebron-james': {
                'points': 20,
                'minutes': '28:30',
                'team': 'LAL',
                'game_status': 'in_progress'
            }
        }
        """
        live_scores = {}
        skipped_games = 0

        for box in live_data:
            # Filter by date - BDL /live API returns games from any date
            game_date = str(box.get("date", ""))[:10]
            if game_date and game_date != target_date:
                skipped_games += 1
                continue
            # Determine game status
            status_text = str(box.get("status", "")).lower()
            period = box.get("period", 0) or 0

            if "final" in status_text:
                game_status = "final"
            elif period > 0:
                game_status = "in_progress"
            else:
                game_status = "scheduled"

            # Get time remaining for display
            time_remaining = box.get("time", "")

            # Process home team players
            home_team = box.get("home_team", {})
            home_abbr = home_team.get("abbreviation", "")
            for player_stat in home_team.get("players", []):
                self._add_player_to_map(
                    live_scores, player_stat, home_abbr, game_status, period, time_remaining
                )

            # Process away team players
            away_team = box.get("visitor_team", {})
            away_abbr = away_team.get("abbreviation", "")
            for player_stat in away_team.get("players", []):
                self._add_player_to_map(
                    live_scores, player_stat, away_abbr, game_status, period, time_remaining
                )

        if skipped_games > 0:
            logger.info(f"Filtered out {skipped_games} games from other dates (target: {target_date})")

        return live_scores

    def _query_game_statuses(self, target_date: str) -> Dict[str, int]:
        """Query game statuses from schedule to determine if games have started."""
        query = """
        SELECT
            COUNTIF(game_status = 1) as scheduled,
            COUNTIF(game_status = 2) as in_progress,
            COUNTIF(game_status = 3) as final
        FROM `nba-props-platform.nba_raw.nbac_schedule`
        WHERE game_date = @target_date
        """
        params = [
            bigquery.ScalarQueryParameter("target_date", "DATE", target_date)
        ]
        try:
            results = self.query_to_list(query, params)
            if results:
                row = results[0]
                return {
                    'scheduled': row.get('scheduled', 0) or 0,
                    'in_progress': row.get('in_progress', 0) or 0,
                    'final': row.get('final', 0) or 0,
                }
        except Exception as e:
            logger.error(f"Failed to query game statuses: {e}", exc_info=True)
        return {}

    def _merge_scores(
        self,
        bdl_scores: Dict[str, Dict],
        bq_scores: Dict[str, Dict]
    ) -> Dict[str, Dict]:
        """
        Merge scores from multiple sources with clear precedence.

        Rules:
        - Final games: always use BigQuery (NBA.com official, authoritative)
        - In-progress games: prefer BDL (real-time), fall back to BigQuery
        - Each entry tagged with score_source for transparency

        This design makes it easy to add more sources later — just add
        another source dict and update the merge logic.
        """
        merged = {}

        # Start with all BigQuery scores (covers final + in-progress)
        for player, data in bq_scores.items():
            merged[player] = {**data, 'score_source': 'nba_official'}

        # Overlay BDL for in-progress games only (real-time is more current)
        for player, data in bdl_scores.items():
            if data.get('game_status') == 'in_progress':
                merged[player] = {**data, 'score_source': 'bdl_live'}
            elif player not in merged:
                # BDL has data that BigQuery doesn't — use it
                merged[player] = {**data, 'score_source': 'bdl_live'}

        return merged

    def _fetch_bigquery_scores(self, target_date: str) -> Tuple[Dict[str, Dict], Dict[str, int]]:
        """
        Fallback: fetch actual player scores from BigQuery when BDL API is unavailable.

        Uses nba_analytics.player_game_summary for actual stats and
        nba_raw.nbac_schedule for game status.

        Returns:
            Tuple of (live_scores_map, game_status_counts)
        """
        query = """
        WITH game_statuses AS (
            SELECT
                CONCAT(
                    FORMAT_DATE('%Y%m%d', game_date), '_',
                    away_team_tricode, '_',
                    home_team_tricode
                ) as game_id,
                game_status,
                home_team_tricode,
                away_team_tricode
            FROM `nba-props-platform.nba_raw.nbac_schedule`
            WHERE game_date = @target_date
        ),
        player_stats AS (
            SELECT
                pgs.player_lookup,
                pgs.points,
                pgs.minutes_played,
                pgs.team_abbr,
                pgs.game_id
            FROM `nba-props-platform.nba_analytics.player_game_summary` pgs
            WHERE pgs.game_date = @target_date
              AND pgs.is_dnp = FALSE
        )
        SELECT
            ps.player_lookup,
            ps.points,
            ps.minutes_played,
            ps.team_abbr,
            ps.game_id,
            gs.game_status as game_status_code
        FROM player_stats ps
        LEFT JOIN game_statuses gs ON ps.game_id = gs.game_id
        """

        params = [
            bigquery.ScalarQueryParameter("target_date", "DATE", target_date)
        ]

        live_scores = {}
        game_status_counts = {'final': 0, 'in_progress': 0, 'scheduled': 0}

        try:
            results = self.query_to_list(query, params)

            # Count unique game statuses
            seen_games = set()
            for row in results:
                game_id = row.get('game_id')
                status_code = row.get('game_status_code')

                # Map numeric status to string
                if status_code == 3:
                    game_status = 'final'
                elif status_code == 2:
                    game_status = 'in_progress'
                else:
                    game_status = 'scheduled'

                # Count unique games
                if game_id and game_id not in seen_games:
                    seen_games.add(game_id)
                    game_status_counts[game_status] = game_status_counts.get(game_status, 0) + 1

                player_lookup = row.get('player_lookup')
                if player_lookup:
                    minutes_raw = row.get('minutes_played')
                    if isinstance(minutes_raw, (int, float)):
                        minutes_str = f"{int(minutes_raw)}:00"
                    else:
                        minutes_str = str(minutes_raw) if minutes_raw else "0:00"

                    live_scores[player_lookup] = {
                        'points': row.get('points') or 0,
                        'minutes': minutes_str,
                        'team': row.get('team_abbr'),
                        'game_status': game_status,
                        'score_source': 'nba_official',
                    }

            logger.info(f"BigQuery scores: {len(live_scores)} players, {len(seen_games)} games")

        except Exception as e:
            logger.error(f"Failed to fetch BigQuery scores: {e}", exc_info=True)

        return live_scores, game_status_counts

    def _add_player_to_map(
        self,
        live_scores: Dict,
        player_stat: Dict,
        team_abbr: str,
        game_status: str,
        period: int = 0,
        time_remaining: str = ""
    ) -> None:
        """Add a player's live stats to the map."""
        player_info = player_stat.get("player", {})
        bdl_player_id = player_info.get("id")

        if not bdl_player_id:
            return

        # Look up player_lookup from cache
        player_lookup = self._player_lookup_cache.get(bdl_player_id)

        # Fallback: generate from name
        if not player_lookup:
            first_name = player_info.get("first_name", "")
            last_name = player_info.get("last_name", "")
            if first_name and last_name:
                full_name = f"{first_name}{last_name}".lower()
                player_lookup = ''.join(c for c in full_name if c.isalnum())

        if player_lookup:
            live_scores[player_lookup] = {
                'points': player_stat.get('pts') or 0,
                'minutes': player_stat.get('min') or "0:00",
                'team': team_abbr,
                'period': period,
                'time_remaining': time_remaining,
                'game_status': game_status,
                'score_source': 'bdl_live',
            }

    def _grade_predictions(
        self,
        predictions: List[Dict],
        live_scores: Dict[str, Dict]
    ) -> List[Dict]:
        """
        Grade each prediction against live scores.

        Returns list of graded predictions sorted by confidence.
        """
        graded = []

        for pred in predictions:
            player_lookup = pred['player_lookup']
            live = live_scores.get(player_lookup)

            # Base prediction info
            graded_pred = {
                'player_lookup': player_lookup,
                'player_name': pred.get('player_name', player_lookup),
                'team': live.get('team') if live else None,
                'home_team': pred.get('home_team'),
                'away_team': pred.get('away_team'),
                'game_status': live.get('game_status', 'scheduled') if live else 'scheduled',
                'period': live.get('period') if live else None,
                'time_remaining': live.get('time_remaining') if live else None,
                'predicted': pred.get('predicted_points'),
                'line': pred.get('line_value'),
                'recommendation': pred.get('recommendation'),
                'confidence': compute_display_confidence(
                    pred.get('predicted_points'),
                    pred.get('line_value'),
                    pred.get('confidence_score'),
                    pred.get('recommendation')
                ),
                'has_line': pred.get('has_prop_line', False),
                'line_source': pred.get('line_source'),
                'score_source': live.get('score_source') if live else None,
            }

            if live and live.get('game_status') != 'scheduled':
                # Player has live data - grade the prediction
                actual = live.get('points', 0)
                predicted = pred.get('predicted_points', 0) or 0
                line = pred.get('line_value')
                recommendation = pred.get('recommendation')

                graded_pred['actual'] = actual
                graded_pred['minutes'] = live.get('minutes')
                graded_pred['error'] = round(predicted - actual, 1) if predicted else None

                # Compute margin_vs_line whenever we have actual and line
                if line is not None:
                    margin_vs_line = actual - line
                    graded_pred['margin_vs_line'] = round(margin_vs_line, 1)
                else:
                    graded_pred['margin_vs_line'] = None

                # Determine effective direction for grading
                # OVER/UNDER use explicit recommendation; PASS/NO_LINE infer from predicted vs line
                if recommendation in ('OVER', 'UNDER'):
                    effective_direction = recommendation
                elif line is not None and predicted:
                    effective_direction = 'OVER' if predicted > line else 'UNDER'
                else:
                    effective_direction = None

                if line is not None and effective_direction:
                    # Grade using effective direction
                    if live.get('game_status') == 'final':
                        if effective_direction == 'OVER':
                            is_correct = actual > line
                        else:  # UNDER
                            is_correct = actual < line
                        graded_pred['status'] = 'correct' if is_correct else 'incorrect'
                    else:
                        # In progress - show trending status
                        if effective_direction == 'OVER':
                            if actual > line:
                                graded_pred['status'] = 'trending_correct'
                            elif actual < line - 5:  # Significantly under
                                graded_pred['status'] = 'trending_incorrect'
                            else:
                                graded_pred['status'] = 'in_progress'
                        else:  # UNDER
                            if actual < line:
                                graded_pred['status'] = 'trending_correct'
                            elif actual > line + 5:  # Significantly over
                                graded_pred['status'] = 'trending_incorrect'
                            else:
                                graded_pred['status'] = 'in_progress'
                else:
                    # No line to grade against
                    if live.get('game_status') == 'final':
                        graded_pred['status'] = 'graded'
                    else:
                        graded_pred['status'] = 'in_progress'
            else:
                # No live data yet
                graded_pred['status'] = 'pending'
                graded_pred['actual'] = None
                graded_pred['minutes'] = None
                graded_pred['error'] = None
                graded_pred['margin_vs_line'] = None

            graded.append(graded_pred)

        # Sort by confidence descending, then by status (graded first)
        status_order = {
            'correct': 0, 'incorrect': 1, 'trending_correct': 2,
            'trending_incorrect': 3, 'in_progress': 4, 'graded': 5, 'pending': 6
        }
        graded.sort(
            key=lambda x: (
                status_order.get(x.get('status'), 9),
                -(x.get('confidence') or 0)
            )
        )

        return graded

    def _compute_summary(
        self,
        graded_predictions: List[Dict],
        live_data: List[Dict]
    ) -> Dict[str, Any]:
        """Compute summary statistics for the grading results."""
        total = len(graded_predictions)
        graded = sum(1 for p in graded_predictions if p.get('actual') is not None)
        pending = total - graded

        # Count correct/incorrect from final games only
        correct = sum(1 for p in graded_predictions if p.get('status') == 'correct')
        incorrect = sum(1 for p in graded_predictions if p.get('status') == 'incorrect')

        # Trending counts (in-progress games)
        trending_correct = sum(1 for p in graded_predictions if p.get('status') == 'trending_correct')
        trending_incorrect = sum(1 for p in graded_predictions if p.get('status') == 'trending_incorrect')

        # Win rate (final games only)
        final_graded = correct + incorrect
        win_rate = round(correct / final_graded, 3) if final_graded > 0 else None

        # Average error (all graded)
        errors = [abs(p.get('error', 0)) for p in graded_predictions if p.get('error') is not None]
        avg_error = round(sum(errors) / len(errors), 1) if errors else None

        # Game counts
        games_final = sum(1 for box in live_data if "final" in str(box.get("status", "")).lower())
        games_in_progress = sum(
            1 for box in live_data
            if (box.get("period", 0) or 0) > 0 and "final" not in str(box.get("status", "")).lower()
        )

        return {
            'total_predictions': total,
            'graded': graded,
            'pending': pending,
            'correct': correct,
            'incorrect': incorrect,
            'trending_correct': trending_correct,
            'trending_incorrect': trending_incorrect,
            'win_rate': win_rate,
            'avg_error': avg_error,
            'games_in_progress': games_in_progress,
            'games_final': games_final
        }

    def _empty_response(self, target_date: str) -> Dict[str, Any]:
        """Return empty response when no predictions exist."""
        return {
            'updated_at': self.get_generated_at(),
            'game_date': target_date,
            'summary': {
                'total_predictions': 0,
                'graded': 0,
                'pending': 0,
                'correct': 0,
                'incorrect': 0,
                'trending_correct': 0,
                'trending_incorrect': 0,
                'win_rate': None,
                'avg_error': None,
                'games_in_progress': 0,
                'games_final': 0
            },
            'predictions': []
        }

    def export(self, target_date: str, update_latest: bool = True) -> str:
        """
        Generate and upload live grading JSON.

        Args:
            target_date: Date string in YYYY-MM-DD format
            update_latest: Whether to also update latest.json

        Returns:
            GCS path of the exported file
        """
        logger.info(f"Exporting live grading for {target_date}")

        json_data = self.generate_json(target_date)

        # Upload date-specific file with short cache (30 seconds)
        path = f'live-grading/{target_date}.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=30')

        # Update latest.json
        if update_latest:
            self.upload_to_gcs(json_data, 'live-grading/latest.json', 'public, max-age=30')
            logger.info("Updated live-grading/latest.json")

        summary = json_data.get('summary', {})
        logger.info(
            f"Exported live grading: {summary.get('total_predictions')} predictions, "
            f"{summary.get('correct')}/{summary.get('graded')} correct"
        )

        return gcs_path
