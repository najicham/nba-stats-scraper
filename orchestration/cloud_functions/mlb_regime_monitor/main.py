"""
MLB Regime Monitor (B1) — Daily Cloud Function

Watches `mlb_predictions.prediction_accuracy` UNDER rows for a degrading
regime. Computes 7d rolling HR, evaluates T1/T3/T4 triggers, persists state
in `mlb_orchestration.direction_regime_state`, and sends a Slack alert on
HEALTHY → DEGRADING or DEGRADING → RECOVERED transitions.

Schedule: 09:00 UTC daily (after grading completes for the prior ET day).
Trigger: HTTP (Cloud Scheduler). Optional body
`{"target_date": "YYYY-MM-DD", "dry_run": false}`; defaults to yesterday ET.

Recalibrated thresholds (Session 4 backtest on 2024-2025 WF data):
  T1: 7d HR < 50% with N >= 35
  T3: 7d slope < -3pp/day
  T4: 7d z-score vs 28d baseline < -2
  Combined: T1 AND (T3 OR T4)

Spec defaults (N>=25, slope -2pp, T1 OR (T3 AND T4)) over-fired in backtest:
8 fires/2024, 12 fires/2025 (stop condition <=3). See
`docs/08-projects/current/mlb-comprehensive-review-2026-05-12/09-B1-BACKTEST-QUERY.md`.
"""

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import functions_framework
import urllib.request
from google.cloud import bigquery

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "nba-props-platform")
SPORT = "MLB"
DIRECTION = "UNDER"
ET = ZoneInfo("America/New_York")

# Recalibrated thresholds
T1_N_FLOOR = 35
T1_HR_CEILING = 0.50
T3_SLOPE_FLOOR = -0.03
T4_Z_FLOOR = -2.0

SLACK_CHANNEL = "#nba-betting-signals"
SLACK_WEBHOOK_ENV = "SLACK_WEBHOOK_URL_SIGNALS"


def _parse_request(request_json) -> tuple[date, bool]:
    """Return (target_date, dry_run)."""
    target_date = None
    dry_run = False
    if request_json and isinstance(request_json, dict):
        td = request_json.get("target_date")
        if td:
            target_date = date.fromisoformat(str(td))
        dry_run = bool(request_json.get("dry_run", False))
    if target_date is None:
        target_date = (datetime.now(ET) - timedelta(days=1)).date()
    return target_date, dry_run


def _compute_regime(client: bigquery.Client, as_of: date) -> Optional[dict]:
    query = f"""
    WITH daily_under AS (
      SELECT
        game_date,
        COUNTIF(recommendation = 'UNDER') AS daily_n,
        COUNTIF(recommendation = 'UNDER' AND prediction_correct) AS daily_hits
      FROM `{PROJECT_ID}.mlb_predictions.prediction_accuracy`
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
        query_parameters=[bigquery.ScalarQueryParameter("as_of", "DATE", as_of)]
    )
    rows = list(client.query(query, job_config=job_config).result())
    if not rows:
        return None
    return dict(rows[0])


def _evaluate_triggers(snap: dict) -> dict:
    n_7d = snap.get("n_7d") or 0
    hr_7d = snap.get("hr_7d")
    hr_7d_prev = snap.get("hr_7d_prev")
    mean_28d = snap.get("mean_28d")
    std_28d = snap.get("std_28d")
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
    return {"t1": t1, "t3": t3, "t4": t4, "combined": t1 and (t3 or t4)}


def _load_state(client: bigquery.Client) -> Optional[dict]:
    query = f"""
    SELECT * FROM `{PROJECT_ID}.mlb_orchestration.direction_regime_state`
    WHERE sport = @sport AND direction = @direction LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("sport", "STRING", SPORT),
            bigquery.ScalarQueryParameter("direction", "STRING", DIRECTION),
        ]
    )
    rows = list(client.query(query, job_config=job_config).result())
    return dict(rows[0]) if rows else None


