"""Compute daily MLB league macro trends for mlb_predictions.league_macro_daily.

Tracks market efficiency (Vegas MAE for K props), strikeout environment,
model performance, and best bets rolling hit rate. Single row per game_date.

Usage:
    # Backfill from historical data
    PYTHONPATH=. .venv/bin/python ml/analysis/mlb_league_macro.py --backfill --start 2024-04-01

    # Single date (used by Cloud Function post-grading)
    PYTHONPATH=. .venv/bin/python ml/analysis/mlb_league_macro.py --date 2026-03-07

    # Dry run (print without writing to BQ)
    PYTHONPATH=. .venv/bin/python ml/analysis/mlb_league_macro.py --date 2026-03-07 --dry-run

Created: 2026-03-08
"""

import argparse
import decimal
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
TABLE_ID = f'{PROJECT_ID}.mlb_predictions.league_macro_daily'

# Market regime thresholds (based on Vegas MAE 7d for K props)
# K lines are typically 4.5-6.5 range, so MAE thresholds are tighter than NBA points
TIGHT_THRESHOLD = 1.7    # Vegas very accurate = hard to beat
LOOSE_THRESHOLD = 2.0    # Vegas less accurate = more opportunity

# DDL for auto-creating the table
CREATE_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS `{TABLE_ID}` (
  game_date DATE NOT NULL,

  -- League K environment (from pitcher_game_summary)
  avg_k_per_game FLOAT64,             -- League avg Ks per start that day
  avg_k_per_9 FLOAT64,                -- League avg K/9 that day
  avg_innings FLOAT64,                -- League avg innings pitched that day
  total_games INT64,                   -- Number of games with starter data
  avg_k_per_game_7d FLOAT64,
  avg_k_per_game_14d FLOAT64,
  avg_k_per_game_30d FLOAT64,

  -- Vegas line accuracy (from bp_pitcher_props strikeouts)
  vegas_mae_daily FLOAT64,            -- |over_line - actual_value| mean
  vegas_bias_daily FLOAT64,           -- actual - over_line (positive = books underestimate Ks)
  avg_line_level FLOAT64,             -- Average K line set by books
  vegas_mae_7d FLOAT64,
  vegas_mae_14d FLOAT64,
  vegas_mae_30d FLOAT64,
  vegas_bias_7d FLOAT64,

  -- Model performance (from prediction_accuracy)
  model_mae_daily FLOAT64,            -- |predicted_strikeouts - actual_strikeouts|
  model_hr_daily FLOAT64,             -- Hit rate (pct correct) that day
  total_predictions INT64,            -- Graded predictions that day
  pct_over FLOAT64,                   -- Pct of predictions that are OVER
  model_mae_7d FLOAT64,
  model_mae_14d FLOAT64,
  model_hr_7d FLOAT64,
  model_hr_14d FLOAT64,
  mae_gap_daily FLOAT64,              -- model_mae - vegas_mae (negative = we beat Vegas)
  mae_gap_7d FLOAT64,

  -- Best bets performance
  bb_hr_7d FLOAT64,                   -- Best bets hit rate (7d rolling)
  bb_n_7d INT64,                      -- Best bets graded count (7d)
  bb_hr_14d FLOAT64,
  bb_n_14d INT64,

  -- Market regime
  market_regime STRING,               -- TIGHT / NORMAL / LOOSE

  computed_at TIMESTAMP
)
PARTITION BY game_date
OPTIONS (
  description='Daily MLB league macro trends. Tracks K environment, Vegas accuracy, model performance, and best bets HR.',
  require_partition_filter=FALSE
)
"""


def ensure_table_exists(bq_client: bigquery.Client) -> None:
    """Create the league_macro_daily table if it doesn't exist."""
    try:
        bq_client.get_table(TABLE_ID)
        logger.debug(f"Table {TABLE_ID} already exists")
    except Exception:
        logger.info(f"Creating table {TABLE_ID}")
        bq_client.query(CREATE_TABLE_DDL).result(timeout=60)
        logger.info(f"Table {TABLE_ID} created")


