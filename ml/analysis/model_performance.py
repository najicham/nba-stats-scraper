"""Compute daily model performance metrics for model_performance_daily table.

Queries prediction_accuracy for rolling hit rates and daily stats per model,
determines decay state, and writes results to BigQuery.

Usage:
    # Backfill
    PYTHONPATH=. python ml/analysis/model_performance.py --backfill --start 2025-11-02

    # Single date (used by Cloud Function)
    PYTHONPATH=. python ml/analysis/model_performance.py --date 2026-02-12

Created: 2026-02-15 (Session 262)
"""

import argparse
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Decay state thresholds
WATCH_THRESHOLD = 58.0
ALERT_THRESHOLD = 55.0
BLOCK_THRESHOLD = 52.4

# Fallback active models — used only if discovery query fails
_FALLBACK_ACTIVE_MODELS = [
    'catboost_v9',
    'catboost_v12',
    'catboost_v9_q43_train1102_0131',
    'catboost_v9_q45_train1102_0131',
]

_FALLBACK_TRAINING_END_DATES = {
    'catboost_v9': date(2026, 2, 5),
    'catboost_v12': date(2026, 2, 5),
    'catboost_v9_q43_train1102_0131': date(2026, 1, 31),
    'catboost_v9_q45_train1102_0131': date(2026, 1, 31),
}


def discover_active_models(bq_client: bigquery.Client,
                           ref_date: date) -> tuple:
    """Discover active models from prediction_accuracy grading data.

    Two-step approach:
      1. Find runtime system_ids that have graded predictions near ref_date
      2. Map training_end_date from model_registry via family classification

    Args:
        bq_client: BigQuery client.
        ref_date: Reference date — discover models active around this date.

    Returns:
        (active_model_ids: list[str], training_end_dates: dict[str, date])
    """
    from shared.config.cross_model_subsets import (
        build_system_id_sql_filter,
        classify_system_id,
    )

    # Step A: Discover runtime system_ids from prediction_accuracy
    sql_filter = build_system_id_sql_filter()
    discovery_query = f"""
    SELECT DISTINCT system_id
    FROM `nba-props-platform.nba_predictions.prediction_accuracy`
    WHERE game_date BETWEEN DATE_SUB(@ref_date, INTERVAL 30 DAY) AND @ref_date
      AND {sql_filter}
      AND prediction_correct IS NOT NULL
    """
    try:
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('ref_date', 'DATE', ref_date),
            ]
        )
        rows = list(bq_client.query(discovery_query, job_config=job_config).result())
        model_ids = [r.system_id for r in rows]
    except Exception as e:
        logger.warning(f"Discovery query failed: {e}. Using fallback models.")
        return _FALLBACK_ACTIVE_MODELS, dict(_FALLBACK_TRAINING_END_DATES)

    if not model_ids:
        logger.warning(f"No models found in prediction_accuracy near {ref_date}, using fallback")
        return _FALLBACK_ACTIVE_MODELS, dict(_FALLBACK_TRAINING_END_DATES)

    logger.info(f"Discovered {len(model_ids)} runtime models from prediction_accuracy: {sorted(model_ids)}")

    # Step B: Map training_end_date from registry via family classification
    training_end_dates = _map_training_dates_from_registry(bq_client, model_ids)

    return model_ids, training_end_dates


def _map_training_dates_from_registry(bq_client: bigquery.Client,
                                      runtime_ids: List[str]) -> Dict[str, date]:
    """Map runtime system_ids to training_end_date via family classification.

    Queries model_registry for all entries with training_end_date, classifies
    each into a family, builds family -> most_recent_training_end_date, then
    maps each runtime ID to its family's training date.
    """
    from shared.config.cross_model_subsets import classify_system_id

    training_dates: Dict[str, date] = {}

    try:
        query = """
        SELECT model_id, training_end_date
        FROM `nba-props-platform.nba_predictions.model_registry`
        WHERE training_end_date IS NOT NULL
        """
        rows = list(bq_client.query(query).result())

        # Build family -> most recent training_end_date
        family_dates: Dict[str, date] = {}
        for row in rows:
            family = classify_system_id(row.model_id)
            if family:
                existing = family_dates.get(family)
                if existing is None or row.training_end_date > existing:
                    family_dates[family] = row.training_end_date

        logger.info(f"Registry family training dates: {family_dates}")

        # Map each runtime system_id to its family's training date
        for sid in runtime_ids:
            family = classify_system_id(sid)
            if family and family in family_dates:
                training_dates[sid] = family_dates[family]
            else:
                logger.warning(f"No training_end_date for {sid} (family={family})")
    except Exception as e:
        logger.warning(f"Failed to query model_registry for training dates: {e}")

    return training_dates

