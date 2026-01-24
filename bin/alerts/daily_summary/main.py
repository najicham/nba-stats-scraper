"""
NBA Prediction Daily Summary - Cloud Function

Sends a daily Slack summary with:
- Yesterday's prediction stats
- System health metrics
- Top 5 high-confidence picks
- Alert count (last 24h)

Triggered by Cloud Scheduler daily at 9 AM ET.

Created: 2026-01-17 (Week 3 - Option B Implementation)
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any

import functions_framework
from google.cloud import bigquery
from google.cloud import logging as cloud_logging
from google.cloud import pubsub_v1
import requests


# Environment variables
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
PREDICTIONS_TABLE = os.environ.get('PREDICTIONS_TABLE', 'nba_predictions.player_prop_predictions')
FEATURE_STORE_TABLE = os.environ.get('FEATURE_STORE_TABLE', 'nba_predictions.ml_feature_store_v2')


def query_yesterday_summary(client: bigquery.Client) -> Dict[str, Any]:
    """Query overall summary stats for yesterday's predictions."""
    query = f"""
    WITH yesterday_predictions AS (
      SELECT
        system_id,
        COUNT(*) as prediction_count,
        AVG(confidence_score) as avg_confidence,
        COUNTIF(confidence_score = 0.5) as fallback_count,
        COUNTIF(recommendation = 'OVER') as over_count,
        COUNTIF(recommendation = 'UNDER') as under_count,
        COUNTIF(recommendation = 'PASS') as pass_count
      FROM `{PREDICTIONS_TABLE}`
      WHERE
        created_at >= TIMESTAMP(CURRENT_DATE() - 1)
        AND created_at < TIMESTAMP(CURRENT_DATE())
      GROUP BY system_id
    )
    SELECT
      COUNT(DISTINCT system_id) as systems_operational,
      SUM(prediction_count) as total_predictions,
      AVG(avg_confidence) as overall_avg_confidence,
      SUM(fallback_count) as total_fallback_predictions,
      SAFE_DIVIDE(SUM(fallback_count), SUM(prediction_count)) * 100 as fallback_rate_pct,
      SUM(over_count) as total_over,
      SUM(under_count) as total_under,
      SUM(pass_count) as total_pass
    FROM yesterday_predictions
    """

    query_job = client.query(query)
    results = list(query_job.result(timeout=60))

    if not results:
        return {
            'systems_operational': 0,
            'total_predictions': 0,
            'overall_avg_confidence': 0,
            'fallback_rate_pct': 0,
            'total_over': 0,
            'total_under': 0,
            'total_pass': 0
        }

    row = results[0]
    return {
        'systems_operational': row.systems_operational or 0,
        'total_predictions': row.total_predictions or 0,
        'overall_avg_confidence': row.overall_avg_confidence or 0,
        'fallback_rate_pct': row.fallback_rate_pct or 0,
        'total_over': row.total_over or 0,
        'total_under': row.total_under or 0,
        'total_pass': row.total_pass or 0
    }


def query_top_picks(client: bigquery.Client) -> List[Dict[str, Any]]:
    """Query top 5 predictions by confidence from yesterday."""
    query = f"""
    SELECT
      player_lookup,
      predicted_points,
      current_points_line,
      recommendation,
      confidence_score,
      system_id
    FROM `{PREDICTIONS_TABLE}`
    WHERE
      created_at >= TIMESTAMP(CURRENT_DATE() - 1)
      AND created_at < TIMESTAMP(CURRENT_DATE())
      AND recommendation IN ('OVER', 'UNDER')
      AND confidence_score > 0.5
    ORDER BY confidence_score DESC
    LIMIT 5
    """

    query_job = client.query(query)
    results = list(query_job.result(timeout=60))

    picks = []
    for row in results:
        picks.append({
            'player': row.player_lookup,
            'prediction': row.predicted_points,
            'line': row.current_points_line,
            'recommendation': row.recommendation,
            'confidence': row.confidence_score * 100,
            'system': row.system_id
        })

    return picks


def query_unique_players(client: bigquery.Client) -> Dict[str, int]:
    """Query unique players and games predicted yesterday."""
    query = f"""
    SELECT
      COUNT(DISTINCT player_lookup) as unique_players,
      COUNT(DISTINCT game_id) as unique_games
    FROM `{PREDICTIONS_TABLE}`
    WHERE
      created_at >= TIMESTAMP(CURRENT_DATE() - 1)
      AND created_at < TIMESTAMP(CURRENT_DATE())
    """

    query_job = client.query(query)
    results = list(query_job.result(timeout=60))

    if not results:
        return {'unique_players': 0, 'unique_games': 0}

    row = results[0]
    return {
        'unique_players': row.unique_players or 0,
        'unique_games': row.unique_games or 0
    }


