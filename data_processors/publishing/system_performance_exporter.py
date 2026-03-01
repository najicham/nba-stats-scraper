"""
System Performance Exporter for Phase 6 Publishing

Exports system accuracy metrics to JSON for the website dashboard.
Shows rolling performance windows for all prediction systems.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date, timedelta

from google.cloud import bigquery

from .base_exporter import BaseExporter
from .exporter_utils import safe_float

logger = logging.getLogger(__name__)


# System metadata for display
SYSTEM_METADATA = {
    'catboost_v12': {
        'display_name': 'CatBoost V12',
        'description': 'CatBoost gradient boosting with 37+ features and real Vegas lines',
        'is_primary': True,
        'ranking': 1
    },
    'ensemble_v1': {
        'display_name': 'Ensemble',
        'description': 'Weighted combination of all prediction systems',
        'is_primary': False,
        'ranking': 2
    },
    'xgboost_v1': {
        'display_name': 'XGBoost ML',
        'description': 'Gradient boosted trees trained on historical data',
        'is_primary': False,
        'ranking': 3
    },
    'moving_average_baseline_v1': {
        'display_name': 'Moving Average',
        'description': 'Weighted moving averages of recent performance',
        'is_primary': False,
        'ranking': 4
    },
    'similarity_balanced_v1': {
        'display_name': 'Similarity',
        'description': 'K-nearest neighbor matching to similar historical games',
        'is_primary': False,
        'ranking': 5
    },
    'zone_matchup_v1': {
        'display_name': 'Zone Matchup',
        'description': 'Shot zone analysis against opponent defense',
        'is_primary': False,
        'ranking': 6
    }
}


class SystemPerformanceExporter(BaseExporter):
    """
    Export system performance metrics to JSON.

    Output files:
    - systems/performance.json - Rolling accuracy for all systems

    JSON structure:
    {
        "as_of_date": "2022-01-07",
        "generated_at": "2025-12-10T...",
        "systems": [
            {
                "system_id": "catboost_v8",
                "display_name": "CatBoost V8",
                "is_primary": true,
                "windows": {
                    "last_7_days": {...},
                    "last_30_days": {...},
                    "season": {...}
                }
            },
            ...
        ],
        "comparison": {...}
    }
    """

    def generate_json(self, as_of_date: str) -> Dict[str, Any]:
        """
        Generate performance JSON as of a specific date.

        Args:
            as_of_date: Date string in YYYY-MM-DD format

        Returns:
            Dictionary ready for JSON serialization
        """
        # Get rolling window metrics for all systems
        windows_by_system = self._query_rolling_windows(as_of_date)

        if not windows_by_system:
            logger.warning(f"No performance data found as of {as_of_date}")
            return self._empty_response(as_of_date)

        # Build systems array
        systems = self._build_systems_array(windows_by_system)

        # Build comparison summary
        comparison = self._build_comparison(windows_by_system)

        return {
            'as_of_date': as_of_date,
            'generated_at': self.get_generated_at(),
            'systems': systems,
            'comparison': comparison
        }

    def _query_rolling_windows(self, as_of_date: str) -> Dict[str, Dict]:
        """
        Query rolling window metrics for all systems.

        Returns dict mapping system_id to window metrics.
        """
        query = """
        WITH daily AS (
            SELECT
                system_id,
                game_date,
                predictions_count,
                recommendations_count,
                correct_count,
                pass_count,
                mae,
                avg_bias,
                win_rate,
                over_win_rate,
                under_win_rate,
                within_3_pct,
                within_5_pct,
                avg_confidence,
                high_confidence_count,
                high_confidence_correct,
                high_confidence_win_rate
            FROM `nba-props-platform.nba_predictions.system_daily_performance`
            WHERE game_date <= @as_of_date
        )
        SELECT
            system_id,

            -- Last 7 days
            SUM(CASE WHEN game_date > DATE_SUB(@as_of_date, INTERVAL 7 DAY) THEN predictions_count END) as last_7_predictions,
            SUM(CASE WHEN game_date > DATE_SUB(@as_of_date, INTERVAL 7 DAY) THEN recommendations_count END) as last_7_recommendations,
            SUM(CASE WHEN game_date > DATE_SUB(@as_of_date, INTERVAL 7 DAY) THEN correct_count END) as last_7_correct,
            ROUND(SAFE_DIVIDE(
                SUM(CASE WHEN game_date > DATE_SUB(@as_of_date, INTERVAL 7 DAY) THEN correct_count END),
                SUM(CASE WHEN game_date > DATE_SUB(@as_of_date, INTERVAL 7 DAY) THEN recommendations_count END)
            ), 3) as last_7_win_rate,
            ROUND(AVG(CASE WHEN game_date > DATE_SUB(@as_of_date, INTERVAL 7 DAY) THEN mae END), 2) as last_7_mae,
            ROUND(AVG(CASE WHEN game_date > DATE_SUB(@as_of_date, INTERVAL 7 DAY) THEN avg_bias END), 2) as last_7_bias,

            -- Last 30 days
            SUM(CASE WHEN game_date > DATE_SUB(@as_of_date, INTERVAL 30 DAY) THEN predictions_count END) as last_30_predictions,
            SUM(CASE WHEN game_date > DATE_SUB(@as_of_date, INTERVAL 30 DAY) THEN recommendations_count END) as last_30_recommendations,
            SUM(CASE WHEN game_date > DATE_SUB(@as_of_date, INTERVAL 30 DAY) THEN correct_count END) as last_30_correct,
            ROUND(SAFE_DIVIDE(
                SUM(CASE WHEN game_date > DATE_SUB(@as_of_date, INTERVAL 30 DAY) THEN correct_count END),
                SUM(CASE WHEN game_date > DATE_SUB(@as_of_date, INTERVAL 30 DAY) THEN recommendations_count END)
            ), 3) as last_30_win_rate,
            ROUND(AVG(CASE WHEN game_date > DATE_SUB(@as_of_date, INTERVAL 30 DAY) THEN mae END), 2) as last_30_mae,
            ROUND(AVG(CASE WHEN game_date > DATE_SUB(@as_of_date, INTERVAL 30 DAY) THEN avg_bias END), 2) as last_30_bias,

            -- Season (all data)
            SUM(predictions_count) as season_predictions,
            SUM(recommendations_count) as season_recommendations,
            SUM(correct_count) as season_correct,
            ROUND(SAFE_DIVIDE(SUM(correct_count), SUM(recommendations_count)), 3) as season_win_rate,
            ROUND(AVG(mae), 2) as season_mae,
            ROUND(AVG(avg_bias), 2) as season_bias,

            -- Over/Under breakdown (season)
            ROUND(AVG(over_win_rate), 3) as over_win_rate,
            ROUND(AVG(under_win_rate), 3) as under_win_rate,

            -- Threshold accuracy (season)
            ROUND(AVG(within_3_pct), 3) as within_3_pct,
            ROUND(AVG(within_5_pct), 3) as within_5_pct,

            -- High confidence (season)
            SUM(high_confidence_count) as high_conf_total,
            SUM(high_confidence_correct) as high_conf_correct,
            ROUND(SAFE_DIVIDE(SUM(high_confidence_correct), SUM(high_confidence_count)), 3) as high_conf_win_rate

        FROM daily
        GROUP BY system_id
        """

        params = [
            bigquery.ScalarQueryParameter('as_of_date', 'DATE', as_of_date)
        ]

        results = self.query_to_list(query, params)

        # Convert to dict by system_id
        return {r['system_id']: r for r in results}

    def _build_systems_array(self, windows_by_system: Dict[str, Dict]) -> List[Dict]:
        """Build the systems array with metadata and windows."""
        systems = []

        for system_id, metrics in windows_by_system.items():
            meta = SYSTEM_METADATA.get(system_id, {
                'display_name': system_id,
                'description': '',
                'is_primary': False,
                'ranking': 99
            })

            system_data = {
                'system_id': system_id,
                'display_name': meta['display_name'],
                'description': meta['description'],
                'is_primary': meta['is_primary'],
                'windows': {
                    'last_7_days': {
                        'predictions': metrics.get('last_7_predictions'),
                        'recommendations': metrics.get('last_7_recommendations'),
                        'correct': metrics.get('last_7_correct'),
                        'win_rate': safe_float(metrics.get('last_7_win_rate')),
                        'mae': safe_float(metrics.get('last_7_mae')),
                        'bias': safe_float(metrics.get('last_7_bias'))
                    },
                    'last_30_days': {
                        'predictions': metrics.get('last_30_predictions'),
                        'recommendations': metrics.get('last_30_recommendations'),
                        'correct': metrics.get('last_30_correct'),
                        'win_rate': safe_float(metrics.get('last_30_win_rate')),
                        'mae': safe_float(metrics.get('last_30_mae')),
                        'bias': safe_float(metrics.get('last_30_bias'))
                    },
                    'season': {
                        'predictions': metrics.get('season_predictions'),
                        'recommendations': metrics.get('season_recommendations'),
                        'correct': metrics.get('season_correct'),
                        'win_rate': safe_float(metrics.get('season_win_rate')),
                        'mae': safe_float(metrics.get('season_mae')),
                        'bias': safe_float(metrics.get('season_bias'))
                    }
                },
                'breakdown': {
                    'over_win_rate': safe_float(metrics.get('over_win_rate')),
                    'under_win_rate': safe_float(metrics.get('under_win_rate')),
                    'within_3_pct': safe_float(metrics.get('within_3_pct')),
                    'within_5_pct': safe_float(metrics.get('within_5_pct')),
                    'high_confidence_win_rate': safe_float(metrics.get('high_conf_win_rate'))
                }
            }

            systems.append(system_data)

        # Sort by ranking
        systems.sort(key=lambda s: SYSTEM_METADATA.get(s['system_id'], {}).get('ranking', 99))

        return systems

    def _build_comparison(self, windows_by_system: Dict[str, Dict]) -> Dict[str, Any]:
        """Build comparison summary across systems."""
        if not windows_by_system:
            return {}

        # Find best by different metrics (season)
        best_mae = min(windows_by_system.items(),
                       key=lambda x: x[1].get('season_mae') or 999)
        best_win_rate = max(windows_by_system.items(),
                           key=lambda x: x[1].get('season_win_rate') or 0)
        lowest_bias = min(windows_by_system.items(),
                         key=lambda x: abs(x[1].get('season_bias') or 999))

        return {
            'best_mae': {
                'system_id': best_mae[0],
                'value': safe_float(best_mae[1].get('season_mae'))
            },
            'best_win_rate': {
                'system_id': best_win_rate[0],
                'value': safe_float(best_win_rate[1].get('season_win_rate'))
            },
            'lowest_bias': {
                'system_id': lowest_bias[0],
                'value': safe_float(lowest_bias[1].get('season_bias'))
            }
        }

    def _empty_response(self, as_of_date: str) -> Dict[str, Any]:
        """Return empty response when no data available."""
        return {
            'as_of_date': as_of_date,
            'generated_at': self.get_generated_at(),
            'systems': [],
            'comparison': {}
        }

    def export(self, as_of_date: str) -> str:
        """
        Generate and upload system performance JSON.

        Args:
            as_of_date: Date string in YYYY-MM-DD format

        Returns:
            GCS path of the exported file
        """
        logger.info(f"Exporting system performance as of {as_of_date}")

        json_data = self.generate_json(as_of_date)

        # Upload with 1-hour cache
        path = 'systems/performance.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=3600')

        return gcs_path
