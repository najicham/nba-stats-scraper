"""Systematic Feature/Filter Scanner for Signal Discovery.

Scans every available feature × threshold × direction combination
and tests whether it's a profitable signal or destructive filter.

Uses 5-layer validation:
1. Binomial test vs 51.5% baseline + BH FDR
2. Cross-season consistency (3/4 seasons)
3. Effect size gate (≥2pp)
4. Edge stratification
5. Block bootstrap by game-date

Usage:
    PYTHONPATH=. python scripts/nba/training/discovery/feature_scanner.py
    PYTHONPATH=. python scripts/nba/training/discovery/feature_scanner.py --min-edge 3.0
    PYTHONPATH=. python scripts/nba/training/discovery/feature_scanner.py --direction UNDER --verbose

Session 466: Initial implementation.
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from scripts.nba.training.discovery.data_loader import DiscoveryDataset
from scripts.nba.training.discovery.stats_utils import (
    BASELINE_HR,
    MIN_N_TOTAL,
    MIN_N_PER_SEASON,
    benjamini_hochberg,
    compute_hypothesis_stats,
    classify_effect,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path('results/signal_discovery')
CHECKPOINT_FILE = OUTPUT_DIR / 'scan_checkpoint.json'

# ============================================================================
# ALREADY TESTED — signals/filters from aggregator.py
# Tag these so the scanner highlights genuinely NEW discoveries
# ============================================================================
ALREADY_TESTED = {
    # Active signals
    'hse_over', 'fast_pace_over', 'b2b_boost_over', 'cold_streak_over',
    'rest_advantage_2d', 'self_creation_over', '3pt_bounce',
    'line_rising_over', 'low_line_over', 'q4_scorer_over',
    'book_disagreement', 'hot_3pt_under', 'cold_3pt_over',
    'line_drifted_down_under', 'home_under', 'bench_under',
    'starter_under', 'volatile_starter_under', 'downtrend_under',
    'sharp_line_drop_under', 'combo_3way', 'combo_he_ms',
    # Active filters
    'cold_fg_under', 'cold_3pt_under', 'high_spread_over',
    'med_usage_under', 'prediction_sanity', 'under_after_streak',
    'familiar_matchup', 'b2b_under', 'ft_variance_under',
    'opponent_depleted_under', 'q4_scorer_under_block',
    # Shadow signals
    'ft_anomaly_under', 'slow_pace_under', 'star_line_under',
    'sharp_consensus_under', 'projection_consensus_over',
    'hot_form_over', 'consistent_scorer_over', 'usage_surge_over',
    'scoring_momentum_over', 'career_matchup_over',
    'mean_reversion_under', 'sharp_book_lean_over',
    'starter_away_overtrend_under', 'over_streak_reversion_under',
    # Removed/dead
    'b2b_fatigue_under', 'prop_line_drop_over', 'dual_agree',
    'hot_streak_2', 'hot_streak_3', 'cold_continuation_2',
}


# ============================================================================
# HYPOTHESIS GENERATORS
# ============================================================================

def generate_percentile_hypotheses(
    df: pd.DataFrame,
    feature_cols: List[str],
    directions: List[str],
    percentiles: List[int] = [10, 25, 75, 90],
) -> List[Dict]:
    """Generate hypotheses: feature above/below percentile × direction."""
    hypotheses = []

    for col in feature_cols:
        if col not in df.columns:
            continue
        series = df[col].dropna()
        if len(series) < 100:
            continue

        pct_values = {p: np.percentile(series, p) for p in percentiles}

        for pct, threshold in pct_values.items():
            for direction in directions:
                if pct >= 75:
                    # High value: feature >= threshold
                    hyp_id = f"{col}_gte_p{pct}_{direction}"
                    hypotheses.append({
                        'id': hyp_id,
                        'feature': col,
                        'condition': f'>= p{pct}',
                        'threshold': round(threshold, 4),
                        'direction': direction,
                        'filter_fn': lambda df, c=col, t=threshold, d=direction: (
                            (df[c] >= t) & (df['direction'] == d)
                        ),
                    })
                else:
                    # Low value: feature <= threshold
                    hyp_id = f"{col}_lte_p{pct}_{direction}"
                    hypotheses.append({
                        'id': hyp_id,
                        'feature': col,
                        'condition': f'<= p{pct}',
                        'threshold': round(threshold, 4),
                        'direction': direction,
                        'filter_fn': lambda df, c=col, t=threshold, d=direction: (
                            (df[c] <= t) & (df['direction'] == d)
                        ),
                    })

    return hypotheses


def generate_deviation_hypotheses(
    df: pd.DataFrame,
    directions: List[str],
) -> List[Dict]:
    """Generate deviation hypotheses: shooting/scoring deviations from average."""
    hypotheses = []

    # Shooting deviation features (pre-game safe)
    deviation_features = [
        ('fg_pct_diff', 'FG% last3 vs season'),
        ('three_pct_diff', '3PT% last3 vs season'),
    ]

    thresholds = [
        (-0.15, 'cold_severe'),
        (-0.10, 'cold'),
        (-0.05, 'cold_mild'),
        (0.05, 'hot_mild'),
        (0.10, 'hot'),
        (0.15, 'hot_severe'),
    ]

    for col, desc in deviation_features:
        if col not in df.columns:
            continue
        for thresh, label in thresholds:
            for direction in directions:
                if thresh > 0:
                    hyp_id = f"{col}_{label}_{direction}"
                    hypotheses.append({
                        'id': hyp_id,
                        'feature': col,
                        'condition': f'>= {thresh} ({desc} {label})',
                        'threshold': thresh,
                        'direction': direction,
                        'filter_fn': lambda df, c=col, t=thresh, d=direction: (
                            (df[c] >= t) & (df['direction'] == d)
                        ),
                    })
                else:
                    hyp_id = f"{col}_{label}_{direction}"
                    hypotheses.append({
                        'id': hyp_id,
                        'feature': col,
                        'condition': f'<= {thresh} ({desc} {label})',
                        'threshold': thresh,
                        'direction': direction,
                        'filter_fn': lambda df, c=col, t=thresh, d=direction: (
                            (df[c] <= t) & (df['direction'] == d)
                        ),
                    })

    return hypotheses


def generate_contextual_hypotheses(
    df: pd.DataFrame,
    directions: List[str],
) -> List[Dict]:
    """Generate contextual hypotheses: B2B, home/away, rest, spread, etc."""
    hypotheses = []

    # Back-to-back
    if 'is_b2b' in df.columns:
        for direction in directions:
            hypotheses.append({
                'id': f'b2b_{direction}',
                'feature': 'is_b2b',
                'condition': '== 1 (back-to-back)',
                'threshold': 1,
                'direction': direction,
                'filter_fn': lambda df, d=direction: (
                    (df['is_b2b'] == 1) & (df['direction'] == d)
                ),
            })

    # Home/Away
    if 'is_home' in df.columns:
        for direction in directions:
            for home_val, label in [(1, 'home'), (0, 'away')]:
                hypotheses.append({
                    'id': f'{label}_{direction}',
                    'feature': 'is_home',
                    'condition': f'== {home_val} ({label})',
                    'threshold': home_val,
                    'direction': direction,
                    'filter_fn': lambda df, h=home_val, d=direction: (
                        (df['is_home'] == h) & (df['direction'] == d)
                    ),
                })

    # Day of week
    if 'day_of_week' in df.columns:
        dow_names = {0: 'Mon', 1: 'Tue', 2: 'Wed', 3: 'Thu', 4: 'Fri', 5: 'Sat', 6: 'Sun'}
        for dow, name in dow_names.items():
            for direction in directions:
                hypotheses.append({
                    'id': f'dow_{name}_{direction}',
                    'feature': 'day_of_week',
                    'condition': f'== {dow} ({name})',
                    'threshold': dow,
                    'direction': direction,
                    'filter_fn': lambda df, w=dow, d=direction: (
                        (df['day_of_week'] == w) & (df['direction'] == d)
                    ),
                })

    # Line range buckets
    if 'line' in df.columns:
        line_buckets = [(0, 12, 'low_line'), (12, 20, 'mid_line'),
                        (20, 28, 'high_line'), (28, 100, 'elite_line')]
        for lo, hi, label in line_buckets:
            for direction in directions:
                hypotheses.append({
                    'id': f'{label}_{direction}',
                    'feature': 'line',
                    'condition': f'[{lo}, {hi}) ({label})',
                    'threshold': f'{lo}-{hi}',
                    'direction': direction,
                    'filter_fn': lambda df, l=lo, h=hi, d=direction: (
                        (df['line'] >= l) & (df['line'] < h) & (df['direction'] == d)
                    ),
                })

    # Spread magnitude
    if 'spread_magnitude' in df.columns:
        for threshold in [0.3, 0.5, 0.7]:
            for direction in directions:
                hypotheses.append({
                    'id': f'spread_gte_{threshold}_{direction}',
                    'feature': 'spread_magnitude',
                    'condition': f'>= {threshold} (normalized)',
                    'threshold': threshold,
                    'direction': direction,
                    'filter_fn': lambda df, t=threshold, d=direction: (
                        (df['spread_magnitude'] >= t) & (df['direction'] == d)
                    ),
                })

    # Neg PM streak
    if 'neg_pm_streak' in df.columns:
        for streak_val in [2, 3]:
            for direction in directions:
                hypotheses.append({
                    'id': f'neg_pm_streak_{streak_val}_{direction}',
                    'feature': 'neg_pm_streak',
                    'condition': f'>= {streak_val}',
                    'threshold': streak_val,
                    'direction': direction,
                    'filter_fn': lambda df, s=streak_val, d=direction: (
                        (df['neg_pm_streak'] >= s) & (df['direction'] == d)
                    ),
                })

    # FTA patterns (pre-game safe: uses last_10 rolling)
    if 'fta_cv_last_10' in df.columns and 'fta_avg_last_10' in df.columns:
        for cv_thresh in [0.4, 0.5, 0.6]:
            for fta_thresh in [3, 5]:
                for direction in directions:
                    hypotheses.append({
                        'id': f'fta_cv_{cv_thresh}_fta_{fta_thresh}_{direction}',
                        'feature': 'fta_cv_last_10',
                        'condition': f'cv >= {cv_thresh} AND fta >= {fta_thresh}',
                        'threshold': f'cv={cv_thresh},fta={fta_thresh}',
                        'direction': direction,
                        'filter_fn': lambda df, cv=cv_thresh, ft=fta_thresh, d=direction: (
                            (df['fta_cv_last_10'] >= cv) &
                            (df['fta_avg_last_10'] >= ft) &
                            (df['direction'] == d)
                        ),
                    })

    # Usage rate buckets
    if 'usage_rate_last_5' in df.columns:
        usage_buckets = [(0, 0.15, 'bench_usage'), (0.15, 0.22, 'role_usage'),
                         (0.22, 0.28, 'starter_usage'), (0.28, 1.0, 'star_usage')]
        for lo, hi, label in usage_buckets:
            for direction in directions:
                hypotheses.append({
                    'id': f'{label}_{direction}',
                    'feature': 'usage_rate_last_5',
                    'condition': f'[{lo}, {hi}) ({label})',
                    'threshold': f'{lo}-{hi}',
                    'direction': direction,
                    'filter_fn': lambda df, l=lo, h=hi, d=direction: (
                        (df['usage_rate_last_5'] >= l) &
                        (df['usage_rate_last_5'] < h) &
                        (df['direction'] == d)
                    ),
                })

    # BettingPros line movement
    if 'line_movement' in df.columns:
        bp_thresholds = [
            (-1.0, None, 'bp_dropped_heavy'),
            (-0.5, -0.1, 'bp_drifted_down'),
            (0.1, 0.5, 'bp_drifted_up'),
            (0.5, None, 'bp_rose'),
            (1.0, None, 'bp_rose_heavy'),
        ]
        for lo, hi, label in bp_thresholds:
            for direction in directions:
                if hi is not None:
                    hypotheses.append({
                        'id': f'{label}_{direction}',
                        'feature': 'line_movement',
                        'condition': f'[{lo}, {hi})',
                        'threshold': f'{lo} to {hi}',
                        'direction': direction,
                        'filter_fn': lambda df, l=lo, h=hi, d=direction: (
                            (df['line_movement'] >= l) &
                            (df['line_movement'] < h) &
                            (df['direction'] == d)
                        ),
                    })
                else:
                    hypotheses.append({
                        'id': f'{label}_{direction}',
                        'feature': 'line_movement',
                        'condition': f'>= {lo}' if lo > 0 else f'<= {lo}',
                        'threshold': lo,
                        'direction': direction,
                        'filter_fn': lambda df, t=lo, d=direction: (
                            ((df['line_movement'] >= t) if t > 0 else (df['line_movement'] <= t)) &
                            (df['direction'] == d)
                        ),
                    })

    # Book disagreement (line_std)
    if 'line_std' in df.columns:
        for thresh in [0.5, 1.0, 1.5, 2.0]:
            for direction in directions:
                hypotheses.append({
                    'id': f'book_std_gte_{thresh}_{direction}',
                    'feature': 'line_std',
                    'condition': f'>= {thresh}',
                    'threshold': thresh,
                    'direction': direction,
                    'filter_fn': lambda df, t=thresh, d=direction: (
                        (df['line_std'] >= t) & (df['direction'] == d)
                    ),
                })

    return hypotheses


def generate_combination_hypotheses(
    df: pd.DataFrame,
    directions: List[str],
) -> List[Dict]:
    """Generate 2-way combination hypotheses for promising feature interactions."""
    hypotheses = []

    combos = [
        # (condition_a, condition_b, id_suffix)
        ('is_home', 'high_line', 'home_high_line'),
        ('is_b2b', 'low_line', 'b2b_low_line'),
    ]

    # Star + home/away
    if all(c in df.columns for c in ['line', 'is_home']):
        for direction in directions:
            # Star away UNDER (line >= 25, away)
            hypotheses.append({
                'id': f'star_away_{direction}',
                'feature': 'line+is_home',
                'condition': 'line >= 25 AND away',
                'threshold': 'line>=25,away',
                'direction': direction,
                'filter_fn': lambda df, d=direction: (
                    (df['line'] >= 25) & (df['is_home'] == 0) & (df['direction'] == d)
                ),
            })
            # Star home
            hypotheses.append({
                'id': f'star_home_{direction}',
                'feature': 'line+is_home',
                'condition': 'line >= 25 AND home',
                'threshold': 'line>=25,home',
                'direction': direction,
                'filter_fn': lambda df, d=direction: (
                    (df['line'] >= 25) & (df['is_home'] == 1) & (df['direction'] == d)
                ),
            })

    # Hot shooting + direction (pre-game safe)
    if 'three_pct_diff' in df.columns and 'line' in df.columns:
        for direction in directions:
            # Hot 3PT + starter line
            hypotheses.append({
                'id': f'hot_3pt_starter_{direction}',
                'feature': 'three_pct_diff+line',
                'condition': '3PT diff >= 0.10 AND line 18-25',
                'threshold': '3pt>=0.10,line=18-25',
                'direction': direction,
                'filter_fn': lambda df, d=direction: (
                    (df['three_pct_diff'] >= 0.10) &
                    (df['line'] >= 18) & (df['line'] < 25) &
                    (df['direction'] == d)
                ),
            })
            # Cold 3PT + high line
            hypotheses.append({
                'id': f'cold_3pt_high_line_{direction}',
                'feature': 'three_pct_diff+line',
                'condition': '3PT diff <= -0.10 AND line >= 20',
                'threshold': '3pt<=-0.10,line>=20',
                'direction': direction,
                'filter_fn': lambda df, d=direction: (
                    (df['three_pct_diff'] <= -0.10) &
                    (df['line'] >= 20) &
                    (df['direction'] == d)
                ),
            })

    # Cold FG + direction (filter candidate)
    if 'fg_pct_diff' in df.columns:
        for direction in directions:
            hypotheses.append({
                'id': f'cold_fg_severe_{direction}',
                'feature': 'fg_pct_diff',
                'condition': 'FG diff <= -0.15 (severe cold)',
                'threshold': -0.15,
                'direction': direction,
                'filter_fn': lambda df, d=direction: (
                    (df['fg_pct_diff'] <= -0.15) & (df['direction'] == d)
                ),
            })

    # Rest advantage + direction
    if 'rest_advantage' in df.columns:
        for direction in directions:
            hypotheses.append({
                'id': f'rest_adv_high_{direction}',
                'feature': 'rest_advantage',
                'condition': '>= 0.7 (strong rest advantage)',
                'threshold': 0.7,
                'direction': direction,
                'filter_fn': lambda df, d=direction: (
                    (df['rest_advantage'] >= 0.7) & (df['direction'] == d)
                ),
            })

    return hypotheses


# ============================================================================
# MAIN SCANNER
# ============================================================================

def run_scan(
    dataset: DiscoveryDataset,
    direction_filter: Optional[str] = None,
    min_edge: float = 3.0,
    verbose: bool = False,
) -> pd.DataFrame:
    """Run the full feature scan.

    Returns DataFrame of results sorted by effect size.
    """
    df = dataset.df.copy()

    # Filter to edge 3+ (the BB-eligible population)
    if min_edge > 0 and 'abs_edge' in df.columns:
        df = df[df['abs_edge'] >= min_edge]
        logger.info(f"Edge >= {min_edge}: {len(df)} rows")

    directions = ['OVER', 'UNDER']
    if direction_filter:
        directions = [direction_filter.upper()]

    # Feature columns for percentile scanning
    # These are the numeric columns available in the enriched dataset
    feature_cols = [
        # Feature store enrichment
        'days_rest', 'opponent_pace', 'scoring_trend_slope', 'points_std_last_10',
        'prop_under_streak', 'prop_over_streak', 'over_rate_last_10',
        'implied_team_total', 'spread_magnitude', 'multi_book_line_std',
        'games_vs_opponent', 'teammate_usage_available', 'star_teammates_out',
        'points_avg_season', 'rest_advantage', 'vegas_points_line',
        'minutes_avg_last_10', 'game_total_line', 'points_avg_last_3',
        'consecutive_games_below_avg', 'usage_rate_last_5',
        # Feature store extra
        'prop_line_delta', 'points_avg_last_5', 'points_avg_last_10',
        'recent_trend', 'team_pace', 'team_win_pct', 'avg_pts_vs_opponent',
        'dnp_rate', 'pts_slope_10g', 'minutes_load_last_7d',
        'deviation_from_avg_last3', 'line_vs_season_avg', 'margin_vs_line_avg_last5',
        # PGS enrichment (pre-game safe rolling stats)
        'usage_rate', 'fg_pct_season', 'three_pct_season',
        'three_pa_per_game', 'fta_avg_last_10', 'fta_cv_last_10',
        'minutes_avg_season', 'fg_pct_last_3', 'three_pct_last_3',
        'mean_points_10g',
        # BettingPros
        'line_std', 'line_movement',
    ]

    # Filter to columns that actually exist
    feature_cols = [c for c in feature_cols if c in df.columns]
    logger.info(f"Scanning {len(feature_cols)} feature columns")

    # --- Generate all hypotheses ---
    all_hyps = []
    all_hyps.extend(generate_percentile_hypotheses(df, feature_cols, directions))
    all_hyps.extend(generate_deviation_hypotheses(df, directions))
    all_hyps.extend(generate_contextual_hypotheses(df, directions))
    all_hyps.extend(generate_combination_hypotheses(df, directions))
    logger.info(f"Generated {len(all_hyps)} hypotheses")

    # Load checkpoint
    checkpoint = {}
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE) as f:
            checkpoint = json.load(f)
        logger.info(f"Loaded checkpoint: {len(checkpoint)} completed")

    # --- Evaluate each hypothesis ---
    results = []
    p_values = []
    skipped = 0
    tested = 0

    for i, hyp in enumerate(all_hyps):
        hyp_id = hyp['id']

        # Skip if already in checkpoint
        if hyp_id in checkpoint:
            skipped += 1
            continue

        # Apply filter function
        try:
            mask = hyp['filter_fn'](df)
            subset = df[mask]
        except Exception as e:
            logger.warning(f"Error evaluating {hyp_id}: {e}")
            checkpoint[hyp_id] = 'error'
            continue

        # Compute stats
        stats = compute_hypothesis_stats(
            subset,
            correct_col='correct',
            date_col='game_date',
            season_col='season',
            baseline=BASELINE_HR,
        )

        if stats is None:
            checkpoint[hyp_id] = 'insufficient_data'
            continue

        tested += 1

        # Tag if already tested
        is_known = any(known in hyp_id.lower() for known in ALREADY_TESTED)

        result = {
            'hypothesis_id': hyp_id,
            'feature': hyp['feature'],
            'condition': hyp['condition'],
            'threshold': hyp['threshold'],
            'direction': hyp['direction'],
            'already_tested': is_known,
            **stats,
        }
        results.append(result)
        p_values.append(stats['p_value'])

        if verbose and tested % 50 == 0:
            logger.info(f"  Tested {tested}/{len(all_hyps)} hypotheses...")

        checkpoint[hyp_id] = 'done'

    logger.info(f"Tested {tested} hypotheses ({skipped} from checkpoint)")

    if not results:
        logger.warning("No hypotheses met minimum sample requirements")
        return pd.DataFrame()

    # --- Apply BH FDR correction ---
    p_arr = np.array(p_values)
    rejected, adjusted_p = benjamini_hochberg(p_arr, alpha=0.05)

    for i, result in enumerate(results):
        result['p_adjusted'] = round(float(adjusted_p[i]), 6)
        result['fdr_significant'] = bool(rejected[i])

    # --- Classify and rank ---
    results_df = pd.DataFrame(results)

    # Verdict: combine FDR significance + consistency + effect size
    def compute_verdict(row):
        if not row.get('fdr_significant'):
            return 'NOT_SIGNIFICANT'
        consistency = row.get('consistency', {})
        if not consistency.get('pass'):
            return 'INCONSISTENT'
        if row.get('ci_excludes_baseline'):
            effect = row.get('effect_class', 'NOISE')
            if 'STRONG' in effect:
                return 'VALIDATED_STRONG'
            elif effect != 'NOISE':
                return 'VALIDATED_WEAK'
        return 'MARGINAL'

    results_df['verdict'] = results_df.apply(compute_verdict, axis=1)

    # Sort: validated first, then by absolute effect size
    verdict_order = {
        'VALIDATED_STRONG': 0, 'VALIDATED_WEAK': 1,
        'MARGINAL': 2, 'INCONSISTENT': 3, 'NOT_SIGNIFICANT': 4,
    }
    results_df['_sort'] = results_df['verdict'].map(verdict_order)
    results_df['abs_effect'] = results_df['effect_pp'].abs()
    results_df = results_df.sort_values(['_sort', 'abs_effect'], ascending=[True, False])
    results_df = results_df.drop(columns=['_sort', 'abs_effect'])

    # Save checkpoint
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump(checkpoint, f, indent=2)

    return results_df


def save_results(results_df: pd.DataFrame, prefix: str = 'feature_scan'):
    """Save results to CSV and JSON."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = OUTPUT_DIR / f'{prefix}_results.csv'
    json_path = OUTPUT_DIR / f'{prefix}_results.json'

    # Flatten consistency dict for CSV
    flat_results = []
    for _, row in results_df.iterrows():
        flat = row.to_dict()
        consistency = flat.pop('consistency', {})
        flat['seasons_consistent'] = consistency.get('seasons_consistent', 0)
        flat['seasons_valid'] = consistency.get('seasons_valid', 0)
        flat['consistency_cv'] = consistency.get('cv')
        flat['consistency_pass'] = consistency.get('pass', False)
        per_season = consistency.get('per_season', {})
        for season, stats in per_season.items():
            flat[f'hr_{season}'] = stats.get('hr')
            flat[f'n_{season}'] = stats.get('n')
        flat_results.append(flat)

    flat_df = pd.DataFrame(flat_results)
    flat_df.to_csv(csv_path, index=False)

    # JSON with full nested structure
    json_results = results_df.to_dict(orient='records')
    with open(json_path, 'w') as f:
        json.dump(json_results, f, indent=2, default=str)

    logger.info(f"Results saved to {csv_path} and {json_path}")
    return csv_path, json_path


