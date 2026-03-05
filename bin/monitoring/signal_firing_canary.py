#!/usr/bin/env python3
"""Signal Firing Canary — detect dead or degrading signals.

Compares each active signal's 7-day firing count to prior 23-day baseline.
Classifies as DEAD (0 fires), DEGRADING (>70% drop), or NEVER_FIRED.

Usage:
    # Check signal health for today
    PYTHONPATH=. python bin/monitoring/signal_firing_canary.py

    # Check for a specific date
    PYTHONPATH=. python bin/monitoring/signal_firing_canary.py --date 2026-03-01

    # Send alerts to Slack
    PYTHONPATH=. python bin/monitoring/signal_firing_canary.py --slack

Created: Session 404+
"""

import argparse
import logging
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.cloud import bigquery

from ml.signals.signal_health import (
    ACTIVE_SIGNALS,
    check_signal_firing_canary,
    format_canary_slack_message,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
SLACK_WEBHOOK_SECRET = 'nba-alerts-webhook-url'


def send_slack_alert(message: str) -> bool:
    """Send alert to Slack #nba-alerts channel."""
    try:
        from google.cloud import secretmanager
        import requests

        sm_client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT_ID}/secrets/{SLACK_WEBHOOK_SECRET}/versions/latest"
        response = sm_client.access_secret_version(request={"name": name})
        webhook_url = response.payload.data.decode("UTF-8").strip()

        resp = requests.post(webhook_url, json={"text": message}, timeout=10)
        if resp.status_code == 200:
            logger.info("Slack alert sent successfully")
            return True
        else:
            logger.warning(f"Slack returned {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.warning(f"Could not send Slack alert: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Detect dead or degrading signals'
    )
    parser.add_argument('--date', type=str, default=str(date.today()),
                       help='Date to check (YYYY-MM-DD, default: today)')
    parser.add_argument('--slack', action='store_true',
                       help='Send alerts to Slack')
    args = parser.parse_args()

    bq_client = bigquery.Client(project=PROJECT_ID)
    target_date = args.date

    print(f"\nSIGNAL FIRING CANARY — {target_date}")
    print(f"Active signals tracked: {len(ACTIVE_SIGNALS)}")
    print()

    alerts = check_signal_firing_canary(bq_client, target_date)

    if not alerts:
        print("All signals healthy — no alerts.")
        return

    dead = [a for a in alerts if a['firing_status'] == 'DEAD']
    degrading = [a for a in alerts if a['firing_status'] == 'DEGRADING']
    never = [a for a in alerts if a['firing_status'] == 'NEVER_FIRED']

    if dead:
        print("DEAD SIGNALS (fired before, now zero in 7d):")
        for a in dead:
            print(f"  {a['signal_tag']:35s}  0 fires in 7d, was {a['fires_prior_23d']} in prior 23d")
        print()

    if degrading:
        print("DEGRADING SIGNALS (>70% drop from baseline):")
        for a in degrading:
            pct = round(100 * a['fires_7d'] / max(a['fires_prior_23d'], 1))
            print(f"  {a['signal_tag']:35s}  {a['fires_7d']} fires in 7d, "
                  f"was {a['fires_prior_23d']} in prior 23d ({pct}% of baseline)")
        print()

    if never:
        print("NEVER FIRED (0 fires in 30d — check configuration):")
        for a in never:
            print(f"  {a['signal_tag']:35s}")
        print()

    print(f"Summary: {len(dead)} DEAD, {len(degrading)} DEGRADING, {len(never)} NEVER_FIRED")

    if args.slack and (dead or degrading):
        slack_msg = format_canary_slack_message(alerts, target_date)
        if slack_msg:
            send_slack_alert(slack_msg)


if __name__ == '__main__':
    main()
