#!/usr/bin/env python3
"""Simulate any model through the full best bets pipeline.

Runs a model's predictions through filters + signals + ranking as if it were
the only model, bypassing per-player selection. This lets us evaluate models
that never win selection in production.

Usage:
    # Simulate a specific model over a date range
    python bin/simulate_best_bets.py --model catboost_v16_noveg_train1201_0215 \
        --start-date 2026-02-01 --end-date 2026-02-28

    # Compare two models side-by-side
    python bin/simulate_best_bets.py --model catboost_v16_noveg_train1201_0215 \
        --compare catboost_v12_noveg_train0110_0220 \
        --start-date 2026-02-01 --end-date 2026-02-28

    # Simulate the current multi-model production pipeline
    python bin/simulate_best_bets.py --multi-model \
        --start-date 2026-02-01 --end-date 2026-02-28

    # Output detailed per-pick breakdown
    python bin/simulate_best_bets.py --model catboost_v16_noveg_train1201_0215 \
        --start-date 2026-02-15 --end-date 2026-02-28 --verbose
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from google.cloud import bigquery

# Project imports
sys.path.insert(0, '.')
from shared.clients.bigquery_pool import get_bigquery_client
from shared.config.gcp_config import get_project_id
from ml.signals.registry import build_default_registry
from ml.signals.aggregator import BestBetsAggregator
from ml.signals.combo_registry import load_combo_registry, match_combo
from ml.signals.supplemental_data import (
    query_predictions_with_supplements,
    query_games_vs_opponent,
    query_model_health,
)
from ml.signals.player_blacklist import compute_player_blacklist
from ml.signals.model_direction_affinity import compute_model_direction_affinities
from ml.signals.model_profile_loader import load_model_profiles

logger = logging.getLogger(__name__)
PROJECT_ID = get_project_id()


def get_game_dates(bq_client: bigquery.Client, start_date: str, end_date: str) -> List[str]:
    """Get dates with games in the range."""
    query = f"""
    SELECT DISTINCT game_date
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date >= '{start_date}'
      AND game_date <= '{end_date}'
      AND prediction_correct IS NOT NULL
    ORDER BY game_date
    """
    rows = list(bq_client.query(query).result())
    return [str(r['game_date']) for r in rows]


def query_single_model_predictions(
    bq_client: bigquery.Client,
    target_date: str,
    model_id: str,
) -> List[Dict]:
    """Query predictions for a single model on a date, with supplemental data.

    Unlike production which uses per-player selection (highest edge wins),
    this returns ALL predictions from the specified model — allowing us to
    simulate what the model would produce if it were the only one.
    """
    # Use the existing function with system_id filter and multi_model=False
    # This bypasses the ROW_NUMBER per-player selection
    predictions, supplemental_map = query_predictions_with_supplements(
        bq_client, target_date, system_id=model_id, multi_model=False
    )

    # Enrich with supplemental data for signal evaluation
    for pred in predictions:
        player = pred.get('player_lookup', '')
        supp = supplemental_map.get(player, {})
        pred['_supplemental'] = supp

    return predictions, supplemental_map


def simulate_date(
    bq_client: bigquery.Client,
    target_date: str,
    model_id: Optional[str] = None,
    multi_model: bool = False,
    registry=None,
    combo_registry=None,
    historical: bool = False,
) -> Dict[str, Any]:
    """Simulate best bets pipeline for one date.

    Returns dict with picks, filter summary, and grading results.
    """
    # 1. Query predictions
    if multi_model:
        predictions, supplemental_map = query_predictions_with_supplements(
            bq_client, target_date, multi_model=True,
            skip_disabled_filter=historical,
        )
    else:
        predictions, supplemental_map = query_predictions_with_supplements(
            bq_client, target_date, system_id=model_id, multi_model=False,
            skip_disabled_filter=historical,
        )

    if not predictions:
        return {
            'date': target_date,
            'candidates': 0,
            'picks': [],
            'filter_summary': {'total_candidates': 0, 'rejected': {}},
            'grading': {'total': 0, 'wins': 0, 'losses': 0, 'hr': 0},
        }

    # 2. Enrich with games vs opponent
    try:
        gvo_map = query_games_vs_opponent(bq_client, target_date)
        for pred in predictions:
            key = (pred.get('player_lookup', ''), pred.get('opponent_team_abbr', ''))
            pred['games_vs_opponent'] = gvo_map.get(key, 0)
    except Exception as e:
        logger.warning(f"GVO query failed: {e}")

    # 3. Query model health
    model_health = query_model_health(bq_client)
    hr_7d = model_health.get('hit_rate_7d_edge3')

    # 4. Compute player blacklist
    try:
        player_blacklist, _ = compute_player_blacklist(bq_client, target_date)
    except Exception:
        player_blacklist = set()

    # 5. Model-direction affinity
    model_dir_blocks = set()
    model_dir_stats = {}
    try:
        _, model_dir_blocks, model_dir_stats = compute_model_direction_affinities(
            bq_client, target_date, PROJECT_ID
        )
    except Exception:
        pass

    # 6. Model profile store
    model_profile_store = None
    try:
        model_profile_store = load_model_profiles(bq_client, target_date)
    except Exception:
        pass

    # 7. Evaluate signals
    if registry is None:
        registry = build_default_registry()
    if combo_registry is None:
        combo_registry = load_combo_registry(bq_client=bq_client)

    signal_results_map = {}
    for pred in predictions:
        supplements = supplemental_map.get(pred.get('player_lookup', ''), {})
        supplements['model_health'] = {'hit_rate_7d_edge3': hr_7d}

        all_results = []
        for signal in registry.all():
            result = signal.evaluate(pred, features=None, supplemental=supplements)
            all_results.append(result)

        key = f"{pred.get('player_lookup', '')}::{pred.get('game_id', '')}"
        signal_results_map[key] = all_results

    # 8. Run aggregator
    aggregator = BestBetsAggregator(
        combo_registry=combo_registry,
        player_blacklist=player_blacklist,
        model_direction_blocks=model_dir_blocks,
        model_direction_affinity_stats=model_dir_stats,
        model_profile_store=model_profile_store,
    )

    picks, filter_summary = aggregator.aggregate(predictions, signal_results_map)

    # 9. Grade picks against actuals
    grading = grade_picks(bq_client, picks, target_date)

    return {
        'date': target_date,
        'candidates': len(predictions),
        'picks': picks,
        'filter_summary': filter_summary,
        'grading': grading,
    }


def grade_picks(bq_client: bigquery.Client, picks: List[Dict],
                target_date: str) -> Dict[str, Any]:
    """Grade simulated picks against actual outcomes."""
    if not picks:
        return {'total': 0, 'wins': 0, 'losses': 0, 'hr': 0, 'pnl': 0}

    # Build lookup of player+game → is_correct from prediction_accuracy
    player_lookups = [p.get('player_lookup', '') for p in picks]
    if not player_lookups:
        return {'total': 0, 'wins': 0, 'losses': 0, 'hr': 0, 'pnl': 0}

    # Query actual outcomes
    placeholders = ', '.join([f"'{pl}'" for pl in player_lookups])
    query = f"""
    SELECT player_lookup, game_id, recommendation, prediction_correct
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date = '{target_date}'
      AND player_lookup IN ({placeholders})
      AND prediction_correct IS NOT NULL
    """

    outcomes = {}
    try:
        for row in bq_client.query(query).result():
            key = f"{row['player_lookup']}::{row['game_id']}::{row['recommendation']}"
            outcomes[key] = row['prediction_correct']
    except Exception as e:
        logger.warning(f"Grading query failed: {e}")
        return {'total': len(picks), 'wins': 0, 'losses': 0, 'hr': 0, 'pnl': 0}

    wins = 0
    losses = 0
    graded_picks = []
    for pick in picks:
        key = f"{pick.get('player_lookup', '')}::{pick.get('game_id', '')}::{pick.get('recommendation', '')}"
        correct = outcomes.get(key)
        if correct is not None:
            pick['is_correct'] = correct
            if correct:
                wins += 1
            else:
                losses += 1
            graded_picks.append(pick)

    total = wins + losses
    hr = (wins / total * 100) if total > 0 else 0
    pnl = wins * 1.0 - losses * 1.1  # -110 odds

    return {
        'total': total,
        'wins': wins,
        'losses': losses,
        'hr': round(hr, 1),
        'pnl': round(pnl, 2),
        'picks': graded_picks,
    }


def simulate_range(
    bq_client: bigquery.Client,
    model_id: Optional[str],
    start_date: str,
    end_date: str,
    multi_model: bool = False,
    verbose: bool = False,
    historical: bool = False,
) -> Dict[str, Any]:
    """Simulate best bets pipeline over a date range."""
    game_dates = get_game_dates(bq_client, start_date, end_date)
    if not game_dates:
        print(f"No game dates found in {start_date} to {end_date}")
        return {}

    label = model_id or 'multi-model'
    print(f"\nSimulating {label} over {len(game_dates)} game days ({start_date} to {end_date})...")

    # Pre-load registries (reuse across dates)
    registry = build_default_registry()
    combo_registry = load_combo_registry(bq_client=bq_client)

    all_picks = []
    total_candidates = 0
    total_wins = 0
    total_losses = 0
    daily_results = []
    filter_totals = {}

    for i, game_date in enumerate(game_dates):
        result = simulate_date(
            bq_client, game_date, model_id=model_id,
            multi_model=multi_model,
            registry=registry, combo_registry=combo_registry,
            historical=historical,
        )

        daily_results.append(result)
        total_candidates += result['candidates']
        g = result['grading']
        total_wins += g['wins']
        total_losses += g['losses']

        # Accumulate filter rejections
        for filt, count in result['filter_summary'].get('rejected', {}).items():
            filter_totals[filt] = filter_totals.get(filt, 0) + count

        picks = result['grading'].get('picks', [])
        all_picks.extend(picks)

        if verbose and picks:
            print(f"\n  {game_date}: {g['wins']}/{g['total']} ({g['hr']}%) — {g['pnl']:+.2f}u")
            for pick in picks:
                status = 'W' if pick.get('is_correct') else 'L'
                edge = abs(pick.get('edge', 0))
                sc = pick.get('signal_count', 0)
                print(f"    [{status}] {pick.get('player_name', '?')} {pick.get('recommendation', '?')} "
                      f"edge={edge:.1f} SC={sc}")

        # Progress indicator
        if (i + 1) % 10 == 0:
            running_total = total_wins + total_losses
            running_hr = (total_wins / running_total * 100) if running_total > 0 else 0
            print(f"  ... {i+1}/{len(game_dates)} dates processed ({total_wins}/{running_total} = {running_hr:.1f}%)")

    # Summary
    total = total_wins + total_losses
    hr = (total_wins / total * 100) if total > 0 else 0
    pnl = total_wins * 1.0 - total_losses * 1.1

    # Direction breakdown
    over_picks = [p for p in all_picks if p.get('recommendation') == 'OVER']
    under_picks = [p for p in all_picks if p.get('recommendation') == 'UNDER']
    over_wins = sum(1 for p in over_picks if p.get('is_correct'))
    under_wins = sum(1 for p in under_picks if p.get('is_correct'))
    over_hr = (over_wins / len(over_picks) * 100) if over_picks else 0
    under_hr = (under_wins / len(under_picks) * 100) if under_picks else 0

    # Signal count breakdown
    sc_breakdown = {}
    for pick in all_picks:
        sc = pick.get('signal_count', 0)
        if sc not in sc_breakdown:
            sc_breakdown[sc] = {'total': 0, 'wins': 0}
        sc_breakdown[sc]['total'] += 1
        if pick.get('is_correct'):
            sc_breakdown[sc]['wins'] += 1

    # Edge band breakdown
    edge_breakdown = {}
    for pick in all_picks:
        edge = abs(pick.get('edge', 0))
        if edge >= 7:
            band = '7+'
        elif edge >= 5:
            band = '5-7'
        else:
            band = '3-5'
        if band not in edge_breakdown:
            edge_breakdown[band] = {'total': 0, 'wins': 0}
        edge_breakdown[band]['total'] += 1
        if pick.get('is_correct'):
            edge_breakdown[band]['wins'] += 1

    # Zero-pick days
    zero_pick_days = sum(1 for r in daily_results if r['grading']['total'] == 0)
    avg_daily_picks = total / len(game_dates) if game_dates else 0

    return {
        'model': label,
        'date_range': f"{start_date} to {end_date}",
        'game_days': len(game_dates),
        'total_candidates': total_candidates,
        'total_picks': total,
        'wins': total_wins,
        'losses': total_losses,
        'hr': round(hr, 1),
        'pnl': round(pnl, 2),
        'over': {'total': len(over_picks), 'wins': over_wins, 'hr': round(over_hr, 1)},
        'under': {'total': len(under_picks), 'wins': under_wins, 'hr': round(under_hr, 1)},
        'sc_breakdown': sc_breakdown,
        'edge_breakdown': edge_breakdown,
        'filter_totals': filter_totals,
        'zero_pick_days': zero_pick_days,
        'avg_daily_picks': round(avg_daily_picks, 2),
        'daily_results': daily_results,
    }


def print_results(results: Dict[str, Any]):
    """Print simulation results in a readable format."""
    print(f"\n{'='*70}")
    print(f"  SIMULATION RESULTS: {results['model']}")
    print(f"  {results['date_range']} ({results['game_days']} game days)")
    print(f"{'='*70}")
    print(f"  Total candidates:   {results['total_candidates']}")
    print(f"  Simulated BB picks: {results['total_picks']}")
    print(f"  Record:            {results['wins']}-{results['losses']} ({results['hr']}%)")
    print(f"  P&L (-110):        {results['pnl']:+.2f} units")
    print(f"  Zero-pick days:    {results['zero_pick_days']}/{results['game_days']}")
    print(f"  Avg daily picks:   {results['avg_daily_picks']}")

    print(f"\n  Direction:")
    o = results['over']
    u = results['under']
    print(f"    OVER:  {o['wins']}/{o['total']} ({o['hr']}%)")
    print(f"    UNDER: {u['wins']}/{u['total']} ({u['hr']}%)")

    print(f"\n  By Edge Band:")
    for band in ['3-5', '5-7', '7+']:
        if band in results['edge_breakdown']:
            eb = results['edge_breakdown'][band]
            eb_hr = (eb['wins'] / eb['total'] * 100) if eb['total'] > 0 else 0
            print(f"    {band:5s}: {eb['wins']}/{eb['total']} ({eb_hr:.1f}%)")

    print(f"\n  By Signal Count:")
    for sc in sorted(results['sc_breakdown'].keys()):
        sb = results['sc_breakdown'][sc]
        sb_hr = (sb['wins'] / sb['total'] * 100) if sb['total'] > 0 else 0
        print(f"    SC={sc}: {sb['wins']}/{sb['total']} ({sb_hr:.1f}%)")

    print(f"\n  Top Filter Rejections:")
    sorted_filters = sorted(results['filter_totals'].items(), key=lambda x: x[1], reverse=True)
    for filt, count in sorted_filters[:10]:
        print(f"    {filt:30s}: {count}")

    print(f"{'='*70}\n")


def print_comparison(results_a: Dict, results_b: Dict):
    """Print side-by-side comparison of two simulations."""
    print(f"\n{'='*70}")
    print(f"  COMPARISON")
    print(f"  {results_a['date_range']}")
    print(f"{'='*70}")
    print(f"  {'Metric':<25s} {'Model A':<20s} {'Model B':<20s}")
    print(f"  {'─'*65}")
    print(f"  {'Model':<25s} {results_a['model'][:18]:<20s} {results_b['model'][:18]:<20s}")
    print(f"  {'Picks':<25s} {results_a['total_picks']:<20d} {results_b['total_picks']:<20d}")
    print(f"  {'HR':<25s} {results_a['hr']:<20.1f} {results_b['hr']:<20.1f}")
    print(f"  {'P&L':<25s} {results_a['pnl']:<20.2f} {results_b['pnl']:<20.2f}")
    print(f"  {'OVER HR':<25s} {results_a['over']['hr']:<20.1f} {results_b['over']['hr']:<20.1f}")
    print(f"  {'UNDER HR':<25s} {results_a['under']['hr']:<20.1f} {results_b['under']['hr']:<20.1f}")
    print(f"  {'Zero-pick days':<25s} {results_a['zero_pick_days']:<20d} {results_b['zero_pick_days']:<20d}")
    print(f"  {'Avg daily picks':<25s} {results_a['avg_daily_picks']:<20.2f} {results_b['avg_daily_picks']:<20.2f}")

    # Statistical significance
    if results_a['total_picks'] >= 10 and results_b['total_picks'] >= 10:
        try:
            from bin.bootstrap_hr import two_proportion_z_test
            z = two_proportion_z_test(
                results_a['wins'], results_a['total_picks'],
                results_b['wins'], results_b['total_picks'],
            )
            diff = results_a['hr'] - results_b['hr']
            print(f"\n  {'HR difference':<25s} {diff:+.1f}pp")
            print(f"  {'Z-test p-value':<25s} {z['p_value']:.4f}")
            if z['p_value'] < 0.05:
                winner = 'A' if diff > 0 else 'B'
                print(f"  {'Verdict':<25s} Model {winner} significantly better (p < 0.05)")
            else:
                print(f"  {'Verdict':<25s} NOT significant (p = {z['p_value']:.3f})")
        except ImportError:
            pass

    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description='Simulate best bets pipeline for any model',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--model', type=str, help='Model system_id to simulate')
    parser.add_argument('--compare', type=str, help='Second model for comparison')
    parser.add_argument('--multi-model', action='store_true',
                       help='Simulate production multi-model pipeline')
    parser.add_argument('--start-date', type=str, required=True,
                       help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, required=True,
                       help='End date (YYYY-MM-DD)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Print per-pick details')
    parser.add_argument('--historical', action='store_true',
                       help='Include predictions from now-disabled models '
                       '(for evaluating historical periods)')

    args = parser.parse_args()

    if not args.model and not args.multi_model:
        parser.error('Either --model or --multi-model is required')

    logging.basicConfig(level=logging.WARNING)
    bq_client = get_bigquery_client(project_id=PROJECT_ID)

    # Run primary simulation
    results_a = simulate_range(
        bq_client, args.model, args.start_date, args.end_date,
        multi_model=args.multi_model, verbose=args.verbose,
        historical=args.historical,
    )

    if not results_a:
        return

    print_results(results_a)

    # Run comparison if requested
    if args.compare:
        results_b = simulate_range(
            bq_client, args.compare, args.start_date, args.end_date,
            verbose=args.verbose, historical=args.historical,
        )
        if results_b:
            print_results(results_b)
            print_comparison(results_a, results_b)


if __name__ == '__main__':
    main()
