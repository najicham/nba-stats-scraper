# predictions/coordinator/signal_calculator.py
"""
Daily Prediction Signal Calculator

Calculates and stores pre-game signals after predictions are generated.
Signals indicate the quality of betting conditions for the day.

Session 71: Automation of signal calculation after batch completion.
Session 71: Added Slack alerts for signal notifications.
"""

import logging
from datetime import date
from typing import Optional

from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Project configuration
PROJECT_ID = 'nba-props-platform'
SIGNALS_TABLE = f'{PROJECT_ID}.nba_predictions.daily_prediction_signals'

# Primary model to send alerts for (avoid spamming with all 7+ models)
PRIMARY_ALERT_MODEL = 'catboost_v9'


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

          CURRENT_TIMESTAMP() as calculated_at,

          -- Session 112: Scenario counts for optimal betting strategies (moved to end to match schema)
          COUNTIF(recommendation = 'OVER' AND current_points_line < 12 AND ABS(predicted_points - current_points_line) >= 5) as optimal_over_count,
          COUNTIF(recommendation = 'UNDER' AND current_points_line >= 25 AND ABS(predicted_points - current_points_line) >= 3) as optimal_under_count,
          COUNTIF(recommendation = 'OVER' AND ABS(predicted_points - current_points_line) >= 7) as ultra_high_edge_count,
          COUNTIF(recommendation = 'UNDER' AND current_points_line < 15 AND ABS(predicted_points - current_points_line) >= 3) as anti_pattern_count,

          -- Session 170: Track prediction bias (avg predicted - vegas line)
          ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl

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

        # Log signal summary for monitoring and send Slack alert
        if rows_affected > 0:
            summary_query = f"""
            SELECT system_id, total_picks, high_edge_picks, pct_over, daily_signal, signal_explanation,
                   optimal_over_count, optimal_under_count, ultra_high_edge_count, anti_pattern_count,
                   avg_pvl
            FROM `{SIGNALS_TABLE}`
            WHERE game_date = @game_date
            ORDER BY system_id
            """
            summary_result = client.query(summary_query, job_config=job_config).result()

            primary_signal_data = None
            for row in summary_result:
                # Session 112: Include scenario counts in logging
                optimal_total = (row.optimal_over_count or 0) + (row.optimal_under_count or 0) + (row.ultra_high_edge_count or 0)
                logger.info(
                    f"  {row.system_id}: {row.total_picks} picks, "
                    f"pct_over={row.pct_over}%, signal={row.daily_signal}, "
                    f"avg_pvl={row.avg_pvl or 0:+.2f}, "
                    f"optimal={optimal_total} (over={row.optimal_over_count or 0}, under={row.optimal_under_count or 0}, ultra={row.ultra_high_edge_count or 0})"
                )
                # Capture primary model for Slack alert
                if row.system_id == PRIMARY_ALERT_MODEL:
                    primary_signal_data = {
                        'game_date': game_date,
                        'system_id': row.system_id,
                        'total_picks': row.total_picks,
                        'high_edge_picks': row.high_edge_picks,
                        'pct_over': row.pct_over,
                        'daily_signal': row.daily_signal,
                        'signal_explanation': row.signal_explanation,
                        # Session 112: Scenario counts
                        'optimal_over_count': row.optimal_over_count or 0,
                        'optimal_under_count': row.optimal_under_count or 0,
                        'ultra_high_edge_count': row.ultra_high_edge_count or 0,
                        'anti_pattern_count': row.anti_pattern_count or 0,
                        # Session 170: Prediction bias tracking
                        'avg_pvl': row.avg_pvl or 0.0,
                    }

            # Send Slack alert for primary model
            if primary_signal_data:
                _send_signal_slack_alert(primary_signal_data)

                # Session 113: Send daily optimal picks notifications (Slack, Email, SMS)
                _send_optimal_picks_notification(game_date)

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


def _send_signal_slack_alert(signal_data: dict) -> bool:
    """
    Send Slack alert for the daily signal.

    Only sends for the primary model (catboost_v9) to avoid spam.
    Alerts on all signal types (RED, YELLOW, GREEN) for daily awareness.

    Args:
        signal_data: Dict with signal information

    Returns:
        True if sent successfully
    """
    try:
        from shared.utils.slack_channels import send_signal_alert_to_slack

        daily_signal = signal_data.get('daily_signal', 'UNKNOWN')
        game_date = signal_data.get('game_date', 'Unknown')

        # Send alert
        success = send_signal_alert_to_slack(signal_data)

        if success:
            logger.info(f"Slack alert sent: {daily_signal} signal for {game_date}")
        else:
            logger.debug(f"Slack alert not sent (webhook not configured)")

        return success

    except ImportError as e:
        logger.debug(f"Slack alerting not available: {e}")
        return False
    except Exception as e:
        logger.warning(f"Failed to send Slack signal alert (non-fatal): {e}")
        return False


def _send_optimal_picks_notification(game_date: str) -> dict:
    """
    Send daily optimal picks via Slack, Email, and SMS.

    Session 113: Integrated with signal calculation for automated daily picks.

    Sends picks for optimal scenarios:
    - optimal_over (87.3% HR)
    - optimal_under (70.7% HR)
    - ultra_high_edge_over (88.5% HR)

    Args:
        game_date: Date to send picks for (YYYY-MM-DD)

    Returns:
        dict with success status: {'slack': bool, 'email': bool, 'sms': bool}
    """
    try:
        from shared.notifications.subset_picks_notifier import SubsetPicksNotifier

        notifier = SubsetPicksNotifier()

        # Send notifications for optimal scenarios
        results = notifier.send_daily_notifications(
            subset_id='v9_high_edge_top5',  # Default subset
            game_date=game_date,
            send_slack=True,
            send_email=True,
            send_sms=True
        )

        logger.info(f"Optimal picks notification sent for {game_date}: {results}")
        return results

    except ImportError as e:
        logger.debug(f"Subset picks notifier not available: {e}")
        return {'slack': False, 'email': False, 'sms': False}
    except Exception as e:
        logger.warning(f"Failed to send optimal picks notification (non-fatal): {e}")
        return {'slack': False, 'email': False, 'sms': False}


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
