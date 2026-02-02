"""
SMS Notifications via Twilio

Sends SMS text messages for daily picks and alerts.
Designed for concise, mobile-friendly messages.

Usage:
    from shared.utils.sms_notifier import SMSNotifier

    notifier = SMSNotifier()
    notifier.send_picks_sms(picks_data)

Environment Variables:
    TWILIO_ACCOUNT_SID: Twilio account SID
    TWILIO_AUTH_TOKEN: Twilio auth token
    TWILIO_FROM_PHONE: Twilio phone number (e.g., +15551234567)
    SMS_TO_PHONE: Recipient phone number (e.g., +15559876543)

Session: 83 (2026-02-02)
"""

import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SMSNotifier:
    """Send SMS notifications via Twilio."""

    def __init__(self):
        """Initialize SMS notifier with Twilio credentials."""
        self.account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
        self.auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
        self.from_phone = os.environ.get('TWILIO_FROM_PHONE')
        self.to_phone = os.environ.get('SMS_TO_PHONE')

        # Validate configuration
        self._validate_config()

        # Import Twilio client (only if credentials exist)
        if self.account_sid and self.auth_token:
            try:
                from twilio.rest import Client
                self.client = Client(self.account_sid, self.auth_token)
                logger.info("Twilio SMS client initialized")
            except ImportError:
                logger.error("Twilio library not installed. Run: pip install twilio")
                self.client = None
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client: {e}")
                self.client = None
        else:
            self.client = None
            logger.debug("Twilio credentials not configured, SMS disabled")

    def _validate_config(self):
        """Validate Twilio configuration."""
        if not all([self.account_sid, self.auth_token, self.from_phone, self.to_phone]):
            missing = []
            if not self.account_sid:
                missing.append('TWILIO_ACCOUNT_SID')
            if not self.auth_token:
                missing.append('TWILIO_AUTH_TOKEN')
            if not self.from_phone:
                missing.append('TWILIO_FROM_PHONE')
            if not self.to_phone:
                missing.append('SMS_TO_PHONE')

            if missing:
                logger.debug(f"SMS disabled - missing: {', '.join(missing)}")

    def is_configured(self) -> bool:
        """Check if SMS is properly configured."""
        return self.client is not None and all([
            self.account_sid,
            self.auth_token,
            self.from_phone,
            self.to_phone
        ])

    def send_sms(self, message: str, to_phone: Optional[str] = None) -> bool:
        """
        Send SMS message via Twilio.

        Args:
            message: SMS message text (max 1600 chars for concatenated SMS)
            to_phone: Optional recipient phone (uses SMS_TO_PHONE if not provided)

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.is_configured():
            logger.warning("SMS not configured, skipping send")
            return False

        recipient = to_phone or self.to_phone

        if not recipient:
            logger.error("No recipient phone number provided")
            return False

        # Validate phone numbers
        if not recipient.startswith('+'):
            logger.warning(f"Phone number should start with +: {recipient}")
            recipient = '+1' + recipient.lstrip('1')  # Assume US if missing

        if not self.from_phone.startswith('+'):
            logger.warning(f"From phone should start with +: {self.from_phone}")

        try:
            # Send SMS via Twilio
            sms = self.client.messages.create(
                body=message,
                from_=self.from_phone,
                to=recipient
            )

            logger.info(f"SMS sent successfully. SID: {sms.sid}, Status: {sms.status}")
            return True

        except Exception as e:
            logger.error(f"Failed to send SMS: {e}", exc_info=True)
            return False

    def send_picks_sms(
        self,
        picks_data: Dict,
        max_picks: int = 3,
        include_historical: bool = True
    ) -> bool:
        """
        Send daily picks via SMS.

        Formats picks for SMS constraints (160 chars per message).
        Uses abbreviations to fit more info.

        Args:
            picks_data: Picks data from SubsetPicksNotifier query
            max_picks: Maximum picks to include (default: 3 for SMS length)
            include_historical: Include hit rate in message

        Returns:
            True if sent successfully
        """
        if not self.is_configured():
            logger.warning("SMS not configured, skipping picks SMS")
            return False

        game_date = picks_data.get('game_date', 'Today')
        signal = picks_data.get('daily_signal', 'UNKNOWN')
        pct_over = picks_data.get('pct_over', 0)
        hit_rate = picks_data.get('hit_rate', 0)
        picks = picks_data.get('picks', [])[:max_picks]

        # Signal emoji
        signal_emoji = {
            'RED': '🔴',
            'YELLOW': '🟡',
            'GREEN': '🟢'
        }.get(signal, '⚪')

        # Format picks (abbreviated)
        picks_text = ""
        for pick in picks:
            player = pick['player'].replace('_', ' ').title()
            # Abbreviate player name (first initial + last name)
            name_parts = player.split()
            if len(name_parts) >= 2:
                short_name = f"{name_parts[0][0]}.{name_parts[-1]}"
            else:
                short_name = player[:10]  # Fallback

            rec = pick['recommendation'][0]  # O or U
            line = pick['line']
            edge = pick['edge']

            picks_text += f"{pick['rank']}.{short_name} {rec}{line} E:{edge} "

        # Build message
        message = f"NBA {signal_emoji}{signal} ({pct_over}%)\n{picks_text.strip()}"

        if include_historical and hit_rate:
            message += f"\nHR:{hit_rate}%"

        # Add view link (if message still short enough)
        if len(message) < 140:
            message += f"\n/subset-picks"

        logger.info(f"Sending picks SMS ({len(message)} chars)")
        return self.send_sms(message)

    def send_signal_alert_sms(
        self,
        signal: str,
        pct_over: float,
        game_date: str
    ) -> bool:
        """
        Send pre-game signal alert via SMS.

        Args:
            signal: Daily signal (RED/YELLOW/GREEN)
            pct_over: Percentage OVER
            game_date: Game date

        Returns:
            True if sent successfully
        """
        if not self.is_configured():
            return False

        signal_emoji = {
            'RED': '🔴',
            'YELLOW': '🟡',
            'GREEN': '🟢'
        }.get(signal, '⚪')

        if signal == 'RED':
            action = "⚠️ Reduce sizing"
        elif signal == 'YELLOW':
            action = "⚠️ Caution"
        else:
            action = "✅ Normal"

        message = f"NBA {signal_emoji}{signal} ({pct_over}% OVER)\n{action}"

        return self.send_sms(message)

    def test_sms(self) -> bool:
        """
        Send test SMS to verify configuration.

        Returns:
            True if test SMS sent successfully
        """
        if not self.is_configured():
            logger.error("Cannot test SMS - not configured")
            return False

        test_message = (
            "🏀 NBA Props - Test SMS\n"
            f"From: {self.from_phone}\n"
            f"To: {self.to_phone}\n"
            "If you received this, SMS is working!"
        )

        logger.info("Sending test SMS...")
        return self.send_sms(test_message)


# Convenience function
def send_picks_via_sms(picks_data: Dict, max_picks: int = 3) -> bool:
    """
    Convenience function to send picks SMS.

    Args:
        picks_data: Picks data dict
        max_picks: Max picks to include

    Returns:
        True if sent successfully
    """
    try:
        notifier = SMSNotifier()
        return notifier.send_picks_sms(picks_data, max_picks=max_picks)
    except Exception as e:
        logger.error(f"Failed to send picks SMS: {e}", exc_info=True)
        return False


if __name__ == '__main__':
    # Test SMS configuration
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        notifier = SMSNotifier()
        if notifier.is_configured():
            success = notifier.test_sms()
            sys.exit(0 if success else 1)
        else:
            logger.error("SMS not configured. Set TWILIO_* and SMS_TO_PHONE env vars")
            sys.exit(1)
    else:
        print("Usage: python sms_notifier.py --test")
        print("\nRequired env vars:")
        print("  TWILIO_ACCOUNT_SID")
        print("  TWILIO_AUTH_TOKEN")
        print("  TWILIO_FROM_PHONE")
        print("  SMS_TO_PHONE")
