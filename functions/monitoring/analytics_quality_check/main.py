"""
Analytics Quality Check - Cloud Function

Validates analytics data quality BEFORE predictions run.
Alerts when key metrics fall below thresholds.

Schedule: 7:30 AM ET daily (after Phase 3, before predictions)
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple
import functions_framework

from google.cloud import bigquery


# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

# Alert thresholds
THRESHOLDS = {
    'usage_rate_coverage': 80.0,      # Alert if active players with usage_rate < 80%
    'minutes_coverage': 90.0,          # Alert if active players with minutes < 90%
    'min_active_players_per_game': 15, # Alert if any game has < 15 active players
    'min_games_expected': 1,           # Minimum games expected (skip alert if 0 games)
}


def get_analytics_quality(game_date: str) -> Dict:
    """Get analytics data quality metrics for a game date."""
    client = bigquery.Client(project=PROJECT_ID)

    query = f"""
    WITH game_stats AS (
        SELECT
            game_id,
            COUNT(*) as total_players,
            COUNTIF(is_dnp = FALSE) as active_players,
            COUNTIF(is_dnp = FALSE AND minutes_played IS NOT NULL AND minutes_played > 0) as has_minutes,
            COUNTIF(is_dnp = FALSE AND usage_rate IS NOT NULL AND usage_rate > 0) as has_usage_rate,
            COUNTIF(is_dnp = FALSE AND points IS NOT NULL) as has_points
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
        WHERE game_date = '{game_date}'
        GROUP BY game_id
    )
    SELECT
        COUNT(*) as game_count,
        SUM(active_players) as total_active,
        SUM(has_minutes) as total_with_minutes,
        SUM(has_usage_rate) as total_with_usage_rate,
        MIN(active_players) as min_active_per_game,
        ROUND(100.0 * SUM(has_minutes) / NULLIF(SUM(active_players), 0), 1) as minutes_coverage_pct,
        ROUND(100.0 * SUM(has_usage_rate) / NULLIF(SUM(active_players), 0), 1) as usage_rate_coverage_pct
    FROM game_stats
    """

    result = client.query(query).result()
    row = next(result)

    return {
        'game_date': game_date,
        'game_count': row.game_count or 0,
        'total_active': row.total_active or 0,
        'total_with_minutes': row.total_with_minutes or 0,
        'total_with_usage_rate': row.total_with_usage_rate or 0,
        'min_active_per_game': row.min_active_per_game or 0,
        'minutes_coverage_pct': row.minutes_coverage_pct or 0.0,
        'usage_rate_coverage_pct': row.usage_rate_coverage_pct or 0.0,
    }


def get_per_game_breakdown(game_date: str) -> List[Dict]:
    """Get per-game quality breakdown for detailed alerting."""
    client = bigquery.Client(project=PROJECT_ID)

    query = f"""
    SELECT
        game_id,
        COUNTIF(is_dnp = FALSE) as active_players,
        COUNTIF(is_dnp = FALSE AND usage_rate IS NOT NULL AND usage_rate > 0) as has_usage_rate,
        ROUND(100.0 * COUNTIF(is_dnp = FALSE AND usage_rate IS NOT NULL AND usage_rate > 0) /
            NULLIF(COUNTIF(is_dnp = FALSE), 0), 1) as usage_rate_pct
    FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
    WHERE game_date = '{game_date}'
    GROUP BY game_id
    ORDER BY usage_rate_pct ASC
    """

    result = client.query(query).result()
    return [dict(row) for row in result]


def check_quality_issues(metrics: Dict, per_game: List[Dict]) -> Tuple[List[str], str]:
    """Check for quality issues and return alerts with severity."""
    issues = []
    severity = 'OK'

    # Skip if no games
    if metrics['game_count'] < THRESHOLDS['min_games_expected']:
        return [], 'OK'

    # Check usage_rate coverage
    if metrics['usage_rate_coverage_pct'] == 0:
        issues.append(f"CRITICAL: 0% usage_rate coverage")
        severity = 'CRITICAL'
    elif metrics['usage_rate_coverage_pct'] < THRESHOLDS['usage_rate_coverage']:
        issues.append(f"usage_rate coverage {metrics['usage_rate_coverage_pct']}% < {THRESHOLDS['usage_rate_coverage']}%")
        if severity != 'CRITICAL':
            severity = 'WARNING'

    # Check minutes coverage
    if metrics['minutes_coverage_pct'] < THRESHOLDS['minutes_coverage']:
        issues.append(f"minutes coverage {metrics['minutes_coverage_pct']}% < {THRESHOLDS['minutes_coverage']}%")
        if severity != 'CRITICAL':
            severity = 'WARNING'

    # Check per-game active players
    low_active_games = [g for g in per_game if g['active_players'] < THRESHOLDS['min_active_players_per_game']]
    if low_active_games:
        for game in low_active_games:
            issues.append(f"Game {game['game_id']} has only {game['active_players']} active players")
        if severity != 'CRITICAL':
            severity = 'WARNING'

    # Check per-game usage_rate
    zero_usage_games = [g for g in per_game if g['usage_rate_pct'] == 0 and g['active_players'] > 0]
    if zero_usage_games:
        for game in zero_usage_games:
            issues.append(f"Game {game['game_id']} has 0% usage_rate ({game['active_players']} active)")
        severity = 'CRITICAL'

    return issues, severity


def format_slack_message(metrics: Dict, issues: List[str], severity: str) -> Dict:
    """Format Slack message for quality alert."""
    if not issues:
        return {
            "text": f"Analytics Quality Check: All metrics OK for {metrics['game_date']}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Analytics Quality Check* - {metrics['game_date']}\n\n"
                            f"*Status:* All metrics OK\n"
                            f"*Games:* {metrics['game_count']}\n"
                            f"*Active Players:* {metrics['total_active']}\n"
                            f"*Usage Rate Coverage:* {metrics['usage_rate_coverage_pct']}%\n"
                            f"*Minutes Coverage:* {metrics['minutes_coverage_pct']}%"
                        )
                    }
                }
            ]
        }

    emoji = "CRITICAL" if severity == 'CRITICAL' else "WARNING"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{emoji} Analytics Quality Check* - {metrics['game_date']}\n\n"
                    f"*{len(issues)} issue(s) detected*"
                )
            }
        },
        {"type": "divider"}
    ]

    # Add issues
    issue_text = "\n".join([f"- {issue}" for issue in issues[:10]])  # Limit to 10
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Issues:*\n{issue_text}"
        }
    })

    # Add metrics summary
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f"*Metrics Summary:*\n"
                f"- Games: {metrics['game_count']}\n"
                f"- Active Players: {metrics['total_active']}\n"
                f"- Usage Rate Coverage: {metrics['usage_rate_coverage_pct']}%\n"
                f"- Minutes Coverage: {metrics['minutes_coverage_pct']}%"
            )
        }
    })

    return {
        "text": f"{emoji} Analytics Quality Check: {len(issues)} issue(s) for {metrics['game_date']}",
        "blocks": blocks
    }


def send_slack_alert(message: Dict) -> bool:
    """Send alert to Slack."""
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL_WARNING')

    if not webhook_url:
        print("WARNING: SLACK_WEBHOOK_URL_WARNING not set")
        print(f"Message: {json.dumps(message, indent=2)}")
        return False

    try:
        response = requests.post(
            webhook_url,
            json=message,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        print(f"Error sending Slack alert: {e}")
        return False


@functions_framework.http
def run_check(request):
    """HTTP Cloud Function entrypoint."""
    # Get game_date from request or use yesterday
    game_date = request.args.get('game_date')
    if not game_date:
        # Default to yesterday (check data from yesterday's games)
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        game_date = yesterday.strftime('%Y-%m-%d')

    always_alert = request.args.get('always_alert') == 'true'

    print(f"=== Analytics Quality Check ===")
    print(f"Game Date: {game_date}")
    print()

    # Get metrics
    metrics = get_analytics_quality(game_date)
    per_game = get_per_game_breakdown(game_date)

    print(f"Games: {metrics['game_count']}")
    print(f"Active Players: {metrics['total_active']}")
    print(f"Usage Rate Coverage: {metrics['usage_rate_coverage_pct']}%")
    print(f"Minutes Coverage: {metrics['minutes_coverage_pct']}%")
    print()

    # Check for issues
    issues, severity = check_quality_issues(metrics, per_game)

    if issues:
        print(f"Issues found ({severity}):")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("No issues found")

    # Send alert if issues found or always_alert
    if issues or always_alert:
        message = format_slack_message(metrics, issues, severity)
        sent = send_slack_alert(message)
        print(f"Slack alert sent: {sent}")

    # Return response
    response_data = {
        'game_date': game_date,
        'status': severity,
        'issues': issues,
        'metrics': metrics,
        'per_game': per_game,
    }

    status_code = 200 if severity == 'OK' else (500 if severity == 'CRITICAL' else 400)
    return json.dumps(response_data), status_code
