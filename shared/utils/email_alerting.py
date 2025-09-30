#!/usr/bin/env python3
"""
File: shared/utils/email_alerting.py

Email alerting utility for NBA Registry System.
Sends alerts for processor errors, unresolved players, and daily summaries.

Usage Examples:
    from shared.utils.email_alerting import EmailAlerter
    
    alerter = EmailAlerter()
    
    # Check if alert should be sent
    if alerter.should_send_unresolved_alert(45):
        alerter.send_unresolved_players_alert(45)
    
    # Send error alert
    alerter.send_error_alert("MERGE operation failed", error_details)
    
    # Send daily summary
    alerter.send_daily_summary(registry_stats)
"""

import os
import smtplib
import logging
import html
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AlertThresholds:
    """Configuration for alert thresholds."""
    max_unresolved_players: int = 50
    min_success_rate: float = 90.0
    max_processing_time_minutes: int = 30
    max_consecutive_errors: int = 3


class EmailAlerter:
    """
    Email alerting utility for NBA Registry System.
    
    Handles different alert levels:
    - CRITICAL: System failures, database errors
    - WARNING: High unresolved counts, performance issues  
    - INFO: Daily summaries, new player discoveries
    """
    
    def __init__(self):
        """Initialize email alerter with environment settings."""
        self.smtp_host = os.environ.get('BREVO_SMTP_HOST', 'smtp-relay.brevo.com')
        self.smtp_port = int(os.environ.get('BREVO_SMTP_PORT', '587'))
        self.smtp_username = os.environ.get('BREVO_SMTP_USERNAME')
        self.smtp_password = os.environ.get('BREVO_SMTP_PASSWORD')
        self.from_email = os.environ.get('BREVO_FROM_EMAIL')
        self.from_name = os.environ.get('BREVO_FROM_NAME', 'NBA Registry System')
        
        # Alert recipients
        self.alert_recipients = os.environ.get('EMAIL_ALERTS_TO', '').split(',')
        self.critical_recipients = os.environ.get('EMAIL_CRITICAL_TO', '').split(',')
        
        # Clean up recipient lists
        self.alert_recipients = [email.strip() for email in self.alert_recipients if email.strip()]
        self.critical_recipients = [email.strip() for email in self.critical_recipients if email.strip()]
        
        # Alert thresholds
        self.thresholds = AlertThresholds(
            max_unresolved_players=int(os.environ.get('EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD', '50')),
            min_success_rate=float(os.environ.get('EMAIL_ALERT_SUCCESS_RATE_THRESHOLD', '90.0')),
            max_processing_time_minutes=int(os.environ.get('EMAIL_ALERT_MAX_PROCESSING_TIME', '30'))
        )
        
        # Validate configuration
        self._validate_config()
        
        logger.info(f"Email alerter initialized: {len(self.alert_recipients)} alert recipients, "
                   f"{len(self.critical_recipients)} critical recipients")
    
    def _validate_config(self):
        """Validate email configuration."""
        required_settings = [
            ('BREVO_SMTP_USERNAME', self.smtp_username),
            ('BREVO_SMTP_PASSWORD', self.smtp_password),
            ('BREVO_FROM_EMAIL', self.from_email)
        ]
        
        missing_settings = [name for name, value in required_settings if not value]
        
        if missing_settings:
            logger.error(f"Missing required email settings: {', '.join(missing_settings)}")
            raise ValueError(f"Email alerting requires these environment variables: {', '.join(missing_settings)}")
        
        if not self.alert_recipients:
            logger.warning("No EMAIL_ALERTS_TO recipients configured - alerts will not be sent")
    
    def _send_email(self, subject: str, body_html: str, recipients: List[str], 
                   alert_level: str = "INFO") -> bool:
        """Send email via Brevo SMTP."""
        if not recipients:
            logger.warning(f"No recipients for {alert_level} alert: {subject}")
            return False
        
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"[NBA Registry {alert_level}] {subject}"
            msg['From'] = f"{self.from_name} <{self.from_email}>"
            msg['To'] = ', '.join(recipients)
            
            # Add HTML body
            html_part = MIMEText(body_html, 'html')
            msg.attach(html_part)
            
            # Send via SMTP with timeout
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
            
            logger.info(f"Sent {alert_level} alert '{subject}' to {len(recipients)} recipients")
            return True
            
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error sending {alert_level} alert '{subject}': {str(e)}")
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
        
        html_body = f"""
        <html>
        <body>
            <h2 style="color: #d32f2f;">🚨 Critical Error Alert</h2>
            <p><strong>Processor:</strong> {safe_processor}</p>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            <p><strong>Error:</strong> {safe_error_msg}</p>
            
            {self._format_error_details(error_details) if error_details else ''}
            
            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated alert from the NBA Registry System.
                Immediate investigation may be required.
            </p>
        </body>
        </html>
        """
        
        return self._send_email(subject, html_body, self.critical_recipients, "CRITICAL")
    
    def should_send_unresolved_alert(self, unresolved_count: int, threshold: int = None) -> bool:
        """
        Check if unresolved players alert should be sent.
        
        Args:
            unresolved_count: Number of unresolved players
            threshold: Optional custom threshold (uses config default if not provided)
            
        Returns:
            True if alert should be sent, False otherwise
        """
        if threshold is None:
            threshold = self.thresholds.max_unresolved_players
        return unresolved_count > threshold
    
    def send_unresolved_players_alert(self, unresolved_count: int, 
                                    threshold: int = None) -> bool:
        """
        Send alert for high unresolved player count.
        
        Note: This method always sends an alert. Use should_send_unresolved_alert()
        to check if the alert is necessary before calling this method.
        
        Args:
            unresolved_count: Number of unresolved players
            threshold: Optional custom threshold (uses config default if not provided)
            
        Returns:
            True if email sent successfully, False otherwise
        """
        if threshold is None:
            threshold = self.thresholds.max_unresolved_players
        
        subject = f"High Unresolved Player Count: {unresolved_count}"
        
        html_body = f"""
        <html>
        <body>
            <h2 style="color: #ff9800;">⚠️ High Unresolved Player Count</h2>
            <p><strong>Current Count:</strong> {unresolved_count} unresolved players</p>
            <p><strong>Threshold:</strong> {threshold}</p>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            
            <p>The registry processor has detected an unusually high number of unresolved players. 
            This may indicate:</p>
            <ul>
                <li>New player name formats not handled by the system</li>
                <li>Data quality issues in source systems</li>
                <li>Name change detection requiring manual review</li>
            </ul>
            
            <p><strong>Recommended Action:</strong> Review unresolved players table and investigate patterns.</p>
            
            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated alert from the NBA Registry System.
            </p>
        </body>
        </html>
        """
        
        return self._send_email(subject, html_body, self.alert_recipients, "WARNING")
    
    def should_send_performance_alert(self, processing_time_minutes: float) -> bool:
        """
        Check if performance alert should be sent.
        
        Args:
            processing_time_minutes: Processing time in minutes
            
        Returns:
            True if alert should be sent, False otherwise
        """
        return processing_time_minutes > self.thresholds.max_processing_time_minutes
    
    def send_processing_performance_alert(self, processing_time_minutes: float, 
                                        records_processed: int) -> bool:
        """
        Send alert for slow processing performance.
        
        Note: This method always sends an alert. Use should_send_performance_alert()
        to check if the alert is necessary before calling this method.
        
        Args:
            processing_time_minutes: Processing time in minutes
            records_processed: Number of records processed
            
        Returns:
            True if email sent successfully, False otherwise
        """
        subject = f"Slow Processing Performance: {processing_time_minutes:.1f} minutes"
        
        records_per_minute = records_processed / processing_time_minutes if processing_time_minutes > 0 else 0
        
        html_body = f"""
        <html>
        <body>
            <h2 style="color: #ff9800;">⚠️ Processing Performance Alert</h2>
            <p><strong>Processing Time:</strong> {processing_time_minutes:.1f} minutes</p>
            <p><strong>Records Processed:</strong> {records_processed:,}</p>
            <p><strong>Records/Minute:</strong> {records_per_minute:.1f}</p>
            <p><strong>Threshold:</strong> {self.thresholds.max_processing_time_minutes} minutes</p>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            
            <p>Registry processing is taking longer than expected. Possible causes:</p>
            <ul>
                <li>Large data volume requiring optimization</li>
                <li>Database performance issues</li>
                <li>Network connectivity problems</li>
                <li>Resource constraints on processing infrastructure</li>
            </ul>
            
            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated alert from the NBA Registry System.
            </p>
        </body>
        </html>
        """
        
        return self._send_email(subject, html_body, self.alert_recipients, "WARNING")
    
    def send_daily_summary(self, registry_stats: Dict) -> bool:
        """
        Send daily registry processing summary.
        
        Args:
            registry_stats: Dictionary containing registry statistics
            
        Returns:
            True if email sent successfully, False otherwise
        """
        subject = f"Daily Registry Summary - {date.today().strftime('%Y-%m-%d')}"
        
        # Extract key metrics with safe defaults
        total_records = registry_stats.get('total_records', 0)
        unique_players = registry_stats.get('unique_players', 0)
        seasons_covered = registry_stats.get('seasons_covered', 0)
        processing_errors = len(registry_stats.get('errors', []))
        
        # Calculate success indicators
        success_indicators = []
        if processing_errors == 0:
            success_indicators.append("✅ No processing errors")
        else:
            success_indicators.append(f"❌ {processing_errors} processing errors")
        
        html_body = f"""
        <html>
        <body>
            <h2 style="color: #4caf50;">📊 Daily Registry Summary</h2>
            <p><strong>Date:</strong> {date.today().strftime('%Y-%m-%d')}</p>
            
            <h3>Key Metrics</h3>
            <ul>
                <li><strong>Total Records:</strong> {total_records:,}</li>
                <li><strong>Unique Players:</strong> {unique_players:,}</li>
                <li><strong>Seasons Covered:</strong> {seasons_covered}</li>
                <li><strong>Processing Errors:</strong> {processing_errors}</li>
            </ul>
            
            <h3>Status Indicators</h3>
            <ul>
                {''.join(f'<li>{indicator}</li>' for indicator in success_indicators)}
            </ul>
            
            {self._format_season_breakdown(registry_stats.get('seasons_breakdown', []))}
            
            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated daily summary from the NBA Registry System.
            </p>
        </body>
        </html>
        """
        
        return self._send_email(subject, html_body, self.alert_recipients, "INFO")
    
    def send_new_players_discovery_alert(self, new_players: List[str], 
                                       processing_run_id: str) -> bool:
        """
        Send alert for newly discovered players.
        
        Args:
            new_players: List of new player names
            processing_run_id: ID of the processing run that discovered them
            
        Returns:
            True if email sent successfully, False otherwise
        """
        if not new_players:
            logger.info("No new players to alert about")
            return True
        
        subject = f"New Players Discovered: {len(new_players)} players"
        
        # Escape player names
        players_list = '\n'.join([f'<li>{html.escape(player)}</li>' for player in new_players[:10]])
        if len(new_players) > 10:
            players_list += f'<li><em>... and {len(new_players) - 10} more</em></li>'
        
        html_body = f"""
        <html>
        <body>
            <h2 style="color: #2196f3;">🏀 New Players Discovered</h2>
            <p><strong>Count:</strong> {len(new_players)} new players</p>
            <p><strong>Processing Run:</strong> {html.escape(processing_run_id)}</p>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            
            <h3>Players:</h3>
            <ul>
                {players_list}
            </ul>
            
            <p>These players have been assigned universal player IDs and added to the registry.</p>
            
            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated alert from the NBA Registry System.
            </p>
        </body>
        </html>
        """
        
        return self._send_email(subject, html_body, self.alert_recipients, "INFO")
    
    def _format_error_details(self, error_details: Dict) -> str:
        """Format error details for HTML display with escaping."""
        if not error_details:
            return ""
        
        details_html = "<h3>Error Details</h3><ul>"
        for key, value in error_details.items():
            safe_key = html.escape(str(key))
            safe_value = html.escape(str(value))
            details_html += f"<li><strong>{safe_key}:</strong> {safe_value}</li>"
        details_html += "</ul>"
        
        return details_html
    
    def _format_season_breakdown(self, seasons_breakdown: List[Dict]) -> str:
        """Format season breakdown for HTML display with escaping."""
        if not seasons_breakdown:
            return ""
        
        breakdown_html = "<h3>Season Breakdown</h3><ul>"
        for season in seasons_breakdown[:5]:  # Show top 5 seasons
            season_name = html.escape(str(season.get('season', 'Unknown')))
            records = season.get('records', 0)
            players = season.get('players', 0)
            breakdown_html += f"""
            <li><strong>{season_name}:</strong> 
                {records:,} records, 
                {players:,} players
            </li>
            """
        breakdown_html += "</ul>"
        
        return breakdown_html
    
    def test_email_configuration(self) -> bool:
        """
        Send test email to verify configuration.
        
        Returns:
            True if test email sent successfully, False otherwise
        """
        subject = "NBA Registry Email Test"
        
        html_body = f"""
        <html>
        <body>
            <h2 style="color: #4caf50;">✅ Email Configuration Test</h2>
            <p>This is a test email to verify that the NBA Registry email alerting system is working correctly.</p>
            <p><strong>Sent at:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            <p><strong>From:</strong> {html.escape(self.from_email)}</p>
            <p><strong>SMTP Host:</strong> {html.escape(self.smtp_host)}</p>
            
            <p>If you received this email, the alerting system is configured correctly!</p>
            
            <hr>
            <p style="color: #666; font-size: 12px;">
                This is a test email from the NBA Registry System.
            </p>
        </body>
        </html>
        """
        
        return self._send_email(subject, html_body, self.alert_recipients, "TEST")


# Convenience function for quick error alerts
def send_quick_error_alert(error_message: str, processor_name: str = "NBA Registry"):
    """
    Quick function to send error alert without instantiating class.
    
    Args:
        error_message: The error message to send
        processor_name: Name of the processor
        
    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        alerter = EmailAlerter()
        return alerter.send_error_alert(error_message, processor_name=processor_name)
    except Exception as e:
        logger.error(f"Failed to send quick error alert: {e}")
        return False