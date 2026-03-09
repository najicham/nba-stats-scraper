#!/usr/bin/env python3
"""
MLB Ultra-Bet Tier Discovery
Cross-season validated signal combinations for 70%+ HR.

Uses walk-forward predictions from both classifier (CatBoost) and regressor models.
"""
import pandas as pd
import numpy as np
from itertools import combinations
from typing import List, Tuple, Dict, Optional
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# CONFIG
# =============================================================================
PROJ_ROOT = "/home/naji/code/nba-stats-scraper"

# Load both datasets
CLASSIFIER_FILE = f"{PROJ_ROOT}/results/mlb_walkforward_v4_rich/predictions_catboost_120d_fixed_edge1.0.csv"
CLASSIFIER_WIDE = f"{PROJ_ROOT}/results/mlb_walkforward_v4_rich/predictions_catboost_120d_fixed_edge0.5.csv"
REGRESSOR_FILE = f"{PROJ_ROOT}/results/mlb_walkforward_v4_regression/predictions_regression_120d_edge0.50.csv"

BLACKLIST = frozenset([
    'tanner_bibee', 'mitchell_parker', 'casey_mize', 'mitch_keller',
    'logan_webb', 'jose_berrios', 'logan_gilbert', 'logan_allen',
    'jake_irvin', 'george_kirby', 'mackenzie_gore', 'bailey_ober',
    'zach_eflin', 'ryne_nelson', 'jameson_taillon', 'ryan_feltner',
    'luis_severino', 'randy_vasquez',
])

CROSS_SEASON_GAP_THRESHOLD = 5.0  # pp
BOOTSTRAP_N = 5000

