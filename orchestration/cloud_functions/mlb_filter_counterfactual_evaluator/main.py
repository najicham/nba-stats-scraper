"""MLB Filter Counterfactual Evaluator Cloud Function.

Computes daily counterfactual hit rate for each MLB negative filter by joining
best_bets_filter_audit (blocked picks) with prediction_accuracy (actuals).
Writes one row per (game_date, filter_name) to filter_counterfactual_daily.

PHASE 1 (initial deploy 2026-05-18): data collection + Slack warnings only.
ELIGIBLE_FOR_AUTO_DEMOTE is intentionally empty — no filter will be
auto-demoted. The CF rolls forward daily so we accumulate the evidence base
needed to populate the eligibility list later. When a filter trends bad
(CF HR >= CF_HR_THRESHOLD for CONSECUTIVE_DAYS), Slack gets an advisory
warning so a human can review.

Triggered by Cloud Scheduler at 11:30 AM ET daily (after MLB grading
backfills actuals into prediction_accuracy).

Ported from orchestration/cloud_functions/filter_counterfactual_evaluator
(NBA, Session 432). MLB differences:
  - Reads mlb_predictions.* tables instead of nba_predictions.*
  - No best_bets_filtered_picks table on MLB side — JOIN at query time
    between best_bets_filter_audit and prediction_accuracy
  - ELIGIBLE list empty until MLB pick/block volume justifies it
  - filter_name is recorded WITHOUT a filter_reason field in MLB audit;
    we use filter_name directly as the key
"""

import functions_framework
import hashlib
import json
import logging
import os
import requests
from datetime import datetime, timezone
from flask import Request
from google.cloud import bigquery
from typing import Dict, List, Optional, Set

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL_ALERTS') or os.environ.get('SLACK_WEBHOOK_URL_WARNING')

# Phase 1: NO auto-demote. CF data is collected daily; humans review trends.
# To enable auto-demote for a specific filter, add its name here.
# Filters known today (since 2026-04-01, with block counts):
#   direction_filter (237)       - structural OVER-only gate, strategy decision
#   away_edge_floor (217)         - core safety, edge gate
#   edge_floor (114)              - core safety, edge gate
#   pitcher_blacklist (53)        - core safety, manual list
#   away_over_blocked_policy (15) - recent BLOCK_ALL_AWAY_OVER policy
#   overconfidence_cap (5)        - MAX_EDGE cap
ELIGIBLE_FOR_AUTO_DEMOTE: Set[str] = set()

# Per-filter overrides for MIN_PICKS_7D when the default (20) is too low.
PER_FILTER_MIN_PICKS_7D: Dict[str, int] = {}

# Core safety filters — NEVER auto-demote even if added to ELIGIBLE accidentally.
NEVER_DEMOTE = {
    'pitcher_blacklist',
    'edge_floor',
    'away_edge_floor',
    'direction_filter',
    'insufficient_data_skip',
    'bullpen_game_skip',
    'il_return_skip',
    'pitch_count_cap_skip',
    'whole_line_over',
}

# Thresholds (mirror NBA defaults; tune later once MLB CF baseline exists)
CF_HR_THRESHOLD = 55.0       # Blocked picks would win >= 55% = filter hurts
MIN_PICKS_PER_DAY = 0
MIN_PICKS_7D = 20            # Need 20+ graded blocked picks over 7 days
CONSECUTIVE_DAYS = 7
MAX_DEMOTIONS_PER_RUN = 2

_bq_client = None


def _get_bq_client():
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


def _send_slack(message: str) -> None:
    if not SLACK_WEBHOOK_URL:
        logger.warning("No SLACK_WEBHOOK_URL_ALERTS configured, skipping alert")
        return
    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json={'text': message}, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Slack alert failed: {e}")


