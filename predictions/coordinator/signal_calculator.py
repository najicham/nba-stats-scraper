# predictions/coordinator/signal_calculator.py
"""
Daily Prediction Signal Calculator

Calculates and stores pre-game signals after predictions are generated.
Signals indicate the quality of betting conditions for the day.

Session 71: Automation of signal calculation after batch completion.
"""

import logging
from datetime import date
from typing import Optional

from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Project configuration
PROJECT_ID = 'nba-props-platform'
SIGNALS_TABLE = f'{PROJECT_ID}.nba_predictions.daily_prediction_signals'


def calculate_daily_signals(game_date: str, project_id: str = PROJECT_ID) -> dict:
    """
    Calculate and store daily prediction signals for a game date.

    This runs after predictions are consolidated into the main table.
    Calculates signals for all prediction systems that generated predictions.

    Args:
        game_date: Date to calculate signals for (YYYY-MM-DD format)
        project_id: GCP project ID

    Returns:
        dict with calculation results:
        - success: bool
        - systems_processed: int
        - error: str (if failed)
    """
    logger.info(f"Calculating daily signals for {game_date}...")

    try:
        client = bigquery.Client(project=project_id)

        # Delete any existing signals for this date (idempotent)
        delete_query = f"""
        DELETE FROM `{SIGNALS_TABLE}`
        WHERE game_date = @game_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )

        client.query(delete_query, job_config=job_config).result()
        logger.info(f"Cleared existing signals for {game_date}")

        # Insert new signals for all systems
        insert_query = f"""
        INSERT INTO `{SIGNALS_TABLE}`
        SELECT
          DATE(@game_date) as game_date,
          system_id,

          COUNT(*) as total_picks,
          COUNTIF(ABS(predicted_points - current_points_line) >= 5) as high_edge_picks,
          COUNTIF(confidence_score >= 0.92 AND ABS(predicted_points - current_points_line) >= 3) as premium_picks,

          ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over,
          ROUND(100.0 * COUNTIF(recommendation = 'UNDER') / COUNT(*), 1) as pct_under,

          ROUND(AVG(confidence_score) * 100, 2) as avg_confidence,
          ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_edge,

          CASE
            WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25 THEN 'UNDER_HEAVY'
            WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 40 THEN 'OVER_HEAVY'
            ELSE 'BALANCED'
          END as skew_category,

          CASE
            WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) < 3 THEN 'LOW'
            WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) > 8 THEN 'HIGH'
            ELSE 'NORMAL'
          END as volume_category,

          CASE
            WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25 THEN 'RED'
            WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) < 3 THEN 'YELLOW'
            WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 45 THEN 'YELLOW'
            ELSE 'GREEN'
          END as daily_signal,

          CASE
            WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25
              THEN 'Heavy UNDER skew - historically 54% hit rate vs 82% on balanced days'
            WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) < 3
              THEN 'Low pick volume - high variance expected'
            WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 45
              THEN 'Heavy OVER skew - monitor for potential underperformance'
            ELSE 'Balanced signals - historical 82% hit rate on high-edge picks'
          END as signal_explanation,

          CURRENT_TIMESTAMP() as calculated_at

        FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        WHERE game_date = @game_date
          AND current_points_line IS NOT NULL
        GROUP BY system_id
        HAVING COUNT(*) >= 10  -- Only calculate signals if we have enough predictions
        """

        job = client.query(insert_query, job_config=job_config)
        result = job.result()
        rows_affected = job.num_dml_affected_rows or 0

        logger.info(f"Daily signals calculated: {rows_affected} system(s) for {game_date}")

        # Log signal summary for monitoring
        if rows_affected > 0:
            summary_query = f"""
            SELECT system_id, total_picks, pct_over, daily_signal, signal_explanation
            FROM `{SIGNALS_TABLE}`
            WHERE game_date = @game_date
            ORDER BY system_id
            """
            summary_result = client.query(summary_query, job_config=job_config).result()

            for row in summary_result:
                logger.info(
                    f"  {row.system_id}: {row.total_picks} picks, "
                    f"pct_over={row.pct_over}%, signal={row.daily_signal}"
                )

        return {
            'success': True,
            'systems_processed': rows_affected,
            'game_date': game_date
        }

    except Exception as e:
        logger.error(f"Failed to calculate daily signals for {game_date}: {e}", exc_info=True)
        return {
            'success': False,
            'systems_processed': 0,
            'error': str(e)
        }


def get_daily_signal(game_date: str, system_id: str = 'catboost_v9') -> Optional[dict]:
    """
    Get the daily signal for a specific system and date.

    Args:
        game_date: Date to check (YYYY-MM-DD)
        system_id: Prediction system ID

    Returns:
        dict with signal info or None if not found
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)

        query = f"""
        SELECT *
        FROM `{SIGNALS_TABLE}`
        WHERE game_date = @game_date AND system_id = @system_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("system_id", "STRING", system_id)
            ]
        )

        result = client.query(query, job_config=job_config).result()
        rows = list(result)

        if rows:
            row = rows[0]
            return {
                'game_date': str(row.game_date),
                'system_id': row.system_id,
                'total_picks': row.total_picks,
                'high_edge_picks': row.high_edge_picks,
                'pct_over': row.pct_over,
                'daily_signal': row.daily_signal,
                'signal_explanation': row.signal_explanation
            }
        return None

    except Exception as e:
        logger.error(f"Failed to get daily signal: {e}")
        return None
