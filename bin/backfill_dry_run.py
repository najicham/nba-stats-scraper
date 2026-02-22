#!/usr/bin/env python3
"""Backfill Dry Run — simulate what the consolidated best bets code would pick.

Runs the production SignalBestBetsExporter.generate_json() for historical dates
WITHOUT writing to BQ or GCS. Compares simulated picks against actual graded
results to compute what the hit rate would have been.

Usage:
    # Single date dry run
    PYTHONPATH=. python bin/backfill_dry_run.py --date 2026-02-19

    # Date range with summary
    PYTHONPATH=. python bin/backfill_dry_run.py --start 2026-02-01 --end 2026-02-19

    # Compare against existing best_bets subset
    PYTHONPATH=. python bin/backfill_dry_run.py --start 2026-01-01 --end 2026-02-19 --compare
"""

import argparse
import json
import logging
import sys
import os
from datetime import datetime, timedelta, date, timezone
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
from ml.signals.cross_model_scorer import CrossModelScorer
from ml.signals.pick_angle_builder import build_pick_angles
from ml.signals.ultra_bets import compute_ultra_live_hrs

logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


def simulate_date(bq_client: bigquery.Client, target_date: str,
                  combo_registry: dict) -> Dict:
    """Simulate what the consolidated code would pick for a single date.

    Returns dict with picks, filter_summary, and comparison data.
    """
    # 1. Query predictions (multi_model=True, same as production)
    predictions, supplemental_map = query_predictions_with_supplements(
        bq_client, target_date, multi_model=True
    )

    if not predictions:
        return {
            'date': target_date,
            'n_predictions': 0,
            'picks': [],
            'filter_summary': {'total_candidates': 0, 'passed_filters': 0, 'rejected': {}},
        }

    # 2. Evaluate signals on predictions
    registry = build_default_registry()
    model_health = query_model_health(bq_client)
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

    # 3. Compute blacklist and games_vs_opponent
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

    # 4. Get signal health
    signal_health = get_signal_health_summary(bq_client, target_date)

    # 5. Run aggregator (same as production)
    aggregator = BestBetsAggregator(
        combo_registry=combo_registry,
        signal_health=signal_health,
        player_blacklist=player_blacklist,
    )
    top_picks, filter_summary = aggregator.aggregate(predictions, signal_results_map)

    # Build pick angles (was missing — caused empty angles on backfill writes)
    cross_model_factors = {}
    try:
        scorer = CrossModelScorer()
        cross_model_factors = scorer.compute_factors(bq_client, target_date, PROJECT_ID)
    except Exception:
        pass

    for pick in top_picks:
        key = f"{pick['player_lookup']}::{pick['game_id']}"
        pick['pick_angles'] = build_pick_angles(
            pick, signal_results_map.get(key, []), cross_model_factors.get(key, {}),
        )

    return {
        'date': target_date,
        'n_predictions': len(predictions),
        'picks': top_picks,
        'filter_summary': filter_summary,
    }


def grade_picks(bq_client: bigquery.Client, picks: List[Dict],
                target_date: str) -> List[Dict]:
    """Look up actual results for simulated picks."""
    if not picks:
        return picks

    players = list(set(p['player_lookup'] for p in picks))
    placeholders = ','.join([f"'{p}'" for p in players])

    query = f"""
    SELECT player_lookup, system_id, actual_points, prediction_correct,
           recommendation, ROUND(ABS(predicted_points - line_value), 1) as edge
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date = '{target_date}'
      AND player_lookup IN ({placeholders})
      AND is_voided = FALSE
    """
    rows = {(r.player_lookup, r.system_id): r
            for r in bq_client.query(query).result(timeout=60)}

    for pick in picks:
        key = (pick['player_lookup'], pick.get('system_id', ''))
        if key in rows:
            r = rows[key]
            pick['actual_points'] = r.actual_points
            pick['prediction_correct'] = r.prediction_correct
        else:
            # Try matching by player only (may match different system_id)
            player_rows = [v for k, v in rows.items() if k[0] == pick['player_lookup']]
            if player_rows:
                r = player_rows[0]
                pick['actual_points'] = r.actual_points
                pick['prediction_correct'] = r.prediction_correct
            else:
                pick['actual_points'] = None
                pick['prediction_correct'] = None

    return picks


