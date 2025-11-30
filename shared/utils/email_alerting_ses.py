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
from typing import Dict, List
import boto3
from botocore.exceptions import ClientError

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

        # AWS credentials
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
                        processor_name: str = "Registry Processor") -> bool:
        """
        Send critical error alert.

        Args:
            error_message: The error message to send
            error_details: Optional dictionary with error details
            processor_name: Name of the processor that encountered the error

        Returns:
            True if email sent successfully, False otherwise
        """
        subject = f"{processor_name} - Critical Error"

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
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #d32f2f;">🚨 Critical Error Alert</h2>
            <p><strong>Processor:</strong> {safe_processor}</p>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            <p><strong>Error:</strong> {safe_error_msg}</p>

            {details_html}

            <hr style="margin-top: 30px; border: none; border-top: 1px solid #ccc;">
            <p style="color: #666; font-size: 12px;">
                This is an automated alert from the NBA Registry System.
                Immediate investigation may be required.
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
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #ff9800;">⚠️ Unresolved Players Alert</h2>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            <p><strong>Unresolved Count:</strong> {unresolved_count}</p>
            <p><strong>Threshold:</strong> {threshold}</p>

            <p style="margin-top: 20px;">
                The number of unresolved players has exceeded the threshold.
                Manual review may be required.
            </p>

            <hr style="margin-top: 30px; border: none; border-top: 1px solid #ccc;">
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
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #0d6efd;">📊 Daily Summary</h2>
            <p><strong>Date:</strong> {datetime.now().strftime('%Y-%m-%d')}</p>

            <h3>Summary:</h3>
            <ul>
                {summary_items}
            </ul>

            <hr style="margin-top: 30px; border: none; border-top: 1px solid #ccc;">
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
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #28a745;">🆕 New Players Discovered</h2>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            <p><strong>Processing Run:</strong> {html.escape(processing_run_id)}</p>
            <p><strong>Count:</strong> {len(players)}</p>

            <h3>Players:</h3>
            <ul>
                {player_items}
            </ul>

            <hr style="margin-top: 30px; border: none; border-top: 1px solid #ccc;">
            <p style="color: #666; font-size: 12px;">
                This is an automated alert from the NBA Registry System.
            </p>
        </body>
        </html>
        """

        return self._send_email(subject, html_body, self.alert_recipients, "INFO")

    def should_send_unresolved_alert(self, unresolved_count: int, threshold: int = 50) -> bool:
        """Check if unresolved players alert should be sent."""
        return unresolved_count > threshold