def compute_daily_cf_hr(bq: bigquery.Client, target_date: str) -> List[Dict]:
    """Compute counterfactual HR per filter for a single game date.

    JOINs best_bets_filter_audit (BLOCKED rows only) with prediction_accuracy
    on (pitcher_lookup, game_date, recommendation, line_value). Uses the
    standard MLB join pattern.
    """
    query = f"""
    WITH blocked AS (
      SELECT DISTINCT
        a.filter_name,
        a.pitcher_lookup,
        a.game_date,
        a.recommendation,
        a.line_value
      FROM `{PROJECT_ID}.mlb_predictions.best_bets_filter_audit` a
      WHERE a.game_date = @target_date
        AND a.filter_result = 'BLOCKED'
    ),
    joined AS (
      SELECT
        b.filter_name,
        pa.prediction_correct
      FROM blocked b
      INNER JOIN `{PROJECT_ID}.mlb_predictions.prediction_accuracy` pa
        ON pa.pitcher_lookup = b.pitcher_lookup
        AND pa.game_date = b.game_date
        AND pa.recommendation = b.recommendation
        AND pa.line_value = b.line_value
      WHERE pa.game_date = @target_date
        AND pa.has_prop_line = TRUE
        AND pa.recommendation IN ('OVER', 'UNDER')
    )
    SELECT
      filter_name,
      COUNT(*) AS blocked_count,
      COUNTIF(prediction_correct = TRUE) AS wins,
      COUNTIF(prediction_correct = FALSE) AS losses,
      COUNTIF(prediction_correct IS NULL) AS pushes,
      ROUND(
        100.0 * COUNTIF(prediction_correct = TRUE)
        / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0),
        1
      ) AS counterfactual_hr
    FROM joined
    GROUP BY filter_name
    HAVING COUNT(*) > 0
    ORDER BY blocked_count DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )
    rows = list(bq.query(query, job_config=job_config).result(timeout=60))
    return [dict(row) for row in rows]


def write_daily_cf_hr(bq: bigquery.Client, target_date: str, daily_rows: List[Dict]) -> int:
    """Write daily counterfactual HR rows. MERGE per filter for re-run safety."""
    table_ref = f'{PROJECT_ID}.mlb_predictions.filter_counterfactual_daily'
    now = datetime.now(timezone.utc).isoformat()

    if not daily_rows:
        return 0

    written = 0
    for r in daily_rows:
        merge_query = f"""
        MERGE `{table_ref}` T
        USING (SELECT @game_date AS game_date, @filter_name AS filter_name) S
        ON T.game_date = S.game_date AND T.filter_name = S.filter_name
        WHEN MATCHED THEN UPDATE SET
            blocked_count = @blocked_count,
            wins = @wins,
            losses = @losses,
            pushes = @pushes,
            counterfactual_hr = @cf_hr,
            computed_at = @computed_at
        WHEN NOT MATCHED THEN INSERT
            (game_date, filter_name, blocked_count, wins, losses, pushes, counterfactual_hr, computed_at)
        VALUES (@game_date, @filter_name, @blocked_count, @wins, @losses, @pushes, @cf_hr, @computed_at)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('game_date', 'DATE', target_date),
                bigquery.ScalarQueryParameter('filter_name', 'STRING', r['filter_name']),
                bigquery.ScalarQueryParameter('blocked_count', 'INT64', r['blocked_count']),
                bigquery.ScalarQueryParameter('wins', 'INT64', r['wins']),
                bigquery.ScalarQueryParameter('losses', 'INT64', r['losses']),
                bigquery.ScalarQueryParameter('pushes', 'INT64', r['pushes']),
                bigquery.ScalarQueryParameter('cf_hr', 'FLOAT64', r['counterfactual_hr']),
                bigquery.ScalarQueryParameter('computed_at', 'TIMESTAMP', now),
            ]
        )
        try:
            bq.query(merge_query, job_config=job_config).result(timeout=30)
            written += 1
        except Exception as e:
            logger.warning(f"MERGE failed for {r['filter_name']}: {e}")

    return written


