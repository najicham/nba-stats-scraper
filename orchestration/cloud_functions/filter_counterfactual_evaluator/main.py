"""Filter Counterfactual Evaluator Cloud Function.

Computes daily counterfactual hit rate for each active negative filter by
analyzing graded picks in best_bets_filtered_picks. When a filter's CF HR
>= 55% at N >= 20 for 7 consecutive days, it auto-demotes the filter to
observation-only via the filter_overrides table and sends a Slack alert.

Triggered by Cloud Scheduler at 11:30 AM ET daily (after post_grading_export
has backfilled actuals into best_bets_filtered_picks).

Created: Session 432
"""

import functions_framework
import json
import logging
import os
import requests
from datetime import datetime, timezone
from flask import Request
from google.cloud import bigquery
from typing import Dict, List, Optional, Set, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL_ALERTS') or os.environ.get('SLACK_WEBHOOK_URL_WARNING')

# Filters eligible for auto-demotion. Core safety filters are excluded.
ELIGIBLE_FOR_AUTO_DEMOTE = {
    'med_usage_under',
    'b2b_under_block',
    'line_dropped_under',
    'opponent_under_block',
    'opponent_depleted_under',
    'q4_scorer_under_block',
    'friday_over_block',
    'high_skew_over_block',
    'high_book_std_under',
    'under_after_streak',
    'under_after_bad_miss',
    'familiar_matchup',
    'model_direction_affinity',
}

# Core safety filters — NEVER auto-demote
NEVER_DEMOTE = {
    'blacklist', 'edge_floor', 'over_edge_floor', 'under_edge_7plus',
    'quality_floor', 'signal_count', 'sc3_over_block', 'signal_density',
    'starter_over_sc_floor', 'confidence', 'rescue_cap',
}

# Auto-demote thresholds
CF_HR_THRESHOLD = 55.0       # Filter's blocked picks win >= 55% = filter hurts
MIN_PICKS_PER_DAY = 0        # No per-day minimum (daily can be sparse)
MIN_PICKS_7D = 20            # Need 20+ graded picks over 7 days
CONSECUTIVE_DAYS = 7         # Must exceed threshold for 7 consecutive days
MAX_DEMOTIONS_PER_RUN = 2    # Safety: max 2 filters demoted per run

_bq_client = None


def _get_bq_client():
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


def _send_slack(message: str) -> None:
    """Send a Slack alert. Non-fatal if it fails."""
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

    Queries best_bets_filtered_picks (which has actuals filled by post_grading_export)
    and groups by filter_reason.
    """
    query = f"""
    SELECT
      filter_reason AS filter_name,
      COUNT(*) AS blocked_count,
      COUNTIF(prediction_correct = TRUE) AS wins,
      COUNTIF(prediction_correct = FALSE) AS losses,
      COUNTIF(prediction_correct IS NULL) AS pushes,
      ROUND(
        100.0 * COUNTIF(prediction_correct = TRUE)
        / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0),
        1
      ) AS counterfactual_hr
    FROM `{PROJECT_ID}.nba_predictions.best_bets_filtered_picks`
    WHERE game_date = @target_date
      AND prediction_correct IS NOT NULL
    GROUP BY filter_reason
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
    """Write daily counterfactual HR rows to filter_counterfactual_daily.

    Uses MERGE per filter for re-run safety (avoids streaming buffer conflicts).
    """
    table_ref = f'{PROJECT_ID}.nba_predictions.filter_counterfactual_daily'
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