TABLE_ID = 'nba-props-platform.nba_predictions.model_performance_daily'


def compute_for_date(bq_client: bigquery.Client, target_date: date,
                     prev_day_states: Optional[Dict] = None,
                     active_models: List[str] = None,
                     training_end_dates: Dict = None) -> List[dict]:
    """Compute model performance metrics for a single date.

    Args:
        bq_client: BigQuery client.
        target_date: Date to compute metrics for.
        prev_day_states: Previous day's state dict (model_id -> row dict)
            for consecutive-day tracking. If None, queries BQ for previous day.
        active_models: List of active model IDs. If None, loads from registry.
        training_end_dates: Dict of model_id -> training_end_date. If None, loads from registry.

    Returns:
        List of row dicts ready for BQ insert.
    """
    if active_models is None or training_end_dates is None:
        active_models, training_end_dates = discover_active_models(bq_client, target_date)

    # Query rolling metrics for all models on this date
    query = """
    WITH daily_results AS (
      SELECT
        game_date,
        system_id AS model_id,
        recommendation,
        CASE WHEN prediction_correct THEN 1 ELSE 0 END AS win
      FROM `nba-props-platform.nba_predictions.prediction_accuracy`
      WHERE game_date BETWEEN @window_start AND @target_date
        AND ABS(predicted_points - line_value) >= 3
        AND system_id IN UNNEST(@model_ids)
    ),
    model_date_stats AS (
      SELECT
        model_id,
        -- Daily stats for target_date
        COUNTIF(game_date = @target_date) AS daily_picks,
        COUNTIF(game_date = @target_date AND win = 1) AS daily_wins,
        COUNTIF(game_date = @target_date AND win = 0) AS daily_losses,
        -- 7d rolling
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)) AS rolling_n_7d,
        SAFE_DIVIDE(
          COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY) AND win = 1),
          COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY))
        ) * 100.0 AS rolling_hr_7d,
        -- 14d rolling
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY)) AS rolling_n_14d,
        SAFE_DIVIDE(
          COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND win = 1),
          COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY))
        ) * 100.0 AS rolling_hr_14d,
        -- 30d rolling
        COUNT(*) AS rolling_n_30d,
        SAFE_DIVIDE(COUNTIF(win = 1), COUNT(*)) * 100.0 AS rolling_hr_30d,
        -- Session 366: Directional HR splits (7d)
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY) AND recommendation = 'OVER') AS rolling_n_over_7d,
        SAFE_DIVIDE(
          COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY) AND recommendation = 'OVER' AND win = 1),
          NULLIF(COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY) AND recommendation = 'OVER'), 0)
        ) * 100.0 AS rolling_hr_over_7d,
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY) AND recommendation = 'UNDER') AS rolling_n_under_7d,
        SAFE_DIVIDE(
          COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY) AND recommendation = 'UNDER' AND win = 1),
          NULLIF(COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY) AND recommendation = 'UNDER'), 0)
        ) * 100.0 AS rolling_hr_under_7d,
        -- Session 366: Directional HR splits (14d)
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND recommendation = 'OVER') AS rolling_n_over_14d,
        SAFE_DIVIDE(
          COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND recommendation = 'OVER' AND win = 1),
          NULLIF(COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND recommendation = 'OVER'), 0)
        ) * 100.0 AS rolling_hr_over_14d,
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND recommendation = 'UNDER') AS rolling_n_under_14d,
        SAFE_DIVIDE(
          COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND recommendation = 'UNDER' AND win = 1),
          NULLIF(COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND recommendation = 'UNDER'), 0)
        ) * 100.0 AS rolling_hr_under_14d
      FROM daily_results
      GROUP BY model_id
    ),
    -- Session 366: Best-bets stats from signal_best_bets_picks
    best_bets_stats AS (
      SELECT
        bb.source_model_id AS model_id,
        -- 14d
        COUNTIF(bb.game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND pa.prediction_correct IS NOT NULL) AS bb_n_14d,
        SAFE_DIVIDE(
          COUNTIF(bb.game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND pa.prediction_correct = TRUE),
          NULLIF(COUNTIF(bb.game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND pa.prediction_correct IS NOT NULL), 0)
        ) * 100.0 AS bb_hr_14d,
        -- 21d
        COUNTIF(pa.prediction_correct IS NOT NULL) AS bb_n_21d,
        SAFE_DIVIDE(
          COUNTIF(pa.prediction_correct = TRUE),
          NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0)
        ) * 100.0 AS bb_hr_21d,
        -- Directional (21d)
        SAFE_DIVIDE(
          COUNTIF(bb.recommendation = 'OVER' AND pa.prediction_correct = TRUE),
          NULLIF(COUNTIF(bb.recommendation = 'OVER' AND pa.prediction_correct IS NOT NULL), 0)
        ) * 100.0 AS bb_over_hr_21d,
        SAFE_DIVIDE(
          COUNTIF(bb.recommendation = 'UNDER' AND pa.prediction_correct = TRUE),
          NULLIF(COUNTIF(bb.recommendation = 'UNDER' AND pa.prediction_correct IS NOT NULL), 0)
        ) * 100.0 AS bb_under_hr_21d,
        -- Filter pass rate
        SAFE_DIVIDE(
          COUNT(*),
          (SELECT COUNT(*) FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa2
           WHERE pa2.system_id = bb.source_model_id
             AND pa2.game_date BETWEEN DATE_SUB(@target_date, INTERVAL 21 DAY) AND @target_date
             AND ABS(pa2.predicted_points - pa2.line_value) >= 3)
        ) AS bb_filter_pass_rate
      FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` bb
      LEFT JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
        ON bb.player_lookup = pa.player_lookup
        AND bb.game_date = pa.game_date
        AND bb.system_id = pa.system_id
        AND pa.is_voided IS NOT TRUE
      WHERE bb.game_date BETWEEN DATE_SUB(@target_date, INTERVAL 21 DAY) AND @target_date
        AND bb.source_model_id IS NOT NULL
      GROUP BY bb.source_model_id
    )
    SELECT mds.*, bbs.bb_n_14d, bbs.bb_hr_14d, bbs.bb_n_21d, bbs.bb_hr_21d,
           bbs.bb_over_hr_21d, bbs.bb_under_hr_21d, bbs.bb_filter_pass_rate
    FROM model_date_stats mds
    LEFT JOIN best_bets_stats bbs ON bbs.model_id = mds.model_id
    """

    window_start = target_date - timedelta(days=30)
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('window_start', 'DATE', window_start),
            bigquery.ArrayQueryParameter('model_ids', 'STRING', active_models),
        ]
    )

    results = list(bq_client.query(query, job_config=job_config).result())

    # Get previous day states for consecutive-day tracking
    if prev_day_states is None:
        prev_day_states = _get_previous_day_states(bq_client, target_date)

    rows = []
    now = datetime.now(timezone.utc)

    for row in results:
        model_id = row.model_id
        hr_7d = row.rolling_hr_7d

        # Determine state
        if hr_7d is None or row.rolling_n_7d < 5:
            state = 'INSUFFICIENT_DATA'
        elif hr_7d < BLOCK_THRESHOLD:
            state = 'BLOCKED'
        elif hr_7d < ALERT_THRESHOLD:
            state = 'DEGRADING'
        elif hr_7d < WATCH_THRESHOLD:
            state = 'WATCH'
        else:
            state = 'HEALTHY'

        # Track consecutive days
        prev = prev_day_states.get(model_id, {})
        prev_watch = prev.get('consecutive_days_below_watch', 0)
        prev_alert = prev.get('consecutive_days_below_alert', 0)

        consec_watch = (prev_watch + 1) if (hr_7d is not None and hr_7d < WATCH_THRESHOLD) else 0
        consec_alert = (prev_alert + 1) if (hr_7d is not None and hr_7d < ALERT_THRESHOLD) else 0

        # Determine action
        prev_state = prev.get('state', 'HEALTHY')
        action = 'NO_CHANGE'
        action_reason = None
        if state != prev_state and prev_state:
            if state == 'BLOCKED':
                action = 'DEGRADED'
                action_reason = f'7d HR {hr_7d:.1f}% below breakeven ({BLOCK_THRESHOLD}%)'
            elif state == 'DEGRADING':
                action = 'DEGRADED'
                action_reason = f'7d HR {hr_7d:.1f}% below alert threshold ({ALERT_THRESHOLD}%)'
            elif state == 'WATCH':
                action = 'DEGRADED'
                action_reason = f'7d HR {hr_7d:.1f}% below watch threshold ({WATCH_THRESHOLD}%)'
            elif state == 'HEALTHY' and prev_state in ('WATCH', 'DEGRADING', 'BLOCKED'):
                action = 'RECOVERED'
                action_reason = f'7d HR {hr_7d:.1f}% recovered above {WATCH_THRESHOLD}%'

        # Days since training
        train_end = training_end_dates.get(model_id)
        days_since = (target_date - train_end).days if train_end else None

        daily_hr = None
        daily_roi = None
        if row.daily_picks and row.daily_picks > 0:
            daily_hr = round(100.0 * row.daily_wins / row.daily_picks, 1)
            daily_roi = round(100.0 * (row.daily_wins - row.daily_losses) / row.daily_picks, 1)

        rows.append({
            'game_date': target_date.isoformat(),
            'model_id': model_id,
            'rolling_hr_7d': round(hr_7d, 1) if hr_7d is not None else None,
            'rolling_hr_14d': round(row.rolling_hr_14d, 1) if row.rolling_hr_14d is not None else None,
            'rolling_hr_30d': round(row.rolling_hr_30d, 1) if row.rolling_hr_30d is not None else None,
            'rolling_n_7d': row.rolling_n_7d,
            'rolling_n_14d': row.rolling_n_14d,
            'rolling_n_30d': row.rolling_n_30d,
            # Session 366: Directional HR splits
            'rolling_hr_over_7d': round(row.rolling_hr_over_7d, 1) if row.rolling_hr_over_7d is not None else None,
            'rolling_hr_under_7d': round(row.rolling_hr_under_7d, 1) if row.rolling_hr_under_7d is not None else None,
            'rolling_n_over_7d': row.rolling_n_over_7d,
            'rolling_n_under_7d': row.rolling_n_under_7d,
            'rolling_hr_over_14d': round(row.rolling_hr_over_14d, 1) if row.rolling_hr_over_14d is not None else None,
            'rolling_hr_under_14d': round(row.rolling_hr_under_14d, 1) if row.rolling_hr_under_14d is not None else None,
            'rolling_n_over_14d': row.rolling_n_over_14d,
            'rolling_n_under_14d': row.rolling_n_under_14d,
            'daily_picks': row.daily_picks,
            'daily_wins': row.daily_wins,
            'daily_losses': row.daily_losses,
            'daily_hr': daily_hr,
            'daily_roi': daily_roi,
            'state': state,
            'consecutive_days_below_watch': consec_watch,
            'consecutive_days_below_alert': consec_alert,
            'action': action,
            'action_reason': action_reason,
            'days_since_training': days_since,
            # Session 366: Best-bets post-filter metrics
            'best_bets_hr_14d': round(row.bb_hr_14d, 1) if getattr(row, 'bb_hr_14d', None) is not None else None,
            'best_bets_hr_21d': round(row.bb_hr_21d, 1) if getattr(row, 'bb_hr_21d', None) is not None else None,
            'best_bets_n_14d': getattr(row, 'bb_n_14d', None),
            'best_bets_n_21d': getattr(row, 'bb_n_21d', None),
            'best_bets_over_hr_21d': round(row.bb_over_hr_21d, 1) if getattr(row, 'bb_over_hr_21d', None) is not None else None,
            'best_bets_under_hr_21d': round(row.bb_under_hr_21d, 1) if getattr(row, 'bb_under_hr_21d', None) is not None else None,
            'best_bets_filter_pass_rate': round(row.bb_filter_pass_rate, 3) if getattr(row, 'bb_filter_pass_rate', None) is not None else None,
            'computed_at': now.isoformat(),
        })

    return rows