def find_trending_bad_filters(bq: bigquery.Client, target_date: str) -> List[Dict]:
    """Identify filters trending bad (CF HR >= threshold over 7d, N >= MIN_PICKS_7D).

    In Phase 1 this just produces advisory Slack warnings — nothing is
    auto-demoted. The query is the same as the NBA auto-demote query so
    we'll have direct parity when Phase 2 enables eligibility.
    """
    query = f"""
    WITH daily AS (
      SELECT
        filter_name,
        game_date,
        blocked_count,
        wins,
        losses,
        counterfactual_hr,
        ROW_NUMBER() OVER (PARTITION BY filter_name ORDER BY game_date) AS rn
      FROM `{PROJECT_ID}.mlb_predictions.filter_counterfactual_daily`
      WHERE game_date BETWEEN DATE_SUB(@target_date, INTERVAL 9 DAY) AND @target_date
    ),
    streak_groups AS (
      SELECT
        filter_name,
        game_date,
        wins,
        losses,
        counterfactual_hr,
        DATE_SUB(game_date, INTERVAL CAST(rn AS INT64) DAY) AS grp
      FROM daily
      WHERE counterfactual_hr >= {CF_HR_THRESHOLD}
    ),
    streak_sizes AS (
      SELECT
        filter_name,
        grp,
        COUNT(*) AS streak_len
      FROM streak_groups
      GROUP BY filter_name, grp
    ),
    rolling AS (
      SELECT
        filter_name,
        COUNT(DISTINCT game_date) AS days_with_data,
        SUM(wins + losses) AS total_graded,
        SUM(wins) AS total_wins,
        ROUND(100.0 * SUM(wins) / NULLIF(SUM(wins + losses), 0), 1) AS hr_7d,
        MIN(counterfactual_hr) AS min_daily_hr
      FROM daily
      GROUP BY filter_name
    )
    SELECT
      filter_name,
      days_with_data,
      total_graded,
      total_wins,
      hr_7d,
      min_daily_hr
    FROM rolling
    WHERE days_with_data >= {CONSECUTIVE_DAYS}
      AND total_graded >= {MIN_PICKS_7D}
      AND (
        SELECT MAX(streak_len)
        FROM streak_sizes
        WHERE filter_name = rolling.filter_name
      ) >= {CONSECUTIVE_DAYS}
      AND hr_7d >= {CF_HR_THRESHOLD}
    ORDER BY hr_7d DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )
    rows = list(bq.query(query, job_config=job_config).result(timeout=60))
    return [dict(row) for row in rows]


def get_already_demoted(bq: bigquery.Client) -> Set[str]:
    query = f"""
    SELECT filter_name
    FROM `{PROJECT_ID}.mlb_predictions.filter_overrides`
    WHERE active = TRUE
    """
    rows = list(bq.query(query).result(timeout=30))
    return {row.filter_name for row in rows}


def apply_demotion(bq: bigquery.Client, filter_name: str, cf_hr: float,
                   n_graded: int, reason: str) -> None:
    """Write a demotion record. Only called for filters in ELIGIBLE_FOR_AUTO_DEMOTE."""
    table_ref = f'{PROJECT_ID}.mlb_predictions.filter_overrides'
    now = datetime.now(timezone.utc).isoformat()

    merge_query = f"""
    MERGE `{table_ref}` T
    USING (SELECT @filter_name AS filter_name) S
    ON T.filter_name = S.filter_name AND T.active = TRUE
    WHEN MATCHED THEN UPDATE SET
        cf_hr_7d = @cf_hr,
        n_7d = @n_graded,
        reason = @reason,
        triggered_at = @triggered_at,
        triggered_by = 'auto_demote'
    WHEN NOT MATCHED THEN INSERT
        (filter_name, override_type, reason, cf_hr_7d, n_7d, triggered_at, triggered_by, active, demote_start_date, re_eval_date)
    VALUES (@filter_name, 'demote_to_observation', @reason, @cf_hr, @n_graded, @triggered_at, 'auto_demote', TRUE, CURRENT_DATE(), DATE_ADD(CURRENT_DATE(), INTERVAL 14 DAY))
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('filter_name', 'STRING', filter_name),
            bigquery.ScalarQueryParameter('cf_hr', 'FLOAT64', cf_hr),
            bigquery.ScalarQueryParameter('n_graded', 'INT64', n_graded),
            bigquery.ScalarQueryParameter('reason', 'STRING', reason),
            bigquery.ScalarQueryParameter('triggered_at', 'TIMESTAMP', now),
        ]
    )
    bq.query(merge_query, job_config=job_config).result(timeout=30)
    logger.info(f"Demotion applied: {filter_name} (CF HR={cf_hr}%, N={n_graded})")


def find_latest_graded_date(bq: bigquery.Client) -> Optional[str]:
    """Most recent game_date with graded MLB picks in prediction_accuracy."""
    query = f"""
    SELECT MAX(game_date) AS latest_date
    FROM `{PROJECT_ID}.mlb_predictions.prediction_accuracy`
    WHERE prediction_correct IS NOT NULL
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
    """
    rows = list(bq.query(query).result(timeout=30))
    if rows and rows[0].latest_date:
        return str(rows[0].latest_date)
    return None


