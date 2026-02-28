#!/usr/bin/env python3
"""Post-Filter Evaluation — compare raw model HR vs post-filter HR.

Shows how much value the 16 negative filters add (or remove) for each model.
Helps close the experiment-to-production gap: experiments measure raw model HR,
but production depends on filtered HR.

Usage:
    PYTHONPATH=. python bin/post_filter_eval.py \
        --model-id catboost_v12_train1201_0215 \
        --start 2026-02-15 --end 2026-02-27
"""

import argparse
import logging
import sys
import os
from datetime import datetime, timedelta, date
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import bigquery
from ml.signals.registry import build_default_registry
from ml.signals.aggregator import BestBetsAggregator, ALGORITHM_VERSION
from ml.signals.combo_registry import load_combo_registry
from ml.signals.model_health import BREAKEVEN_HR
from ml.signals.signal_health import get_signal_health_summary
from ml.signals.supplemental_data import (
    query_model_health,
    query_predictions_with_supplements,
    query_games_vs_opponent,
)
from ml.signals.player_blacklist import compute_player_blacklist
from ml.signals.model_direction_affinity import compute_model_direction_affinities
from shared.config.cross_model_subsets import classify_system_id

logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


def query_raw_model_hr(bq_client: bigquery.Client, model_id: str,
                       start_date: str, end_date: str) -> Dict:
    """Query raw model performance from prediction_accuracy."""
    query = f"""
    SELECT
      COUNT(*) as total,
      COUNTIF(prediction_correct = TRUE) as wins,
      COUNTIF(prediction_correct = FALSE) as losses,
      ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / NULLIF(COUNT(*), 0), 1) as hr,
      COUNTIF(recommendation = 'OVER' AND prediction_correct = TRUE) as over_wins,
      COUNTIF(recommendation = 'OVER' AND prediction_correct = FALSE) as over_losses,
      COUNTIF(recommendation = 'UNDER' AND prediction_correct = TRUE) as under_wins,
      COUNTIF(recommendation = 'UNDER' AND prediction_correct = FALSE) as under_losses
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND system_id = '{model_id}'
      AND ABS(predicted_points - line_value) >= 3.0
      AND prediction_correct IS NOT NULL
      AND is_voided IS NOT TRUE
    """
    row = next(bq_client.query(query).result(timeout=60))
    return dict(row)


def simulate_filtered_picks(bq_client: bigquery.Client, model_id: str,
                             target_date: str, combo_registry: dict) -> Tuple[List, Dict]:
    """Run single-model predictions through the full filter pipeline."""
    family = classify_system_id(model_id)

    # Query predictions for this model
    predictions, supplemental_map = query_predictions_with_supplements(
        bq_client, target_date, system_id=model_id, multi_model=False
    )

    if not predictions:
        return [], {'total_candidates': 0, 'passed_filters': 0, 'rejected': {}}

    # Populate source model fields for filters that need them
    for pred in predictions:
        pred['source_model_id'] = model_id
        pred['source_model_family'] = family

    # Evaluate signals
    registry = build_default_registry()
    model_health = query_model_health(bq_client, system_id=model_id)
    hr_7d = model_health.get('hit_rate_7d_edge3')
    signal_results_map = {}

    for pred in predictions:
        supplements = supplemental_map.get(pred['player_lookup'], {})
        supplements['model_health'] = {'hit_rate_7d_edge3': hr_7d}

        all_results = []
        for signal in registry.all():
            result = signal.evaluate(pred, features=None, supplemental=supplements)
            all_results.append(result)

        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signal_results_map[key] = all_results

    # Compute blacklist and games_vs_opponent
    player_blacklist = set()
    try:
        player_blacklist, _ = compute_player_blacklist(bq_client, target_date)
    except Exception:
        pass

    try:
        gvo_map = query_games_vs_opponent(bq_client, target_date)
        for pred in predictions:
            opp = pred.get('opponent_team_abbr', '')
            pred['games_vs_opponent'] = gvo_map.get(
                (pred['player_lookup'], opp), 0
            )
    except Exception:
        pass

    # Compute model-direction affinities
    model_dir_blocks = set()
    try:
        _, model_dir_blocks, _ = compute_model_direction_affinities(
            bq_client, target_date, PROJECT_ID
        )
    except Exception:
        pass

    signal_health = get_signal_health_summary(bq_client, target_date)

    # Run aggregator
    aggregator = BestBetsAggregator(
        combo_registry=combo_registry,
        signal_health=signal_health,
        player_blacklist=player_blacklist,
        model_direction_blocks=model_dir_blocks,
    )
    top_picks, filter_summary = aggregator.aggregate(predictions, signal_results_map)

    return top_picks, filter_summary


def grade_picks(bq_client: bigquery.Client, picks: List[Dict],
                target_date: str, model_id: str) -> List[Dict]:
    """Look up actual results for filtered picks."""
    if not picks:
        return picks

    players = list(set(p['player_lookup'] for p in picks))
    placeholders = ','.join([f"'{p}'" for p in players])

    query = f"""
    SELECT player_lookup, actual_points, prediction_correct, recommendation
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date = '{target_date}'
      AND system_id = '{model_id}'
      AND player_lookup IN ({placeholders})
      AND is_voided IS NOT TRUE
    """
    rows = {r.player_lookup: r for r in bq_client.query(query).result(timeout=60)}

    for pick in picks:
        r = rows.get(pick['player_lookup'])
        if r:
            pick['actual_points'] = r.actual_points
            pick['prediction_correct'] = r.prediction_correct
        else:
            pick['actual_points'] = None
            pick['prediction_correct'] = None

    return picks


