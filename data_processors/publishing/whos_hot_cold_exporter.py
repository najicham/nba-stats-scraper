"""
Who's Hot/Cold Exporter for Trends v2

Exports players on hot and cold streaks based on a composite "heat score"
that combines hit rate, streak length, and margin performance.

Heat Score = 50% hit_rate + 25% streak_factor + 25% margin_factor

Output: /v1/trends/whos-hot-v2.json
Refresh: Daily (6 AM ET)
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date, datetime

from google.cloud import bigquery

from .base_exporter import BaseExporter
from shared.utils.schedule import NBAScheduleService

logger = logging.getLogger(__name__)


class WhosHotColdExporter(BaseExporter):
    """
    Export hot and cold players based on heat score.

    JSON structure:
    {
        "generated_at": "...",
        "as_of_date": "2024-12-15",
        "time_period": "last_10",
        "min_games": 5,
        "hot": [
            {
                "rank": 1,
                "player_lookup": "jordanclarkson",
                "player_name": "Jordan Clarkson",
                "team": "UTA",
                "heat_score": 0.85,
                "hit_rate": 0.75,
                "current_streak": 5,
                "streak_type": "OVER",
                "avg_margin": 3.2,
                "games_played": 10,
                "playing_tonight": true,
                "tonight_opponent": "LAL",
                "tonight_game_time": "9:00 PM ET"
            }
        ],
        "cold": [...],
        "league_average": {
            "hit_rate": 0.498,
            "avg_margin": 0.12
        }
    }
    """

    # Default configuration
    DEFAULT_MIN_GAMES = 5
    DEFAULT_LOOKBACK_DAYS = 30
    DEFAULT_TOP_N = 10

    def generate_json(
        self,
        as_of_date: str = None,
        min_games: int = None,
        lookback_days: int = None,
        top_n: int = None
    ) -> Dict[str, Any]:
        """
        Generate who's hot/cold JSON.

        Args:
            as_of_date: Date string (YYYY-MM-DD), defaults to today
            min_games: Minimum games for inclusion (default 5)
            lookback_days: Days to look back (default 30)
            top_n: Number of players in hot/cold lists (default 10)

        Returns:
            Dictionary ready for JSON serialization
        """
        if as_of_date is None:
            as_of_date = date.today().strftime('%Y-%m-%d')
        if min_games is None:
            min_games = self.DEFAULT_MIN_GAMES
        if lookback_days is None:
            lookback_days = self.DEFAULT_LOOKBACK_DAYS
        if top_n is None:
            top_n = self.DEFAULT_TOP_N

        logger.info(f"Generating who's hot/cold as of {as_of_date}")

        # Get heat scores for all qualifying players
        all_players = self._query_heat_scores(as_of_date, min_games, lookback_days)

        if not all_players:
            return self._empty_response(as_of_date, min_games, lookback_days)

        # Get tonight's games for playing_tonight enrichment
        tonight_games = self._query_tonight_games(as_of_date)

        # Calculate league averages
        league_avg_hit = sum(p['hit_rate'] for p in all_players) / len(all_players)
        league_avg_margin = sum(p['avg_margin'] for p in all_players) / len(all_players)

        # Sort by heat score
        all_players.sort(key=lambda x: x['heat_score'], reverse=True)

        # Get hot (top N) and cold (bottom N)
        hot_players = all_players[:top_n]
        cold_players = all_players[-top_n:][::-1]  # Reverse to show coldest first

        # Enrich with tonight's game info
        hot_players = [self._enrich_with_tonight(p, tonight_games, rank) for rank, p in enumerate(hot_players, 1)]
        cold_players = [self._enrich_with_tonight(p, tonight_games, rank) for rank, p in enumerate(cold_players, 1)]

        return {
            'generated_at': self.get_generated_at(),
            'as_of_date': as_of_date,
            'time_period': f'last_{lookback_days}_days',
            'min_games': min_games,
            'total_qualifying_players': len(all_players),
            'hot': hot_players,
            'cold': cold_players,
            'league_average': {
                'hit_rate': round(league_avg_hit, 3),
                'avg_margin': round(league_avg_margin, 2)
            }
        }

    def _query_heat_scores(self, as_of_date: str, min_games: int, lookback_days: int) -> List[Dict]:
        """
        Query heat scores for all qualifying players.

        Heat Score = 0.5 * normalized_hit_rate + 0.25 * streak_factor + 0.25 * margin_factor

        Where:
        - normalized_hit_rate: hit_rate scaled 0-1 (0% = 0, 100% = 1)
        - streak_factor: current streak / 10 (capped at 1)
        - margin_factor: (avg_margin + 10) / 20 capped 0-1
        """
        query = """
        WITH recent_games AS (
            -- Get recent games with prop results
            SELECT
                g.player_lookup,
                g.game_date,
                g.points,
                g.points_line,
                g.over_under_result,
                g.points - g.points_line as margin,
                g.team_abbr,
                ROW_NUMBER() OVER (PARTITION BY g.player_lookup ORDER BY g.game_date DESC) as game_num
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            WHERE g.game_date >= DATE_SUB(@as_of_date, INTERVAL @lookback_days DAY)
              AND g.game_date <= @as_of_date
              AND g.over_under_result IN ('OVER', 'UNDER')
        ),
        player_stats AS (
            -- Calculate hit rate and margin
            SELECT
                player_lookup,
                COUNT(*) as games_played,
                SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) as overs,
                ROUND(SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) / COUNT(*), 3) as hit_rate,
                ROUND(AVG(margin), 2) as avg_margin,
                MAX(team_abbr) as team_abbr
            FROM recent_games
            GROUP BY player_lookup
            HAVING COUNT(*) >= @min_games
        ),
        first_game_result AS (
            -- Get the most recent game's result for each player
            SELECT player_lookup, over_under_result as first_result
            FROM recent_games
            WHERE game_num = 1
        ),
        streak_breaks AS (
            -- Find where the streak breaks (first game with different result than most recent)
            SELECT
                r.player_lookup,
                MIN(r.game_num) as first_break_game
            FROM recent_games r
            JOIN first_game_result f ON r.player_lookup = f.player_lookup
            WHERE r.over_under_result != f.first_result
            GROUP BY r.player_lookup
        ),
        max_games AS (
            -- Get max game_num per player (for players with no streak break)
            SELECT player_lookup, MAX(game_num) as max_game
            FROM recent_games
            GROUP BY player_lookup
        ),
        streak_calc AS (
            -- Calculate current streak length
            SELECT
                f.player_lookup,
                f.first_result as current_result,
                COALESCE(sb.first_break_game - 1, mg.max_game) as streak_length
            FROM first_game_result f
            LEFT JOIN streak_breaks sb ON f.player_lookup = sb.player_lookup
            LEFT JOIN max_games mg ON f.player_lookup = mg.player_lookup
        ),
        player_names AS (
            SELECT player_lookup, player_name, team_abbr
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        ),
        heat_scores AS (
            SELECT
                ps.player_lookup,
                COALESCE(pn.player_name, ps.player_lookup) as player_name,
                ps.team_abbr,
                ps.games_played,
                ps.hit_rate,
                ps.avg_margin,
                COALESCE(sc.streak_length, 0) as current_streak,
                COALESCE(sc.current_result, 'NONE') as streak_type,
                -- Heat score calculation
                ROUND(
                    0.5 * ps.hit_rate +
                    0.25 * LEAST(COALESCE(sc.streak_length, 0) / 10.0, 1.0) +
                    0.25 * LEAST(GREATEST((ps.avg_margin + 10) / 20.0, 0), 1.0)
                , 3) as heat_score
            FROM player_stats ps
            LEFT JOIN streak_calc sc ON ps.player_lookup = sc.player_lookup
            LEFT JOIN player_names pn ON ps.player_lookup = pn.player_lookup
        )
        SELECT * FROM heat_scores
        ORDER BY heat_score DESC
        """

        params = [
            bigquery.ScalarQueryParameter('as_of_date', 'DATE', as_of_date),
            bigquery.ScalarQueryParameter('min_games', 'INT64', min_games),
            bigquery.ScalarQueryParameter('lookback_days', 'INT64', lookback_days)
        ]

        results = self.query_to_list(query, params)

        return [
            {
                'player_lookup': r['player_lookup'],
                'player_name': r['player_name'],
                'team': r['team_abbr'],
                'heat_score': self._safe_float(r['heat_score']),
                'hit_rate': self._safe_float(r['hit_rate']),
                'current_streak': r['current_streak'],
                'streak_type': r['streak_type'],
                'avg_margin': self._safe_float(r['avg_margin']),
                'games_played': r['games_played']
            }
            for r in results
        ]

    def _query_tonight_games(self, as_of_date: str) -> Dict[str, Dict]:
        """Query games scheduled for today/tonight.

        Returns:
            Dict mapping team codes to game info:
            {
                'LAL': {'opponent': 'GSW', 'game_time': '7:30 PM ET'},
                'GSW': {'opponent': 'LAL', 'game_time': '7:30 PM ET'},
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

                # Add both teams to the map
                tonight_map[game.home_team] = {
                    'opponent': game.away_team,
                    'game_time': game_time
                }
                tonight_map[game.away_team] = {
                    'opponent': game.home_team,
                    'game_time': game_time
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

    def _enrich_with_tonight(self, player: Dict, tonight_games: Dict, rank: int) -> Dict:
        """Add tonight's game info and rank to player."""
        player['rank'] = rank

        # Check if player's team has a game tonight
        team = player.get('team')
        if team and team in tonight_games:
            game = tonight_games[team]
            player['playing_tonight'] = True
            player['tonight_opponent'] = game.get('opponent')
            player['tonight_game_time'] = game.get('game_time')
        else:
            player['playing_tonight'] = False
            player['tonight_opponent'] = None
            player['tonight_game_time'] = None

        return player

    def _empty_response(self, as_of_date: str, min_games: int, lookback_days: int) -> Dict[str, Any]:
        """Return empty response when no data available."""
        return {
            'generated_at': self.get_generated_at(),
            'as_of_date': as_of_date,
            'time_period': f'last_{lookback_days}_days',
            'min_games': min_games,
            'total_qualifying_players': 0,
            'hot': [],
            'cold': [],
            'league_average': {
                'hit_rate': None,
                'avg_margin': None
            }
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

    def export(self, as_of_date: str = None, **kwargs) -> str:
        """
        Generate and upload who's hot/cold JSON.

        Args:
            as_of_date: Date string (YYYY-MM-DD), defaults to today
            **kwargs: Additional arguments passed to generate_json

        Returns:
            GCS path of the exported file
        """
        if as_of_date is None:
            as_of_date = date.today().strftime('%Y-%m-%d')

        logger.info(f"Exporting who's hot/cold as of {as_of_date}")

        json_data = self.generate_json(as_of_date, **kwargs)

        path = 'trends/whos-hot-v2.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=3600')  # 1 hour cache

        logger.info(f"Exported who's hot/cold to {gcs_path}")
        return gcs_path
