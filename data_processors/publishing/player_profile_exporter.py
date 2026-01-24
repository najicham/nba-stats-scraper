"""
Player Profile Exporter for Phase 6 Publishing

Exports player accuracy profiles showing how well we predict each player.
Used for player detail pages on the website.
"""

import logging
from typing import Dict, List, Any, Optional

from google.cloud import bigquery

from .base_exporter import BaseExporter
from .exporter_utils import safe_float

logger = logging.getLogger(__name__)


class PlayerProfileExporter(BaseExporter):
    """
    Export player prediction accuracy profiles to JSON.

    Note: This exporter has multiple output types (index vs individual player).
    The generate_json method returns the player index by default.

    Output files:
    - players/index.json - Summary of all players
    - players/{player_lookup}.json - Detailed profile for a player

    JSON structure (index):
    {
        "generated_at": "2025-12-10T...",
        "total_players": 584,
        "players": [
            {
                "player_lookup": "lebron_james",
                "games_predicted": 45,
                "mae": 4.8,
                "win_rate": 0.72,
                "bias": -2.1
            }
        ]
    }

    JSON structure (player detail):
    {
        "player_lookup": "lebron_james",
        "generated_at": "2025-12-10T...",
        "summary": {...},
        "recent_predictions": [...],
        "by_recommendation": {...}
    }
    """

    def generate_json(self, **kwargs) -> Dict[str, Any]:
        """
        Generate JSON - returns player index by default.

        Override of abstract method. Use generate_index_json or
        generate_player_json for specific outputs.
        """
        return self.generate_index_json()

    def generate_index_json(self) -> Dict[str, Any]:
        """
        Generate player index JSON with summary stats for all players.

        Returns:
            Dictionary ready for JSON serialization
        """
        players = self._query_player_summaries()

        if not players:
            logger.warning("No players found")
            return {
                'generated_at': self.get_generated_at(),
                'total_players': 0,
                'players': []
            }

        # Format players
        formatted = []
        for p in players:
            formatted.append({
                'player_lookup': p['player_lookup'],
                'player_full_name': p.get('player_full_name', p['player_lookup']),
                'team': p.get('team_abbr'),
                'games_predicted': p['games_predicted'],
                'recommendations': p['recommendations'],
                'mae': safe_float(p['mae']),
                'win_rate': safe_float(p['win_rate']),
                'bias': safe_float(p['bias']),
                'within_5_pct': safe_float(p['within_5_pct'])
            })

        # Sort by games predicted descending
        formatted.sort(key=lambda x: x['games_predicted'], reverse=True)

        return {
            'generated_at': self.get_generated_at(),
            'total_players': len(formatted),
            'players': formatted
        }

    def generate_player_json(self, player_lookup: str) -> Dict[str, Any]:
        """
        Generate detailed profile JSON for a specific player.

        Args:
            player_lookup: Player identifier (e.g., 'lebron_james')

        Returns:
            Dictionary ready for JSON serialization
        """
        # Get summary stats
        summary = self._query_player_summary(player_lookup)
        if not summary:
            logger.warning(f"No data found for player {player_lookup}")
            return self._empty_player_response(player_lookup)

        # Get game log (50 games with full box score)
        game_log = self._query_game_log(player_lookup, limit=50)

        # Get splits (rest, location, defense_tier, opponents)
        splits = self._query_splits(player_lookup)

        # Get our track record (OVER/UNDER breakdown)
        track_record = self._query_track_record(player_lookup)

        # Get next game info
        next_game = self._query_next_game(player_lookup)

        # Get recent news
        recent_news = self._query_recent_news(player_lookup)

        return {
            'player_lookup': player_lookup,
            'player_full_name': summary.get('player_full_name', player_lookup),
            'generated_at': self.get_generated_at(),
            'recent_news': recent_news,
            'summary': {
                'team': summary.get('team_abbr'),
                'games_predicted': summary['games_predicted'],
                'total_recommendations': summary['recommendations'],
                'correct': summary['correct'],
                'mae': safe_float(summary['mae']),
                'win_rate': safe_float(summary['win_rate']),
                'bias': safe_float(summary['bias']),
                'avg_confidence': safe_float(summary['avg_confidence']),
                'within_3_pct': safe_float(summary['within_3_pct']),
                'within_5_pct': safe_float(summary['within_5_pct']),
                'date_range': {
                    'first': str(summary['first_date']) if summary.get('first_date') else None,
                    'last': str(summary['last_date']) if summary.get('last_date') else None
                }
            },
            'interpretation': self._build_interpretation(summary),
            'game_log': game_log,
            'splits': splits,
            'our_track_record': track_record,
            'next_game': next_game
        }

    def _query_player_summaries(self) -> List[Dict]:
        """Query summary stats for all players."""
        query = """
        WITH accuracy AS (
            SELECT
                player_lookup,
                MAX(team_abbr) as team_abbr,
                COUNT(DISTINCT game_date) as games_predicted,
                COUNTIF(recommendation IN ('OVER', 'UNDER')) as recommendations,
                COUNTIF(prediction_correct) as correct,
                ROUND(AVG(absolute_error), 2) as mae,
                ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNTIF(recommendation IN ('OVER', 'UNDER'))), 3) as win_rate,
                ROUND(AVG(signed_error), 2) as bias,
                ROUND(SAFE_DIVIDE(COUNTIF(within_5_points), COUNT(*)), 3) as within_5_pct
            FROM `nba-props-platform.nba_predictions.prediction_accuracy`
            WHERE system_id = 'catboost_v8'
            GROUP BY player_lookup
            HAVING games_predicted >= 3
        )
        SELECT
            a.*,
            COALESCE(r.player_name, a.player_lookup) as player_full_name
        FROM accuracy a
        LEFT JOIN (
            SELECT player_lookup, player_name
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        ) r ON a.player_lookup = r.player_lookup
        ORDER BY a.games_predicted DESC
        """
        return self.query_to_list(query)

    def _query_player_summary(self, player_lookup: str) -> Optional[Dict]:
        """Query detailed summary for a single player."""
        query = """
        WITH accuracy AS (
            SELECT
                player_lookup,
                MAX(team_abbr) as team_abbr,
                COUNT(DISTINCT game_date) as games_predicted,
                COUNTIF(recommendation IN ('OVER', 'UNDER')) as recommendations,
                COUNTIF(prediction_correct) as correct,
                ROUND(AVG(absolute_error), 2) as mae,
                ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNTIF(recommendation IN ('OVER', 'UNDER'))), 3) as win_rate,
                ROUND(AVG(signed_error), 2) as bias,
                ROUND(AVG(confidence_score), 3) as avg_confidence,
                ROUND(SAFE_DIVIDE(COUNTIF(within_3_points), COUNT(*)), 3) as within_3_pct,
                ROUND(SAFE_DIVIDE(COUNTIF(within_5_points), COUNT(*)), 3) as within_5_pct,
                MIN(game_date) as first_date,
                MAX(game_date) as last_date
            FROM `nba-props-platform.nba_predictions.prediction_accuracy`
            WHERE system_id = 'catboost_v8'
              AND player_lookup = @player_lookup
            GROUP BY player_lookup
        )
        SELECT
            a.*,
            COALESCE(r.player_name, a.player_lookup) as player_full_name
        FROM accuracy a
        LEFT JOIN (
            SELECT player_lookup, player_name
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            WHERE player_lookup = @player_lookup
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        ) r ON a.player_lookup = r.player_lookup
        """
        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup)
        ]
        results = self.query_to_list(query, params)
        return results[0] if results else None

    def _query_recent_predictions(self, player_lookup: str, limit: int = 20) -> List[Dict]:
        """Query recent predictions for a player."""
        query = """
        SELECT
            game_date,
            game_id,
            opponent_team_abbr,
            predicted_points,
            actual_points,
            line_value,
            recommendation,
            prediction_correct,
            absolute_error,
            signed_error,
            confidence_score
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE system_id = 'catboost_v8'
          AND player_lookup = @player_lookup
        ORDER BY game_date DESC
        LIMIT @limit
        """
        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('limit', 'INT64', limit)
        ]
        return self.query_to_list(query, params)

    def _query_by_recommendation(self, player_lookup: str) -> Dict[str, Any]:
        """Query breakdown by recommendation type."""
        query = """
        SELECT
            recommendation,
            COUNT(*) as count,
            COUNTIF(prediction_correct) as correct,
            ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNT(*)), 3) as win_rate,
            ROUND(AVG(absolute_error), 2) as mae
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE system_id = 'catboost_v8'
          AND player_lookup = @player_lookup
        GROUP BY recommendation
        """
        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup)
        ]
        results = self.query_to_list(query, params)

        breakdown = {}
        for r in results:
            rec = r['recommendation'] or 'UNKNOWN'
            breakdown[rec.lower()] = {
                'count': r['count'],
                'correct': r['correct'],
                'win_rate': safe_float(r['win_rate']),
                'mae': safe_float(r['mae'])
            }
        return breakdown

    def _query_game_log(self, player_lookup: str, limit: int = 50) -> List[Dict]:
        """Query game log with full box score for a player."""
        query = """
        SELECT
            g.game_date,
            g.opponent_team_abbr,
            g.team_abbr,
            g.win_flag as team_win,
            g.points,
            g.minutes_played,
            g.fg_makes,
            g.fg_attempts,
            g.three_pt_makes,
            g.three_pt_attempts,
            g.ft_makes,
            g.ft_attempts,
            (g.offensive_rebounds + g.defensive_rebounds) as rebounds,
            g.assists,
            g.steals,
            g.blocks,
            g.turnovers,
            g.points_line,
            g.over_under_result,
            -- Derive home_game from game_id format: YYYYMMDD_AWAY_HOME
            CASE
                WHEN SPLIT(g.game_id, '_')[OFFSET(2)] = g.team_abbr THEN TRUE
                ELSE FALSE
            END as home_game,
            CASE
                WHEN g.points_line IS NOT NULL THEN g.points - g.points_line
                ELSE NULL
            END as margin
        FROM `nba-props-platform.nba_analytics.player_game_summary` g
        WHERE g.player_lookup = @player_lookup
        ORDER BY g.game_date DESC
        LIMIT @limit
        """
        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('limit', 'INT64', limit)
        ]
        results = self.query_to_list(query, params)

        formatted = []
        for r in results:
            formatted.append({
                'game_date': str(r['game_date']),
                'opponent': r['opponent_team_abbr'],
                'home_game': r.get('home_game'),
                'team_result': 'W' if r.get('team_win') else 'L',
                'points': r['points'],
                'minutes': safe_float(r.get('minutes_played')),
                'fg': f"{r['fg_makes']}/{r['fg_attempts']}" if r.get('fg_attempts') else None,
                'three': f"{r['three_pt_makes']}/{r['three_pt_attempts']}" if r.get('three_pt_attempts') else None,
                'ft': f"{r['ft_makes']}/{r['ft_attempts']}" if r.get('ft_attempts') else None,
                'rebounds': r.get('rebounds'),
                'assists': r.get('assists'),
                'steals': r.get('steals'),
                'blocks': r.get('blocks'),
                'turnovers': r.get('turnovers'),
                'line': safe_float(r.get('points_line')),
                'over_under': r.get('over_under_result'),
                'margin': safe_float(r.get('margin'))
            })
        return formatted

    def _query_splits(self, player_lookup: str) -> Dict[str, Any]:
        """Query performance splits for a player."""
        query = """
        WITH games AS (
            SELECT
                g.game_date,
                g.game_id,
                g.team_abbr,
                g.points,
                g.points_line,
                g.over_under_result,
                g.opponent_team_abbr,
                -- Derive home_game from game_id format: YYYYMMDD_AWAY_HOME
                CASE
                    WHEN SPLIT(g.game_id, '_')[SAFE_OFFSET(2)] = g.team_abbr THEN TRUE
                    ELSE FALSE
                END as home_game,
                -- Calculate days rest (difference from previous game)
                DATE_DIFF(g.game_date, LAG(g.game_date) OVER (PARTITION BY g.player_lookup ORDER BY g.game_date), DAY) as days_rest
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            WHERE g.player_lookup = @player_lookup
              AND g.season_year >= 2021
        ),
        games_with_rest AS (
            SELECT
                *,
                CASE WHEN days_rest = 1 THEN TRUE ELSE FALSE END as back_to_back
            FROM games
        )
        SELECT
            -- Rest splits (back-to-back)
            ROUND(AVG(CASE WHEN back_to_back THEN points END), 1) as b2b_avg,
            COUNT(CASE WHEN back_to_back THEN 1 END) as b2b_games,
            ROUND(SAFE_DIVIDE(COUNTIF(back_to_back AND over_under_result = 'OVER'), COUNTIF(back_to_back AND over_under_result IS NOT NULL)), 3) as b2b_vs_line_pct,

            -- One day rest
            ROUND(AVG(CASE WHEN days_rest = 2 THEN points END), 1) as one_day_avg,
            COUNT(CASE WHEN days_rest = 2 THEN 1 END) as one_day_games,
            ROUND(SAFE_DIVIDE(COUNTIF(days_rest = 2 AND over_under_result = 'OVER'), COUNTIF(days_rest = 2 AND over_under_result IS NOT NULL)), 3) as one_day_vs_line_pct,

            -- Two days rest
            ROUND(AVG(CASE WHEN days_rest = 3 THEN points END), 1) as two_day_avg,
            COUNT(CASE WHEN days_rest = 3 THEN 1 END) as two_day_games,
            ROUND(SAFE_DIVIDE(COUNTIF(days_rest = 3 AND over_under_result = 'OVER'), COUNTIF(days_rest = 3 AND over_under_result IS NOT NULL)), 3) as two_day_vs_line_pct,

            -- Three+ days rest
            ROUND(AVG(CASE WHEN days_rest >= 4 THEN points END), 1) as three_plus_avg,
            COUNT(CASE WHEN days_rest >= 4 THEN 1 END) as three_plus_games,
            ROUND(SAFE_DIVIDE(COUNTIF(days_rest >= 4 AND over_under_result = 'OVER'), COUNTIF(days_rest >= 4 AND over_under_result IS NOT NULL)), 3) as three_plus_vs_line_pct,

            -- Location splits
            ROUND(AVG(CASE WHEN home_game THEN points END), 1) as home_avg,
            COUNT(CASE WHEN home_game THEN 1 END) as home_games,
            ROUND(SAFE_DIVIDE(COUNTIF(home_game AND over_under_result = 'OVER'), COUNTIF(home_game AND over_under_result IS NOT NULL)), 3) as home_vs_line_pct,

            ROUND(AVG(CASE WHEN NOT home_game THEN points END), 1) as away_avg,
            COUNT(CASE WHEN NOT home_game THEN 1 END) as away_games,
            ROUND(SAFE_DIVIDE(COUNTIF(NOT home_game AND over_under_result = 'OVER'), COUNTIF(NOT home_game AND over_under_result IS NOT NULL)), 3) as away_vs_line_pct

        FROM games_with_rest
        """
        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup)
        ]
        results = self.query_to_list(query, params)

        if not results:
            return {}

        r = results[0]
        return {
            'rest': {
                'b2b': {
                    'avg': safe_float(r.get('b2b_avg')),
                    'games': r.get('b2b_games', 0),
                    'vs_line_pct': safe_float(r.get('b2b_vs_line_pct'))
                },
                'one_day': {
                    'avg': safe_float(r.get('one_day_avg')),
                    'games': r.get('one_day_games', 0),
                    'vs_line_pct': safe_float(r.get('one_day_vs_line_pct'))
                },
                'two_day': {
                    'avg': safe_float(r.get('two_day_avg')),
                    'games': r.get('two_day_games', 0),
                    'vs_line_pct': safe_float(r.get('two_day_vs_line_pct'))
                },
                'three_plus': {
                    'avg': safe_float(r.get('three_plus_avg')),
                    'games': r.get('three_plus_games', 0),
                    'vs_line_pct': safe_float(r.get('three_plus_vs_line_pct'))
                }
            },
            'location': {
                'home': {
                    'avg': safe_float(r.get('home_avg')),
                    'games': r.get('home_games', 0),
                    'vs_line_pct': safe_float(r.get('home_vs_line_pct'))
                },
                'away': {
                    'avg': safe_float(r.get('away_avg')),
                    'games': r.get('away_games', 0),
                    'vs_line_pct': safe_float(r.get('away_vs_line_pct'))
                }
            },
            'opponents': self._query_opponent_splits(player_lookup)
        }

    def _query_opponent_splits(self, player_lookup: str) -> List[Dict]:
        """Query per-opponent splits for teams with 2+ games."""
        query = """
        SELECT
            opponent_team_abbr,
            ROUND(AVG(points), 1) as avg,
            COUNT(*) as games,
            ROUND(SAFE_DIVIDE(COUNTIF(over_under_result = 'OVER'), COUNTIF(over_under_result IS NOT NULL)), 3) as vs_line_pct
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE player_lookup = @player_lookup
          AND season_year >= 2021
        GROUP BY opponent_team_abbr
        HAVING games >= 2
        ORDER BY games DESC, avg DESC
        """
        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup)
        ]
        results = self.query_to_list(query, params)

        return [
            {
                'team': r['opponent_team_abbr'],
                'avg': safe_float(r['avg']),
                'games': r['games'],
                'vs_line_pct': safe_float(r['vs_line_pct'])
            }
            for r in results
        ]

    def _query_track_record(self, player_lookup: str) -> Dict[str, Any]:
        """Query our prediction track record for this player."""
        query = """
        SELECT
            COUNT(*) as total_predictions,
            COUNTIF(recommendation IN ('OVER', 'UNDER')) as total_recommendations,
            COUNTIF(prediction_correct) as wins,
            COUNTIF(NOT prediction_correct AND recommendation IN ('OVER', 'UNDER')) as losses,
            ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNTIF(recommendation IN ('OVER', 'UNDER'))), 3) as overall_pct,

            -- OVER breakdown
            COUNTIF(recommendation = 'OVER') as over_calls,
            COUNTIF(recommendation = 'OVER' AND prediction_correct) as over_wins,
            COUNTIF(recommendation = 'OVER' AND NOT prediction_correct) as over_losses,
            ROUND(SAFE_DIVIDE(COUNTIF(recommendation = 'OVER' AND prediction_correct), COUNTIF(recommendation = 'OVER')), 3) as over_pct,

            -- UNDER breakdown
            COUNTIF(recommendation = 'UNDER') as under_calls,
            COUNTIF(recommendation = 'UNDER' AND prediction_correct) as under_wins,
            COUNTIF(recommendation = 'UNDER' AND NOT prediction_correct) as under_losses,
            ROUND(SAFE_DIVIDE(COUNTIF(recommendation = 'UNDER' AND prediction_correct), COUNTIF(recommendation = 'UNDER')), 3) as under_pct,

            -- Error metrics
            ROUND(AVG(absolute_error), 2) as avg_error,
            ROUND(AVG(signed_error), 2) as bias,
            ROUND(SAFE_DIVIDE(COUNTIF(within_3_points), COUNT(*)), 3) as within_3_pts,
            ROUND(SAFE_DIVIDE(COUNTIF(within_5_points), COUNT(*)), 3) as within_5_pts

        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE player_lookup = @player_lookup
          AND system_id = 'catboost_v8'
        """
        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup)
        ]
        results = self.query_to_list(query, params)

        if not results:
            return {}

        r = results[0]
        return {
            'total_predictions': r.get('total_predictions', 0),
            'overall': {
                'wins': r.get('wins', 0),
                'losses': r.get('losses', 0),
                'pct': safe_float(r.get('overall_pct'))
            },
            'over_calls': {
                'total': r.get('over_calls', 0),
                'wins': r.get('over_wins', 0),
                'losses': r.get('over_losses', 0),
                'pct': safe_float(r.get('over_pct'))
            },
            'under_calls': {
                'total': r.get('under_calls', 0),
                'wins': r.get('under_wins', 0),
                'losses': r.get('under_losses', 0),
                'pct': safe_float(r.get('under_pct'))
            },
            'avg_error': safe_float(r.get('avg_error')),
            'bias': safe_float(r.get('bias')),
            'within_3_pts': safe_float(r.get('within_3_pts')),
            'within_5_pts': safe_float(r.get('within_5_pts'))
        }

    def _query_recent_news(self, player_lookup: str, limit: int = 5) -> List[Dict]:
        """Query recent news articles for a player."""
        query = """
        SELECT
            l.article_id,
            a.title,
            a.source,
            a.source_url,
            a.published_at,
            i.category,
            i.headline,
            i.ai_summary
        FROM `nba-props-platform.nba_analytics.news_player_links` l
        JOIN `nba-props-platform.nba_raw.news_articles_raw` a
            ON l.article_id = a.article_id
        LEFT JOIN `nba-props-platform.nba_analytics.news_insights` i
            ON l.article_id = i.article_id
        WHERE l.player_lookup = @player_lookup
        ORDER BY a.published_at DESC
        LIMIT @limit
        """
        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('limit', 'INT64', limit)
        ]

        try:
            results = self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query news for {player_lookup}: {e}")
            return []

        # Source display name mapping
        source_names = {
            'espn_nba': 'ESPN',
            'espn_mlb': 'ESPN',
            'cbs_nba': 'CBS Sports',
            'cbs_mlb': 'CBS Sports',
            'rotowire_nba': 'RotoWire',
            'rotowire_mlb': 'RotoWire',
            'yahoo_nba': 'Yahoo Sports',
            'yahoo_mlb': 'Yahoo Sports',
        }

        formatted = []
        for r in results:
            # Create headline from title if not present
            headline = r.get('headline')
            if not headline:
                title = r.get('title', '')
                headline = title[:47] + '...' if len(title) > 50 else title

            formatted.append({
                'headline': headline,
                'category': r.get('category', 'other'),
                'source': source_names.get(r['source'], r['source']),
                'source_url': r.get('source_url'),
                'published_at': r['published_at'].isoformat() if r.get('published_at') else None,
            })

        return formatted

    def _query_next_game(self, player_lookup: str) -> Optional[Dict]:
        """Query next scheduled game for the player."""
        query = """
        SELECT
            gc.game_date,
            gc.game_id,
            gc.opponent_team_abbr,
            gc.home_game,
            CASE WHEN pp.player_lookup IS NOT NULL THEN TRUE ELSE FALSE END as has_prediction
        FROM `nba-props-platform.nba_analytics.upcoming_player_game_context` gc
        LEFT JOIN `nba-props-platform.nba_predictions.player_prop_predictions` pp
            ON gc.player_lookup = pp.player_lookup
            AND gc.game_date = pp.game_date
            AND pp.system_id = 'catboost_v8'
        WHERE gc.player_lookup = @player_lookup
          AND gc.game_date >= CURRENT_DATE()
        ORDER BY gc.game_date ASC
        LIMIT 1
        """
        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup)
        ]
        results = self.query_to_list(query, params)

        if not results:
            return None

        r = results[0]
        return {
            'game_date': str(r['game_date']),
            'game_id': r['game_id'],
            'opponent': r['opponent_team_abbr'],
            'home_game': r['home_game'],
            'has_prediction': r['has_prediction']
        }

    def _format_recent_predictions(self, recent: List[Dict]) -> List[Dict[str, Any]]:
        """Format recent predictions for JSON output."""
        formatted = []
        for r in recent:
            if r['prediction_correct'] is True:
                result = 'WIN'
            elif r['prediction_correct'] is False:
                result = 'LOSS'
            elif r['recommendation'] == 'PASS':
                result = 'PASS'
            else:
                result = 'PUSH'

            formatted.append({
                'game_date': str(r['game_date']),
                'game_id': r['game_id'],
                'opponent': r['opponent_team_abbr'],
                'predicted': safe_float(r['predicted_points']),
                'actual': r['actual_points'],
                'line': safe_float(r['line_value']),
                'recommendation': r['recommendation'],
                'result': result,
                'error': safe_float(r['absolute_error']),
                'confidence': safe_float(r['confidence_score'])
            })
        return formatted

    def _build_interpretation(self, summary: Dict) -> Dict[str, str]:
        """Build human-readable interpretation of player stats."""
        interp = {}

        # Bias interpretation
        bias = summary.get('bias')
        if bias is not None:
            if bias < -3:
                interp['bias'] = f"We significantly under-predict this player (bias: {bias})"
            elif bias < -1:
                interp['bias'] = f"We slightly under-predict this player (bias: {bias})"
            elif bias > 3:
                interp['bias'] = f"We significantly over-predict this player (bias: {bias})"
            elif bias > 1:
                interp['bias'] = f"We slightly over-predict this player (bias: {bias})"
            else:
                interp['bias'] = f"Our predictions are well-calibrated for this player (bias: {bias})"

        # Win rate interpretation
        win_rate = summary.get('win_rate')
        recs = summary.get('recommendations', 0)
        if win_rate is not None and recs >= 5:
            if win_rate >= 0.85:
                interp['accuracy'] = f"Excellent track record ({win_rate:.0%} win rate)"
            elif win_rate >= 0.70:
                interp['accuracy'] = f"Good track record ({win_rate:.0%} win rate)"
            elif win_rate >= 0.55:
                interp['accuracy'] = f"Average track record ({win_rate:.0%} win rate)"
            else:
                interp['accuracy'] = f"Below average track record ({win_rate:.0%} win rate)"

        # Sample size interpretation
        games = summary.get('games_predicted', 0)
        if games < 5:
            interp['sample_size'] = "Limited data (fewer than 5 games)"
        elif games < 15:
            interp['sample_size'] = "Moderate sample size"
        else:
            interp['sample_size'] = "Large sample size"

        return interp

    def _empty_player_response(self, player_lookup: str) -> Dict[str, Any]:
        """Return empty response for unknown player."""
        return {
            'player_lookup': player_lookup,
            'player_full_name': player_lookup,
            'generated_at': self.get_generated_at(),
            'recent_news': [],
            'summary': None,
            'interpretation': {'error': 'No prediction data found for this player'},
            'game_log': [],
            'splits': {},
            'our_track_record': {},
            'next_game': None
        }

    def export_index(self) -> str:
        """
        Generate and upload player index JSON.

        Returns:
            GCS path of the exported file
        """
        logger.info("Exporting player index")

        json_data = self.generate_index_json()

        path = 'players/index.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=3600')

        return gcs_path

    def export_player(self, player_lookup: str) -> str:
        """
        Generate and upload player profile JSON.

        Args:
            player_lookup: Player identifier

        Returns:
            GCS path of the exported file
        """
        logger.info(f"Exporting player profile: {player_lookup}")

        json_data = self.generate_player_json(player_lookup)

        path = f'players/{player_lookup}.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=3600')

        return gcs_path

    def export_all_players(self, min_games: int = 5) -> List[str]:
        """
        Export profiles for all players with sufficient data.

        Args:
            min_games: Minimum games to include player

        Returns:
            List of GCS paths
        """
        logger.info(f"Exporting all player profiles (min_games={min_games})")

        # Get player list
        players = self._query_player_summaries()
        eligible = [p for p in players if p['games_predicted'] >= min_games]

        logger.info(f"Found {len(eligible)} players with >= {min_games} games")

        paths = []

        # Export index first
        index_path = self.export_index()
        paths.append(index_path)

        # Export each player
        for i, player in enumerate(eligible):
            player_lookup = player['player_lookup']
            logger.info(f"[{i+1}/{len(eligible)}] Exporting {player_lookup}")
            path = self.export_player(player_lookup)
            paths.append(path)

        return paths
