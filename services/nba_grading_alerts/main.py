"""
NBA Grading Alerting Service

Monitors prediction grading and sends Slack alerts for:
- Grading failures (no grades generated)
- Accuracy drops (<55% threshold)
- High ungradeable rate (>20%)
- Optional daily summary

Deployed as Cloud Function, triggered by Cloud Scheduler daily.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from google.cloud import bigquery
import requests
import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Alert thresholds (can be overridden by environment variables)
ACCURACY_MIN = float(os.environ.get('ALERT_THRESHOLD_ACCURACY_MIN', 55.0))
UNGRADEABLE_MAX = float(os.environ.get('ALERT_THRESHOLD_UNGRADEABLE_MAX', 20.0))
CHECK_DAYS = int(os.environ.get('ALERT_THRESHOLD_DAYS', 7))
SEND_DAILY_SUMMARY = os.environ.get('SEND_DAILY_SUMMARY', 'false').lower() == 'true'


def send_slack_alert(webhook_url: str, message: dict) -> int:
    """Send alert to Slack via webhook."""
    try:
        response = requests.post(webhook_url, json=message, timeout=10)
        response.raise_for_status()
        logger.info(f"Slack alert sent successfully: {response.status_code}")
        return response.status_code
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        raise


def check_grading_health(client: bigquery.Client, game_date: str) -> Dict:
    """Check if grading ran successfully for a date."""
    query = f"""
    SELECT
        COUNT(*) as total_grades,
        COUNTIF(has_issues) as issue_count,
        ROUND(100.0 * COUNTIF(has_issues) / NULLIF(COUNT(*), 0), 1) as issue_pct,
        COUNTIF(player_dnp) as dnp_count,
        COUNTIF(actual_points IS NULL) as missing_actuals
    FROM `nba-props-platform.nba_predictions.prediction_grades`
    WHERE game_date = '{game_date}'
    """

    try:
        result = list(client.query(query).result())
        if not result:
            return {
                'total_grades': 0,
                'issue_count': 0,
                'issue_pct': 0.0,
                'dnp_count': 0,
                'missing_actuals': 0
            }

        row = result[0]
        return {
            'total_grades': row.total_grades,
            'issue_count': row.issue_count,
            'issue_pct': row.issue_pct or 0.0,
            'dnp_count': row.dnp_count,
            'missing_actuals': row.missing_actuals
        }
    except Exception as e:
        logger.error(f"Error checking grading health: {e}")
        return {'total_grades': 0, 'issue_count': 0, 'issue_pct': 0.0, 'dnp_count': 0, 'missing_actuals': 0}


def check_accuracy_health(client: bigquery.Client, days: int = 7) -> List[Dict]:
    """Check if any system's accuracy dropped below threshold."""
    query = f"""
    SELECT
        system_id,
        ROUND(AVG(accuracy_pct), 1) as avg_accuracy,
        MIN(accuracy_pct) as min_accuracy,
        MAX(accuracy_pct) as max_accuracy,
        COUNT(*) as days_tracked,
        ROUND(AVG(avg_margin_of_error), 1) as avg_margin
    FROM `nba-props-platform.nba_predictions.prediction_accuracy_summary`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
    GROUP BY system_id
    HAVING avg_accuracy < {ACCURACY_MIN}  -- Alert threshold
    ORDER BY avg_accuracy ASC
    """

    try:
        return [dict(row) for row in client.query(query).result()]
    except Exception as e:
        logger.error(f"Error checking accuracy health: {e}")
        return []


