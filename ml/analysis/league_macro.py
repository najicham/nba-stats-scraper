"""Compute daily league macro trends for league_macro_daily table.

Tracks market efficiency (Vegas MAE), scoring environment, edge availability,
and best bets rolling performance. Single row per game_date.

Usage:
    # Backfill
    PYTHONPATH=. python ml/analysis/league_macro.py --backfill --start 2026-02-01

    # Single date (used by Cloud Function)
    PYTHONPATH=. python ml/analysis/league_macro.py --date 2026-03-07

Created: 2026-03-08 (Session 435)
"""

import argparse
import decimal
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from google.cloud import bigquery

logger = logging.getLogger(__name__)

TABLE_ID = 'nba-props-platform.nba_predictions.league_macro_daily'

# Market regime thresholds (based on Vegas MAE 7d)
TIGHT_THRESHOLD = 4.5    # Vegas very accurate = hard to beat
LOOSE_THRESHOLD = 5.5    # Vegas less accurate = more opportunity


def compute_for_date(bq_client: bigquery.Client, target_date: date) -> Optional[dict]:
    """Compute league macro metrics for a single date.

    Returns a single dict row, or None if no data for this date.
    """
    row = {}
    row['game_date'] = target_date.isoformat()

    # --- 1. Vegas/Model MAE + Edge metrics (from prediction_accuracy) ---
    mae_data = _compute_mae_metrics(bq_client, target_date)
    if mae_data is None:
        logger.info(f"No graded predictions for {target_date}, skipping")
        return None
    row.update(mae_data)

    # --- 2. League scoring environment (from player_game_summary) ---
    scoring_data = _compute_scoring_metrics(bq_client, target_date)
    row.update(scoring_data)

    # --- 3. Best bets rolling performance ---
    bb_data = _compute_bb_metrics(bq_client, target_date)
    row.update(bb_data)

    # --- 4. Market regime classification ---
    vegas_mae_7d = row.get('vegas_mae_7d')
    if vegas_mae_7d is not None:
        if vegas_mae_7d < TIGHT_THRESHOLD:
            row['market_regime'] = 'TIGHT'
        elif vegas_mae_7d > LOOSE_THRESHOLD:
            row['market_regime'] = 'LOOSE'
        else:
            row['market_regime'] = 'NORMAL'
    else:
        row['market_regime'] = 'NORMAL'

    row['computed_at'] = datetime.now(timezone.utc).isoformat()

    # Convert Decimal values from BQ to float for JSON serialization
    for k, v in row.items():
        if isinstance(v, decimal.Decimal):
            row[k] = float(v)

    return row


