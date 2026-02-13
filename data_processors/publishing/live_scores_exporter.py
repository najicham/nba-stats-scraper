"""
Live Scores Exporter for Phase 6 Publishing

Exports live game scores and player stats during games for real-time
challenge grading on the frontend.

This exporter:
1. Calls BallDontLie API for live box scores
2. Maps BDL player IDs to player_lookup values
3. Exports to GCS as /live/{date}.json

Designed to run every 2-5 minutes during game windows (7 PM - 1 AM ET).
"""

import logging
import os
import requests
from typing import Dict, List, Any, Optional
from datetime import date, datetime, timezone
from collections import defaultdict

from google.cloud import bigquery

from .base_exporter import BaseExporter

# Retry logic for API resilience (prevents live export failures during games)
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
BDL_API_TIMEOUT = 30  # seconds


class LiveScoresExporter(BaseExporter):
    """
    Export live game scores to JSON for real-time challenge grading.

    Output files:
    - live/{date}.json - Current live scores (short cache TTL)
    - live/latest.json - Always points to most recent live data

    JSON structure:
    {
        "updated_at": "2024-12-25T21:30:00Z",
        "game_date": "2024-12-25",
        "poll_id": "20241225T213000Z",
        "games_in_progress": 3,
        "games_final": 2,
        "games": [
            {
                "game_id": "0022400123",
                "status": "in_progress",  // scheduled | in_progress | final
                "period": 3,
                "time_remaining": "5:42",
                "home_team": "LAL",
                "away_team": "GSW",
                "home_score": 78,
                "away_score": 82,
                "players": [
                    {
                        "player_lookup": "lebron-james-lal",
                        "name": "LeBron James",
                        "team": "LAL",
                        "points": 18,
                        "rebounds": 7,
                        "assists": 5,
                        "minutes": "28:30"
                    }
                ]
            }
        ]
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._player_lookup_cache: Dict[int, str] = {}
        self._player_name_cache: Dict[int, str] = {}

    def generate_json(self, target_date: str) -> Dict[str, Any]:
        """
        Generate JSON for live game scores.

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            Dictionary ready for JSON serialization
        """
        poll_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        # Fetch live data from BDL API
        live_data = self._fetch_live_box_scores()

        if not live_data:
            logger.info(f"No live games in progress for {target_date}")
            return self._empty_response(target_date, poll_id)

        # Build player lookup mapping from BigQuery
        self._build_player_lookup_cache()

        # Transform to frontend format
        games_data = self._transform_games(live_data, target_date)

        # Count stats
        games_in_progress = sum(1 for g in games_data if g['status'] == 'in_progress')
        games_final = sum(1 for g in games_data if g['status'] == 'final')

        return {
            'updated_at': self.get_generated_at(),
            'game_date': target_date,
            'poll_id': poll_id,
            'games_in_progress': games_in_progress,
            'games_final': games_final,
            'total_games': len(games_data),
            'games': games_data
        }

    def _fetch_live_box_scores(self) -> List[Dict]:
        """
        Fetch live box scores from BallDontLie API.

        Returns:
            List of live game box score dictionaries
        """
        api_key = os.getenv("BDL_API_KEY")

        headers = {
            "User-Agent": "nba-live-exporter/1.0",
            "Accept": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            # Use retry-wrapped fetch for resilience
            data = self._fetch_bdl_page_with_retry(headers, None)
            live_boxes = data.get("data", [])

            # Handle pagination if needed (unlikely for live games)
            cursor = data.get("meta", {}).get("next_cursor")
            while cursor:
                # Use retry-wrapped fetch for pagination too
                page_data = self._fetch_bdl_page_with_retry(headers, cursor)
                live_boxes.extend(page_data.get("data", []))
                cursor = page_data.get("meta", {}).get("next_cursor")

            logger.info(f"Fetched {len(live_boxes)} live games from BDL API")
            return live_boxes

        except requests.RequestException as e:
            logger.error(f"Failed to fetch live box scores after retries: {e}", exc_info=True)
            return []

    @retry_with_jitter(
        max_attempts=3,
        base_delay=2,  # Short delays for Cloud Function (120s timeout)
        max_delay=15,
        exceptions=(requests.RequestException, requests.Timeout, ConnectionError)
    )
    def _fetch_bdl_page_with_retry(self, headers: Dict[str, str], cursor: Optional[str]) -> Dict[str, Any]:
        """
        Fetch a single page from BDL live API with automatic retry on transient failures.

        Retry strategy:
        - 3 attempts with short exponential backoff (CF has 120s timeout)
        - Handles: Network errors, timeouts, server errors (5xx)

        Args:
            headers: HTTP headers including API key
            cursor: Pagination cursor (None for first page)

        Returns:
            JSON response from API

        Raises:
            requests.RequestException: After all retries exhausted
        """
        params = {"cursor": cursor, "per_page": 100} if cursor else None
        response = requests.get(
            BDL_API_URL,
            headers=headers,
            params=params,
            timeout=BDL_API_TIMEOUT
        )
        response.raise_for_status()
        return response.json()

    def _build_player_lookup_cache(self) -> None:
        """
        Build a mapping of BDL player IDs to player_lookup values.
        Uses the most recent bdl_player_boxscores data.
        """
        if self._player_lookup_cache:
            return  # Already built

        query = """
        SELECT DISTINCT
            bdl_player_id,
            player_lookup,
            player_full_name
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
                    self._player_name_cache[bdl_id] = row.get('player_full_name')

            logger.info(f"Built player lookup cache with {len(self._player_lookup_cache)} players")
        except Exception as e:
            logger.error(f"Failed to build player lookup cache: {e}", exc_info=True)

    def _transform_games(self, live_data: List[Dict], target_date: str) -> List[Dict]:
        """
        Transform BDL live box scores to frontend format.

        Args:
            live_data: Raw BDL API response data
            target_date: Target date for filtering

        Returns:
            List of transformed game dictionaries
        """
        games = []
        skipped_games = 0

        for box in live_data:
            # Filter by date - BDL /live API returns games from any date
            # that are currently active or recently finished
            game_date = str(box.get("date", ""))[:10]  # "2025-12-28"
            if game_date and game_date != target_date:
                skipped_games += 1
                logger.debug(f"Skipping game {box.get('id')} from {game_date}, target is {target_date}")
                continue

            # BDL live API has flat structure - team info is at box level
            # Extract game metadata
            game_id = str(box.get("id", ""))

            # Determine game status
            status_text = str(box.get("status", "")).lower()
            period = box.get("period", 0) or 0

            if "final" in status_text:
                status = "final"
            elif period > 0 or "progress" in status_text or "live" in status_text:
                status = "in_progress"
            else:
                status = "scheduled"

            # Get team info - at box level, not nested in game
            home_team = box.get("home_team", {})
            away_team = box.get("visitor_team", {})

            home_abbr = home_team.get("abbreviation", "")
            away_abbr = away_team.get("abbreviation", "")

            # Get scores - also at box level
            home_score = box.get("home_team_score", 0) or 0
            away_score = box.get("visitor_team_score", 0) or 0

            # Get period and time
            time_remaining = box.get("time", "")

            # Transform player stats
            players = []

            # Home team players
            for player_stat in box.get("home_team", {}).get("players", []):
                player = self._transform_player(player_stat, home_abbr)
                if player:
                    players.append(player)

            # Away team players
            for player_stat in box.get("visitor_team", {}).get("players", []):
                player = self._transform_player(player_stat, away_abbr)
                if player:
                    players.append(player)

            # Sort players by points descending
            players.sort(key=lambda p: p.get('points', 0) or 0, reverse=True)

            games.append({
                'game_id': game_id,
                'status': status,
                'period': period,
                'time_remaining': time_remaining,
                'home_team': home_abbr,
                'away_team': away_abbr,
                'home_score': home_score,
                'away_score': away_score,
                'player_count': len(players),
                'players': players
            })

        # Sort games by status (in_progress first, then final, then scheduled)
        status_order = {'in_progress': 0, 'final': 1, 'scheduled': 2}
        games.sort(key=lambda g: status_order.get(g['status'], 3))

        if skipped_games > 0:
            logger.info(f"Filtered out {skipped_games} games from other dates (target: {target_date})")

        return games

    def _transform_player(self, player_stat: Dict, team_abbr: str) -> Optional[Dict]:
        """
        Transform a single player's stats to frontend format.

        Args:
            player_stat: BDL player stats dictionary
            team_abbr: Team abbreviation

        Returns:
            Transformed player dictionary or None if player not found
        """
        player_info = player_stat.get("player", {})
        bdl_player_id = player_info.get("id")

        if not bdl_player_id:
            return None

        # Look up player_lookup from cache
        player_lookup = self._player_lookup_cache.get(bdl_player_id)
        player_name = self._player_name_cache.get(bdl_player_id)

        # Fallback: generate player_lookup from name if not in cache
        if not player_lookup:
            first_name = player_info.get("first_name", "")
            last_name = player_info.get("last_name", "")
            if first_name and last_name:
                # Generate lookup: lowercase, no spaces, alphanumeric only
                full_name = f"{first_name}{last_name}".lower()
                player_lookup = ''.join(c for c in full_name if c.isalnum())
                player_name = f"{first_name} {last_name}"
                logger.debug(f"Generated fallback lookup for BDL ID {bdl_player_id}: {player_lookup}")
            else:
                return None

        # Extract stats
        return {
            'player_lookup': player_lookup,
            'name': player_name or f"{player_info.get('first_name', '')} {player_info.get('last_name', '')}".strip(),
            'team': team_abbr,
            'points': player_stat.get('pts') or 0,
            'rebounds': (player_stat.get('reb') or 0),
            'assists': player_stat.get('ast') or 0,
            'steals': player_stat.get('stl') or 0,
            'blocks': player_stat.get('blk') or 0,
            'turnovers': player_stat.get('turnover') or 0,
            'minutes': player_stat.get('min') or "0:00",
            'fg_made': player_stat.get('fgm') or 0,
            'fg_attempted': player_stat.get('fga') or 0,
            'fg3_made': player_stat.get('fg3m') or 0,
            'fg3_attempted': player_stat.get('fg3a') or 0,
            'ft_made': player_stat.get('ftm') or 0,
            'ft_attempted': player_stat.get('fta') or 0,
        }

    def _empty_response(self, target_date: str, poll_id: str) -> Dict[str, Any]:
        """Return empty response when no games are live."""
        return {
            'updated_at': self.get_generated_at(),
            'game_date': target_date,
            'poll_id': poll_id,
            'games_in_progress': 0,
            'games_final': 0,
            'total_games': 0,
            'games': []
        }

    def export(self, target_date: str, update_latest: bool = True) -> str:
        """
        Generate and upload live scores JSON.

        Args:
            target_date: Date string in YYYY-MM-DD format
            update_latest: Whether to also update latest.json

        Returns:
            GCS path of the exported file
        """
        logger.info(f"Exporting live scores for {target_date}")

        json_data = self.generate_json(target_date)

        # Upload date-specific file with very short cache (30 seconds)
        path = f'live/{target_date}.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=30')

        # Update latest.json with same short cache
        if update_latest:
            self.upload_to_gcs(json_data, 'live/latest.json', 'public, max-age=30')
            logger.info("Updated live/latest.json")

        games_count = json_data.get('total_games', 0)
        in_progress = json_data.get('games_in_progress', 0)
        logger.info(f"Exported live scores: {games_count} games, {in_progress} in progress")

        return gcs_path