def _upsert_state(
    client: bigquery.Client,
    new_state: str,
    snap: dict,
    triggers: dict,
    as_of: date,
    alert_sent: bool,
    alert_msg: Optional[str],
) -> None:
    now = datetime.now(timezone.utc)
    hr_7d_val = snap.get("hr_7d")
    query = f"""
    MERGE `{PROJECT_ID}.mlb_orchestration.direction_regime_state` T
    USING (SELECT @sport AS sport, @direction AS direction) S
    ON T.sport = S.sport AND T.direction = S.direction
    WHEN MATCHED THEN UPDATE SET
      state = @state,
      state_since = CASE WHEN T.state != @state THEN @as_of ELSE T.state_since END,
      last_evaluated_date = @as_of,
      last_evaluated_at = @now,
      last_alert_at = CASE WHEN @alert_sent THEN @now ELSE T.last_alert_at END,
      last_alert_message = CASE WHEN @alert_sent THEN @alert_msg ELSE T.last_alert_message END,
      last_fire_hr_7d = @hr_7d,
      last_fire_n_7d = @n_7d,
      last_fire_t1 = @t1,
      last_fire_t3 = @t3,
      last_fire_t4 = @t4
    WHEN NOT MATCHED THEN INSERT (
      sport, direction, state, state_since, last_evaluated_date, last_evaluated_at,
      last_alert_at, last_alert_message, last_fire_hr_7d, last_fire_n_7d,
      last_fire_t1, last_fire_t3, last_fire_t4
    ) VALUES (
      @sport, @direction, @state, @as_of, @as_of, @now,
      CASE WHEN @alert_sent THEN @now ELSE NULL END,
      CASE WHEN @alert_sent THEN @alert_msg ELSE NULL END,
      @hr_7d, @n_7d, @t1, @t3, @t4
    )
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("sport", "STRING", SPORT),
            bigquery.ScalarQueryParameter("direction", "STRING", DIRECTION),
            bigquery.ScalarQueryParameter("state", "STRING", new_state),
            bigquery.ScalarQueryParameter("as_of", "DATE", as_of),
            bigquery.ScalarQueryParameter("now", "TIMESTAMP", now),
            bigquery.ScalarQueryParameter("alert_sent", "BOOL", alert_sent),
            bigquery.ScalarQueryParameter("alert_msg", "STRING", alert_msg or ""),
            bigquery.ScalarQueryParameter(
                "hr_7d", "FLOAT64",
                float(hr_7d_val) if hr_7d_val is not None else None
            ),
            bigquery.ScalarQueryParameter(
                "n_7d", "INT64", int(snap.get("n_7d") or 0)
            ),
            bigquery.ScalarQueryParameter("t1", "BOOL", triggers["t1"]),
            bigquery.ScalarQueryParameter("t3", "BOOL", triggers["t3"]),
            bigquery.ScalarQueryParameter("t4", "BOOL", triggers["t4"]),
        ]
    )
    client.query(query, job_config=job_config).result()


def _decide_transition(prior_state: Optional[str], combined_fired: bool) -> str:
    if prior_state is None:
        return "DEGRADING" if combined_fired else "HEALTHY"
    if combined_fired:
        return "DEGRADING"
    if prior_state == "DEGRADING":
        return "RECOVERED"
    if prior_state == "RECOVERED":
        return "HEALTHY"
    return "HEALTHY"


def _build_alert(transition: str, snap: dict, triggers: dict, as_of: date) -> str:
    hr_7d = snap.get("hr_7d") or 0.0
    hr_7d_prev = snap.get("hr_7d_prev")
    mean_28d = snap.get("mean_28d")
    std_28d = snap.get("std_28d")
    n_7d = snap.get("n_7d") or 0
    z = (hr_7d - mean_28d) / std_28d if (mean_28d is not None and std_28d and std_28d > 0) else None
    fired = [n for n, h in [("T1", triggers["t1"]), ("T3", triggers["t3"]), ("T4", triggers["t4"])] if h]
    if transition == "DEGRADING":
        prefix = f":rotating_light: *MLB {DIRECTION} regime DEGRADING* ({as_of})"
    elif transition == "RECOVERED":
        prefix = f":white_check_mark: *MLB {DIRECTION} regime RECOVERED* ({as_of})"
    else:
        prefix = f"MLB {DIRECTION} regime update ({as_of})"
    lines = [prefix, f"• 7d HR: {hr_7d * 100:.1f}% (N={n_7d})"]
    if hr_7d_prev is not None:
        lines.append(
            f"• vs yesterday: {hr_7d_prev * 100:.1f}% "
            f"(Δ {(hr_7d - hr_7d_prev) * 100:+.1f}pp)"
        )
    if mean_28d is not None:
        lines.append(
            f"• 28d mean: {mean_28d * 100:.1f}%"
            + (f" (z = {z:+.2f}σ)" if z is not None else "")
        )
    if fired:
        lines.append(f"• Triggers fired: {', '.join(fired)}")
    lines.append(
        "• Action: review recent UNDER predictions; raw regressor may be over-predicting K. "
        "If UNDER is re-enabled in production, consider pausing UNDER picks."
    )
    return "\n".join(lines)


def _send_slack(message: str) -> bool:
    webhook = os.environ.get(SLACK_WEBHOOK_ENV) or os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        logger.warning("No Slack webhook configured (%s). Skipping alert.", SLACK_WEBHOOK_ENV)
        return False
    try:
        body = json.dumps({"text": message}).encode("utf-8")
        req = urllib.request.Request(
            webhook, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:
        logger.exception("Slack post failed: %s", exc)
        return False


@functions_framework.http
def regime_monitor(request):
    try:
        request_json = request.get_json(silent=True) if request else None
        as_of, dry_run = _parse_request(request_json)
        logger.info("Evaluating MLB %s regime for %s (dry_run=%s)", DIRECTION, as_of, dry_run)

        client = bigquery.Client(project=PROJECT_ID)
        snap = _compute_regime(client, as_of)
        if snap is None or snap.get("hr_7d") is None:
            logger.info("Insufficient data for %s. Skipping.", as_of)
            return (
                json.dumps({"status": "skipped", "reason": "insufficient_data", "as_of": str(as_of)}),
                200,
                {"Content-Type": "application/json"},
            )

        triggers = _evaluate_triggers(snap)
        prior = _load_state(client)
        prior_state = prior["state"] if prior else None
        new_state = _decide_transition(prior_state, triggers["combined"])

        transition = "NONE"
        if prior_state != new_state and new_state in ("DEGRADING", "RECOVERED"):
            transition = new_state

        alert_msg = None
        alert_sent = False
        if transition in ("DEGRADING", "RECOVERED"):
            alert_msg = _build_alert(transition, snap, triggers, as_of)
            if dry_run:
                logger.info("[DRY-RUN] Would alert:\n%s", alert_msg)
            else:
                alert_sent = _send_slack(alert_msg)

        if not dry_run:
            _upsert_state(client, new_state, snap, triggers, as_of, alert_sent, alert_msg)

        response = {
            "status": "success",
            "as_of": str(as_of),
            "prior_state": prior_state,
            "new_state": new_state,
            "transition": transition,
            "snapshot": {
                "hr_7d": snap.get("hr_7d"),
                "n_7d": snap.get("n_7d"),
                "hr_7d_prev": snap.get("hr_7d_prev"),
                "mean_28d": snap.get("mean_28d"),
                "std_28d": snap.get("std_28d"),
            },
            "triggers": triggers,
            "alert_sent": alert_sent,
            "dry_run": dry_run,
        }
        logger.info("regime_monitor result: %s", json.dumps(response, default=str))
        return (json.dumps(response, default=str), 200, {"Content-Type": "application/json"})

    except Exception as exc:
        logger.exception("regime_monitor failed")
        return (
            json.dumps({"status": "error", "message": str(exc)}),
            500,
            {"Content-Type": "application/json"},
        )


# Gen2 entry-point alias
main = regime_monitor