def compute_for_date(bq_client: bigquery.Client, target_date: date) -> Optional[dict]:
    """Compute MLB league macro metrics for a single date.

    Returns a single dict row, or None if no data for this date.
    """
    row = {}
    row['game_date'] = target_date.isoformat()

    # --- 1. League K environment (from pitcher_game_summary) ---
    k_data = _compute_k_environment(bq_client, target_date)
    row.update(k_data)

    # --- 2. Vegas line accuracy (from bp_pitcher_props) ---
    vegas_data = _compute_vegas_accuracy(bq_client, target_date)
    row.update(vegas_data)

    # --- 3. Model performance (from prediction_accuracy) ---
    model_data = _compute_model_metrics(bq_client, target_date)
    row.update(model_data)

    # --- 4. Best bets performance ---
    bb_data = _compute_bb_metrics(bq_client, target_date)
    row.update(bb_data)

    # Check if we have ANY data for this date
    has_k_data = k_data.get('total_games') and k_data['total_games'] > 0
    has_vegas_data = vegas_data.get('vegas_mae_daily') is not None
    has_model_data = model_data.get('total_predictions') and model_data['total_predictions'] > 0

    if not has_k_data and not has_vegas_data and not has_model_data:
        logger.info(f"No data for {target_date}, skipping")
        return None

    # --- 5. Market regime classification ---
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


def _compute_k_environment(bq_client: bigquery.Client, target_date: date) -> dict:
    """Compute league K environment from pitcher_game_summary."""
    query = """
    WITH daily AS (
      SELECT
        game_date,
        strikeouts,
        innings_pitched,
        SAFE_DIVIDE(strikeouts * 9, innings_pitched) as k_per_9
      FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
      WHERE game_date BETWEEN @d30 AND @target_date
        AND innings_pitched >= 3.0
        AND strikeouts IS NOT NULL
    ),
    today AS (
      SELECT
        ROUND(AVG(strikeouts), 2) as avg_k_per_game,
        ROUND(AVG(k_per_9), 2) as avg_k_per_9,
        ROUND(AVG(innings_pitched), 2) as avg_innings,
        COUNT(*) as total_games
      FROM daily WHERE game_date = @target_date
    ),
    rolling_7d AS (
      SELECT ROUND(AVG(strikeouts), 2) as avg_k_per_game_7d
      FROM daily WHERE game_date >= @d7
    ),
    rolling_14d AS (
      SELECT ROUND(AVG(strikeouts), 2) as avg_k_per_game_14d
      FROM daily WHERE game_date >= @d14
    ),
    rolling_30d AS (
      SELECT ROUND(AVG(strikeouts), 2) as avg_k_per_game_30d
      FROM daily
    )
    SELECT t.*, r7.*, r14.*, r30.*
    FROM today t, rolling_7d r7, rolling_14d r14, rolling_30d r30
    """
    d7 = target_date - timedelta(days=6)
    d14 = target_date - timedelta(days=13)
    d30 = target_date - timedelta(days=29)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('d7', 'DATE', d7),
            bigquery.ScalarQueryParameter('d14', 'DATE', d14),
            bigquery.ScalarQueryParameter('d30', 'DATE', d30),
        ]
    )

    rows = list(bq_client.query(query, job_config=job_config).result())
    if not rows:
        return {
            'avg_k_per_game': None, 'avg_k_per_9': None, 'avg_innings': None,
            'total_games': 0, 'avg_k_per_game_7d': None,
            'avg_k_per_game_14d': None, 'avg_k_per_game_30d': None,
        }

    r = rows[0]
    return {
        'avg_k_per_game': r.avg_k_per_game,
        'avg_k_per_9': r.avg_k_per_9,
        'avg_innings': r.avg_innings,
        'total_games': r.total_games,
        'avg_k_per_game_7d': r.avg_k_per_game_7d,
        'avg_k_per_game_14d': r.avg_k_per_game_14d,
        'avg_k_per_game_30d': r.avg_k_per_game_30d,
    }


