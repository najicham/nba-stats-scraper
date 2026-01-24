#!/usr/bin/env python3
"""
File: shared/utils/processor_alerting.py

Processor Alerting System

Provides email and Slack notifications for NBA registry processors.
Replaces silent error fallbacks with explicit alerts and monitoring.

Features:
- Email alerts via SendGrid
- Slack notifications via webhooks
- Different alert levels (error, warning, info)
- Rate limiting to prevent spam
- Structured alert data for monitoring systems
"""

import json
import logging
import os
import smtplib
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Optional, Any
import requests
from shared.utils.auth_utils import get_api_key

# Import alert type system
from shared.utils.alert_types import get_alert_html_heading, detect_alert_type, format_alert_heading

logger = logging.getLogger(__name__)


class ProcessorAlerting:
    """
    Centralized alerting system for NBA registry processors.
    
    Handles email notifications, Slack messages, and monitoring integration.
    Includes rate limiting to prevent alert spam.
    """
    
    def __init__(self):
        # Email configuration
        self.sendgrid_api_key = os.environ.get('SENDGRID_API_KEY')
        self.from_email = os.environ.get('ALERT_FROM_EMAIL', 'nba-processors@nba-props-platform.com')
        self.default_recipients = self._parse_email_list(os.environ.get('ALERT_RECIPIENTS', ''))
        
        # Slack configuration  
        self.slack_webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
        self.default_slack_channel = os.environ.get('SLACK_CHANNEL', '#nba-alerts')
        
        # Rate limiting (prevent spam)
        self.alert_history = {}  # alert_key -> last_sent_timestamp
        self.rate_limit_minutes = 15  # Don't send same alert more than once per 15 minutes
        
        # Alert priorities
        self.alert_levels = {
            'error': {'priority': 1, 'color': '#FF0000', 'emoji': '🚨'},
            'warning': {'priority': 2, 'color': '#FFA500', 'emoji': '⚠️'},
            'info': {'priority': 3, 'color': '#0000FF', 'emoji': 'ℹ️'},
            'success': {'priority': 4, 'color': '#00FF00', 'emoji': '✅'}
        }
        
        logger.info("Initialized ProcessorAlerting system")
    
    def _parse_email_list(self, email_string: str) -> List[str]:
        """Parse comma-separated email list from environment variable."""
        if not email_string:
            return []
        return [email.strip() for email in email_string.split(',') if email.strip()]
    
    def _should_send_alert(self, alert_key: str) -> bool:
        """Check if alert should be sent based on rate limiting."""
        current_time = time.time()
        last_sent = self.alert_history.get(alert_key)
        
        if not last_sent:
            return True
        
        time_diff_minutes = (current_time - last_sent) / 60
        return time_diff_minutes >= self.rate_limit_minutes
    
    def _record_alert_sent(self, alert_key: str):
        """Record that an alert was sent for rate limiting."""
        self.alert_history[alert_key] = time.time()
    
    def send_error_alert(self, processor_name: str, error_type: str, details: Dict[str, Any],
                        recipients: Optional[List[str]] = None) -> bool:
        """
        Send error alert via email and Slack.
        
        Args:
            processor_name: Name of the processor (e.g., 'gamebook_registry')
            error_type: Type of error (e.g., 'universal_id_resolution_failed')
            details: Error details dictionary
            recipients: Override default email recipients
            
        Returns:
            True if alerts sent successfully
        """
        alert_key = f"{processor_name}_{error_type}"
        
        if not self._should_send_alert(alert_key):
            logger.info(f"Rate limited: Skipping duplicate alert for {alert_key}")
            return False
        
        alert_data = {
            'level': 'error',
            'processor': processor_name,
            'error_type': error_type,
            'timestamp': datetime.now().isoformat(),
            'details': details,
            'environment': os.environ.get('ENVIRONMENT', 'production')
        }
        
        # Send email alert
        email_sent = self._send_email_alert(alert_data, recipients)
        
        # Send Slack alert
        slack_sent = self._send_slack_alert(alert_data)
        
        if email_sent or slack_sent:
            self._record_alert_sent(alert_key)
            return True
        
        return False
    
    def send_warning_alert(self, processor_name: str, warning_type: str, details: Dict[str, Any],
                          recipients: Optional[List[str]] = None) -> bool:
        """Send warning alert (less urgent than error)."""
        alert_key = f"{processor_name}_{warning_type}"
        
        if not self._should_send_alert(alert_key):
            logger.info(f"Rate limited: Skipping duplicate warning for {alert_key}")
            return False
        
        alert_data = {
            'level': 'warning',
            'processor': processor_name,
            'warning_type': warning_type,
            'timestamp': datetime.now().isoformat(),
            'details': details,
            'environment': os.environ.get('ENVIRONMENT', 'production')
        }
        
        # Send Slack alert (warnings typically don't need email)
        slack_sent = self._send_slack_alert(alert_data)
        
        if slack_sent:
            self._record_alert_sent(alert_key)
            return True
        
        return False
    
    def send_processing_summary(self, processor_name: str, summary_data: Dict[str, Any],
                              include_email: bool = False) -> bool:
        """Send processing summary (daily/weekly reports)."""
        alert_data = {
            'level': 'info',
            'processor': processor_name,
            'summary_type': 'processing_summary',
            'timestamp': datetime.now().isoformat(),
            'details': summary_data,
            'environment': os.environ.get('ENVIRONMENT', 'production')
        }
        
        # Send Slack summary
        slack_sent = self._send_slack_alert(alert_data)
        
        # Optionally send email summary
        email_sent = False
        if include_email:
            email_sent = self._send_email_alert(alert_data)
        
        return slack_sent or email_sent
    
    def _send_email_alert(self, alert_data: Dict[str, Any], 
                         recipients: Optional[List[str]] = None) -> bool:
        """Send email alert via SendGrid or SMTP."""
        if not self.sendgrid_api_key and not os.environ.get('SMTP_HOST'):
            logger.warning("No email configuration found - skipping email alert")
            return False
        
        recipients = recipients or self.default_recipients
        if not recipients:
            logger.warning("No email recipients configured - skipping email alert")
            return False
        
        try:
            subject = self._build_email_subject(alert_data)
            body = self._build_email_body(alert_data)
            
            if self.sendgrid_api_key:
                return self._send_via_sendgrid(subject, body, recipients)
            else:
                return self._send_via_smtp(subject, body, recipients)
                
        except Exception as e:
            logger.error(f"Failed to send email alert: {e}", exc_info=True)
            return False
    
    def _send_via_sendgrid(self, subject: str, body: str, recipients: List[str]) -> bool:
        """Send email via SendGrid API."""
        url = "https://api.sendgrid.com/v3/mail/send"
        headers = {
            "Authorization": f"Bearer {self.sendgrid_api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "personalizations": [{"to": [{"email": email} for email in recipients]}],
            "from": {"email": self.from_email},
            "subject": subject,
            "content": [{"type": "text/html", "value": body}]
        }
        
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 202:
            logger.info(f"Email alert sent successfully to {len(recipients)} recipients")
            return True
        else:
            logger.error(f"SendGrid API error: {response.status_code} - {response.text}", exc_info=True)
            return False
    
    def _send_via_smtp(self, subject: str, body: str, recipients: List[str]) -> bool:
        """Send email via SMTP (fallback method)."""
        smtp_host = os.environ.get('SMTP_HOST')
        smtp_port = int(os.environ.get('SMTP_PORT', 587))
        smtp_user = os.environ.get('SMTP_USER')
        # Get SMTP password from Secret Manager (with env var fallback for local dev)
        smtp_password = get_api_key(
            secret_name='brevo-smtp-password',
            default_env_var='SMTP_PASSWORD'
        )
        
        if not all([smtp_host, smtp_user, smtp_password]):
            logger.warning("Incomplete SMTP configuration - skipping email")
            return False
        
        try:
            msg = MIMEMultipart()
            msg['From'] = self.from_email
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'html'))
            
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.send_message(msg)
            
            logger.info(f"SMTP email sent successfully to {len(recipients)} recipients")
            return True
            
        except Exception as e:
            logger.error(f"SMTP send error: {e}", exc_info=True)
            return False
    
    def _send_slack_alert(self, alert_data: Dict[str, Any]) -> bool:
        """Send alert to Slack via webhook."""
        if not self.slack_webhook_url:
            logger.warning("No Slack webhook URL configured - skipping Slack alert")
            return False
        
        try:
            message = self._build_slack_message(alert_data)
            
            response = requests.post(
                self.slack_webhook_url,
                json=message,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("Slack alert sent successfully")
                return True
            else:
                logger.error(f"Slack webhook error: {response.status_code} - {response.text}", exc_info=True)
                return False
                
        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}", exc_info=True)
            return False
    
    def _build_email_subject(self, alert_data: Dict[str, Any]) -> str:
        """Build email subject line."""
        level = alert_data['level'].upper()
        processor = alert_data['processor']
        env = alert_data.get('environment', 'production').upper()
        
        if alert_data['level'] == 'error':
            error_type = alert_data.get('error_type', 'unknown')
            return f"[{env}] NBA Processor {level}: {processor} - {error_type}"
        elif alert_data['level'] == 'warning':
            warning_type = alert_data.get('warning_type', 'unknown')
            return f"[{env}] NBA Processor {level}: {processor} - {warning_type}"
        else:
            return f"[{env}] NBA Processor Update: {processor}"
    
    def _build_email_body(self, alert_data: Dict[str, Any]) -> str:
        """Build HTML email body with intelligent alert type detection."""
        # Detect alert type from error/warning message and details
        error_msg = alert_data.get('error_type') or alert_data.get('warning_type') or ''
        alert_type = detect_alert_type(error_msg, alert_data.get('details'))

        # Get HTML heading with appropriate emoji and color
        alert_heading = get_alert_html_heading(alert_type)

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="padding: 20px;">
                {alert_heading}
                <p><strong>Processor:</strong> {alert_data['processor']}</p>
                <p><strong>Time:</strong> {alert_data['timestamp']}</p>
                <p><strong>Environment:</strong> {alert_data.get('environment', 'production')}</p>
        """

        if alert_data['level'] == 'error':
            html += f"<p><strong>Error Type:</strong> {alert_data.get('error_type', 'unknown')}</p>"
        elif alert_data['level'] == 'warning':
            html += f"<p><strong>Warning Type:</strong> {alert_data.get('warning_type', 'unknown')}</p>"

        # Add details
        html += "<h3>Details:</h3><ul>"
        for key, value in alert_data.get('details', {}).items():
            html += f"<li><strong>{key}:</strong> {value}</li>"
        html += "</ul>"

        html += """
            </div>
        </body>
        </html>
        """

        return html
    
    def _build_slack_message(self, alert_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build Slack message payload."""
        level_info = self.alert_levels.get(alert_data['level'], {})
        emoji = level_info.get('emoji', '📢')
        color = level_info.get('color', '#000000')
        
        # Build main message
        if alert_data['level'] == 'error':
            title = f"{emoji} Processor Error: {alert_data['processor']}"
            error_type = alert_data.get('error_type', 'unknown')
            description = f"Error Type: {error_type}"
        elif alert_data['level'] == 'warning':
            title = f"{emoji} Processor Warning: {alert_data['processor']}"
            warning_type = alert_data.get('warning_type', 'unknown')
            description = f"Warning: {warning_type}"
        else:
            title = f"{emoji} Processor Update: {alert_data['processor']}"
            description = "Processing summary"
        
        # Build fields for details
        fields = []
        details = alert_data.get('details', {})
        
        for key, value in list(details.items())[:10]:  # Limit to 10 fields
            fields.append({
                "title": key.replace('_', ' ').title(),
                "value": str(value),
                "short": len(str(value)) < 50
            })
        
        # Slack message format
        message = {
            "channel": self.default_slack_channel,
            "username": "NBA Processor Alerts",
            "icon_emoji": ":basketball:",
            "attachments": [
                {
                    "color": color,
                    "title": title,
                    "text": description,
                    "fields": fields,
                    "footer": f"Environment: {alert_data.get('environment', 'production')}",
                    "ts": int(datetime.fromisoformat(alert_data['timestamp']).timestamp())
                }
            ]
        }
        
        return message
    
    def send_slack_message(self, message: str, channel: Optional[str] = None) -> bool:
        """Send simple text message to Slack."""
        if not self.slack_webhook_url:
            logger.warning("No Slack webhook URL configured")
            return False
        
        payload = {
            "channel": channel or self.default_slack_channel,
            "username": "NBA Processor Alerts",
            "text": message,
            "icon_emoji": ":basketball:"
        }
        
        try:
            response = requests.post(self.slack_webhook_url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send Slack message: {e}", exc_info=True)
            return False
    
    def get_alert_stats(self) -> Dict[str, Any]:
        """Get statistics about alert activity."""
        current_time = time.time()
        recent_alerts = []
        
        for alert_key, timestamp in self.alert_history.items():
            if (current_time - timestamp) < 3600:  # Last hour
                recent_alerts.append({
                    'alert_key': alert_key,
                    'sent_minutes_ago': int((current_time - timestamp) / 60)
                })
        
        return {
            'total_alerts_sent': len(self.alert_history),
            'recent_alerts_last_hour': len(recent_alerts),
            'recent_alerts': recent_alerts,
            'rate_limit_minutes': self.rate_limit_minutes,
            'email_configured': bool(self.sendgrid_api_key or os.environ.get('SMTP_HOST')),
            'slack_configured': bool(self.slack_webhook_url),
            'default_recipients': len(self.default_recipients)
        }


# Global alerting instance
alerting = ProcessorAlerting()


# Convenience functions for easy usage
def send_error_alert(processor_name: str, error_type: str, details: Dict[str, Any]) -> bool:
    """Convenience function to send error alert."""
    return alerting.send_error_alert(processor_name, error_type, details)


def send_warning_alert(processor_name: str, warning_type: str, details: Dict[str, Any]) -> bool:
    """Convenience function to send warning alert."""
    return alerting.send_warning_alert(processor_name, warning_type, details)


def send_slack_message(message: str, channel: Optional[str] = None) -> bool:
    """Convenience function to send Slack message."""
    return alerting.send_slack_message(message, channel)