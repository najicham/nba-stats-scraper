#!/usr/bin/env python3
"""Bias Decay Monitor — detect model-vs-Vegas edge drift per model.

Reads `model_performance_daily` (latest row per enabled model) and fires Slack
alerts based on `mae_gap_7d` (model_mae_7d − vegas_mae_7d):

  - LOST_EDGE:  `mae_gap_7d > 1.0 K` on >=5 of last 7 days  (primary alert)
  - LOSING_BAD: `mae_gap_7d > 2.0 K` on >=3 of last 5 days  (urgent)

Followup to the 2025-26 NBA anomaly diagnosis at
`docs/08-projects/current/2026-05-15-2025-26-anomaly-rootcause/`. Validation
in section 4 of the monitoring plan showed that per-model `pred_bias` is too
noisy to alert on directly (~60% of healthy 2024-25 days exceeded |1.5K|), but
`mae_gap` cleanly separates anomalous from healthy: median mae_gap_7d was
0.39 K in 2024-25 vs 1.44 K in Nov 2025.

`pred_bias_7d/14d/30d` are still computed and persisted in
`model_performance_daily` as diagnostic columns (visible in the admin
dashboard and useful for investigation), but they do NOT trigger alerts on
their own.

Alert-only — does not auto-disable. Same channel as `signal_decay_monitor`.

Usage:
    PYTHONPATH=. python bin/monitoring/bias_decay_monitor.py
    PYTHONPATH=. python bin/monitoring/bias_decay_monitor.py --date 2026-02-15
    PYTHONPATH=. python bin/monitoring/bias_decay_monitor.py --dry-run

Created: 2026-05-15 (anomaly follow-up).
"""

import argparse
import json
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

# Thresholds + classify_verdict() live in a shared module so the Slack alerter
# and the admin dashboard view can't drift apart. Source of truth:
# shared/monitoring/bias_decay_thresholds.py
from shared.monitoring.bias_decay_thresholds import (  # noqa: E402
    LOST_EDGE_MAE_GAP,
    LOST_EDGE_DAYS_REQUIRED,
    LOST_EDGE_WINDOW,
    LOSING_BAD_MAE_GAP,
    LOSING_BAD_DAYS_REQUIRED,
    LOSING_BAD_WINDOW,
    MIN_N_FOR_VERDICT,
    classify_verdict,
)


