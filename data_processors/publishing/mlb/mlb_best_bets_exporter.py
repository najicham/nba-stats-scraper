#!/usr/bin/env python3
"""
File: data_processors/publishing/mlb/mlb_best_bets_exporter.py

MLB Best Bets Exporter

Exports high-confidence MLB pitcher strikeout picks.

Criteria:
- Confidence >= 70%
- Edge >= 1.0
- OVER or UNDER recommendation (no PASS)

Output: gs://mlb-props-platform-api/v1/mlb/best-bets/{date}.json

Usage:
    exporter = MlbBestBetsExporter()
    result = exporter.export(game_date='2025-08-15')
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from data_processors.publishing.base_exporter import BaseExporter

logger = logging.getLogger(__name__)

# Best bets thresholds
MIN_CONFIDENCE = 70
MIN_EDGE = 1.0


class MlbBestBetsExporter(BaseExporter):
    """
    Exports high-confidence MLB picks.

    Schema:
    {
        "generated_at": "2025-08-15T10:00:00Z",
        "game_date": "2025-08-15",
        "criteria": {...},
        "best_bets": [...],
        "summary": {...}
    }
    """

    def __init__(
        self,
        project_id: str = 'nba-props-platform',
        bucket_name: str = 'nba-props-platform-api',
        min_confidence: int = MIN_CONFIDENCE,
        min_edge: float = MIN_EDGE
    ):
        super().__init__(project_id=project_id, bucket_name=bucket_name)
        self.min_confidence = min_confidence
        self.min_edge = min_edge
        logger.info(f"MlbBestBetsExporter initialized (conf>={min_confidence}, edge>={min_edge})")

    def generate_json(self, game_date: str, **kwargs) -> Dict[str, Any]:
        """
        Generate best bets JSON for a date.

        Args:
            game_date: Date to export (YYYY-MM-DD)

        Returns:
            Dictionary ready for JSON export
        """
        logger.info(f"Generating MLB best bets export for {game_date}")

        # Query best bets
        best_bets = self._get_best_bets(game_date)

        # Build summary
        summary = self._build_summary(best_bets)

        return {
            'generated_at': self.get_generated_at(),
            'game_date': game_date,
            'criteria': {
                'min_confidence': self.min_confidence,
                'min_edge': self.min_edge,
                'recommendations': ['OVER', 'UNDER']
            },
            'best_bets': best_bets,
            'summary': summary
        }

    def _get_best_bets(self, game_date: str) -> List[Dict]:
        """Get high-confidence picks for a date."""
        query = f"""
        SELECT
            pitcher_lookup,
            pitcher_name,
            team_abbr,
            opponent_team_abbr,
            is_home,
            strikeouts_line,
            predicted_strikeouts,
            recommendation,
            confidence,
            edge,
            model_version,
            is_correct,
            actual_strikeouts
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date = '{game_date}'
          AND confidence >= {self.min_confidence}
          AND ABS(edge) >= {self.min_edge}
          AND recommendation IN ('OVER', 'UNDER')
        ORDER BY confidence DESC, ABS(edge) DESC
        """

        rows = self.query_to_list(query)

        best_bets = []
        for row in rows:
            bet = {
                'pitcher_id': row.get('pitcher_lookup'),
                'pitcher_name': row.get('pitcher_name'),
                'team': row.get('team_abbr'),
                'opponent': row.get('opponent_team_abbr'),
                'is_home': bool(row.get('is_home')),
                'strikeouts_line': float(row.get('strikeouts_line', 0)),
                'predicted_strikeouts': round(float(row.get('predicted_strikeouts', 0)), 1),
                'recommendation': row.get('recommendation'),
                'confidence': int(row.get('confidence', 0)),
                'edge': round(float(row.get('edge', 0)), 2),
                'model_version': row.get('model_version'),
                'rank': len(best_bets) + 1
            }

            # Add grading if available
            if row.get('is_correct') is not None:
                bet['is_correct'] = row.get('is_correct')
                bet['actual_strikeouts'] = row.get('actual_strikeouts')

            best_bets.append(bet)

        return best_bets

    def _build_summary(self, best_bets: List[Dict]) -> Dict[str, Any]:
        """Build summary statistics."""
        total = len(best_bets)
        over_picks = sum(1 for b in best_bets if b.get('recommendation') == 'OVER')
        under_picks = sum(1 for b in best_bets if b.get('recommendation') == 'UNDER')

        # Average metrics
        avg_confidence = sum(b.get('confidence', 0) for b in best_bets) / total if total else 0
        avg_edge = sum(abs(b.get('edge', 0)) for b in best_bets) / total if total else 0

        # Grading if available
        graded = [b for b in best_bets if b.get('is_correct') is not None]
        grading_summary = None
        if graded:
            correct = sum(1 for b in graded if b.get('is_correct') == True)
            grading_summary = {
                'graded': len(graded),
                'correct': correct,
                'accuracy': round(100 * correct / len(graded), 1) if graded else 0
            }

        return {
            'total_best_bets': total,
            'over_picks': over_picks,
            'under_picks': under_picks,
            'avg_confidence': round(avg_confidence, 1),
            'avg_edge': round(avg_edge, 2),
            'grading': grading_summary
        }

    def export(self, game_date: str, **kwargs) -> str:
        """
        Generate and upload best bets to GCS.

        Args:
            game_date: Date to export

        Returns:
            GCS path of uploaded file
        """
        json_data = self.generate_json(game_date, **kwargs)
        path = f"mlb/best-bets/{game_date}.json"

        return self.upload_to_gcs(
            json_data,
            path,
            cache_control='public, max-age=60'
        )


def main():
    """Main entry point."""
    import argparse
    from datetime import date

    parser = argparse.ArgumentParser(
        description='MLB Best Bets Exporter'
    )
    parser.add_argument(
        '--date',
        type=str,
        default=date.today().isoformat(),
        help='Date to export (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--min-confidence',
        type=int,
        default=MIN_CONFIDENCE,
        help='Minimum confidence threshold'
    )
    parser.add_argument(
        '--min-edge',
        type=float,
        default=MIN_EDGE,
        help='Minimum edge threshold'
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

    exporter = MlbBestBetsExporter(
        min_confidence=args.min_confidence,
        min_edge=args.min_edge
    )

    if args.dry_run:
        import json
        result = exporter.generate_json(args.date)
        print(json.dumps(result, indent=2))
    else:
        gcs_path = exporter.export(args.date)
        print(f"Exported to: {gcs_path}")


if __name__ == '__main__':
    main()
