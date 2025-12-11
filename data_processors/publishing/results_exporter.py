"""
Results Exporter for Phase 6 Publishing

Exports daily prediction results to JSON for the website.
Shows how predictions compared to actual outcomes.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date

from google.cloud import bigquery

from .base_exporter import BaseExporter

logger = logging.getLogger(__name__)


class ResultsExporter(BaseExporter):
    """
    Export daily prediction results to JSON.

    Output files:
    - results/{date}.json - Results for a specific date
    - results/latest.json - Most recent results (symlink-like behavior)

    JSON structure:
    {
        "game_date": "2021-11-10",
        "generated_at": "2025-12-10T...",
        "summary": {
            "total_predictions": 156,
            "recommendations": 95,
            "correct": 87,
            "win_rate": 0.916,
            "avg_mae": 4.28,
            "avg_bias": -1.2
        },
        "results": [...],
        "highlights": {...}
    }
    """

    def generate_json(self, target_date: str) -> Dict[str, Any]:
        """
        Generate results JSON for a specific date.

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            Dictionary ready for JSON serialization
        """
        # Query prediction results for ensemble system
        results = self._query_results(target_date)

        if not results:
            logger.warning(f"No results found for {target_date}")
            return self._empty_response(target_date)

        # Build summary statistics
        summary = self._build_summary(results)

        # Format individual results
        formatted_results = self._format_results(results)

        # Get highlights (best/worst predictions)
        highlights = self._get_highlights(results)

        return {
            'game_date': target_date,
            'generated_at': self.get_generated_at(),
            'summary': summary,
            'results': formatted_results,
            'highlights': highlights
        }

    def _query_results(self, target_date: str) -> List[Dict]:
        """Query prediction_accuracy for ensemble results on a date."""
        query = """
        SELECT
            player_lookup,
            game_id,
            team_abbr,
            opponent_team_abbr,
            predicted_points,
            actual_points,
            line_value,
            recommendation,
            prediction_correct,
            absolute_error,
            signed_error,
            confidence_score,
            within_3_points,
            within_5_points,
            minutes_played
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE game_date = @target_date
          AND system_id = 'ensemble_v1'
        ORDER BY game_id, player_lookup
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date)
        ]

        return self.query_to_list(query, params)

    def _build_summary(self, results: List[Dict]) -> Dict[str, Any]:
        """Build summary statistics from results."""
        total = len(results)

        # Count recommendations (OVER/UNDER, not PASS)
        recommendations = [r for r in results if r['recommendation'] in ('OVER', 'UNDER')]
        rec_count = len(recommendations)

        # Count correct/incorrect
        correct = sum(1 for r in recommendations if r['prediction_correct'])
        incorrect = rec_count - correct

        # Calculate averages
        errors = [float(r['absolute_error']) for r in results if r['absolute_error'] is not None]
        signed_errors = [float(r['signed_error']) for r in results if r['signed_error'] is not None]

        avg_mae = round(sum(errors) / len(errors), 2) if errors else 0
        avg_bias = round(sum(signed_errors) / len(signed_errors), 2) if signed_errors else 0

        # Threshold accuracy
        within_3 = sum(1 for r in results if r['within_3_points'])
        within_5 = sum(1 for r in results if r['within_5_points'])

        # PASS count
        pass_count = sum(1 for r in results if r['recommendation'] == 'PASS')

        return {
            'total_predictions': total,
            'recommendations': rec_count,
            'correct': correct,
            'incorrect': incorrect,
            'pass_count': pass_count,
            'win_rate': round(correct / rec_count, 3) if rec_count > 0 else 0,
            'avg_mae': avg_mae,
            'avg_bias': avg_bias,
            'within_3_points': within_3,
            'within_3_pct': round(within_3 / total, 3) if total > 0 else 0,
            'within_5_points': within_5,
            'within_5_pct': round(within_5 / total, 3) if total > 0 else 0
        }

    def _format_results(self, results: List[Dict]) -> List[Dict[str, Any]]:
        """Format individual results for JSON output."""
        formatted = []

        for r in results:
            # Determine result status
            if r['recommendation'] == 'PASS':
                result_status = 'PASS'
            elif r['prediction_correct'] is True:
                result_status = 'WIN'
            elif r['prediction_correct'] is False:
                result_status = 'LOSS'
            else:
                result_status = 'PUSH'  # Exactly hit the line

            formatted.append({
                'player_lookup': r['player_lookup'],
                'game_id': r['game_id'],
                'team': r['team_abbr'],
                'opponent': r['opponent_team_abbr'],
                'predicted': float(r['predicted_points']) if r['predicted_points'] else None,
                'actual': r['actual_points'],
                'line': float(r['line_value']) if r['line_value'] else None,
                'recommendation': r['recommendation'],
                'result': result_status,
                'error': float(r['absolute_error']) if r['absolute_error'] else None,
                'bias': float(r['signed_error']) if r['signed_error'] else None,
                'confidence': float(r['confidence_score']) if r['confidence_score'] else None,
                'minutes': float(r['minutes_played']) if r['minutes_played'] else None
            })

        return formatted

    def _get_highlights(self, results: List[Dict]) -> Dict[str, Any]:
        """Get best and worst predictions for highlights."""
        if not results:
            return {}

        # Filter to results with errors
        with_errors = [r for r in results if r['absolute_error'] is not None]
        if not with_errors:
            return {}

        # Best prediction (smallest error)
        best = min(with_errors, key=lambda r: float(r['absolute_error']))

        # Worst prediction (largest error)
        worst = max(with_errors, key=lambda r: float(r['absolute_error']))

        return {
            'best_prediction': {
                'player': best['player_lookup'],
                'team': best['team_abbr'],
                'predicted': float(best['predicted_points']),
                'actual': best['actual_points'],
                'error': float(best['absolute_error'])
            },
            'worst_prediction': {
                'player': worst['player_lookup'],
                'team': worst['team_abbr'],
                'predicted': float(worst['predicted_points']),
                'actual': worst['actual_points'],
                'error': float(worst['absolute_error']),
                'minutes': float(worst['minutes_played']) if worst['minutes_played'] else None
            }
        }

    def _empty_response(self, target_date: str) -> Dict[str, Any]:
        """Return empty response for dates with no data."""
        return {
            'game_date': target_date,
            'generated_at': self.get_generated_at(),
            'summary': {
                'total_predictions': 0,
                'recommendations': 0,
                'correct': 0,
                'incorrect': 0,
                'pass_count': 0,
                'win_rate': 0,
                'avg_mae': 0,
                'avg_bias': 0,
                'within_3_points': 0,
                'within_3_pct': 0,
                'within_5_points': 0,
                'within_5_pct': 0
            },
            'results': [],
            'highlights': {}
        }

    def export(self, target_date: str, update_latest: bool = True) -> str:
        """
        Generate and upload results JSON.

        Args:
            target_date: Date string in YYYY-MM-DD format
            update_latest: Whether to also update latest.json

        Returns:
            GCS path of the exported file
        """
        logger.info(f"Exporting results for {target_date}")

        json_data = self.generate_json(target_date)

        # Upload date-specific file (cache for 1 day since historical)
        path = f'results/{target_date}.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=86400')

        # Optionally update latest.json (shorter cache)
        if update_latest:
            self.upload_to_gcs(json_data, 'results/latest.json', 'public, max-age=300')
            logger.info("Updated results/latest.json")

        return gcs_path