def _compute_mae_metrics(bq_client: bigquery.Client, target_date: date) -> Optional[dict]:
    """Compute Vegas MAE, Model MAE, edge metrics from prediction_accuracy."""
    query = """
    WITH raw AS (
      SELECT
        game_date, player_lookup,
        ABS(line_value - actual_points) as vegas_error,
        ABS(predicted_points - actual_points) as model_error,
        ABS(predicted_points - line_value) as edge,
        line_value,
        recommendation,
        ROW_NUMBER() OVER (
          PARTITION BY game_date, player_lookup
          ORDER BY ABS(predicted_points - line_value) DESC
        ) as rn
      FROM `nba-props-platform.nba_predictions.prediction_accuracy`
      WHERE game_date BETWEEN @start_date AND @target_date
        AND has_prop_line = TRUE
        AND recommendation IN ('OVER', 'UNDER')
        AND prediction_correct IS NOT NULL
        AND actual_points IS NOT NULL
        AND (system_id = 'catboost_v12' OR system_id LIKE 'catboost_v12_%')
    ),
    daily AS (
      SELECT game_date, vegas_error, model_error, edge, line_value, recommendation
      FROM raw WHERE rn = 1
    ),
    today AS (
      SELECT
        ROUND(AVG(vegas_error), 2) as vegas_mae_daily,
        ROUND(AVG(model_error), 2) as model_mae_daily,
        ROUND(AVG(model_error) - AVG(vegas_error), 2) as mae_gap_daily,
        ROUND(AVG(edge), 2) as avg_edge_daily,
        ROUND(AVG(line_value), 1) as avg_line_daily,
        ROUND(SAFE_DIVIDE(COUNTIF(edge >= 3), COUNT(*)) * 100, 1) as pct_edge_3plus,
        COUNT(*) as total_predictions,
        ROUND(SAFE_DIVIDE(COUNTIF(recommendation = 'OVER'), COUNT(*)) * 100, 1) as pct_over
      FROM daily WHERE game_date = @target_date
    ),
    rolling_7d AS (
      SELECT
        ROUND(AVG(vegas_error), 2) as vegas_mae_7d,
        ROUND(AVG(model_error), 2) as model_mae_7d,
        ROUND(AVG(model_error) - AVG(vegas_error), 2) as mae_gap_7d,
        ROUND(AVG(edge), 2) as avg_edge_7d
      FROM daily WHERE game_date >= @d7
    ),
    rolling_14d AS (
      SELECT
        ROUND(AVG(vegas_error), 2) as vegas_mae_14d,
        ROUND(AVG(model_error), 2) as model_mae_14d,
        ROUND(AVG(model_error) - AVG(vegas_error), 2) as mae_gap_14d
      FROM daily WHERE game_date >= @d14
    )
    SELECT t.*, r7.*, r14.*
    FROM today t, rolling_7d r7, rolling_14d r14
    """
    d7 = target_date - timedelta(days=6)
    d14 = target_date - timedelta(days=13)
    start_date = target_date - timedelta(days=13)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('start_date', 'DATE', start_date),
            bigquery.ScalarQueryParameter('d7', 'DATE', d7),
            bigquery.ScalarQueryParameter('d14', 'DATE', d14),
        ]
    )

    rows = list(bq_client.query(query, job_config=job_config).result())
    if not rows or rows[0].total_predictions is None or rows[0].total_predictions == 0:
        return None

    r = rows[0]
    return {
        'vegas_mae_daily': r.vegas_mae_daily,
        'vegas_mae_7d': r.vegas_mae_7d,
        'vegas_mae_14d': r.vegas_mae_14d,
        'model_mae_daily': r.model_mae_daily,
        'model_mae_7d': r.model_mae_7d,
        'model_mae_14d': r.model_mae_14d,
        'mae_gap_daily': r.mae_gap_daily,
        'mae_gap_7d': r.mae_gap_7d,
        'mae_gap_14d': r.mae_gap_14d,
        'avg_edge_daily': r.avg_edge_daily,
        'avg_edge_7d': r.avg_edge_7d,
        'avg_line_daily': r.avg_line_daily,
        'pct_edge_3plus': r.pct_edge_3plus,
        'total_predictions': r.total_predictions,
        'pct_over': r.pct_over,
    }


def _compute_scoring_metrics(bq_client: bigquery.Client, target_date: date) -> dict:
    """Compute league scoring environment from player_game_summary."""
    query = """
    WITH daily AS (
      SELECT game_date, points
      FROM `nba-props-platform.nba_analytics.player_game_summary`
      WHERE game_date BETWEEN @d7 AND @target_date
        AND (is_dnp IS NULL OR is_dnp = FALSE)
        AND minutes_played > 0
    ),
    today AS (
      SELECT
        ROUND(AVG(points), 2) as league_avg_ppg,
        ROUND(STDDEV(points), 2) as league_scoring_std,
        ROUND(SAFE_DIVIDE(COUNTIF(points >= 20), COUNT(*)) * 100, 1) as league_pct_over_20
      FROM daily WHERE game_date = @target_date
    ),
    rolling_7d AS (
      SELECT ROUND(AVG(points), 2) as league_avg_ppg_7d
      FROM daily
    ),
    games_today AS (
      SELECT COUNT(*) as games_played
      FROM `nba-props-platform.nba_reference.nba_schedule`
      WHERE game_date = @target_date AND game_status = 3
    )
    SELECT t.*, r.league_avg_ppg_7d, g.games_played
    FROM today t, rolling_7d r, games_today g
    """
    d7 = target_date - timedelta(days=6)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('d7', 'DATE', d7),
        ]
    )

    rows = list(bq_client.query(query, job_config=job_config).result())
    if not rows:
        return {
            'games_played': 0,
            'league_avg_ppg': None,
            'league_avg_ppg_7d': None,
            'league_scoring_std': None,
            'league_pct_over_20': None,
        }

    r = rows[0]
    return {
        'games_played': r.games_played,
        'league_avg_ppg': r.league_avg_ppg,
        'league_avg_ppg_7d': r.league_avg_ppg_7d,
        'league_scoring_std': r.league_scoring_std,
        'league_pct_over_20': r.league_pct_over_20,
    }


