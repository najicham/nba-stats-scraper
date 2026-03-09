#!/usr/bin/env python3
"""MLB Signal & Filter Stack Optimization — comprehensive walk-forward analysis.

Reads regressor walk-forward predictions (all edges) and runs:
1. Individual filter evaluation (13+ candidate filters)
2. Additive filter stacking (ordered by individual lift)
3. Signal stacking for OVER ranking (positive signals)
4. UNDER feasibility deep-dive
5. Edge floor sensitivity with top-3 selection
6. Interaction effects (filter combos)

Uses lowest-edge file (0.25) to get full prediction universe,
then applies our own edge floors.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# CONFIG
# =============================================================================

# Use regressor predictions — full universe at edge 0.25
DATA_FILE = Path('/home/naji/code/nba-stats-scraper/results/mlb_walkforward_v4_regression/predictions_regression_120d_edge0.25.csv')

# Also load the rich classifier for comparison
CLASSIFIER_FILE = Path('/home/naji/code/nba-stats-scraper/results/mlb_walkforward_v4_rich/predictions_catboost_120d_fixed_edge0.5.csv')

# Current blacklist from signals.py
CURRENT_BLACKLIST = frozenset([
    'freddy_peralta', 'tyler_glasnow', 'tanner_bibee', 'mitchell_parker',
    'hunter_greene', 'yusei_kikuchi', 'casey_mize', 'paul_skenes',
    'jose_soriano', 'mitch_keller',
])

CURRENT_BAD_OPPONENTS = frozenset(['KC', 'MIA', 'CWS'])
CURRENT_BAD_VENUES = frozenset([
    'loanDepot park', 'Rate Field', 'Sutter Health Park', 'Busch Stadium',
])

MIN_BLOCKED_N = 20  # Minimum blocked picks for valid filter eval

# =============================================================================
# LOAD DATA
# =============================================================================

print("=" * 90)
print("MLB SIGNAL & FILTER STACK OPTIMIZATION")
print("=" * 90)

df = pd.read_csv(DATA_FILE)
print(f"\nLoaded {len(df)} regressor predictions from {DATA_FILE.name}")
print(f"Date range: {df['game_date'].min()} to {df['game_date'].max()}")
print(f"Unique pitchers: {df['pitcher_lookup'].nunique()}")
print(f"Unique game dates: {df['game_date'].nunique()}")

# Basic stats
print(f"\nOverall HR: {df['correct'].mean():.1%} (N={len(df)})")
over = df[df['predicted_over'] == 1]
under = df[df['predicted_over'] == 0]
print(f"OVER predictions:  {over['correct'].mean():.1%} (N={len(over)})")
print(f"UNDER predictions: {under['correct'].mean():.1%} (N={len(under)})")

# Edge distribution
print(f"\nEdge distribution (abs_edge):")
for threshold in [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
    subset = df[df['abs_edge'] >= threshold]
    if len(subset) > 0:
        print(f"  edge >= {threshold:.2f}: {subset['correct'].mean():.1%} (N={len(subset)})")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def hr_with_ci(series, label=""):
    """Return HR with 95% CI and N."""
    n = len(series)
    if n == 0:
        return {"hr": 0, "n": 0, "ci_low": 0, "ci_high": 0}
    hr = series.mean()
    se = np.sqrt(hr * (1 - hr) / n) if n > 1 else 0
    return {
        "hr": hr,
        "n": n,
        "ci_low": max(0, hr - 1.96 * se),
        "ci_high": min(1, hr + 1.96 * se),
    }


def filter_eval(df_base, mask_blocked, filter_name, min_blocked=MIN_BLOCKED_N):
    """Evaluate a single filter: blocked HR, remaining HR, lift."""
    n_total = len(df_base)
    blocked = df_base[mask_blocked]
    remaining = df_base[~mask_blocked]

    base_hr = df_base['correct'].mean()
    blocked_hr = blocked['correct'].mean() if len(blocked) > 0 else float('nan')
    remaining_hr = remaining['correct'].mean() if len(remaining) > 0 else float('nan')
    lift = remaining_hr - base_hr if not np.isnan(remaining_hr) else 0

    valid = len(blocked) >= min_blocked

    return {
        'filter': filter_name,
        'base_hr': base_hr,
        'base_n': n_total,
        'blocked_hr': blocked_hr,
        'blocked_n': len(blocked),
        'remaining_hr': remaining_hr,
        'remaining_n': len(remaining),
        'lift_pp': lift * 100,
        'valid': valid,
        'pct_blocked': len(blocked) / n_total * 100 if n_total > 0 else 0,
    }


def print_filter_table(results, title=""):
    """Pretty-print filter evaluation results."""
    if title:
        print(f"\n{'=' * 90}")
        print(f"  {title}")
        print(f"{'=' * 90}")

    # Sort by lift descending
    results_sorted = sorted(results, key=lambda x: x.get('lift_pp', 0), reverse=True)

    print(f"{'Filter':<35} {'Base HR':>8} {'Blocked HR':>11} {'Blocked N':>10} "
          f"{'Remain HR':>10} {'Remain N':>9} {'Lift':>7} {'Valid':>6}")
    print("-" * 100)

    for r in results_sorted:
        valid_flag = "YES" if r['valid'] else "no"
        blocked_hr_str = f"{r['blocked_hr']:.1%}" if not np.isnan(r['blocked_hr']) else "N/A"
        remaining_hr_str = f"{r['remaining_hr']:.1%}" if not np.isnan(r['remaining_hr']) else "N/A"
        print(f"{r['filter']:<35} {r['base_hr']:>7.1%} {blocked_hr_str:>11} {r['blocked_n']:>10} "
              f"{remaining_hr_str:>10} {r['remaining_n']:>9} {r['lift_pp']:>+6.1f}pp {valid_flag:>5}")


# =============================================================================
# 1. INDIVIDUAL FILTER EVALUATION
# =============================================================================

print("\n\n" + "=" * 90)
print("  SECTION 1: INDIVIDUAL FILTER EVALUATION (OVER PICKS)")
print("=" * 90)

# Work with OVER predictions at edge >= 0.5 (regressor sweet spot start)
over_base = df[(df['predicted_over'] == 1) & (df['abs_edge'] >= 0.5)].copy()
print(f"\nBase: OVER picks at edge >= 0.5: {over_base['correct'].mean():.1%} (N={len(over_base)})")

filter_results = []

# --- 1a. Pitcher Blacklist (validate current list) ---
mask = over_base['pitcher_lookup'].isin(CURRENT_BLACKLIST)
filter_results.append(filter_eval(over_base, mask, "pitcher_blacklist (current)"))

# Find ALL pitchers with <45% HR at N >= 8
pitcher_hr = over_base.groupby('pitcher_lookup').agg(
    hr=('correct', 'mean'),
    n=('correct', 'count')
).reset_index()
bad_pitchers = pitcher_hr[(pitcher_hr['hr'] < 0.45) & (pitcher_hr['n'] >= 8)]
print(f"\n  Pitchers with <45% HR, N >= 8 (OVER, edge >= 0.5):")
for _, row in bad_pitchers.sort_values('hr').iterrows():
    in_bl = "  [IN BLACKLIST]" if row['pitcher_lookup'] in CURRENT_BLACKLIST else "  **MISSING**"
    print(f"    {row['pitcher_lookup']:<25} {row['hr']:.1%} (N={row['n']}){in_bl}")

# Expanded blacklist with all <45% HR pitchers
expanded_blacklist = frozenset(bad_pitchers['pitcher_lookup'].tolist())
mask_expanded = over_base['pitcher_lookup'].isin(expanded_blacklist)
filter_results.append(filter_eval(over_base, mask_expanded, "pitcher_blacklist (expanded)"))

# --- 1b. Bad Opponents (validate KC/MIA/CWS + find others) ---
mask = over_base['opponent_team_abbr'].isin(CURRENT_BAD_OPPONENTS)
filter_results.append(filter_eval(over_base, mask, "bad_opponent (KC/MIA/CWS)"))

# Find ALL opponents with <50% HR
opp_hr = over_base.groupby('opponent_team_abbr').agg(
    hr=('correct', 'mean'),
    n=('correct', 'count')
).reset_index()
bad_opps = opp_hr[(opp_hr['hr'] < 0.50) & (opp_hr['n'] >= 15)]
print(f"\n  Opponents with <50% OVER HR, N >= 15:")
for _, row in bad_opps.sort_values('hr').iterrows():
    in_list = "  [IN LIST]" if row['opponent_team_abbr'] in CURRENT_BAD_OPPONENTS else "  **NEW**"
    print(f"    vs {row['opponent_team_abbr']:<5} {row['hr']:.1%} (N={row['n']}){in_list}")

# Show ALL opponent HRs
print(f"\n  ALL opponents OVER HR:")
for _, row in opp_hr.sort_values('hr').iterrows():
    marker = " <-- BAD" if row['hr'] < 0.50 and row['n'] >= 15 else ""
    print(f"    vs {row['opponent_team_abbr']:<5} {row['hr']:.1%} (N={row['n']}){marker}")

expanded_bad_opps = frozenset(bad_opps['opponent_team_abbr'].tolist())
mask_expanded_opp = over_base['opponent_team_abbr'].isin(expanded_bad_opps)
filter_results.append(filter_eval(over_base, mask_expanded_opp, "bad_opponent (expanded)"))

# --- 1c. Bad Venues (validate current + find others) ---
mask = over_base['venue'].isin(CURRENT_BAD_VENUES)
filter_results.append(filter_eval(over_base, mask, "bad_venue (current)"))

venue_hr = over_base.groupby('venue').agg(
    hr=('correct', 'mean'),
    n=('correct', 'count')
).reset_index()
bad_venues = venue_hr[(venue_hr['hr'] < 0.48) & (venue_hr['n'] >= 10)]
print(f"\n  Venues with <48% OVER HR, N >= 10:")
for _, row in bad_venues.sort_values('hr').iterrows():
    in_list = "  [IN LIST]" if row['venue'] in CURRENT_BAD_VENUES else "  **NEW**"
    print(f"    {row['venue']:<30} {row['hr']:.1%} (N={row['n']}){in_list}")

expanded_bad_venues = frozenset(bad_venues['venue'].tolist())
mask_expanded_venue = over_base['venue'].isin(expanded_bad_venues)
filter_results.append(filter_eval(over_base, mask_expanded_venue, "bad_venue (expanded)"))

# --- 1d. Low K/9 Pitcher ---
mask_k9_6 = over_base['season_k_per_9'] < 6.0
mask_k9_7 = over_base['season_k_per_9'] < 7.0
filter_results.append(filter_eval(over_base, mask_k9_6, "low_k9 (< 6.0)"))
filter_results.append(filter_eval(over_base, mask_k9_7, "low_k9 (< 7.0)"))

# --- 1e. High Line Filter (line >= 7.5 — overpriced aces?) ---
mask_high_line = over_base['strikeouts_line'] >= 7.5
filter_results.append(filter_eval(over_base, mask_high_line, "high_line (>= 7.5)"))

mask_high_line_7 = over_base['strikeouts_line'] >= 7.0
filter_results.append(filter_eval(over_base, mask_high_line_7, "high_line (>= 7.0)"))

# --- 1f. Low Line Filter (line <= 3.5) ---
mask_low_line = over_base['strikeouts_line'] <= 3.5
filter_results.append(filter_eval(over_base, mask_low_line, "low_line (<= 3.5)"))

mask_low_line_4 = over_base['strikeouts_line'] <= 4.0
filter_results.append(filter_eval(over_base, mask_low_line_4, "low_line (<= 4.0)"))

# --- 1g. Short Rest (< 4 days) ---
mask_short_rest = over_base['days_rest'] < 4
filter_results.append(filter_eval(over_base, mask_short_rest, "short_rest (< 4d)"))

mask_short_rest_3 = over_base['days_rest'] <= 3
filter_results.append(filter_eval(over_base, mask_short_rest_3, "short_rest (<= 3d)"))

# --- 1h. Long Rest Signal (>= 7 days, >= 8 days) ---
# This is a POSITIVE signal, not a filter — but test if non-long-rest is worse
mask_long_rest_7 = over_base['days_rest'] >= 7
mask_long_rest_8 = over_base['days_rest'] >= 8
# Show long rest as a positive signal (high HR)
lr7 = over_base[mask_long_rest_7]
lr8 = over_base[mask_long_rest_8]
print(f"\n  Long rest (OVER, edge >= 0.5):")
print(f"    days_rest >= 7: {lr7['correct'].mean():.1%} (N={len(lr7)})")
print(f"    days_rest >= 8: {lr8['correct'].mean():.1%} (N={len(lr8)})")
print(f"    days_rest < 7:  {over_base[~mask_long_rest_7]['correct'].mean():.1%} (N={len(over_base[~mask_long_rest_7])})")

# --- 1i. Projection Disagrees (projection < line) ---
over_with_proj = over_base.dropna(subset=['projection_value'])
mask_proj_disagree = over_with_proj['projection_value'] < over_with_proj['strikeouts_line']
filter_results.append(filter_eval(over_with_proj, mask_proj_disagree, "projection_disagrees (proj < line)"))

# Stronger: projection < line - 0.5
mask_proj_strong_disagree = over_with_proj['projection_value'] < (over_with_proj['strikeouts_line'] - 0.5)
filter_results.append(filter_eval(over_with_proj, mask_proj_strong_disagree, "projection_disagrees (proj < line-0.5)"))

# --- 1j. Away Pitcher Filter ---
mask_away = over_base['is_home'] == 0
filter_results.append(filter_eval(over_base, mask_away, "away_pitcher"))

# --- 1k. Day Game Filter ---
mask_day = over_base['is_day_game'] == 1
filter_results.append(filter_eval(over_base, mask_day, "day_game"))

# --- 1l. Recent Cold Streak (k_avg_last_5 < line) ---
mask_cold = over_base['k_avg_last_5'] < over_base['strikeouts_line']
filter_results.append(filter_eval(over_base, mask_cold, "cold_streak (avg5 < line)"))

# Stronger: k_avg_last_5 < line - 1
mask_cold_strong = over_base['k_avg_last_5'] < (over_base['strikeouts_line'] - 1.0)
filter_results.append(filter_eval(over_base, mask_cold_strong, "cold_streak (avg5 < line-1)"))

# --- 1m. Recent Hot Streak (k_avg_last_5 > line + 1) — positive signal ---
mask_hot = over_base['k_avg_last_5'] > (over_base['strikeouts_line'] + 1.0)
hot = over_base[mask_hot]
not_hot = over_base[~mask_hot]
print(f"\n  Hot streak (k_avg_last_5 > line + 1.0):")
print(f"    HOT:     {hot['correct'].mean():.1%} (N={len(hot)})")
print(f"    NOT HOT: {not_hot['correct'].mean():.1%} (N={len(not_hot)})")

# --- 1n. Overconfidence (edge > 2.0) ---
mask_overconf = over_base['abs_edge'] > 2.0
filter_results.append(filter_eval(over_base, mask_overconf, "overconfidence (edge > 2.0)"))

mask_overconf_1_75 = over_base['abs_edge'] > 1.75
filter_results.append(filter_eval(over_base, mask_overconf_1_75, "overconfidence (edge > 1.75)"))

# Print filter summary
print_filter_table(filter_results, "INDIVIDUAL FILTER RESULTS (OVER, edge >= 0.5)")


# =============================================================================
# 2. ADDITIVE FILTER STACKING
# =============================================================================

print("\n\n" + "=" * 90)
print("  SECTION 2: ADDITIVE FILTER STACKING (OVER, edge >= 0.5)")
print("=" * 90)

# Only use valid filters with positive lift
valid_filters = [r for r in filter_results if r['valid'] and r['lift_pp'] > 0]
valid_filters_sorted = sorted(valid_filters, key=lambda x: x['lift_pp'], reverse=True)

print(f"\n  Filters with positive lift and N >= {MIN_BLOCKED_N} blocked:")
for r in valid_filters_sorted:
    print(f"    {r['filter']:<35} lift: {r['lift_pp']:>+5.1f}pp, blocked: {r['blocked_n']}, "
          f"blocked HR: {r['blocked_hr']:.1%}")

# Define filter masks for stacking (using the BEST version of each filter type)
# We'll use a curated list, picking best threshold per filter category
def make_filter_masks(df_in):
    """Create named filter masks."""
    masks = {}

    # Pitcher blacklist (expanded)
    masks['pitcher_blacklist'] = df_in['pitcher_lookup'].isin(expanded_blacklist)

    # Bad opponents (expanded)
    masks['bad_opponent'] = df_in['opponent_team_abbr'].isin(expanded_bad_opps)

    # Bad venues (expanded)
    masks['bad_venue'] = df_in['venue'].isin(expanded_bad_venues)

    # Low K/9
    masks['low_k9_lt7'] = df_in['season_k_per_9'] < 7.0
    masks['low_k9_lt6'] = df_in['season_k_per_9'] < 6.0

    # High line
    masks['high_line_7'] = df_in['strikeouts_line'] >= 7.0
    masks['high_line_7_5'] = df_in['strikeouts_line'] >= 7.5

    # Low line
    masks['low_line_3_5'] = df_in['strikeouts_line'] <= 3.5
    masks['low_line_4'] = df_in['strikeouts_line'] <= 4.0

    # Short rest
    masks['short_rest_lt4'] = df_in['days_rest'] < 4

    # Projection disagrees (need to handle NaN)
    proj_valid = df_in['projection_value'].notna()
    masks['proj_disagrees'] = proj_valid & (df_in['projection_value'] < df_in['strikeouts_line'])
    masks['proj_strong_disagree'] = proj_valid & (df_in['projection_value'] < (df_in['strikeouts_line'] - 0.5))

    # Away pitcher
    masks['away_pitcher'] = df_in['is_home'] == 0

    # Day game
    masks['day_game'] = df_in['is_day_game'] == 1

    # Cold streak
    masks['cold_streak'] = df_in['k_avg_last_5'] < df_in['strikeouts_line']
    masks['cold_streak_strong'] = df_in['k_avg_last_5'] < (df_in['strikeouts_line'] - 1.0)

    # Overconfidence
    masks['overconfidence_2'] = df_in['abs_edge'] > 2.0
    masks['overconfidence_1_75'] = df_in['abs_edge'] > 1.75

    return masks


# Additive stacking: start with best, add next best, track cumulative
# Use one version per category (best version)
stacking_order_candidates = [
    # (filter_name, mask_key) — ordered by individual lift (we'll sort by actual)
    ("overconfidence (>2.0)", "overconfidence_2"),
    ("pitcher_blacklist", "pitcher_blacklist"),
    ("bad_opponent", "bad_opponent"),
    ("bad_venue", "bad_venue"),
    ("low_k9 (<7.0)", "low_k9_lt7"),
    ("low_k9 (<6.0)", "low_k9_lt6"),
    ("high_line (>=7.5)", "high_line_7_5"),
    ("high_line (>=7.0)", "high_line_7"),
    ("low_line (<=3.5)", "low_line_3_5"),
    ("short_rest (<4d)", "short_rest_lt4"),
    ("projection_disagrees", "proj_disagrees"),
    ("proj_strong_disagree", "proj_strong_disagree"),
    ("away_pitcher", "away_pitcher"),
    ("day_game", "day_game"),
    ("cold_streak (avg5<line)", "cold_streak"),
    ("cold_streak_strong", "cold_streak_strong"),
]

# First compute individual lifts to sort
masks = make_filter_masks(over_base)
individual_lifts = []
for name, key in stacking_order_candidates:
    m = masks[key]
    remaining = over_base[~m]
    if m.sum() >= 5 and len(remaining) > 0:  # At least 5 blocked
        lift = remaining['correct'].mean() - over_base['correct'].mean()
        individual_lifts.append((name, key, lift, m.sum()))

individual_lifts.sort(key=lambda x: x[2], reverse=True)

print(f"\n  Additive stacking order (by individual lift):")
print(f"  {'Step':<4} {'Filter':<35} {'Indiv Lift':>11} {'Blocked':>8}")
print(f"  {'-'*62}")
for i, (name, key, lift, blocked) in enumerate(individual_lifts, 1):
    print(f"  {i:<4} {name:<35} {lift*100:>+9.1f}pp {blocked:>8}")

# Now do additive stacking
print(f"\n  Cumulative stacking results:")
print(f"  {'Step':<4} {'Filter Added':<35} {'Cum HR':>8} {'Cum N':>7} {'Cum Lift':>9} {'Marginal':>9}")
print(f"  {'-'*76}")

combined_mask = pd.Series(False, index=over_base.index)
base_hr = over_base['correct'].mean()
prev_hr = base_hr

print(f"  {'0':<4} {'(baseline)':<35} {base_hr:>7.1%} {len(over_base):>7} {0:>+8.1f}pp {0:>+8.1f}pp")

stacking_results = [{'step': 0, 'filter': '(baseline)', 'hr': base_hr, 'n': len(over_base), 'cum_lift': 0, 'marginal': 0}]

for i, (name, key, indiv_lift, blocked) in enumerate(individual_lifts, 1):
    combined_mask = combined_mask | masks[key]
    remaining = over_base[~combined_mask]
    if len(remaining) == 0:
        break
    cum_hr = remaining['correct'].mean()
    cum_lift = (cum_hr - base_hr) * 100
    marginal = (cum_hr - prev_hr) * 100

    stacking_results.append({
        'step': i, 'filter': name, 'hr': cum_hr, 'n': len(remaining),
        'cum_lift': cum_lift, 'marginal': marginal,
    })

    print(f"  {i:<4} {name:<35} {cum_hr:>7.1%} {len(remaining):>7} {cum_lift:>+8.1f}pp {marginal:>+8.1f}pp")
    prev_hr = cum_hr

# Find optimal stack (highest HR with reasonable N)
print(f"\n  Optimal stack analysis (HR * sqrt(N) proxy for profit):")
for r in stacking_results:
    proxy = r['hr'] * np.sqrt(r['n'])
    print(f"    Step {r['step']}: HR {r['hr']:.1%}, N={r['n']}, proxy={proxy:.1f}")


# =============================================================================
# 3. SIGNAL STACKING FOR OVER RANKING
# =============================================================================

print("\n\n" + "=" * 90)
print("  SECTION 3: POSITIVE SIGNALS FOR OVER RANKING")
print("=" * 90)

# Work with OVER predictions at edge >= 0.75 (production edge floor)
over_prod = df[(df['predicted_over'] == 1) & (df['abs_edge'] >= 0.75)].copy()
print(f"\nBase: OVER picks at edge >= 0.75: {over_prod['correct'].mean():.1%} (N={len(over_prod)})")

# Define positive signal flags
over_prod['sig_projection_agrees'] = over_prod['projection_value'] > over_prod['strikeouts_line']
over_prod['sig_home'] = over_prod['is_home'] == 1
over_prod['sig_long_rest'] = over_prod['days_rest'] >= 7
over_prod['sig_high_k9'] = over_prod['season_k_per_9'] >= 9.0
over_prod['sig_high_k9_10'] = over_prod['season_k_per_9'] >= 10.0
over_prod['sig_hot_streak'] = over_prod['k_avg_last_5'] > (over_prod['strikeouts_line'] + 1.0)
over_prod['sig_night_game'] = over_prod['is_day_game'] == 0
over_prod['sig_proj_strong'] = over_prod['projection_value'] > (over_prod['strikeouts_line'] + 0.5)
over_prod['sig_avg5_above'] = over_prod['k_avg_last_5'] > over_prod['strikeouts_line']

signal_names = [
    ('sig_projection_agrees', 'Projection agrees (proj > line)'),
    ('sig_proj_strong', 'Projection strong agrees (proj > line+0.5)'),
    ('sig_home', 'Home pitcher'),
    ('sig_long_rest', 'Long rest (>= 7d)'),
    ('sig_high_k9', 'High K/9 (>= 9.0)'),
    ('sig_high_k9_10', 'Elite K/9 (>= 10.0)'),
    ('sig_hot_streak', 'Hot streak (avg5 > line+1)'),
    ('sig_night_game', 'Night game'),
    ('sig_avg5_above', 'Recent K avg > line'),
]

print(f"\n  {'Signal':<40} {'With':>8} {'N_with':>8} {'Without':>10} {'N_without':>10} {'Lift':>8}")
print(f"  {'-'*88}")

signal_results_list = []
for col, name in signal_names:
    with_sig = over_prod[over_prod[col] == True]
    without_sig = over_prod[over_prod[col] == False]
    with_hr = with_sig['correct'].mean() if len(with_sig) > 0 else 0
    without_hr = without_sig['correct'].mean() if len(without_sig) > 0 else 0
    lift = with_hr - without_hr
    signal_results_list.append({
        'signal': name, 'col': col, 'with_hr': with_hr, 'n_with': len(with_sig),
        'without_hr': without_hr, 'n_without': len(without_sig), 'lift': lift
    })
    print(f"  {name:<40} {with_hr:>7.1%} {len(with_sig):>8} {without_hr:>9.1%} {len(without_sig):>10} {lift*100:>+7.1f}pp")

# Signal count analysis
over_prod['signal_count'] = (
    over_prod['sig_projection_agrees'].astype(int) +
    over_prod['sig_home'].astype(int) +
    over_prod['sig_long_rest'].astype(int) +
    over_prod['sig_high_k9'].astype(int) +
    over_prod['sig_hot_streak'].astype(int) +
    over_prod['sig_night_game'].astype(int) +
    over_prod['sig_avg5_above'].astype(int)
)

print(f"\n  Signal count distribution (OVER, edge >= 0.75):")
for sc in sorted(over_prod['signal_count'].unique()):
    subset = over_prod[over_prod['signal_count'] == sc]
    print(f"    SC={sc}: {subset['correct'].mean():.1%} (N={len(subset)})")

print(f"\n  Signal count >= N:")
for min_sc in range(1, 7):
    subset = over_prod[over_prod['signal_count'] >= min_sc]
    if len(subset) > 0:
        print(f"    SC >= {min_sc}: {subset['correct'].mean():.1%} (N={len(subset)})")


# =============================================================================
# 4. UNDER FEASIBILITY DEEP-DIVE
# =============================================================================

print("\n\n" + "=" * 90)
print("  SECTION 4: UNDER FEASIBILITY (regressor)")
print("=" * 90)

# UNDER = predicted_over == 0
under_all = df[df['predicted_over'] == 0].copy()
print(f"\nUNDER predictions: {under_all['correct'].mean():.1%} (N={len(under_all)})")

# Edge bucketing for UNDER
print(f"\n  UNDER by edge bucket:")
for lo, hi in [(0.25, 0.5), (0.5, 0.75), (0.75, 1.0), (1.0, 1.5), (1.5, 2.0)]:
    subset = under_all[(under_all['abs_edge'] >= lo) & (under_all['abs_edge'] < hi)]
    if len(subset) >= 10:
        print(f"    edge [{lo:.2f}, {hi:.2f}): {subset['correct'].mean():.1%} (N={len(subset)})")

# UNDER filters
under_base = under_all[under_all['abs_edge'] >= 0.5].copy()
print(f"\n  UNDER at edge >= 0.5: {under_base['correct'].mean():.1%} (N={len(under_base)})")

if len(under_base) >= 30:
    under_filters = []

    # Low K/9 + UNDER (pitcher doesn't K much → line is set appropriately)
    mask_low_k9_u = under_base['season_k_per_9'] < 7.0
    under_filters.append(filter_eval(under_base, mask_low_k9_u, "low_k9 (<7.0) UNDER"))

    # High K/9 + UNDER (ace having off day — interesting)
    mask_high_k9_u = under_base['season_k_per_9'] >= 9.0
    subset = under_base[mask_high_k9_u]
    if len(subset) >= 10:
        print(f"\n  High K/9 + UNDER: {subset['correct'].mean():.1%} (N={len(subset)})")

    # Night game + UNDER
    mask_night_u = under_base['is_day_game'] == 0
    under_filters.append(filter_eval(under_base, ~mask_night_u, "night_only UNDER (block day)"))

    # Home + UNDER
    mask_home_u = under_base['is_home'] == 1
    home_under = under_base[mask_home_u]
    away_under = under_base[~mask_home_u]
    print(f"\n  Home vs Away UNDER:")
    print(f"    HOME:  {home_under['correct'].mean():.1%} (N={len(home_under)})")
    print(f"    AWAY:  {away_under['correct'].mean():.1%} (N={len(away_under)})")

    # Projection disagrees with line (projection < line → supports UNDER)
    under_with_proj = under_base.dropna(subset=['projection_value'])
    mask_proj_under = under_with_proj['projection_value'] < under_with_proj['strikeouts_line']
    proj_under_agrees = under_with_proj[mask_proj_under]
    proj_under_disagrees = under_with_proj[~mask_proj_under]
    print(f"\n  Projection + UNDER:")
    print(f"    Proj < line (agrees w/ UNDER): {proj_under_agrees['correct'].mean():.1%} (N={len(proj_under_agrees)})")
    print(f"    Proj >= line (disagrees):      {proj_under_disagrees['correct'].mean():.1%} (N={len(proj_under_disagrees)})")

    # Recent cold + UNDER (avg5 < line → supports UNDER)
    mask_cold_u = under_base['k_avg_last_5'] < under_base['strikeouts_line']
    cold_under = under_base[mask_cold_u]
    not_cold_under = under_base[~mask_cold_u]
    print(f"\n  Cold streak + UNDER:")
    print(f"    avg5 < line (supports UNDER):  {cold_under['correct'].mean():.1%} (N={len(cold_under)})")
    print(f"    avg5 >= line:                   {not_cold_under['correct'].mean():.1%} (N={len(not_cold_under)})")

    # High line + UNDER (ace with inflated line)
    mask_hi_line_u = under_base['strikeouts_line'] >= 6.5
    hi_line_under = under_base[mask_hi_line_u]
    lo_line_under = under_base[~mask_hi_line_u]
    print(f"\n  Line level + UNDER:")
    print(f"    line >= 6.5 (ace under): {hi_line_under['correct'].mean():.1%} (N={len(hi_line_under)})")
    print(f"    line < 6.5:              {lo_line_under['correct'].mean():.1%} (N={len(lo_line_under)})")

    # Short rest + UNDER
    mask_sr_u = under_base['days_rest'] < 4
    sr_under = under_base[mask_sr_u]
    print(f"\n  Short rest + UNDER:")
    print(f"    rest < 4d:  {sr_under['correct'].mean():.1%} (N={len(sr_under)})")
    print(f"    rest >= 4d: {under_base[~mask_sr_u]['correct'].mean():.1%} (N={len(under_base[~mask_sr_u])})")

    # Combo: multiple UNDER signals
    under_base['u_proj_agrees'] = under_base['projection_value'] < under_base['strikeouts_line']
    under_base['u_cold'] = under_base['k_avg_last_5'] < under_base['strikeouts_line']
    under_base['u_high_line'] = under_base['strikeouts_line'] >= 6.5
    under_base['u_away'] = under_base['is_home'] == 0
    under_base['u_signal_count'] = (
        under_base['u_proj_agrees'].astype(int) +
        under_base['u_cold'].astype(int) +
        under_base['u_high_line'].astype(int) +
        under_base['u_away'].astype(int)
    )

    print(f"\n  UNDER signal count (edge >= 0.5):")
    for sc in sorted(under_base['u_signal_count'].dropna().unique()):
        subset = under_base[under_base['u_signal_count'] == sc]
        if len(subset) >= 5:
            print(f"    SC={int(sc)}: {subset['correct'].mean():.1%} (N={len(subset)})")
else:
    print("  Not enough UNDER predictions for deep analysis.")


# =============================================================================
# 5. EDGE FLOOR SENSITIVITY WITH TOP-3 SELECTION
# =============================================================================

print("\n\n" + "=" * 90)
print("  SECTION 5: EDGE FLOOR SENSITIVITY (OVER) — with top-3 daily selection")
print("=" * 90)

over_all = df[df['predicted_over'] == 1].copy()

# Apply best filter stack (overconfidence + blacklist + bad_opp as minimum)
masks_all = make_filter_masks(over_all)

# Recommended filters: overconfidence + pitcher_blacklist + bad_opponent
# (we'll test with and without more aggressive filtering)
filter_sets = {
    'no_filter': pd.Series(False, index=over_all.index),
    'minimal (overconf+BL)': masks_all.get('overconfidence_2', pd.Series(False, index=over_all.index)) | masks_all.get('pitcher_blacklist', pd.Series(False, index=over_all.index)),
    'standard (overconf+BL+opp)': (
        masks_all.get('overconfidence_2', pd.Series(False, index=over_all.index)) |
        masks_all.get('pitcher_blacklist', pd.Series(False, index=over_all.index)) |
        masks_all.get('bad_opponent', pd.Series(False, index=over_all.index))
    ),
    'aggressive (+venue+proj)': (
        masks_all.get('overconfidence_2', pd.Series(False, index=over_all.index)) |
        masks_all.get('pitcher_blacklist', pd.Series(False, index=over_all.index)) |
        masks_all.get('bad_opponent', pd.Series(False, index=over_all.index)) |
        masks_all.get('bad_venue', pd.Series(False, index=over_all.index)) |
        masks_all.get('proj_disagrees', pd.Series(False, index=over_all.index))
    ),
}

for filter_name, filter_mask in filter_sets.items():
    filtered = over_all[~filter_mask].copy()
    print(f"\n  Filter set: {filter_name} ({len(filtered)} predictions)")
    print(f"  {'Edge Floor':<12} {'All HR':>8} {'All N':>7} {'Top3/day HR':>12} {'Top3/day N':>11} {'Picks/day':>10}")
    print(f"  {'-'*64}")

    for edge_floor in [0.25, 0.5, 0.75, 1.0, 1.25, 1.5]:
        eligible = filtered[filtered['abs_edge'] >= edge_floor]
        if len(eligible) == 0:
            continue

        all_hr = eligible['correct'].mean()

        # Top-3 per day by edge
        top3 = eligible.sort_values('abs_edge', ascending=False).groupby('game_date').head(3)
        top3_hr = top3['correct'].mean()
        top3_n = len(top3)

        # Average picks per day
        n_days = eligible['game_date'].nunique()
        picks_per_day = top3_n / n_days if n_days > 0 else 0

        print(f"  {edge_floor:<12.2f} {all_hr:>7.1%} {len(eligible):>7} {top3_hr:>11.1%} {top3_n:>11} {picks_per_day:>9.1f}")


# Also test top-1, top-2, top-3 at different edges
print(f"\n  Top-N selection sensitivity (standard filter, OVER):")
standard_mask = filter_sets['standard (overconf+BL+opp)']
filtered_std = over_all[~standard_mask].copy()

print(f"  {'Edge':<8} {'Top-1 HR':>9} {'N':>5} {'Top-2 HR':>9} {'N':>5} {'Top-3 HR':>9} {'N':>5} {'All HR':>8} {'All N':>7}")
print(f"  {'-'*70}")

for edge_floor in [0.5, 0.75, 1.0, 1.25]:
    eligible = filtered_std[filtered_std['abs_edge'] >= edge_floor]
    if len(eligible) == 0:
        continue

    all_hr = eligible['correct'].mean()
    results_by_n = {}

    for top_n in [1, 2, 3]:
        top = eligible.sort_values('abs_edge', ascending=False).groupby('game_date').head(top_n)
        results_by_n[top_n] = (top['correct'].mean(), len(top))

    print(f"  {edge_floor:<8.2f} "
          f"{results_by_n[1][0]:>8.1%} {results_by_n[1][1]:>5} "
          f"{results_by_n[2][0]:>8.1%} {results_by_n[2][1]:>5} "
          f"{results_by_n[3][0]:>8.1%} {results_by_n[3][1]:>5} "
          f"{all_hr:>7.1%} {len(eligible):>7}")


# =============================================================================
# 6. INTERACTION EFFECTS (filter combos)
# =============================================================================

print("\n\n" + "=" * 90)
print("  SECTION 6: INTERACTION EFFECTS (OVER, edge >= 0.5)")
print("=" * 90)

masks_over = make_filter_masks(over_base)

# Define interaction combos
interactions = [
    ("home + proj_agrees",
     (over_base['is_home'] == 1) & (over_base['projection_value'] > over_base['strikeouts_line']),
     "Positive combo"),
    ("away + proj_disagrees",
     (over_base['is_home'] == 0) & (over_base['projection_value'] < over_base['strikeouts_line']),
     "Double negative"),
    ("home + high_k9",
     (over_base['is_home'] == 1) & (over_base['season_k_per_9'] >= 9.0),
     "Ace at home"),
    ("away + low_k9",
     (over_base['is_home'] == 0) & (over_base['season_k_per_9'] < 7.0),
     "Weak pitcher away"),
    ("bad_opp + high_line",
     over_base['opponent_team_abbr'].isin(expanded_bad_opps) & (over_base['strikeouts_line'] >= 7.0),
     "Ace vs weak lineup"),
    ("proj_agrees + hot_streak",
     (over_base['projection_value'] > over_base['strikeouts_line']) & (over_base['k_avg_last_5'] > (over_base['strikeouts_line'] + 1.0)),
     "Projection + momentum"),
    ("proj_agrees + home",
     (over_base['projection_value'] > over_base['strikeouts_line']) & (over_base['is_home'] == 1),
     "Proj agrees + home"),
    ("proj_disagrees + cold",
     (over_base['projection_value'] < over_base['strikeouts_line']) & (over_base['k_avg_last_5'] < over_base['strikeouts_line']),
     "Double negative (filter)"),
    ("long_rest + home",
     (over_base['days_rest'] >= 7) & (over_base['is_home'] == 1),
     "Fresh arm at home"),
    ("high_edge + proj_agrees",
     (over_base['abs_edge'] >= 1.0) & (over_base['projection_value'] > over_base['strikeouts_line']),
     "High edge + projection"),
    ("high_edge + home + proj",
     (over_base['abs_edge'] >= 1.0) & (over_base['is_home'] == 1) & (over_base['projection_value'] > over_base['strikeouts_line']),
     "Triple positive"),
    ("night + home",
     (over_base['is_day_game'] == 0) & (over_base['is_home'] == 1),
     "Night game at home"),
    ("day + away",
     (over_base['is_day_game'] == 1) & (over_base['is_home'] == 0),
     "Day game away"),
    ("blacklist + bad_opp",
     over_base['pitcher_lookup'].isin(expanded_blacklist) | over_base['opponent_team_abbr'].isin(expanded_bad_opps),
     "Either blacklist or bad opp"),
]

base_hr = over_base['correct'].mean()

print(f"\n  Base HR: {base_hr:.1%} (N={len(over_base)})")
print(f"\n  {'Combo':<40} {'HR':>8} {'N':>6} {'Lift':>8} {'Type'}")
print(f"  {'-'*75}")

for name, mask, combo_type in interactions:
    subset = over_base[mask]
    if len(subset) >= 10:
        hr = subset['correct'].mean()
        lift = (hr - base_hr) * 100
        print(f"  {name:<40} {hr:>7.1%} {len(subset):>6} {lift:>+7.1f}pp {combo_type}")

# Also show what happens if we BLOCK double-negative combos
print(f"\n  Block combos (remove from pool):")
block_combos = [
    ("Block: away + proj_disagrees",
     (over_base['is_home'] == 0) & (over_base['projection_value'] < over_base['strikeouts_line'])),
    ("Block: away + low_k9",
     (over_base['is_home'] == 0) & (over_base['season_k_per_9'] < 7.0)),
    ("Block: proj_disagrees + cold",
     (over_base['projection_value'] < over_base['strikeouts_line']) & (over_base['k_avg_last_5'] < over_base['strikeouts_line'])),
    ("Block: day + away",
     (over_base['is_day_game'] == 1) & (over_base['is_home'] == 0)),
]

for name, mask in block_combos:
    blocked = over_base[mask]
    remaining = over_base[~mask]
    if len(blocked) >= 10 and len(remaining) > 0:
        b_hr = blocked['correct'].mean()
        r_hr = remaining['correct'].mean()
        lift = (r_hr - base_hr) * 100
        print(f"  {name:<40} blocked: {b_hr:.1%} (N={len(blocked)}), "
              f"remaining: {r_hr:.1%} (N={len(remaining)}), lift: {lift:+.1f}pp")


# =============================================================================
# SECTION 7: RECOMMENDED FILTER STACK + SUMMARY
# =============================================================================

print("\n\n" + "=" * 90)
print("  SECTION 7: RECOMMENDED FILTER STACK + FINAL SUMMARY")
print("=" * 90)

# Build recommended stack based on findings
print("""
Based on the analysis above, here is the recommended filter + signal architecture:

