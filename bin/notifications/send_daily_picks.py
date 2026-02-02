#!/usr/bin/env python3
"""
Send Daily Subset Picks - Manual trigger script

Sends today's subset picks via Slack and Email.
Can be run manually or via Cloud Scheduler.

Usage:
    python bin/notifications/send_daily_picks.py
    python bin/notifications/send_daily_picks.py --subset v9_high_edge_top3
    python bin/notifications/send_daily_picks.py --date 2026-02-02
    python bin/notifications/send_daily_picks.py --slack-only
    python bin/notifications/send_daily_picks.py --email-only

Session: 83 (2026-02-02)
"""

import argparse
import logging
import sys
from datetime import date

# Add project root to path
sys.path.insert(0, '/app')  # For Cloud Run
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from shared.notifications.subset_picks_notifier import SubsetPicksNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='Send daily subset picks notifications')
    parser.add_argument(
        '--subset',
        default='v9_high_edge_top5',
        help='Subset ID to send (default: v9_high_edge_top5)'
    )
    parser.add_argument(
        '--date',
        help='Game date (YYYY-MM-DD), defaults to today'
    )
    parser.add_argument(
        '--slack-only',
        action='store_true',
        help='Send only Slack notification'
    )
    parser.add_argument(
        '--email-only',
        action='store_true',
        help='Send only Email notification'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Test mode - show what would be sent without actually sending'
    )

    args = parser.parse_args()

    # Determine what to send
    send_slack = not args.email_only
    send_email = not args.slack_only

    game_date = args.date or date.today().isoformat()

    logger.info(f"Sending daily picks for {args.subset} on {game_date}")
    logger.info(f"Channels: Slack={send_slack}, Email={send_email}")

    if args.test:
        logger.info("TEST MODE - Not actually sending")
        notifier = SubsetPicksNotifier()
        picks_data = notifier._query_subset_picks(args.subset, game_date)

        if picks_data:
            logger.info(f"Found {len(picks_data['picks'])} picks")
            logger.info(f"Signal: {picks_data['daily_signal']} ({picks_data['pct_over']}% OVER)")
            logger.info(f"Historical: {picks_data['hit_rate']}% HR ({picks_data['days']} days)")

            for pick in picks_data['picks'][:5]:
                logger.info(
                    f"  {pick['rank']}. {pick['player']} {pick['recommendation']} {pick['line']} "
                    f"(Edge: {pick['edge']}, Conf: {pick['confidence']}%)"
                )

            logger.info("TEST MODE - Exiting without sending")
            return 0
        else:
            logger.error("No picks data found")
            return 1

    # Send notifications
    try:
        notifier = SubsetPicksNotifier()
        results = notifier.send_daily_notifications(
            subset_id=args.subset,
            game_date=game_date,
            send_slack=send_slack,
            send_email=send_email
        )

        # Log results
        if results.get('slack'):
            logger.info("✅ Slack notification sent successfully")
        elif send_slack:
            logger.error("❌ Slack notification failed")

        if results.get('email'):
            logger.info("✅ Email notification sent successfully")
        elif send_email:
            logger.error("❌ Email notification failed")

        # Exit code based on results
        if send_slack and send_email:
            success = results.get('slack') and results.get('email')
        elif send_slack:
            success = results.get('slack')
        elif send_email:
            success = results.get('email')
        else:
            success = False

        return 0 if success else 1

    except Exception as e:
        logger.error(f"Error sending notifications: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
