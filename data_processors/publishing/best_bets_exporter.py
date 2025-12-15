"""
Best Bets Exporter for Phase 6 Publishing

Exports top prediction picks ranked by composite score.
Combines confidence, edge, and system agreement for ranking.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date

from google.cloud import bigquery

from .base_exporter import BaseExporter

logger = logging.getLogger(__name__)


class BestBetsExporter(BaseExporter):
    """
    Export best bets (top picks) to JSON.

    Output files:
    - best-bets/{date}.json - Best bets for a specific date
    - best-bets/latest.json - Most recent best bets

    Ranking methodology:
    1. Filter to actionable recommendations (OVER/UNDER only)
    2. Compute composite score = confidence * edge_factor * agreement_factor
    3. Rank by composite score descending
    4. Return top N picks

    JSON structure:
    {
        "game_date": "2021-11-10",
        "generated_at": "2025-12-10T...",
        "methodology": "...",
        "picks": [
            {
                "rank": 1,
                "player_lookup": "stephen_curry",
                "recommendation": "OVER",
                "line": 26.5,
                "predicted": 29.8,
                "edge": 3.3,
                "confidence": 0.82,
                "composite_score": 0.91,
                ...
            }
        ]
    }
    """

    DEFAULT_TOP_N = 15

    def generate_json(self, target_date: str, top_n: int = None) -> Dict[str, Any]:
        """
        Generate best bets JSON for a specific date.

        Args:
            target_date: Date string in YYYY-MM-DD format
            top_n: Number of top picks to include (default 15)

        Returns:
            Dictionary ready for JSON serialization
        """
        if top_n is None:
            top_n = self.DEFAULT_TOP_N

        # Query predictions with ranking data
        picks = self._query_ranked_predictions(target_date, top_n)

        if not picks:
            logger.warning(f"No best bets found for {target_date}")
            return self._empty_response(target_date)

        # Format picks
        formatted_picks = self._format_picks(picks)

        return {
            'game_date': target_date,
            'generated_at': self.get_generated_at(),
            'methodology': 'Ranked by composite score: confidence * edge_factor * historical_accuracy',
            'total_picks': len(formatted_picks),
            'picks': formatted_picks
        }

    def _query_ranked_predictions(self, target_date: str, top_n: int) -> List[Dict]:
        """
        Query predictions ranked by composite score.

        Composite score formula:
        - Base: confidence_score (0-1)
        - Edge factor: 1 + (edge / 10), capped at 1.5
        - Historical factor: Player's historical accuracy
        """
        query = """
        WITH player_history AS (
            -- Pre-compute player historical accuracy
            SELECT
                player_lookup,
                COUNT(*) as sample_size,
                ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END), 3) as historical_accuracy
            FROM `nba-props-platform.nba_predictions.prediction_accuracy`
            WHERE system_id = 'ensemble_v1'
              AND game_date < @target_date
              AND recommendation IN ('OVER', 'UNDER')
            GROUP BY player_lookup
        ),
        player_names AS (
            -- Get player full names from registry
            SELECT player_lookup, player_name
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        ),
        fatigue_data AS (
            -- Get fatigue scores for the date
            SELECT
                player_lookup,
                fatigue_score
            FROM `nba-props-platform.nba_precompute.player_composite_factors`
            WHERE game_date = @target_date
        ),
        predictions AS (
            SELECT
                p.player_lookup,
                COALESCE(pn.player_name, p.player_lookup) as player_full_name,
                p.game_id,
                p.team_abbr,
                p.opponent_team_abbr,
                p.predicted_points,
                p.actual_points,
                p.line_value,
                p.recommendation,
                p.prediction_correct,
                p.confidence_score,
                p.absolute_error,
                p.signed_error,
                ABS(p.predicted_points - p.line_value) as edge,
                h.historical_accuracy as player_historical_accuracy,
                h.sample_size as player_sample_size,
                f.fatigue_score
            FROM `nba-props-platform.nba_predictions.prediction_accuracy` p
            LEFT JOIN player_history h ON p.player_lookup = h.player_lookup
            LEFT JOIN player_names pn ON p.player_lookup = pn.player_lookup
            LEFT JOIN fatigue_data f ON p.player_lookup = f.player_lookup
            WHERE p.game_date = @target_date
              AND p.system_id = 'ensemble_v1'
              AND p.recommendation IN ('OVER', 'UNDER')
        ),
        scored AS (
            SELECT
                *,
                -- Edge factor: 1 + edge/10, capped at 1.5
                LEAST(1.5, 1.0 + edge / 10.0) as edge_factor,
                -- Historical factor: use player accuracy if available, else 0.85
                COALESCE(player_historical_accuracy, 0.85) as hist_factor,
                -- Composite score
                confidence_score
                    * LEAST(1.5, 1.0 + edge / 10.0)
                    * COALESCE(player_historical_accuracy, 0.85) as composite_score
            FROM predictions
        )
        SELECT *
        FROM scored
        ORDER BY composite_score DESC
        LIMIT @top_n
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('top_n', 'INT64', top_n)
        ]

        return self.query_to_list(query, params)

    def _format_picks(self, picks: List[Dict]) -> List[Dict[str, Any]]:
        """Format picks for JSON output."""
        formatted = []

        for rank, pick in enumerate(picks, 1):
            # Determine result if we have actual data
            if pick['actual_points'] is not None:
                if pick['prediction_correct'] is True:
                    result = 'WIN'
                elif pick['prediction_correct'] is False:
                    result = 'LOSS'
                else:
                    result = 'PUSH'
            else:
                result = 'PENDING'

            # Build rationale
            rationale = self._build_rationale(pick)

            # Compute fatigue level from score
            fatigue_score = pick.get('fatigue_score')
            if fatigue_score is not None:
                if fatigue_score >= 95:
                    fatigue_level = 'fresh'
                elif fatigue_score >= 75:
                    fatigue_level = 'normal'
                else:
                    fatigue_level = 'tired'
            else:
                fatigue_level = None

            formatted.append({
                'rank': rank,
                'player_lookup': pick['player_lookup'],
                'player_full_name': pick.get('player_full_name', pick['player_lookup']),
                'game_id': pick['game_id'],
                'team': pick['team_abbr'],
                'opponent': pick['opponent_team_abbr'],
                'recommendation': pick['recommendation'],
                'line': self._safe_float(pick['line_value']),
                'predicted': self._safe_float(pick['predicted_points']),
                'edge': self._safe_float(pick['edge']),
                'confidence': self._safe_float(pick['confidence_score']),
                'composite_score': round(self._safe_float(pick['composite_score']) or 0, 3),
                'player_historical_accuracy': self._safe_float(pick['player_historical_accuracy']),
                'player_sample_size': pick['player_sample_size'],
                'fatigue_score': self._safe_float(fatigue_score),
                'fatigue_level': fatigue_level,
                'rationale': rationale,
                'result': result,
                'actual': pick['actual_points'],
                'error': self._safe_float(pick['absolute_error'])
            })

        return formatted

    def _build_rationale(self, pick: Dict) -> List[str]:
        """Build human-readable rationale for the pick."""
        rationale = []

        # Confidence
        conf = pick.get('confidence_score')
        if conf and conf >= 0.80:
            rationale.append(f"High confidence ({conf:.0%})")
        elif conf and conf >= 0.70:
            rationale.append(f"Good confidence ({conf:.0%})")

        # Edge
        edge = pick.get('edge')
        if edge and edge >= 4.0:
            rationale.append(f"Strong edge ({edge:.1f} points)")
        elif edge and edge >= 2.5:
            rationale.append(f"Solid edge ({edge:.1f} points)")

        # Historical accuracy
        hist = pick.get('player_historical_accuracy')
        sample = pick.get('player_sample_size', 0)
        if hist and sample >= 5:
            if hist >= 0.80:
                rationale.append(f"Strong track record ({hist:.0%} accuracy, {sample} games)")
            elif hist >= 0.70:
                rationale.append(f"Good track record ({hist:.0%} accuracy, {sample} games)")

        # Fatigue factor
        fatigue = pick.get('fatigue_score')
        if fatigue is not None:
            if fatigue >= 95:
                rationale.append(f"Well-rested (fatigue: {fatigue:.0f})")
            elif fatigue < 75:
                rationale.append(f"Elevated fatigue (fatigue: {fatigue:.0f})")

        # If no rationale, add generic
        if not rationale:
            rationale.append("Meets minimum criteria")

        return rationale

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

    def _empty_response(self, target_date: str) -> Dict[str, Any]:
        """Return empty response when no data available."""
        return {
            'game_date': target_date,
            'generated_at': self.get_generated_at(),
            'methodology': 'Ranked by composite score: confidence * edge_factor * historical_accuracy',
            'total_picks': 0,
            'picks': []
        }

    def export(self, target_date: str, top_n: int = None, update_latest: bool = True) -> str:
        """
        Generate and upload best bets JSON.

        Args:
            target_date: Date string in YYYY-MM-DD format
            top_n: Number of top picks (default 15)
            update_latest: Whether to also update latest.json

        Returns:
            GCS path of the exported file
        """
        logger.info(f"Exporting best bets for {target_date}")

        json_data = self.generate_json(target_date, top_n)

        # Upload date-specific file
        path = f'best-bets/{target_date}.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=86400')

        # Optionally update latest.json
        if update_latest:
            self.upload_to_gcs(json_data, 'best-bets/latest.json', 'public, max-age=300')
            logger.info("Updated best-bets/latest.json")

        return gcs_path
