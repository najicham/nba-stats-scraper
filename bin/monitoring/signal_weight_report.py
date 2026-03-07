#!/usr/bin/env python3
"""Weekly signal weight and promotion report.

Generates a Slack-ready report showing:
1. UNDER signal weights vs current HR — flags stale weights
2. Shadow signals meeting promotion criteria
3. Active signals with concerning HR trends

Uses signal_health_daily table data. Run weekly or on-demand.

Usage:
    python bin/monitoring/signal_weight_report.py [--dry-run] [--date YYYY-MM-DD]

Created: 2026-03-07 (Session 429)
"""

import argparse
import logging
import os
import sys
from datetime import date, timedelta

from google.cloud import bigquery

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', os.environ.get('GCP_PROJECT', 'nba-props-platform'))
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# Current hardcoded weights from aggregator.py — used for comparison
CURRENT_UNDER_WEIGHTS = {
    'sharp_book_lean_under': 1.0,
    'sharp_line_drop_under': 2.5,
    'book_disagreement': 2.5,
    'bench_under': 2.0,
    'home_under': 2.0,
    'starter_away_overtrend_under': 1.5,
    'extended_rest_under': 1.5,
    'volatile_starter_under': 2.0,
    'downtrend_under': 2.0,
}

BREAKEVEN_HR = 52.4
PROMOTION_HR = 60.0
PROMOTION_N = 30
RESCUE_HR = 65.0
RESCUE_N = 15


def query_signal_health(bq_client, target_date):
    """Query latest signal health data."""
    query = f"""
    SELECT signal_tag, hr_season, picks_season, hr_14d, picks_14d, hr_30d, picks_30d, regime
    FROM `{PROJECT_ID}.nba_predictions.signal_health_daily`
    WHERE game_date = '{target_date}'
    ORDER BY signal_tag
    """
    try:
        return list(bq_client.query(query).result())
    except Exception as e:
        logger.warning(f"Query failed for {target_date}: {e}")
        return []


def build_weight_section(health_rows):
    """Compare current UNDER weights to live HR."""
    lines = ["*UNDER Signal Weights vs Live HR:*"]
    lines.append("```")
    lines.append(f"{'Signal':<35} {'Weight':>6} {'HR_14d':>7} {'N_14d':>6} {'Status':>10}")
    lines.append("-" * 70)

    for tag, weight in sorted(CURRENT_UNDER_WEIGHTS.items()):
        row = next((r for r in health_rows if r.signal_tag == tag), None)
        if row:
            hr = row.hr_14d or 0
            n = row.picks_14d or 0
            if hr < BREAKEVEN_HR and n >= 15:
                status = "BELOW_BE"
            elif hr < 55 and n >= 15:
                status = "MARGINAL"
            elif n < 15:
                status = "LOW_N"
            else:
                status = "OK"
            lines.append(f"{tag:<35} {weight:>6.1f} {hr:>6.1f}% {n:>5} {status:>10}")
        else:
            lines.append(f"{tag:<35} {weight:>6.1f}    N/A   N/A    NO_DATA")

    lines.append("```")
    return '\n'.join(lines)


def build_promotion_section(health_rows):
    """Find shadow signals meeting promotion criteria."""
    # Shadow signals = those in signal_health but NOT in CURRENT_UNDER_WEIGHTS
    # and not base signals
    base_tags = {'model_health', 'high_edge', 'edge_spread_optimal',
                 'blowout_recovery', 'starter_under', 'blowout_risk_under'}
    known_active = set(CURRENT_UNDER_WEIGHTS.keys()) | base_tags | {
        'fast_pace_over', 'line_rising_over', 'volatile_scoring_over',
        'high_scoring_environment_over', 'sharp_book_lean_over',
    }

    candidates = []
    for row in health_rows:
        if row.signal_tag in known_active:
            continue
        hr = row.hr_season or 0
        n = row.picks_season or 0

        if n >= PROMOTION_N and hr >= PROMOTION_HR:
            candidates.append(('PRODUCTION', row.signal_tag, hr, n))
        elif n >= RESCUE_N and hr >= RESCUE_HR:
            candidates.append(('RESCUE', row.signal_tag, hr, n))

    if not candidates:
        return "*Shadow Signal Promotion:* None ready"

    lines = ["*Shadow Signal Promotion Candidates:*"]
    lines.append("```")
    for level, tag, hr, n in sorted(candidates, key=lambda x: -x[2]):
        lines.append(f"  {tag}: {hr:.1f}% HR (N={n}) -> READY for {level}")
    lines.append("```")
    return '\n'.join(lines)


def build_concern_section(health_rows):
    """Flag active signals with concerning trends."""
    concerns = []
    for tag in CURRENT_UNDER_WEIGHTS:
        row = next((r for r in health_rows if r.signal_tag == tag), None)
        if not row:
            continue
        hr_14d = row.hr_14d or 0
        n_14d = row.picks_14d or 0
        if n_14d >= 15 and hr_14d < BREAKEVEN_HR:
            concerns.append((tag, hr_14d, n_14d))

    if not concerns:
        return "*Active Signal Concerns:* None"

    lines = ["*Active Signal Concerns (below breakeven 14d):*"]
    for tag, hr, n in sorted(concerns, key=lambda x: x[1]):
        lines.append(f"  :warning: `{tag}`: {hr:.1f}% HR (N={n}) — below {BREAKEVEN_HR}% breakeven")
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Signal weight and promotion report')
    parser.add_argument('--date', default=str(date.today()), help='Target date')
    parser.add_argument('--dry-run', action='store_true', help='Print only, no Slack')
    args = parser.parse_args()

    bq_client = bigquery.Client(project=PROJECT_ID)

    # Try target date, then previous days
    health_rows = []
    for offset in range(3):
        d = str(date.fromisoformat(args.date) - timedelta(days=offset))
        health_rows = query_signal_health(bq_client, d)
        if health_rows:
            logger.info(f"Using signal health data from {d}")
            break

    if not health_rows:
        print("No signal health data found in last 3 days")
        return

    weight_section = build_weight_section(health_rows)
    promotion_section = build_promotion_section(health_rows)
    concern_section = build_concern_section(health_rows)

    report = f"""Signal Weight & Promotion Report ({args.date})

{weight_section}

{promotion_section}

{concern_section}"""

    print(report)

    if not args.dry_run:
        try:
            from shared.utils.slack_alerts import send_slack_alert
            send_slack_alert(report, channel='#nba-alerts')
            logger.info("Report sent to #nba-alerts")
        except Exception as e:
            logger.warning(f"Failed to send Slack report: {e}")


def http_handler(request=None):
    """HTTP entry point for Cloud Scheduler."""
    try:
        sys.argv = ['signal_weight_report']
        main()
        return ('{"status": "ok"}', 200, {'Content-Type': 'application/json'})
    except Exception as e:
        logger.error(f"Signal weight report failed: {e}")
        return (f'{{"status": "error", "message": "{e}"}}', 200,
                {'Content-Type': 'application/json'})


if __name__ == '__main__':
    main()