def _compute_bb_metrics(bq_client: bigquery.Client, target_date: date) -> dict:
    """Compute best bets rolling hit rate."""
    query = """
    WITH bb_graded AS (
      SELECT bb.game_date,
        pa.prediction_correct
      FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` bb
      JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
        ON bb.game_date = pa.game_date
        AND bb.player_lookup = pa.player_lookup
        AND bb.recommendation = pa.recommendation
        AND bb.system_id = pa.system_id
        AND pa.has_prop_line = TRUE
      WHERE bb.game_date BETWEEN @d14 AND @target_date
    ),
    rolling_7d AS (
      SELECT
        ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE),
              COUNTIF(prediction_correct IS NOT NULL)) * 100, 1) as bb_hr_7d,
        CAST(COUNTIF(prediction_correct IS NOT NULL) AS INT64) as bb_n_7d
      FROM bb_graded WHERE game_date >= @d7
    ),
    rolling_14d AS (
      SELECT
        ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE),
              COUNTIF(prediction_correct IS NOT NULL)) * 100, 1) as bb_hr_14d,
        CAST(COUNTIF(prediction_correct IS NOT NULL) AS INT64) as bb_n_14d
      FROM bb_graded
    )
    SELECT r7.*, r14.*
    FROM rolling_7d r7, rolling_14d r14
    """
    d7 = target_date - timedelta(days=6)
    d14 = target_date - timedelta(days=13)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('d7', 'DATE', d7),
            bigquery.ScalarQueryParameter('d14', 'DATE', d14),
        ]
    )

    rows = list(bq_client.query(query, job_config=job_config).result())
    if not rows:
        return {'bb_hr_7d': None, 'bb_n_7d': 0, 'bb_hr_14d': None, 'bb_n_14d': 0}

    r = rows[0]
    return {
        'bb_hr_7d': r.bb_hr_7d,
        'bb_n_7d': r.bb_n_7d,
        'bb_hr_14d': r.bb_hr_14d,
        'bb_n_14d': r.bb_n_14d,
    }


def write_rows(bq_client: bigquery.Client, row: dict) -> int:
    """Write computed row to league_macro_daily. Returns rows written.

    Uses DELETE-before-write to prevent duplicate rows when re-run.
    """
    if not row:
        return 0

    target_date = row['game_date']

    # Delete existing row for this date
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

    # Write new row
    load_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
    )
    load_job = bq_client.load_table_from_json([row], TABLE_ID, job_config=load_config)
    load_job.result(timeout=60)

    logger.info(f"Wrote 1 row to league_macro_daily for {target_date}")
    return 1


def backfill(bq_client: bigquery.Client, start_date: date,
             end_date: Optional[date] = None) -> int:
    """Backfill league_macro_daily from start_date to end_date."""
    if end_date is None:
        end_date = date.today() - timedelta(days=1)

    # Find dates that have graded predictions
    query = """
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_predictions.prediction_accuracy`
    WHERE game_date BETWEEN @start AND @end
      AND has_prop_line = TRUE
      AND prediction_correct IS NOT NULL
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
        logger.warning(f"No graded dates found between {start_date} and {end_date}")
        return 0

    logger.info(f"Backfilling {len(dates)} dates: {dates[0]} to {dates[-1]}")
    total_written = 0

    for d in dates:
        try:
            row = compute_for_date(bq_client, d)
            if row:
                write_rows(bq_client, row)
                total_written += 1
        except Exception as e:
            logger.error(f"Failed to compute for {d}: {e}", exc_info=True)

    logger.info(f"Backfill complete: {total_written}/{len(dates)} dates written")
    return total_written


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description='Compute league macro daily metrics')
    parser.add_argument('--date', type=str, help='Target date (YYYY-MM-DD)')
    parser.add_argument('--backfill', action='store_true', help='Run backfill mode')
    parser.add_argument('--start', type=str, help='Backfill start date')
    parser.add_argument('--end', type=str, help='Backfill end date (default: yesterday)')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s'
    )

    bq_client = bigquery.Client(project='nba-props-platform')

    if args.backfill:
        if not args.start:
            parser.error('--start required for backfill')
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end) if args.end else None
        total = backfill(bq_client, start, end)
        print(f"Backfill complete: {total} dates written")
    else:
        target = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
        row = compute_for_date(bq_client, target)
        if row:
            written = write_rows(bq_client, row)
            print(f"Wrote {written} row for {target}")
            # Print summary
            print(f"  Vegas MAE: {row.get('vegas_mae_daily')} (7d: {row.get('vegas_mae_7d')})")
            print(f"  Model MAE: {row.get('model_mae_daily')} (7d: {row.get('model_mae_7d')})")
            print(f"  MAE gap:   {row.get('mae_gap_daily')} (7d: {row.get('mae_gap_7d')})")
            print(f"  Scoring:   {row.get('league_avg_ppg')} ppg (7d: {row.get('league_avg_ppg_7d')})")
            print(f"  Edge:      {row.get('avg_edge_daily')} (7d: {row.get('avg_edge_7d')})")
            print(f"  BB HR:     {row.get('bb_hr_7d')}% (N={row.get('bb_n_7d')})")
            print(f"  Regime:    {row.get('market_regime')}")
        else:
            print(f"No data for {target}")


if __name__ == '__main__':
    main()
