#!/usr/bin/env python3
"""
Data Completeness Checker Cloud Function

Runs daily to check for missing games in BigQuery.
Compares NBA schedule against actual data from both:
- NBA.com Gamebook player stats
- Ball Don't Lie (BDL) player box scores

Sends email alerts when games are missing or incomplete.
Logs results to orchestration tables for trending.

Triggered by Cloud Scheduler daily at 9 AM ET (14:00 UTC).
"""

import functions_framework
from google.cloud import bigquery
from datetime import datetime
import os
import sys
import logging
import uuid

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path for imports
sys.path.insert(0, '/workspace')

def send_email_alert(missing_games, check_id):
    """Send email with missing games report."""
    try:
        import boto3
        from botocore.exceptions import ClientError

        # Get AWS SES credentials from environment
        aws_region = os.environ.get('AWS_SES_REGION', 'us-west-2')
        aws_access_key = os.environ.get('AWS_SES_ACCESS_KEY_ID')
        aws_secret_key = os.environ.get('AWS_SES_SECRET_ACCESS_KEY')
        from_email = os.environ.get('AWS_SES_FROM_EMAIL', 'alert@989.ninja')
        from_name = os.environ.get('AWS_SES_FROM_NAME', 'NBA Data Pipeline')
        to_emails = os.environ.get('EMAIL_ALERTS_TO', '').split(',')
        to_emails = [email.strip() for email in to_emails if email.strip()]

        if not aws_access_key or not aws_secret_key:
            logger.error("AWS SES credentials not configured")
            return False

        if not to_emails:
            logger.warning("No email recipients configured")
            return False

        # Initialize AWS SES client
        ses_client = boto3.client(
            'ses',
            region_name=aws_region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key
        )

        # Build subject and body
        subject = f"Data Completeness Alert - {len(missing_games)} Missing/Incomplete Games"
        body_html = format_html_report(missing_games, check_id)

        # Send email
        response = ses_client.send_email(
            Source=f"{from_name} <{from_email}>",
            Destination={'ToAddresses': to_emails},
            Message={
                'Subject': {
                    'Data': f"[NBA Pipeline WARNING] {subject}",
                    'Charset': 'UTF-8'
                },
                'Body': {
                    'Html': {
                        'Data': body_html,
                        'Charset': 'UTF-8'
                    }
                }
            }
        )

        logger.info(f"Email alert sent successfully. MessageId: {response['MessageId']}")
        return True

    except ClientError as e:
        logger.error(f"AWS SES error: {e.response['Error']['Message']}")
        return False
    except Exception as e:
        logger.error(f"Failed to send email alert: {e}", exc_info=True)
        return False


