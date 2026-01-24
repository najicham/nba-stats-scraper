"""
Shadow Performance Report Cloud Function

Sends weekly Slack report on filtered predictions' shadow performance.
Monitors the 88-90 confidence tier to track if performance improves.

Purpose:
- Track shadow performance of filtered picks (is_actionable = false)
- Compare to active tiers for context
- Identify trends that might warrant re-enabling filtered tiers

Triggered by: Cloud Scheduler (recommended: Monday 9 AM ET)

Deployment:
    gcloud functions deploy shadow-performance-report \
        --gen2 \
        --runtime python311 \
        --region us-west2 \
        --source orchestration/cloud_functions/shadow_performance_report \
        --entry-point send_shadow_report \
        --trigger-http \
        --allow-unauthenticated \
        --set-env-vars GCP_PROJECT=nba-props-platform,SLACK_WEBHOOK_URL=$SLACK_WEBHOOK_URL

Scheduler:
    gcloud scheduler jobs create http shadow-performance-report-job \
        --schedule "0 9 * * 1" \
        --time-zone "America/New_York" \
        --uri https://FUNCTION_URL \
        --http-method GET \
        --location us-west2

Version: 1.0
Created: 2026-01-10
"""

import logging
import os
from datetime import date, timedelta
from typing import Dict, List, Optional

from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client
from shared.utils.slack_retry import send_slack_webhook_with_retry
import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')

# Re-enabling threshold
RE_ENABLE_HIT_RATE_THRESHOLD = 70.0


def get_shadow_performance(bq_client: bigquery.Client, weeks_back: int = 4) -> List[Dict]:
    """
    Get shadow performance for filtered picks over recent weeks.

    Returns weekly breakdown of filtered tier performance.
    """
    query = f"""
    SELECT
        filter_reason,
        DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,
        COUNT(*) as picks,
        COUNTIF(prediction_correct = true) as wins,
        COUNTIF(prediction_correct = false) as losses,
        ROUND(SAFE_DIVIDE(
            COUNTIF(prediction_correct = true),
            NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0)
        ) * 100, 1) as hit_rate,
        ROUND((COUNTIF(prediction_correct = true) * 91.0 -
               COUNTIF(prediction_correct = false) * 100.0) /
              NULLIF(COUNT(*) * 110.0, 0) * 100, 1) as roi
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE is_actionable = false
        AND filter_reason IS NOT NULL
        AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks_back * 7} DAY)
        AND prediction_correct IS NOT NULL
    GROUP BY 1, 2
    ORDER BY 2 DESC, 1
    """

    result = bq_client.query(query).result()
    return [dict(row) for row in result]


def get_active_tier_performance(bq_client: bigquery.Client, weeks_back: int = 4) -> Dict:
    """
    Get performance of active (non-filtered) picks for comparison.
    """
    query = f"""
    SELECT
        COUNT(*) as picks,
        COUNTIF(prediction_correct = true) as wins,
        COUNTIF(prediction_correct = false) as losses,
        ROUND(SAFE_DIVIDE(
            COUNTIF(prediction_correct = true),
            NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0)
        ) * 100, 1) as hit_rate,
        ROUND((COUNTIF(prediction_correct = true) * 91.0 -
               COUNTIF(prediction_correct = false) * 100.0) /
              NULLIF(COUNT(*) * 110.0, 0) * 100, 1) as roi
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE (is_actionable = true OR is_actionable IS NULL)
        AND has_prop_line = true
        AND recommendation IN ('OVER', 'UNDER')
        AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks_back * 7} DAY)
        AND prediction_correct IS NOT NULL
    """

    result = bq_client.query(query).result()
    row = list(result)[0]
    return {
        'picks': row.picks or 0,
        'wins': row.wins or 0,
        'losses': row.losses or 0,
        'hit_rate': row.hit_rate,
        'roi': row.roi,
    }


