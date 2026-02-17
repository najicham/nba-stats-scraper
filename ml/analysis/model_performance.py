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

# Fallback active models — used only if model_registry query fails
_FALLBACK_ACTIVE_MODELS = [
    'catboost_v9',
    'catboost_v12',
    'catboost_v9_q43',
    'catboost_v9_q45',
]

_FALLBACK_TRAINING_END_DATES = {
    'catboost_v9': date(2026, 1, 8),
    'catboost_v12': date(2026, 1, 31),
    'catboost_v9_q43': date(2026, 1, 31),
    'catboost_v9_q45': date(2026, 1, 31),
}


def get_active_models_from_registry(bq_client: bigquery.Client) -> tuple:
    """Load active models and training end dates from model_registry.

    Returns:
        (active_model_ids: list[str], training_end_dates: dict[str, date])
    """
    try:
        query = """
        SELECT model_id, training_end_date
        FROM `nba-props-platform.nba_predictions.model_registry`
        WHERE enabled = TRUE AND status IN ('active', 'production')
        """
        results = list(bq_client.query(query).result())
        if not results:
            logger.warning("No enabled models in model_registry, using fallback")
            return _FALLBACK_ACTIVE_MODELS, _FALLBACK_TRAINING_END_DATES

        model_ids = [r.model_id for r in results]
        training_dates = {r.model_id: r.training_end_date for r in results}
        logger.info(f"Loaded {len(model_ids)} active models from model_registry")
        return model_ids, training_dates
    except Exception as e:
        logger.warning(f"Failed to query model_registry: {e}. Using fallback models.")
        return _FALLBACK_ACTIVE_MODELS, _FALLBACK_TRAINING_END_DATES

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
        active_models, training_end_dates = get_active_models_from_registry(bq_client)

    # Query rolling metrics for all models on this date
    query = """
    WITH daily_results AS (
      SELECT
        game_date,
        system_id AS model_id,
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
        SAFE_DIVIDE(COUNTIF(win = 1), COUNT(*)) * 100.0 AS rolling_hr_30d
      FROM daily_results
      GROUP BY model_id
    )
    SELECT * FROM model_date_stats
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
    """Write computed rows to model_performance_daily. Returns rows written."""
    if not rows:
        return 0

    errors = bq_client.insert_rows_json(TABLE_ID, rows)
    if errors:
        logger.error(f"BQ insert errors: {errors}")
        raise RuntimeError(f"Failed to write {len(rows)} rows: {errors}")

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

    # Load active models once for the entire backfill
    active_models, training_end_dates = get_active_models_from_registry(bq_client)

    total_rows = 0
    prev_states: Dict[str, dict] = {}

    for d in dates:
        rows = compute_for_date(bq_client, d, prev_day_states=prev_states,
                               active_models=active_models,
                               training_end_dates=training_end_dates)
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
            print(f"  {r['model_id']}: {r['rolling_hr_7d']}% HR 7d "
                  f"(N={r['rolling_n_7d']}), state={r['state']}")
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