def main():
    parser = argparse.ArgumentParser(
        description='Compare raw model HR vs post-filter HR'
    )
    parser.add_argument('--model-id', required=True, help='Model system_id to evaluate')
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    bq_client = bigquery.Client(project=PROJECT_ID)
    combo_registry = load_combo_registry(bq_client=bq_client)

    start = datetime.strptime(args.start, '%Y-%m-%d').date()
    end = datetime.strptime(args.end, '%Y-%m-%d').date()
    dates = []
    d = start
    while d <= end:
        dates.append(d.strftime('%Y-%m-%d'))
        d += timedelta(days=1)

    print(f"\nPOST-FILTER EVALUATION: {args.model_id}")
    print(f"Period: {args.start} to {args.end} ({len(dates)} days)")
    print(f"Algorithm: {ALGORITHM_VERSION}")
    print(f"Family: {classify_system_id(args.model_id)}")
    print()

    # 1. Raw model HR
    raw = query_raw_model_hr(bq_client, args.model_id, args.start, args.end)
    raw_total = raw['total']
    raw_hr = raw['hr']
    raw_over_total = raw['over_wins'] + raw['over_losses']
    raw_over_hr = round(100.0 * raw['over_wins'] / raw_over_total, 1) if raw_over_total else 0
    raw_under_total = raw['under_wins'] + raw['under_losses']
    raw_under_hr = round(100.0 * raw['under_wins'] / raw_under_total, 1) if raw_under_total else 0

    # 2. Filtered model HR — simulate each date
    filtered_correct = 0
    filtered_wrong = 0
    filtered_ungraded = 0
    filtered_over_correct = 0
    filtered_over_wrong = 0
    filtered_under_correct = 0
    filtered_under_wrong = 0
    filter_totals = defaultdict(int)
    total_candidates = 0
    total_passed = 0

    for target_date in dates:
        picks, fs = simulate_filtered_picks(
            bq_client, args.model_id, target_date, combo_registry
        )
        picks = grade_picks(bq_client, picks, target_date, args.model_id)

        total_candidates += fs.get('total_candidates', 0)
        total_passed += fs.get('passed_filters', 0)

        for k, v in fs.get('rejected', {}).items():
            filter_totals[k] += v

        for p in picks:
            if p.get('prediction_correct') is True:
                filtered_correct += 1
                if p.get('recommendation') == 'OVER':
                    filtered_over_correct += 1
                else:
                    filtered_under_correct += 1
            elif p.get('prediction_correct') is False:
                filtered_wrong += 1
                if p.get('recommendation') == 'OVER':
                    filtered_over_wrong += 1
                else:
                    filtered_under_wrong += 1
            else:
                filtered_ungraded += 1

    filtered_graded = filtered_correct + filtered_wrong
    filtered_hr = round(100.0 * filtered_correct / filtered_graded, 1) if filtered_graded else 0
    filtered_over_graded = filtered_over_correct + filtered_over_wrong
    filtered_over_hr = round(100.0 * filtered_over_correct / filtered_over_graded, 1) if filtered_over_graded else 0
    filtered_under_graded = filtered_under_correct + filtered_under_wrong
    filtered_under_hr = round(100.0 * filtered_under_correct / filtered_under_graded, 1) if filtered_under_graded else 0

    pass_rate = round(100.0 * total_passed / total_candidates, 1) if total_candidates else 0
    delta = round(filtered_hr - (raw_hr or 0), 1)

    # 3. Display
    print(f"RAW MODEL (all edge 3+):     {raw_hr}% HR ({raw['wins']}/{raw_total})  "
          f"OVER {raw_over_hr}% (N={raw_over_total})  UNDER {raw_under_hr}% (N={raw_under_total})")
    print(f"POST-FILTER (16 filters):    {filtered_hr}% HR ({filtered_correct}/{filtered_graded})  "
          f"OVER {filtered_over_hr}% (N={filtered_over_graded})  UNDER {filtered_under_hr}% (N={filtered_under_graded})")

    if delta > 0:
        verdict = f"Filters IMPROVE this model by +{delta}pp"
    elif delta < 0:
        verdict = f"Filters HURT this model by {delta}pp"
    else:
        verdict = "Filters have no effect on HR"
    print(f"Verdict: {verdict} ({pass_rate}% pass rate)")

    if filtered_ungraded:
        print(f"Ungraded: {filtered_ungraded} picks (games not yet final)")

    # P&L comparison
    raw_pnl = raw['wins'] * 100 - raw['losses'] * 110 if raw_total else 0
    filtered_pnl = filtered_correct * 100 - filtered_wrong * 110 if filtered_graded else 0
    print(f"\nEst. P&L ($110 risk):  RAW ${raw_pnl:+,d}  |  FILTERED ${filtered_pnl:+,d}")

    # Filter rejection breakdown
    total_rejected = sum(filter_totals.values())
    if total_rejected:
        print(f"\nFilter Rejection Breakdown ({total_rejected} rejected):")
        for k, v in sorted(filter_totals.items(), key=lambda x: -x[1]):
            if v > 0:
                pct = round(100.0 * v / total_rejected, 1)
                print(f"  {k:30s} {v:5d}  ({pct}%)")


if __name__ == '__main__':
    main()