NEGATIVE FILTERS (block picks) — in priority order:
  1. overconfidence_cap: edge > 2.0 (high-edge picks are overfit)
  2. pitcher_blacklist: expanded list from walk-forward <45% HR, N >= 8
  3. bad_opponent: expanded list from walk-forward <50% HR, N >= 15
  4. bad_venue: expanded list from walk-forward <48% HR, N >= 10
  5. projection_disagrees: projection < line (model disagrees with external source)

POSITIVE SIGNALS for OVER ranking (boost quality score):
  Weight 3.0: projection_agrees (proj > line)
  Weight 2.5: projection_strong_agrees (proj > line + 0.5)
  Weight 2.0: home_pitcher
  Weight 2.0: hot_streak (avg5 > line + 1.0)
  Weight 1.5: recent_k_above_line (avg5 > line)
  Weight 1.5: long_rest (>= 7 days)
  Weight 1.0: night_game
  Weight 1.0: high_k9 (>= 9.0)
""")

# Final simulation: best-recommended stack with top-3 per day
print(f"  FINAL SIMULATION: recommended stack + top-3/day")
print(f"  {'='*60}")

# Apply recommended filters
over_final = df[df['predicted_over'] == 1].copy()
n_start = len(over_final)

# Filter 1: overconfidence
mask_oc = over_final['abs_edge'] > 2.0
over_final = over_final[~mask_oc]
print(f"  After overconfidence cap (>2.0):     {len(over_final)} ({n_start - len(over_final)} blocked)")

# Filter 2: pitcher blacklist (expanded)
n_before = len(over_final)
mask_bl = over_final['pitcher_lookup'].isin(expanded_blacklist)
over_final = over_final[~mask_bl]
print(f"  After pitcher blacklist:             {len(over_final)} ({n_before - len(over_final)} blocked)")

# Filter 3: bad opponents (expanded)
n_before = len(over_final)
mask_bo = over_final['opponent_team_abbr'].isin(expanded_bad_opps)
over_final = over_final[~mask_bo]
print(f"  After bad opponents:                 {len(over_final)} ({n_before - len(over_final)} blocked)")

# Filter 4: bad venues (expanded)
n_before = len(over_final)
mask_bv = over_final['venue'].isin(expanded_bad_venues)
over_final = over_final[~mask_bv]
print(f"  After bad venues:                    {len(over_final)} ({n_before - len(over_final)} blocked)")

# Test with and without projection disagrees filter
over_final_no_proj = over_final.copy()
n_before = len(over_final)
mask_pd = over_final['projection_value'].notna() & (over_final['projection_value'] < over_final['strikeouts_line'])
over_final_with_proj = over_final[~mask_pd]
print(f"  After projection disagrees (opt):    {len(over_final_with_proj)} ({n_before - len(over_final_with_proj)} blocked)")

for edge_floor in [0.5, 0.75, 1.0]:
    print(f"\n  --- Edge floor: {edge_floor} ---")
    for label, df_pool in [("w/o proj filter", over_final_no_proj), ("w/ proj filter", over_final_with_proj)]:
        eligible = df_pool[df_pool['abs_edge'] >= edge_floor]
        if len(eligible) == 0:
            continue

        top3 = eligible.sort_values('abs_edge', ascending=False).groupby('game_date').head(3)
        top2 = eligible.sort_values('abs_edge', ascending=False).groupby('game_date').head(2)
        top1 = eligible.sort_values('abs_edge', ascending=False).groupby('game_date').head(1)

        n_days = eligible['game_date'].nunique()

        print(f"    {label:<20} "
              f"Top1: {top1['correct'].mean():.1%}(N={len(top1)}) "
              f"Top2: {top2['correct'].mean():.1%}(N={len(top2)}) "
              f"Top3: {top3['correct'].mean():.1%}(N={len(top3)}) "
              f"[{n_days} days, {len(eligible)} eligible]")


# =============================================================================
# Monthly breakdown for best config
# =============================================================================

print(f"\n\n  MONTHLY BREAKDOWN — recommended stack, edge >= 0.75, top-3/day:")
print(f"  {'='*70}")

best_pool = over_final_no_proj[over_final_no_proj['abs_edge'] >= 0.75]
top3_best = best_pool.sort_values('abs_edge', ascending=False).groupby('game_date').head(3)
top3_best = top3_best.copy()
top3_best['month'] = pd.to_datetime(top3_best['game_date']).dt.to_period('M')

print(f"  {'Month':<12} {'HR':>8} {'N':>6} {'Wins':>6} {'Losses':>7}")
print(f"  {'-'*42}")

for month in sorted(top3_best['month'].unique()):
    m_data = top3_best[top3_best['month'] == month]
    hr = m_data['correct'].mean()
    wins = m_data['correct'].sum()
    losses = len(m_data) - wins
    print(f"  {str(month):<12} {hr:>7.1%} {len(m_data):>6} {int(wins):>6} {int(losses):>7}")

print(f"  {'TOTAL':<12} {top3_best['correct'].mean():>7.1%} {len(top3_best):>6} "
      f"{int(top3_best['correct'].sum()):>6} {int(len(top3_best) - top3_best['correct'].sum()):>7}")

# Losing months?
losing_months = []
for month in sorted(top3_best['month'].unique()):
    m_data = top3_best[top3_best['month'] == month]
    if m_data['correct'].mean() < 0.5:
        losing_months.append(str(month))

if losing_months:
    print(f"\n  LOSING MONTHS: {', '.join(losing_months)}")
else:
    print(f"\n  ZERO LOSING MONTHS!")


# =============================================================================
# Print expanded lists for code update
# =============================================================================

print(f"\n\n  EXPANDED LISTS FOR CODE UPDATE:")
print(f"  {'='*60}")

print(f"\n  EXPANDED BLACKLIST ({len(expanded_blacklist)} pitchers):")
for p in sorted(expanded_blacklist):
    print(f"    '{p}',")

print(f"\n  EXPANDED BAD OPPONENTS ({len(expanded_bad_opps)} teams):")
for t in sorted(expanded_bad_opps):
    print(f"    '{t}',")

print(f"\n  EXPANDED BAD VENUES ({len(expanded_bad_venues)} venues):")
for v in sorted(expanded_bad_venues):
    print(f"    '{v}',")


print("\n\n" + "=" * 90)
print("  ANALYSIS COMPLETE")
print("=" * 90)