def print_summary(results_df: pd.DataFrame):
    """Print a human-readable summary of findings."""
    print("\n" + "=" * 80)
    print("SIGNAL DISCOVERY SCAN RESULTS")
    print("=" * 80)

    total = len(results_df)
    sig = len(results_df[results_df['fdr_significant']])
    validated = len(results_df[results_df['verdict'].str.startswith('VALIDATED')])
    new_validated = len(results_df[
        results_df['verdict'].str.startswith('VALIDATED') &
        ~results_df['already_tested']
    ])

    print(f"\nHypotheses tested: {total}")
    print(f"FDR significant (p_adj < 0.05): {sig}")
    print(f"Cross-season validated: {validated}")
    print(f"NEW discoveries (not already tested): {new_validated}")

    # --- Top Signal Candidates (HR > baseline) ---
    signals = results_df[
        (results_df['verdict'].str.startswith('VALIDATED')) &
        (results_df['effect_pp'] > 0)
    ].head(20)

    if len(signals) > 0:
        print(f"\n{'─' * 80}")
        print("TOP SIGNAL CANDIDATES (HR > baseline)")
        print(f"{'─' * 80}")
        print(f"{'ID':<45} {'Dir':<6} {'HR':>6} {'N':>6} {'Effect':>7} {'CI':>12} {'New':>4} {'Verdict':<18}")
        print(f"{'─' * 45} {'─' * 5} {'─' * 6} {'─' * 6} {'─' * 7} {'─' * 12} {'─' * 4} {'─' * 18}")
        for _, r in signals.iterrows():
            new_flag = '★' if not r['already_tested'] else ' '
            ci = f"[{r['bootstrap_ci_lo']:.3f},{r['bootstrap_ci_hi']:.3f}]"
            print(f"{r['hypothesis_id']:<45} {r['direction']:<6} {r['hr']:>5.1%} {r['total_n']:>6} "
                  f"{r['effect_pp']:>+6.1f}pp {ci:>12} {new_flag:>4} {r['verdict']:<18}")

    # --- Top Filter Candidates (HR < baseline) ---
    filters = results_df[
        (results_df['verdict'].str.startswith('VALIDATED')) &
        (results_df['effect_pp'] < 0)
    ].head(20)

    if len(filters) > 0:
        print(f"\n{'─' * 80}")
        print("TOP FILTER CANDIDATES (HR < baseline, block these)")
        print(f"{'─' * 80}")
        print(f"{'ID':<45} {'Dir':<6} {'HR':>6} {'N':>6} {'Effect':>7} {'CI':>12} {'New':>4} {'Verdict':<18}")
        print(f"{'─' * 45} {'─' * 5} {'─' * 6} {'─' * 6} {'─' * 7} {'─' * 12} {'─' * 4} {'─' * 18}")
        for _, r in filters.iterrows():
            new_flag = '★' if not r['already_tested'] else ' '
            ci = f"[{r['bootstrap_ci_lo']:.3f},{r['bootstrap_ci_hi']:.3f}]"
            print(f"{r['hypothesis_id']:<45} {r['direction']:<6} {r['hr']:>5.1%} {r['total_n']:>6} "
                  f"{r['effect_pp']:>+6.1f}pp {ci:>12} {new_flag:>4} {r['verdict']:<18}")

    # --- Verdict distribution ---
    print(f"\n{'─' * 80}")
    print("VERDICT DISTRIBUTION")
    print(f"{'─' * 80}")
    for verdict, count in results_df['verdict'].value_counts().items():
        print(f"  {verdict:<25} {count:>5}")