def query_feature_quality(client: bigquery.Client) -> Dict[str, Any]:
    """Check feature freshness and availability."""
    query = f"""
    SELECT
      COUNT(DISTINCT player_lookup) as players_with_features,
      MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), last_updated, HOUR)) as max_hours_since_update,
      AVG(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), last_updated, HOUR)) as avg_hours_since_update
    FROM `{FEATURE_STORE_TABLE}`
    WHERE
      game_date >= CURRENT_DATE()
      AND last_updated >= TIMESTAMP(CURRENT_DATE() - 1)
    """

    try:
        query_job = client.query(query)
        results = list(query_job.result(timeout=60))

        if not results:
            return {'status': 'unknown', 'hours_old': 999}

        row = results[0]
        avg_hours = row.avg_hours_since_update or 999

        return {
            'status': 'fresh' if avg_hours < 4 else 'stale',
            'hours_old': round(avg_hours, 1),
            'players': row.players_with_features or 0
        }
    except Exception as e:
        print(f"Error querying feature quality: {e}")
        return {'status': 'error', 'hours_old': 999}


def count_recent_alerts() -> int:
    """Count alerts triggered in last 24 hours from Cloud Logging."""
    try:
        logging_client = cloud_logging.Client(project=PROJECT_ID)

        # Count ERROR severity logs with alert_type in last 24h
        yesterday = datetime.utcnow() - timedelta(hours=24)
        filter_str = f"""
        severity="ERROR"
        AND (jsonPayload.alert_type="ENV_VAR_CHANGE"
             OR jsonPayload.alert_type="MODEL_LOAD_FAILURE"
             OR jsonPayload.alert_type="HIGH_FALLBACK_RATE"
             OR jsonPayload.alert_type="CONFIDENCE_DRIFT"
             OR jsonPayload.alert_type="FEATURE_STALE")
        AND timestamp >= "{yesterday.isoformat()}Z"
        """

        entries = logging_client.list_entries(filter_=filter_str, page_size=100)
        alert_count = sum(1 for _ in entries)

        return alert_count
    except Exception as e:
        print(f"Error counting alerts: {e}")
        return -1  # Indicate error


def get_dlq_depth() -> int:
    """Get Dead Letter Queue message count using Cloud Monitoring API."""
    try:
        from google.cloud import monitoring_v3
        from google.protobuf import timestamp_pb2
        import time

        client = monitoring_v3.MetricServiceClient()
        project_name = f"projects/{PROJECT_ID}"

        # Query the num_undelivered_messages metric for our DLQ subscription
        now = time.time()
        seconds = int(now)
        nanos = int((now - seconds) * 10**9)

        interval = monitoring_v3.TimeInterval(
            {
                "end_time": {"seconds": seconds, "nanos": nanos},
                "start_time": {"seconds": seconds - 300, "nanos": nanos},  # Last 5 minutes
            }
        )

        # Filter for the specific DLQ subscription
        filter_str = (
            'metric.type = "pubsub.googleapis.com/subscription/num_undelivered_messages" '
            f'AND resource.labels.subscription_id = "prediction-request-dlq-sub"'
        )

        results = client.list_time_series(
            request={
                "name": project_name,
                "filter": filter_str,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            }
        )

        # Get the most recent value
        for result in results:
            if result.points:
                return int(result.points[0].value.int64_value)

        # No data found - subscription may be empty or not exist
        return 0
    except ImportError:
        print("Warning: google-cloud-monitoring not installed, DLQ depth unavailable")
        return -1
    except Exception as e:
        print(f"Error getting DLQ depth: {e}")
        return -1


