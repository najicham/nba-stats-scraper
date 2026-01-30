"""
System Performance Alert Cloud Function

Monitors prediction system performance and sends alerts when:
1. Champion system (catboost_v8) performance regresses
2. A challenger system outperforms the champion
3. Performance drops below critical thresholds

Triggered by: Cloud Scheduler (recommended: run daily after grading completes)

Deployment:
    gcloud functions deploy system-performance-alert \
        --gen2 \
        --runtime python311 \
        --region us-west2 \
        --source orchestration/cloud_functions/system_performance_alert \
        --entry-point check_system_performance \
        --trigger-http \
        --allow-unauthenticated \
        --set-env-vars GCP_PROJECT=nba-props-platform

Version: 1.0
Created: 2026-01-10
"""

import json
import logging
import os
from datetime import date, timedelta
from typing import Dict, List, Optional, Any

from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client
from shared.utils.slack_retry import send_slack_webhook_with_retry
import functions_framework
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')
CHAMPION_SYSTEM = 'catboost_v8'

# Alert thresholds
MAE_REGRESSION_THRESHOLD = 0.5  # Alert if 7d MAE > 30d MAE + 0.5
MIN_WIN_RATE = 0.55  # Alert if win rate drops below 55%
MIN_PICKS_FOR_COMPARISON = 50  # Minimum picks to make comparison
CHALLENGER_OUTPERFORM_MARGIN = 0.03  # 3% margin to flag challenger

# Slack webhook
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')


