#!/usr/bin/env python3
"""
File: data_processors/publishing/mlb/mlb_predictions_exporter.py

MLB Predictions Exporter

Exports daily MLB pitcher strikeout predictions to GCS for API consumption.

Output: gs://mlb-props-platform-api/v1/mlb/predictions/{date}.json

Usage:
    exporter = MlbPredictionsExporter()
    result = exporter.export(game_date='2025-08-15')
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from data_processors.publishing.base_exporter import BaseExporter

logger = logging.getLogger(__name__)

# MLB-specific constants
MLB_BUCKET_NAME = 'nba-props-platform-api'  # Reuse same bucket with /mlb prefix
MLB_API_VERSION = 'v1'


class MlbPredictionsExporter(BaseExporter):
    """
    Exports MLB pitcher strikeout predictions.

    Schema:
    {
        "generated_at": "2025-08-15T10:00:00Z",
        "game_date": "2025-08-15",
        "predictions": [...],
        "summary": {...}
    }
    """

    def __init__(
        self,
        project_id: str = 'nba-props-platform',
        bucket_name: str = MLB_BUCKET_NAME
    ):
        super().__init__(project_id=project_id, bucket_name=bucket_name)
        logger.info("MlbPredictionsExporter initialized")

    def generate_json(self, game_date: str, **kwargs) -> Dict[str, Any]:
        """
        Generate predictions JSON for a date.

        Args:
            game_date: Date to export (YYYY-MM-DD)

        Returns:
            Dictionary ready for JSON export
        """
        logger.info(f"Generating MLB predictions export for {game_date}")

        # Query predictions
        predictions = self._get_predictions(game_date)

        # Build summary
        summary = self._build_summary(predictions)

        return {
            'generated_at': self.get_generated_at(),
            'game_date': game_date,
            'predictions': predictions,
            'summary': summary
        }

    def _get_predictions(self, game_date: str) -> List[Dict]:
        """Get predictions for a date."""
        query = f"""
        SELECT
            p.pitcher_lookup,
            p.pitcher_name,
            p.team_abbr as team,
            p.opponent_team_abbr as opponent,
            p.is_home as home_away,
            p.strikeouts_line,
            p.predicted_strikeouts,
            p.recommendation,
            p.confidence,
            p.edge,
            p.model_version,
            p.is_correct,
            p.actual_strikeouts
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts` p
        WHERE p.game_date = '{game_date}'
        ORDER BY p.confidence DESC, p.pitcher_name ASC
        """

        rows = self.query_to_list(query)

        predictions = []
        for row in rows:
            prediction = {
                'pitcher_id': row.get('pitcher_lookup'),
                'pitcher_name': row.get('pitcher_name'),
                'team': row.get('team'),
                'opponent': row.get('opponent'),
                'is_home': bool(row.get('home_away')),
                'strikeouts_line': float(row.get('strikeouts_line', 0)),
                'predicted_strikeouts': round(float(row.get('predicted_strikeouts', 0)), 1),
                'recommendation': row.get('recommendation'),
                'confidence': round(float(row.get('confidence', 0)), 2),
                'edge': round(float(row.get('edge', 0)), 2),
                'model_version': row.get('model_version')
            }

            # Add grading if available
            if row.get('is_correct') is not None:
                prediction['is_correct'] = row.get('is_correct')
                prediction['actual_strikeouts'] = row.get('actual_strikeouts')

            predictions.append(prediction)

        return predictions

    def _build_summary(self, predictions: List[Dict]) -> Dict[str, Any]:
        """Build summary statistics."""
        total = len(predictions)
        over_picks = sum(1 for p in predictions if p.get('recommendation') == 'OVER')
        under_picks = sum(1 for p in predictions if p.get('recommendation') == 'UNDER')
        pass_picks = sum(1 for p in predictions if p.get('recommendation') == 'PASS')

        # Confidence distribution
        high_confidence = sum(1 for p in predictions if p.get('confidence', 0) >= 70)
        medium_confidence = sum(1 for p in predictions if 50 <= p.get('confidence', 0) < 70)
        low_confidence = sum(1 for p in predictions if p.get('confidence', 0) < 50)

        # Grading summary if available
        graded = [p for p in predictions if p.get('is_correct') is not None]
        grading_summary = None
        if graded:
            correct = sum(1 for p in graded if p.get('is_correct') == True)
            grading_summary = {
                'graded': len(graded),
                'correct': correct,
                'accuracy': round(100 * correct / len(graded), 1) if graded else 0
            }

        return {
            'total_predictions': total,
            'over_picks': over_picks,
            'under_picks': under_picks,
            'pass_picks': pass_picks,
            'high_confidence': high_confidence,
            'medium_confidence': medium_confidence,
            'low_confidence': low_confidence,
            'grading': grading_summary
        }

    def export(self, game_date: str, **kwargs) -> str:
        """
        Generate and upload predictions to GCS.

        Args:
            game_date: Date to export

        Returns:
            GCS path of uploaded file
        """
        json_data = self.generate_json(game_date, **kwargs)
        path = f"mlb/predictions/{game_date}.json"

        return self.upload_to_gcs(
            json_data,
            path,
            cache_control='public, max-age=60'  # 1 minute cache for live data
        )


def main():
    """Main entry point."""
    import argparse
    from datetime import date

    parser = argparse.ArgumentParser(
        description='MLB Predictions Exporter'
    )
    parser.add_argument(
        '--date',
        type=str,
        default=date.today().isoformat(),
        help='Date to export (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Generate JSON but do not upload'
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    exporter = MlbPredictionsExporter()

    if args.dry_run:
        import json
        result = exporter.generate_json(args.date)
        print(json.dumps(result, indent=2))
    else:
        gcs_path = exporter.export(args.date)
        print(f"Exported to: {gcs_path}")


if __name__ == '__main__':
    main()