def query_latest_per_model(bq_client: bigquery.Client, target_date: date) -> list:
    """Latest model_performance_daily row per enabled model, plus a lookback window.

    Returns one record per enabled model (most-recent row within last 7 days),
    enriched with consecutive-day counts derived from a 14-day lookback so we
    can detect DRIFTING (3+ days) and LOST_EDGE (7+ days) patterns.
    """
    query = """
    WITH active AS (
      SELECT model_id
      FROM `nba-props-platform.nba_predictions.model_registry`
      WHERE enabled = TRUE
    ),
    recent AS (
      SELECT
        mpd.game_date,
        mpd.model_id,
        mpd.pred_bias_7d,
        mpd.pred_bias_14d,
        mpd.model_mae_7d,
        mpd.vegas_mae_7d,
        mpd.mae_gap_7d,
        mpd.rolling_hr_7d,
        mpd.rolling_n_7d,
        mpd.state AS hr_state,
        ROW_NUMBER() OVER (
          PARTITION BY mpd.model_id ORDER BY mpd.game_date DESC
        ) AS rn
      FROM `nba-props-platform.nba_predictions.model_performance_daily` mpd
      JOIN active a USING (model_id)
      WHERE mpd.game_date BETWEEN DATE_SUB(@target_date, INTERVAL 14 DAY)
                              AND @target_date
    ),
    consec AS (
      SELECT
        model_id,
        COUNTIF(mae_gap_7d > @lost_edge_gap
                AND game_date > DATE_SUB(@target_date, INTERVAL @lost_edge_window DAY)) AS lost_edge_days,
        COUNTIF(mae_gap_7d > @losing_bad_gap
                AND game_date > DATE_SUB(@target_date, INTERVAL @losing_bad_window DAY)) AS losing_bad_days
      FROM recent
      GROUP BY model_id
    )
    SELECT
      r.game_date, r.model_id,
      r.pred_bias_7d, r.pred_bias_14d,
      r.model_mae_7d, r.vegas_mae_7d, r.mae_gap_7d,
      r.rolling_hr_7d, r.rolling_n_7d, r.hr_state,
      c.lost_edge_days, c.losing_bad_days
    FROM recent r
    JOIN consec c USING (model_id)
    WHERE r.rn = 1
    ORDER BY r.model_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('lost_edge_gap', 'FLOAT64', LOST_EDGE_MAE_GAP),
            bigquery.ScalarQueryParameter('lost_edge_window', 'INT64', LOST_EDGE_WINDOW),
            bigquery.ScalarQueryParameter('losing_bad_gap', 'FLOAT64', LOSING_BAD_MAE_GAP),
            bigquery.ScalarQueryParameter('losing_bad_window', 'INT64', LOSING_BAD_WINDOW),
        ]
    )
    rows = bq_client.query(query, job_config=job_config).result(timeout=60)
    return [dict(r) for r in rows]


def classify(rows: list) -> dict:
    """Classify each model into actionable buckets based on mae_gap_7d.

    Buckets (mutually exclusive — most severe wins):
      losing_bad: mae_gap_7d > 2.0 K on >=3 of last 5 days  (urgent)
      lost_edge:  mae_gap_7d > 1.0 K on >=5 of last 7 days  (primary)
      watch:      mae_gap_7d > 0.5 K (single day)
      healthy:    everything else
      insufficient_data: rolling_n_7d < MIN_N_FOR_VERDICT or mae_gap_7d NULL

    Per-row classification delegates to `shared.monitoring.bias_decay_thresholds.classify_verdict`.
    This function only adds the human-readable `verdict` string and groups rows.
    """
    buckets = {
        'losing_bad': [],
        'lost_edge': [],
        'watch': [],
        'healthy': [],
        'insufficient_data': [],
    }
    # Map shared classify_verdict() return values to local bucket keys.
    verdict_to_bucket = {
        'LOSING_BAD': 'losing_bad',
        'LOST_EDGE': 'lost_edge',
        'WATCH': 'watch',
        'HEALTHY': 'healthy',
        'INSUFFICIENT_DATA': 'insufficient_data',
    }

    for r in rows:
        n = r.get('rolling_n_7d') or 0
        gap = r.get('mae_gap_7d')
        bias = r.get('pred_bias_7d')

        entry = {
            'model_id': r['model_id'],
            'game_date': r['game_date'],
            'pred_bias_7d': bias,
            'mae_gap_7d': gap,
            'model_mae_7d': r.get('model_mae_7d'),
            'vegas_mae_7d': r.get('vegas_mae_7d'),
            'rolling_hr_7d': r.get('rolling_hr_7d'),
            'rolling_n_7d': n,
            'lost_edge_days': r.get('lost_edge_days') or 0,
            'losing_bad_days': r.get('losing_bad_days') or 0,
        }

        verdict = classify_verdict(entry)
        bucket_key = verdict_to_bucket[verdict]

        # Add a human-readable string for the alert/report output.
        if verdict == 'LOSING_BAD':
            entry['verdict'] = (
                f"LOSING_BAD: mae_gap_7d={gap:+.2f} K > {LOSING_BAD_MAE_GAP} "
                f"on {entry['losing_bad_days']} of last {LOSING_BAD_WINDOW} days — "
                f"retrain or disable"
            )
        elif verdict == 'LOST_EDGE':
            entry['verdict'] = (
                f"LOST_EDGE: mae_gap_7d={gap:+.2f} K (model_mae − vegas_mae) "
                f"on {entry['lost_edge_days']} of last {LOST_EDGE_WINDOW} days — "
                f"Vegas is sharper"
            )
        elif verdict == 'WATCH':
            entry['verdict'] = (
                f"WATCH: mae_gap_7d={gap:+.2f} K "
                f"(pred_bias_7d={(bias if bias is not None else 0):+.2f}, N={n})"
            )

        buckets[bucket_key].append(entry)

    return buckets


def format_report(buckets: dict, target_date) -> str:
    lines = [f"Bias Decay Monitor — {target_date}", "=" * 50]

    def _emit(name, items):
        if not items:
            return
        lines.append(f"\n{name.upper()} ({len(items)}):")
        for it in items:
            lines.append(f"  {it['model_id']}: {it['verdict']}")

    _emit('losing_bad', buckets['losing_bad'])
    _emit('lost_edge', buckets['lost_edge'])
    _emit('watch', buckets['watch'])

    lines.append(f"\nHEALTHY: {len(buckets['healthy'])} models")
    for h in buckets['healthy']:
        bias_str = (f"{h['pred_bias_7d']:+.2f}" if h['pred_bias_7d'] is not None
                    else 'n/a')
        gap_str = (f"{h['mae_gap_7d']:+.2f}" if h['mae_gap_7d'] is not None
                   else 'n/a')
        lines.append(
            f"  {h['model_id']}: mae_gap_7d={gap_str} K "
            f"(pred_bias={bias_str}, N={h['rolling_n_7d']})"
        )

    if buckets['insufficient_data']:
        lines.append(
            f"\nINSUFFICIENT DATA: {len(buckets['insufficient_data'])} models "
            f"(N < {MIN_N_FOR_VERDICT} or mae_gap NULL)"
        )
        for i in buckets['insufficient_data']:
            lines.append(f"  {i['model_id']}: N={i['rolling_n_7d']}")

    return '\n'.join(lines)


def build_slack_message(buckets: dict, target_date) -> str:
    """Slack alert body. Only called when there's something actionable."""
    lines = [f":warning: *Bias Decay Monitor — {target_date}*"]

    if buckets['losing_bad']:
        lines.append(f"\n:rotating_light: *LOSING_BAD ({len(buckets['losing_bad'])})*")
        for it in buckets['losing_bad']:
            lines.append(f"  • `{it['model_id']}`: {it['verdict']}")

    if buckets['lost_edge']:
        lines.append(f"\n:chart_with_downwards_trend: *LOST_EDGE ({len(buckets['lost_edge'])})*")
        for it in buckets['lost_edge']:
            lines.append(f"  • `{it['model_id']}`: {it['verdict']}")

    lines.append(
        "\n_Recommended action: `./bin/retrain.sh MODEL_ID --enable` or "
        "`python bin/deactivate_model.py MODEL_ID`._"
    )
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Bias decay monitor')
    parser.add_argument('--date', help='Target date (YYYY-MM-DD)',
                        default=str(date.today()))
    parser.add_argument('--dry-run', action='store_true',
                        help='Print report only, no Slack alerts')
    args = parser.parse_args()

    target = date.fromisoformat(args.date)
    bq_client = bigquery.Client(project=PROJECT_ID)

    logger.info(f"Checking bias/mae drift for {target}")
    rows = query_latest_per_model(bq_client, target)

    if not rows:
        # Try previous day if target has no rows yet (typical when run early ET)
        prev = target - timedelta(days=1)
        logger.info(f"No rows for {target}, trying {prev}")
        rows = query_latest_per_model(bq_client, prev)

    if not rows:
        logger.warning("No model_performance_daily rows found")
        return

    buckets = classify(rows)
    print(format_report(buckets, target))

    has_alerts = (buckets['losing_bad'] or buckets['lost_edge'])
    if has_alerts and not args.dry_run:
        try:
            from shared.utils.slack_alerts import send_slack_alert
            msg = build_slack_message(buckets, target)
            sent = send_slack_alert(
                msg,
                channel='#nba-betting-signals',
                alert_type='bias_decay',
            )
            if sent:
                n_alert = len(buckets['losing_bad']) + len(buckets['lost_edge'])
                logger.info(f"Sent Slack alert for {n_alert} models")
            else:
                logger.warning("Slack alert send returned False")
        except Exception as e:
            logger.warning(f"Failed to send Slack alert: {e}")


def http_handler(request=None):
    """HTTP entry point for Cloud Scheduler invocation."""
    try:
        sys.argv = ['bias_decay_monitor']
        main()
        return ('{"status": "ok"}', 200, {'Content-Type': 'application/json'})
    except Exception as e:
        logger.error(f"Bias decay monitor failed: {e}")
        body = json.dumps({"status": "error", "message": str(e)})
        return (body, 200, {'Content-Type': 'application/json'})


if __name__ == '__main__':
    main()