def get_monthly_trend(bq_client: bigquery.Client, filter_reason: str) -> List[Dict]:
    """
    Get monthly hit rate trend for a specific filter reason.
    Used to check re-enabling criteria (70%+ for 3 consecutive months).
    """
    query = f"""
    SELECT
        DATE_TRUNC(game_date, MONTH) as month,
        COUNT(*) as picks,
        ROUND(SAFE_DIVIDE(
            COUNTIF(prediction_correct = true),
            NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0)
        ) * 100, 1) as hit_rate
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE filter_reason = @filter_reason
        AND prediction_correct IS NOT NULL
    GROUP BY 1
    ORDER BY 1 DESC
    LIMIT 3
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("filter_reason", "STRING", filter_reason)
        ]
    )

    result = bq_client.query(query, job_config=job_config).result()
    return [dict(row) for row in result]


def check_re_enable_criteria(monthly_trend: List[Dict]) -> Dict:
    """
    Check if filtered tier meets re-enabling criteria.

    Criteria:
    - Hit rate > 70% for 3 consecutive months
    - At least 200 picks per month
    """
    if len(monthly_trend) < 3:
        return {
            'meets_criteria': False,
            'reason': f'Only {len(monthly_trend)} months of data (need 3)'
        }

    all_above_threshold = all(
        m['hit_rate'] and m['hit_rate'] >= RE_ENABLE_HIT_RATE_THRESHOLD
        for m in monthly_trend[:3]
    )

    all_sufficient_sample = all(
        m['picks'] and m['picks'] >= 200
        for m in monthly_trend[:3]
    )

    if not all_sufficient_sample:
        return {
            'meets_criteria': False,
            'reason': 'Insufficient sample size (<200 picks/month)'
        }

    if not all_above_threshold:
        return {
            'meets_criteria': False,
            'reason': f'Hit rate below {RE_ENABLE_HIT_RATE_THRESHOLD}% in one or more months'
        }

    return {
        'meets_criteria': True,
        'reason': 'All criteria met - consider re-enabling!'
    }


def format_trend_arrow(current: float, previous: float) -> str:
    """Format trend indicator arrow."""
    if current is None or previous is None:
        return ""
    diff = current - previous
    if diff > 2:
        return "↑↑"
    elif diff > 0:
        return "↑"
    elif diff < -2:
        return "↓↓"
    elif diff < 0:
        return "↓"
    return "→"


def build_slack_message(
    shadow_data: List[Dict],
    active_performance: Dict,
    monthly_trend: List[Dict],
    re_enable_check: Dict
) -> Dict:
    """Build formatted Slack message."""

    # Get this week and last week data
    this_week = shadow_data[0] if shadow_data else None
    last_week = shadow_data[1] if len(shadow_data) > 1 else None

    # Calculate trend
    trend_arrow = ""
    if this_week and last_week and this_week.get('hit_rate') and last_week.get('hit_rate'):
        trend_arrow = format_trend_arrow(this_week['hit_rate'], last_week['hit_rate'])

    # Determine status emoji
    if this_week and this_week.get('hit_rate'):
        if this_week['hit_rate'] >= 70:
            status_emoji = ":chart_with_upwards_trend:"
            status_text = "Improving - approaching threshold"
        elif this_week['hit_rate'] >= 52.4:  # Breakeven at -110
            status_emoji = ":bar_chart:"
            status_text = "Profitable but below threshold"
        else:
            status_emoji = ":chart_with_downwards_trend:"
            status_text = "Below breakeven"
    else:
        status_emoji = ":grey_question:"
        status_text = "No data this week"

    # Format weekly breakdown
    weeks_text = ""
    for week_data in shadow_data[:4]:
        week_str = week_data['week_start'].strftime('%m/%d') if hasattr(week_data['week_start'], 'strftime') else str(week_data['week_start'])[:10]
        hr = week_data.get('hit_rate', 'N/A')
        hr_str = f"{hr}%" if hr else "N/A"
        picks = week_data.get('picks', 0)
        weeks_text += f"• {week_str}: {hr_str} ({picks} picks)\n"

    # Build blocks
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{status_emoji} Weekly Shadow Performance Report",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*88-90 Confidence Tier (Filtered)*\nTracking shadow performance to determine if this tier should be re-enabled."
            }
        }
    ]

    # This week's stats
    if this_week:
        blocks.append({
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*This Week:*\n{this_week.get('hit_rate', 'N/A')}% {trend_arrow}"},
                {"type": "mrkdwn", "text": f"*Picks:*\n{this_week.get('picks', 0)} ({this_week.get('wins', 0)}W-{this_week.get('losses', 0)}L)"},
                {"type": "mrkdwn", "text": f"*ROI:*\n{this_week.get('roi', 'N/A')}%"},
                {"type": "mrkdwn", "text": f"*Status:*\n{status_text}"},
            ]
        })

    # Weekly trend
    if weeks_text:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Weekly Breakdown:*\n{weeks_text}"
            }
        })

    # Comparison to active tiers
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Active Tiers (90+) Comparison:*\n{active_performance.get('hit_rate', 'N/A')}% hit rate | {active_performance.get('picks', 0)} picks | {active_performance.get('roi', 'N/A')}% ROI"
        }
    })

    # Re-enable status
    re_enable_emoji = ":white_check_mark:" if re_enable_check['meets_criteria'] else ":x:"
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Re-enable Check:* {re_enable_emoji}\n{re_enable_check['reason']}\n_Criteria: 70%+ hit rate for 3 consecutive months with 200+ picks/month_"
        }
    })

    # Divider and footer
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"See `FILTER-DECISIONS.md` for rollback instructions | Data from `v_shadow_performance` view"
            }
        ]
    })

    return {"blocks": blocks}


def send_slack_message(message: Dict) -> bool:
    """Send message to Slack webhook."""
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not configured, skipping Slack message")
        return False

    try:
        success = send_slack_webhook_with_retry(SLACK_WEBHOOK_URL, message, timeout=10)
        if success:
            logger.info("Slack message sent successfully")
        return success
    except Exception as e:
        logger.error(f"Failed to send Slack message: {e}")
        return False


@functions_framework.http
def send_shadow_report(request):
    """
    Main Cloud Function entry point.

    Generates and sends weekly shadow performance report.

    Query params:
        weeks_back: Number of weeks to include (default: 4)
        dry_run: If 'true', don't send to Slack, just return data

    Returns:
        JSON response with report data and send status.
    """
    try:
        # Parse request
        weeks_back = int(request.args.get('weeks_back', '4'))
        dry_run = request.args.get('dry_run', 'false').lower() == 'true'

        logger.info(f"Generating shadow performance report (weeks_back={weeks_back}, dry_run={dry_run})")

        # Get data
        bq_client = get_bigquery_client(project_id=PROJECT_ID)

        shadow_data = get_shadow_performance(bq_client, weeks_back)
        active_performance = get_active_tier_performance(bq_client, weeks_back)

        # Get monthly trend for 88-90 tier
        monthly_trend = get_monthly_trend(bq_client, 'confidence_tier_88_90')
        re_enable_check = check_re_enable_criteria(monthly_trend)

        logger.info(f"Shadow data: {len(shadow_data)} weeks, Active: {active_performance}")
        logger.info(f"Re-enable check: {re_enable_check}")

        # Build message
        message = build_slack_message(
            shadow_data,
            active_performance,
            monthly_trend,
            re_enable_check
        )

        # Send to Slack
        sent = False
        if not dry_run:
            sent = send_slack_message(message)

        # Build response
        response = {
            'shadow_weeks': len(shadow_data),
            'this_week': shadow_data[0] if shadow_data else None,
            'active_performance': active_performance,
            'monthly_trend': [
                {'month': str(m['month']), 'picks': m['picks'], 'hit_rate': m['hit_rate']}
                for m in monthly_trend
            ],
            're_enable_check': re_enable_check,
            'message_sent': sent,
            'dry_run': dry_run,
        }

        # Convert date objects for JSON serialization
        if response['this_week'] and 'week_start' in response['this_week']:
            response['this_week']['week_start'] = str(response['this_week']['week_start'])

        return response, 200

    except Exception as e:
        logger.exception(f"Error generating shadow report: {e}")
        return {'error': str(e)}, 500


@functions_framework.http
def health(request):
    """Health check endpoint for shadow_performance_report."""
    return json.dumps({
        'status': 'healthy',
        'function': 'shadow_performance_report',
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}