def _compute_vegas_accuracy(bq_client: bigquery.Client, target_date: date) -> dict:
    """Compute Vegas line accuracy from bp_pitcher_props (strikeouts market)."""
    query = """
    WITH daily AS (
      SELECT
        game_date,
        ABS(over_line - actual_value) as vegas_error,
        (actual_value - over_line) as vegas_bias,
        over_line
      FROM `nba-props-platform.mlb_raw.bp_pitcher_props`
      WHERE game_date BETWEEN @d30 AND @target_date
        AND market_id = 285
        AND is_scored = TRUE
        AND actual_value IS NOT NULL
        AND over_line IS NOT NULL
    ),
    today AS (
      SELECT
        ROUND(AVG(vegas_error), 2) as vegas_mae_daily,
        ROUND(AVG(vegas_bias), 2) as vegas_bias_daily,
        ROUND(AVG(over_line), 1) as avg_line_level
      FROM daily WHERE game_date = @target_date
    ),
    rolling_7d AS (
      SELECT
        ROUND(AVG(vegas_error), 2) as vegas_mae_7d,
        ROUND(AVG(vegas_bias), 2) as vegas_bias_7d
      FROM daily WHERE game_date >= @d7
    ),
    rolling_14d AS (
      SELECT ROUND(AVG(vegas_error), 2) as vegas_mae_14d
      FROM daily WHERE game_date >= @d14
    ),
    rolling_30d AS (
      SELECT ROUND(AVG(vegas_error), 2) as vegas_mae_30d
      FROM daily
    )
    SELECT t.*, r7.*, r14.*, r30.*
    FROM today t, rolling_7d r7, rolling_14d r14, rolling_30d r30
    """
    d7 = target_date - timedelta(days=6)
    d14 = target_date - timedelta(days=13)
    d30 = target_date - timedelta(days=29)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('d7', 'DATE', d7),
            bigquery.ScalarQueryParameter('d14', 'DATE', d14),
            bigquery.ScalarQueryParameter('d30', 'DATE', d30),
        ]
    )

    rows = list(bq_client.query(query, job_config=job_config).result())
    if not rows:
        return {
            'vegas_mae_daily': None, 'vegas_bias_daily': None,
            'avg_line_level': None, 'vegas_mae_7d': None,
            'vegas_mae_14d': None, 'vegas_mae_30d': None,
            'vegas_bias_7d': None,
        }

    r = rows[0]
    return {
        'vegas_mae_daily': r.vegas_mae_daily,
        'vegas_bias_daily': r.vegas_bias_daily,
        'avg_line_level': r.avg_line_level,
        'vegas_mae_7d': r.vegas_mae_7d,
        'vegas_mae_14d': r.vegas_mae_14d,
        'vegas_mae_30d': r.vegas_mae_30d,
        'vegas_bias_7d': r.vegas_bias_7d,
    }


