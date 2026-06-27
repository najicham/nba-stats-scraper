#!/usr/bin/env python3
"""
B1 — MLB Direction Regime Monitor (Session 4, 2026-05-13)

Watches the MLB regressor's UNDER predictions for a degrading regime. Reads
graded predictions from `mlb_predictions.prediction_accuracy`, computes a 7d
rolling hit rate, and fires a Slack alert when the combined T1 AND (T3 OR T4)
trigger flips on a previously-HEALTHY day.

Thresholds were recalibrated in Session 4 after the spec defaults
(N>=25, slope -2pp, T1 OR (T3 AND T4)) over-fired (8 fires/season 2024,
12 fires/season 2025; stop condition was <=3). See
`docs/08-projects/current/mlb-comprehensive-review-2026-05-12/09-B1-BACKTEST-QUERY.md`.

Recalibrated thresholds (1 fire/season on 2024-2025 walk-forward):
  T1: 7d HR < 50% with N >= 35
  T3: 7d slope < -3pp/day
  T4: 7d z-score vs 28d baseline < -2
  Combined: T1 AND (T3 OR T4)

State machine persisted in `mlb_orchestration.direction_regime_state` —
one row per (sport, direction). Prevents double-alerting on consecutive
fires. Transitions: HEALTHY -> DEGRADING (alert), DEGRADING -> RECOVERED
(alert), RECOVERED -> HEALTHY (silent).

Usage:
    PYTHONPATH=. python bin/monitoring/mlb_regime_monitor.py
    PYTHONPATH=. python bin/monitoring/mlb_regime_monitor.py --dry-run
    PYTHONPATH=. python bin/monitoring/mlb_regime_monitor.py --as-of 2026-05-12

Exit codes: 0=success (regardless of trigger state), 1=hard error.
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "nba-props-platform")
SPORT = "MLB"
DIRECTION = "UNDER"

# Recalibrated thresholds (Session 4)
T1_N_FLOOR = 35
T1_HR_CEILING = 0.50
T3_SLOPE_FLOOR = -0.03   # delta hr_7d vs prior day
T4_Z_FLOOR = -2.0

SLACK_CHANNEL = "#nba-betting-signals"


def get_bq_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT_ID)


def compute_regime(bq_client: bigquery.Client, as_of: date) -> Optional[dict]:
    """Return the regime snapshot for `as_of`.

    Returns a dict with 7d HR, 7d N, lagged HR, 28d mean/std, and trigger
    fires — or None if there isn't enough data to evaluate (need 28d of
    rolling history plus a lagged day).
    """
    query = """
    WITH daily_under AS (
      SELECT
        game_date,
        COUNTIF(recommendation = 'UNDER') AS daily_n,
        COUNTIF(recommendation = 'UNDER' AND prediction_correct) AS daily_hits
      FROM `nba-props-platform.mlb_predictions.prediction_accuracy`
      WHERE game_date BETWEEN DATE_SUB(@as_of, INTERVAL 60 DAY) AND @as_of
        AND recommendation = 'UNDER'
        AND has_prop_line = TRUE
        AND prediction_correct IS NOT NULL
      GROUP BY game_date
    ),
    rolling_7d AS (
      SELECT
        game_date,
        SUM(daily_n) OVER w7  AS n_7d,
        SUM(daily_hits) OVER w7 AS hits_7d,
        SAFE_DIVIDE(SUM(daily_hits) OVER w7, SUM(daily_n) OVER w7) AS hr_7d
      FROM daily_under
      WINDOW w7 AS (
        ORDER BY UNIX_DATE(game_date)
        RANGE BETWEEN 6 PRECEDING AND CURRENT ROW
      )
    ),
    rolling_28d AS (
      SELECT
        game_date,
        AVG(hr_7d) OVER w28 AS mean_28d,
        STDDEV(hr_7d) OVER w28 AS std_28d
      FROM rolling_7d
      WINDOW w28 AS (
        ORDER BY UNIX_DATE(game_date)
        RANGE BETWEEN 28 PRECEDING AND 1 PRECEDING
      )
    ),
    enriched AS (
      SELECT
        r.game_date,
        r.n_7d,
        r.hits_7d,
        r.hr_7d,
        LAG(r.hr_7d) OVER (ORDER BY r.game_date) AS hr_7d_prev,
        r28.mean_28d,
        r28.std_28d
      FROM rolling_7d r
      LEFT JOIN rolling_28d r28 USING (game_date)
    )
    SELECT * FROM enriched WHERE game_date = @as_of
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('as_of', 'DATE', as_of),
        ]
    )
    rows = list(bq_client.query(query, job_config=job_config).result())
    if not rows:
        return None
    return dict(rows[0])


