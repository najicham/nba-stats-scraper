"""
Results Exporter for Phase 6 Publishing

Exports daily prediction results to JSON for the website.
Shows how predictions compared to actual outcomes.

Enhanced fields (December 2025):
- confidence_tier: high/medium/low based on confidence_score
- player_tier: elite/starter/role_player based on season PPG
- Context fields: is_home, is_back_to_back, days_rest
- Breakdowns: aggregated stats by tier, confidence, recommendation, context
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date

from google.cloud import bigquery

from .base_exporter import BaseExporter
from .exporter_utils import safe_float, get_generated_at

logger = logging.getLogger(__name__)


# Tier thresholds
CONFIDENCE_THRESHOLDS = {
    'high': 0.70,
    'medium': 0.55,
}

PLAYER_TIER_THRESHOLDS = {
    'elite': 25.0,      # 25+ PPG
    'starter': 15.0,    # 15-25 PPG
}


def get_confidence_tier(confidence_score: Optional[float]) -> str:
    """
    Bucket confidence score into tiers.

    Args:
        confidence_score: 0.0 to 1.0 confidence value

    Returns:
        'high', 'medium', or 'low'
    """
    if confidence_score is None:
        return 'low'
    if confidence_score >= CONFIDENCE_THRESHOLDS['high']:
        return 'high'
    elif confidence_score >= CONFIDENCE_THRESHOLDS['medium']:
        return 'medium'
    else:
        return 'low'


def get_player_tier(season_ppg: Optional[float]) -> str:
    """
    Classify player tier based on season PPG.

    Args:
        season_ppg: Player's season scoring average

    Returns:
        'elite', 'starter', or 'role_player'
    """
    if season_ppg is None:
        return 'role_player'
    if season_ppg >= PLAYER_TIER_THRESHOLDS['elite']:
        return 'elite'
    elif season_ppg >= PLAYER_TIER_THRESHOLDS['starter']:
        return 'starter'
    else:
        return 'role_player'


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

        # Format individual results (with tier and context fields)
        formatted_results = self._format_results(results)

        # Get highlights (best/worst predictions)
        highlights = self._get_highlights(results)

        # Compute breakdowns by tier, confidence, recommendation, context
        breakdowns = self._compute_breakdowns(formatted_results)

        return {
            'game_date': target_date,
            'generated_at': self.get_generated_at(),
            'summary': summary,
            'breakdowns': breakdowns,
            'results': formatted_results,
            'highlights': highlights
        }

    def _query_results(self, target_date: str) -> List[Dict]:
        """
        Query prediction_accuracy for ensemble results on a date.

        Joins with ml_feature_store_v2 to get:
        - is_home: whether player's team is home
        - days_rest: days since player's team last played
        - points_avg_season: for player_tier classification
        - back_to_back: from features array (index 16)
        """
        query = """
        WITH feature_data AS (
            SELECT
                player_lookup,
                game_id,
                is_home,
                days_rest,
                -- Extract points_avg_season from features array (index 2)
                SAFE_CAST(features[OFFSET(2)] AS FLOAT64) as points_avg_season,
                -- Extract back_to_back from features array (index 16)
                CASE WHEN features[OFFSET(16)] > 0.5 THEN TRUE ELSE FALSE END as is_back_to_back
            FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
            WHERE game_date = @target_date
        )
        SELECT
            pa.player_lookup,
            pa.game_id,
            pa.team_abbr,
            pa.opponent_team_abbr,
            pa.predicted_points,
            pa.actual_points,
            pa.line_value,
            pa.recommendation,
            pa.prediction_correct,
            pa.absolute_error,
            pa.signed_error,
            pa.confidence_score,
            pa.within_3_points,
            pa.within_5_points,
            pa.minutes_played,
            -- Context fields from feature store
            COALESCE(fd.is_home, FALSE) as is_home,
            COALESCE(fd.days_rest, 1) as days_rest,
            COALESCE(fd.is_back_to_back, FALSE) as is_back_to_back,
            fd.points_avg_season
        FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
        LEFT JOIN feature_data fd
            ON pa.player_lookup = fd.player_lookup
            AND pa.game_id = fd.game_id
        WHERE pa.game_date = @target_date
          AND pa.system_id = 'catboost_v9'
        ORDER BY pa.game_id, pa.player_lookup
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
        errors = [safe_float(r['absolute_error']) for r in results if r['absolute_error'] is not None]
        errors = [e for e in errors if e is not None]
        signed_errors = [safe_float(r['signed_error']) for r in results if r['signed_error'] is not None]
        signed_errors = [e for e in signed_errors if e is not None]

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
        """Format individual results for JSON output with tier and context fields."""
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

            # Calculate tiers
            confidence_score = safe_float(r['confidence_score'])
            season_ppg = safe_float(r.get('points_avg_season'))

            formatted.append({
                'player_lookup': r['player_lookup'],
                'game_id': r['game_id'],
                'team': r['team_abbr'],
                'opponent': r['opponent_team_abbr'],
                'predicted': safe_float(r['predicted_points']),
                'actual': r['actual_points'],
                'line': safe_float(r['line_value']),
                'recommendation': r['recommendation'],
                'result': result_status,
                'error': safe_float(r['absolute_error']),
                'bias': safe_float(r['signed_error']),
                'confidence': confidence_score,
                'minutes': safe_float(r['minutes_played']),
                # NEW: Tier fields
                'confidence_tier': get_confidence_tier(confidence_score),
                'player_tier': get_player_tier(season_ppg),
                # NEW: Context fields
                'is_home': r.get('is_home', False),
                'is_back_to_back': r.get('is_back_to_back', False),
                'days_rest': r.get('days_rest', 1),
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
        best = min(with_errors, key=lambda r: safe_float(r['absolute_error'], default=float('inf')))

        # Worst prediction (largest error)
        worst = max(with_errors, key=lambda r: safe_float(r['absolute_error'], default=0))

        return {
            'best_prediction': {
                'player': best['player_lookup'],
                'team': best['team_abbr'],
                'predicted': safe_float(best['predicted_points']),
                'actual': best['actual_points'],
                'error': safe_float(best['absolute_error'])
            },
            'worst_prediction': {
                'player': worst['player_lookup'],
                'team': worst['team_abbr'],
                'predicted': safe_float(worst['predicted_points']),
                'actual': worst['actual_points'],
                'error': safe_float(worst['absolute_error']),
                'minutes': safe_float(worst['minutes_played'])
            }
        }

    def _compute_breakdowns(self, formatted_results: List[Dict]) -> Dict[str, Any]:
        """
        Compute aggregated breakdown stats by tier, confidence, recommendation, and context.

        Args:
            formatted_results: List of formatted result dicts (with tier and context fields)

        Returns:
            Dictionary with breakdown stats for each category
        """
        def compute_stats(results_subset: List[Dict]) -> Dict[str, Any]:
            """Compute stats for a subset of results."""
            total = len(results_subset)
            if total == 0:
                return {
                    'total': 0,
                    'wins': 0,
                    'losses': 0,
                    'pushes': 0,
                    'win_rate': 0,
                    'avg_error': 0,
                }

            # Only count recommendations (OVER/UNDER, not PASS)
            recs = [r for r in results_subset if r['recommendation'] in ('OVER', 'UNDER')]
            wins = sum(1 for r in recs if r['result'] == 'WIN')
            losses = sum(1 for r in recs if r['result'] == 'LOSS')
            pushes = sum(1 for r in recs if r['result'] == 'PUSH')

            errors = [r['error'] for r in results_subset if r['error'] is not None]
            avg_error = round(sum(errors) / len(errors), 2) if errors else 0

            rec_count = len(recs)
            return {
                'total': total,
                'wins': wins,
                'losses': losses,
                'pushes': pushes,
                'win_rate': round(wins / rec_count, 3) if rec_count > 0 else 0,
                'avg_error': avg_error,
            }

        # Filter to non-PASS recommendations for meaningful breakdowns
        recs_only = [r for r in formatted_results if r['recommendation'] in ('OVER', 'UNDER')]

        return {
            'by_player_tier': {
                'elite': compute_stats([r for r in recs_only if r['player_tier'] == 'elite']),
                'starter': compute_stats([r for r in recs_only if r['player_tier'] == 'starter']),
                'role_player': compute_stats([r for r in recs_only if r['player_tier'] == 'role_player']),
            },
            'by_confidence': {
                'high': compute_stats([r for r in recs_only if r['confidence_tier'] == 'high']),
                'medium': compute_stats([r for r in recs_only if r['confidence_tier'] == 'medium']),
                'low': compute_stats([r for r in recs_only if r['confidence_tier'] == 'low']),
            },
            'by_recommendation': {
                'over': compute_stats([r for r in recs_only if r['recommendation'] == 'OVER']),
                'under': compute_stats([r for r in recs_only if r['recommendation'] == 'UNDER']),
            },
            'by_context': {
                'home': compute_stats([r for r in recs_only if r['is_home']]),
                'away': compute_stats([r for r in recs_only if not r['is_home']]),
                'back_to_back': compute_stats([r for r in recs_only if r['is_back_to_back']]),
                'rested': compute_stats([r for r in recs_only if r['days_rest'] >= 2]),
            },
        }

    def _empty_response(self, target_date: str) -> Dict[str, Any]:
        """Return empty response for dates with no data."""
        empty_stats = {
            'total': 0, 'wins': 0, 'losses': 0, 'pushes': 0, 'win_rate': 0, 'avg_error': 0
        }
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
            'breakdowns': {
                'by_player_tier': {
                    'elite': empty_stats.copy(),
                    'starter': empty_stats.copy(),
                    'role_player': empty_stats.copy(),
                },
                'by_confidence': {
                    'high': empty_stats.copy(),
                    'medium': empty_stats.copy(),
                    'low': empty_stats.copy(),
                },
                'by_recommendation': {
                    'over': empty_stats.copy(),
                    'under': empty_stats.copy(),
                },
                'by_context': {
                    'home': empty_stats.copy(),
                    'away': empty_stats.copy(),
                    'back_to_back': empty_stats.copy(),
                    'rested': empty_stats.copy(),
                },
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
