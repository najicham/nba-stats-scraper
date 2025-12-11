"""
Player Profile Exporter for Phase 6 Publishing

Exports player accuracy profiles showing how well we predict each player.
Used for player detail pages on the website.
"""

import logging
from typing import Dict, List, Any, Optional

from google.cloud import bigquery

from .base_exporter import BaseExporter

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
                'team': p.get('team_abbr'),
                'games_predicted': p['games_predicted'],
                'recommendations': p['recommendations'],
                'mae': self._safe_float(p['mae']),
                'win_rate': self._safe_float(p['win_rate']),
                'bias': self._safe_float(p['bias']),
                'within_5_pct': self._safe_float(p['within_5_pct'])
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

        # Get recent predictions
        recent = self._query_recent_predictions(player_lookup, limit=20)

        # Get breakdown by recommendation type
        by_rec = self._query_by_recommendation(player_lookup)

        return {
            'player_lookup': player_lookup,
            'generated_at': self.get_generated_at(),
            'summary': {
                'team': summary.get('team_abbr'),
                'games_predicted': summary['games_predicted'],
                'total_recommendations': summary['recommendations'],
                'correct': summary['correct'],
                'mae': self._safe_float(summary['mae']),
                'win_rate': self._safe_float(summary['win_rate']),
                'bias': self._safe_float(summary['bias']),
                'avg_confidence': self._safe_float(summary['avg_confidence']),
                'within_3_pct': self._safe_float(summary['within_3_pct']),
                'within_5_pct': self._safe_float(summary['within_5_pct']),
                'date_range': {
                    'first': str(summary['first_date']) if summary.get('first_date') else None,
                    'last': str(summary['last_date']) if summary.get('last_date') else None
                }
            },
            'interpretation': self._build_interpretation(summary),
            'recent_predictions': self._format_recent_predictions(recent),
            'by_recommendation': by_rec
        }

    def _query_player_summaries(self) -> List[Dict]:
        """Query summary stats for all players."""
        query = """
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
        WHERE system_id = 'ensemble_v1'
        GROUP BY player_lookup
        HAVING games_predicted >= 3
        ORDER BY games_predicted DESC
        """
        return self.query_to_list(query)

    def _query_player_summary(self, player_lookup: str) -> Optional[Dict]:
        """Query detailed summary for a single player."""
        query = """
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
        WHERE system_id = 'ensemble_v1'
          AND player_lookup = @player_lookup
        GROUP BY player_lookup
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
        WHERE system_id = 'ensemble_v1'
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
        WHERE system_id = 'ensemble_v1'
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
                'win_rate': self._safe_float(r['win_rate']),
                'mae': self._safe_float(r['mae'])
            }
        return breakdown

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
                'predicted': self._safe_float(r['predicted_points']),
                'actual': r['actual_points'],
                'line': self._safe_float(r['line_value']),
                'recommendation': r['recommendation'],
                'result': result,
                'error': self._safe_float(r['absolute_error']),
                'confidence': self._safe_float(r['confidence_score'])
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

    def _empty_player_response(self, player_lookup: str) -> Dict[str, Any]:
        """Return empty response for unknown player."""
        return {
            'player_lookup': player_lookup,
            'generated_at': self.get_generated_at(),
            'summary': None,
            'interpretation': {'error': 'No prediction data found for this player'},
            'recent_predictions': [],
            'by_recommendation': {}
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