def _compute_model_metrics(bq_client: bigquery.Client, target_date: date) -> dict:
    """Compute model MAE and hit rate from prediction_accuracy."""
    query = """
    WITH daily AS (
      SELECT
        game_date,
        absolute_error as model_error,
        prediction_correct,
        recommendation
      FROM `nba-props-platform.mlb_predictions.prediction_accuracy`
      WHERE game_date BETWEEN @d14 AND @target_date
        AND has_prop_line = TRUE
        AND recommendation IN ('OVER', 'UNDER')
        AND prediction_correct IS NOT NULL
        AND actual_strikeouts IS NOT NULL
        AND is_voided = FALSE
    ),
    today AS (
      SELECT
        ROUND(AVG(model_error), 2) as model_mae_daily,
        ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE),
              COUNTIF(prediction_correct IS NOT NULL)) * 100, 1) as model_hr_daily,
        COUNT(*) as total_predictions,
        ROUND(SAFE_DIVIDE(COUNTIF(recommendation = 'OVER'), COUNT(*)) * 100, 1) as pct_over
      FROM daily WHERE game_date = @target_date
    ),
    rolling_7d AS (
      SELECT
        ROUND(AVG(model_error), 2) as model_mae_7d,
        ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE),
              COUNTIF(prediction_correct IS NOT NULL)) * 100, 1) as model_hr_7d
      FROM daily WHERE game_date >= @d7
    ),
    rolling_14d AS (
      SELECT
        ROUND(AVG(model_error), 2) as model_mae_14d,
        ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE),
              COUNTIF(prediction_correct IS NOT NULL)) * 100, 1) as model_hr_14d
      FROM daily
    )
    SELECT t.*, r7.*, r14.*
    FROM today t, rolling_7d r7, rolling_14d r14
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

    try:
        rows = list(bq_client.query(query, job_config=job_config).result())
    except Exception as e:
        # Table may not exist yet pre-season
        logger.debug(f"Model metrics query failed (table may not exist): {e}")
        return {
            'model_mae_daily': None, 'model_hr_daily': None,
            'total_predictions': 0, 'pct_over': None,
            'model_mae_7d': None, 'model_mae_14d': None,
            'model_hr_7d': None, 'model_hr_14d': None,
            'mae_gap_daily': None, 'mae_gap_7d': None,
        }

    if not rows or rows[0].total_predictions is None or rows[0].total_predictions == 0:
        return {
            'model_mae_daily': None, 'model_hr_daily': None,
            'total_predictions': 0, 'pct_over': None,
            'model_mae_7d': None, 'model_mae_14d': None,
            'model_hr_7d': None, 'model_hr_14d': None,
            'mae_gap_daily': None, 'mae_gap_7d': None,
        }

    r = rows[0]
    # Compute MAE gap (negative = model beats Vegas)
    mae_gap_daily = None
    mae_gap_7d = None

    return {
        'model_mae_daily': r.model_mae_daily,
        'model_hr_daily': r.model_hr_daily,
        'total_predictions': r.total_predictions,
        'pct_over': r.pct_over,
        'model_mae_7d': r.model_mae_7d,
        'model_mae_14d': r.model_mae_14d,
        'model_hr_7d': r.model_hr_7d,
        'model_hr_14d': r.model_hr_14d,
        'mae_gap_daily': mae_gap_daily,
        'mae_gap_7d': mae_gap_7d,
    }


def _compute_bb_metrics(bq_client: bigquery.Client, target_date: date) -> dict:
    """Compute best bets rolling hit rate."""
    query = """
    WITH bb_graded AS (
      SELECT bb.game_date,
        pa.prediction_correct
      FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks` bb
      JOIN `nba-props-platform.mlb_predictions.prediction_accuracy` pa
        ON bb.game_date = pa.game_date
        AND bb.pitcher_lookup = pa.pitcher_lookup
        AND bb.recommendation = pa.recommendation
        AND bb.system_id = pa.system_id
        AND pa.has_prop_line = TRUE
        AND pa.is_voided = FALSE
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

    try:
        rows = list(bq_client.query(query, job_config=job_config).result())
    except Exception as e:
        # Table may not exist yet pre-season
        logger.debug(f"BB metrics query failed (table may not exist): {e}")
        return {'bb_hr_7d': None, 'bb_n_7d': 0, 'bb_hr_14d': None, 'bb_n_14d': 0}

    if not rows:
        return {'bb_hr_7d': None, 'bb_n_7d': 0, 'bb_hr_14d': None, 'bb_n_14d': 0}

    r = rows[0]
    return {
        'bb_hr_7d': r.bb_hr_7d,
        'bb_n_7d': r.bb_n_7d,
        'bb_hr_14d': r.bb_hr_14d,
        'bb_n_14d': r.bb_n_14d,
    }


def _compute_mae_gap(row: dict) -> dict:
    """Compute MAE gap between model and Vegas. Must be called after both are populated."""
    mae_gap_daily = None
    mae_gap_7d = None

    model_mae = row.get('model_mae_daily')
    vegas_mae = row.get('vegas_mae_daily')
    if model_mae is not None and vegas_mae is not None:
        mae_gap_daily = round(model_mae - vegas_mae, 2)

    model_mae_7d = row.get('model_mae_7d')
    vegas_mae_7d = row.get('vegas_mae_7d')
    if model_mae_7d is not None and vegas_mae_7d is not None:
        mae_gap_7d = round(model_mae_7d - vegas_mae_7d, 2)

    return {'mae_gap_daily': mae_gap_daily, 'mae_gap_7d': mae_gap_7d}


def write_row(bq_client: bigquery.Client, row: dict) -> int:
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

    logger.info(f"Wrote 1 row to mlb league_macro_daily for {target_date}")
    return 1


def backfill(bq_client: bigquery.Client, start_date: date,
             end_date: Optional[date] = None, dry_run: bool = False) -> int:
    """Backfill league_macro_daily from start_date to end_date.

    Finds dates that have pitcher_game_summary data (from completed games).
    """
    if end_date is None:
        end_date = date.today() - timedelta(days=1)

    # Find dates that have pitcher game summary data
    query = """
    SELECT DISTINCT game_date
    FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
    WHERE game_date BETWEEN @start AND @end
      AND strikeouts IS NOT NULL
    ORDER BY game_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('start', 'DATE', start_date),
            bigquery.ScalarQueryParameter('end', 'DATE', end_date),
        ]
    )

    try:
        dates = [row.game_date for row in bq_client.query(query, job_config=job_config).result()]
    except Exception as e:
        logger.warning(f"Could not query pitcher_game_summary: {e}")
        # Fall back to bp_pitcher_props for historical backfill
        query2 = """
        SELECT DISTINCT game_date
        FROM `nba-props-platform.mlb_raw.bp_pitcher_props`
        WHERE game_date BETWEEN @start AND @end
          AND market_id = 285
          AND is_scored = TRUE
        ORDER BY game_date
        """
        dates = [row.game_date for row in bq_client.query(query2, job_config=job_config).result()]

    if not dates:
        logger.warning(f"No dates with data found between {start_date} and {end_date}")
        return 0

    logger.info(f"Backfilling {len(dates)} dates: {dates[0]} to {dates[-1]}")
    total_written = 0

    for d in dates:
        try:
            row = compute_for_date(bq_client, d)
            if row:
                # Compute MAE gap after both model and vegas data are populated
                gap = _compute_mae_gap(row)
                row.update(gap)

                if dry_run:
                    _print_row(row)
                else:
                    write_row(bq_client, row)
                total_written += 1
        except Exception as e:
            logger.error(f"Failed to compute for {d}: {e}", exc_info=True)

    logger.info(f"Backfill complete: {total_written}/{len(dates)} dates processed")
    return total_written


def _print_row(row: dict) -> None:
    """Pretty-print a row for dry-run mode."""
    d = row.get('game_date', '?')
    print(f"\n--- {d} ---")
    print(f"  K env:     avg={row.get('avg_k_per_game')} K/game, "
          f"K/9={row.get('avg_k_per_9')}, "
          f"IP={row.get('avg_innings')}, "
          f"games={row.get('total_games')}")
    print(f"  K env 7d:  avg={row.get('avg_k_per_game_7d')} K/game")
    print(f"  Vegas:     MAE={row.get('vegas_mae_daily')} "
          f"(7d: {row.get('vegas_mae_7d')}, 14d: {row.get('vegas_mae_14d')})")
    print(f"  Vegas:     bias={row.get('vegas_bias_daily')} "
          f"(7d: {row.get('vegas_bias_7d')}), "
          f"avg_line={row.get('avg_line_level')}")
    print(f"  Model:     MAE={row.get('model_mae_daily')} "
          f"(7d: {row.get('model_mae_7d')}), "
          f"HR={row.get('model_hr_daily')}% "
          f"(7d: {row.get('model_hr_7d')}%)")
    print(f"  MAE gap:   {row.get('mae_gap_daily')} "
          f"(7d: {row.get('mae_gap_7d')})")
    print(f"  BB HR:     {row.get('bb_hr_7d')}% (N={row.get('bb_n_7d')})")
    print(f"  Regime:    {row.get('market_regime')}")
    print(f"  Preds:     {row.get('total_predictions')} "
          f"({row.get('pct_over')}% OVER)")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description='Compute MLB league macro daily metrics')
    parser.add_argument('--date', type=str, help='Target date (YYYY-MM-DD)')
    parser.add_argument('--backfill', action='store_true', help='Run backfill mode')
    parser.add_argument('--start', type=str, help='Backfill start date')
    parser.add_argument('--end', type=str, help='Backfill end date (default: yesterday)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print results without writing to BQ')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s'
    )

    bq_client = bigquery.Client(project=PROJECT_ID)

    if not args.dry_run:
        ensure_table_exists(bq_client)

    if args.backfill:
        if not args.start:
            parser.error('--start required for backfill')
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end) if args.end else None
        total = backfill(bq_client, start, end, dry_run=args.dry_run)
        print(f"\nBackfill complete: {total} dates {'printed' if args.dry_run else 'written'}")
    else:
        target = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
        row = compute_for_date(bq_client, target)
        if row:
            # Compute MAE gap after both model and vegas data are populated
            gap = _compute_mae_gap(row)
            row.update(gap)

            if args.dry_run:
                _print_row(row)
            else:
                written = write_row(bq_client, row)
                print(f"Wrote {written} row for {target}")
                _print_row(row)
        else:
            print(f"No data for {target}")


if __name__ == '__main__':
    main()