def _get_previous_day_states(bq_client: bigquery.Client,
                             target_date: date) -> Dict[str, dict]:
    """Fetch previous day's state for consecutive-day tracking."""
    query = """
    SELECT model_id, state, consecutive_days_below_watch, consecutive_days_below_alert
    FROM `nba-props-platform.nba_predictions.model_performance_daily`
    WHERE game_date = @prev_date
    """
    prev_date = target_date - timedelta(days=1)
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('prev_date', 'DATE', prev_date),
        ]
    )
    try:
        rows = list(bq_client.query(query, job_config=job_config).result())
        return {r.model_id: dict(r) for r in rows}
    except Exception:
        return {}


def write_rows(bq_client: bigquery.Client, rows: List[dict]) -> int:
    """Write computed rows to model_performance_daily. Returns rows written.

    Uses DELETE-before-write to prevent duplicate rows when re-run on the same date.
    """
    if not rows:
        return 0

    # Extract target date from first row (all rows share the same game_date)
    target_date = rows[0]['game_date']

    # Delete existing rows for this date before writing
    delete_query = f"""
    DELETE FROM `{TABLE_ID}`
    WHERE game_date = @target_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )
    delete_job = bq_client.query(delete_query, job_config=job_config)
    delete_result = delete_job.result(timeout=60)
    deleted = delete_job.num_dml_affected_rows or 0
    if deleted > 0:
        logger.info(f"Deleted {deleted} existing rows for {target_date}")

    # Write new rows using batch load (not streaming insert)
    load_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
    )
    load_job = bq_client.load_table_from_json(rows, TABLE_ID, job_config=load_config)
    load_job.result(timeout=60)

    logger.info(f"Wrote {len(rows)} rows to model_performance_daily")
    return len(rows)


def backfill(bq_client: bigquery.Client, start_date: date,
             end_date: Optional[date] = None) -> int:
    """Backfill model_performance_daily from start_date to end_date.

    Processes dates sequentially so consecutive-day tracking is accurate.
    """
    if end_date is None:
        end_date = date.today() - timedelta(days=1)

    # Find dates that actually have graded predictions
    query = """
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_predictions.prediction_accuracy`
    WHERE game_date BETWEEN @start AND @end
      AND ABS(predicted_points - line_value) >= 3
    ORDER BY game_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('start', 'DATE', start_date),
            bigquery.ScalarQueryParameter('end', 'DATE', end_date),
        ]
    )
    dates = [row.game_date for row in bq_client.query(query, job_config=job_config).result()]

    if not dates:
        logger.warning(f"No graded predictions found between {start_date} and {end_date}")
        return 0

    logger.info(f"Backfilling {len(dates)} dates from {dates[0]} to {dates[-1]}")

    # Discover models per-date so backfill picks up the right models for each day.
    # Training dates change less often, so we cache the registry mapping.
    total_rows = 0
    prev_states: Dict[str, dict] = {}
    cached_training_dates: Optional[Dict] = None

    for d in dates:
        active_models, training_end_dates = discover_active_models(bq_client, d)
        if cached_training_dates is None:
            cached_training_dates = training_end_dates
        else:
            # Merge any new training date mappings
            cached_training_dates.update(training_end_dates)
        rows = compute_for_date(bq_client, d, prev_day_states=prev_states,
                               active_models=active_models,
                               training_end_dates=cached_training_dates)
        if rows:
            write_rows(bq_client, rows)
            total_rows += len(rows)
            # Update prev_states for next iteration
            prev_states = {r['model_id']: r for r in rows}

    logger.info(f"Backfill complete: {total_rows} rows across {len(dates)} dates")
    return total_rows


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description='Compute model performance daily metrics')
    parser.add_argument('--date', type=str, help='Single date to compute (YYYY-MM-DD)')
    parser.add_argument('--backfill', action='store_true', help='Backfill historical data')
    parser.add_argument('--start', type=str, default='2025-11-02',
                        help='Backfill start date (default: 2025-11-02)')
    parser.add_argument('--end', type=str, help='Backfill end date (default: yesterday)')
    args = parser.parse_args()

    bq_client = bigquery.Client(project='nba-props-platform')

    if args.backfill:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end) if args.end else None
        total = backfill(bq_client, start, end)
        print(f"Backfill complete: {total} rows written")
    elif args.date:
        target = date.fromisoformat(args.date)
        rows = compute_for_date(bq_client, target)
        written = write_rows(bq_client, rows)
        print(f"Computed {written} rows for {target}")
        for r in rows:
            over_str = f"OVER {r['rolling_hr_over_7d']}% N={r['rolling_n_over_7d']}" if r.get('rolling_hr_over_7d') is not None else ""
            under_str = f"UNDER {r['rolling_hr_under_7d']}% N={r['rolling_n_under_7d']}" if r.get('rolling_hr_under_7d') is not None else ""
            bb_str = f"BB {r['best_bets_hr_21d']}% N={r['best_bets_n_21d']}" if r.get('best_bets_hr_21d') is not None else ""
            print(f"  {r['model_id']}: {r['rolling_hr_7d']}% HR 7d "
                  f"(N={r['rolling_n_7d']}), state={r['state']}"
                  f"  {over_str}  {under_str}  {bb_str}")
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
