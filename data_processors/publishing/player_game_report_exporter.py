"""
Player Game Report Exporter for Player Modal

Exports per-game deep dive analysis for a specific player on a specific date.
Combines player profile, opponent context, prediction angles, and result.

Endpoint: GET /v1/player/{player_lookup}/game-report/{date}
Refresh: On-demand / cached per game

Frontend fields (GameReportResponse):
- player_profile: archetype, shot_profile, position
- opponent_context: pace, defense_rank, defense_by_zone
- prop_lines: current, opening, movement
- moving_averages: l5, l10, l20, season
- line_analysis: inflation_score, bounce_back_score
- prediction_angles: supporting[], against[]
- recent_games: last 5 games with stats
- head_to_head: vs opponent history
- result: actual points, recommendation, correct
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date, datetime

from google.cloud import bigquery

from .base_exporter import BaseExporter
from .exporter_utils import safe_float
from shared.config.model_selection import get_champion_model_id

logger = logging.getLogger(__name__)


# Shot profile thresholds (from data requirements)
SHOT_PROFILE_THRESHOLDS = {
    'interior': 0.50,    # 50%+ paint shots
    'perimeter': 0.50,   # 50%+ three-point shots
    'mid_range': 0.30,   # 30%+ mid-range shots
}


def classify_shot_profile(paint_rate: float, three_pt_rate: float, mid_rate: float) -> str:
    """Classify player's shot profile based on zone distribution."""
    if paint_rate and paint_rate >= SHOT_PROFILE_THRESHOLDS['interior']:
        return 'interior'
    elif three_pt_rate and three_pt_rate >= SHOT_PROFILE_THRESHOLDS['perimeter']:
        return 'perimeter'
    elif mid_rate and mid_rate >= SHOT_PROFILE_THRESHOLDS['mid_range']:
        return 'mid_range'
    return 'balanced'


