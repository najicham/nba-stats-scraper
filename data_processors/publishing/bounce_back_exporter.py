"""
Bounce-Back Watch Exporter for Trends v2

Identifies players who had a bad game (10+ points below season average)
and shows their historical bounce-back rate.

Output: /v1/trends/bounce-back.json
Refresh: Daily (6 AM ET)

Frontend fields (BounceBackCandidate):
- player_lookup, player_full_name, team_abbr
- last_game: {result, opponent, margin}
- season_average, shortfall
- bounce_back_rate, bounce_back_sample
- significance ("high"/"medium"/"low")
- playing_tonight, tonight: {opponent, game_time, home}
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date, datetime

from google.cloud import bigquery

from .base_exporter import BaseExporter
from shared.utils.schedule import NBAScheduleService

logger = logging.getLogger(__name__)


class BounceBackExporter(BaseExporter):
    """
    Export bounce-back candidates - players due for a rebound performance.

    JSON structure:
    {
        "generated_at": "...",
        "as_of_date": "2024-12-15",
        "bounce_back_candidates": [
            {
                "rank": 1,
                "player_lookup": "stephencurry",
                "player_full_name": "Stephen Curry",
                "team_abbr": "GSW",
                "last_game": {
                    "date": "2024-12-14",
                    "result": 12,
                    "opponent": "LAL",
                    "margin": -14.5
                },
                "season_average": 26.5,
                "shortfall": 14.5,
                "bounce_back_rate": 0.786,
                "bounce_back_sample": 14,
                "significance": "high",
                "playing_tonight": true,
                "tonight": {
                    "opponent": "PHX",
                    "game_time": "7:30 PM ET",
                    "home": true
                }
            }
        ],
        "league_baseline": {
            "avg_bounce_back_rate": 0.62,
            "sample_size": 1234
        }
    }
    """

    # Configuration
    DEFAULT_SHORTFALL_THRESHOLD = 10  # Points below average to qualify
    MIN_BOUNCE_BACK_SAMPLE = 3  # Minimum historical bad games needed

    def generate_json(
        self,
        as_of_date: str = None,
        shortfall_threshold: int = None
    ) -> Dict[str, Any]:
        """
        Generate bounce-back candidates JSON.

        Args:
            as_of_date: Date string (YYYY-MM-DD), defaults to today
            shortfall_threshold: Points below avg to qualify (default 10)

        Returns:
            Dictionary ready for JSON serialization
        """
        if as_of_date is None:
            as_of_date = date.today().strftime('%Y-%m-%d')
        if shortfall_threshold is None:
            shortfall_threshold = self.DEFAULT_SHORTFALL_THRESHOLD

        logger.info(f"Generating bounce-back candidates as of {as_of_date}")

        # Get candidates with bounce-back rates
        candidates = self._query_bounce_back_candidates(as_of_date, shortfall_threshold)

        # Get league baseline
        league_baseline = self._query_league_baseline(as_of_date, shortfall_threshold)

        # Get tonight's games for playing_tonight enrichment
        tonight_games = self._query_tonight_games(as_of_date)

        # Add rankings and tonight's game info
        for rank, candidate in enumerate(candidates, 1):
            candidate['rank'] = rank
            self._enrich_with_tonight(candidate, tonight_games)

        return {
            'generated_at': self.get_generated_at(),
            'as_of_date': as_of_date,
            'shortfall_threshold': shortfall_threshold,
            'total_candidates': len(candidates),
            'bounce_back_candidates': candidates,
            'league_baseline': league_baseline
        }

    def _query_bounce_back_candidates(self, as_of_date: str, shortfall_threshold: int) -> List[Dict]:
        """Query players who had a bad game and their bounce-back rates."""
        query = """
        WITH season_averages AS (
            -- Calculate season average for each player
            SELECT
                player_lookup,
                AVG(points) as season_avg,
                COUNT(*) as season_games
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE season_year = CASE
                WHEN EXTRACT(MONTH FROM @as_of_date) >= 10 THEN EXTRACT(YEAR FROM @as_of_date)
                ELSE EXTRACT(YEAR FROM @as_of_date) - 1
              END
              AND game_date <= @as_of_date
            GROUP BY player_lookup
            HAVING COUNT(*) >= 10
        ),
        last_game AS (
            -- Get most recent game for each player
            SELECT
                g.player_lookup,
                g.game_date,
                g.points,
                g.opponent_team_abbr,
                g.team_abbr,
                ROW_NUMBER() OVER (PARTITION BY g.player_lookup ORDER BY g.game_date DESC) as rn
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            WHERE g.game_date <= @as_of_date
              AND g.season_year = CASE
                WHEN EXTRACT(MONTH FROM @as_of_date) >= 10 THEN EXTRACT(YEAR FROM @as_of_date)
                ELSE EXTRACT(YEAR FROM @as_of_date) - 1
              END
        ),
        bad_game_players AS (
            -- Players whose last game was significantly below average
            SELECT
                lg.player_lookup,
                lg.game_date as last_game_date,
                lg.points as last_game_points,
                lg.opponent_team_abbr as last_game_opponent,
                lg.team_abbr,
                sa.season_avg,
                ROUND(sa.season_avg - lg.points, 1) as shortfall
            FROM last_game lg
            JOIN season_averages sa ON lg.player_lookup = sa.player_lookup
            WHERE lg.rn = 1
              AND sa.season_avg - lg.points >= @shortfall_threshold
        ),
        games_with_context AS (
            -- All games with lag to get previous game points
            SELECT
                g.player_lookup,
                g.game_date,
                g.points,
                LAG(g.points) OVER (PARTITION BY g.player_lookup ORDER BY g.game_date) as prev_points,
                sa.season_avg
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            JOIN season_averages sa ON g.player_lookup = sa.player_lookup
            WHERE g.season_year >= 2021
        ),
        bounce_back_history AS (
            -- Calculate historical bounce-back rate for bad games
            SELECT
                gc.player_lookup,
                COUNT(*) as bad_game_count,
                SUM(CASE WHEN gc.points >= gc.season_avg THEN 1 ELSE 0 END) as bounced_back,
                ROUND(SUM(CASE WHEN gc.points >= gc.season_avg THEN 1 ELSE 0 END) / COUNT(*), 3) as bounce_back_rate
            FROM games_with_context gc
            WHERE gc.prev_points IS NOT NULL
              AND gc.season_avg - gc.prev_points >= @shortfall_threshold
            GROUP BY gc.player_lookup
            HAVING COUNT(*) >= @min_sample
        ),
        player_names AS (
            SELECT player_lookup, player_name
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        )
        SELECT
            bg.player_lookup,
            COALESCE(pn.player_name, bg.player_lookup) as player_name,
            bg.team_abbr as team,
            bg.last_game_date,
            bg.last_game_points,
            bg.last_game_opponent,
            ROUND(bg.season_avg, 1) as season_average,
            bg.shortfall,
            COALESCE(bb.bounce_back_rate, 0.5) as bounce_back_rate,
            COALESCE(bb.bad_game_count, 0) as bounce_back_sample,
            CASE
                WHEN bb.bad_game_count >= 10 AND bb.bounce_back_rate >= 0.7 THEN 'high'
                WHEN bb.bad_game_count >= 5 AND bb.bounce_back_rate >= 0.6 THEN 'medium'
                ELSE 'low'
            END as significance
        FROM bad_game_players bg
        LEFT JOIN bounce_back_history bb ON bg.player_lookup = bb.player_lookup
        LEFT JOIN player_names pn ON bg.player_lookup = pn.player_lookup
        ORDER BY bb.bounce_back_rate DESC, bg.shortfall DESC
        """

        params = [
            bigquery.ScalarQueryParameter('as_of_date', 'DATE', as_of_date),
            bigquery.ScalarQueryParameter('shortfall_threshold', 'INT64', shortfall_threshold),
            bigquery.ScalarQueryParameter('min_sample', 'INT64', self.MIN_BOUNCE_BACK_SAMPLE)
        ]

        results = self.query_to_list(query, params)

        return [
            {
                'player_lookup': r['player_lookup'],
                'player_full_name': r['player_name'],
                'team_abbr': r['team'],
                'last_game': {
                    'date': str(r['last_game_date']),
                    'result': r['last_game_points'],
                    'opponent': r['last_game_opponent'],
                    'margin': -self._safe_float(r['shortfall']),  # Negative since below average
                },
                'season_average': self._safe_float(r['season_average']),
                'shortfall': self._safe_float(r['shortfall']),
                'bounce_back_rate': self._safe_float(r['bounce_back_rate']),
                'bounce_back_sample': r['bounce_back_sample'],
                'significance': r['significance']
            }
            for r in results
        ]

    def _query_league_baseline(self, as_of_date: str, shortfall_threshold: int) -> Dict[str, Any]:
        """Query league-wide bounce-back rate baseline."""
        query = """
        WITH season_averages AS (
            SELECT
                player_lookup,
                AVG(points) as season_avg
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE season_year >= 2021
            GROUP BY player_lookup
            HAVING COUNT(*) >= 10
        ),
        games_with_context AS (
            SELECT
                g.player_lookup,
                g.game_date,
                g.points,
                LAG(g.points) OVER (PARTITION BY g.player_lookup ORDER BY g.game_date) as prev_points,
                sa.season_avg
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            JOIN season_averages sa ON g.player_lookup = sa.player_lookup
            WHERE g.season_year >= 2021
        )
        SELECT
            COUNT(*) as total_bad_games,
            SUM(CASE WHEN points >= season_avg THEN 1 ELSE 0 END) as bounced_back,
            ROUND(SUM(CASE WHEN points >= season_avg THEN 1 ELSE 0 END) / COUNT(*), 3) as avg_bounce_back_rate
        FROM games_with_context
        WHERE prev_points IS NOT NULL
          AND season_avg - prev_points >= @shortfall_threshold
        """

        params = [
            bigquery.ScalarQueryParameter('shortfall_threshold', 'INT64', shortfall_threshold)
        ]

        results = self.query_to_list(query, params)

        if results:
            return {
                'avg_bounce_back_rate': self._safe_float(results[0]['avg_bounce_back_rate']),
                'sample_size': results[0]['total_bad_games']
            }
        return {
            'avg_bounce_back_rate': None,
            'sample_size': 0
        }

    def _safe_float(self, value) -> Optional[float]:
        """Convert to float, handling None and special values."""
        if value is None:
            return None
        try:
            f = float(value)
            if f != f:  # NaN check
                return None
            return round(f, 3)
        except (TypeError, ValueError):
            return None

    def _query_tonight_games(self, as_of_date: str) -> Dict[str, Dict]:
        """Query games scheduled for today/tonight.

        Returns:
            Dict mapping team codes to game info:
            {
                'LAL': {'opponent': 'GSW', 'game_time': '7:30 PM ET', 'home': True},
                'GSW': {'opponent': 'LAL', 'game_time': '7:30 PM ET', 'home': False},
                ...
            }
        """
        try:
            schedule = NBAScheduleService()
            games = schedule.get_games_for_date(as_of_date)

            tonight_map = {}
            for game in games:
                # Parse game time from ISO format to readable format
                game_time = self._format_game_time(game.commence_time)

                # Add both teams to the map with home/away distinction
                tonight_map[game.home_team] = {
                    'opponent': game.away_team,
                    'game_time': game_time,
                    'home': True
                }
                tonight_map[game.away_team] = {
                    'opponent': game.home_team,
                    'game_time': game_time,
                    'home': False
                }

            logger.info(f"Found {len(games)} games tonight with {len(tonight_map)} teams playing")
            return tonight_map

        except Exception as e:
            logger.warning(f"Could not fetch tonight's games: {e}")
            return {}

    def _format_game_time(self, commence_time: str) -> Optional[str]:
        """Format ISO commence_time to readable game time."""
        if not commence_time:
            return None
        try:
            # Parse ISO format (e.g., "2024-12-15T19:30:00-05:00")
            dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
            # Format as "7:30 PM ET"
            return dt.strftime('%-I:%M %p ET')
        except (ValueError, AttributeError):
            return None

    def _enrich_with_tonight(self, candidate: Dict, tonight_games: Dict) -> None:
        """Add tonight's game info to candidate (mutates in place)."""
        team = candidate.get('team_abbr')
        if team and team in tonight_games:
            game = tonight_games[team]
            candidate['playing_tonight'] = True
            candidate['tonight'] = {
                'opponent': game.get('opponent'),
                'game_time': game.get('game_time'),
                'home': game.get('home', False),
            }
        else:
            candidate['playing_tonight'] = False
            candidate['tonight'] = None

    def export(self, as_of_date: str = None, **kwargs) -> str:
        """
        Generate and upload bounce-back candidates JSON.

        Args:
            as_of_date: Date string (YYYY-MM-DD), defaults to today
            **kwargs: Additional arguments passed to generate_json

        Returns:
            GCS path of the exported file
        """
        if as_of_date is None:
            as_of_date = date.today().strftime('%Y-%m-%d')

        logger.info(f"Exporting bounce-back candidates as of {as_of_date}")

        json_data = self.generate_json(as_of_date, **kwargs)

        path = 'trends/bounce-back.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=3600')  # 1 hour cache

        logger.info(f"Exported bounce-back candidates to {gcs_path}")
        return gcs_path