def get_existing_best_bets(bq_client: bigquery.Client,
                           target_date: str) -> List[Dict]:
    """Get existing best_bets subset picks for comparison."""
    query = f"""
    SELECT DISTINCT player_lookup, recommendation, ROUND(edge, 1) as edge,
           system_id
    FROM `{PROJECT_ID}.nba_predictions.current_subset_picks`
    WHERE game_date = '{target_date}' AND subset_id = 'best_bets'
    """
    return [dict(r) for r in bq_client.query(query).result(timeout=60)]


def print_date_result(result: Dict, existing: List[Dict] = None,
                      compare: bool = False):
    """Print results for a single date."""
    d = result['date']
    picks = result['picks']
    fs = result['filter_summary']

    correct = sum(1 for p in picks if p.get('prediction_correct') is True)
    wrong = sum(1 for p in picks if p.get('prediction_correct') is False)
    graded = correct + wrong
    ungraded = len(picks) - graded

    hr = f"{100*correct/graded:.0f}%" if graded else "N/A"

    # Compact line for multi-date runs
    rejected_str = ', '.join(f"{k}={v}" for k, v in fs.get('rejected', {}).items() if v > 0)
    print(f"\n{'='*70}")
    print(f"  {d}  |  {result['n_predictions']} preds → {fs['passed_filters']} passed → {len(picks)} picks  |  {correct}-{wrong} ({hr})")
    if rejected_str:
        print(f"  Filters: {rejected_str}")

    if picks:
        for p in picks:
            actual = p.get('actual_points', '?')
            mark = '✓' if p.get('prediction_correct') else ('✗' if p.get('prediction_correct') is False else '?')
            sys_id = p.get('system_id', '?')
            # Shorten model name
            short_model = sys_id.replace('catboost_', '').replace('_train', 'T').replace('_noveg', '')[:20]
            print(f"    {mark} {p['player_lookup']:25s} {p.get('recommendation','?'):5s} "
                  f"edge={abs(p.get('edge') or p.get('composite_score') or 0):5.1f} "
                  f"actual={actual} model={short_model}")

    if compare and existing:
        existing_players = set(e['player_lookup'] for e in existing)
        new_players = set(p['player_lookup'] for p in picks)

        added = new_players - existing_players
        removed = existing_players - new_players
        kept = new_players & existing_players

        if added or removed:
            print(f"  vs OLD: kept={len(kept)}, added={len(added)}, removed={len(removed)}")
            if removed:
                print(f"    Removed: {', '.join(sorted(removed))}")
            if added:
                print(f"    Added:   {', '.join(sorted(added))}")