def main():
    parser = argparse.ArgumentParser(description='Systematic Feature/Filter Scanner')
    parser.add_argument('--min-edge', type=float, default=3.0,
                        help='Minimum edge to include (default: 3.0)')
    parser.add_argument('--direction', type=str, default=None,
                        help='Filter to OVER or UNDER only')
    parser.add_argument('--verbose', action='store_true',
                        help='Show progress during scan')
    parser.add_argument('--reset', action='store_true',
                        help='Clear checkpoint and rescan everything')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format='%(asctime)s %(levelname)s %(message)s',
    )

    if args.reset and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        logger.info("Checkpoint cleared")

    print("Loading dataset...")
    t0 = time.time()
    dataset = DiscoveryDataset(min_edge=0)  # Load all, filter in scan
    summary = dataset.summary()
    print(f"Dataset: {summary['total_rows']} rows, {summary['columns']} cols")
    print(f"Seasons: {summary['seasons']}")
    print(f"Baseline HR: {summary['baseline_hr']:.1%}")
    print(f"Edge 3+ HR: {summary['edge_3plus_hr']:.1%}")

    print(f"\nRunning scan (min_edge={args.min_edge})...")
    results_df = run_scan(
        dataset,
        direction_filter=args.direction,
        min_edge=args.min_edge,
        verbose=args.verbose,
    )

    elapsed = time.time() - t0
    print(f"\nScan completed in {elapsed:.1f}s")

    if len(results_df) > 0:
        save_results(results_df)
        print_summary(results_df)
    else:
        print("No results — all hypotheses had insufficient data")


if __name__ == '__main__':
    main()