def check_calibration_health(client: bigquery.Client, days: int = 7, threshold: float = 15.0) -> List[Dict]:
    """Check if any system has poor calibration (high calibration error)."""
    query = f"""
    SELECT
        system_id,
        COUNT(DISTINCT confidence_bucket) as confidence_buckets,
        SUM(total_predictions) as total_predictions,
        ROUND(AVG(ABS(calibration_error)), 2) as avg_abs_calibration_error,
        ROUND(MAX(ABS(calibration_error)), 2) as max_abs_calibration_error,
        ROUND(AVG(calibration_error), 2) as avg_calibration_error,
        CASE
            WHEN AVG(ABS(calibration_error)) > 15 THEN 'POOR'
            WHEN AVG(ABS(calibration_error)) > 10 THEN 'FAIR'
            WHEN AVG(ABS(calibration_error)) > 5 THEN 'GOOD'
            ELSE 'EXCELLENT'
        END as calibration_health
    FROM `nba-props-platform.nba_predictions.confidence_calibration`
    WHERE last_prediction_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
      AND confidence_bucket >= 65  -- Focus on high-confidence predictions
    GROUP BY system_id
    HAVING AVG(ABS(calibration_error)) > {threshold}  -- Alert threshold
    ORDER BY avg_abs_calibration_error DESC
    """

    try:
        return [dict(row) for row in client.query(query).result()]
    except Exception as e:
        logger.error(f"Error checking calibration health: {e}")
        return []


def get_weekly_summary(client: bigquery.Client, days: int = 7) -> Dict:
    """Get weekly summary with trends and insights."""
    query = f"""
    SELECT
        system_id,
        COUNT(*) as total_predictions,
        COUNTIF(prediction_correct) as correct,
        COUNTIF(NOT prediction_correct) as incorrect,
        ROUND(100.0 * COUNTIF(prediction_correct) / COUNTIF(prediction_correct IS NOT NULL), 2) as accuracy_pct,
        ROUND(AVG(CASE WHEN prediction_correct IS NOT NULL THEN margin_of_error END), 2) as avg_margin_of_error,
        ROUND(AVG(CASE WHEN prediction_correct IS NOT NULL THEN confidence_score END) * 100, 2) as avg_confidence
    FROM `nba-props-platform.nba_predictions.prediction_grades`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
      AND has_issues = FALSE
    GROUP BY system_id
    ORDER BY accuracy_pct DESC
    """

    try:
        systems = [dict(row) for row in client.query(query).result()]

        return {
            'days': days,
            'total_predictions': sum(s['total_predictions'] for s in systems),
            'systems': systems,
            'best_system': systems[0]['system_id'] if systems else 'N/A',
            'best_accuracy': systems[0]['accuracy_pct'] if systems else 0
        }
    except Exception as e:
        logger.error(f"Error getting weekly summary: {e}")
        return {'days': days, 'total_predictions': 0, 'systems': [], 'best_system': 'N/A', 'best_accuracy': 0}


def check_ranking_change(client: bigquery.Client) -> Optional[Dict]:
    """Check if top system has changed from previous week."""
    # Get current week's best system (last 7 days)
    current_query = """
    SELECT system_id, ROUND(AVG(accuracy_pct), 2) as avg_accuracy
    FROM `nba-props-platform.nba_predictions.prediction_accuracy_summary`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    GROUP BY system_id
    ORDER BY avg_accuracy DESC
    LIMIT 1
    """

    # Get previous week's best system (days 8-14)
    previous_query = """
    SELECT system_id, ROUND(AVG(accuracy_pct), 2) as avg_accuracy
    FROM `nba-props-platform.nba_predictions.prediction_accuracy_summary`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
      AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    GROUP BY system_id
    ORDER BY avg_accuracy DESC
    LIMIT 1
    """

    try:
        current_result = list(client.query(current_query).result(timeout=60))
        previous_result = list(client.query(previous_query).result(timeout=60))

        if not current_result or not previous_result:
            return None

        current_best = current_result[0]
        previous_best = previous_result[0]

        # Only alert if ranking changed
        if current_best.system_id != previous_best.system_id:
            return {
                'previous_best': previous_best.system_id,
                'previous_accuracy': previous_best.avg_accuracy,
                'current_best': current_best.system_id,
                'current_accuracy': current_best.avg_accuracy
            }

        return None
    except Exception as e:
        logger.error(f"Error checking ranking change: {e}")
        return None


