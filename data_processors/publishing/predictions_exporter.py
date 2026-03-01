"""
Predictions Exporter for Phase 6 Publishing

Exports today's predictions (pre-game) grouped by game.
Used for the main predictions page on the website.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date
from collections import defaultdict

from google.cloud import bigquery

from .base_exporter import BaseExporter
from .exporter_utils import safe_float, calculate_edge, get_generated_at

logger = logging.getLogger(__name__)


class PredictionsExporter(BaseExporter):
    """
    Export daily predictions to JSON, grouped by game.

    Output files:
    - predictions/{date}.json - Predictions for a specific date
    - predictions/today.json - Today's predictions

    This exports from player_prop_predictions (Phase 5A output),
    NOT prediction_accuracy (which has post-game actuals).

    JSON structure:
    {
        "game_date": "2021-11-10",
        "generated_at": "2025-12-10T...",
        "total_games": 8,
        "total_predictions": 156,
        "games": [
            {
                "game_id": "20211110_BKN_ORL",
                "home_team": "ORL",
                "away_team": "BKN",
                "predictions": [...]
            }
        ]
    }
    """

    def generate_json(self, target_date: str) -> Dict[str, Any]:
        """
        Generate predictions JSON for a specific date.

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            Dictionary ready for JSON serialization
        """
        # Query predictions (ensemble only for display)
        predictions = self._query_predictions(target_date)

        if not predictions:
            logger.warning(f"No predictions found for {target_date}")
            return self._empty_response(target_date)

        # Group by game
        games = self._group_by_game(predictions)

        return {
            'game_date': target_date,
            'generated_at': self.get_generated_at(),
            'total_games': len(games),
            'total_predictions': len(predictions),
            'games': games
        }

    def _query_predictions(self, target_date: str) -> List[Dict]:
        """Query predictions from player_prop_predictions table."""
        query = """
        SELECT
            p.player_lookup,
            p.game_id,
            p.game_date,
            p.predicted_points,
            p.confidence_score,
            p.recommendation,
            p.current_points_line as line_value,
            p.pace_adjustment,
            p.similar_games_count,

            -- Try to get team info from prediction_accuracy if available
            pa.team_abbr,
            pa.opponent_team_abbr

        FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
        LEFT JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
            ON p.player_lookup = pa.player_lookup
            AND p.game_id = pa.game_id
            AND p.game_date = pa.game_date
            AND pa.system_id = 'catboost_v12'
        WHERE p.game_date = @target_date
          AND p.system_id = 'catboost_v12'
        ORDER BY p.game_id, p.confidence_score DESC
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date)
        ]

        return self.query_to_list(query, params)

    def _group_by_game(self, predictions: List[Dict]) -> List[Dict[str, Any]]:
        """Group predictions by game_id."""
        games_dict = defaultdict(list)

        for pred in predictions:
            game_id = pred['game_id']
            games_dict[game_id].append(pred)

        # Convert to list of game objects
        games = []
        for game_id, preds in games_dict.items():
            # Extract teams from game_id (format: YYYYMMDD_AWAY_HOME)
            parts = game_id.split('_')
            if len(parts) >= 3:
                away_team = parts[1]
                home_team = parts[2]
            else:
                away_team = preds[0].get('opponent_team_abbr') or 'UNK'
                home_team = preds[0].get('team_abbr') or 'UNK'

            # Format predictions for this game
            formatted_preds = []
            for pred in preds:
                # Determine which team the player is on
                player_team = pred.get('team_abbr')
                is_home = player_team == home_team if player_team else None

                formatted_preds.append({
                    'player_lookup': pred['player_lookup'],
                    'team': player_team,
                    'is_home': is_home,
                    'prediction': {
                        'points': safe_float(pred['predicted_points']),
                        'confidence': safe_float(pred['confidence_score']),
                        'recommendation': pred['recommendation'],
                        'line': safe_float(pred['line_value']),
                        'edge': calculate_edge(pred.get('predicted_points'), pred.get('line_value'))
                    },
                    'context': {
                        'pace_adjustment': safe_float(pred['pace_adjustment']),
                        'similar_games': pred.get('similar_games_count')
                    }
                })

            # Sort by confidence descending
            formatted_preds.sort(key=lambda x: x['prediction']['confidence'] or 0, reverse=True)

            # Count recommendations
            over_count = sum(1 for p in formatted_preds if p['prediction']['recommendation'] == 'OVER')
            under_count = sum(1 for p in formatted_preds if p['prediction']['recommendation'] == 'UNDER')
            pass_count = sum(1 for p in formatted_preds if p['prediction']['recommendation'] == 'PASS')

            games.append({
                'game_id': game_id,
                'home_team': home_team,
                'away_team': away_team,
                'prediction_count': len(formatted_preds),
                'recommendation_breakdown': {
                    'over': over_count,
                    'under': under_count,
                    'pass': pass_count
                },
                'predictions': formatted_preds
            })

        # Sort games by game_id (which starts with date)
        games.sort(key=lambda g: g['game_id'])

        return games

    def _empty_response(self, target_date: str) -> Dict[str, Any]:
        """Return empty response when no data available."""
        return {
            'game_date': target_date,
            'generated_at': self.get_generated_at(),
            'total_games': 0,
            'total_predictions': 0,
            'games': []
        }

    def export(self, target_date: str, update_today: bool = False) -> str:
        """
        Generate and upload predictions JSON.

        Args:
            target_date: Date string in YYYY-MM-DD format
            update_today: Whether to also update today.json

        Returns:
            GCS path of the exported file
        """
        logger.info(f"Exporting predictions for {target_date}")

        json_data = self.generate_json(target_date)

        # Upload date-specific file
        path = f'predictions/{target_date}.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=3600')

        # Optionally update today.json
        if update_today:
            self.upload_to_gcs(json_data, 'predictions/today.json', 'public, max-age=300')
            logger.info("Updated predictions/today.json")

        return gcs_path
