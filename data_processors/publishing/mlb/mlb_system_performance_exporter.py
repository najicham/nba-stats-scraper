#!/usr/bin/env python3
"""
File: data_processors/publishing/mlb/mlb_system_performance_exporter.py

MLB System Performance Exporter

Exports model accuracy metrics for V1.4 vs V1.6 comparison.

Output: gs://mlb-props-platform-api/v1/mlb/performance/{date}.json

Usage:
    exporter = MlbSystemPerformanceExporter()
    result = exporter.export(game_date='2025-08-15', lookback_days=30)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional

from data_processors.publishing.base_exporter import BaseExporter

logger = logging.getLogger(__name__)


class MlbSystemPerformanceExporter(BaseExporter):
    """
    Exports MLB model performance metrics.

    Compares V1.4 (champion) vs V1.6 (challenger) accuracy.

    Schema:
    {
        "generated_at": "2025-08-16T06:00:00Z",
        "period": {"start": "...", "end": "..."},
        "models": {...},
        "by_recommendation": {...},
        "daily_performance": [...],
        "recommendation": "..."
    }
    """

    def __init__(
        self,
        project_id: str = 'nba-props-platform',
        bucket_name: str = 'nba-props-platform-api'
    ):
        super().__init__(project_id=project_id, bucket_name=bucket_name)
        logger.info("MlbSystemPerformanceExporter initialized")

    def generate_json(
        self,
        game_date: str = None,
        lookback_days: int = 30,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate performance JSON.

        Args:
            game_date: End date (default: yesterday)
            lookback_days: Number of days to analyze

        Returns:
            Dictionary ready for JSON export
        """
        # Default to yesterday (need graded data)
        if not game_date:
            game_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        end_date = game_date
        start_date = (datetime.strptime(game_date, '%Y-%m-%d') - timedelta(days=lookback_days)).strftime('%Y-%m-%d')

        logger.info(f"Generating MLB performance export for {start_date} to {end_date}")

        # Get model performance
        model_stats = self._get_model_performance(start_date, end_date)

        # Get performance by recommendation type
        by_recommendation = self._get_performance_by_recommendation(start_date, end_date)

        # Get daily performance
        daily_performance = self._get_daily_performance(start_date, end_date)

        # Generate recommendation
        recommendation = self._generate_recommendation(model_stats)

        return {
            'generated_at': self.get_generated_at(),
            'period': {
                'start': start_date,
                'end': end_date,
                'days': lookback_days
            },
            'models': model_stats,
            'by_recommendation': by_recommendation,
            'daily_performance': daily_performance,
            'recommendation': recommendation
        }

    def _get_model_performance(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """Get overall performance by model version."""
        query = f"""
        SELECT
            model_version,
            COUNT(*) as total_predictions,
            COUNTIF(is_correct = TRUE) as correct,
            COUNTIF(is_correct = FALSE) as incorrect,
            COUNTIF(is_correct IS NULL) as ungraded,
            ROUND(100.0 * COUNTIF(is_correct = TRUE) / NULLIF(COUNTIF(is_correct IS NOT NULL), 0), 1) as accuracy,
            ROUND(AVG(confidence), 1) as avg_confidence,
            ROUND(AVG(ABS(edge)), 2) as avg_edge
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY model_version
        ORDER BY model_version
        """

        rows = self.query_to_list(query)

        models = {}
        for row in rows:
            version = row.get('model_version', 'unknown')
            models[version] = {
                'total_predictions': row.get('total_predictions', 0),
                'correct': row.get('correct', 0),
                'incorrect': row.get('incorrect', 0),
                'ungraded': row.get('ungraded', 0),
                'accuracy': row.get('accuracy', 0),
                'avg_confidence': row.get('avg_confidence', 0),
                'avg_edge': row.get('avg_edge', 0)
            }

        return models

    def _get_performance_by_recommendation(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """Get performance split by OVER/UNDER."""
        query = f"""
        SELECT
            model_version,
            recommendation,
            COUNT(*) as total,
            COUNTIF(is_correct = TRUE) as correct,
            ROUND(100.0 * COUNTIF(is_correct = TRUE) / NULLIF(COUNTIF(is_correct IS NOT NULL), 0), 1) as accuracy
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND recommendation IN ('OVER', 'UNDER')
        GROUP BY model_version, recommendation
        ORDER BY model_version, recommendation
        """

        rows = self.query_to_list(query)

        by_rec = {}
        for row in rows:
            version = row.get('model_version', 'unknown')
            rec = row.get('recommendation', 'unknown')

            if version not in by_rec:
                by_rec[version] = {}

            by_rec[version][rec] = {
                'total': row.get('total', 0),
                'correct': row.get('correct', 0),
                'accuracy': row.get('accuracy', 0)
            }

        return by_rec

    def _get_daily_performance(self, start_date: str, end_date: str) -> List[Dict]:
        """Get daily performance trend."""
        query = f"""
        SELECT
            game_date,
            model_version,
            COUNT(*) as predictions,
            COUNTIF(is_correct = TRUE) as correct,
            ROUND(100.0 * COUNTIF(is_correct = TRUE) / NULLIF(COUNTIF(is_correct IS NOT NULL), 0), 1) as accuracy
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND is_correct IS NOT NULL
        GROUP BY game_date, model_version
        ORDER BY game_date DESC, model_version
        LIMIT 100
        """

        rows = self.query_to_list(query)

        daily = []
        for row in rows:
            daily.append({
                'date': str(row.get('game_date', '')),
                'model_version': row.get('model_version'),
                'predictions': row.get('predictions', 0),
                'correct': row.get('correct', 0),
                'accuracy': row.get('accuracy', 0)
            })

        return daily

    def _generate_recommendation(self, model_stats: Dict) -> str:
        """Generate recommendation based on performance."""
        if not model_stats:
            return "Insufficient data for recommendation"

        # Compare V1.4 vs V1.6
        v14 = model_stats.get('V1.4', {})
        v16 = model_stats.get('V1.6', {})

        v14_acc = v14.get('accuracy', 0) or 0
        v16_acc = v16.get('accuracy', 0) or 0

        if v16_acc > v14_acc + 5:
            return f"V1.6 is significantly outperforming V1.4 (+{v16_acc - v14_acc:.1f}%). Consider promotion."
        elif v16_acc > v14_acc:
            return f"V1.6 is slightly outperforming V1.4 (+{v16_acc - v14_acc:.1f}%). Continue monitoring."
        elif v14_acc > v16_acc + 5:
            return f"V1.4 is outperforming V1.6 (+{v14_acc - v16_acc:.1f}%). Keep V1.4 as champion."
        else:
            return "Models performing similarly. Continue shadow mode evaluation."

    def export(
        self,
        game_date: str = None,
        lookback_days: int = 30,
        **kwargs
    ) -> str:
        """
        Generate and upload performance report to GCS.

        Args:
            game_date: End date for analysis
            lookback_days: Number of days to analyze

        Returns:
            GCS path of uploaded file
        """
        if not game_date:
            game_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        json_data = self.generate_json(game_date, lookback_days, **kwargs)
        path = f"mlb/performance/{game_date}.json"

        return self.upload_to_gcs(
            json_data,
            path,
            cache_control='public, max-age=3600'  # 1 hour cache
        )


def main():
    """Main entry point."""
    import argparse
    from datetime import date

    parser = argparse.ArgumentParser(
        description='MLB System Performance Exporter'
    )
    parser.add_argument(
        '--date',
        type=str,
        help='End date for analysis (YYYY-MM-DD), default: yesterday'
    )
    parser.add_argument(
        '--lookback-days',
        type=int,
        default=30,
        help='Number of days to analyze'
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

    exporter = MlbSystemPerformanceExporter()

    if args.dry_run:
        import json
        result = exporter.generate_json(args.date, args.lookback_days)
        print(json.dumps(result, indent=2))
    else:
        gcs_path = exporter.export(args.date, args.lookback_days)
        print(f"Exported to: {gcs_path}")


if __name__ == '__main__':
    main()
