#!/usr/bin/env python3
"""Model Family Dashboard — per-model raw HR, best-bets HR, direction splits, effective weight.

Ad-hoc diagnostic showing how each model performs raw vs in best bets,
and what effective weight it receives in production selection.

Usage:
    PYTHONPATH=. python bin/model_family_dashboard.py
    PYTHONPATH=. python bin/model_family_dashboard.py --days 14
"""

import argparse
import logging
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import bigquery

logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


def main():
    parser = argparse.ArgumentParser(description='Model family performance dashboard')
    parser.add_argument('--days', type=int, default=21, help='Lookback days (default: 21)')
    parser.add_argument('--min-picks', type=int, default=5, help='Min graded picks to show (default: 5)')
    args = parser.parse_args()

    bq_client = bigquery.Client(project=PROJECT_ID)
    end_date = (date.today() - timedelta(days=1)).isoformat()
    start_date = (date.today() - timedelta(days=args.days)).isoformat()

    # Query 1: Raw model HR (all edge 3+ predictions)
    raw_query = f"""
    WITH raw_stats AS (
      SELECT
        system_id,
        COUNT(*) as raw_total,
        COUNTIF(prediction_correct = TRUE) as raw_wins,
        ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / NULLIF(COUNT(*), 0), 1) as raw_hr,
        COUNTIF(recommendation = 'OVER' AND prediction_correct IS NOT NULL) as over_total,
        COUNTIF(recommendation = 'OVER' AND prediction_correct = TRUE) as over_wins,
        COUNTIF(recommendation = 'UNDER' AND prediction_correct IS NOT NULL) as under_total,
        COUNTIF(recommendation = 'UNDER' AND prediction_correct = TRUE) as under_wins,
        ROUND(AVG(ABS(predicted_points - line_value)), 1) as avg_edge
      FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
      WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        AND ABS(predicted_points - line_value) >= 3.0
        AND prediction_correct IS NOT NULL
        AND is_voided IS NOT TRUE
      GROUP BY system_id
      HAVING COUNT(*) >= {args.min_picks}
    )
    SELECT * FROM raw_stats ORDER BY raw_hr DESC
    """

    # Query 2: Best bets HR (picks that passed filters)
    bb_query = f"""
    WITH bb_stats AS (
      SELECT
        bb.source_model_id as system_id,
        COUNT(*) as bb_total,
        COUNTIF(pa.prediction_correct = TRUE) as bb_wins,
        ROUND(100.0 * COUNTIF(pa.prediction_correct = TRUE) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as bb_hr,
        COUNTIF(bb.recommendation = 'OVER' AND pa.prediction_correct IS NOT NULL) as bb_over_total,
        COUNTIF(bb.recommendation = 'OVER' AND pa.prediction_correct = TRUE) as bb_over_wins,
        COUNTIF(bb.recommendation = 'UNDER' AND pa.prediction_correct IS NOT NULL) as bb_under_total,
        COUNTIF(bb.recommendation = 'UNDER' AND pa.prediction_correct = TRUE) as bb_under_wins
      FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks` bb
      LEFT JOIN `{PROJECT_ID}.nba_predictions.prediction_accuracy` pa
        ON bb.player_lookup = pa.player_lookup
        AND bb.game_date = pa.game_date
        AND bb.system_id = pa.system_id
        AND pa.is_voided IS NOT TRUE
      WHERE bb.game_date BETWEEN '{start_date}' AND '{end_date}'
        AND bb.source_model_id IS NOT NULL
      GROUP BY bb.source_model_id
    )
    SELECT * FROM bb_stats ORDER BY system_id
    """

    print(f"\nMODEL FAMILY DASHBOARD ({start_date} to {end_date})")
    print("=" * 130)

    # Execute queries
    raw_rows = {r.system_id: dict(r) for r in bq_client.query(raw_query).result(timeout=60)}
    bb_rows = {r.system_id: dict(r) for r in bq_client.query(bb_query).result(timeout=60)}

    all_models = sorted(set(raw_rows.keys()) | set(bb_rows.keys()))

    print(f"\n{'Model':<45s} {'Raw HR':>7s} {'N':>5s} {'BB HR':>7s} {'N':>5s} {'OVER':>7s} {'UNDER':>7s} {'AvgEdge':>7s} {'Wt':>5s}")
    print("-" * 130)

    for model in all_models:
        raw = raw_rows.get(model, {})
        bb = bb_rows.get(model, {})

        # Shorten model name
        short = model.replace('catboost_', '').replace('lgbm_', 'L:')
        if len(short) > 43:
            short = short[:40] + '...'

        raw_hr = f"{raw.get('raw_hr', 0):.1f}%" if raw.get('raw_hr') else 'N/A'
        raw_n = str(raw.get('raw_total', 0))
        bb_hr = f"{bb.get('bb_hr', 0):.1f}%" if bb.get('bb_hr') else 'N/A'
        bb_n = str(bb.get('bb_total', 0))

        # Direction splits (raw)
        over_t = raw.get('over_total', 0)
        over_hr = f"{100*raw.get('over_wins',0)/over_t:.0f}%" if over_t else 'N/A'
        under_t = raw.get('under_total', 0)
        under_hr = f"{100*raw.get('under_wins',0)/under_t:.0f}%" if under_t else 'N/A'

        avg_edge = f"{raw.get('avg_edge', 0):.1f}" if raw.get('avg_edge') else 'N/A'

        # Effective weight: min(1.0, hr_14d / 55.0)
        hr_14d = raw.get('raw_hr', 50.0) or 50.0
        weight = min(1.0, hr_14d / 55.0)
        wt_str = f"{weight:.2f}"

        print(f"  {short:<43s} {raw_hr:>7s} {raw_n:>5s} {bb_hr:>7s} {bb_n:>5s} {over_hr:>7s} {under_hr:>7s} {avg_edge:>7s} {wt_str:>5s}")

    # Summary
    print(f"\n  Total models: {len(all_models)}")
    profitable = [m for m in all_models if raw_rows.get(m, {}).get('raw_hr', 0) and raw_rows[m]['raw_hr'] >= 52.4]
    print(f"  Above breakeven (raw): {len(profitable)}/{len(all_models)}")
    bb_profitable = [m for m in all_models if bb_rows.get(m, {}).get('bb_hr', 0) and bb_rows[m]['bb_hr'] >= 52.4]
    print(f"  Above breakeven (best bets): {len(bb_profitable)}/{len([m for m in all_models if m in bb_rows])}")


if __name__ == '__main__':
    main()
