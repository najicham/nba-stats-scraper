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

# Freshness monitoring configuration
# Each check monitors when data was last updated
FRESHNESS_CHECKS = [
    {
        'table': 'nba_raw.bdl_injuries',
        'threshold_hours': 24,
        'timestamp_column': 'processed_at',
        'severity': 'CRITICAL',
        'description': 'Injury data from BallDontLie API'
    },
    {
        'table': 'nba_raw.odds_api_player_points_props',
        'threshold_hours': 12,
        'timestamp_column': 'created_at',
        'severity': 'WARNING',
        'description': 'Player props from Odds API'
    },
    {
        'table': 'nba_raw.bettingpros_player_points_props',
        'threshold_hours': 12,
        'timestamp_column': 'created_at',
        'severity': 'WARNING',
        'description': 'Player props from BettingPros'
    },
    {
        'table': 'nba_analytics.player_game_summary',
        'threshold_hours': 24,
        'timestamp_column': 'updated_at',
        'severity': 'WARNING',
        'description': 'Player analytics summaries'
    },
    {
        'table': 'nba_predictions.player_composite_factors',
        'threshold_hours': 24,
        'timestamp_column': 'created_at',
        'severity': 'WARNING',
        'description': 'ML feature store for predictions'
    }
]

def check_freshness(bq_client, project_id):
    """
    Check data freshness for critical tables.

    Returns list of tables with stale data (exceeding freshness threshold).

    Args:
        bq_client: BigQuery client instance
        project_id: GCP project ID

    Returns:
        List of dicts with freshness issues:
        [{
            'table': 'nba_raw.bdl_injuries',
            'hours_stale': 36.5,
            'threshold_hours': 24,
            'severity': 'CRITICAL',
            'description': 'Injury data from BallDontLie API',
            'last_update': '2026-01-01 10:00:00 UTC'
        }]
    """
    stale_tables = []

    for check in FRESHNESS_CHECKS:
        try:
            query = f"""
            SELECT
                TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX({check['timestamp_column']}), HOUR) as hours_stale,
                MAX({check['timestamp_column']}) as last_update
            FROM `{project_id}.{check['table']}`
            """

            logger.info(f"Checking freshness for {check['table']}")
            query_job = bq_client.query(query)
            results = list(query_job.result(timeout=30))

            if not results:
                # No data in table at all - critical issue
                stale_tables.append({
                    'table': check['table'],
                    'hours_stale': None,
                    'threshold_hours': check['threshold_hours'],
                    'severity': 'CRITICAL',
                    'description': check['description'],
                    'last_update': 'NEVER',
                    'issue': 'NO DATA'
                })
                logger.warning(f"Table {check['table']} has NO DATA")
                continue

            row = results[0]
            hours_stale = row.hours_stale
            last_update = row.last_update

            if hours_stale is None:
                # NULL timestamp column - critical issue
                stale_tables.append({
                    'table': check['table'],
                    'hours_stale': None,
                    'threshold_hours': check['threshold_hours'],
                    'severity': 'CRITICAL',
                    'description': check['description'],
                    'last_update': 'NULL',
                    'issue': 'NULL TIMESTAMPS'
                })
                logger.warning(f"Table {check['table']} has NULL timestamps")
                continue

            if hours_stale > check['threshold_hours']:
                stale_tables.append({
                    'table': check['table'],
                    'hours_stale': round(hours_stale, 1),
                    'threshold_hours': check['threshold_hours'],
                    'severity': check['severity'],
                    'description': check['description'],
                    'last_update': str(last_update),
                    'issue': 'STALE'
                })
                logger.warning(
                    f"Table {check['table']} is STALE: "
                    f"{hours_stale:.1f}h old (threshold: {check['threshold_hours']}h)"
                )
            else:
                logger.info(
                    f"Table {check['table']} is FRESH: "
                    f"{hours_stale:.1f}h old (threshold: {check['threshold_hours']}h)"
                )

        except Exception as e:
            # If check fails, log but continue with other checks
            logger.error(f"Failed to check freshness for {check['table']}: {e}")
            stale_tables.append({
                'table': check['table'],
                'hours_stale': None,
                'threshold_hours': check['threshold_hours'],
                'severity': 'CRITICAL',
                'description': check['description'],
                'last_update': 'ERROR',
                'issue': f'CHECK FAILED: {str(e)[:100]}'
            })

    return stale_tables

def send_email_alert(missing_games, stale_tables, check_id):
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
        total_issues = len(missing_games) + len(stale_tables)
        subject_parts = []
        if missing_games:
            subject_parts.append(f"{len(missing_games)} Missing/Incomplete Games")
        if stale_tables:
            subject_parts.append(f"{len(stale_tables)} Stale Tables")
        subject = f"Data Completeness Alert - {' + '.join(subject_parts)}"
        body_html = format_html_report(missing_games, stale_tables, check_id)

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


