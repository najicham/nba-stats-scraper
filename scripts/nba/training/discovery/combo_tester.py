"""Signal Combo Interaction Tester.

Tests 2-way and 3-way interactions of signal-like conditions.
Identifies synergistic combos where joint HR > max(individual HR).

Usage:
    PYTHONPATH=. python scripts/nba/training/discovery/combo_tester.py
    PYTHONPATH=. python scripts/nba/training/discovery/combo_tester.py --min-edge 3.0 --top-n 15

Session 466: Initial implementation.
"""

import argparse
import json
import logging
import time
from itertools import combinations
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import numpy as np
import pandas as pd

from scripts.nba.training.discovery.data_loader import DiscoveryDataset
from scripts.nba.training.discovery.stats_utils import (
    BASELINE_HR,
    MIN_N_TOTAL,
    MIN_N_PER_SEASON,
    benjamini_hochberg,
    compute_hypothesis_stats,
    cross_season_consistency,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path('results/signal_discovery')

# Minimum co-fire count for a combo to be tested
MIN_COMBO_N = 50


def define_signal_conditions(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """Define signal-like conditions as boolean masks on the DataFrame.

    Each condition returns a boolean Series (True where signal fires).
    Uses only pre-game features.
    """
    signals = {}

    # --- OVER signals ---
    if 'implied_team_total' in df.columns:
        signals['hse_over'] = (df['direction'] == 'OVER') & (df['implied_team_total'] >= 0.75)

    if 'opponent_pace' in df.columns:
        signals['fast_pace_over'] = (df['direction'] == 'OVER') & (df['opponent_pace'] >= 0.75)

    if 'three_pct_diff' in df.columns:
        signals['cold_3pt_over'] = (df['direction'] == 'OVER') & (df['three_pct_diff'] <= -0.15)
        signals['hot_3pt_under'] = (df['direction'] == 'UNDER') & (df['three_pct_diff'] >= 0.10)

    if 'rest_advantage' in df.columns:
        signals['rest_advantage_over'] = (df['direction'] == 'OVER') & (df['rest_advantage'] >= 0.7)
        signals['rest_advantage_under'] = (df['direction'] == 'UNDER') & (df['rest_advantage'] >= 0.7)

    if 'line_movement' in df.columns:
        signals['bp_rose_over'] = (df['direction'] == 'OVER') & (df['line_movement'] >= 0.5)
        signals['bp_dropped_under'] = (df['direction'] == 'UNDER') & (df['line_movement'] <= -0.5)
        signals['bp_dropped_heavy_under'] = (df['direction'] == 'UNDER') & (df['line_movement'] <= -1.0)

    if 'line_std' in df.columns:
        signals['book_disagree_over'] = (df['direction'] == 'OVER') & (df['line_std'] >= 1.0)
        signals['book_disagree_under'] = (df['direction'] == 'UNDER') & (df['line_std'] >= 1.0)

    if 'usage_rate_last_5' in df.columns:
        signals['high_usage_over'] = (df['direction'] == 'OVER') & (df['usage_rate_last_5'] >= 0.25)

    # --- UNDER signals ---
    if 'is_home' in df.columns:
        signals['home_under'] = (df['direction'] == 'UNDER') & (df['is_home'] == 1) & (df['line'] >= 15)

    if 'scoring_trend_slope' in df.columns:
        signals['downtrend_under'] = (df['direction'] == 'UNDER') & (
            df['scoring_trend_slope'].between(-0.03, -0.01)
        )

    if 'points_std_last_10' in df.columns:
        signals['volatile_under'] = (df['direction'] == 'UNDER') & (
            df['points_std_last_10'] >= 0.5
        ) & (df['line'] >= 18) & (df['line'] <= 25)

    if 'prop_line_delta' in df.columns:
        signals['line_drop_under'] = (df['direction'] == 'UNDER') & (df['prop_line_delta'] <= -2.0)
        signals['line_rise_over'] = (df['direction'] == 'OVER') & (df['prop_line_delta'] >= 1.0)

    if 'fg_pct_diff' in df.columns:
        signals['cold_fg_under_block'] = (df['direction'] == 'UNDER') & (df['fg_pct_diff'] <= -0.10)

    # --- Contextual ---
    if 'is_home' in df.columns:
        signals['away_under'] = (df['direction'] == 'UNDER') & (df['is_home'] == 0)

    if 'line' in df.columns:
        signals['star_line_under'] = (df['direction'] == 'UNDER') & (df['line'] >= 25)
        signals['low_line_over'] = (df['direction'] == 'OVER') & (df['line'] < 12)
        signals['mid_line_under'] = (df['direction'] == 'UNDER') & (df['line'].between(18, 25))

    if 'abs_edge' in df.columns:
        signals['high_edge'] = df['abs_edge'] >= 5.0
        signals['very_high_edge'] = df['abs_edge'] >= 7.0

    if 'spread_magnitude' in df.columns:
        signals['high_spread'] = df['spread_magnitude'] >= 0.5

    if 'fta_cv_last_10' in df.columns and 'fta_avg_last_10' in df.columns:
        signals['ft_volatile_under'] = (df['direction'] == 'UNDER') & (
            df['fta_cv_last_10'] >= 0.5
        ) & (df['fta_avg_last_10'] >= 5)

    if 'consecutive_games_below_avg' in df.columns:
        signals['cold_streak_over'] = (df['direction'] == 'OVER') & (
            df['consecutive_games_below_avg'] >= 0.5
        )

    return signals


def test_combos(
    df: pd.DataFrame,
    signals: Dict[str, pd.Series],
    combo_size: int = 2,
    min_n: int = MIN_COMBO_N,
) -> List[Dict]:
    """Test all N-way combinations of signals.

    Returns list of combo results.
    """
    results = []
    signal_names = list(signals.keys())
    total_combos = 0
    tested = 0

    for combo in combinations(signal_names, combo_size):
        total_combos += 1

        # Joint mask: all signals must fire
        joint_mask = signals[combo[0]]
        for sig in combo[1:]:
            joint_mask = joint_mask & signals[sig]

        joint_n = joint_mask.sum()
        if joint_n < min_n:
            continue

        subset = df[joint_mask]
        tested += 1

        # Joint stats
        joint_stats = compute_hypothesis_stats(
            subset,
            correct_col='correct',
            date_col='game_date',
            season_col='season',
            baseline=BASELINE_HR,
        )
        if joint_stats is None:
            continue

        # Individual HRs
        individual_hrs = {}
        for sig in combo:
            sig_subset = df[signals[sig]]
            if len(sig_subset) > 0:
                individual_hrs[sig] = sig_subset['correct'].mean()
            else:
                individual_hrs[sig] = 0.0

        max_individual_hr = max(individual_hrs.values())
        synergy_pp = (joint_stats['hr'] - max_individual_hr) * 100

        # Classify
        if synergy_pp >= 5.0 and joint_stats['consistency']['pass']:
            verdict = 'SYNERGISTIC'
        elif synergy_pp > 0 and joint_stats['consistency']['pass']:
            verdict = 'ADDITIVE'
        elif joint_stats['hr'] >= max_individual_hr:
            verdict = 'NEUTRAL'
        else:
            verdict = 'REDUNDANT'

        results.append({
            'combo_id': ' + '.join(combo),
            'combo_size': combo_size,
            'signals': list(combo),
            'direction': subset['direction'].mode().iloc[0] if len(subset) > 0 else 'MIXED',
            'joint_hr': round(joint_stats['hr'], 4),
            'joint_n': joint_stats['total_n'],
            'effect_pp': joint_stats['effect_pp'],
            'synergy_pp': round(synergy_pp, 1),
            'max_individual_hr': round(max_individual_hr, 4),
            'individual_hrs': {k: round(v, 4) for k, v in individual_hrs.items()},
            'p_value': joint_stats['p_value'],
            'bootstrap_ci': f"[{joint_stats['bootstrap_ci_lo']:.3f},{joint_stats['bootstrap_ci_hi']:.3f}]",
            'consistency': joint_stats['consistency'],
            'verdict': verdict,
        })

    logger.info(f"  {combo_size}-way: {total_combos} total, {tested} had N>={min_n}, {len(results)} passed stats")
    return results


def run_combo_test(
    dataset: DiscoveryDataset,
    min_edge: float = 3.0,
    top_n: int = 15,
) -> pd.DataFrame:
    """Run the full combo test."""
    df = dataset.df.copy()

    if min_edge > 0 and 'abs_edge' in df.columns:
        df = df[df['abs_edge'] >= min_edge]
        logger.info(f"Edge >= {min_edge}: {len(df)} rows")

    # Define signal conditions
    signals = define_signal_conditions(df)
    logger.info(f"Defined {len(signals)} signal conditions")

    # Log signal fire counts
    for name, mask in sorted(signals.items(), key=lambda x: -x[1].sum()):
        n = mask.sum()
        if n > 0:
            hr = df[mask]['correct'].mean()
            logger.info(f"  {name}: N={n}, HR={hr:.1%}")

    # Test 2-way combos
    all_results = []
    results_2way = test_combos(df, signals, combo_size=2, min_n=MIN_COMBO_N)
    all_results.extend(results_2way)

    # Test 3-way combos (only top signals by volume)
    top_signals = sorted(signals.keys(), key=lambda k: -signals[k].sum())[:top_n]
    top_signal_dict = {k: signals[k] for k in top_signals}
    results_3way = test_combos(df, top_signal_dict, combo_size=3, min_n=MIN_COMBO_N)
    all_results.extend(results_3way)

    if not all_results:
        logger.warning("No combos met minimum sample requirements")
        return pd.DataFrame()

    # Apply BH FDR
    p_values = np.array([r['p_value'] for r in all_results])
    rejected, adjusted_p = benjamini_hochberg(p_values, alpha=0.05)
    for i, result in enumerate(all_results):
        result['p_adjusted'] = round(float(adjusted_p[i]), 6)
        result['fdr_significant'] = bool(rejected[i])

    results_df = pd.DataFrame(all_results)

    # Sort: synergistic first, then by joint HR
    verdict_order = {'SYNERGISTIC': 0, 'ADDITIVE': 1, 'NEUTRAL': 2, 'REDUNDANT': 3}
    results_df['_sort'] = results_df['verdict'].map(verdict_order)
    results_df = results_df.sort_values(['_sort', 'joint_hr'], ascending=[True, False])
    results_df = results_df.drop(columns=['_sort'])

    return results_df


def print_combo_summary(results_df: pd.DataFrame):
    """Print combo test results."""
    print("\n" + "=" * 90)
    print("SIGNAL COMBO INTERACTION RESULTS")
    print("=" * 90)

    for verdict in ['SYNERGISTIC', 'ADDITIVE', 'NEUTRAL']:
        subset = results_df[results_df['verdict'] == verdict]
        if len(subset) == 0:
            continue

        print(f"\n{'─' * 90}")
        print(f"{verdict} COMBOS ({len(subset)})")
        print(f"{'─' * 90}")
        print(f"{'Combo':<55} {'Dir':<6} {'HR':>6} {'N':>5} {'Synergy':>8} {'MaxIndiv':>9} {'CI':>15}")
        print(f"{'─' * 55} {'─' * 5} {'─' * 6} {'─' * 5} {'─' * 8} {'─' * 9} {'─' * 15}")

        for _, r in subset.head(20).iterrows():
            print(f"{r['combo_id']:<55} {r['direction']:<6} {r['joint_hr']:>5.1%} "
                  f"{r['joint_n']:>5} {r['synergy_pp']:>+7.1f}pp {r['max_individual_hr']:>8.1%} "
                  f"{r['bootstrap_ci']:>15}")

    # Verdict distribution
    print(f"\n{'─' * 90}")
    print("VERDICT DISTRIBUTION")
    print(f"{'─' * 90}")
    for verdict, count in results_df['verdict'].value_counts().items():
        print(f"  {verdict:<25} {count:>5}")


def main():
    parser = argparse.ArgumentParser(description='Signal Combo Interaction Tester')
    parser.add_argument('--min-edge', type=float, default=3.0,
                        help='Minimum edge to include (default: 3.0)')
    parser.add_argument('--top-n', type=int, default=15,
                        help='Top N signals for 3-way combos (default: 15)')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format='%(asctime)s %(levelname)s %(message)s',
    )

    print("Loading dataset...")
    t0 = time.time()
    dataset = DiscoveryDataset(min_edge=0)

    print(f"\nRunning combo test (min_edge={args.min_edge}, top_n={args.top_n})...")
    results_df = run_combo_test(dataset, min_edge=args.min_edge, top_n=args.top_n)

    elapsed = time.time() - t0
    print(f"\nCombo test completed in {elapsed:.1f}s")

    if len(results_df) > 0:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        csv_path = OUTPUT_DIR / 'combo_test_results.csv'
        json_path = OUTPUT_DIR / 'combo_test_results.json'

        # Flatten for CSV
        flat = results_df.copy()
        flat['consistency_pass'] = flat['consistency'].apply(lambda x: x.get('pass', False) if isinstance(x, dict) else False)
        flat['seasons_consistent'] = flat['consistency'].apply(lambda x: x.get('seasons_consistent', 0) if isinstance(x, dict) else 0)
        flat = flat.drop(columns=['consistency', 'individual_hrs', 'signals'], errors='ignore')
        flat.to_csv(csv_path, index=False)

        json_results = results_df.to_dict(orient='records')
        with open(json_path, 'w') as f:
            json.dump(json_results, f, indent=2, default=str)

        print(f"Results saved to {csv_path}")
        print_combo_summary(results_df)
    else:
        print("No combos met minimum requirements")


if __name__ == '__main__':
    main()
