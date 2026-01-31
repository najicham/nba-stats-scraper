"""
BigQuery Client - Historical data and analytics

Provides access to:
- Processor run history
- Prediction accuracy metrics
- Feature store health
- Data quality trends
"""
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional
from google.cloud import bigquery

logger = logging.getLogger(__name__)


class BigQueryClient:
    """Client for accessing BigQuery analytics and historical data"""

    def __init__(self, project_id: str = "nba-props-platform"):
        self.client = bigquery.Client(project=project_id)
        self.project_id = project_id

    def get_todays_summary(self) -> Dict[str, Any]:
        """
        Get today's processing summary

        Returns:
            Summary metrics for today's pipeline execution
        """
        query = f"""
        WITH today_predictions AS (
            SELECT
                COUNT(*) as total_predictions,
                COUNT(DISTINCT game_id) as games_with_predictions
            FROM `{self.project_id}.nba_predictions.player_prop_predictions`
            WHERE game_date = CURRENT_DATE()
        ),
        today_games AS (
            SELECT COUNT(*) as total_games
            FROM `{self.project_id}.nba_reference.nba_schedule`
            WHERE game_date = CURRENT_DATE()
            AND game_status IN (1, 2, 3)  -- 1=Scheduled, 2=InProgress, 3=Final
        ),
        today_grading AS (
            SELECT
                COUNT(*) as total_graded,
                COUNTIF(prediction_correct) as correct_predictions,
                ROUND(COUNTIF(prediction_correct) * 100.0 / NULLIF(COUNT(*), 0), 1) as accuracy_pct
            FROM `{self.project_id}.nba_predictions.prediction_accuracy`
            WHERE game_date = CURRENT_DATE()
        ),
        week_avg AS (
            SELECT
                ROUND(COUNTIF(prediction_correct) * 100.0 / NULLIF(COUNT(*), 0), 1) as week_avg_accuracy
            FROM `{self.project_id}.nba_predictions.prediction_accuracy`
            WHERE game_date >= CURRENT_DATE() - 7
            AND game_date < CURRENT_DATE()
        )
        SELECT
            p.total_predictions,
            p.games_with_predictions,
            g.total_games,
            ROUND(p.games_with_predictions * 100.0 / NULLIF(g.total_games, 0), 1) as coverage_pct,
            gr.total_graded,
            gr.correct_predictions,
            gr.accuracy_pct,
            w.week_avg_accuracy,
            ROUND(gr.accuracy_pct - w.week_avg_accuracy, 1) as accuracy_vs_week_avg
        FROM today_predictions p
        CROSS JOIN today_games g
        CROSS JOIN today_grading gr
        CROSS JOIN week_avg w
        """

        try:
            result = self.client.query(query).result()
            row = next(result, None)

            if row:
                return {
                    'total_predictions': row.total_predictions or 0,
                    'games_with_predictions': row.games_with_predictions or 0,
                    'total_games': row.total_games or 0,
                    'coverage_pct': row.coverage_pct or 0.0,
                    'total_graded': row.total_graded or 0,
                    'correct_predictions': row.correct_predictions or 0,
                    'accuracy_pct': row.accuracy_pct or 0.0,
                    'week_avg_accuracy': row.week_avg_accuracy or 0.0,
                    'accuracy_vs_week_avg': row.accuracy_vs_week_avg or 0.0
                }
            else:
                return self._empty_summary()
        except Exception as e:
            logger.error(f"Error fetching today's summary: {e}")
            return self._empty_summary()

    def get_processor_run_stats(self) -> Dict[str, Any]:
        """
        Get processor execution statistics

        Returns:
            Stats on processor runs, success rates, errors
        """
        query = f"""
        WITH today_runs AS (
            SELECT
                processor_name,
                COUNT(*) as total_runs,
                COUNTIF(status = 'success') as successful_runs,
                COUNTIF(status = 'error') as failed_runs,
                ROUND(AVG(duration_seconds), 1) as avg_duration_seconds
            FROM `{self.project_id}.nba_reference.processor_run_history`
            WHERE DATE(started_at) = CURRENT_DATE()
            GROUP BY processor_name
        )
        SELECT
            processor_name,
            total_runs,
            successful_runs,
            failed_runs,
            ROUND(successful_runs * 100.0 / total_runs, 1) as success_rate_pct,
            avg_duration_seconds
        FROM today_runs
        ORDER BY processor_name
        """

        try:
            result = self.client.query(query).result()
            stats = []

            for row in result:
                stats.append({
                    'processor_type': row.processor_name,
                    'total_runs': row.total_runs,
                    'successful_runs': row.successful_runs,
                    'failed_runs': row.failed_runs,
                    'success_rate_pct': row.success_rate_pct,
                    'avg_duration_seconds': row.avg_duration_seconds
                })

            return {'processors': stats}
        except Exception as e:
            logger.error(f"Error fetching processor run stats: {e}")
            return {'processors': []}

    def get_recent_errors(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent processor errors

        Args:
            limit: Maximum number of errors to return

        Returns:
            List of recent errors
        """
        query = f"""
        SELECT
            processor_name,
            started_at,
            errors
        FROM `{self.project_id}.nba_reference.processor_run_history`
        WHERE status = 'error'
        AND DATE(started_at) >= CURRENT_DATE() - 1
        ORDER BY started_at DESC
        LIMIT {limit}
        """

        try:
            result = self.client.query(query).result()
            errors = []

            for row in result:
                # errors is a JSON field, extract message if available
                error_msg = str(row.errors) if row.errors else 'Unknown error'
                errors.append({
                    'processor_type': row.processor_name,
                    'timestamp': row.started_at.isoformat() if row.started_at else None,
                    'error_message': error_msg,
                    'error_details': None
                })

            return errors
        except Exception as e:
            logger.error(f"Error fetching recent errors: {e}")
            return []

    def get_data_quality_alerts(self) -> List[Dict[str, Any]]:
        """
        Get active data quality alerts

        Returns:
            List of active alerts from quality monitoring
        """
        # TODO: Query data quality monitoring tables when they exist
        # For now, return empty list
        return []

    def get_shot_zone_quality(self) -> Dict[str, Any]:
        """
        Get shot zone data quality metrics

        Returns:
            Shot zone quality stats
        """
        query = f"""
        SELECT
            game_date,
            pct_complete,
            avg_paint_rate,
            low_paint_anomalies + high_three_anomalies as anomaly_count
        FROM `{self.project_id}.nba_orchestration.shot_zone_quality_trend`
        WHERE game_date >= CURRENT_DATE() - 7
        ORDER BY game_date DESC
        LIMIT 1
        """

        try:
            result = self.client.query(query).result()
            row = next(result, None)

            if row:
                return {
                    'game_date': row.game_date.isoformat() if row.game_date else None,
                    'completeness_pct': row.pct_complete,
                    'avg_paint_rate': row.avg_paint_rate,
                    'anomaly_count': row.anomaly_count,
                    'status': 'good' if row.pct_complete >= 80 else 'degraded'
                }
            else:
                return {'status': 'unknown'}
        except Exception as e:
            logger.error(f"Error fetching shot zone quality: {e}")
            return {'status': 'error', 'error': str(e)}

    @staticmethod
    def _empty_summary() -> Dict[str, Any]:
        """Return empty summary structure"""
        return {
            'total_predictions': 0,
            'games_with_predictions': 0,
            'total_games': 0,
            'coverage_pct': 0.0,
            'total_graded': 0,
            'correct_predictions': 0,
            'accuracy_pct': 0.0,
            'week_avg_accuracy': 0.0,
            'accuracy_vs_week_avg': 0.0
        }