def check_reactivation(bq: bigquery.Client, target_date: str) -> int:
    """Reactivate filters where re_eval_date has passed AND last 3-day CF HR < 50%."""
    due_query = f"""
    SELECT filter_name
    FROM `{PROJECT_ID}.mlb_predictions.filter_overrides`
    WHERE active = TRUE
      AND re_eval_date IS NOT NULL
      AND re_eval_date <= @target_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter('target_date', 'DATE', target_date)]
    )
    try:
        due_rows = list(bq.query(due_query, job_config=job_config).result(timeout=30))
    except Exception as e:
        logger.warning(f"check_reactivation: due query failed: {e}")
        return 0

    reactivated = 0
    for row in due_rows:
        filter_name = row.filter_name
        hr_query = f"""
        SELECT ROUND(100.0 * SUM(wins) / NULLIF(SUM(wins + losses), 0), 1) AS hr_3d
        FROM `{PROJECT_ID}.mlb_predictions.filter_counterfactual_daily`
        WHERE filter_name = @filter_name
          AND game_date BETWEEN DATE_SUB(@target_date, INTERVAL 2 DAY) AND @target_date
        """
        hr_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('filter_name', 'STRING', filter_name),
                bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            ]
        )
        try:
            hr_rows = list(bq.query(hr_query, job_config=hr_config).result(timeout=30))
            hr_3d = hr_rows[0].hr_3d if hr_rows and hr_rows[0].hr_3d is not None else 100.0
        except Exception as e:
            logger.warning(f"check_reactivation: CF HR query failed for {filter_name}: {e}")
            continue

        if hr_3d < 50.0:
            reactivate_query = f"""
            UPDATE `{PROJECT_ID}.mlb_predictions.filter_overrides`
            SET active = FALSE
            WHERE filter_name = @filter_name AND active = TRUE
            """
            try:
                bq.query(reactivate_query, job_config=bigquery.QueryJobConfig(
                    query_parameters=[bigquery.ScalarQueryParameter('filter_name', 'STRING', filter_name)]
                )).result(timeout=30)
                logger.info(f"Reactivated filter '{filter_name}': re_eval_date passed, 3d CF HR={hr_3d}% < 50%")
                reactivated += 1
            except Exception as e:
                logger.warning(f"check_reactivation: reactivate UPDATE failed for {filter_name}: {e}")

    return reactivated


@functions_framework.http
def main(request: Request):
    """HTTP entry point for Cloud Scheduler."""
    logger.info("MLB filter counterfactual evaluator starting (Phase 1: data collection)")

    bq = _get_bq_client()

    target_date = find_latest_graded_date(bq)
    if not target_date:
        logger.info("No graded MLB picks found in last 3 days, skipping")
        return 'No graded data', 200

    logger.info(f"Evaluating filters for game_date={target_date}")

    if ELIGIBLE_FOR_AUTO_DEMOTE:
        try:
            reactivated = check_reactivation(bq, target_date)
            if reactivated > 0:
                logger.info(f"Reactivated {reactivated} filter(s) after re-evaluation")
        except Exception as e:
            logger.warning(f"check_reactivation failed (non-blocking): {e}")

    # Step 1: Compute today's CF HR per filter
    daily_rows = compute_daily_cf_hr(bq, target_date)
    if not daily_rows:
        logger.info(f"No graded blocked picks for {target_date}")
        return 'No filtered picks', 200

    # Step 2: Write to filter_counterfactual_daily
    written = write_daily_cf_hr(bq, target_date, daily_rows)
    logger.info(f"Wrote {written} filter CF HR rows for {target_date}")

    for r in daily_rows:
        logger.info(
            f"  {r['filter_name']}: CF HR {r['counterfactual_hr']}% "
            f"({r['wins']}/{r['wins'] + r['losses']}) blocked={r['blocked_count']}"
        )

    # Step 3: Identify filters trending bad (advisory only in Phase 1)
    trending_bad = find_trending_bad_filters(bq, target_date)

    if not trending_bad:
        logger.info("No filters trending bad over 7d window")
        return json.dumps({'status': 'ok', 'date': target_date, 'demoted': [], 'warnings': []}), 200

    # In Phase 1, send Slack advisory and stop. Phase 2 will gate on
    # ELIGIBLE_FOR_AUTO_DEMOTE + NEVER_DEMOTE and call apply_demotion.
    warning_names = [c['filter_name'] for c in trending_bad]
    logger.warning(
        f"PHASE 1 ADVISORY: {len(trending_bad)} filter(s) trending bad: {warning_names}. "
        f"Auto-demote is disabled until ELIGIBLE_FOR_AUTO_DEMOTE is populated."
    )

    slack_lines = [
        f":bell: *MLB Filter CF Advisory* (Phase 1 — auto-demote disabled)",
        f"Date: {target_date}",
        "",
    ]
    for c in trending_bad:
        slack_lines.append(
            f"  `{c['filter_name']}` — 7d CF HR {c['hr_7d']}% "
            f"({c['total_wins']}/{c['total_graded']}); {c['days_with_data']} days of data"
        )
    slack_lines.append("")
    slack_lines.append(
        "These filters' blocked picks would have won at this rate. "
        "Review and add to ELIGIBLE_FOR_AUTO_DEMOTE in main.py if you want auto-demote."
    )
    _send_slack('\n'.join(slack_lines))

    return json.dumps({
        'status': 'phase1_advisory',
        'date': target_date,
        'demoted': [],
        'warnings': warning_names,
    }), 200