def check_auto_demote(bq: bigquery.Client, target_date: str) -> List[Dict]:
    """Check which eligible filters meet the 7-day consecutive auto-demote criteria.

    Criteria: CF HR >= 55% AND cumulative N >= 20 for 7 consecutive days.
    Uses a 10-day window to ensure enough game days are captured (Mon-Sun may
    only have 5-7 game days in a calendar week).
    Returns list of filters that should be demoted.
    """
    # Query the last 10 days of filter_counterfactual_daily for eligible filters
    eligible_list = ', '.join(f"'{f}'" for f in ELIGIBLE_FOR_AUTO_DEMOTE)

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
      FROM `{PROJECT_ID}.nba_predictions.filter_counterfactual_daily`
      WHERE game_date BETWEEN DATE_SUB(@target_date, INTERVAL 9 DAY) AND @target_date
        AND filter_name IN ({eligible_list})
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
    """Get set of filters already demoted via filter_overrides."""
    query = f"""
    SELECT filter_name
    FROM `{PROJECT_ID}.nba_predictions.filter_overrides`
    WHERE active = TRUE
    """
    rows = list(bq.query(query).result(timeout=30))
    return {row.filter_name for row in rows}


def apply_demotion(bq: bigquery.Client, filter_name: str, cf_hr: float,
                   n_graded: int, reason: str) -> None:
    """Write a demotion record to filter_overrides."""
    table_ref = f'{PROJECT_ID}.nba_predictions.filter_overrides'
    now = datetime.now(timezone.utc).isoformat()

    # MERGE: update if exists, insert if not
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


def log_to_service_errors(bq: bigquery.Client, filter_name: str,
                          cf_hr: float, n_graded: int) -> None:
    """Log demotion decision to service_errors for audit trail."""
    import hashlib
    table_ref = f'{PROJECT_ID}.nba_orchestration.service_errors'
    now = datetime.now(timezone.utc).isoformat()
    msg = f"Auto-demoted filter '{filter_name}': CF HR {cf_hr}% (N={n_graded}) for 7 consecutive days"
    error_id = hashlib.md5(
        f"filter_counterfactual_evaluator:auto_demote:{filter_name}:{now[:16]}".encode()
    ).hexdigest()

    row = {
        'error_id': error_id,
        'service_name': 'filter_counterfactual_evaluator',
        'error_timestamp': now,
        'error_type': 'FilterAutoDemote',
        'error_category': 'configuration_change',
        'severity': 'warning',
        'error_message': msg,
        'stack_trace': None,
        'game_date': None,
        'processor_name': None,
        'phase': 'monitoring',
        'correlation_id': None,
        'recovery_attempted': True,
        'recovery_successful': True,
    }
    try:
        errors = bq.insert_rows_json(table_ref, [row])
        if errors:
            logger.warning(f"service_errors write failed: {errors[:1]}")
    except Exception as e:
        logger.warning(f"Failed to log to service_errors: {e}")


def find_latest_graded_date(bq: bigquery.Client) -> Optional[str]:
    """Find the most recent game_date with graded filtered picks."""
    query = f"""
    SELECT MAX(game_date) AS latest_date
    FROM `{PROJECT_ID}.nba_predictions.best_bets_filtered_picks`
    WHERE prediction_correct IS NOT NULL
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
    """
    rows = list(bq.query(query).result(timeout=30))
    if rows and rows[0].latest_date:
        return str(rows[0].latest_date)
    return None


