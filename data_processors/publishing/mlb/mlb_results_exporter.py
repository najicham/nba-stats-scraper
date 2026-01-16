#!/usr/bin/env python3
"""
File: data_processors/publishing/mlb/mlb_results_exporter.py

MLB Results Exporter

Exports game outcomes and graded predictions.

Output: gs://mlb-props-platform-api/v1/mlb/results/{date}.json

Usage:
    exporter = MlbResultsExporter()
    result = exporter.export(game_date='2025-08-15')
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from data_processors.publishing.base_exporter import BaseExporter

logger = logging.getLogger(__name__)


class MlbResultsExporter(BaseExporter):
    """
    Exports MLB game results and graded predictions.

    Schema:
    {
        "generated_at": "2025-08-16T06:00:00Z",
        "game_date": "2025-08-15",
        "results": [...],
        "summary": {...}
    }
    """

    def __init__(
        self,
        project_id: str = 'nba-props-platform',
        bucket_name: str = 'nba-props-platform-api'
    ):
        super().__init__(project_id=project_id, bucket_name=bucket_name)
        logger.info("MlbResultsExporter initialized")

    def generate_json(self, game_date: str, **kwargs) -> Dict[str, Any]:
        """
        Generate results JSON for a date.

        Args:
            game_date: Date to export (YYYY-MM-DD)

        Returns:
            Dictionary ready for JSON export
        """
        logger.info(f"Generating MLB results export for {game_date}")

        # Query results
        results = self._get_results(game_date)

        # Build summary
        summary = self._build_summary(results)

        return {
            'generated_at': self.get_generated_at(),
            'game_date': game_date,
            'results': results,
            'summary': summary
        }

    def _get_results(self, game_date: str) -> List[Dict]:
        """Get graded results for a date."""
        query = f"""
        SELECT
            pitcher_lookup,
            pitcher_name,
            team_abbr,
            opponent_team_abbr,
            is_home,
            strikeouts_line,
            predicted_strikeouts,
            actual_strikeouts,
            recommendation,
            confidence,
            edge,
            is_correct,
            model_version,
            graded_at
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date = '{game_date}'
          AND is_correct IS NOT NULL
        ORDER BY pitcher_name ASC
        """

        rows = self.query_to_list(query)

        results = []
        for row in rows:
            result = {
                'pitcher_id': row.get('pitcher_lookup'),
                'pitcher_name': row.get('pitcher_name'),
                'team': row.get('team_abbr'),
                'opponent': row.get('opponent_team_abbr'),
                'is_home': bool(row.get('is_home')),
                'strikeouts_line': float(row.get('strikeouts_line', 0)),
                'predicted_strikeouts': round(float(row.get('predicted_strikeouts', 0)), 1),
                'actual_strikeouts': int(row.get('actual_strikeouts', 0)),
                'recommendation': row.get('recommendation'),
                'confidence': int(row.get('confidence', 0)),
                'edge': round(float(row.get('edge', 0)), 2),
                'is_correct': row.get('is_correct'),
                'model_version': row.get('model_version')
            }

            # Calculate result details
            actual = result['actual_strikeouts']
            line = result['strikeouts_line']
            result['actual_vs_line'] = 'OVER' if actual > line else ('UNDER' if actual < line else 'PUSH')
            result['prediction_error'] = round(result['predicted_strikeouts'] - actual, 1)

            results.append(result)

        return results

    def _build_summary(self, results: List[Dict]) -> Dict[str, Any]:
        """Build summary statistics."""
        total = len(results)
        if total == 0:
            return {
                'total_graded': 0,
                'correct': 0,
                'incorrect': 0,
                'accuracy': 0,
                'by_recommendation': {}
            }

        correct = sum(1 for r in results if r.get('is_correct') == True)
        incorrect = sum(1 for r in results if r.get('is_correct') == False)

        # By recommendation
        over_results = [r for r in results if r.get('recommendation') == 'OVER']
        under_results = [r for r in results if r.get('recommendation') == 'UNDER']

        over_correct = sum(1 for r in over_results if r.get('is_correct') == True)
        under_correct = sum(1 for r in under_results if r.get('is_correct') == True)

        # Prediction accuracy metrics
        errors = [abs(r.get('prediction_error', 0)) for r in results]
        mae = sum(errors) / total if total else 0

        return {
            'total_graded': total,
            'correct': correct,
            'incorrect': incorrect,
            'accuracy': round(100 * correct / total, 1) if total else 0,
            'mean_absolute_error': round(mae, 2),
            'by_recommendation': {
                'OVER': {
                    'total': len(over_results),
                    'correct': over_correct,
                    'accuracy': round(100 * over_correct / len(over_results), 1) if over_results else 0
                },
                'UNDER': {
                    'total': len(under_results),
                    'correct': under_correct,
                    'accuracy': round(100 * under_correct / len(under_results), 1) if under_results else 0
                }
            }
        }

    def export(self, game_date: str, **kwargs) -> str:
        """
        Generate and upload results to GCS.

        Args:
            game_date: Date to export

        Returns:
            GCS path of uploaded file
        """
        json_data = self.generate_json(game_date, **kwargs)
        path = f"mlb/results/{game_date}.json"

        return self.upload_to_gcs(
            json_data,
            path,
            cache_control='public, max-age=3600'  # 1 hour cache (results don't change)
        )


def main():
    """Main entry point."""
    import argparse
    from datetime import date, timedelta

    parser = argparse.ArgumentParser(
        description='MLB Results Exporter'
    )
    parser.add_argument(
        '--date',
        type=str,
        default=(date.today() - timedelta(days=1)).isoformat(),
        help='Date to export (YYYY-MM-DD), default: yesterday'
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

    exporter = MlbResultsExporter()

    if args.dry_run:
        import json
        result = exporter.generate_json(args.date)
        print(json.dumps(result, indent=2))
    else:
        gcs_path = exporter.export(args.date)
        print(f"Exported to: {gcs_path}")


if __name__ == '__main__':
    main()
