#!/usr/bin/env python3
"""
File: shared/utils/email_alerting_ses.py

AWS SES Email alerting utility for NBA Registry System.
Sends alerts for processor errors, unresolved players, and daily summaries using AWS SES.

Usage Examples:
    from shared.utils.email_alerting_ses import EmailAlerterSES

    alerter = EmailAlerterSES()

    # Send error alert
    alerter.send_error_alert("MERGE operation failed", error_details)
"""

import os
import logging
import html
from datetime import datetime
from typing import Dict, List, Optional
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# Import alert type system
from shared.utils.alert_types import get_alert_html_heading, detect_alert_type

# Import Secret Manager for secure credential retrieval
from shared.utils.secrets import get_secret_manager

# Load .env file for SES credentials (fallback only)
load_dotenv()

logger = logging.getLogger(__name__)


class EmailAlerterSES:
    """
    AWS SES Email alerting utility for NBA Registry System.

    Handles different alert levels:
    - CRITICAL: System failures, database errors
    - WARNING: High unresolved counts, performance issues
    - INFO: Daily summaries, new player discoveries
    """

    def __init__(self):
        """Initialize email alerter with AWS SES settings."""
        self.aws_region = os.environ.get('AWS_SES_REGION', 'us-west-2')
        self.from_email = os.environ.get('AWS_SES_FROM_EMAIL', 'alert@989.ninja')
        self.from_name = os.environ.get('AWS_SES_FROM_NAME', 'NBA Registry System')

        # AWS credentials - try Secret Manager first, fall back to env vars
        try:
            secret_manager = get_secret_manager()
            aws_access_key = secret_manager.get_aws_ses_access_key_id()
            aws_secret_key = secret_manager.get_aws_ses_secret_key()
            logger.info("Using AWS SES credentials from Secret Manager")
        except Exception as e:
            logger.warning(f"Failed to get AWS SES credentials from Secret Manager: {e}")
            logger.info("Falling back to environment variables for AWS SES credentials")
            aws_access_key = os.environ.get('AWS_SES_ACCESS_KEY_ID')
            aws_secret_key = os.environ.get('AWS_SES_SECRET_ACCESS_KEY')

        # Alert recipients
        self.alert_recipients = os.environ.get('EMAIL_ALERTS_TO', '').split(',')
        self.critical_recipients = os.environ.get('EMAIL_CRITICAL_TO', '').split(',')

        # Clean up recipient lists
        self.alert_recipients = [email.strip() for email in self.alert_recipients if email.strip()]
        self.critical_recipients = [email.strip() for email in self.critical_recipients if email.strip()]

        # Initialize AWS SES client
        try:
            self.ses_client = boto3.client(
                'ses',
                region_name=self.aws_region,
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key
            )
            logger.info(f"AWS SES client initialized for region: {self.aws_region}")
        except Exception as e:
            logger.error(f"Failed to initialize AWS SES client: {e}")
            raise

        # Validate configuration
        self._validate_config()

        logger.info(f"Email alerter (SES) initialized: {len(self.alert_recipients)} alert recipients, "
                   f"{len(self.critical_recipients)} critical recipients")

    def _validate_config(self):
        """Validate email configuration."""
        if not self.from_email:
            raise ValueError("AWS_SES_FROM_EMAIL environment variable is required")

        if not self.alert_recipients and not self.critical_recipients:
            logger.warning("No email recipients configured - alerts will not be sent")

    def _send_email(self, subject: str, body_html: str, recipients: List[str],
                   alert_level: str = "INFO") -> bool:
        """Send email via AWS SES."""
        if not recipients:
            logger.warning(f"No recipients for {alert_level} alert: {subject}")
            return False

        try:
            response = self.ses_client.send_email(
                Source=f"{self.from_name} <{self.from_email}>",
                Destination={
                    'ToAddresses': recipients
                },
                Message={
                    'Subject': {
                        'Data': f"[NBA Registry {alert_level}] {subject}",
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

            logger.info(f"Sent {alert_level} alert '{subject}' to {len(recipients)} recipients via SES. MessageId: {response['MessageId']}")
            return True

        except ClientError as e:
            logger.error(f"AWS SES error sending {alert_level} alert '{subject}': {e.response['Error']['Message']}")
            return False
        except Exception as e:
            logger.error(f"Failed to send {alert_level} alert '{subject}': {str(e)}")
            return False

    def send_error_alert(self, error_message: str, error_details: Dict = None,
                        processor_name: str = "Registry Processor",
                        alert_type: Optional[str] = None) -> bool:
        """
        Send error alert with appropriate heading based on error type.

        Args:
            error_message: The error message to send
            error_details: Optional dictionary with error details
            processor_name: Name of the processor that encountered the error
            alert_type: Optional alert type (auto-detected if not provided)
                       See shared.utils.alert_types for available types

        Returns:
            True if email sent successfully, False otherwise
        """
        # Auto-detect alert type if not provided
        if alert_type is None:
            alert_type = detect_alert_type(error_message, error_details)

        # Get alert heading with appropriate emoji and color
        alert_heading = get_alert_html_heading(alert_type)

        subject = f"{processor_name} - {alert_type.replace('_', ' ').title()}"

        # Escape all user-provided content
        safe_processor = html.escape(processor_name)
        safe_error_msg = html.escape(error_message)

        # Build details section if provided
        details_html = ""
        if error_details:
            details_html = "<h3>Error Details:</h3><ul>"
            for key, value in error_details.items():
                safe_key = html.escape(str(key))
                safe_value = html.escape(str(value))
                details_html += f"<li><strong>{safe_key}:</strong> {safe_value}</li>"
            details_html += "</ul>"

        html_body = f"""
        <html>
        <body>
            {alert_heading}
            <p><strong>Processor:</strong> {safe_processor}</p>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            <p><strong>Error:</strong> {safe_error_msg}</p>

            {details_html}

            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated alert from the NBA Registry System.
                Investigation may be required.
            </p>
        </body>
        </html>
        """

        return self._send_email(subject, html_body, self.critical_recipients or self.alert_recipients, "CRITICAL")

    def send_unresolved_players_alert(self, unresolved_count: int,
                                    threshold: int = 50) -> bool:
        """Send alert for high unresolved player count."""
        subject = f"High Unresolved Player Count: {unresolved_count}"

        html_body = f"""
        <html>
        <body>
            <h2 style="color: #ff9800;">⚠️ Unresolved Players Alert</h2>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            <p><strong>Unresolved Count:</strong> {unresolved_count}</p>
            <p><strong>Threshold:</strong> {threshold}</p>

            <p>
                The number of unresolved players has exceeded the threshold.
                Manual review may be required.
            </p>

            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated alert from the NBA Registry System.
            </p>
        </body>
        </html>
        """

        return self._send_email(subject, html_body, self.alert_recipients, "WARNING")

    def send_daily_summary(self, summary_data: Dict) -> bool:
        """Send daily summary email."""
        subject = f"Daily Summary - {datetime.now().strftime('%Y-%m-%d')}"

        # Build summary HTML
        summary_items = ""
        for key, value in summary_data.items():
            safe_key = html.escape(str(key).replace('_', ' ').title())
            safe_value = html.escape(str(value))
            summary_items += f"<li><strong>{safe_key}:</strong> {safe_value}</li>"

        html_body = f"""
        <html>
        <body>
            <h2 style="color: #0d6efd;">📊 Daily Summary</h2>
            <p><strong>Date:</strong> {datetime.now().strftime('%Y-%m-%d')}</p>

            <h3>Summary:</h3>
            <ul>
                {summary_items}
            </ul>

            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated daily summary from the NBA Registry System.
            </p>
        </body>
        </html>
        """

        return self._send_email(subject, html_body, self.alert_recipients, "INFO")

    def send_new_players_discovery_alert(self, players: List[Dict], processing_run_id: str = "unknown") -> bool:
        """Send alert for newly discovered players."""
        subject = f"New Players Discovered: {len(players)}"

        # Build player list HTML
        player_items = ""
        for player in players[:20]:  # Limit to first 20
            name = html.escape(player.get('name', 'Unknown'))
            player_id = html.escape(str(player.get('player_id', 'N/A')))
            player_items += f"<li>{name} (ID: {player_id})</li>"

        if len(players) > 20:
            player_items += f"<li><em>... and {len(players) - 20} more</em></li>"

        html_body = f"""
        <html>
        <body>
            <h2 style="color: #28a745;">🆕 New Players Discovered</h2>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            <p><strong>Processing Run:</strong> {html.escape(processing_run_id)}</p>
            <p><strong>Count:</strong> {len(players)}</p>

            <h3>Players:</h3>
            <ul>
                {player_items}
            </ul>

            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated alert from the NBA Registry System.
            </p>
        </body>
        </html>
        """

        return self._send_email(subject, html_body, self.alert_recipients, "INFO")

    def send_pipeline_health_summary(self, health_data: Dict) -> bool:
        """
        Send daily pipeline health summary email.

        Args:
            health_data: Dictionary containing:
                - date: Processing date
                - phases: Dict of phase statuses {phase_name: {complete: int, total: int, status: str}}
                - total_duration_minutes: Total pipeline duration
                - data_quality: Overall quality (GOLD/SILVER/BRONZE)
                - gaps_detected: Number of gaps found
                - records_processed: Total records
        """
        date_str = health_data.get('date', datetime.now().strftime('%Y-%m-%d'))
        subject = f"✅ Pipeline Health - {date_str}"

        # Build phase status rows
        phases = health_data.get('phases', {})
        phase_rows = ""
        for phase_name, phase_info in phases.items():
            complete = phase_info.get('complete', 0)
            total = phase_info.get('total', 0)
            status = phase_info.get('status', 'unknown')

            if status == 'success':
                icon = "✅"
                color = "#28a745"
            elif status == 'partial':
                icon = "⚠️"
                color = "#ff9800"
            else:
                icon = "❌"
                color = "#d32f2f"

            phase_rows += f'<tr><td>{html.escape(phase_name)}</td><td style="color: {color};">{icon} {complete}/{total}</td></tr>'

        duration = health_data.get('total_duration_minutes', 0)
        quality = health_data.get('data_quality', 'UNKNOWN')
        gaps = health_data.get('gaps_detected', 0)
        records = health_data.get('records_processed', 0)

        # Quality color
        quality_color = "#28a745" if quality == "GOLD" else "#ff9800" if quality == "SILVER" else "#d32f2f"

        html_body = f"""
        <html>
        <body>
            <h2 style="color: #28a745;">✅ Daily Pipeline Health Summary</h2>
            <p><strong>Date:</strong> {html.escape(date_str)}</p>
            <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>

            <h3>Phase Status</h3>
            <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
                <tr style="background-color: #f5f5f5;">
                    <th>Phase</th>
                    <th>Status</th>
                </tr>
                {phase_rows}
            </table>

            <h3>Summary</h3>
            <ul>
                <li><strong>Total Duration:</strong> {duration} minutes</li>
                <li><strong>Data Quality:</strong> <span style="color: {quality_color};">{html.escape(quality)}</span></li>
                <li><strong>Gaps Detected:</strong> {gaps}</li>
                <li><strong>Records Processed:</strong> {records:,}</li>
            </ul>

            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated daily health summary from the NBA Registry System.
            </p>
        </body>
        </html>
        """

        return self._send_email(subject, html_body, self.alert_recipients, "INFO")

    def send_prediction_completion_summary(self, prediction_data: Dict) -> bool:
        """
        Send prediction completion summary email.

        Args:
            prediction_data: Dictionary containing:
                - date: Prediction date
                - games_count: Number of games today
                - players_predicted: Number successfully predicted
                - players_total: Total players attempted
                - failed_players: List of {name, reason} for failures
                - confidence_distribution: Dict {high: n, medium: n, low: n}
                - top_recommendations: List of {player, line, recommendation, confidence}
                - duration_minutes: Time to complete
        """
        date_str = prediction_data.get('date', datetime.now().strftime('%Y-%m-%d'))
        predicted = prediction_data.get('players_predicted', 0)
        total = prediction_data.get('players_total', 0)

        subject = f"🏀 Predictions Ready - {date_str} ({predicted}/{total})"

        games = prediction_data.get('games_count', 0)
        duration = prediction_data.get('duration_minutes', 0)

        # Failed players section
        failed_players = prediction_data.get('failed_players', [])
        failed_html = ""
        if failed_players:
            failed_html = "<h3>Failed Predictions</h3><ul>"
            for player in failed_players[:10]:
                name = html.escape(player.get('name', 'Unknown'))
                reason = html.escape(player.get('reason', 'Unknown error'))
                failed_html += f"<li><strong>{name}:</strong> {reason}</li>"
            if len(failed_players) > 10:
                failed_html += f"<li><em>... and {len(failed_players) - 10} more</em></li>"
            failed_html += "</ul>"

        # Confidence distribution
        conf_dist = prediction_data.get('confidence_distribution', {})
        high_conf = conf_dist.get('high', 0)
        med_conf = conf_dist.get('medium', 0)
        low_conf = conf_dist.get('low', 0)

        # Top recommendations
        recommendations = prediction_data.get('top_recommendations', [])
        recs_html = ""
        if recommendations:
            recs_html = "<h3>Top Recommendations</h3><ul>"
            for rec in recommendations[:5]:
                player = html.escape(rec.get('player', 'Unknown'))
                line = rec.get('line', 0)
                action = html.escape(rec.get('recommendation', 'N/A'))
                confidence = rec.get('confidence', 0)
                recs_html += f"<li><strong>{player}:</strong> {action} {line} pts ({confidence}% confidence)</li>"
            recs_html += "</ul>"

        # Status color
        success_rate = (predicted / total * 100) if total > 0 else 0
        status_color = "#28a745" if success_rate >= 95 else "#ff9800" if success_rate >= 80 else "#d32f2f"

        html_body = f"""
        <html>
        <body>
            <h2 style="color: #6f42c1;">🏀 Prediction Completion Summary</h2>
            <p><strong>Date:</strong> {html.escape(date_str)}</p>
            <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>

            <h3>Overview</h3>
            <ul>
                <li><strong>Games Today:</strong> {games}</li>
                <li><strong>Players Predicted:</strong> <span style="color: {status_color};">{predicted}/{total}</span></li>
                <li><strong>Duration:</strong> {duration} minutes</li>
            </ul>

            <h3>Confidence Distribution</h3>
            <ul>
                <li><strong>High (&gt;80%):</strong> {high_conf} players</li>
                <li><strong>Medium (50-80%):</strong> {med_conf} players</li>
                <li><strong>Low (&lt;50%):</strong> {low_conf} players</li>
            </ul>

            {recs_html}
            {failed_html}

            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated prediction summary from the NBA Registry System.
            </p>
        </body>
        </html>
        """

        return self._send_email(subject, html_body, self.alert_recipients, "INFO")

    def send_dependency_stall_alert(self, stall_data: Dict) -> bool:
        """
        Send alert when pipeline is stalled waiting for dependencies.

        Args:
            stall_data: Dictionary containing:
                - waiting_phase: Phase that is waiting (e.g., "Phase 3")
                - blocked_by_phase: Phase being waited on (e.g., "Phase 2")
                - wait_minutes: How long it has been waiting
                - missing_processors: List of processor names not yet complete
                - completed_count: Number of processors completed
                - total_count: Total processors expected
        """
        waiting = stall_data.get('waiting_phase', 'Unknown')
        blocked_by = stall_data.get('blocked_by_phase', 'Unknown')
        wait_mins = stall_data.get('wait_minutes', 0)

        subject = f"⏳ Pipeline Stall - {waiting} waiting {wait_mins}+ mins"

        missing = stall_data.get('missing_processors', [])
        completed = stall_data.get('completed_count', 0)
        total = stall_data.get('total_count', 0)

        # Build missing processors list
        missing_html = ""
        if missing:
            missing_html = "<h3>Missing Processors</h3><ul>"
            for proc in missing[:15]:
                missing_html += f"<li>❌ {html.escape(proc)}</li>"
            if len(missing) > 15:
                missing_html += f"<li><em>... and {len(missing) - 15} more</em></li>"
            missing_html += "</ul>"

        html_body = f"""
        <html>
        <body>
            <h2 style="color: #ff9800;">⏳ Pipeline Stall Detected</h2>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>

            <p style="font-size: 16px;">
                <strong>{html.escape(waiting)}</strong> has been waiting
                <strong style="color: #d32f2f;">{wait_mins} minutes</strong>
                for <strong>{html.escape(blocked_by)}</strong> to complete.
            </p>

            <h3>Status</h3>
            <ul>
                <li><strong>Completed:</strong> {completed}/{total} processors</li>
                <li><strong>Missing:</strong> {len(missing)} processors</li>
            </ul>

            {missing_html}

            <h3>Recommended Actions</h3>
            <ul>
                <li>Check Cloud Run logs for the missing processors</li>
                <li>Verify Phase 1 scrapers completed successfully</li>
                <li>Check GCS for expected data files</li>
                <li>Manually trigger missing processors if needed</li>
            </ul>

            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated stall alert from the NBA Registry System.
                Investigation recommended.
            </p>
        </body>
        </html>
        """

        return self._send_email(subject, html_body, self.critical_recipients or self.alert_recipients, "WARNING")

    def send_backfill_progress_report(self, progress_data: Dict) -> bool:
        """
        Send backfill progress report email.

        Args:
            progress_data: Dictionary containing:
                - season: Season being backfilled (e.g., "2023-24")
                - phase: Current phase (e.g., "Phase 3 Analytics")
                - completed_dates: Number of dates completed
                - total_dates: Total dates to process
                - successful: Number of successful dates
                - partial: Number of partial successes
                - failed: Number of failed dates
                - failed_dates: List of failed date strings
                - estimated_remaining_minutes: Estimated time remaining
                - alerts_suppressed: Number of alerts suppressed
        """
        season = progress_data.get('season', 'Unknown')
        phase = progress_data.get('phase', 'Unknown')
        completed = progress_data.get('completed_dates', 0)
        total = progress_data.get('total_dates', 0)

        progress_pct = (completed / total * 100) if total > 0 else 0
        subject = f"📦 Backfill Progress - {season} {phase} ({progress_pct:.0f}%)"

        successful = progress_data.get('successful', 0)
        partial = progress_data.get('partial', 0)
        failed = progress_data.get('failed', 0)
        failed_dates = progress_data.get('failed_dates', [])
        remaining = progress_data.get('estimated_remaining_minutes', 0)
        suppressed = progress_data.get('alerts_suppressed', 0)

        # Failed dates list
        failed_html = ""
        if failed_dates:
            failed_html = "<h3>Failed Dates</h3><ul>"
            for date in failed_dates[:10]:
                failed_html += f"<li>❌ {html.escape(str(date))}</li>"
            if len(failed_dates) > 10:
                failed_html += f"<li><em>... and {len(failed_dates) - 10} more</em></li>"
            failed_html += "</ul>"

        # Progress bar (simple text-based)
        filled = int(progress_pct / 5)
        progress_bar = "█" * filled + "░" * (20 - filled)

        html_body = f"""
        <html>
        <body>
            <h2 style="color: #17a2b8;">📦 Backfill Progress Report</h2>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>

            <h3>Current Operation</h3>
            <ul>
                <li><strong>Season:</strong> {html.escape(season)}</li>
                <li><strong>Phase:</strong> {html.escape(phase)}</li>
            </ul>

            <h3>Progress</h3>
            <p style="font-family: monospace; font-size: 14px;">
                [{progress_bar}] {progress_pct:.1f}%
            </p>
            <p><strong>{completed}/{total}</strong> dates processed</p>

            <h3>Results</h3>
            <ul>
                <li style="color: #28a745;">✅ Successful: {successful}</li>
                <li style="color: #ff9800;">⚠️ Partial: {partial}</li>
                <li style="color: #d32f2f;">❌ Failed: {failed}</li>
            </ul>

            {failed_html}

            <h3>Estimates</h3>
            <ul>
                <li><strong>Time Remaining:</strong> ~{remaining} minutes</li>
                <li><strong>Alerts Suppressed:</strong> {suppressed:,}</li>
            </ul>

            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated backfill progress report from the NBA Registry System.
            </p>
        </body>
        </html>
        """

        return self._send_email(subject, html_body, self.alert_recipients, "INFO")

    def send_data_quality_alert(self, quality_data: Dict) -> bool:
        """
        Send alert when data quality degrades.

        Args:
            quality_data: Dictionary containing:
                - processor_name: Name of the processor
                - date: Processing date
                - previous_quality: Previous quality level (GOLD/SILVER/BRONZE)
                - current_quality: Current quality level
                - reason: Reason for degradation
                - fallback_sources: List of fallback sources used
                - impact: Description of impact
        """
        processor = quality_data.get('processor_name', 'Unknown')
        date_str = quality_data.get('date', datetime.now().strftime('%Y-%m-%d'))
        prev_quality = quality_data.get('previous_quality', 'GOLD')
        curr_quality = quality_data.get('current_quality', 'UNKNOWN')

        subject = f"📉 Data Quality Degraded - {prev_quality} → {curr_quality}"

        reason = quality_data.get('reason', 'Unknown reason')
        fallbacks = quality_data.get('fallback_sources', [])
        impact = quality_data.get('impact', 'Prediction confidence may be affected.')

        # Fallback sources
        fallback_html = ""
        if fallbacks:
            fallback_html = "<h3>Fallback Sources Used</h3><ul>"
            for source in fallbacks:
                fallback_html += f"<li>{html.escape(source)}</li>"
            fallback_html += "</ul>"

        # Quality color
        curr_color = "#28a745" if curr_quality == "GOLD" else "#ff9800" if curr_quality == "SILVER" else "#d32f2f"

        html_body = f"""
        <html>
        <body>
            <h2 style="color: #ff9800;">📉 Data Quality Degradation Alert</h2>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>

            <h3>Details</h3>
            <ul>
                <li><strong>Processor:</strong> {html.escape(processor)}</li>
                <li><strong>Date:</strong> {html.escape(date_str)}</li>
                <li><strong>Quality Change:</strong> {html.escape(prev_quality)} → <span style="color: {curr_color};">{html.escape(curr_quality)}</span></li>
            </ul>

            <h3>Reason</h3>
            <p>{html.escape(reason)}</p>

            {fallback_html}

            <h3>Impact</h3>
            <p>{html.escape(impact)}</p>

            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated quality alert from the NBA Registry System.
            </p>
        </body>
        </html>
        """

        return self._send_email(subject, html_body, self.alert_recipients, "WARNING")

    def send_stale_data_warning(self, stale_data: Dict) -> bool:
        """
        Send warning when upstream data is stale.

        Args:
            stale_data: Dictionary containing:
                - processor_name: Processor detecting the stale data
                - upstream_table: Name of the stale table
                - last_updated: When the table was last updated
                - expected_freshness_hours: How fresh data should be
                - actual_age_hours: How old the data actually is
                - possible_causes: List of possible causes
        """
        processor = stale_data.get('processor_name', 'Unknown')
        table = stale_data.get('upstream_table', 'Unknown')
        age_hours = stale_data.get('actual_age_hours', 0)

        subject = f"🕐 Stale Data Warning - {table} ({age_hours}h old)"

        last_updated = stale_data.get('last_updated', 'Unknown')
        expected = stale_data.get('expected_freshness_hours', 6)
        causes = stale_data.get('possible_causes', [
            'Scraper failure',
            'Processor stuck or failed',
            'GCS upload issue',
            'Pub/Sub message lost'
        ])

        # Causes list
        causes_html = "<ul>"
        for cause in causes:
            causes_html += f"<li>{html.escape(cause)}</li>"
        causes_html += "</ul>"

        html_body = f"""
        <html>
        <body>
            <h2 style="color: #fd7e14;">🕐 Stale Data Warning</h2>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>

            <h3>Details</h3>
            <ul>
                <li><strong>Detected By:</strong> {html.escape(processor)}</li>
                <li><strong>Stale Table:</strong> {html.escape(table)}</li>
                <li><strong>Last Updated:</strong> {html.escape(str(last_updated))}</li>
                <li><strong>Data Age:</strong> <span style="color: #d32f2f;">{age_hours} hours</span></li>
                <li><strong>Expected Freshness:</strong> &lt;{expected} hours</li>
            </ul>

            <h3>Possible Causes</h3>
            {causes_html}

            <h3>Recommended Actions</h3>
            <ul>
                <li>Check Phase 1 scraper logs</li>
                <li>Verify GCS bucket has recent files</li>
                <li>Check processor run history for failures</li>
                <li>Manually trigger upstream processor if needed</li>
            </ul>

            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated stale data warning from the NBA Registry System.
            </p>
        </body>
        </html>
        """

        return self._send_email(subject, html_body, self.alert_recipients, "WARNING")

    def should_send_unresolved_alert(self, unresolved_count: int, threshold: int = 50) -> bool:
        """Check if unresolved players alert should be sent."""
        return unresolved_count > threshold