def format_html_report(missing_games, stale_tables, check_id):
    """Format missing games and stale tables as HTML report."""
    import html

    # Group missing games by date
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
    total_stale = len(stale_tables)
    critical_stale = sum(1 for t in stale_tables if t['severity'] == 'CRITICAL')

    # Build missing games table rows
    games_table_rows = ""
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

            games_table_rows += f"""
            <tr>
                <td>{html.escape(date)}</td>
                <td>{html.escape(game['game_code'])}</td>
                <td>{html.escape(game['matchup'])}</td>
                {gamebook_cell}
                {bdl_cell}
            </tr>
            """

    # Build stale tables section
    stale_tables_section = ""
    if stale_tables:
        stale_table_rows = ""
        for table in stale_tables:
            severity_color = '#d32f2f' if table['severity'] == 'CRITICAL' else '#ff9800'
            stale_hours = f"{table['hours_stale']:.1f}" if table['hours_stale'] is not None else "N/A"
            issue_icon = "❌" if table['severity'] == 'CRITICAL' else "⚠️"

            stale_table_rows += f"""
            <tr>
                <td>{issue_icon} {html.escape(table['table'])}</td>
                <td>{html.escape(table['description'])}</td>
                <td style="color: {severity_color}; font-weight: bold;">{stale_hours}h</td>
                <td>{table['threshold_hours']}h</td>
                <td>{html.escape(str(table['last_update']))}</td>
                <td style="color: {severity_color};">{html.escape(table['issue'])}</td>
            </tr>
            """

        stale_tables_section = f"""
        <h3 style="color: #ff9800;">Data Freshness Issues</h3>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; width: 100%;">
        <tr style="background-color: #f5f5f5;">
            <th>Table</th>
            <th>Description</th>
            <th>Hours Stale</th>
            <th>Threshold</th>
            <th>Last Update</th>
            <th>Issue</th>
        </tr>
        {stale_table_rows}
        </table>
        """

    # Build missing games section
    missing_games_section = ""
    if missing_games:
        missing_games_section = f"""
        <h3>Missing/Incomplete Games</h3>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; width: 100%;">
        <tr style="background-color: #f5f5f5;">
            <th>Date</th>
            <th>Game Code</th>
            <th>Matchup</th>
            <th>Gamebook</th>
            <th>BDL</th>
        </tr>
        {games_table_rows}
        </table>
        """

    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif;">
        <h2 style="color: #ff9800;">🚨 Daily Data Completeness & Freshness Report</h2>
        <p><strong>Check Time:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>
        <p><strong>Check ID:</strong> <code>{html.escape(check_id)}</code></p>

        <h3>Summary</h3>
        <ul>
            <li><strong>Missing Games:</strong> {total_missing} games</li>
            <li><strong>Gamebook Issues:</strong> {gamebook_missing} games</li>
            <li><strong>BDL Issues:</strong> {bdl_missing} games</li>
            <li><strong>Stale Tables:</strong> {total_stale} tables</li>
            <li><strong>Critical Freshness Issues:</strong> {critical_stale} tables</li>
        </ul>

        {stale_tables_section}

        {missing_games_section}

        <h3>Recommended Actions</h3>
        <ol>
            <li><strong>For stale data:</strong> Check scraper schedulers and recent execution logs</li>
            <li><strong>For missing games:</strong> Check scraper logs for failed executions (Phase 1)</li>
            <li>Verify GCS files exist for missing games:
                <ul>
                    <li><code>gs://nba-scraped-data/nba-com/gamebooks-data/[date]/</code></li>
                    <li><code>gs://nba-scraped-data/ball-dont-lie/player-box-scores/[date]/</code></li>
                </ul>
            </li>
            <li>Check processor logs for errors (Phase 2)</li>
            <li>Trigger backfill if data exists in GCS but not BigQuery</li>
        </ol>

        <h3>Monitoring Details</h3>
        <ul>
            <li>Completeness query: <code>functions/monitoring/data_completeness_checker/check_data_completeness.sql</code></li>
            <li>Freshness checks: {len(FRESHNESS_CHECKS)} tables monitored</li>
        </ul>

        <hr>
        <p style="color: #666; font-size: 12px;">
            This is an automated daily report from the NBA Stats Pipeline Data Completeness & Freshness Checker.
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

        # Check 1: Data completeness (missing games)
        logger.info("Checking data completeness...")
        sql_path = os.path.join(os.path.dirname(__file__), 'check_data_completeness.sql')
        with open(sql_path, 'r') as f:
            query = f.read()

        logger.info("Executing completeness query...")
        query_job = bq_client.query(query)
        results = list(query_job.result(timeout=60))
        missing_games = [dict(row) for row in results] if results else []
        missing_count = len(missing_games)

        # Check 2: Data freshness (stale tables)
        logger.info("Checking data freshness...")
        stale_tables = check_freshness(bq_client, project_id)
        stale_count = len(stale_tables)

        # Calculate duration
        duration_sec = (datetime.utcnow() - start_time).total_seconds()

        # Determine if we have any issues
        has_issues = (missing_count > 0) or (stale_count > 0)

        if has_issues:
            # Found issues - send alert
            logger.warning(
                f"Found {missing_count} missing/incomplete games + "
                f"{stale_count} stale tables"
            )

            # Send email alert
            alert_sent = send_email_alert(missing_games, stale_tables, check_id)

            # Log results
            log_check_result(bq_client, check_id, missing_count, alert_sent, duration_sec)
            if missing_games:
                log_missing_games(bq_client, check_id, missing_games)

            # Return response
            return {
                'status': 'alert_sent' if alert_sent else 'alert_failed',
                'check_id': check_id,
                'missing_games_count': missing_count,
                'stale_tables_count': stale_count,
                'alert_sent': alert_sent,
                'duration_seconds': duration_sec,
                'games': missing_games,
                'stale_tables': stale_tables
            }, 200

        else:
            # All checks passed - success!
            logger.info("All checks passed - no missing games or stale data")

            # Log success
            log_check_result(bq_client, check_id, 0, False, duration_sec)

            return {
                'status': 'ok',
                'check_id': check_id,
                'message': 'All checks passed - no issues found',
                'missing_games_count': 0,
                'stale_tables_count': 0,
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