def get_daily_summary(client: bigquery.Client, game_date: str) -> Dict:
    """Get daily grading summary for informational alert."""
    query = f"""
    SELECT
        system_id,
        total_predictions,
        correct_predictions,
        accuracy_pct,
        avg_margin_of_error
    FROM `nba-props-platform.nba_predictions.prediction_accuracy_summary`
    WHERE game_date = '{game_date}'
    ORDER BY accuracy_pct DESC
    """

    try:
        systems = [dict(row) for row in client.query(query).result()]

        # Get overall stats
        health = check_grading_health(client, game_date)

        return {
            'systems': systems,
            'total_grades': health['total_grades'],
            'issue_count': health['issue_count'],
            'issue_pct': health['issue_pct']
        }
    except Exception as e:
        logger.error(f"Error getting daily summary: {e}")
        return {'systems': [], 'total_grades': 0, 'issue_count': 0, 'issue_pct': 0.0}


def build_alert_message(alert_type: str, data: Dict) -> Dict:
    """Build Slack message payload with blocks."""

    if alert_type == 'grading_failure':
        return {
            "text": f"🚨 NBA Grading Alert: No grades generated for {data['game_date']}",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "🚨 Grading Failure Detected"}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Date:*\n{data['game_date']}"},
                        {"type": "mrkdwn", "text": f"*Grades Generated:*\n{data['total_grades']}"}
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Possible Causes:*\n• Scheduled query failed\n• No predictions for this date\n• Boxscores not yet ingested\n• All predictions already graded"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Action Required:*\nCheck <https://console.cloud.google.com/bigquery/scheduled-queries|scheduled query execution history>"
                    }
                }
            ]
        }

    elif alert_type == 'accuracy_drop':
        systems_text = "\n".join([
            f"• *{s['system_id']}*: {s['avg_accuracy']}% avg (min: {s['min_accuracy']}%, max: {s['max_accuracy']}%)"
            for s in data['systems']
        ])

        return {
            "text": f"⚠️ NBA Grading Alert: Accuracy drop detected ({len(data['systems'])} systems below {ACCURACY_MIN}%)",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "⚠️ Accuracy Drop Detected"}
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Systems below {ACCURACY_MIN}% threshold:*\n{systems_text}"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Period:*\nLast {data['days']} days"},
                        {"type": "mrkdwn", "text": f"*Systems Affected:*\n{len(data['systems'])}"}
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Recommended Actions:*\n• Review model performance\n• Check for data quality issues\n• Consider model recalibration\n• Review recent feature changes"
                    }
                }
            ]
        }

    elif alert_type == 'data_quality':
        issues_text = f"• {data['dnp_count']} players DNP\n• {data['missing_actuals']} missing actual results"

        return {
            "text": f"⚠️ NBA Grading Alert: High ungradeable rate ({data['issue_pct']}%)",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "⚠️ Data Quality Issue"}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Date:*\n{data['game_date']}"},
                        {"type": "mrkdwn", "text": f"*Issue Rate:*\n{data['issue_pct']}%"}
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Details:*\n{data['issue_count']} of {data['total_grades']} predictions have issues\n\n{issues_text}"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Action:* Review boxscore ingestion pipeline"
                    }
                }
            ]
        }

    elif alert_type == 'daily_summary':
        if not data['systems']:
            systems_text = "_No grading data available_"
            best_system = "N/A"
            avg_margin = "N/A"
        else:
            systems_text = "\n".join([
                f"• *{s['system_id']}*: {s['accuracy_pct']}% accuracy"
                for s in data['systems'][:5]  # Top 5
            ])
            best_system = data['systems'][0]['system_id']
            avg_margin = round(sum(s['avg_margin_of_error'] for s in data['systems']) / len(data['systems']), 1)

        graded_pct = round(100.0 * (data['total_grades'] - data['issue_count']) / max(data['total_grades'], 1), 1)

        return {
            "text": f"🏀 NBA Grading Daily Summary - {data['game_date']}",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"🏀 NBA Grading Daily Summary"}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Date:*\n{data['game_date']}"},
                        {"type": "mrkdwn", "text": f"*Status:*\n{'✅ Complete' if graded_pct > 95 else '⚠️ Partial'}"}
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Grading Stats:*\n• Total predictions: {data['total_grades']}\n• Graded successfully: {data['total_grades'] - data['issue_count']} ({graded_pct}%)\n• Issues: {data['issue_count']} ({data['issue_pct']}%)"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*📊 System Performance:*\n{systems_text}\n\n*Best performing:* {best_system}\n*Avg margin of error:* {avg_margin} points"
                    }
                }
            ]
        }

    elif alert_type == 'calibration_alert':
        systems_text = "\n".join([
            f"• *{s['system_id']}*: {s['avg_abs_calibration_error']} pts avg error ({s['calibration_health']})"
            for s in data['systems']
        ])

        # Determine interpretation text
        if data['systems']:
            first_system = data['systems'][0]
            if first_system['avg_calibration_error'] > 0:
                interpretation = f"Model reports {first_system['avg_abs_calibration_error']} pts higher confidence than actual accuracy (overconfident)."
            else:
                interpretation = f"Model reports {first_system['avg_abs_calibration_error']} pts lower confidence than actual accuracy (underconfident)."
        else:
            interpretation = "Calibration errors detected."

        return {
            "text": f"📊 NBA Grading Alert: Calibration issue detected ({len(data['systems'])} systems)",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "📊 Calibration Issue Detected"}
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Systems with poor calibration (>15 pt error):*\n{systems_text}"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Period:*\nLast {data.get('days', 7)} days"},
                        {"type": "mrkdwn", "text": f"*Systems Affected:*\n{len(data['systems'])}"}
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Interpretation:*\n{interpretation}"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Recommended Actions:*\n• Apply temperature scaling to confidence scores\n• Review feature importance and model architecture\n• Retrain with balanced confidence targets\n• Consider ensemble confidence fusion"
                    }
                }
            ]
        }

    elif alert_type == 'weekly_summary':
        systems_text = "\n".join([
            f"• *{s['system_id']}*: {s['accuracy_pct']}% accuracy ({s['total_predictions']} predictions)"
            for s in data['systems'][:5]  # Top 5
        ])

        return {
            "text": f"📅 NBA Grading Weekly Summary - {data['days']} days",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "📅 NBA Grading Weekly Summary"}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Period:*\nLast {data['days']} days"},
                        {"type": "mrkdwn", "text": f"*Total Predictions:*\n{data['total_predictions']:,}"}
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*📊 Top Performing Systems:*\n{systems_text}"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Best System:*\n{data['best_system']}"},
                        {"type": "mrkdwn", "text": f"*Best Accuracy:*\n{data['best_accuracy']}%"}
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*💡 Insight:* Review full metrics in the admin dashboard for detailed ROI analysis and player insights."
                    }
                }
            ]
        }

    elif alert_type == 'ranking_change':
        change_emoji = "📈" if data['current_accuracy'] > data['previous_accuracy'] else "📉"

        return {
            "text": f"🔄 NBA Grading Alert: Top system changed from {data['previous_best']} to {data['current_best']}",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "🔄 System Ranking Change"}
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"The top-performing prediction system has changed!"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Previous Leader (Week -2):*\n{data['previous_best']} ({data['previous_accuracy']}%)"},
                        {"type": "mrkdwn", "text": f"*New Leader (Week -1):*\n{data['current_best']} ({data['current_accuracy']}%)"}
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{change_emoji} *Accuracy Change:* {data['current_accuracy'] - data['previous_accuracy']:+.2f} percentage points"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Recommended Actions:*\n• Review betting strategy to prioritize new top system\n• Investigate what changed in system performance\n• Update confidence thresholds if needed"
                    }
                }
            ]
        }

    return {"text": f"NBA Grading Alert: {alert_type}"}


