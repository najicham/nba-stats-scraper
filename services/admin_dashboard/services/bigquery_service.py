"""
BigQuery Service for Admin Dashboard

Queries BigQuery for pipeline status, game details, and historical data.
"""

import os
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional
from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')


class BigQueryService:
    """Service for querying BigQuery pipeline data."""

    def __init__(self):
        self.client = bigquery.Client(project=PROJECT_ID)

    def get_daily_status(self, target_date: date) -> Optional[Dict]:
        """
        Get pipeline status for a specific date.

        Returns dict with:
        - games_scheduled: Number of games
        - phase3_context: Player context records
        - phase4_features: ML feature records
        - predictions: Active prediction count
        - pipeline_status: Overall status (COMPLETE, PHASE_X_PENDING, etc.)
        """
        query = f"""
        SELECT
            game_date,
            games_scheduled,
            phase3_context,
            phase4_features,
            predictions,
            players_with_predictions,
            pipeline_status
        FROM `{PROJECT_ID}.nba_orchestration.daily_phase_status`
        WHERE game_date = '{target_date.isoformat()}'
        """

        try:
            result = list(self.client.query(query).result())
            if result:
                row = result[0]
                return {
                    'game_date': str(row.game_date),
                    'games_scheduled': row.games_scheduled,
                    'phase3_context': row.phase3_context,
                    'phase4_features': row.phase4_features,
                    'predictions': row.predictions,
                    'players_with_predictions': row.players_with_predictions,
                    'pipeline_status': row.pipeline_status
                }
            else:
                # No data for this date
                return {
                    'game_date': target_date.isoformat(),
                    'games_scheduled': 0,
                    'phase3_context': 0,
                    'phase4_features': 0,
                    'predictions': 0,
                    'players_with_predictions': 0,
                    'pipeline_status': 'NO_DATA'
                }
        except Exception as e:
            logger.error(f"Error querying daily status: {e}")
            raise

    def get_games_detail(self, target_date: date) -> List[Dict]:
        """
        Get detailed status per game for a specific date.

        Returns list of games with context/feature/prediction counts.
        """
        query = f"""
        WITH games AS (
            SELECT
                game_id,
                game_date,
                home_team_name,
                away_team_name,
                home_team_tricode,
                away_team_tricode,
                game_status_text
            FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
            WHERE game_date = '{target_date.isoformat()}'
        ),
        context AS (
            SELECT game_id, COUNT(*) as context_count
            FROM `{PROJECT_ID}.nba_analytics.upcoming_player_game_context`
            WHERE game_date = '{target_date.isoformat()}'
            GROUP BY game_id
        ),
        features AS (
            SELECT game_id, COUNT(*) as feature_count
            FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
            WHERE game_date = '{target_date.isoformat()}'
            GROUP BY game_id
        ),
        predictions AS (
            SELECT game_id, COUNT(*) as prediction_count
            FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
            WHERE game_date = '{target_date.isoformat()}'
              AND is_active = TRUE
            GROUP BY game_id
        )
        SELECT
            g.game_id,
            g.home_team_name,
            g.away_team_name,
            g.home_team_tricode,
            g.away_team_tricode,
            g.game_status_text,
            COALESCE(c.context_count, 0) as context_count,
            COALESCE(f.feature_count, 0) as feature_count,
            COALESCE(p.prediction_count, 0) as prediction_count,
            CASE
                WHEN COALESCE(p.prediction_count, 0) > 0 THEN 'COMPLETE'
                WHEN COALESCE(f.feature_count, 0) > 0 THEN 'PHASE_5_PENDING'
                WHEN COALESCE(c.context_count, 0) > 0 THEN 'PHASE_4_PENDING'
                ELSE 'PHASE_3_PENDING'
            END as game_status
        FROM games g
        LEFT JOIN context c ON g.game_id = c.game_id
        LEFT JOIN features f ON g.game_id = f.game_id
        LEFT JOIN predictions p ON g.game_id = p.game_id
        ORDER BY g.game_id
        """

        try:
            result = list(self.client.query(query).result())
            return [
                {
                    'game_id': row.game_id,
                    'home_team': row.home_team_name,
                    'away_team': row.away_team_name,
                    'home_abbr': row.home_team_tricode,
                    'away_abbr': row.away_team_tricode,
                    'game_status_text': row.game_status_text,
                    'context_count': row.context_count,
                    'feature_count': row.feature_count,
                    'prediction_count': row.prediction_count,
                    'pipeline_status': row.game_status
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying game details: {e}")
            raise

    def get_pipeline_history(self, days: int = 7) -> List[Dict]:
        """
        Get pipeline status for the last N days.

        Returns list of daily status records.
        """
        query = f"""
        SELECT
            game_date,
            games_scheduled,
            phase3_context,
            phase4_features,
            predictions,
            players_with_predictions,
            pipeline_status
        FROM `{PROJECT_ID}.nba_orchestration.daily_phase_status`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          AND game_date <= DATE_ADD(CURRENT_DATE(), INTERVAL 1 DAY)
        ORDER BY game_date DESC
        """

        try:
            result = list(self.client.query(query).result())
            return [
                {
                    'game_date': str(row.game_date),
                    'games_scheduled': row.games_scheduled,
                    'phase3_context': row.phase3_context,
                    'phase4_features': row.phase4_features,
                    'predictions': row.predictions,
                    'players_with_predictions': row.players_with_predictions,
                    'pipeline_status': row.pipeline_status
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying pipeline history: {e}")
            raise

    def get_processor_stats(self, target_date: date, processor_name: str) -> Optional[Dict]:
        """Get stats for a specific processor run."""
        # This could query run_history collection or a dedicated stats table
        # For now, return None - to be implemented
        return None

    def get_processor_failures(self, hours: int = 24) -> List[Dict]:
        """
        Get recent processor failures from processor_run_history.

        Args:
            hours: How many hours back to look (default 24)

        Returns:
            List of failed processor runs with details
        """
        query = f"""
        SELECT
            processor_name,
            data_date,
            run_id,
            status,
            error_message,
            started_at,
            processed_at,
            duration_seconds,
            records_processed,
            phase
        FROM `{PROJECT_ID}.nba_reference.processor_run_history`
        WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
          AND status IN ('failed', 'error')
        ORDER BY started_at DESC
        LIMIT 50
        """

        try:
            result = list(self.client.query(query).result())
            return [
                {
                    'processor_name': row.processor_name,
                    'data_date': str(row.data_date) if row.data_date else None,
                    'run_id': row.run_id,
                    'status': row.status,
                    'error_message': row.error_message[:500] if row.error_message else None,
                    'started_at': row.started_at.isoformat() if row.started_at else None,
                    'processed_at': row.processed_at.isoformat() if row.processed_at else None,
                    'duration_seconds': row.duration_seconds,
                    'records_processed': row.records_processed,
                    'phase': row.phase
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying processor failures: {e}")
            return []

    def get_player_game_summary_coverage(self, days: int = 7) -> List[Dict]:
        """
        Get player_game_summary coverage for recent days.

        Shows row counts vs game counts to identify missing data.
        """
        query = f"""
        WITH game_counts AS (
            SELECT
                game_date,
                COUNT(DISTINCT game_id) as games_final
            FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
              AND game_status_text = 'Final'
            GROUP BY game_date
        ),
        summary_counts AS (
            SELECT
                game_date,
                COUNT(*) as summary_rows,
                COUNT(DISTINCT game_id) as games_with_data
            FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
            GROUP BY game_date
        )
        SELECT
            g.game_date,
            g.games_final,
            COALESCE(s.summary_rows, 0) as summary_rows,
            COALESCE(s.games_with_data, 0) as games_with_data,
            CASE
                WHEN g.games_final = 0 THEN 'NO_GAMES'
                WHEN COALESCE(s.summary_rows, 0) = 0 THEN 'MISSING'
                WHEN s.games_with_data < g.games_final THEN 'PARTIAL'
                ELSE 'COMPLETE'
            END as coverage_status
        FROM game_counts g
        LEFT JOIN summary_counts s ON g.game_date = s.game_date
        ORDER BY g.game_date DESC
        """

        try:
            result = list(self.client.query(query).result())
            return [
                {
                    'game_date': str(row.game_date),
                    'games_final': row.games_final,
                    'summary_rows': row.summary_rows,
                    'games_with_data': row.games_with_data,
                    'coverage_status': row.coverage_status
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying coverage: {e}")
            return []

    def get_grading_status(self, days: int = 7) -> List[Dict]:
        """
        Get grading status for recent days.

        Shows prediction counts vs graded counts.
        """
        query = f"""
        WITH predictions AS (
            SELECT
                game_date,
                COUNT(*) as prediction_count
            FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
            GROUP BY game_date
        ),
        graded AS (
            SELECT
                game_date,
                COUNT(*) as graded_count,
                ROUND(AVG(absolute_error), 2) as mae
            FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND game_date < CURRENT_DATE()
            GROUP BY game_date
        )
        SELECT
            p.game_date,
            p.prediction_count,
            COALESCE(g.graded_count, 0) as graded_count,
            g.mae,
            CASE
                WHEN COALESCE(g.graded_count, 0) = 0 THEN 'NOT_GRADED'
                WHEN g.graded_count < p.prediction_count * 0.8 THEN 'PARTIAL'
                ELSE 'COMPLETE'
            END as grading_status
        FROM predictions p
        LEFT JOIN graded g ON p.game_date = g.game_date
        ORDER BY p.game_date DESC
        """

        try:
            result = list(self.client.query(query).result())
            return [
                {
                    'game_date': str(row.game_date),
                    'prediction_count': row.prediction_count,
                    'graded_count': row.graded_count,
                    'mae': row.mae,
                    'grading_status': row.grading_status
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Error querying grading status: {e}")
            return []
