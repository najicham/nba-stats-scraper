"""Compute daily MLB model performance metrics for model_performance_daily table.

Simplified version of NBA model_performance.py for MLB's single-model setup.
Queries mlb_predictions.prediction_accuracy for rolling hit rates and daily stats,
writes results to mlb_predictions.model_performance_daily.

Usage:
    PYTHONPATH=. python ml/analysis/mlb_model_performance.py --date 2026-04-10
    PYTHONPATH=. python ml/analysis/mlb_model_performance.py --backfill --start 2026-04-01

Created: 2026-04-10 (Session 519)
"""

import argparse
import decimal
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
TABLE_ID = f'{PROJECT_ID}.mlb_predictions.model_performance_daily'
PREDICTION_ACCURACY_TABLE = f'{PROJECT_ID}.mlb_predictions.prediction_accuracy'
BB_TABLE = f'{PROJECT_ID}.mlb_predictions.signal_best_bets_picks'

# MLB uses a single model currently
DEFAULT_MODELS = ['catboost_v2_regressor']

# Decay thresholds (same as NBA)
WATCH_THRESHOLD = 58.0
ALERT_THRESHOLD = 55.0
BLOCK_THRESHOLD = 52.4


def compute_for_date(
    bq_client: bigquery.Client,
    target_date: date,
    model_ids: List[str] = None,
) -> List[dict]:
    """Compute model performance metrics for a single date.

    Returns list of row dicts ready for BQ insert.
    """
    if model_ids is None:
        model_ids = DEFAULT_MODELS

    query = f"""
    WITH graded AS (
      SELECT
        game_date,
        system_id AS model_id,
        recommendation,
        CASE WHEN prediction_correct THEN 1 ELSE 0 END AS win,
        ABS(predicted_strikeouts - actual_strikeouts) AS abs_error
      FROM `{PREDICTION_ACCURACY_TABLE}`
      WHERE game_date BETWEEN DATE_SUB(@target_date, INTERVAL 30 DAY) AND @target_date
        AND prediction_correct IS NOT NULL
        AND system_id IN UNNEST(@model_ids)
    )
    SELECT
      model_id,
      -- Daily
      COUNTIF(game_date = @target_date) AS daily_picks,
      COUNTIF(game_date = @target_date AND win = 1) AS daily_wins,
      COUNTIF(game_date = @target_date AND win = 0) AS daily_losses,
      -- 7d rolling
      COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)) AS n_7d,
      SAFE_DIVIDE(
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY) AND win = 1),
        NULLIF(COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)), 0)
      ) * 100.0 AS hr_7d,
      -- 14d rolling
      COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY)) AS n_14d,
      SAFE_DIVIDE(
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND win = 1),
        NULLIF(COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY)), 0)
      ) * 100.0 AS hr_14d,
      -- 30d rolling
      COUNT(*) AS n_30d,
      SAFE_DIVIDE(COUNTIF(win = 1), NULLIF(COUNT(*), 0)) * 100.0 AS hr_30d,
      -- OVER splits (7d, 14d, 30d)
      COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY) AND recommendation = 'OVER') AS n_over_7d,
      SAFE_DIVIDE(
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY) AND recommendation = 'OVER' AND win = 1),
        NULLIF(COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY) AND recommendation = 'OVER'), 0)
      ) * 100.0 AS hr_over_7d,
      COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND recommendation = 'OVER') AS n_over_14d,
      SAFE_DIVIDE(
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND recommendation = 'OVER' AND win = 1),
        NULLIF(COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND recommendation = 'OVER'), 0)
      ) * 100.0 AS hr_over_14d,
      COUNT(CASE WHEN recommendation = 'OVER' THEN 1 END) AS n_over_30d,
      SAFE_DIVIDE(
        COUNTIF(recommendation = 'OVER' AND win = 1),
        NULLIF(COUNT(CASE WHEN recommendation = 'OVER' THEN 1 END), 0)
      ) * 100.0 AS hr_over_30d,
      -- UNDER splits (7d, 14d, 30d)
      COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY) AND recommendation = 'UNDER') AS n_under_7d,
      SAFE_DIVIDE(
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY) AND recommendation = 'UNDER' AND win = 1),
        NULLIF(COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY) AND recommendation = 'UNDER'), 0)
      ) * 100.0 AS hr_under_7d,
      COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND recommendation = 'UNDER') AS n_under_14d,
      SAFE_DIVIDE(
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND recommendation = 'UNDER' AND win = 1),
        NULLIF(COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) AND recommendation = 'UNDER'), 0)
      ) * 100.0 AS hr_under_14d,
      COUNT(CASE WHEN recommendation = 'UNDER' THEN 1 END) AS n_under_30d,
      SAFE_DIVIDE(
        COUNTIF(recommendation = 'UNDER' AND win = 1),
        NULLIF(COUNT(CASE WHEN recommendation = 'UNDER' THEN 1 END), 0)
      ) * 100.0 AS hr_under_30d,
      -- MAE
      AVG(CASE WHEN game_date > DATE_SUB(@target_date, INTERVAL 7 DAY) THEN abs_error END) AS mae_7d,
      AVG(CASE WHEN game_date > DATE_SUB(@target_date, INTERVAL 14 DAY) THEN abs_error END) AS mae_14d,
      AVG(abs_error) AS mae_30d
    FROM graded
    GROUP BY model_id
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("target_date", "DATE", target_date.isoformat()),
            bigquery.ArrayQueryParameter("model_ids", "STRING", model_ids),
        ]
    )

    try:
        result = bq_client.query(query, job_config=job_config).result()
    except Exception as e:
        logger.error(f"Model performance query failed: {e}")
        return []

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for r in result:
        # Convert BQ Decimal (from AVG of NUMERIC cols like mae_7d) to float
        # so insert_rows_json can serialize without TypeError.
        row = {
            k: float(v) if isinstance(v, decimal.Decimal) else v
            for k, v in dict(r).items()
        }
        row['game_date'] = target_date.isoformat()
        row['daily_hr'] = (
            round(row['daily_wins'] / row['daily_picks'] * 100, 1)
            if row.get('daily_picks', 0) > 0 else None
        )
        row['computed_at'] = now

        # Simple decay state (no state machine — MLB is single-model)
        hr_7d = row.get('hr_7d')
        if hr_7d is None or row.get('n_7d', 0) < 5:
            row['decay_state'] = 'INSUFFICIENT_DATA'
        elif hr_7d >= WATCH_THRESHOLD:
            row['decay_state'] = 'HEALTHY'
        elif hr_7d >= ALERT_THRESHOLD:
            row['decay_state'] = 'WATCH'
        elif hr_7d >= BLOCK_THRESHOLD:
            row['decay_state'] = 'DEGRADING'
        else:
            row['decay_state'] = 'BLOCKED'

        rows.append(row)

    logger.info(
        f"Computed model performance for {target_date}: "
        f"{len(rows)} models"
    )
    return rows


def write_rows(bq_client: bigquery.Client, rows: List[dict]) -> int:
    """Write model performance rows to BQ."""
    if not rows:
        return 0

    try:
        errors = bq_client.insert_rows_json(TABLE_ID, rows)
        if errors:
            logger.error(f"Model performance insert errors: {errors[:3]}")
            return 0
        logger.info(f"Wrote {len(rows)} model performance rows")
        return len(rows)
    except Exception as e:
        logger.error(f"Failed to write model performance: {e}")
        return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="MLB model performance daily")
    parser.add_argument("--date", type=str, help="Single date (YYYY-MM-DD)")
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--start", type=str, help="Backfill start date")
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    if args.backfill and args.start:
        d = date.fromisoformat(args.start)
        end = date.today()
        while d <= end:
            rows = compute_for_date(client, d)
            write_rows(client, rows)
            d += timedelta(days=1)
    elif args.date:
        rows = compute_for_date(client, date.fromisoformat(args.date))
        write_rows(client, rows)
    else:
        rows = compute_for_date(client, date.today())
        write_rows(client, rows)