@functions_framework.http
def main(request):
    """
    Cloud Function entry point.

    Triggered by Cloud Scheduler daily at 12:30 PM PT.
    Checks grading health and sends Slack alerts as needed.
    """
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if not webhook_url:
        logger.error("SLACK_WEBHOOK_URL environment variable not set")
        return {"error": "SLACK_WEBHOOK_URL not configured"}, 500

    try:
        client = bigquery.Client(project='nba-props-platform')
        yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()

        logger.info(f"Checking grading health for {yesterday}")

        alerts = []

        # Check 1: Grading ran successfully
        health = check_grading_health(client, yesterday)
        logger.info(f"Grading health: {health}")

        if health['total_grades'] == 0:
            logger.warning(f"No grades found for {yesterday}")
            alerts.append(('grading_failure', {'game_date': yesterday, **health}))
        elif health['issue_pct'] > UNGRADEABLE_MAX:
            logger.warning(f"High ungradeable rate: {health['issue_pct']}%")
            alerts.append(('data_quality', {'game_date': yesterday, **health}))

        # Check 2: Accuracy drop across systems
        low_accuracy_systems = check_accuracy_health(client, days=CHECK_DAYS)
        if low_accuracy_systems:
            logger.warning(f"Found {len(low_accuracy_systems)} systems with low accuracy")
            alerts.append(('accuracy_drop', {'systems': low_accuracy_systems, 'days': CHECK_DAYS}))

        # Check 3: Calibration health (poor calibration = >15 point error)
        calibration_threshold = float(os.environ.get('ALERT_THRESHOLD_CALIBRATION', 15.0))
        poor_calibration_systems = check_calibration_health(client, days=CHECK_DAYS, threshold=calibration_threshold)
        if poor_calibration_systems:
            logger.warning(f"Found {len(poor_calibration_systems)} systems with poor calibration")
            alerts.append(('calibration_alert', {'systems': poor_calibration_systems, 'days': CHECK_DAYS}))

        # Check 4: System ranking change (weekly check)
        ranking_change = check_ranking_change(client)
        if ranking_change:
            logger.info(f"System ranking changed: {ranking_change['previous_best']} -> {ranking_change['current_best']}")
            alerts.append(('ranking_change', ranking_change))

        # Check 5: Weekly summary (sent on Mondays)
        today = datetime.now()
        is_monday = today.weekday() == 0  # Monday = 0
        send_weekly = os.environ.get('SEND_WEEKLY_SUMMARY', 'false').lower() == 'true'

        if is_monday or send_weekly:  # Send on Mondays or if explicitly enabled
            weekly_data = get_weekly_summary(client, days=7)
            if weekly_data['total_predictions'] > 0:
                logger.info(f"Sending weekly summary: {weekly_data['total_predictions']} predictions")
                alerts.append(('weekly_summary', weekly_data))

        # Optional: Daily summary
        if SEND_DAILY_SUMMARY and health['total_grades'] > 0:
            summary = get_daily_summary(client, yesterday)
            alerts.append(('daily_summary', {'game_date': yesterday, **summary}))

        # Send all alerts
        logger.info(f"Sending {len(alerts)} alerts")
        for alert_type, data in alerts:
            try:
                message = build_alert_message(alert_type, data)
                send_slack_alert(webhook_url, message)
                logger.info(f"Sent {alert_type} alert")
            except Exception as e:
                logger.error(f"Failed to send {alert_type} alert: {e}")

        return {
            "status": "success",
            "date_checked": yesterday,
            "alerts_sent": len(alerts),
            "alert_types": [a[0] for a in alerts],
            "grading_health": health
        }, 200

    except Exception as e:
        logger.error(f"Error in main function: {e}", exc_info=True)
        return {"error": str(e)}, 500


if __name__ == '__main__':
    # For local testing
    class MockRequest:
        pass

    result = main(MockRequest())
    print(json.dumps(result, indent=2))
