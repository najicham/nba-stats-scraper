"""
Game Coverage Alert Cloud Function
===================================
Alerts when prediction coverage is insufficient before games start.

Triggered by Cloud Scheduler 2 hours before first game of the day.
Checks that all games have adequate prediction coverage and alerts
if any game has fewer than MIN_PLAYERS_PER_GAME players with predictions.

This function was created after the Jan 23, 2026 incident where
TOR@POR had 0 predictions due to stale ESPN roster data.

Version: 1.0
Created: 2026-01-24
"""

import logging
import os
from datetime import date, datetime, timezone, timedelta
from typing import Dict, List, Optional

from google.cloud import bigquery
import functions_framework

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')

# Alert thresholds
MIN_PLAYERS_PER_GAME = 8  # Alert if fewer than 8 players have predictions
MIN_PREDICTIONS_PER_PLAYER = 3  # Minimum predictions per player to count


@functions_framework.http
def game_coverage_alert(request):
    """
    Check prediction coverage for today's games and alert if insufficient.

    Triggered by Cloud Scheduler.

    Query params:
        - date: Optional date to check (YYYY-MM-DD), defaults to today
        - dry_run: If true, don't send alerts (just log)

    Returns:
        JSON response with coverage status
    """
    try:
        # Parse request
        request_json = request.get_json(silent=True) or {}
        request_args = request.args

        date_str = (
            request_json.get('date') or
            request_args.get('date') or
            date.today().isoformat()
        )
        dry_run = request_json.get('dry_run', False) or request_args.get('dry_run', 'false').lower() == 'true'

        logger.info(f"Checking game coverage for {date_str} (dry_run={dry_run})")

        # Initialize BigQuery client
        bq_client = bigquery.Client(project=PROJECT_ID)

        # Get coverage data
        coverage = get_game_coverage(bq_client, date_str)

        if not coverage['games']:
            logger.info(f"No games scheduled for {date_str}")
            return {'status': 'no_games', 'date': date_str}, 200

        # Check for issues
        issues = []
        for game in coverage['games']:
            if game['player_count'] < MIN_PLAYERS_PER_GAME:
                issues.append(game)

        coverage['issues'] = issues
        coverage['has_issues'] = len(issues) > 0

        if issues:
            logger.warning(f"Found {len(issues)} games with insufficient coverage")

            if not dry_run:
                send_coverage_alert(coverage)
            else:
                logger.info("DRY RUN: Would have sent alert")

            return {
                'status': 'alert_sent' if not dry_run else 'alert_skipped_dry_run',
                'date': date_str,
                'issues_count': len(issues),
                'coverage': coverage
            }, 200
        else:
            logger.info(f"All {len(coverage['games'])} games have adequate coverage")
            return {
                'status': 'ok',
                'date': date_str,
                'games_count': len(coverage['games']),
                'coverage': coverage
            }, 200

    except Exception as e:
        logger.error(f"Error checking game coverage: {e}", exc_info=True)
        return {'status': 'error', 'error': str(e)}, 500


