#!/usr/bin/env python3
"""Signal Health — compute daily multi-timeframe performance for each signal.

Queries pick_signal_tags + prediction_accuracy to produce rolling HR at
7d, 14d, 30d, season timeframes for each signal. Classifies regime
(HOT / NORMAL / COLD) based on 7d-vs-season divergence.

Purpose: Monitoring and frontend transparency, NOT blocking.
    - COLD regime (divergence < -10) predicts 39.6% HR
    - NORMAL regime predicts 80.0% HR
    - This is informational — the signal count floor and combo registry
      handle actual pick quality.

Usage:
    # Single date
    PYTHONPATH=. python ml/signals/signal_health.py --date 2026-02-14

    # Backfill range
    PYTHONPATH=. python ml/signals/signal_health.py --backfill --start 2026-01-09 --end 2026-02-14

Created: 2026-02-15 (Session 259)
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
SYSTEM_ID = 'catboost_v9'
TABLE_ID = f'{PROJECT_ID}.nba_predictions.signal_health_daily'

# Signals that depend on model accuracy (decay with model staleness)
MODEL_DEPENDENT_SIGNALS = frozenset({
    'high_edge', 'edge_spread_optimal', 'combo_he_ms', 'combo_3way',
})

# Regime thresholds (Session 257 analysis)
COLD_THRESHOLD = -10.0   # divergence_7d_vs_season < -10 → COLD
HOT_THRESHOLD = 10.0     # divergence_7d_vs_season > +10 → HOT


def compute_signal_health(
    bq_client: bigquery.Client,
    target_date: str,
) -> List[Dict[str, Any]]:
    """Compute signal health metrics for a single date.

    Queries pick_signal_tags (unnested) joined with prediction_accuracy
    across 4 timeframes (7d, 14d, 30d, season) for each signal.

    Args:
        bq_client: BigQuery client.
        target_date: Date to compute health for (YYYY-MM-DD).

    Returns:
        List of dicts ready for BigQuery insertion (one per signal_tag).
    """
    query = f"""
    WITH tagged AS (
      SELECT
        pst.game_date,
        pst.player_lookup,
        pst.system_id,
        signal_tag,
        pa.prediction_correct
      FROM `{PROJECT_ID}.nba_predictions.pick_signal_tags` pst
      CROSS JOIN UNNEST(pst.signal_tags) AS signal_tag
      INNER JOIN `{PROJECT_ID}.nba_predictions.prediction_accuracy` pa
        ON pst.player_lookup = pa.player_lookup
        AND pst.game_date = pa.game_date
        AND pst.system_id = pa.system_id
      WHERE pst.game_date >= '2025-10-22'
        AND pst.game_date <= @target_date
        AND pa.prediction_correct IS NOT NULL
        AND pa.is_voided IS NOT TRUE
    ),

    signal_metrics AS (
      SELECT
        signal_tag,

        -- 7d
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)
                AND prediction_correct) AS wins_7d,
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)) AS picks_7d,

        -- 14d
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY)
                AND prediction_correct) AS wins_14d,
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY)) AS picks_14d,

        -- 30d
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 30 DAY)
                AND prediction_correct) AS wins_30d,
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 30 DAY)) AS picks_30d,

        -- Season
        COUNTIF(prediction_correct) AS wins_season,
        COUNT(*) AS picks_season

      FROM tagged
      GROUP BY signal_tag
    )

    SELECT
      signal_tag,
      ROUND(100.0 * SAFE_DIVIDE(wins_7d, picks_7d), 1) AS hr_7d,
      ROUND(100.0 * SAFE_DIVIDE(wins_14d, picks_14d), 1) AS hr_14d,
      ROUND(100.0 * SAFE_DIVIDE(wins_30d, picks_30d), 1) AS hr_30d,
      ROUND(100.0 * SAFE_DIVIDE(wins_season, picks_season), 1) AS hr_season,
      picks_7d, picks_14d, picks_30d, picks_season
    FROM signal_metrics
    WHERE picks_season > 0
    ORDER BY signal_tag
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )

    rows = bq_client.query(query, job_config=job_config).result(timeout=60)
    now = datetime.now(timezone.utc).isoformat()

    results = []
    for row in rows:
        hr_7d = row.hr_7d
        hr_season = row.hr_season

        # Divergence
        div_7d = round(hr_7d - hr_season, 1) if hr_7d is not None and hr_season is not None else None
        div_14d = round(row.hr_14d - hr_season, 1) if row.hr_14d is not None and hr_season is not None else None

        # Regime classification
        if div_7d is not None and div_7d < COLD_THRESHOLD:
            regime = 'COLD'
        elif div_7d is not None and div_7d > HOT_THRESHOLD:
            regime = 'HOT'
        else:
            regime = 'NORMAL'

        is_model_dep = row.signal_tag in MODEL_DEPENDENT_SIGNALS

        # Status
        if regime == 'COLD' and is_model_dep:
            status = 'DEGRADING'
        elif div_7d is not None and div_7d < -5.0:
            status = 'WATCH'
        else:
            status = 'HEALTHY'

        results.append({
            'game_date': target_date,
            'signal_tag': row.signal_tag,
            'hr_7d': hr_7d,
            'hr_14d': row.hr_14d,
            'hr_30d': row.hr_30d,
            'hr_season': hr_season,
            'picks_7d': row.picks_7d,
            'picks_14d': row.picks_14d,
            'picks_30d': row.picks_30d,
            'picks_season': row.picks_season,
            'divergence_7d_vs_season': div_7d,
            'divergence_14d_vs_season': div_14d,
            'regime': regime,
            'status': status,
            'days_in_current_regime': None,  # Populated by consecutive-day logic below
            'is_model_dependent': is_model_dep,
            'computed_at': now,
        })

    # Compute days_in_current_regime by checking prior days
    _fill_regime_duration(bq_client, target_date, results)

    logger.info(
        f"Computed signal health for {target_date}: "
        f"{len(results)} signals, "
        f"{sum(1 for r in results if r['regime'] == 'COLD')} COLD, "
        f"{sum(1 for r in results if r['regime'] == 'HOT')} HOT"
    )

    return results