# =============================================================================
# DATA LOADING
# =============================================================================
def load_data():
    """Load and merge both datasets for maximum coverage."""
    # Load regressor (larger, edge >= 0.5)
    reg = pd.read_csv(REGRESSOR_FILE)
    reg['source'] = 'regressor'
    reg['edge'] = reg['real_edge']  # Use real_edge from regressor

    # Load classifier (edge >= 0.5)
    cls = pd.read_csv(CLASSIFIER_WIDE)
    cls['source'] = 'classifier'

    # Standardize columns
    common_cols = [
        'game_date', 'correct', 'actual_over', 'predicted_over', 'edge',
        'pitcher_name', 'pitcher_lookup', 'team_abbr', 'opponent_team_abbr',
        'venue', 'is_home', 'is_day_game', 'strikeouts_line', 'actual_strikeouts',
        'projection_value', 'days_rest', 'k_avg_last_5', 'season_k_per_9', 'source'
    ]

    reg_std = reg[common_cols].copy()
    cls_std = cls[common_cols].copy()

    # Use regressor as primary (larger, regression-based edge is better)
    # Also keep classifier for comparison
    print(f"Regressor predictions: {len(reg_std)}")
    print(f"Classifier predictions: {len(cls_std)}")

    return reg_std, cls_std


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived features."""
    df = df.copy()
    df['game_date'] = pd.to_datetime(df['game_date'])
    df['year'] = df['game_date'].dt.year
    df['is_half_line'] = (df['strikeouts_line'] % 1 == 0.5).astype(int)
    df['is_whole_line'] = (df['strikeouts_line'] % 1 == 0.0).astype(int)
    df['is_blacklisted'] = df['pitcher_lookup'].isin(BLACKLIST).astype(int)
    df['is_over_pred'] = (df['predicted_over'] == 1).astype(int)
    df['projection_above_line'] = (df['projection_value'] > df['strikeouts_line']).astype(int)
    df['k_avg_above_line'] = (df['k_avg_last_5'] > df['strikeouts_line']).astype(int)
    df['low_line'] = (df['strikeouts_line'] <= 4.5).astype(int)
    df['long_rest'] = (df['days_rest'] >= 6).astype(int)
    df['good_k_pitcher'] = (df['season_k_per_9'] >= 8.0).astype(int)
    df['avoid_ace_trap'] = (df['season_k_per_9'] < 9.0).astype(int)
    df['good_k_no_trap'] = ((df['season_k_per_9'] >= 8.0) & (df['season_k_per_9'] < 9.0)).astype(int)

    # Rank by edge within each day (for top-N daily filtering)
    df['edge_rank'] = df.groupby('game_date')['edge'].rank(ascending=False, method='first')

    return df


# =============================================================================
# ANALYSIS HELPERS
# =============================================================================
def compute_hr(df: pd.DataFrame) -> Dict:
    """Compute HR stats with cross-season breakdown."""
    if len(df) == 0:
        return {'hr': 0, 'n': 0, 'hr_2024': 0, 'n_2024': 0, 'hr_2025': 0, 'n_2025': 0, 'gap': 0, 'stable': True}

    total_hr = df['correct'].mean() * 100
    total_n = len(df)

    d24 = df[df['year'] == 2024]
    d25 = df[df['year'] == 2025]

    hr_24 = d24['correct'].mean() * 100 if len(d24) > 0 else np.nan
    n_24 = len(d24)
    hr_25 = d25['correct'].mean() * 100 if len(d25) > 0 else np.nan
    n_25 = len(d25)

    gap = abs(hr_24 - hr_25) if not (np.isnan(hr_24) or np.isnan(hr_25)) else np.nan
    stable = gap <= CROSS_SEASON_GAP_THRESHOLD if not np.isnan(gap) else False

    return {
        'hr': total_hr, 'n': total_n,
        'hr_2024': hr_24, 'n_2024': n_24,
        'hr_2025': hr_25, 'n_2025': n_25,
        'gap': gap, 'stable': stable
    }


def bootstrap_ci(df: pd.DataFrame, n_boot: int = BOOTSTRAP_N) -> Tuple[float, float, float]:
    """Bootstrap 95% CI for HR."""
    if len(df) < 5:
        return (0, 0, 0)
    correct = df['correct'].values
    hrs = []
    rng = np.random.default_rng(42)
    for _ in range(n_boot):
        sample = rng.choice(correct, size=len(correct), replace=True)
        hrs.append(sample.mean() * 100)
    hrs = np.array(hrs)
    return (np.percentile(hrs, 2.5), np.percentile(hrs, 50), np.percentile(hrs, 97.5))


def print_hr(label: str, stats: Dict, indent: int = 0):
    """Print HR stats nicely."""
    prefix = "  " * indent
    stable_flag = "STABLE" if stats['stable'] else "UNSTABLE"
    gap_str = f"{stats['gap']:.1f}pp" if not np.isnan(stats.get('gap', np.nan)) else "N/A"
    print(f"{prefix}{label}: {stats['hr']:.1f}% HR (N={stats['n']}) | "
          f"2024: {stats['hr_2024']:.1f}% (N={stats['n_2024']}) | "
          f"2025: {stats['hr_2025']:.1f}% (N={stats['n_2025']}) | "
          f"Gap: {gap_str} [{stable_flag}]")


def picks_per_day(df: pd.DataFrame) -> float:
    """Average picks per day."""
    if len(df) == 0:
        return 0
    n_days = df['game_date'].nunique()
    return len(df) / n_days if n_days > 0 else 0


# =============================================================================
# MAIN ANALYSIS
# =============================================================================
def main():
    print("=" * 100)
    print("MLB ULTRA-BET TIER DISCOVERY — Cross-Season Validated")
    print("=" * 100)

    reg, cls = load_data()

    # Use regressor as primary dataset (more predictions, regression edge)
    df = add_features(reg)
    df_cls = add_features(cls)

    print(f"\nDate range: {df['game_date'].min()} to {df['game_date'].max()}")
    print(f"2024 predictions: {len(df[df['year']==2024])}")
    print(f"2025 predictions: {len(df[df['year']==2025])}")
    print(f"Overall HR: {df['correct'].mean()*100:.1f}%")

    # Also check classifier
    print(f"\nClassifier date range: {df_cls['game_date'].min()} to {df_cls['game_date'].max()}")
    print(f"Classifier HR: {df_cls['correct'].mean()*100:.1f}%")

    # =============================================================================
    # SECTION 1: BASELINE — OVER + half-line + not-blacklisted + edge 0.75-2.0 + top-3 daily
    # =============================================================================
    print("\n" + "=" * 100)
    print("SECTION 1: BASELINE — OVER + half-line + not-blacklisted + edge [0.75, 2.0] + top-3/day")
    print("=" * 100)

    base_mask = (
        (df['is_over_pred'] == 1) &
        (df['is_half_line'] == 1) &
        (df['is_blacklisted'] == 0) &
        (df['edge'] >= 0.75) &
        (df['edge'] <= 2.0)
    )
    base = df[base_mask].copy()
    # Rank within this subset for top-3
    base['sub_rank'] = base.groupby('game_date')['edge'].rank(ascending=False, method='first')
    base_top3 = base[base['sub_rank'] <= 3]

    print(f"\nBefore top-3: {len(base)} predictions")
    base_stats = compute_hr(base)
    print_hr("All qualifying", base_stats)

    base_top3_stats = compute_hr(base_top3)
    print_hr("Top-3 daily", base_top3_stats)
    print(f"  Avg picks/day: {picks_per_day(base_top3):.1f}")

    # Also without top-3 restriction
    base_no_rank = df[base_mask]
    print(f"\n  (For reference - no top-3 filter: {compute_hr(base_no_rank)['hr']:.1f}% HR, N={len(base_no_rank)})")

    # =============================================================================
    # SECTION 2: SINGLE SIGNAL LAYERING
    # =============================================================================
    print("\n" + "=" * 100)
    print("SECTION 2: SINGLE SIGNAL LAYERING (on top of base)")
    print("=" * 100)

    # Base pool (before top-3) for signal testing
    signals = {
        'edge >= 1.0': lambda d: d['edge'] >= 1.0,
        'edge >= 1.25': lambda d: d['edge'] >= 1.25,
        'edge >= 1.5': lambda d: d['edge'] >= 1.5,
        'is_home': lambda d: d['is_home'] == 1,
        'proj > line': lambda d: d['projection_above_line'] == 1,
        'low_line <= 4.5': lambda d: d['low_line'] == 1,
        'k_avg > line': lambda d: d['k_avg_above_line'] == 1,
        'days_rest >= 6': lambda d: d['long_rest'] == 1,
        'K/9 >= 8.0': lambda d: d['good_k_pitcher'] == 1,
        'K/9 < 9.0': lambda d: d['avoid_ace_trap'] == 1,
        'K/9 8.0-9.0': lambda d: d['good_k_no_trap'] == 1,
    }

    signal_results = {}
    for name, mask_fn in signals.items():
        filtered = base[mask_fn(base)]
        # Apply top-3 within this filtered subset
        filtered = filtered.copy()
        filtered['sub_rank'] = filtered.groupby('game_date')['edge'].rank(ascending=False, method='first')
        filtered_top3 = filtered[filtered['sub_rank'] <= 3]
        stats = compute_hr(filtered_top3)
        stats['ppd'] = picks_per_day(filtered_top3)
        signal_results[name] = stats
        print_hr(f"+ {name}", stats)
        print(f"    Picks/day: {stats['ppd']:.1f}")

    # =============================================================================
    # SECTION 2b: Also test WITHOUT top-3 for each signal (raw lift)
    # =============================================================================
    print("\n--- Without top-3 restriction (raw signal lift) ---")
    signal_results_raw = {}
    for name, mask_fn in signals.items():
        filtered = base[mask_fn(base)]
        stats = compute_hr(filtered)
        signal_results_raw[name] = stats
        stable_str = "STABLE" if stats['stable'] else "UNSTABLE"
        print(f"  + {name}: {stats['hr']:.1f}% (N={stats['n']}) | "
              f"2024: {stats['hr_2024']:.1f}% (N={stats['n_2024']}) | "
              f"2025: {stats['hr_2025']:.1f}% (N={stats['n_2025']}) | [{stable_str}]")

    # =============================================================================
    # SECTION 3: TWO-SIGNAL COMBOS (top 5 stable singles)
    # =============================================================================
    print("\n" + "=" * 100)
    print("SECTION 3: TWO-SIGNAL COMBOS (top 5 stable singles)")
    print("=" * 100)

    # Rank signals by combined HR, filter stable only
    stable_signals = {k: v for k, v in signal_results.items()
                      if v['stable'] and v['n'] >= 20}

    # Sort by HR descending
    sorted_signals = sorted(stable_signals.items(), key=lambda x: x[1]['hr'], reverse=True)
    top5_names = [name for name, _ in sorted_signals[:5]]

    print(f"\nTop 5 stable singles: {top5_names}")
    if len(top5_names) < 5:
        # Also include best unstable ones
        all_sorted = sorted(signal_results.items(), key=lambda x: x[1]['hr'], reverse=True)
        for name, stats in all_sorted:
            if name not in top5_names and stats['n'] >= 15:
                top5_names.append(name)
            if len(top5_names) >= 5:
                break
        print(f"  (Padded with high-HR signals): {top5_names}")

    combo2_results = {}
    for i, (s1, s2) in enumerate(combinations(top5_names, 2)):
        mask1 = signals[s1]
        mask2 = signals[s2]
        filtered = base[mask1(base) & mask2(base)]
        # Top-3 daily
        filtered = filtered.copy()
        if len(filtered) > 0:
            filtered['sub_rank'] = filtered.groupby('game_date')['edge'].rank(ascending=False, method='first')
            filtered_top3 = filtered[filtered['sub_rank'] <= 3]
        else:
            filtered_top3 = filtered
        stats = compute_hr(filtered_top3)
        stats['ppd'] = picks_per_day(filtered_top3) if len(filtered_top3) > 0 else 0
        combo_name = f"{s1} + {s2}"
        combo2_results[combo_name] = stats
        print_hr(f"{s1} + {s2}", stats)
        print(f"    Picks/day: {stats['ppd']:.1f}")

    # Also test without top-3 for combos
    print("\n--- Two-signal combos WITHOUT top-3 ---")
    combo2_raw = {}
    for s1, s2 in combinations(top5_names, 2):
        mask1 = signals[s1]
        mask2 = signals[s2]
        filtered = base[mask1(base) & mask2(base)]
        stats = compute_hr(filtered)
        combo_name = f"{s1} + {s2}"
        combo2_raw[combo_name] = stats
        if stats['n'] >= 10:
            stable_str = "STABLE" if stats['stable'] else "UNSTABLE"
            print(f"  {combo_name}: {stats['hr']:.1f}% (N={stats['n']}) | "
                  f"2024: {stats['hr_2024']:.1f}% | 2025: {stats['hr_2025']:.1f}% | [{stable_str}]")

    # =============================================================================
    # SECTION 4: THREE-SIGNAL COMBOS
    # =============================================================================
    print("\n" + "=" * 100)
    print("SECTION 4: THREE-SIGNAL COMBOS")
    print("=" * 100)

    # Take top 3 stable pairs
    stable_pairs = {k: v for k, v in combo2_results.items() if v['n'] >= 15}
    sorted_pairs = sorted(stable_pairs.items(), key=lambda x: x[1]['hr'], reverse=True)[:3]

    if not sorted_pairs:
        # Fallback: take any with N >= 10
        sorted_pairs = sorted(combo2_results.items(), key=lambda x: x[1]['hr'], reverse=True)[:3]

    print(f"Top pairs to extend:")
    for name, stats in sorted_pairs:
        print(f"  {name}: {stats['hr']:.1f}% (N={stats['n']})")

    combo3_results = {}
    all_signal_names = list(signals.keys())
    for pair_name, _ in sorted_pairs:
        pair_signals = pair_name.split(" + ")
        for extra in all_signal_names:
            if extra in pair_signals:
                continue
            combined_mask = True
            for s in pair_signals:
                combined_mask = combined_mask & signals[s](base)
            combined_mask = combined_mask & signals[extra](base)
            filtered = base[combined_mask]
            if len(filtered) < 5:
                continue
            filtered = filtered.copy()
            filtered['sub_rank'] = filtered.groupby('game_date')['edge'].rank(ascending=False, method='first')
            filtered_top3 = filtered[filtered['sub_rank'] <= 3]
            stats = compute_hr(filtered_top3)
            stats['ppd'] = picks_per_day(filtered_top3) if len(filtered_top3) > 0 else 0
            combo_name = f"{pair_name} + {extra}"
            combo3_results[combo_name] = stats
            if stats['n'] >= 10:
                print_hr(f"{combo_name}", stats)
                print(f"    Picks/day: {stats['ppd']:.1f}")

    # =============================================================================
    # SECTION 5: TOP-1 vs TOP-2 vs TOP-3
    # =============================================================================
    print("\n" + "=" * 100)
    print("SECTION 5: TOP-1 vs TOP-2 vs TOP-3 DAILY RESTRICTION")
    print("=" * 100)

    # Collect all promising combos (HR >= 58%)
    all_combos = {}
    all_combos.update(signal_results)
    all_combos.update(combo2_results)
    all_combos.update(combo3_results)

    promising = {k: v for k, v in all_combos.items() if v['hr'] >= 55 and v['n'] >= 15}
    sorted_promising = sorted(promising.items(), key=lambda x: x[1]['hr'], reverse=True)[:10]

    for combo_name, _ in sorted_promising:
        # Reconstruct the filter
        parts = [p.strip() for p in combo_name.split("+")]
        parts = [p.strip() for p in parts]

        combined_mask = pd.Series(True, index=base.index)
        valid = True
        for p in parts:
            p = p.strip()
            if p in signals:
                combined_mask = combined_mask & signals[p](base)
            else:
                valid = False
                break
        if not valid:
            continue

        filtered = base[combined_mask].copy()
        if len(filtered) == 0:
            continue
        filtered['sub_rank'] = filtered.groupby('game_date')['edge'].rank(ascending=False, method='first')

        print(f"\n  {combo_name}:")
        for top_n in [1, 2, 3, 5]:
            top_df = filtered[filtered['sub_rank'] <= top_n]
            stats = compute_hr(top_df)
            ppd = picks_per_day(top_df)
            stable_str = "S" if stats['stable'] else "U"
            print(f"    Top-{top_n}: {stats['hr']:.1f}% (N={stats['n']}) | "
                  f"2024: {stats['hr_2024']:.1f}% | 2025: {stats['hr_2025']:.1f}% | "
                  f"{ppd:.1f}/day [{stable_str}]")

    # =============================================================================
    # SECTION 6: STRUCTURAL ULTRA (market structure, not model)
    # =============================================================================
    print("\n" + "=" * 100)
    print("SECTION 6: STRUCTURAL ULTRA (market-based, not model-confidence)")
    print("=" * 100)

    structural_tests = {
        "Half + low(3.5-4.5) + OVER + !BL + edge>=1.0": (
            (df['is_over_pred'] == 1) &
            (df['is_half_line'] == 1) &
            (df['is_blacklisted'] == 0) &
            (df['strikeouts_line'] >= 3.5) &
            (df['strikeouts_line'] <= 4.5) &
            (df['edge'] >= 1.0)
        ),
        "Half + low(<=4.5) + OVER + !BL + edge>=0.75": (
            (df['is_over_pred'] == 1) &
            (df['is_half_line'] == 1) &
            (df['is_blacklisted'] == 0) &
            (df['strikeouts_line'] <= 4.5) &
            (df['edge'] >= 0.75)
        ),
        "Half + K/9>=8 + K/9<9.0 + OVER + !BL + edge>=0.75": (
            (df['is_over_pred'] == 1) &
            (df['is_half_line'] == 1) &
            (df['is_blacklisted'] == 0) &
            (df['season_k_per_9'] >= 8.0) &
            (df['season_k_per_9'] < 9.0) &
            (df['edge'] >= 0.75)
        ),
        "Half + low(<=4.5) + home + OVER + !BL + edge>=0.75": (
            (df['is_over_pred'] == 1) &
            (df['is_half_line'] == 1) &
            (df['is_blacklisted'] == 0) &
            (df['strikeouts_line'] <= 4.5) &
            (df['is_home'] == 1) &
            (df['edge'] >= 0.75)
        ),
        "Half + low(<=4.5) + proj>line + OVER + !BL + edge>=0.75": (
            (df['is_over_pred'] == 1) &
            (df['is_half_line'] == 1) &
            (df['is_blacklisted'] == 0) &
            (df['strikeouts_line'] <= 4.5) &
            (df['projection_above_line'] == 1) &
            (df['edge'] >= 0.75)
        ),
        "Half + K/9 8-9 + low(<=4.5) + OVER + !BL + edge>=0.75": (
            (df['is_over_pred'] == 1) &
            (df['is_half_line'] == 1) &
            (df['is_blacklisted'] == 0) &
            (df['season_k_per_9'] >= 8.0) &
            (df['season_k_per_9'] < 9.0) &
            (df['strikeouts_line'] <= 4.5) &
            (df['edge'] >= 0.75)
        ),
    }

    for name, mask in structural_tests.items():
        filtered = df[mask]
        stats = compute_hr(filtered)
        ppd = picks_per_day(filtered)
        print_hr(name, stats)
        print(f"    Picks/day: {ppd:.1f}")

        # Top-1 and top-2 versions
        if len(filtered) > 0:
            filtered = filtered.copy()
            filtered['sub_rank'] = filtered.groupby('game_date')['edge'].rank(ascending=False, method='first')
            for top_n in [1, 2]:
                top_df = filtered[filtered['sub_rank'] <= top_n]
                ts = compute_hr(top_df)
                ppd_n = picks_per_day(top_df)
                print(f"      Top-{top_n}: {ts['hr']:.1f}% (N={ts['n']}) | "
                      f"2024: {ts['hr_2024']:.1f}% | 2025: {ts['hr_2025']:.1f}% | "
                      f"{ppd_n:.1f}/day")

    # =============================================================================
    # SECTION 7: LINE-LEVEL SPECIFIC
    # =============================================================================
    print("\n" + "=" * 100)
    print("SECTION 7: LINE-LEVEL SPECIFIC")
    print("=" * 100)

    # Test each line value for OVER + !BL
    over_not_bl = df[(df['is_over_pred'] == 1) & (df['is_blacklisted'] == 0)]
    line_values = sorted(over_not_bl['strikeouts_line'].unique())

    print("\nLine-by-line HR (OVER + not-blacklisted):")
    profitable_lines = []
    for lv in line_values:
        line_df = over_not_bl[over_not_bl['strikeouts_line'] == lv]
        if len(line_df) < 10:
            continue
        stats = compute_hr(line_df)
        is_half = "HALF" if lv % 1 == 0.5 else "WHOLE"
        stable_str = "S" if stats['stable'] else "U"
        if stats['hr'] >= 58:
            profitable_lines.append(lv)
        marker = " ***" if stats['hr'] >= 60 else (" **" if stats['hr'] >= 55 else "")
        print(f"  Line {lv:4.1f} [{is_half}]: {stats['hr']:.1f}% (N={stats['n']}) | "
              f"2024: {stats['hr_2024']:.1f}% (N={stats['n_2024']}) | "
              f"2025: {stats['hr_2025']:.1f}% (N={stats['n_2025']}) | [{stable_str}]{marker}")

    # Ultra = only profitable lines
    print(f"\nProfitable lines (>=58% HR): {profitable_lines}")
    if profitable_lines:
        profit_mask = (
            (df['is_over_pred'] == 1) &
            (df['is_blacklisted'] == 0) &
            (df['strikeouts_line'].isin(profitable_lines)) &
            (df['edge'] >= 0.75)
        )
        profit_df = df[profit_mask]
        stats = compute_hr(profit_df)
        print_hr("Profitable lines + edge >= 0.75", stats)
        print(f"    Picks/day: {picks_per_day(profit_df):.1f}")

    # Cross-season stable profitable lines
    stable_profitable = []
    for lv in profitable_lines:
        line_df = over_not_bl[over_not_bl['strikeouts_line'] == lv]
        stats = compute_hr(line_df)
        if stats['stable']:
            stable_profitable.append(lv)
    print(f"\nStable profitable lines: {stable_profitable}")
    if stable_profitable:
        sp_mask = (
            (df['is_over_pred'] == 1) &
            (df['is_blacklisted'] == 0) &
            (df['strikeouts_line'].isin(stable_profitable)) &
            (df['edge'] >= 0.75)
        )
        sp_df = df[sp_mask]
        stats = compute_hr(sp_df)
        print_hr("Stable profitable lines + edge >= 0.75", stats)

    # =============================================================================
    # SECTION 8: MONTE CARLO BOOTSTRAP
    # =============================================================================
    print("\n" + "=" * 100)
    print("SECTION 8: MONTE CARLO BOOTSTRAP (5000 resamples)")
    print("=" * 100)

    # Collect best candidates from all sections
    candidates = {}

    # Best single signals (top-3)
    for name, stats in sorted(signal_results.items(), key=lambda x: x[1]['hr'], reverse=True)[:3]:
        candidates[f"Single: {name} (top-3)"] = (base, signals[name], 3)

    # Best two-signal combos
    for name, stats in sorted(combo2_results.items(), key=lambda x: x[1]['hr'], reverse=True)[:3]:
        parts = [p.strip() for p in name.split("+")]
        def make_combo_mask(parts):
            def mask_fn(d):
                m = pd.Series(True, index=d.index)
                for p in parts:
                    p = p.strip()
                    if p in signals:
                        m = m & signals[p](d)
                return m
            return mask_fn
        candidates[f"Pair: {name} (top-3)"] = (base, make_combo_mask(parts), 3)

    # Best three-signal combos
    for name, stats in sorted(combo3_results.items(), key=lambda x: x[1]['hr'], reverse=True)[:3]:
        parts = [p.strip() for p in name.split("+")]
        def make_combo_mask3(parts):
            def mask_fn(d):
                m = pd.Series(True, index=d.index)
                for p in parts:
                    p = p.strip()
                    if p in signals:
                        m = m & signals[p](d)
                return m
            return mask_fn
        candidates[f"Triple: {name} (top-3)"] = (base, make_combo_mask3(parts), 3)

    # Structural candidates
    for name, mask in structural_tests.items():
        filtered = df[mask]
        if len(filtered) >= 20:
            stats = compute_hr(filtered)
            if stats['hr'] >= 58:
                candidates[f"Struct: {name}"] = (df, lambda d, m=mask: m, None)

    # The full base (reference)
    candidates["BASELINE (top-3)"] = (base, lambda d: pd.Series(True, index=d.index), 3)

    print(f"\nBootstrapping {len(candidates)} candidates...\n")

    bootstrap_results = []
    for name, (data_source, mask_fn, top_n) in candidates.items():
        try:
            if callable(mask_fn):
                result = mask_fn(data_source)
                if isinstance(result, pd.Series):
                    filtered = data_source[result]
                else:
                    filtered = data_source[result]
            else:
                filtered = data_source

            if top_n is not None and len(filtered) > 0:
                filtered = filtered.copy()
                filtered['sub_rank'] = filtered.groupby('game_date')['edge'].rank(ascending=False, method='first')
                filtered = filtered[filtered['sub_rank'] <= top_n]

            if len(filtered) < 10:
                continue

            ci_low, ci_med, ci_high = bootstrap_ci(filtered)
            hr = filtered['correct'].mean() * 100
            n = len(filtered)
            ppd = picks_per_day(filtered)

            includes_70 = ci_high >= 70
            includes_65 = ci_high >= 65

            bootstrap_results.append({
                'name': name, 'hr': hr, 'n': n, 'ppd': ppd,
                'ci_low': ci_low, 'ci_med': ci_med, 'ci_high': ci_high,
                'includes_70': includes_70, 'includes_65': includes_65
            })

            ci_70 = "YES" if includes_70 else "no"
            ci_65 = "YES" if includes_65 else "no"
            print(f"  {name}")
            print(f"    HR: {hr:.1f}% (N={n}) | 95% CI: [{ci_low:.1f}%, {ci_high:.1f}%] | "
                  f"70% in CI: {ci_70} | 65% in CI: {ci_65} | {ppd:.1f}/day")
        except Exception as e:
            print(f"  {name}: ERROR - {e}")

    # =============================================================================
    # SECTION 9: VOLUME CHECK
    # =============================================================================
    print("\n" + "=" * 100)
    print("SECTION 9: VOLUME CHECK — picks per day")
    print("=" * 100)

    for br in sorted(bootstrap_results, key=lambda x: x['hr'], reverse=True):
        volume_flag = "OK" if br['ppd'] >= 0.5 else "TOO LOW"
        print(f"  {br['name']}: {br['ppd']:.2f}/day [{volume_flag}]")

    # =============================================================================
    # SECTION 10: TOP-1/TOP-2 FOR ALL STRUCTURAL CANDIDATES
    # =============================================================================
    print("\n" + "=" * 100)
    print("SECTION 10: TOP-1 vs TOP-2 FOR ALL STRUCTURAL + BEST COMBOS")
    print("=" * 100)

    # Reconstruct structural candidates
    for name, mask in structural_tests.items():
        filtered = df[mask].copy()
        if len(filtered) < 10:
            continue
        filtered['sub_rank'] = filtered.groupby('game_date')['edge'].rank(ascending=False, method='first')
        print(f"\n  {name}:")
        for top_n in [1, 2, 3]:
            top_df = filtered[filtered['sub_rank'] <= top_n]
            stats = compute_hr(top_df)
            ppd = picks_per_day(top_df)
            ci_low, _, ci_high = bootstrap_ci(top_df)
            print(f"    Top-{top_n}: {stats['hr']:.1f}% (N={stats['n']}) | "
                  f"95% CI: [{ci_low:.1f}%, {ci_high:.1f}%] | "
                  f"2024: {stats['hr_2024']:.1f}% | 2025: {stats['hr_2025']:.1f}% | "
                  f"{ppd:.1f}/day | Gap: {stats['gap']:.1f}pp")

    # =============================================================================
    # SECTION 11: CROSS-DATASET VALIDATION (Classifier vs Regressor)
    # =============================================================================
    print("\n" + "=" * 100)
    print("SECTION 11: CROSS-DATASET VALIDATION — Does the best ultra hold in classifier data?")
    print("=" * 100)

    # Test structural ultras on classifier data too
    for name, mask_fn_str in [
        ("Half + low(<=4.5) + OVER + !BL + edge>=0.75", lambda d: (
            (d['is_over_pred'] == 1) & (d['is_half_line'] == 1) &
            (d['is_blacklisted'] == 0) & (d['strikeouts_line'] <= 4.5) & (d['edge'] >= 0.75)
        )),
        ("Half + low(3.5-4.5) + OVER + !BL + edge>=1.0", lambda d: (
            (d['is_over_pred'] == 1) & (d['is_half_line'] == 1) &
            (d['is_blacklisted'] == 0) & (d['strikeouts_line'] >= 3.5) &
            (d['strikeouts_line'] <= 4.5) & (d['edge'] >= 1.0)
        )),
        ("Half + K/9 8-9 + OVER + !BL + edge>=0.75", lambda d: (
            (d['is_over_pred'] == 1) & (d['is_half_line'] == 1) &
            (d['is_blacklisted'] == 0) & (d['season_k_per_9'] >= 8.0) &
            (d['season_k_per_9'] < 9.0) & (d['edge'] >= 0.75)
        )),
    ]:
        print(f"\n  {name}:")
        for label, dataset in [("Regressor", df), ("Classifier", df_cls)]:
            filtered = dataset[mask_fn_str(dataset)]
            if len(filtered) > 0:
                filtered = filtered.copy()
                filtered['sub_rank'] = filtered.groupby('game_date')['edge'].rank(ascending=False, method='first')
                for top_n in [1, 2, 3]:
                    top_df = filtered[filtered['sub_rank'] <= top_n]
                    stats = compute_hr(top_df)
                    print(f"    [{label}] Top-{top_n}: {stats['hr']:.1f}% (N={stats['n']}) | "
                          f"2024: {stats['hr_2024']:.1f}% | 2025: {stats['hr_2025']:.1f}%")

    # =============================================================================
    # SECTION 12: EXHAUSTIVE 2-FILTER ON FULL REGRESSOR SET
    # =============================================================================
    print("\n" + "=" * 100)
    print("SECTION 12: EXHAUSTIVE SIGNAL SEARCH ON RAW DATA (no top-3, no base)")
    print("=" * 100)
    print("Testing all combinations on raw OVER + !BL + half-line from regressor")

    raw_base = df[
        (df['is_over_pred'] == 1) &
        (df['is_half_line'] == 1) &
        (df['is_blacklisted'] == 0)
    ]
    print(f"Raw base: {len(raw_base)} predictions, HR: {raw_base['correct'].mean()*100:.1f}%")

    all_filters = {
        'edge>=0.75': lambda d: d['edge'] >= 0.75,
        'edge>=1.0': lambda d: d['edge'] >= 1.0,
        'edge>=1.25': lambda d: d['edge'] >= 1.25,
        'edge>=1.5': lambda d: d['edge'] >= 1.5,
        'home': lambda d: d['is_home'] == 1,
        'proj>line': lambda d: d['projection_above_line'] == 1,
        'line<=4.5': lambda d: d['low_line'] == 1,
        'line<=3.5': lambda d: d['strikeouts_line'] <= 3.5,
        'k_avg>line': lambda d: d['k_avg_above_line'] == 1,
        'rest>=6': lambda d: d['long_rest'] == 1,
        'K/9>=8': lambda d: d['good_k_pitcher'] == 1,
        'K/9<9': lambda d: d['avoid_ace_trap'] == 1,
        'K/9_8-9': lambda d: d['good_k_no_trap'] == 1,
        'line_3.5': lambda d: d['strikeouts_line'] == 3.5,
        'line_4.5': lambda d: d['strikeouts_line'] == 4.5,
        'line_5.5': lambda d: d['strikeouts_line'] == 5.5,
        'line_6.5': lambda d: d['strikeouts_line'] == 6.5,
        'line_7.5': lambda d: d['strikeouts_line'] == 7.5,
        'day_game': lambda d: d['is_day_game'] == 1,
        'night_game': lambda d: d['is_day_game'] == 0,
    }

    # Singles
    print("\n--- Singles ---")
    single_results_raw = []
    for name, fn in all_filters.items():
        filtered = raw_base[fn(raw_base)]
        if len(filtered) < 15:
            continue
        stats = compute_hr(filtered)
        single_results_raw.append((name, stats))

    single_results_raw.sort(key=lambda x: x[1]['hr'], reverse=True)
    for name, stats in single_results_raw[:15]:
        stable_str = "S" if stats['stable'] else "U"
        print(f"  + {name}: {stats['hr']:.1f}% (N={stats['n']}) | "
              f"2024: {stats['hr_2024']:.1f}% | 2025: {stats['hr_2025']:.1f}% | [{stable_str}]")

    # Pairs
    print("\n--- Pairs (N>=15, sorted by HR) ---")
    pair_results_raw = []
    filter_names = list(all_filters.keys())
    for i in range(len(filter_names)):
        for j in range(i+1, len(filter_names)):
            n1, n2 = filter_names[i], filter_names[j]
            filtered = raw_base[all_filters[n1](raw_base) & all_filters[n2](raw_base)]
            if len(filtered) < 15:
                continue
            stats = compute_hr(filtered)
            pair_results_raw.append((f"{n1} + {n2}", stats))

    pair_results_raw.sort(key=lambda x: x[1]['hr'], reverse=True)
    for name, stats in pair_results_raw[:20]:
        stable_str = "S" if stats['stable'] else "U"
        print(f"  {name}: {stats['hr']:.1f}% (N={stats['n']}) | "
              f"2024: {stats['hr_2024']:.1f}% | 2025: {stats['hr_2025']:.1f}% | [{stable_str}]")

    # Triples
    print("\n--- Triples (N>=15, sorted by HR) ---")
    triple_results_raw = []
    for i in range(len(filter_names)):
        for j in range(i+1, len(filter_names)):
            for k in range(j+1, len(filter_names)):
                n1, n2, n3 = filter_names[i], filter_names[j], filter_names[k]
                filtered = raw_base[
                    all_filters[n1](raw_base) & all_filters[n2](raw_base) & all_filters[n3](raw_base)
                ]
                if len(filtered) < 15:
                    continue
                stats = compute_hr(filtered)
                triple_results_raw.append((f"{n1} + {n2} + {n3}", stats))

    triple_results_raw.sort(key=lambda x: x[1]['hr'], reverse=True)
    for name, stats in triple_results_raw[:20]:
        stable_str = "S" if stats['stable'] else "U"
        print(f"  {name}: {stats['hr']:.1f}% (N={stats['n']}) | "
              f"2024: {stats['hr_2024']:.1f}% | 2025: {stats['hr_2025']:.1f}% | [{stable_str}]")

    # =============================================================================
    # SECTION 13: BOOTSTRAP THE ABSOLUTE BEST CROSS-SEASON STABLE CANDIDATES
    # =============================================================================
    print("\n" + "=" * 100)
    print("SECTION 13: FINAL BOOTSTRAP — Best stable candidates from exhaustive search")
    print("=" * 100)

    # Collect stable triples with HR >= 60%
    best_stable = []
    for name, stats in triple_results_raw:
        if stats['stable'] and stats['hr'] >= 58 and stats['n'] >= 20:
            best_stable.append((name, stats))
    for name, stats in pair_results_raw:
        if stats['stable'] and stats['hr'] >= 58 and stats['n'] >= 30:
            best_stable.append((name, stats))

    best_stable.sort(key=lambda x: x[1]['hr'], reverse=True)

    print(f"\nStable candidates with HR >= 58%:")
    for name, stats in best_stable[:15]:
        # Reconstruct mask
        parts = [p.strip() for p in name.split("+")]
        parts = [p.strip() for p in parts]
        valid = all(p in all_filters for p in parts)
        if not valid:
            continue

        combined = raw_base.copy()
        for p in parts:
            combined = combined[all_filters[p](combined)]

        ci_low, ci_med, ci_high = bootstrap_ci(combined)
        ppd = picks_per_day(combined)
        ci_70 = "YES" if ci_high >= 70 else "no"
        ci_65 = "YES" if ci_high >= 65 else "no"
        print(f"\n  {name}")
        print(f"    HR: {stats['hr']:.1f}% (N={stats['n']}) | 95% CI: [{ci_low:.1f}%, {ci_high:.1f}%]")
        print(f"    2024: {stats['hr_2024']:.1f}% (N={stats['n_2024']}) | 2025: {stats['hr_2025']:.1f}% (N={stats['n_2025']})")
        print(f"    70% in CI: {ci_70} | 65% in CI: {ci_65} | {ppd:.1f}/day")

        # Top-1 / Top-2
        combined_r = combined.copy()
        combined_r['sub_rank'] = combined_r.groupby('game_date')['edge'].rank(ascending=False, method='first')
        for top_n in [1, 2]:
            top_df = combined_r[combined_r['sub_rank'] <= top_n]
            ts = compute_hr(top_df)
            ci_l, _, ci_h = bootstrap_ci(top_df)
            ppd_n = picks_per_day(top_df)
            print(f"    Top-{top_n}: {ts['hr']:.1f}% (N={ts['n']}) CI: [{ci_l:.1f}%, {ci_h:.1f}%] | {ppd_n:.1f}/day")

    # =============================================================================
    # DEFINITIVE ANSWER
    # =============================================================================
    print("\n" + "=" * 100)
    print("DEFINITIVE ANSWER")
    print("=" * 100)

    # Find the single best cross-season stable candidate
    best_overall = None
    best_hr = 0
    for name, stats in best_stable:
        if stats['stable'] and stats['n'] >= 20 and stats['hr'] > best_hr:
            best_overall = (name, stats)
            best_hr = stats['hr']

    # Also check structural
    struct_candidates = []
    for name, mask in structural_tests.items():
        filtered = df[mask]
        if len(filtered) >= 20:
            stats = compute_hr(filtered)
            if stats['stable']:
                struct_candidates.append((name, stats))

    struct_candidates.sort(key=lambda x: x[1]['hr'], reverse=True)

    print(f"""