def get_game_coverage(bq_client: bigquery.Client, date_str: str) -> Dict:
    """
    Query prediction coverage per game.

    Args:
        bq_client: BigQuery client
        date_str: Date to check (YYYY-MM-DD)

    Returns:
        Dictionary with game coverage data
    """
    query = f"""
    WITH scheduled_games AS (
        SELECT
            game_id,
            home_team_tricode,
            away_team_tricode,
            game_time_utc
        FROM `{PROJECT_ID}.nba_reference.nba_schedule`
        WHERE game_date = @game_date
    ),
    prediction_coverage AS (
        SELECT
            game_id,
            COUNT(DISTINCT player_lookup) as player_count,
            COUNT(*) as prediction_count
        FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        WHERE game_date = @game_date
          AND is_active = TRUE
        GROUP BY game_id
    ),
    feature_coverage AS (
        SELECT
            game_id,
            COUNT(*) as feature_count,
            COUNTIF(is_production_ready) as production_ready_count
        FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
        WHERE game_date = @game_date
        GROUP BY game_id
    )
    SELECT
        s.game_id,
        s.home_team_tricode,
        s.away_team_tricode,
        s.game_time_utc,
        COALESCE(p.player_count, 0) as player_count,
        COALESCE(p.prediction_count, 0) as prediction_count,
        COALESCE(f.feature_count, 0) as feature_count,
        COALESCE(f.production_ready_count, 0) as production_ready_count,
        CASE
            WHEN p.player_count IS NULL THEN 'NO_PREDICTIONS'
            WHEN p.player_count < @min_players THEN 'LOW_COVERAGE'
            ELSE 'OK'
        END as status
    FROM scheduled_games s
    LEFT JOIN prediction_coverage p ON s.game_id = p.game_id
    LEFT JOIN feature_coverage f ON s.game_id = f.game_id
    ORDER BY s.game_time_utc
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", date_str),
            bigquery.ScalarQueryParameter("min_players", "INT64", MIN_PLAYERS_PER_GAME),
        ]
    )

    games = []
    total_players = 0
    total_predictions = 0

    for row in bq_client.query(query, job_config=job_config):
        game = {
            'game_id': row.game_id,
            'matchup': f"{row.away_team_tricode}@{row.home_team_tricode}",
            'game_time_utc': row.game_time_utc.isoformat() if row.game_time_utc else None,
            'player_count': row.player_count,
            'prediction_count': row.prediction_count,
            'feature_count': row.feature_count,
            'production_ready_count': row.production_ready_count,
            'status': row.status
        }
        games.append(game)
        total_players += row.player_count
        total_predictions += row.prediction_count

    return {
        'date': date_str,
        'games': games,
        'game_count': len(games),
        'total_players': total_players,
        'total_predictions': total_predictions,
        'checked_at': datetime.now(timezone.utc).isoformat()
    }


def send_coverage_alert(coverage: Dict) -> bool:
    """
    Send alert via Slack for games with insufficient coverage.

    Args:
        coverage: Coverage data dictionary

    Returns:
        True if alert sent successfully
    """
    try:
        from shared.utils.slack_alerting import send_slack_alert

        # Build alert message
        issues = coverage.get('issues', [])
        date_str = coverage['date']

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f":warning: Game Coverage Alert - {date_str}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{len(issues)} game(s)* have insufficient prediction coverage (< {MIN_PLAYERS_PER_GAME} players)"
                }
            },
            {"type": "divider"}
        ]

        for game in issues:
            status_emoji = ":x:" if game['player_count'] == 0 else ":warning:"
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{status_emoji} *{game['matchup']}*\n"
                        f"Players: {game['player_count']} | "
                        f"Predictions: {game['prediction_count']} | "
                        f"Features: {game['feature_count']}"
                    )
                }
            })

        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"*Action needed:* Check roster freshness and upstream processors. "
                        f"Run `python3 -m monitoring.nba.roster_coverage_monitor` to diagnose."
                    )
                }
            ]
        })

        # Send to #nba-alerts channel
        success = send_slack_alert(
            channel='#nba-alerts',
            text=f"Game Coverage Alert: {len(issues)} games have low prediction coverage",
            blocks=blocks
        )

        if success:
            logger.info(f"Sent coverage alert to Slack for {len(issues)} games")
        return success

    except ImportError:
        logger.warning("Slack alerting not available, falling back to logging")
        for game in coverage.get('issues', []):
            logger.error(f"LOW COVERAGE: {game['matchup']} - {game['player_count']} players")
        return False
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


def get_first_game_time(bq_client: bigquery.Client, date_str: str) -> Optional[datetime]:
    """
    Get the start time of the first game on the given date.

    Args:
        bq_client: BigQuery client
        date_str: Date to check

    Returns:
        datetime of first game, or None if no games
    """
    query = f"""
    SELECT MIN(game_time_utc) as first_game
    FROM `{PROJECT_ID}.nba_reference.nba_schedule`
    WHERE game_date = @game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", date_str),
        ]
    )

    result = list(bq_client.query(query, job_config=job_config))
    if result and result[0].first_game:
        return result[0].first_game
    return None