def _fill_regime_duration(
    bq_client: bigquery.Client,
    target_date: str,
    results: List[Dict],
) -> None:
    """Fill days_in_current_regime by checking prior signal_health_daily rows."""
    if not results:
        return

    try:
        query = f"""
        SELECT signal_tag, regime, game_date
        FROM `{TABLE_ID}`
        WHERE game_date >= DATE_SUB(@target_date, INTERVAL 14 DAY)
          AND game_date < @target_date
        ORDER BY signal_tag, game_date DESC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            ]
        )
        prior_rows = bq_client.query(query, job_config=job_config).result(timeout=30)

        # Build map: signal_tag -> list of (date, regime) sorted by date desc
        prior_map: Dict[str, List] = {}
        for row in prior_rows:
            tag = row.signal_tag
            if tag not in prior_map:
                prior_map[tag] = []
            prior_map[tag].append(row.regime)

        for r in results:
            tag = r['signal_tag']
            current_regime = r['regime']
            streak = 1  # Today counts as day 1
            for prior_regime in prior_map.get(tag, []):
                if prior_regime == current_regime:
                    streak += 1
                else:
                    break
            r['days_in_current_regime'] = streak

    except Exception as e:
        logger.warning(f"Could not compute regime duration: {e}")
        for r in results:
            r['days_in_current_regime'] = 1


def write_health_rows(bq_client: bigquery.Client, rows: List[Dict]) -> int:
    """Write signal health rows to BigQuery using batch load."""
    if not rows:
        return 0

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
    )
    load_job = bq_client.load_table_from_json(rows, TABLE_ID, job_config=job_config)
    load_job.result(timeout=60)
    logger.info(f"Wrote {len(rows)} signal health rows to {TABLE_ID}")
    return len(rows)


def get_signal_health_summary(
    bq_client: bigquery.Client,
    target_date: str,
) -> Dict[str, Dict[str, Any]]:
    """Get signal health summary for JSON export.

    Returns:
        Dict keyed by signal_tag with hr_7d, hr_season, regime, status.
    """
    query = f"""
    SELECT signal_tag, hr_7d, hr_season, regime, status, is_model_dependent
    FROM `{TABLE_ID}`
    WHERE game_date = @target_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )

    try:
        rows = bq_client.query(query, job_config=job_config).result(timeout=30)
        return {
            row.signal_tag: {
                'hr_7d': row.hr_7d,
                'hr_season': row.hr_season,
                'regime': row.regime,
                'status': row.status,
                'is_model_dependent': row.is_model_dependent,
            }
            for row in rows
        }
    except Exception as e:
        logger.warning(f"Could not load signal health for {target_date}: {e}")
        return {}


def main():
    parser = argparse.ArgumentParser(description="Signal Health Computation")
    parser.add_argument('--date', help='Single date to compute (YYYY-MM-DD)')
    parser.add_argument('--backfill', action='store_true', help='Backfill a date range')
    parser.add_argument('--start', default='2026-01-09', help='Backfill start date')
    parser.add_argument('--end', default='2026-02-14', help='Backfill end date')
    parser.add_argument('--dry-run', action='store_true', help='Print without writing')
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    if args.date:
        dates = [args.date]
    elif args.backfill:
        # Get game dates in range
        dates_q = f"""
        SELECT DISTINCT game_date
        FROM `{PROJECT_ID}.nba_predictions.pick_signal_tags`
        WHERE game_date BETWEEN @start AND @end
        ORDER BY game_date
        """
        dates_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("start", "DATE", args.start),
            bigquery.ScalarQueryParameter("end", "DATE", args.end),
        ])
        dates = [str(row.game_date) for row in client.query(dates_q, job_config=dates_config).result()]
    else:
        print("Specify --date or --backfill")
        sys.exit(1)

    print(f"Computing signal health for {len(dates)} date(s)")
    total = 0

    for i, date_str in enumerate(dates):
        rows = compute_signal_health(client, date_str)
        cold = sum(1 for r in rows if r['regime'] == 'COLD')
        degrading = sum(1 for r in rows if r['status'] == 'DEGRADING')
        print(f"[{i+1}/{len(dates)}] {date_str}: {len(rows)} signals, {cold} COLD, {degrading} DEGRADING")

        if not args.dry_run and rows:
            write_health_rows(client, rows)
            total += len(rows)

    print(f"\nTotal rows written: {total}")
    if args.dry_run:
        print("(DRY RUN — nothing written)")


if __name__ == '__main__':
    main()