def check_reactivation(bq: bigquery.Client, target_date: str) -> int:
    """Reactivate filters where re_eval_date has passed AND last 3-day CF HR < 50%.

    Returns number of filters reactivated.
    Called at start of main() before daily CF computation.
    Wrapped in try/except — never blocks normal CF evaluation.
    """
    due_query = f"""
    SELECT filter_name
    FROM `{PROJECT_ID}.nba_predictions.filter_overrides`
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
        # Check last 3 days CF HR
        hr_query = f"""
        SELECT ROUND(100.0 * SUM(wins) / NULLIF(SUM(wins + losses), 0), 1) AS hr_3d
        FROM `{PROJECT_ID}.nba_predictions.filter_counterfactual_daily`
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
            # Reactivate: set active = FALSE
            reactivate_query = f"""
            UPDATE `{PROJECT_ID}.nba_predictions.filter_overrides`
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
    logger.info("Filter counterfactual evaluator starting")

    bq = _get_bq_client()

    # Step 1: Find the latest graded game date
    target_date = find_latest_graded_date(bq)

    # Re-evaluate demoted filters whose re_eval_date has passed
    if target_date:
        try:
            reactivated = check_reactivation(bq, target_date)
            if reactivated > 0:
                logger.info(f"Reactivated {reactivated} filter(s) after re-evaluation")
        except Exception as e:
            logger.warning(f"check_reactivation failed (non-blocking): {e}")
    if not target_date:
        logger.info("No graded filtered picks found in last 3 days, skipping")
        return 'No graded data', 200

    logger.info(f"Evaluating filters for game_date={target_date}")

    # Step 2: Compute daily CF HR per filter
    daily_rows = compute_daily_cf_hr(bq, target_date)
    if not daily_rows:
        logger.info(f"No graded filtered picks for {target_date}")
        return 'No filtered picks', 200

    # Step 3: Write to filter_counterfactual_daily
    written = write_daily_cf_hr(bq, target_date, daily_rows)
    logger.info(f"Wrote {written} filter CF HR rows for {target_date}")

    # Log summary
    for r in daily_rows:
        if r['filter_name'] in ELIGIBLE_FOR_AUTO_DEMOTE:
            logger.info(
                f"  {r['filter_name']}: CF HR {r['counterfactual_hr']}% "
                f"({r['wins']}/{r['wins'] + r['losses']}) blocked={r['blocked_count']}"
            )

    # Step 4: Check 7-day auto-demote criteria
    candidates = check_auto_demote(bq, target_date)
    if not candidates:
        logger.info("No filters meet auto-demote criteria")
        return json.dumps({'status': 'ok', 'date': target_date, 'demoted': []}), 200

    # Step 5: Filter out already-demoted filters
    already_demoted = get_already_demoted(bq)
    new_demotions = [c for c in candidates if c['filter_name'] not in already_demoted]

    if not new_demotions:
        logger.info(f"All {len(candidates)} candidates already demoted")
        return json.dumps({'status': 'ok', 'date': target_date, 'demoted': []}), 200

    # Safety: max 2 demotions per run
    if len(new_demotions) > MAX_DEMOTIONS_PER_RUN:
        logger.warning(
            f"{len(new_demotions)} filters qualify for demotion, capping at {MAX_DEMOTIONS_PER_RUN}. "
            f"Skipped: {[c['filter_name'] for c in new_demotions[MAX_DEMOTIONS_PER_RUN:]]}"
        )
        new_demotions = new_demotions[:MAX_DEMOTIONS_PER_RUN]

    # Step 6: Apply demotions + Slack alert
    demoted_names = []
    for candidate in new_demotions:
        fname = candidate['filter_name']
        cf_hr = candidate['hr_7d']
        n_graded = candidate['total_graded']
        reason = (
            f"7-day CF HR {cf_hr}% (N={n_graded}) >= {CF_HR_THRESHOLD}% threshold. "
            f"Filter was blocking profitable picks for {CONSECUTIVE_DAYS} consecutive days."
        )

        apply_demotion(bq, fname, cf_hr, n_graded, reason)
        log_to_service_errors(bq, fname, cf_hr, n_graded)
        demoted_names.append(fname)

        logger.info(f"AUTO-DEMOTED: {fname} — CF HR {cf_hr}% (N={n_graded})")

    # Slack notification
    slack_lines = [
        f":warning: *Filter Auto-Demotion Alert*",
        f"Date: {target_date}",
        "",
    ]
    for candidate in new_demotions:
        fname = candidate['filter_name']
        cf_hr = candidate['hr_7d']
        n_graded = candidate['total_graded']
        wins = candidate['total_wins']
        slack_lines.append(
            f"  `{fname}` demoted to observation — "
            f"CF HR {cf_hr}% ({wins}/{n_graded}) for {CONSECUTIVE_DAYS}d"
        )
    slack_lines.append("")
    slack_lines.append(
        "Blocked picks were winning at this rate. "
        "Filter will be skipped in tomorrow's export. "
        "Review: `SELECT * FROM nba_predictions.filter_overrides WHERE active = TRUE`"
    )
    _send_slack('\n'.join(slack_lines))

    result = {
        'status': 'demoted',
        'date': target_date,
        'demoted': demoted_names,
    }
    return json.dumps(result), 200
