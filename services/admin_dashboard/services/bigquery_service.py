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
