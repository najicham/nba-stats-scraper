#!/usr/bin/env python3
"""Signal Decay Monitor — detect signal decay and recovery for actionable alerts.

Queries signal_health_daily to classify each signal as HEALTHY, WATCH, DEGRADING,
or RECOVERED. Produces recommendations like "volatile_scoring_over RECOVERED" or
"bench_under DEGRADING — consider disabling".

Complements model decay_detection CF (Session 389) but for signals.

Usage:
    PYTHONPATH=. python bin/monitoring/signal_decay_monitor.py
    PYTHONPATH=. python bin/monitoring/signal_decay_monitor.py --date 2026-03-05
    PYTHONPATH=. python bin/monitoring/signal_decay_monitor.py --dry-run

Created: 2026-03-05 (Session 411)
"""

import argparse
import logging
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'

# Signals known to be disabled — track for recovery detection
DISABLED_SIGNALS = {
    'b2b_fatigue_under',
    'rest_advantage_2d',
    'blowout_recovery',
    'prop_line_drop_over',
}

# Thresholds
BREAKEVEN_HR = 52.4  # -110 juice breakeven
WATCH_HR_14D = 50.0  # Below breakeven for 14d → WATCH
DEGRADING_HR_14D = 45.0  # Badly losing → DEGRADING
RECOVERY_HR_14D = 60.0  # HR 60%+ for 14d → RECOVERED
MIN_PICKS_FOR_VERDICT = 10  # Need at least N picks to judge


def query_signal_health(bq_client: bigquery.Client, target_date: str):
    """Get latest signal health data."""
    query = f"""
    SELECT
        signal_tag,
        hr_7d, hr_14d, hr_30d, hr_season,
        picks_7d, picks_14d, picks_30d, picks_season,
        regime, status,
        days_in_current_regime
    FROM `{PROJECT_ID}.nba_predictions.signal_health_daily`
    WHERE game_date = @target_date
    ORDER BY signal_tag
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )
    rows = bq_client.query(query, job_config=job_config).result(timeout=30)
    return [dict(row) for row in rows]


def classify_signals(health_rows):
    """Classify each signal into actionable categories."""
    results = {
        'healthy': [],
        'watch': [],
        'degrading': [],
        'recovered': [],
        'insufficient_data': [],
    }

    for row in health_rows:
        tag = row['signal_tag']
        hr_14d = row.get('hr_14d')
        picks_14d = row.get('picks_14d') or 0
        hr_30d = row.get('hr_30d')
        picks_30d = row.get('picks_30d') or 0

        entry = {
            'signal_tag': tag,
            'hr_14d': hr_14d,
            'hr_30d': hr_30d,
            'picks_14d': picks_14d,
            'picks_30d': picks_30d,
            'regime': row.get('regime', 'UNKNOWN'),
            'days_in_regime': row.get('days_in_current_regime', 0),
        }

        # Not enough data to judge
        if picks_14d < MIN_PICKS_FOR_VERDICT:
            results['insufficient_data'].append(entry)
            continue

        # Check for recovery of disabled signals
        if tag in DISABLED_SIGNALS and hr_14d and hr_14d >= RECOVERY_HR_14D:
            entry['recommendation'] = f"RECOVERED: {hr_14d:.1f}% HR (14d, N={picks_14d}) — consider re-enabling"
            results['recovered'].append(entry)
            continue

        if hr_14d is None:
            results['insufficient_data'].append(entry)
            continue

        # Degrading: well below breakeven
        if hr_14d < DEGRADING_HR_14D:
            entry['recommendation'] = f"DEGRADING: {hr_14d:.1f}% HR (14d, N={picks_14d}) — consider disabling"
            results['degrading'].append(entry)
        # Watch: below breakeven
        elif hr_14d < WATCH_HR_14D:
            entry['recommendation'] = f"WATCH: {hr_14d:.1f}% HR (14d, N={picks_14d}) — monitoring"
            results['watch'].append(entry)
        else:
            results['healthy'].append(entry)

    return results


def format_report(results, target_date):
    """Format human-readable report."""
    lines = [f"Signal Decay Monitor — {target_date}", "=" * 50]

    if results['recovered']:
        lines.append(f"\nRECOVERED ({len(results['recovered'])}):")
        for r in results['recovered']:
            lines.append(f"  {r['signal_tag']}: {r['recommendation']}")

    if results['degrading']:
        lines.append(f"\nDEGRADING ({len(results['degrading'])}):")
        for r in results['degrading']:
            lines.append(f"  {r['signal_tag']}: {r['recommendation']}")

    if results['watch']:
        lines.append(f"\nWATCH ({len(results['watch'])}):")
        for r in results['watch']:
            lines.append(f"  {r['signal_tag']}: {r['recommendation']}")

    healthy_count = len(results['healthy'])
    lines.append(f"\nHEALTHY: {healthy_count} signals")
    for h in results['healthy']:
        lines.append(f"  {h['signal_tag']}: {h['hr_14d']:.1f}% (14d, N={h['picks_14d']})")

    if results['insufficient_data']:
        lines.append(f"\nINSUFFICIENT DATA: {len(results['insufficient_data'])} signals (< {MIN_PICKS_FOR_VERDICT} picks)")
        for i in results['insufficient_data']:
            lines.append(f"  {i['signal_tag']}: N={i['picks_14d']}")

    lines.append(f"\nSummary: {healthy_count} healthy, {len(results['watch'])} watch, "
                 f"{len(results['degrading'])} degrading, {len(results['recovered'])} recovered")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Signal decay monitor')
    parser.add_argument('--date', help='Target date (YYYY-MM-DD)', default=str(date.today()))
    parser.add_argument('--dry-run', action='store_true', help='Print report only, no alerts')
    args = parser.parse_args()

    bq_client = bigquery.Client(project=PROJECT_ID)

    logger.info(f"Checking signal health for {args.date}")
    health_rows = query_signal_health(bq_client, args.date)

    if not health_rows:
        # Try previous day if no data for target date
        prev_date = str(date.fromisoformat(args.date) - timedelta(days=1))
        logger.info(f"No data for {args.date}, trying {prev_date}")
        health_rows = query_signal_health(bq_client, prev_date)

    if not health_rows:
        logger.warning("No signal health data found")
        return

    results = classify_signals(health_rows)
    report = format_report(results, args.date)
    print(report)

    # Alert on degrading or recovered signals
    if not args.dry_run:
        alerts = results['degrading'] + results['recovered']
        if alerts:
            try:
                from shared.utils.slack_alerts import send_slack_alert
                alert_lines = ["Signal Decay Monitor Alert:"]
                for a in alerts:
                    alert_lines.append(f"  {a['signal_tag']}: {a['recommendation']}")
                send_slack_alert('\n'.join(alert_lines), channel='#nba-alerts')
                logger.info(f"Sent alerts for {len(alerts)} signals")
            except Exception as e:
                logger.warning(f"Failed to send Slack alert: {e}")


if __name__ == '__main__':
    main()