def write_picks_to_bigquery(bq_client: bigquery.Client, target_date: str,
                            picks: List[Dict]) -> int:
    """Write aggregator picks to signal_best_bets_picks with DELETE-before-INSERT.

    Returns number of rows written.
    """
    table_ref = f'{PROJECT_ID}.nba_predictions.signal_best_bets_picks'

    # Delete existing rows for this date
    try:
        delete_query = f"""
        DELETE FROM `{table_ref}`
        WHERE game_date = '{target_date}'
        """
        job = bq_client.query(delete_query)
        job.result(timeout=30)
        deleted = job.num_dml_affected_rows or 0
        if deleted > 0:
            logger.info(f"Deleted {deleted} existing rows for {target_date}")
    except Exception as e:
        logger.warning(f"Failed to delete existing rows for {target_date}: {e}")

    if not picks:
        return 0

    rows = []
    for pick in picks:
        rows.append({
            'player_lookup': pick['player_lookup'],
            'game_id': pick.get('game_id', ''),
            'game_date': target_date,
            'system_id': pick.get('system_id') or pick.get('source_model_id') or 'catboost_v9',
            'player_name': pick.get('player_name', ''),
            'team_abbr': pick.get('team_abbr', ''),
            'opponent_team_abbr': pick.get('opponent_team_abbr', ''),
            'predicted_points': pick.get('predicted_points'),
            'line_value': pick.get('line_value'),
            'recommendation': pick.get('recommendation', ''),
            'edge': round(float(abs(pick.get('edge') or 0)), 1),
            'confidence_score': round(min(float(pick.get('confidence_score') or 0), 9.999), 3),
            'signal_tags': pick.get('signal_tags', []),
            'signal_count': pick.get('signal_count', 0),
            'composite_score': pick.get('composite_score'),
            'matched_combo_id': pick.get('matched_combo_id'),
            'combo_classification': pick.get('combo_classification'),
            'combo_hit_rate': pick.get('combo_hit_rate'),
            'warning_tags': pick.get('warning_tags', []),
            'rank': pick.get('rank'),
            'model_agreement_count': pick.get('model_agreement_count', 0),
            'agreeing_model_ids': pick.get('agreeing_model_ids', []),
            'feature_set_diversity': pick.get('feature_set_diversity', 0),
            'consensus_bonus': pick.get('consensus_bonus', 0),
            'quantile_consensus_under': pick.get('quantile_consensus_under', False),
            'pick_angles': pick.get('pick_angles', []),
            'qualifying_subsets': '[]',
            'qualifying_subset_count': pick.get('qualifying_subset_count', 0),
            'algorithm_version': pick.get('algorithm_version', ALGORITHM_VERSION),
            'source_model_id': pick.get('source_model_id'),
            'source_model_family': pick.get('source_model_family'),
            'n_models_eligible': pick.get('n_models_eligible'),
            'champion_edge': (
                round(float(pick['champion_edge']), 1)
                if pick.get('champion_edge') is not None else None
            ),
            'direction_conflict': pick.get('direction_conflict'),
            # Ultra Bets (Session 326)
            'ultra_tier': pick.get('ultra_tier', False),
            'ultra_criteria': json.dumps(pick.get('ultra_criteria', [])),
            'created_at': datetime.now(timezone.utc).isoformat(),
        })

    try:
        from google.cloud.bigquery import LoadJobConfig, WriteDisposition, CreateDisposition
        job_config = LoadJobConfig(
            write_disposition=WriteDisposition.WRITE_APPEND,
            create_disposition=CreateDisposition.CREATE_NEVER,
        )
        load_job = bq_client.load_table_from_json(rows, table_ref, job_config=job_config)
        load_job.result(timeout=60)
        return len(rows)
    except Exception as e:
        logger.error(f"Failed to write picks for {target_date}: {e}")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description='Simulate consolidated best bets for historical dates'
    )
    parser.add_argument('--date', type=str, help='Single date (YYYY-MM-DD)')
    parser.add_argument('--start', type=str, help='Start date for range')
    parser.add_argument('--end', type=str, help='End date for range')
    parser.add_argument('--compare', action='store_true',
                        help='Compare against existing best_bets subset')
    parser.add_argument('--write', action='store_true',
                        help='Write picks to signal_best_bets_picks (DELETE old + INSERT new)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show debug logging')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    if args.date:
        dates = [args.date]
    elif args.start and args.end:
        start = datetime.strptime(args.start, '%Y-%m-%d').date()
        end = datetime.strptime(args.end, '%Y-%m-%d').date()
        dates = []
        d = start
        while d <= end:
            dates.append(d.strftime('%Y-%m-%d'))
            d += timedelta(days=1)
    else:
        parser.error('Provide --date or --start/--end')

    bq_client = bigquery.Client(project=PROJECT_ID)
    combo_registry = load_combo_registry(bq_client=bq_client)

    print(f"Backfill Dry Run — Algorithm: {ALGORITHM_VERSION}")
    print(f"Dates: {dates[0]} to {dates[-1]} ({len(dates)} days)")
    print(f"Combo registry: {len(combo_registry)} entries "
          f"(0 ANTI_PATTERN)")

    # Accumulators for summary
    total_picks = 0
    total_correct = 0
    total_wrong = 0
    total_ungraded = 0
    daily_results = []
    filter_totals = defaultdict(int)

    total_written = 0

    for target_date in dates:
        result = simulate_date(bq_client, target_date, combo_registry)
        picks = grade_picks(bq_client, result['picks'], target_date)

        existing = None
        if args.compare:
            existing = get_existing_best_bets(bq_client, target_date)

        print_date_result(result, existing, args.compare)

        if args.write:
            # Enrich ultra criteria with live HRs before writing to BQ
            try:
                ultra_live = compute_ultra_live_hrs(bq_client, PROJECT_ID)
                for pick in result['picks']:
                    for crit in pick.get('ultra_criteria', []):
                        live = ultra_live.get(crit['id'], {})
                        crit['live_hr'] = live.get('live_hr')
                        crit['live_n'] = live.get('live_n', 0)
            except Exception:
                pass
            written = write_picks_to_bigquery(bq_client, target_date, result['picks'])
            total_written += written

        correct = sum(1 for p in picks if p.get('prediction_correct') is True)
        wrong = sum(1 for p in picks if p.get('prediction_correct') is False)
        graded = correct + wrong
        ungraded = len(picks) - graded

        total_picks += len(picks)
        total_correct += correct
        total_wrong += wrong
        total_ungraded += ungraded
        daily_results.append({
            'date': target_date,
            'picks': len(picks),
            'correct': correct,
            'wrong': wrong,
        })

        for k, v in result['filter_summary'].get('rejected', {}).items():
            filter_totals[k] += v

    # Print summary
    total_graded = total_correct + total_wrong
    hr = f"{100*total_correct/total_graded:.1f}%" if total_graded else "N/A"

    print(f"\n{'='*70}")
    mode = "BACKFILL" if args.write else "DRY RUN"
    print(f"SUMMARY — {mode} — {len(dates)} days, {ALGORITHM_VERSION}")
    print(f"{'='*70}")
    if args.write:
        print(f"  Wrote {total_written} picks to signal_best_bets_picks")
    print(f"  Total picks:  {total_picks}")
    print(f"  Graded:       {total_graded} ({total_correct}W - {total_wrong}L)")
    print(f"  Hit Rate:     {hr}")
    print(f"  Ungraded:     {total_ungraded}")
    if total_graded:
        pnl = total_correct * 100 - total_wrong * 110
        print(f"  Est. P&L:     ${pnl:+,d} ($110 risk / $100 win)")

    if filter_totals:
        print(f"\n  Filter rejection totals:")
        for k, v in sorted(filter_totals.items(), key=lambda x: -x[1]):
            if v > 0:
                print(f"    {k:25s} {v:6d}")

    # Weekly breakdown
    if len(daily_results) > 7:
        print(f"\n  Weekly breakdown:")
        week_start = None
        week_c, week_w = 0, 0
        for dr in daily_results:
            d = datetime.strptime(dr['date'], '%Y-%m-%d').date()
            if week_start is None or (d - week_start).days >= 7:
                if week_start is not None and (week_c + week_w) > 0:
                    whr = f"{100*week_c/(week_c+week_w):.0f}%"
                    print(f"    {week_start} — {week_c}W-{week_w}L ({whr})")
                week_start = d
                week_c, week_w = 0, 0
            week_c += dr['correct']
            week_w += dr['wrong']
        if week_start and (week_c + week_w) > 0:
            whr = f"{100*week_c/(week_c+week_w):.0f}%"
            print(f"    {week_start} — {week_c}W-{week_w}L ({whr})")


if __name__ == '__main__':
    main()