def get_system_performance(
    bq_client: bigquery.Client,
    system_id: str,
    days: int
) -> Dict[str, Any]:
    """
    Get rolling performance metrics for a system.

    Returns:
        Dict with win_rate, mae, picks, avg_confidence
    """
    query = f"""
    SELECT
        system_id,
        SUM(recommendations_count) as picks,
        SUM(correct_count) as correct,
        ROUND(SAFE_DIVIDE(SUM(correct_count), SUM(recommendations_count)), 4) as win_rate,
        ROUND(AVG(mae), 2) as mae,
        ROUND(AVG(avg_confidence), 3) as avg_confidence,
        ROUND(SAFE_DIVIDE(SUM(high_confidence_correct), SUM(high_confidence_count)), 4) as high_conf_win_rate,
        SUM(high_confidence_count) as high_conf_picks
    FROM `{PROJECT_ID}.nba_predictions.system_daily_performance`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
      AND game_date < CURRENT_DATE()
      AND system_id = @system_id
    GROUP BY system_id
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("system_id", "STRING", system_id)
        ]
    )

    results = list(bq_client.query(query, job_config=job_config))

    if not results:
        return {
            'system_id': system_id,
            'picks': 0,
            'win_rate': None,
            'mae': None,
            'avg_confidence': None,
            'high_conf_win_rate': None,
            'high_conf_picks': 0
        }

    row = results[0]
    return {
        'system_id': system_id,
        'picks': row.picks or 0,
        'correct': row.correct or 0,
        'win_rate': float(row.win_rate) if row.win_rate else None,
        'mae': float(row.mae) if row.mae else None,
        'avg_confidence': float(row.avg_confidence) if row.avg_confidence else None,
        'high_conf_win_rate': float(row.high_conf_win_rate) if row.high_conf_win_rate else None,
        'high_conf_picks': row.high_conf_picks or 0
    }


def get_all_systems_performance(bq_client: bigquery.Client, days: int) -> List[Dict]:
    """Get performance for all active systems."""
    query = f"""
    SELECT
        system_id,
        SUM(recommendations_count) as picks,
        SUM(correct_count) as correct,
        ROUND(SAFE_DIVIDE(SUM(correct_count), SUM(recommendations_count)), 4) as win_rate,
        ROUND(AVG(mae), 2) as mae,
        ROUND(AVG(avg_confidence), 3) as avg_confidence
    FROM `{PROJECT_ID}.nba_predictions.system_daily_performance`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
      AND game_date < CURRENT_DATE()
    GROUP BY system_id
    HAVING SUM(recommendations_count) >= {MIN_PICKS_FOR_COMPARISON}
    ORDER BY win_rate DESC
    """

    results = list(bq_client.query(query))

    return [
        {
            'system_id': row.system_id,
            'picks': row.picks or 0,
            'correct': row.correct or 0,
            'win_rate': float(row.win_rate) if row.win_rate else None,
            'mae': float(row.mae) if row.mae else None,
            'avg_confidence': float(row.avg_confidence) if row.avg_confidence else None
        }
        for row in results
    ]


def check_champion_regression(
    perf_7d: Dict,
    perf_30d: Dict
) -> List[str]:
    """Check if champion system is regressing."""
    alerts = []

    if not perf_7d['picks'] >= MIN_PICKS_FOR_COMPARISON:
        return alerts

    # Check MAE regression
    if perf_7d['mae'] and perf_30d['mae']:
        mae_diff = perf_7d['mae'] - perf_30d['mae']
        if mae_diff > MAE_REGRESSION_THRESHOLD:
            alerts.append(
                f"MAE Regression: {perf_7d['mae']:.2f} (7d) vs {perf_30d['mae']:.2f} (30d) "
                f"[+{mae_diff:.2f} points]"
            )

    # Check win rate drop
    if perf_7d['win_rate'] and perf_7d['win_rate'] < MIN_WIN_RATE:
        alerts.append(
            f"Win Rate Below Threshold: {perf_7d['win_rate']:.1%} (7d) < {MIN_WIN_RATE:.0%} minimum "
            f"[{perf_7d['picks']} picks]"
        )

    # Check win rate regression vs 30d baseline
    if perf_7d['win_rate'] and perf_30d['win_rate']:
        wr_diff = perf_30d['win_rate'] - perf_7d['win_rate']
        if wr_diff > 0.05:  # 5% drop
            alerts.append(
                f"Win Rate Drop: {perf_7d['win_rate']:.1%} (7d) vs {perf_30d['win_rate']:.1%} (30d) "
                f"[-{wr_diff:.1%}]"
            )

    return alerts


def check_challenger_outperformance(
    champion_perf: Dict,
    all_systems: List[Dict]
) -> List[str]:
    """Check if any challenger system is outperforming the champion."""
    alerts = []

    if not champion_perf['win_rate']:
        return alerts

    for system in all_systems:
        if system['system_id'] == CHAMPION_SYSTEM:
            continue

        if not system['win_rate'] or system['picks'] < MIN_PICKS_FOR_COMPARISON:
            continue

        margin = system['win_rate'] - champion_perf['win_rate']
        if margin > CHALLENGER_OUTPERFORM_MARGIN:
            alerts.append(
                f"Challenger Outperforming: {system['system_id']} has {system['win_rate']:.1%} "
                f"vs {CHAMPION_SYSTEM} {champion_perf['win_rate']:.1%} "
                f"[+{margin:.1%} margin, {system['picks']} picks]"
            )

    return alerts


def format_slack_message(
    champion_7d: Dict,
    champion_30d: Dict,
    all_systems_7d: List[Dict],
    alerts: List[str]
) -> Dict:
    """Format Slack message with performance summary and alerts."""

    # Header based on alert status
    if alerts:
        header = ":warning: System Performance Alert"
        color = "#ff9800"  # Orange
    else:
        header = ":white_check_mark: System Performance OK"
        color = "#4caf50"  # Green

    # Champion performance summary
    champion_text = (
        f"*{CHAMPION_SYSTEM}* (Champion)\n"
        f"• 7-day: {champion_7d['win_rate']:.1%} win rate, {champion_7d['mae']:.2f} MAE ({champion_7d['picks']} picks)\n"
        f"• 30-day: {champion_30d['win_rate']:.1%} win rate, {champion_30d['mae']:.2f} MAE ({champion_30d['picks']} picks)"
    )

    # System leaderboard (top 5)
    leaderboard_lines = []
    for i, sys in enumerate(all_systems_7d[:5]):
        emoji = ":crown:" if sys['system_id'] == CHAMPION_SYSTEM else f"{i+1}."
        leaderboard_lines.append(
            f"{emoji} *{sys['system_id']}*: {sys['win_rate']:.1%} ({sys['picks']} picks)"
        )
    leaderboard_text = "\n".join(leaderboard_lines)

    # Alert section
    alert_text = "\n".join([f"• {a}" for a in alerts]) if alerts else "No issues detected"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": champion_text}
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*7-Day Leaderboard*\n{leaderboard_text}"}
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Alerts*\n{alert_text}"}
        }
    ]

    return {
        "attachments": [{"color": color, "blocks": blocks}]
    }


def send_slack_alert(message: Dict) -> bool:
    """Send alert to Slack."""
    if not SLACK_WEBHOOK_URL:
        logger.warning("No Slack webhook configured, skipping alert")
        return False

    success = send_slack_webhook_with_retry(SLACK_WEBHOOK_URL, message, timeout=10)

    if success:
        logger.info("Slack alert sent successfully")
    else:
        logger.error("Failed to send Slack alert after retries", exc_info=True)

    return success


@functions_framework.http
def check_system_performance(request):
    """
    Main entry point for the Cloud Function.

    Checks system performance and sends alerts if issues detected.
    """
    logger.info("Starting system performance check")

    bq_client = get_bigquery_client(project_id=PROJECT_ID)

    # Get champion performance
    champion_7d = get_system_performance(bq_client, CHAMPION_SYSTEM, 7)
    champion_30d = get_system_performance(bq_client, CHAMPION_SYSTEM, 30)

    # Get all systems for comparison
    all_systems_7d = get_all_systems_performance(bq_client, 7)

    # Check for issues
    alerts = []
    alerts.extend(check_champion_regression(champion_7d, champion_30d))
    alerts.extend(check_challenger_outperformance(champion_7d, all_systems_7d))

    # Log results
    logger.info(f"Champion 7d: {champion_7d}")
    logger.info(f"Champion 30d: {champion_30d}")
    logger.info(f"All systems 7d: {all_systems_7d}")
    logger.info(f"Alerts: {alerts}")

    # Format and send Slack message
    slack_message = format_slack_message(
        champion_7d, champion_30d, all_systems_7d, alerts
    )

    # Always send daily summary (or only on alerts - configurable)
    send_daily_summary = os.environ.get('SEND_DAILY_SUMMARY', 'true').lower() == 'true'

    if alerts or send_daily_summary:
        send_slack_alert(slack_message)

    return {
        'status': 'alert' if alerts else 'ok',
        'champion_7d': champion_7d,
        'champion_30d': champion_30d,
        'all_systems_7d': all_systems_7d,
        'alerts': alerts
    }


@functions_framework.http
def health(request):
    """Health check endpoint for system_performance_alert."""
    return json.dumps({
        'status': 'healthy',
        'function': 'system_performance_alert',
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}
