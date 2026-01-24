"""
Tonight's Trend Plays Exporter for Trends Page

Identifies players playing TONIGHT who have actionable trends:
1. Streak plays: 3+ game OVER/UNDER streak
2. Momentum plays: 15%+ scoring change (L5 vs L15)
3. Rest plays: On B2B (tired) or 3+ days rest (fresh)

Output: /v1/trends/tonight-plays.json
Refresh: Daily (updated throughout day as games approach)

Frontend fields (TonightTrendPlay):
- player_lookup, player_full_name, team_abbr, position
- trend_type: "streak" | "momentum" | "rest"
- trend_direction: "over" | "under"
- trend_details: type-specific details
- tonight: {opponent, game_time, home}
- confidence: "high" | "medium"
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date, datetime

from google.cloud import bigquery

from .base_exporter import BaseExporter
from .exporter_utils import safe_float
from shared.utils.schedule import NBAScheduleService

logger = logging.getLogger(__name__)


class TonightTrendPlaysExporter(BaseExporter):
    """
    Export tonight's trend plays - actionable betting angles for today's games.

    JSON structure:
    {
        "generated_at": "...",
        "game_date": "2024-12-15",
        "games_tonight": 8,
        "trend_plays": [
            {
                "player_lookup": "stephencurry",
                "player_full_name": "Stephen Curry",
                "team_abbr": "GSW",
                "position": "PG",
                "trend_type": "streak",
                "trend_direction": "over",
                "trend_details": {
                    "streak_length": 5,
                    "avg_margin": 4.2,
                    "hit_rate_l10": 0.80
                },
                "confidence": "high",
                "tonight": {
                    "opponent": "LAL",
                    "game_time": "7:30 PM ET",
                    "home": true
                }
            }
        ],
        "by_trend_type": {
            "streak": 12,
            "momentum": 8,
            "rest": 15
        }
    }
    """

    # Configuration thresholds
    MIN_STREAK_LENGTH = 3
    MIN_MOMENTUM_CHANGE_PCT = 0.15  # 15% scoring change L5 vs L15
    REST_THRESHOLD_FRESH = 3  # 3+ days rest = fresh
    REST_THRESHOLD_TIRED = 1  # B2B = tired
    MAX_DAYS_REST = 7  # Cap at 7 days to exclude long injury returns

    def generate_json(self, game_date: str = None) -> Dict[str, Any]:
        """
        Generate tonight's trend plays JSON.

        Args:
            game_date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            Dictionary ready for JSON serialization
        """
        if game_date is None:
            game_date = date.today().strftime('%Y-%m-%d')

        logger.info(f"Generating tonight's trend plays for {game_date}")

        # Get tonight's games first - if no games, return empty
        tonight_games = self._query_tonight_games(game_date)
        if not tonight_games:
            return self._empty_response(game_date, 0)

        teams_playing = set(tonight_games.keys())
        games_count = len(tonight_games) // 2  # Each game adds 2 teams

        # Query each trend type for players on teams playing tonight
        streak_plays = self._query_streak_plays(game_date, teams_playing)
        momentum_plays = self._query_momentum_plays(game_date, teams_playing)
        rest_plays = self._query_rest_plays(game_date, teams_playing)

        # Combine and dedupe (player can have multiple trends, keep best one)
        all_plays = []
        seen_players = set()

        # Priority: streak > momentum > rest (streaks are most actionable)
        for play in streak_plays + momentum_plays + rest_plays:
            player_key = play['player_lookup']
            if player_key not in seen_players:
                seen_players.add(player_key)
                # Enrich with tonight's game info
                self._enrich_with_tonight(play, tonight_games)
                all_plays.append(play)

        # Sort by confidence then trend type priority
        confidence_order = {'high': 0, 'medium': 1}
        type_order = {'streak': 0, 'momentum': 1, 'rest': 2}
        all_plays.sort(key=lambda x: (
            confidence_order.get(x['confidence'], 2),
            type_order.get(x['trend_type'], 3)
        ))

        return {
            'generated_at': self.get_generated_at(),
            'game_date': game_date,
            'games_tonight': games_count,
            'total_trend_plays': len(all_plays),
            'trend_plays': all_plays,
            'by_trend_type': {
                'streak': len(streak_plays),
                'momentum': len(momentum_plays),
                'rest': len(rest_plays)
            }
        }

    def _query_streak_plays(self, game_date: str, teams_playing: set) -> List[Dict]:
        """Query players with 3+ game OVER/UNDER streaks."""
        teams_list = list(teams_playing)

        query = """
        WITH recent_games AS (
            SELECT
                g.player_lookup,
                g.team_abbr,
                g.game_date,
                g.points,
                g.points_line,
                g.over_under_result,
                g.points - g.points_line as margin,
                ROW_NUMBER() OVER (PARTITION BY g.player_lookup ORDER BY g.game_date DESC) as game_num
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            WHERE g.game_date < @game_date
              AND g.game_date >= DATE_SUB(@game_date, INTERVAL 30 DAY)
              AND g.over_under_result IN ('OVER', 'UNDER')
              AND g.team_abbr IN UNNEST(@teams_playing)
        ),
        first_result AS (
            SELECT player_lookup, over_under_result as first_result
            FROM recent_games
            WHERE game_num = 1
        ),
        streak_breaks AS (
            SELECT
                r.player_lookup,
                MIN(r.game_num) as first_break_game
            FROM recent_games r
            JOIN first_result f ON r.player_lookup = f.player_lookup
            WHERE r.over_under_result != f.first_result
            GROUP BY r.player_lookup
        ),
        max_games AS (
            SELECT player_lookup, MAX(game_num) as max_game
            FROM recent_games
            GROUP BY player_lookup
        ),
        streak_calc AS (
            SELECT
                f.player_lookup,
                f.first_result as streak_direction,
                COALESCE(sb.first_break_game - 1, mg.max_game) as streak_length
            FROM first_result f
            LEFT JOIN streak_breaks sb ON f.player_lookup = sb.player_lookup
            LEFT JOIN max_games mg ON f.player_lookup = mg.player_lookup
        ),
        player_stats AS (
            SELECT
                r.player_lookup,
                r.team_abbr,
                AVG(r.margin) as avg_margin,
                SUM(CASE WHEN r.game_num <= 10 AND r.over_under_result = 'OVER' THEN 1 ELSE 0 END) as overs_l10,
                COUNT(CASE WHEN r.game_num <= 10 THEN 1 END) as games_l10
            FROM recent_games r
            GROUP BY r.player_lookup, r.team_abbr
        ),
        player_names AS (
            SELECT player_lookup, player_name, position
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        )
        SELECT
            sc.player_lookup,
            COALESCE(pn.player_name, sc.player_lookup) as player_name,
            ps.team_abbr,
            pn.position,
            sc.streak_direction,
            sc.streak_length,
            ROUND(ps.avg_margin, 1) as avg_margin,
            ROUND(ps.overs_l10 / NULLIF(ps.games_l10, 0), 2) as hit_rate_l10
        FROM streak_calc sc
        JOIN player_stats ps ON sc.player_lookup = ps.player_lookup
        LEFT JOIN player_names pn ON sc.player_lookup = pn.player_lookup
        WHERE sc.streak_length >= @min_streak
        ORDER BY sc.streak_length DESC, ps.avg_margin DESC
        """

        params = [
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
            bigquery.ArrayQueryParameter('teams_playing', 'STRING', teams_list),
            bigquery.ScalarQueryParameter('min_streak', 'INT64', self.MIN_STREAK_LENGTH)
        ]

        results = self.query_to_list(query, params)

        return [
            {
                'player_lookup': r['player_lookup'],
                'player_full_name': r['player_name'],
                'team_abbr': r['team_abbr'],
                'position': r.get('position'),
                'trend_type': 'streak',
                'trend_direction': r['streak_direction'].lower(),
                'trend_details': {
                    'streak_length': r['streak_length'],
                    'avg_margin': safe_float(r['avg_margin']),
                    'hit_rate_l10': safe_float(r['hit_rate_l10'])
                },
                'confidence': 'high' if r['streak_length'] >= 5 else 'medium'
            }
            for r in results
        ]

    def _query_momentum_plays(self, game_date: str, teams_playing: set) -> List[Dict]:
        """Query players with 15%+ scoring change (L5 vs L15)."""
        teams_list = list(teams_playing)

        query = """
        WITH recent_games AS (
            SELECT
                g.player_lookup,
                g.team_abbr,
                g.points,
                ROW_NUMBER() OVER (PARTITION BY g.player_lookup ORDER BY g.game_date DESC) as game_num
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            WHERE g.game_date < @game_date
              AND g.game_date >= DATE_SUB(@game_date, INTERVAL 45 DAY)
              AND g.team_abbr IN UNNEST(@teams_playing)
        ),
        player_avgs AS (
            SELECT
                player_lookup,
                team_abbr,
                AVG(CASE WHEN game_num <= 5 THEN points END) as l5_avg,
                AVG(CASE WHEN game_num <= 15 THEN points END) as l15_avg,
                COUNT(CASE WHEN game_num <= 15 THEN 1 END) as games_l15
            FROM recent_games
            GROUP BY player_lookup, team_abbr
            HAVING COUNT(CASE WHEN game_num <= 5 THEN 1 END) >= 5
               AND COUNT(CASE WHEN game_num <= 15 THEN 1 END) >= 10
        ),
        momentum_calc AS (
            SELECT
                player_lookup,
                team_abbr,
                l5_avg,
                l15_avg,
                games_l15,
                (l5_avg - l15_avg) / NULLIF(l15_avg, 0) as pct_change,
                CASE
                    WHEN l5_avg > l15_avg THEN 'surging'
                    ELSE 'slumping'
                END as momentum_type
            FROM player_avgs
            WHERE l15_avg > 0
        ),
        player_names AS (
            SELECT player_lookup, player_name, position
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        )
        SELECT
            mc.player_lookup,
            COALESCE(pn.player_name, mc.player_lookup) as player_name,
            mc.team_abbr,
            pn.position,
            mc.momentum_type,
            ROUND(mc.l5_avg, 1) as l5_avg,
            ROUND(mc.l15_avg, 1) as l15_avg,
            ROUND(mc.pct_change * 100, 1) as pct_change,
            ROUND(mc.l5_avg - mc.l15_avg, 1) as ppg_change
        FROM momentum_calc mc
        LEFT JOIN player_names pn ON mc.player_lookup = pn.player_lookup
        WHERE ABS(mc.pct_change) >= @min_change_pct
        ORDER BY ABS(mc.pct_change) DESC
        """

        params = [
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
            bigquery.ArrayQueryParameter('teams_playing', 'STRING', teams_list),
            bigquery.ScalarQueryParameter('min_change_pct', 'FLOAT64', self.MIN_MOMENTUM_CHANGE_PCT)
        ]

        results = self.query_to_list(query, params)

        return [
            {
                'player_lookup': r['player_lookup'],
                'player_full_name': r['player_name'],
                'team_abbr': r['team_abbr'],
                'position': r.get('position'),
                'trend_type': 'momentum',
                'trend_direction': 'over' if r['momentum_type'] == 'surging' else 'under',
                'trend_details': {
                    'momentum_type': r['momentum_type'],
                    'l5_avg': safe_float(r['l5_avg']),
                    'l15_avg': safe_float(r['l15_avg']),
                    'pct_change': safe_float(r['pct_change']),
                    'ppg_change': safe_float(r['ppg_change'])
                },
                'confidence': 'high' if abs(r['pct_change']) >= 25 else 'medium'
            }
            for r in results
        ]

    def _query_rest_plays(self, game_date: str, teams_playing: set) -> List[Dict]:
        """Query players with rest advantage (3+ days) or disadvantage (B2B)."""
        teams_list = list(teams_playing)

        query = """
        WITH last_games AS (
            SELECT
                g.player_lookup,
                g.team_abbr,
                g.game_date,
                ROW_NUMBER() OVER (PARTITION BY g.player_lookup ORDER BY g.game_date DESC) as rn
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            WHERE g.game_date < @game_date
              AND g.team_abbr IN UNNEST(@teams_playing)
        ),
        rest_calc AS (
            SELECT
                player_lookup,
                team_abbr,
                game_date as last_game_date,
                DATE_DIFF(@game_date, game_date, DAY) as days_rest
            FROM last_games
            WHERE rn = 1
        ),
        games_with_rest AS (
            -- First compute days_rest per game using window function
            SELECT
                g.player_lookup,
                g.points,
                DATE_DIFF(g.game_date, LAG(g.game_date) OVER (
                    PARTITION BY g.player_lookup ORDER BY g.game_date), DAY) as days_since_last
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            WHERE g.season_year >= 2022
              AND g.player_lookup IN (SELECT player_lookup FROM rest_calc)
        ),
        rest_splits AS (
            -- Now aggregate using the pre-computed days_rest
            SELECT
                player_lookup,
                AVG(CASE WHEN days_since_last >= 3 THEN points END) as rested_avg,
                AVG(CASE WHEN days_since_last = 1 THEN points END) as b2b_avg,
                AVG(points) as overall_avg,
                COUNT(CASE WHEN days_since_last >= 3 THEN 1 END) as rested_games,
                COUNT(CASE WHEN days_since_last = 1 THEN 1 END) as b2b_games
            FROM games_with_rest
            WHERE days_since_last IS NOT NULL
            GROUP BY player_lookup
        ),
        player_names AS (
            SELECT player_lookup, player_name, position
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        )
        SELECT
            rc.player_lookup,
            COALESCE(pn.player_name, rc.player_lookup) as player_name,
            rc.team_abbr,
            pn.position,
            rc.days_rest,
            CASE
                WHEN rc.days_rest >= @fresh_threshold THEN 'fresh'
                WHEN rc.days_rest = @tired_threshold THEN 'tired'
                ELSE NULL
            END as rest_status,
            ROUND(rs.rested_avg, 1) as rested_avg,
            ROUND(rs.b2b_avg, 1) as b2b_avg,
            ROUND(rs.overall_avg, 1) as overall_avg,
            rs.rested_games,
            rs.b2b_games,
            ROUND(COALESCE(rs.rested_avg, rs.overall_avg) - COALESCE(rs.b2b_avg, rs.overall_avg), 1) as rest_impact
        FROM rest_calc rc
        LEFT JOIN rest_splits rs ON rc.player_lookup = rs.player_lookup
        LEFT JOIN player_names pn ON rc.player_lookup = pn.player_lookup
        WHERE (
            (rc.days_rest >= @fresh_threshold AND rc.days_rest <= @max_days_rest)
            OR rc.days_rest = @tired_threshold
          )
          -- Only include if we have meaningful historical data and significant rest impact
          AND (
            (rc.days_rest >= @fresh_threshold AND rs.rested_games >= 5 AND ABS(COALESCE(rs.rested_avg, 0) - COALESCE(rs.overall_avg, 0)) >= 2)
            OR
            (rc.days_rest = @tired_threshold AND rs.b2b_games >= 3 AND ABS(COALESCE(rs.b2b_avg, 0) - COALESCE(rs.overall_avg, 0)) >= 2)
          )
        ORDER BY
            CASE WHEN rc.days_rest >= @fresh_threshold THEN 0 ELSE 1 END,
            ABS(COALESCE(rs.rested_avg, rs.overall_avg) - COALESCE(rs.b2b_avg, rs.overall_avg)) DESC
        """

        params = [
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
            bigquery.ArrayQueryParameter('teams_playing', 'STRING', teams_list),
            bigquery.ScalarQueryParameter('fresh_threshold', 'INT64', self.REST_THRESHOLD_FRESH),
            bigquery.ScalarQueryParameter('tired_threshold', 'INT64', self.REST_THRESHOLD_TIRED),
            bigquery.ScalarQueryParameter('max_days_rest', 'INT64', self.MAX_DAYS_REST)
        ]

        results = self.query_to_list(query, params)

        plays = []
        for r in results:
            if r['rest_status'] is None:
                continue

            rest_impact = safe_float(r.get('rest_impact')) or 0
            is_fresh = r['rest_status'] == 'fresh'

            # Fresh players lean OVER, tired players lean UNDER
            # But only if historical data supports it
            if is_fresh:
                direction = 'over' if rest_impact > 0 else 'under'
                sample_games = r.get('rested_games') or 0
            else:
                direction = 'under' if rest_impact > 0 else 'over'
                sample_games = r.get('b2b_games') or 0

            plays.append({
                'player_lookup': r['player_lookup'],
                'player_full_name': r['player_name'],
                'team_abbr': r['team_abbr'],
                'position': r.get('position'),
                'trend_type': 'rest',
                'trend_direction': direction,
                'trend_details': {
                    'rest_status': r['rest_status'],
                    'days_rest': r['days_rest'],
                    'rested_avg': safe_float(r.get('rested_avg')),
                    'b2b_avg': safe_float(r.get('b2b_avg')),
                    'overall_avg': safe_float(r.get('overall_avg')),
                    'rest_impact': rest_impact,
                    'sample_games': sample_games
                },
                'confidence': 'high' if sample_games >= 10 and abs(rest_impact) >= 3 else 'medium'
            })

        return plays

    def _query_tonight_games(self, game_date: str) -> Dict[str, Dict]:
        """Query games scheduled for today/tonight.

        Returns:
            Dict mapping team codes to game info
        """
        try:
            schedule = NBAScheduleService()
            games = schedule.get_games_for_date(game_date)

            tonight_map = {}
            for game in games:
                game_time = self._format_game_time(game.commence_time)

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
            dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
            return dt.strftime('%-I:%M %p ET')
        except (ValueError, AttributeError):
            return None

    def _enrich_with_tonight(self, play: Dict, tonight_games: Dict) -> None:
        """Add tonight's game info to play (mutates in place)."""
        team = play.get('team_abbr')
        if team and team in tonight_games:
            game = tonight_games[team]
            play['tonight'] = {
                'opponent': game.get('opponent'),
                'game_time': game.get('game_time'),
                'home': game.get('home', False),
            }
        else:
            play['tonight'] = None

    def _empty_response(self, game_date: str, games_count: int) -> Dict[str, Any]:
        """Return empty response when no games tonight."""
        return {
            'generated_at': self.get_generated_at(),
            'game_date': game_date,
            'games_tonight': games_count,
            'total_trend_plays': 0,
            'trend_plays': [],
            'by_trend_type': {
                'streak': 0,
                'momentum': 0,
                'rest': 0
            }
        }

    def export(self, game_date: str = None) -> str:
        """
        Generate and upload tonight's trend plays JSON.

        Args:
            game_date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            GCS path of the exported file
        """
        if game_date is None:
            game_date = date.today().strftime('%Y-%m-%d')

        logger.info(f"Exporting tonight's trend plays for {game_date}")

        json_data = self.generate_json(game_date)

        path = 'trends/tonight-plays.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=3600')  # 1 hour cache

        logger.info(f"Exported tonight's trend plays to {gcs_path}")
        return gcs_path