def format_html_report(missing_games, check_id):
    """Format missing games as HTML table."""
    import html

    # Group by date
    by_date = {}
    for game in missing_games:
        date = str(game['game_date'])
        if date not in by_date:
            by_date[date] = []
        by_date[date].append(game)

    # Build summary stats
    total_missing = len(missing_games)
    gamebook_missing = sum(1 for g in missing_games if g['gamebook_status'] != 'OK')
    bdl_missing = sum(1 for g in missing_games if g['bdl_status'] != 'OK')

    # Build table rows
    table_rows = ""
    for date in sorted(by_date.keys(), reverse=True):
        for game in by_date[date]:
            gamebook_cell = format_status_cell(
                game['gamebook_status'],
                game.get('gamebook_players', 0)
            )
            bdl_cell = format_status_cell(
                game['bdl_status'],
                game.get('bdl_players', 0)
            )

            table_rows += f"""
            <tr>
                <td>{html.escape(date)}</td>
                <td>{html.escape(game['game_code'])}</td>
                <td>{html.escape(game['matchup'])}</td>
                {gamebook_cell}
                {bdl_cell}
            </tr>
            """

    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif;">
        <h2 style="color: #ff9800;">🚨 Daily Data Completeness Report</h2>
        <p><strong>Check Time:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>
        <p><strong>Check ID:</strong> <code>{html.escape(check_id)}</code></p>

        <h3>Summary</h3>
        <ul>
            <li><strong>Total Issues:</strong> {total_missing} games</li>
            <li><strong>Gamebook Issues:</strong> {gamebook_missing} games</li>
            <li><strong>BDL Issues:</strong> {bdl_missing} games</li>
        </ul>

        <h3>Missing/Incomplete Games</h3>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; width: 100%;">
        <tr style="background-color: #f5f5f5;">
            <th>Date</th>
            <th>Game Code</th>
            <th>Matchup</th>
            <th>Gamebook</th>
            <th>BDL</th>
        </tr>
        {table_rows}
        </table>

        <h3>Recommended Actions</h3>
        <ol>
            <li>Check scraper logs for failed executions (Phase 1)</li>
            <li>Verify GCS files exist for missing games:
                <ul>
                    <li><code>gs://nba-scraped-data/nba-com/gamebooks-data/[date]/</code></li>
                    <li><code>gs://nba-scraped-data/ball-dont-lie/player-box-scores/[date]/</code></li>
                </ul>
            </li>
            <li>Check processor logs for errors (Phase 2)</li>
            <li>Trigger backfill if data exists in GCS but not BigQuery</li>
        </ol>

        <h3>Query Used</h3>
        <p>Check query: <code>functions/monitoring/data_completeness_checker/check_data_completeness.sql</code></p>

        <hr>
        <p style="color: #666; font-size: 12px;">
            This is an automated daily report from the NBA Stats Pipeline Data Completeness Checker.
            <br>
            Runs daily at 9 AM ET (14:00 UTC).
        </p>
    </body>
    </html>
    """

    return html_body


def format_status_cell(status, player_count):
    """Format a status cell with color coding."""
    if status == 'MISSING':
        return '<td style="background-color: #ffcdd2; color: #d32f2f;">❌ MISSING (0 players)</td>'
    elif status == 'INCOMPLETE':
        return f'<td style="background-color: #fff3cd; color: #ff9800;">⚠️ INCOMPLETE ({player_count} players)</td>'
    else:
        return f'<td style="background-color: #d4edda; color: #28a745;">✅ OK ({player_count} players)</td>'


def log_check_result(bq_client, check_id, missing_count, alert_sent, duration_sec, status="success"):
    """Log check result to orchestration table."""
    try:
        table_id = "nba-props-platform.nba_orchestration.data_completeness_checks"

        rows = [{
            'check_id': check_id,
            'check_timestamp': datetime.utcnow().isoformat(),
            'missing_games_count': missing_count,
            'alert_sent': alert_sent,
            'check_duration_seconds': duration_sec,
            'status': status
        }]

        errors = bq_client.insert_rows_json(table_id, rows)

        if errors:
            logger.error(f"Failed to log check result: {errors}")
        else:
            logger.info(f"Logged check result: {check_id}")

    except Exception as e:
        logger.error(f"Failed to log check result: {e}", exc_info=True)


def log_missing_games(bq_client, check_id, missing_games):
    """Log missing games to orchestration table for trending."""
    try:
        table_id = "nba-props-platform.nba_orchestration.missing_games_log"

        rows = []
        for game in missing_games:
            row = {
                'log_id': str(uuid.uuid4()),
                'check_id': check_id,
                'game_date': str(game['game_date']),
                'game_code': game['game_code'],
                'matchup': game['matchup'],
                'gamebook_missing': game['gamebook_status'] != 'OK',
                'bdl_missing': game['bdl_status'] != 'OK',
                'discovered_at': datetime.utcnow().isoformat(),
                'backfilled_at': None
            }
            rows.append(row)

        errors = bq_client.insert_rows_json(table_id, rows)

        if errors:
            logger.error(f"Failed to log missing games: {errors}")
        else:
            logger.info(f"Logged {len(rows)} missing games for check {check_id}")

    except Exception as e:
        logger.error(f"Failed to log missing games: {e}", exc_info=True)


@functions_framework.http
def check_completeness(request):
    """
    Cloud Function entrypoint.

    Checks data completeness by comparing NBA schedule vs actual data.
    Sends email alerts if games are missing or incomplete.
    Logs results to BigQuery orchestration tables.

    Returns:
        JSON response with check results and HTTP status code
    """
    start_time = datetime.utcnow()
    check_id = f"check_{start_time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    logger.info(f"Starting data completeness check: {check_id}")

    try:
        # Initialize BigQuery client
        project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        bq_client = bigquery.Client(project=project_id)

        # Read and execute completeness query
        sql_path = os.path.join(os.path.dirname(__file__), 'check_data_completeness.sql')
        with open(sql_path, 'r') as f:
            query = f.read()

        logger.info("Executing completeness query...")
        query_job = bq_client.query(query)
        results = list(query_job.result(timeout=60))

        # Calculate duration
        duration_sec = (datetime.utcnow() - start_time).total_seconds()

        if results:
            # Missing or incomplete games found
            missing_games = [dict(row) for row in results]
            missing_count = len(missing_games)

            logger.warning(f"Found {missing_count} missing/incomplete games")

            # Send email alert
            alert_sent = send_email_alert(missing_games, check_id)

            # Log results
            log_check_result(bq_client, check_id, missing_count, alert_sent, duration_sec)
            log_missing_games(bq_client, check_id, missing_games)

            # Return response
            return {
                'status': 'alert_sent' if alert_sent else 'alert_failed',
                'check_id': check_id,
                'missing_games_count': missing_count,
                'alert_sent': alert_sent,
                'duration_seconds': duration_sec,
                'games': missing_games
            }, 200

        else:
            # All games present - success!
            logger.info("All games accounted for - no issues found")

            # Log success
            log_check_result(bq_client, check_id, 0, False, duration_sec)

            return {
                'status': 'ok',
                'check_id': check_id,
                'message': 'All games accounted for',
                'missing_games_count': 0,
                'duration_seconds': duration_sec
            }, 200

    except Exception as e:
        # Log error
        duration_sec = (datetime.utcnow() - start_time).total_seconds()
        logger.error(f"Data completeness check failed: {e}", exc_info=True)

        try:
            log_check_result(bq_client, check_id, 0, False, duration_sec, status="error")
        except:
            pass

        return {
            'status': 'error',
            'check_id': check_id,
            'error': str(e),
            'duration_seconds': duration_sec
        }, 500


# For local testing
if __name__ == '__main__':
    import json

    class MockRequest:
        pass

    result, status = check_completeness(MockRequest())
    print(json.dumps(result, indent=2, default=str))
    print(f"Status: {status}")