class PlayerGameReportExporter(BaseExporter):
    """
    Export per-game analysis for Player Modal game report tab.

    JSON structure:
    {
        "player_lookup": "stephencurry",
        "player_full_name": "Stephen Curry",
        "game_date": "2024-12-15",
        "game_id": "20241215_GSW_LAL",
        "generated_at": "...",
        "player_profile": {
            "position": "PG",
            "shot_profile": "perimeter",
            "season_ppg": 26.5
        },
        "opponent_context": {
            "opponent": "LAL",
            "is_home": true,
            "opp_pace": 98.5,
            "opp_def_rating": 112.3,
            "opp_def_rank": 15,
            "opp_paint_defense": "average",
            "opp_perimeter_defense": "weak"
        },
        "moving_averages": {
            "l5": 28.2,
            "l10": 26.8,
            "l20": 26.1,
            "season": 26.5
        },
        "prop_line": {
            "line": 27.5,
            "recommendation": "OVER",
            "predicted": 29.2,
            "confidence": 0.72
        },
        "prediction_angles": {
            "supporting": ["Hot streak (5G OVER)", "Weak perimeter D"],
            "against": ["Back-to-back game"]
        },
        "recent_games": [...],
        "head_to_head": {...},
        "result": {
            "actual": 32,
            "margin": 4.5,
            "correct": true
        }
    }
    """

    def generate_json(self, player_lookup: str, game_date: str) -> Dict[str, Any]:
        """
        Generate game report JSON for a specific player and date.

        Args:
            player_lookup: Player identifier (e.g., 'stephencurry')
            game_date: Date string in YYYY-MM-DD format

        Returns:
            Dictionary ready for JSON serialization
        """
        logger.info(f"Generating game report for {player_lookup} on {game_date}")

        # Get player profile info
        profile = self._query_player_profile(player_lookup, game_date)
        if not profile:
            return self._empty_response(player_lookup, game_date, "Player not found")

        # Get the game details
        game = self._query_game_details(player_lookup, game_date)
        if not game:
            return self._empty_response(player_lookup, game_date, "Game not found")

        # Get opponent context
        opponent_context = self._query_opponent_context(game.get('opponent_team_abbr'), game_date)

        # Get moving averages
        moving_averages = self._query_moving_averages(player_lookup, game_date)

        # Get prediction info
        prediction = self._query_prediction(player_lookup, game_date)

        # Get recent games (last 5)
        recent_games = self._query_recent_games(player_lookup, game_date, limit=5)

        # Get head-to-head history
        h2h = self._query_head_to_head(player_lookup, game.get('opponent_team_abbr'), game_date)

        # Build prediction angles
        angles = self._build_prediction_angles(
            profile, moving_averages, opponent_context, game, recent_games
        )

        # Build result if game is complete
        result = None
        if game.get('actual_points') is not None:
            line = prediction.get('line') if prediction else None
            result = {
                'actual': game['actual_points'],
                'margin': safe_float(game['actual_points'] - line) if line else None,
                'correct': prediction.get('correct') if prediction else None,
            }

        return {
            'player_lookup': player_lookup,
            'player_full_name': profile.get('player_name', player_lookup),
            'game_date': game_date,
            'game_id': game.get('game_id'),
            'generated_at': self.get_generated_at(),
            'player_profile': {
                'position': profile.get('position'),
                'shot_profile': profile.get('shot_profile', 'balanced'),
                'season_ppg': safe_float(profile.get('season_ppg')),
            },
            'opponent_context': opponent_context,
            'moving_averages': moving_averages,
            'prop_line': {
                'line': safe_float(prediction.get('line')),
                'recommendation': prediction.get('recommendation'),
                'predicted': safe_float(prediction.get('predicted')),
                'confidence': safe_float(prediction.get('confidence')),
            } if prediction else None,
            'prediction_angles': angles,
            'recent_games': recent_games,
            'head_to_head': h2h,
            'result': result,
        }

    def _query_player_profile(self, player_lookup: str, game_date: str) -> Optional[Dict]:
        """Query player profile with shot profile classification."""
        query = """
        WITH player_info AS (
            SELECT
                player_lookup,
                player_name,
                position,
                team_abbr
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            WHERE player_lookup = @player_lookup
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        ),
        season_stats AS (
            SELECT
                player_lookup,
                AVG(points) as season_ppg
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE player_lookup = @player_lookup
              AND game_date < @game_date
              AND season_year = CASE
                  WHEN EXTRACT(MONTH FROM @game_date) >= 10 THEN EXTRACT(YEAR FROM @game_date)
                  ELSE EXTRACT(YEAR FROM @game_date) - 1
              END
            GROUP BY player_lookup
        ),
        shot_zones AS (
            SELECT
                player_lookup,
                paint_rate_last_10 as pct_paint,
                mid_range_rate_last_10 as pct_mid_range,
                three_pt_rate_last_10 as pct_three
            FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
            WHERE player_lookup = @player_lookup
              AND analysis_date <= @game_date
            ORDER BY analysis_date DESC
            LIMIT 1
        )
        SELECT
            pi.player_lookup,
            pi.player_name,
            pi.position,
            pi.team_abbr,
            ss.season_ppg,
            sz.pct_paint,
            sz.pct_mid_range,
            sz.pct_three
        FROM player_info pi
        LEFT JOIN season_stats ss ON pi.player_lookup = ss.player_lookup
        LEFT JOIN shot_zones sz ON pi.player_lookup = sz.player_lookup
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
        ]

        results = self.query_to_list(query, params)
        if not results:
            return None

        r = results[0]
        shot_profile = classify_shot_profile(
            safe_float(r.get('pct_paint')),
            safe_float(r.get('pct_three')),
            safe_float(r.get('pct_mid_range'))
        )

        return {
            'player_name': r['player_name'],
            'position': r.get('position'),
            'team_abbr': r.get('team_abbr'),
            'season_ppg': safe_float(r.get('season_ppg')),
            'shot_profile': shot_profile,
        }

    def _query_game_details(self, player_lookup: str, game_date: str) -> Optional[Dict]:
        """Query game details for this player on this date."""
        query = """
        SELECT
            game_id,
            game_date,
            team_abbr,
            opponent_team_abbr,
            points as actual_points,
            minutes_played,
            CASE WHEN team_abbr = SUBSTR(game_id, 14, 3) THEN TRUE ELSE FALSE END as is_home
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
        LIMIT 1
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
        ]

        results = self.query_to_list(query, params)
        return results[0] if results else None

    def _query_opponent_context(self, opponent: str, game_date: str) -> Dict[str, Any]:
        """Query opponent context (pace, defense ratings, zone defense)."""
        if not opponent:
            return {}

        # Query defense zone analysis which has the precomputed defense stats
        query = """
        WITH defense_zone AS (
            SELECT
                team_abbr,
                paint_pct_allowed_last_15 as paint_pct_allowed,
                three_pt_pct_allowed_last_15 as three_pt_pct_allowed,
                defensive_rating_last_15 as overall_defense_rating,
                opponent_pace as opp_pace,
                RANK() OVER (ORDER BY defensive_rating_last_15 ASC) as def_rank
            FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
            WHERE analysis_date <= @game_date
            QUALIFY ROW_NUMBER() OVER (PARTITION BY team_abbr ORDER BY analysis_date DESC) = 1
        )
        SELECT *
        FROM defense_zone
        WHERE team_abbr = @opponent
        """

        params = [
            bigquery.ScalarQueryParameter('opponent', 'STRING', opponent),
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
        ]

        results = self.query_to_list(query, params)
        if not results:
            return {'opponent': opponent}

        r = results[0]

        # Classify defense quality based on percentages allowed
        def defense_tier(pct_allowed):
            if pct_allowed is None:
                return 'average'
            pct = float(pct_allowed)
            if pct <= 0.45:
                return 'strong'
            elif pct >= 0.52:
                return 'weak'
            return 'average'

        return {
            'opponent': opponent,
            'opp_pace': safe_float(r.get('opp_pace')),
            'opp_def_rating': safe_float(r.get('overall_defense_rating')),
            'opp_def_rank': r.get('def_rank'),
            'opp_paint_defense': defense_tier(r.get('paint_pct_allowed')),
            'opp_perimeter_defense': defense_tier(r.get('three_pt_pct_allowed')),
        }

    def _query_moving_averages(self, player_lookup: str, game_date: str) -> Dict[str, Any]:
        """Query moving averages (L5, L10, L20, season)."""
        query = """
        WITH recent_games AS (
            SELECT
                points,
                ROW_NUMBER() OVER (ORDER BY game_date DESC) as game_num
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE player_lookup = @player_lookup
              AND game_date < @game_date
              AND season_year = CASE
                  WHEN EXTRACT(MONTH FROM @game_date) >= 10 THEN EXTRACT(YEAR FROM @game_date)
                  ELSE EXTRACT(YEAR FROM @game_date) - 1
              END
        )
        SELECT
            ROUND(AVG(CASE WHEN game_num <= 5 THEN points END), 1) as l5,
            ROUND(AVG(CASE WHEN game_num <= 10 THEN points END), 1) as l10,
            ROUND(AVG(CASE WHEN game_num <= 20 THEN points END), 1) as l20,
            ROUND(AVG(points), 1) as season
        FROM recent_games
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
        ]

        results = self.query_to_list(query, params)
        if not results:
            return {}

        r = results[0]
        return {
            'l5': safe_float(r.get('l5')),
            'l10': safe_float(r.get('l10')),
            'l20': safe_float(r.get('l20')),
            'season': safe_float(r.get('season')),
        }

    def _query_prediction(self, player_lookup: str, game_date: str) -> Optional[Dict]:
        """Query prediction and result for this game."""
        query = """
        SELECT
            line_value as line,
            predicted_points as predicted,
            confidence_score as confidence,
            recommendation,
            prediction_correct as correct
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
          AND system_id = @champion_model_id
        LIMIT 1
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
            bigquery.ScalarQueryParameter('champion_model_id', 'STRING', get_champion_model_id()),
        ]

        results = self.query_to_list(query, params)
        return results[0] if results else None

    def _query_recent_games(self, player_lookup: str, game_date: str, limit: int = 5) -> List[Dict]:
        """Query recent games before this date."""
        query = """
        SELECT
            game_date,
            opponent_team_abbr as opponent,
            points,
            points_line as line,
            over_under_result as result,
            minutes_played
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE player_lookup = @player_lookup
          AND game_date < @game_date
        ORDER BY game_date DESC
        LIMIT @limit
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
            bigquery.ScalarQueryParameter('limit', 'INT64', limit),
        ]

        results = self.query_to_list(query, params)
        return [
            {
                'date': str(r['game_date']),
                'opponent': r['opponent'],
                'points': r['points'],
                'line': safe_float(r.get('line')),
                'result': r.get('result'),
                'minutes': safe_float(r.get('minutes_played')),
            }
            for r in results
        ]

    def _query_head_to_head(self, player_lookup: str, opponent: str, game_date: str) -> Dict[str, Any]:
        """Query head-to-head history vs opponent."""
        if not opponent:
            return {}

        query = """
        SELECT
            COUNT(*) as games,
            ROUND(AVG(points), 1) as avg_points,
            ROUND(AVG(points_line), 1) as avg_line,
            SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) as overs,
            SUM(CASE WHEN over_under_result = 'UNDER' THEN 1 ELSE 0 END) as unders
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE player_lookup = @player_lookup
          AND opponent_team_abbr = @opponent
          AND game_date < @game_date
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('opponent', 'STRING', opponent),
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
        ]

        results = self.query_to_list(query, params)
        if not results or results[0]['games'] == 0:
            return {'games': 0}

        r = results[0]
        total = r['overs'] + r['unders']
        return {
            'games': r['games'],
            'avg_points': safe_float(r.get('avg_points')),
            'avg_line': safe_float(r.get('avg_line')),
            'over_rate': round(r['overs'] / total, 2) if total > 0 else None,
        }

    def _build_prediction_angles(
        self,
        profile: Dict,
        moving_avgs: Dict,
        opponent_context: Dict,
        game: Dict,
        recent_games: List[Dict]
    ) -> Dict[str, List[str]]:
        """Build supporting and opposing prediction angles."""
        supporting = []
        against = []

        # Check hot/cold streak
        if recent_games:
            over_count = sum(1 for g in recent_games if g.get('result') == 'OVER')
            under_count = sum(1 for g in recent_games if g.get('result') == 'UNDER')
            if over_count >= 3:
                supporting.append(f"Hot streak ({over_count}G OVER)")
            elif under_count >= 3:
                against.append(f"Cold streak ({under_count}G UNDER)")

        # Check defense matchup
        shot_profile = profile.get('shot_profile', 'balanced')
        if shot_profile == 'perimeter' and opponent_context.get('opp_perimeter_defense') == 'weak':
            supporting.append("Weak perimeter defense")
        elif shot_profile == 'perimeter' and opponent_context.get('opp_perimeter_defense') == 'strong':
            against.append("Strong perimeter defense")
        elif shot_profile == 'interior' and opponent_context.get('opp_paint_defense') == 'weak':
            supporting.append("Weak paint defense")
        elif shot_profile == 'interior' and opponent_context.get('opp_paint_defense') == 'strong':
            against.append("Strong paint defense")

        # Check recent form vs averages
        l5 = moving_avgs.get('l5')
        season = moving_avgs.get('season')
        if l5 and season:
            diff_pct = (l5 - season) / season if season > 0 else 0
            if diff_pct >= 0.15:
                supporting.append(f"Trending up (+{round(diff_pct*100)}% L5)")
            elif diff_pct <= -0.15:
                against.append(f"Trending down ({round(diff_pct*100)}% L5)")

        # Check pace advantage
        opp_pace = opponent_context.get('opp_pace')
        if opp_pace:
            if opp_pace >= 102:
                supporting.append("Fast-paced opponent")
            elif opp_pace <= 96:
                against.append("Slow-paced opponent")

        return {
            'supporting': supporting[:3],  # Max 3 angles each
            'against': against[:3],
        }

    def _empty_response(self, player_lookup: str, game_date: str, reason: str) -> Dict[str, Any]:
        """Return empty response when no data available."""
        return {
            'player_lookup': player_lookup,
            'game_date': game_date,
            'generated_at': self.get_generated_at(),
            'error': reason,
            'player_profile': None,
            'opponent_context': None,
            'moving_averages': None,
            'prop_line': None,
            'prediction_angles': {'supporting': [], 'against': []},
            'recent_games': [],
            'head_to_head': None,
            'result': None,
        }

    def export(self, player_lookup: str, game_date: str) -> str:
        """
        Generate and upload game report JSON.

        Args:
            player_lookup: Player identifier
            game_date: Date string in YYYY-MM-DD format

        Returns:
            GCS path of the exported file
        """
        logger.info(f"Exporting game report for {player_lookup} on {game_date}")

        json_data = self.generate_json(player_lookup, game_date)

        # Upload to GCS
        path = f'players/{player_lookup}/game-report/{game_date}.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=86400')  # 1 day cache

        logger.info(f"Exported game report to {gcs_path}")
        return gcs_path
