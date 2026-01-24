"""
Live Grading Exporter for Phase 6 Publishing

Exports live prediction grading results during games.
Combines tonight's predictions with live scores to show real-time accuracy.

This exporter:
1. Queries tonight's predictions from BigQuery
2. Fetches live player scores from BDL API
3. Computes live grading metrics (correct/incorrect, error, etc.)
4. Exports to GCS as /live-grading/{date}.json

Designed to run alongside LiveScoresExporter every 2-5 minutes during games.
"""

import logging
import os
import requests
from typing import Dict, List, Any, Optional, Tuple
from datetime import date, datetime, timezone
from collections import defaultdict

from google.cloud import bigquery

from .base_exporter import BaseExporter

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
                "confidence": 0.72
            }
        ]
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._player_lookup_cache: Dict[int, str] = {}

    def generate_json(self, target_date: str) -> Dict[str, Any]:
        """
        Generate JSON for live prediction grading.

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            Dictionary ready for JSON serialization
        """
        # Fetch tonight's predictions from BigQuery
        predictions = self._query_predictions(target_date)

        if not predictions:
            logger.info(f"No predictions found for {target_date}")
            return self._empty_response(target_date)

        # Build player lookup mapping for BDL
        self._build_player_lookup_cache()

        # Fetch live scores from BDL API
        live_data = self._fetch_live_box_scores()

        # Build live scores lookup by player_lookup (filtered by target date)
        live_scores = self._build_live_scores_map(live_data, target_date)

        # Grade predictions against live scores
        graded_predictions = self._grade_predictions(predictions, live_scores)

        # Compute summary statistics
        summary = self._compute_summary(graded_predictions, live_data)

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
              AND p.system_id = 'catboost_v8'
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
            logger.error(f"Failed to query predictions: {e}")
            return []

    def _build_player_lookup_cache(self) -> None:
        """Build mapping of BDL player IDs to player_lookup values."""
        if self._player_lookup_cache:
            return

        query = """
        SELECT DISTINCT
            bdl_player_id,
            player_lookup
        FROM `nba_raw.bdl_player_boxscores`
        WHERE bdl_player_id IS NOT NULL
          AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
        """

        try:
            results = self.query_to_list(query)
            for row in results:
                bdl_id = row.get('bdl_player_id')
                if bdl_id:
                    self._player_lookup_cache[bdl_id] = row.get('player_lookup')
            logger.info(f"Built player lookup cache with {len(self._player_lookup_cache)} players")
        except Exception as e:
            logger.error(f"Failed to build player lookup cache: {e}")

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
            logger.error(f"Failed to fetch live box scores after retries: {e}")
            return []

    @retry_with_jitter(
        max_attempts=5,
        base_delay=60,  # Start with 60s delay (BDL API rate limits)
        max_delay=1800,  # Max 30 minutes delay
        exceptions=(requests.RequestException, requests.Timeout, ConnectionError)
    )
    def _fetch_bdl_with_retry(self, headers: Dict[str, str]) -> Dict[str, Any]:
        """
        Fetch BDL live API with automatic retry on transient failures.

        Retry strategy:
        - 5 attempts with exponential backoff + jitter
        - Handles: Network errors, timeouts, API rate limits (429), server errors (5xx)
        - Total retry window: ~30 minutes worst case

        This prevents live grading failures during games (runs every 2-5 minutes).
        Same retry logic as BDL box score scraper which prevented 40% of weekly failures.

        Args:
            headers: HTTP headers including API key

        Returns:
            JSON response from API

        Raises:
            requests.RequestException: After all retries exhausted
        """
        @retry_with_jitter(
            max_attempts=5,
            base_delay=2.0,
            max_delay=60.0,
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
                'game_status': game_status
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
                'confidence': pred.get('confidence_score'),
                'has_line': pred.get('has_prop_line', False),
                'line_source': pred.get('line_source'),
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

                if line is not None and recommendation in ('OVER', 'UNDER'):
                    margin_vs_line = actual - line
                    graded_pred['margin_vs_line'] = round(margin_vs_line, 1)

                    # Determine if prediction is correct
                    # For in-progress games, show "pending" unless clear
                    if live.get('game_status') == 'final':
                        if recommendation == 'OVER':
                            is_correct = actual > line
                        else:  # UNDER
                            is_correct = actual < line
                        graded_pred['status'] = 'correct' if is_correct else 'incorrect'
                    else:
                        # In progress - show trending status
                        if recommendation == 'OVER':
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
                    # NO_LINE or PASS - still show grading based on prediction accuracy
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