QUESTION: Is 70% HR achievable with cross-season stability?

BEST CROSS-SEASON STABLE CANDIDATES:
""")

    all_final = best_stable[:5] + struct_candidates[:3]
    all_final.sort(key=lambda x: x[1]['hr'], reverse=True)
    for name, stats in all_final[:8]:
        print(f"  {stats['hr']:.1f}% | N={stats['n']:3d} | Gap={stats['gap']:.1f}pp | {name}")

    if all_final:
        ceiling = max(s['hr'] for _, s in all_final)
    else:
        ceiling = 0

    print(f"""
CEILING FOR CROSS-SEASON STABLE ULTRA: ~{ceiling:.0f}%

The answer depends on what the data shows above. Look at the 95% CIs:
- If the best stable candidate's CI upper bound reaches 70%, then 70% is PLAUSIBLE but not guaranteed
- If no candidate's CI upper bound reaches 65%, then 65% is the hard ceiling
- With N < 100, any HR above 65% has a CI wide enough to be noise
""")

    # Final summary of the real ceiling
    print("\nFINAL VERDICT:")
    if ceiling >= 70:
        print(f"  70%+ IS achievable: {all_final[0][0]} at {ceiling:.1f}%")
        print(f"  BUT verify N >= 50 and cross-season gap < 5pp before trusting this.")
    elif ceiling >= 65:
        print(f"  65-70% is the realistic ceiling. Best stable: {ceiling:.1f}%")
        print(f"  70% would require N < 30 subsets (unreliable) or new signals.")
    else:
        print(f"  Real ceiling is ~{ceiling:.0f}% for any cross-season stable filter combo.")
        print(f"  70% is NOT achievable with current signals + cross-season validation.")


if __name__ == "__main__":
    main()