def evaluate_triggers(snapshot: dict) -> dict:
    """Apply recalibrated thresholds. Returns trigger booleans + combined."""
    n_7d = snapshot.get('n_7d') or 0
    hr_7d = snapshot.get('hr_7d')
    hr_7d_prev = snapshot.get('hr_7d_prev')
    mean_28d = snapshot.get('mean_28d')
    std_28d = snapshot.get('std_28d')

    t1 = bool(n_7d >= T1_N_FLOOR and hr_7d is not None and hr_7d < T1_HR_CEILING)
    t3 = bool(
        hr_7d is not None and hr_7d_prev is not None
        and (hr_7d - hr_7d_prev) < T3_SLOPE_FLOOR
    )
    t4 = bool(
        hr_7d is not None and mean_28d is not None
        and std_28d is not None and std_28d > 0
        and ((hr_7d - mean_28d) / std_28d) < T4_Z_FLOOR
    )
    combined = t1 and (t3 or t4)
    return {'t1': t1, 't3': t3, 't4': t4, 'combined': combined}


def load_state(bq_client: bigquery.Client) -> Optional[dict]:
    """Read current state row, if any."""
    query = f"""
    SELECT *
    FROM `{PROJECT_ID}.mlb_orchestration.direction_regime_state`
    WHERE sport = @sport AND direction = @direction
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('sport', 'STRING', SPORT),
            bigquery.ScalarQueryParameter('direction', 'STRING', DIRECTION),
        ]
    )
    rows = list(bq_client.query(query, job_config=job_config).result())
    if not rows:
        return None
    return dict(rows[0])


def upsert_state(
    bq_client: bigquery.Client,
    new_state: str,
    snapshot: dict,
    triggers: dict,
    as_of: date,
    alert_sent: bool,
    alert_msg: Optional[str],
    notes: Optional[str] = None,
) -> None:
    """MERGE the state row. Uses DML (single-row, low-frequency)."""
    state_since = as_of if new_state != 'HEALTHY' else as_of
    now = datetime.now(timezone.utc)
    query = f"""
    MERGE `{PROJECT_ID}.mlb_orchestration.direction_regime_state` T
    USING (SELECT @sport AS sport, @direction AS direction) S
    ON T.sport = S.sport AND T.direction = S.direction
    WHEN MATCHED THEN UPDATE SET
      state = @state,
      state_since = CASE WHEN T.state != @state THEN @state_since ELSE T.state_since END,
      last_evaluated_date = @as_of,
      last_evaluated_at = @now,
      last_alert_at = CASE WHEN @alert_sent THEN @now ELSE T.last_alert_at END,
      last_alert_message = CASE WHEN @alert_sent THEN @alert_msg ELSE T.last_alert_message END,
      last_fire_hr_7d = @hr_7d,
      last_fire_n_7d = @n_7d,
      last_fire_t1 = @t1,
      last_fire_t3 = @t3,
      last_fire_t4 = @t4,
      notes = COALESCE(@notes, T.notes)
    WHEN NOT MATCHED THEN INSERT (
      sport, direction, state, state_since, last_evaluated_date, last_evaluated_at,
      last_alert_at, last_alert_message, last_fire_hr_7d, last_fire_n_7d,
      last_fire_t1, last_fire_t3, last_fire_t4, notes
    ) VALUES (
      @sport, @direction, @state, @state_since, @as_of, @now,
      CASE WHEN @alert_sent THEN @now ELSE NULL END,
      CASE WHEN @alert_sent THEN @alert_msg ELSE NULL END,
      @hr_7d, @n_7d, @t1, @t3, @t4, @notes
    )
    """
    hr_7d_val = snapshot.get('hr_7d')
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('sport', 'STRING', SPORT),
            bigquery.ScalarQueryParameter('direction', 'STRING', DIRECTION),
            bigquery.ScalarQueryParameter('state', 'STRING', new_state),
            bigquery.ScalarQueryParameter('state_since', 'DATE', state_since),
            bigquery.ScalarQueryParameter('as_of', 'DATE', as_of),
            bigquery.ScalarQueryParameter('now', 'TIMESTAMP', now),
            bigquery.ScalarQueryParameter('alert_sent', 'BOOL', alert_sent),
            bigquery.ScalarQueryParameter('alert_msg', 'STRING', alert_msg or ''),
            bigquery.ScalarQueryParameter(
                'hr_7d', 'FLOAT64',
                float(hr_7d_val) if hr_7d_val is not None else None
            ),
            bigquery.ScalarQueryParameter(
                'n_7d', 'INT64', int(snapshot.get('n_7d') or 0)
            ),
            bigquery.ScalarQueryParameter('t1', 'BOOL', triggers['t1']),
            bigquery.ScalarQueryParameter('t3', 'BOOL', triggers['t3']),
            bigquery.ScalarQueryParameter('t4', 'BOOL', triggers['t4']),
            bigquery.ScalarQueryParameter('notes', 'STRING', notes),
        ]
    )
    bq_client.query(query, job_config=job_config).result()


def build_alert_message(
    direction: str,
    transition: str,
    snapshot: dict,
    triggers: dict,
    as_of: date,
) -> str:
    """Format Slack message."""
    hr_7d = snapshot.get('hr_7d') or 0.0
    hr_7d_prev = snapshot.get('hr_7d_prev')
    mean_28d = snapshot.get('mean_28d')
    std_28d = snapshot.get('std_28d')
    n_7d = snapshot.get('n_7d') or 0

    fired_names = [name for name, hit in
                   [('T1', triggers['t1']), ('T3', triggers['t3']), ('T4', triggers['t4'])]
                   if hit]

    if transition == 'DEGRADING':
        prefix = f":rotating_light: *MLB {direction} regime DEGRADING* ({as_of})"
    elif transition == 'RECOVERED':
        prefix = f":white_check_mark: *MLB {direction} regime RECOVERED* ({as_of})"
    else:
        prefix = f"MLB {direction} regime update ({as_of})"

    z_score = None
    if mean_28d is not None and std_28d and std_28d > 0:
        z_score = (hr_7d - mean_28d) / std_28d

    lines = [
        prefix,
        f"• 7d HR: {hr_7d * 100:.1f}% (N={n_7d})",
    ]
    if hr_7d_prev is not None:
        slope_pp = (hr_7d - hr_7d_prev) * 100
        lines.append(
            f"• vs yesterday: {hr_7d_prev * 100:.1f}% (Δ {slope_pp:+.1f}pp)"
        )
    if mean_28d is not None:
        lines.append(
            f"• 28d mean: {mean_28d * 100:.1f}%"
            + (f" (z = {z_score:+.2f}σ)" if z_score is not None else "")
        )
    if fired_names:
        lines.append(f"• Triggers fired: {', '.join(fired_names)}")
    lines.append(
        "• Action: review recent UNDER predictions; raw regressor may be over-predicting K. "
        "If UNDER is re-enabled in production, consider pausing UNDER picks."
    )
    return "\n".join(lines)


def decide_transition(prior_state: Optional[str], combined_fired: bool) -> str:
    """Return the new state given prior state and current trigger."""
    if prior_state is None:
        # First eval ever
        return 'DEGRADING' if combined_fired else 'HEALTHY'
    if combined_fired:
        return 'DEGRADING'
    # Not fired
    if prior_state == 'DEGRADING':
        return 'RECOVERED'
    if prior_state == 'RECOVERED':
        return 'HEALTHY'
    return 'HEALTHY'


def main():
    parser = argparse.ArgumentParser(description="MLB B1 Direction Regime Monitor")
    parser.add_argument(
        '--as-of', type=str, default=None,
        help='Date to evaluate (YYYY-MM-DD). Defaults to yesterday (ET).'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Compute and log but do not write state or send Slack.'
    )
    args = parser.parse_args()

    if args.as_of:
        as_of = date.fromisoformat(args.as_of)
    else:
        # Yesterday in ET (post-grading window)
        from zoneinfo import ZoneInfo
        as_of = (datetime.now(ZoneInfo('America/New_York')) - timedelta(days=1)).date()

    logger.info(f"Evaluating MLB {DIRECTION} regime for {as_of}")

    bq_client = get_bq_client()

    snapshot = compute_regime(bq_client, as_of)
    if snapshot is None or snapshot.get('hr_7d') is None:
        logger.info(f"Insufficient data to evaluate regime for {as_of}. Exiting.")
        return 0

    triggers = evaluate_triggers(snapshot)
    prior = load_state(bq_client)
    prior_state = prior['state'] if prior else None
    new_state = decide_transition(prior_state, triggers['combined'])

    transition_kind = 'NONE'
    if prior_state != new_state:
        if new_state == 'DEGRADING':
            transition_kind = 'DEGRADING'
        elif new_state == 'RECOVERED':
            transition_kind = 'RECOVERED'

    logger.info(
        f"snapshot: hr_7d={snapshot.get('hr_7d')}, n_7d={snapshot.get('n_7d')}, "
        f"prev={snapshot.get('hr_7d_prev')}, mean_28d={snapshot.get('mean_28d')}, "
        f"std_28d={snapshot.get('std_28d')}"
    )
    logger.info(
        f"triggers: t1={triggers['t1']}, t3={triggers['t3']}, t4={triggers['t4']}, "
        f"combined={triggers['combined']}"
    )
    logger.info(f"state: prior={prior_state}, new={new_state}, transition={transition_kind}")

    alert_msg = None
    alert_sent = False
    if transition_kind in ('DEGRADING', 'RECOVERED'):
        alert_msg = build_alert_message(DIRECTION, transition_kind, snapshot, triggers, as_of)
        if args.dry_run:
            logger.info(f"[DRY-RUN] Would send Slack alert:\n{alert_msg}")
        else:
            try:
                from shared.utils.slack_alerts import send_slack_alert
                alert_sent = send_slack_alert(
                    alert_msg, channel=SLACK_CHANNEL,
                    alert_type=f'MLB_REGIME_{transition_kind}'
                )
            except Exception as e:
                logger.error(f"Slack alert failed: {e}")
                alert_sent = False

    if args.dry_run:
        logger.info("[DRY-RUN] Skipping state upsert.")
    else:
        upsert_state(
            bq_client, new_state, snapshot, triggers, as_of,
            alert_sent, alert_msg,
            notes=None,
        )

    return 0


if __name__ == '__main__':
    sys.exit(main())