def format_slack_message(
    summary: Dict[str, Any],
    top_picks: List[Dict[str, Any]],
    unique_stats: Dict[str, int],
    feature_quality: Dict[str, Any],
    alert_count: int,
    dlq_depth: int
) -> Dict[str, Any]:
    """Format data as Slack Block Kit message."""

    # Determine status emojis
    fallback_emoji = "✅" if summary['fallback_rate_pct'] < 10 else "⚠️" if summary['fallback_rate_pct'] < 30 else "🚨"
    systems_emoji = "✅" if summary['systems_operational'] >= 5 else "⚠️"
    feature_emoji = "✅" if feature_quality['status'] == 'fresh' else "⚠️"
    alerts_emoji = "🎉" if alert_count == 0 else "⚠️"

    # Format yesterday's date
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')

    # Build top picks text
    top_picks_text = ""
    for i, pick in enumerate(top_picks, 1):
        top_picks_text += (
            f"{i}. *{pick['player']}* {pick['recommendation']} {pick['line']} "
            f"({pick['confidence']:.1f}% conf) [{pick['system']}]\n"
        )

    if not top_picks_text:
        top_picks_text = "_No high-confidence picks yesterday_\n"

    # Build Slack blocks
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🏀 NBA Predictions Daily Summary - {yesterday}"
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*📊 Yesterday's Stats*\n"
                        f"• Predictions Generated: *{summary['total_predictions']:,}*\n"
                        f"• Unique Players: *{unique_stats['unique_players']}*\n"
                        f"• Systems Operational: *{summary['systems_operational']}/5* {systems_emoji}\n"
                        f"• Average Confidence: *{summary['overall_avg_confidence']:.1f}%*\n"
                        f"• Fallback Rate: *{summary['fallback_rate_pct']:.1f}%* {fallback_emoji}"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*📈 Recommendations Breakdown*\n"
                        f"• OVER: {summary['total_over']}\n"
                        f"• UNDER: {summary['total_under']}\n"
                        f"• PASS: {summary['total_pass']}"
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🎯 Top 5 Picks (by confidence)*\n{top_picks_text}"
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*⚙️ System Health*\n"
                        f"• Model Loading: {systems_emoji} All operational\n"
                        f"• Feature Quality: {feature_emoji} {feature_quality['status'].title()} "
                        f"({feature_quality['hours_old']}h old)\n"
                        f"• Alerts (24h): {alert_count if alert_count >= 0 else '?'} {alerts_emoji}"
            }
        }
    ]

    # Add DLQ status if available
    if dlq_depth >= 0:
        dlq_emoji = "✅" if dlq_depth < 50 else "⚠️"
        blocks[-1]['text']['text'] += f"\n• Dead Letter Queue: {dlq_depth} messages {dlq_emoji}"

    # Add links section
    blocks.extend([
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🔗 Quick Links*\n"
                        f"• <https://console.cloud.google.com/monitoring/dashboards?project={PROJECT_ID}|Dashboards>\n"
                        f"• <https://console.cloud.google.com/logs/query?project={PROJECT_ID}|Logs>\n"
                        f"• <https://console.cloud.google.com/bigquery?project={PROJECT_ID}&ws=!1m5!1m4!4m3!1s{PROJECT_ID}!2snba_predictions!3splayer_prop_predictions|BigQuery>"
            }
        }
    ])

    return {"blocks": blocks}


def send_to_slack(message: Dict[str, Any]) -> bool:
    """Send message to Slack webhook."""
    if not SLACK_WEBHOOK_URL:
        print("ERROR: SLACK_WEBHOOK_URL not set")
        return False

    try:
        response = requests.post(
            SLACK_WEBHOOK_URL,
            json=message,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )

        if response.status_code == 200:
            print("✅ Slack message sent successfully")
            return True
        else:
            print(f"❌ Slack webhook returned {response.status_code}: {response.text}")
            return False
    except requests.exceptions.Timeout:
        print("❌ Slack webhook timed out after 10s")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Connection error to Slack: {e}")
        return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Error sending to Slack: {e}")
        return False


@functions_framework.http
def send_daily_summary(request):
    """HTTP Cloud Function entrypoint."""
    print("🏀 NBA Prediction Daily Summary - Starting")

    # Initialize BigQuery client
    client = bigquery.Client(project=PROJECT_ID)

    try:
        # Query all data
        print("Querying yesterday's summary...")
        summary = query_yesterday_summary(client)

        print("Querying top picks...")
        top_picks = query_top_picks(client)

        print("Querying unique players...")
        unique_stats = query_unique_players(client)

        print("Checking feature quality...")
        feature_quality = query_feature_quality(client)

        print("Counting recent alerts...")
        alert_count = count_recent_alerts()

        print("Getting DLQ depth...")
        dlq_depth = get_dlq_depth()

        # Format Slack message
        print("Formatting Slack message...")
        slack_message = format_slack_message(
            summary, top_picks, unique_stats, feature_quality, alert_count, dlq_depth
        )

        # Send to Slack
        print("Sending to Slack...")
        success = send_to_slack(slack_message)

        if success:
            return {"status": "success", "message": "Daily summary sent to Slack"}, 200
        else:
            return {"status": "error", "message": "Failed to send to Slack"}, 500

    except Exception as e:
        print(f"❌ Error in send_daily_summary: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}, 500
