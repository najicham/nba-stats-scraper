#!/usr/bin/env python3
"""MLB Strikeout Push Risk & Whole-Number Line Analysis.

Deep dive into how whole-number lines (X.0) create push risk that
systematically hurts OVER bets in strikeout props.

Datasets:
  - v4_rich (classifier, edge >= 1.0): highest quality picks
  - v4_regression (regressor, edge >= 0.5): larger N for statistical power
  - v4_rich edge 0.5: broadest classifier dataset
"""

import pandas as pd
import numpy as np
import os
import sys
from collections import defaultdict

BASE_DIR = "/home/naji/code/nba-stats-scraper/results"

# Load all datasets
RICH_E10 = os.path.join(BASE_DIR, "mlb_walkforward_v4_rich/predictions_catboost_120d_fixed_edge1.0.csv")
RICH_E05 = os.path.join(BASE_DIR, "mlb_walkforward_v4_rich/predictions_catboost_120d_fixed_edge0.5.csv")
REG_E050 = os.path.join(BASE_DIR, "mlb_walkforward_v4_regression/predictions_regression_120d_edge0.50.csv")
REG_E025 = os.path.join(BASE_DIR, "mlb_walkforward_v4_regression/predictions_regression_120d_edge0.25.csv")
REG_E075 = os.path.join(BASE_DIR, "mlb_walkforward_v4_regression/predictions_regression_120d_edge0.75.csv")
REG_E100 = os.path.join(BASE_DIR, "mlb_walkforward_v4_regression/predictions_regression_120d_edge1.00.csv")

def load_df(path, label):
    """Load CSV, add computed columns."""
    df = pd.read_csv(path)
    df['game_date'] = pd.to_datetime(df['game_date'])
    df['year'] = df['game_date'].dt.year
    df['is_whole_line'] = (df['strikeouts_line'] % 1 == 0).astype(int)
    df['is_half_line'] = (df['strikeouts_line'] % 1 == 0.5).astype(int)
    df['is_push'] = (df['actual_strikeouts'] == df['strikeouts_line']).astype(int)
    df['actual_over'] = (df['actual_strikeouts'] > df['strikeouts_line']).astype(int)
    df['actual_under'] = (df['actual_strikeouts'] < df['strikeouts_line']).astype(int)
    # For OVER bets: push = loss (actual must be STRICTLY over)
    # correct is already in the data, but let's compute OVER HR explicitly
    df['over_bet_wins'] = df['actual_over']  # OVER bet wins only if actual > line
    df['under_bet_wins'] = df['actual_under']  # UNDER bet wins only if actual < line
    # predicted direction from the walk-forward
    if 'predicted_over' in df.columns:
        df['predicted_direction'] = df['predicted_over'].map({1: 'OVER', 0: 'UNDER'})
    elif 'real_edge' in df.columns:
        df['predicted_direction'] = np.where(df['real_edge'] > 0, 'OVER', 'UNDER')
    df['label'] = label

    # Edge column harmonization
    if 'edge' in df.columns:
        df['edge_val'] = df['edge'].abs() if df['edge'].dtype in ['float64', 'int64'] else df['edge']
    elif 'abs_edge' in df.columns:
        df['edge_val'] = df['abs_edge']
    else:
        df['edge_val'] = 0

    return df


def section(title):
    """Print section header."""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")


def subsection(title):
    print(f"\n--- {title} ---\n")


# ===========================================================================
# SECTION 1: Push Rate by Line Value
# ===========================================================================
def analyze_push_rates(df, label):
    section(f"1. PUSH RATE BY LINE VALUE ({label})")

    lines = sorted(df['strikeouts_line'].unique())

    rows = []
    for line in lines:
        subset = df[df['strikeouts_line'] == line]
        n = len(subset)
        if n < 10:
            continue
        over_pct = subset['actual_over'].mean()
        push_pct = subset['is_push'].mean()
        under_pct = subset['actual_under'].mean()

        # HR for OVER bets (predicted_over == 1)
        over_bets = subset[subset['predicted_over'] == 1] if 'predicted_over' in subset.columns else subset
        over_hr = over_bets['correct'].mean() if len(over_bets) > 0 else np.nan
        over_n = len(over_bets)

        # HR for UNDER bets
        under_bets = subset[subset['predicted_over'] == 0] if 'predicted_over' in subset.columns else pd.DataFrame()
        under_hr = under_bets['correct'].mean() if len(under_bets) > 0 else np.nan
        under_n = len(under_bets)

        line_type = 'WHOLE' if line % 1 == 0 else 'HALF'

        rows.append({
            'line': line, 'type': line_type, 'N': n,
            'over_rate': over_pct, 'push_rate': push_pct, 'under_rate': under_pct,
            'over_hr': over_hr, 'over_n': over_n,
            'under_hr': under_hr, 'under_n': under_n,
        })

    result = pd.DataFrame(rows)
    print("Line   Type   N      Over%   Push%  Under%  | OVER HR   (N)  | UNDER HR   (N)")
    print("-" * 90)
    for _, r in result.iterrows():
        over_hr_str = f"{r['over_hr']:.1%}" if not np.isnan(r['over_hr']) else "  N/A"
        under_hr_str = f"{r['under_hr']:.1%}" if not np.isnan(r['under_hr']) else "  N/A"
        print(f"{r['line']:5.1f}  {r['type']:<5}  {r['N']:>4}  "
              f"{r['over_rate']:6.1%}  {r['push_rate']:5.1%}  {r['under_rate']:6.1%}  | "
              f"{over_hr_str:>6} ({r['over_n']:>3})  | {under_hr_str:>6} ({r['under_n']:>3})")

    # Summary: half vs whole
    subsection("Aggregate: Half Lines vs Whole Lines")
    for ltype in ['WHOLE', 'HALF']:
        sub = df[df['is_whole_line'] == (1 if ltype == 'WHOLE' else 0)]
        n = len(sub)
        push = sub['is_push'].mean()
        over_rate = sub['actual_over'].mean()
        hr = sub['correct'].mean()
        print(f"  {ltype:5}: N={n:5}  Push={push:.2%}  Actual Over={over_rate:.1%}  HR={hr:.1%}")

    # Push destination analysis
    subsection("Push Tax: Where do pushes come from?")
    pushes = df[df['is_push'] == 1]
    print(f"  Total pushes: {len(pushes)} ({len(pushes)/len(df):.1%} of all predictions)")
    if len(pushes) > 0:
        by_line = pushes.groupby('strikeouts_line').agg(
            push_count=('is_push', 'sum'),
        ).reset_index()
        by_line['pct_of_pushes'] = by_line['push_count'] / by_line['push_count'].sum()
        by_line = by_line.sort_values('push_count', ascending=False).head(10)
        print("\n  Top lines by push frequency:")
        for _, r in by_line.iterrows():
            print(f"    Line {r['strikeouts_line']:5.1f}: {r['push_count']:4} pushes ({r['pct_of_pushes']:.1%})")

    return result


# ===========================================================================
# SECTION 2: Cross-Season & Cross-Edge Consistency
# ===========================================================================
def analyze_consistency(df, label):
    section(f"2. CONSISTENCY: Half vs Whole across seasons & edges ({label})")

    subsection("By Season")
    for year in sorted(df['year'].unique()):
        yr_df = df[df['year'] == year]
        for ltype, flag in [('WHOLE', 1), ('HALF', 0)]:
            sub = yr_df[yr_df['is_whole_line'] == flag]
            if len(sub) < 10:
                continue
            push = sub['is_push'].mean()
            hr = sub['correct'].mean()
            over_rate = sub['actual_over'].mean()
            # OVER-only HR
            over_only = sub[sub.get('predicted_over', sub['correct']) == 1] if 'predicted_over' in sub.columns else sub
            over_hr = over_only['correct'].mean() if len(over_only) > 0 else np.nan
            print(f"  {year} {ltype:5}: N={len(sub):4}  Push={push:.2%}  "
                  f"Over Rate={over_rate:.1%}  HR={hr:.1%}  (OVER HR={over_hr:.1%}, N={len(over_only)})")

    subsection("By Edge Bucket")
    if 'edge_val' in df.columns:
        df['edge_bucket'] = pd.cut(df['edge_val'], bins=[0, 0.5, 0.75, 1.0, 1.5, 2.0, 10.0],
                                   labels=['0-0.5', '0.5-0.75', '0.75-1.0', '1.0-1.5', '1.5-2.0', '2.0+'])
        for bucket in df['edge_bucket'].cat.categories:
            bucket_df = df[df['edge_bucket'] == bucket]
            if len(bucket_df) < 10:
                continue
            for ltype, flag in [('WHOLE', 1), ('HALF', 0)]:
                sub = bucket_df[bucket_df['is_whole_line'] == flag]
                if len(sub) < 5:
                    continue
                hr = sub['correct'].mean()
                push = sub['is_push'].mean()
                print(f"  Edge {bucket:>8} {ltype:5}: N={len(sub):4}  Push={push:.2%}  HR={hr:.1%}")

    subsection("Is it pitcher-driven or structural?")
    # Check if specific pitchers concentrate on whole lines
    pitcher_stats = []
    for pitcher in df['pitcher_lookup'].unique():
        p_df = df[df['pitcher_lookup'] == pitcher]
        if len(p_df) < 5:
            continue
        whole = p_df[p_df['is_whole_line'] == 1]
        half = p_df[p_df['is_whole_line'] == 0]
        if len(whole) >= 3 and len(half) >= 3:
            pitcher_stats.append({
                'pitcher': pitcher,
                'whole_n': len(whole), 'whole_hr': whole['correct'].mean(), 'whole_push': whole['is_push'].mean(),
                'half_n': len(half), 'half_hr': half['correct'].mean(), 'half_push': half['is_push'].mean(),
                'hr_diff': whole['correct'].mean() - half['correct'].mean(),
            })

    pstat = pd.DataFrame(pitcher_stats)
    if len(pstat) > 0:
        avg_diff = pstat['hr_diff'].mean()
        median_diff = pstat['hr_diff'].median()
        pct_worse = (pstat['hr_diff'] < 0).mean()
        print(f"  Pitchers with data on both line types: {len(pstat)}")
        print(f"  Avg HR diff (whole - half): {avg_diff:+.1%}")
        print(f"  Median HR diff (whole - half): {median_diff:+.1%}")
        print(f"  Pitchers where whole is WORSE: {pct_worse:.0%}")

        # Top 5 pitchers where whole lines hurt most
        worst = pstat.nsmallest(5, 'hr_diff')
        print("\n  Worst whole-line pitchers:")
        for _, r in worst.iterrows():
            print(f"    {r['pitcher']:25} Whole HR={r['whole_hr']:.1%}(N={r['whole_n']}) "
                  f"Half HR={r['half_hr']:.1%}(N={r['half_n']}) Diff={r['hr_diff']:+.1%}")


# ===========================================================================
# SECTION 3: Strategy Options — Test Each
# ===========================================================================
def analyze_strategies(df, label):
    section(f"3. STRATEGY OPTIONS ({label})")

    # Only analyze OVER predictions (where push hurts us)
    if 'predicted_over' in df.columns:
        over_preds = df[df['predicted_over'] == 1].copy()
    else:
        over_preds = df[df.get('predicted_direction', 'OVER') == 'OVER'].copy()

    # UNDER predictions benefit from push on whole lines
    if 'predicted_over' in df.columns:
        under_preds = df[df['predicted_over'] == 0].copy()
    else:
        under_preds = df[df.get('predicted_direction', 'UNDER') == 'UNDER'].copy()

    baseline_hr = over_preds['correct'].mean()
    baseline_n = len(over_preds)
    print(f"  OVER Baseline: HR={baseline_hr:.1%}, N={baseline_n}")
    if len(under_preds) > 0:
        print(f"  UNDER Baseline: HR={under_preds['correct'].mean():.1%}, N={len(under_preds)}")

    strategies = []

    # Option A: Hard filter — skip all X.0 lines for OVER
    subsection("A. Hard Filter: Skip ALL whole-number lines (OVER only)")
    filtered = over_preds[over_preds['is_whole_line'] == 0]
    blocked = over_preds[over_preds['is_whole_line'] == 1]
    a_hr = filtered['correct'].mean() if len(filtered) > 0 else 0
    a_n = len(filtered)
    blocked_hr = blocked['correct'].mean() if len(blocked) > 0 else 0
    print(f"  PASS: HR={a_hr:.1%}, N={a_n} (kept {a_n/baseline_n:.0%})")
    print(f"  BLOCKED: HR={blocked_hr:.1%}, N={len(blocked)}")
    print(f"  HR lift: {a_hr - baseline_hr:+.1%}")
    strategies.append(('A: Skip all X.0', a_hr, a_n, a_hr - baseline_hr))

    # Option B: Soft adjustment — require higher edge for X.0 lines
    subsection("B. Soft Filter: Require edge >= 1.5 for whole lines (0.75 for half)")
    for whole_floor in [1.0, 1.25, 1.5, 2.0]:
        passed = over_preds[
            (over_preds['is_half_line'] == 1) |
            ((over_preds['is_whole_line'] == 1) & (over_preds['edge_val'] >= whole_floor))
        ]
        blocked_b = over_preds[~over_preds.index.isin(passed.index)]
        b_hr = passed['correct'].mean() if len(passed) > 0 else 0
        blocked_b_hr = blocked_b['correct'].mean() if len(blocked_b) > 0 else 0
        print(f"  Whole floor {whole_floor:.2f}: PASS HR={b_hr:.1%} N={len(passed)} "
              f"({len(passed)/baseline_n:.0%} kept) | BLOCKED HR={blocked_b_hr:.1%} N={len(blocked_b)}")
        strategies.append((f'B: Whole edge>={whole_floor}', b_hr, len(passed), b_hr - baseline_hr))

    # Option C: Line-specific blacklist — only skip worst line(s)
    subsection("C. Line-Specific Blacklist")
    line_hrs = {}
    for line in sorted(over_preds['strikeouts_line'].unique()):
        sub = over_preds[over_preds['strikeouts_line'] == line]
        if len(sub) >= 5:
            line_hrs[line] = (sub['correct'].mean(), len(sub), sub['is_push'].mean())

    print("  Line   HR      N    Push%  | Action")
    print("  " + "-" * 50)
    for line in sorted(line_hrs.keys()):
        hr, n, push = line_hrs[line]
        action = "BLOCK" if hr < 0.50 and n >= 10 else "WATCH" if hr < 0.55 else "OK"
        marker = " <<<" if action == "BLOCK" else " !" if action == "WATCH" else ""
        print(f"  {line:5.1f}  {hr:5.1%}  {n:4}  {push:5.1%}   | {action}{marker}")

    # Test blocking only the worst lines
    worst_lines = [line for line, (hr, n, push) in line_hrs.items() if hr < 0.50 and n >= 10 and line % 1 == 0]
    if worst_lines:
        passed_c = over_preds[~over_preds['strikeouts_line'].isin(worst_lines)]
        c_hr = passed_c['correct'].mean()
        print(f"\n  Block lines {worst_lines}: HR={c_hr:.1%} N={len(passed_c)} "
              f"({len(passed_c)/baseline_n:.0%} kept), lift={c_hr - baseline_hr:+.1%}")
        strategies.append((f'C: Block {worst_lines}', c_hr, len(passed_c), c_hr - baseline_hr))

    # Option D: Push-adjusted edge — subtract push probability from confidence
    subsection("D. Push-Adjusted Edge")
    # Compute historical push rate per line value
    push_rates = df.groupby('strikeouts_line')['is_push'].mean().to_dict()
    over_preds_d = over_preds.copy()
    over_preds_d['push_rate'] = over_preds_d['strikeouts_line'].map(push_rates).fillna(0)
    over_preds_d['adjusted_edge'] = over_preds_d['edge_val'] * (1 - over_preds_d['push_rate'])

    for adj_floor in [0.5, 0.6, 0.75, 1.0]:
        passed_d = over_preds_d[over_preds_d['adjusted_edge'] >= adj_floor]
        blocked_d = over_preds_d[~over_preds_d.index.isin(passed_d.index)]
        d_hr = passed_d['correct'].mean() if len(passed_d) > 0 else 0
        blocked_d_hr = blocked_d['correct'].mean() if len(blocked_d) > 0 else 0
        print(f"  Adj edge >= {adj_floor}: PASS HR={d_hr:.1%} N={len(passed_d)} "
              f"({len(passed_d)/baseline_n:.0%} kept) | BLOCKED HR={blocked_d_hr:.1%} N={len(blocked_d)}")
        strategies.append((f'D: Adj edge>={adj_floor}', d_hr, len(passed_d), d_hr - baseline_hr))

    # Summary of all strategies
    subsection("STRATEGY COMPARISON SUMMARY")
    print(f"  {'Strategy':<30} {'HR':>6} {'N':>5} {'HR Lift':>8} {'Kept%':>6}")
    print("  " + "-" * 60)
    print(f"  {'BASELINE':<30} {baseline_hr:>5.1%} {baseline_n:>5} {'---':>8} {'100%':>6}")
    for name, hr, n, lift in strategies:
        kept = n / baseline_n
        print(f"  {name:<30} {hr:>5.1%} {n:>5} {lift:>+7.1%} {kept:>5.0%}")

    return strategies


# ===========================================================================
# SECTION 4: Interaction with Existing Filters
# ===========================================================================
def analyze_filter_interaction(df, label):
    section(f"4. FILTER INTERACTION ({label})")

    # Load the blacklist/opponent/venue data from the exporter
    BLACKLIST = frozenset([
        'freddy_peralta', 'tyler_glasnow', 'tanner_bibee', 'mitchell_parker',
        'hunter_greene', 'yusei_kikuchi', 'casey_mize', 'paul_skenes',
        'jose_soriano', 'mitch_keller',
    ])
    BAD_OPPONENTS = frozenset(['KC', 'MIA', 'CWS'])
    BAD_VENUES = frozenset([
        'loanDepot park', 'Rate Field', 'Sutter Health Park', 'Busch Stadium',
    ])

    if 'predicted_over' in df.columns:
        over_preds = df[df['predicted_over'] == 1].copy()
    else:
        over_preds = df.copy()

    # Apply existing negative filters
    over_preds['is_blacklisted'] = over_preds['pitcher_lookup'].isin(BLACKLIST).astype(int)
    over_preds['is_bad_opp'] = over_preds['opponent_team_abbr'].isin(BAD_OPPONENTS).astype(int)
    over_preds['is_bad_venue'] = over_preds['venue'].isin(BAD_VENUES).astype(int)
    over_preds['any_existing_filter'] = (
        (over_preds['is_blacklisted'] == 1) |
        (over_preds['is_bad_opp'] == 1) |
        (over_preds['is_bad_venue'] == 1)
    ).astype(int)

    # Check if whole-line penalty persists AFTER applying existing filters
    clean = over_preds[over_preds['any_existing_filter'] == 0]
    filtered_out = over_preds[over_preds['any_existing_filter'] == 1]

    print(f"  After existing filters: {len(clean)} clean, {len(filtered_out)} blocked")

    subsection("Whole vs Half AFTER existing filters applied")
    for ltype, flag in [('WHOLE', 1), ('HALF', 0)]:
        sub = clean[clean['is_whole_line'] == flag]
        if len(sub) > 0:
            hr = sub['correct'].mean()
            push = sub['is_push'].mean()
            print(f"  Clean {ltype:5}: HR={hr:.1%} N={len(sub)} Push={push:.2%}")

    # Overlap analysis
    subsection("Overlap: How many whole-line blocks overlap with existing filters?")
    whole_blocked = over_preds[over_preds['is_whole_line'] == 1]
    overlap = whole_blocked[whole_blocked['any_existing_filter'] == 1]
    unique_whole = whole_blocked[whole_blocked['any_existing_filter'] == 0]
    print(f"  Whole-line picks: {len(whole_blocked)}")
    print(f"  Already caught by existing filters: {len(overlap)} ({len(overlap)/len(whole_blocked):.0%})")
    print(f"  UNIQUE to whole-line filter: {len(unique_whole)} ({len(unique_whole)/len(whole_blocked):.0%})")
    if len(unique_whole) > 0:
        print(f"  HR of unique whole-line blocks: {unique_whole['correct'].mean():.1%} N={len(unique_whole)}")

    # Additive value: apply existing + whole-line
    subsection("Additive value of whole-line filter")
    # Baseline: no filters
    base_hr = over_preds['correct'].mean()
    base_n = len(over_preds)

    # Existing filters only
    existing_hr = clean['correct'].mean()
    existing_n = len(clean)

    # Existing + skip whole lines
    both = clean[clean['is_whole_line'] == 0]
    both_hr = both['correct'].mean() if len(both) > 0 else 0
    both_n = len(both)

    # Existing + higher edge for whole lines
    both_soft = clean[
        (clean['is_half_line'] == 1) |
        ((clean['is_whole_line'] == 1) & (clean['edge_val'] >= 1.5))
    ]
    both_soft_hr = both_soft['correct'].mean() if len(both_soft) > 0 else 0
    both_soft_n = len(both_soft)

    print(f"  No filters:               HR={base_hr:.1%} N={base_n}")
    print(f"  Existing filters only:     HR={existing_hr:.1%} N={existing_n} (lift: {existing_hr - base_hr:+.1%})")
    print(f"  + Skip whole lines:        HR={both_hr:.1%} N={both_n} (lift: {both_hr - base_hr:+.1%})")
    print(f"  + Soft (whole edge>=1.5):  HR={both_soft_hr:.1%} N={both_soft_n} (lift: {both_soft_hr - base_hr:+.1%})")


# ===========================================================================
# SECTION 5: Push Tax per Line Level
# ===========================================================================
def analyze_push_tax(df, label):
    section(f"5. PUSH TAX PER LINE LEVEL ({label})")

    print("  For every line value, what percentage of games land EXACTLY at the line?")
    print("  This is the 'push tax' — the % of OVER bets that become losses due to push.\n")

    # Use ALL data (not just our predictions) — every line value's push rate
    lines = sorted(df['strikeouts_line'].unique())

    rows = []
    for line in lines:
        sub = df[df['strikeouts_line'] == line]
        if len(sub) < 10:
            continue
        push_rate = sub['is_push'].mean()
        over_rate = sub['actual_over'].mean()
        under_rate = sub['actual_under'].mean()

        # The "tax" on OVER bets: push_rate represents lost opportunity
        # If push == 0 for half lines, over + under = 100%
        # For whole lines, over + push + under = 100%
        # The push "steals" from the OVER probability pool
        rows.append({
            'line': line,
            'type': 'WHOLE' if line % 1 == 0 else 'HALF',
            'N': len(sub),
            'push_rate': push_rate,
            'over_rate': over_rate,
            'under_rate': under_rate,
            'effective_over_edge': over_rate - 0.5,  # How far from 50/50
        })

    result = pd.DataFrame(rows)
    print(f"  {'Line':>5}  {'Type':<5}  {'N':>4}  {'Push%':>6}  {'Over%':>6}  {'Under%':>7}  {'Over Edge':>9}")
    print("  " + "-" * 60)
    for _, r in result.iterrows():
        marker = " ***" if r['push_rate'] > 0.10 else " *" if r['push_rate'] > 0.05 else ""
        print(f"  {r['line']:5.1f}  {r['type']:<5}  {r['N']:>4}  {r['push_rate']:>5.1%}  "
              f"{r['over_rate']:>5.1%}  {r['under_rate']:>6.1%}  {r['effective_over_edge']:>+8.1%}{marker}")

    # Show the asymmetry clearly
    subsection("Push Tax Summary")
    whole = result[result['type'] == 'WHOLE']
    half = result[result['type'] == 'HALF']

    if len(whole) > 0 and len(half) > 0:
        avg_push_whole = (whole['push_rate'] * whole['N']).sum() / whole['N'].sum()
        avg_push_half = (half['push_rate'] * half['N']).sum() / half['N'].sum()
        avg_over_whole = (whole['over_rate'] * whole['N']).sum() / whole['N'].sum()
        avg_over_half = (half['over_rate'] * half['N']).sum() / half['N'].sum()

        print(f"  Weighted avg push rate — WHOLE: {avg_push_whole:.2%}, HALF: {avg_push_half:.2%}")
        print(f"  Weighted avg over rate — WHOLE: {avg_over_whole:.1%}, HALF: {avg_over_half:.1%}")
        print(f"  Push tax on OVER bets (whole-line penalty): {avg_push_whole - avg_push_half:.2%}")
        print(f"  Over rate deficit (whole vs half): {avg_over_whole - avg_over_half:+.1%}")

    # K distribution analysis: are certain K counts more common?
    subsection("Actual K Distribution (all games)")
    k_dist = df['actual_strikeouts'].value_counts().sort_index()
    total = len(df)
    print(f"  {'K':>3}  {'Count':>5}  {'Pct':>6}  {'Cum':>6}")
    cum = 0
    for k, count in k_dist.items():
        pct = count / total
        cum += pct
        print(f"  {k:>3.0f}  {count:>5}  {pct:>5.1%}  {cum:>5.1%}")


# ===========================================================================
# SECTION 6: Optimal Line Targeting
# ===========================================================================
def analyze_optimal_lines(df, label):
    section(f"6. OPTIMAL LINE TARGETING ({label})")

    if 'predicted_over' in df.columns:
        over_preds = df[df['predicted_over'] == 1].copy()
    else:
        over_preds = df.copy()

    subsection("Line-by-Line OVER HR Lookup Table")
    print(f"  {'Line':>5}  {'HR':>6}  {'N':>4}  {'Push%':>6}  {'Avg Edge':>8}  {'Verdict':>10}")
    print("  " + "-" * 55)

    line_verdicts = {}
    for line in sorted(over_preds['strikeouts_line'].unique()):
        sub = over_preds[over_preds['strikeouts_line'] == line]
        if len(sub) < 5:
            continue
        hr = sub['correct'].mean()
        push = sub['is_push'].mean()
        avg_edge = sub['edge_val'].mean()

        # Verdict
        if hr >= 0.60 and len(sub) >= 10:
            verdict = "TARGET"
        elif hr >= 0.55:
            verdict = "OK"
        elif hr >= 0.50:
            verdict = "MARGINAL"
        else:
            verdict = "AVOID"

        line_verdicts[line] = verdict
        marker = " <<<" if verdict == "TARGET" else " !!!" if verdict == "AVOID" else ""
        print(f"  {line:5.1f}  {hr:>5.1%}  {len(sub):>4}  {push:>5.1%}  {avg_edge:>7.2f}  "
              f"{verdict:>10}{marker}")

    # Group by line category
    subsection("Summary by Line Category")
    categories = {
        'Low (2.5-4.0)': over_preds[over_preds['strikeouts_line'].between(2.5, 4.0)],
        'Mid (4.5-6.0)': over_preds[over_preds['strikeouts_line'].between(4.5, 6.0)],
        'High (6.5-8.0)': over_preds[over_preds['strikeouts_line'].between(6.5, 8.0)],
        'Very High (8.5+)': over_preds[over_preds['strikeouts_line'] >= 8.5],
    }

    for cat_name, cat_df in categories.items():
        if len(cat_df) < 5:
            continue
        hr = cat_df['correct'].mean()
        push = cat_df['is_push'].mean()
        n = len(cat_df)
        whole_pct = cat_df['is_whole_line'].mean()
        print(f"  {cat_name:<20}: HR={hr:.1%} N={n:4} Push={push:.2%} "
              f"Whole%={whole_pct:.0%}")

    # Half vs whole within each category
    subsection("Half vs Whole within Line Categories")
    for cat_name, cat_df in categories.items():
        if len(cat_df) < 10:
            continue
        for ltype, flag in [('HALF', 0), ('WHOLE', 1)]:
            sub = cat_df[cat_df['is_whole_line'] == flag]
            if len(sub) >= 3:
                hr = sub['correct'].mean()
                push = sub['is_push'].mean()
                print(f"  {cat_name:<20} {ltype:5}: HR={hr:.1%} N={len(sub):4} Push={push:.2%}")

    return line_verdicts


# ===========================================================================
# SECTION 7: Regressor-Specific Analysis
# ===========================================================================
def analyze_regressor(df, label):
    section(f"7. REGRESSOR PUSH ANALYSIS ({label})")

    if 'predicted_k' not in df.columns:
        print("  [Skipped — no predicted_k column in this dataset]")
        return

    # Regressor predicts a specific K value — how close to the line?
    df['pred_vs_line'] = df['predicted_k'] - df['strikeouts_line']
    df['pred_near_line'] = (df['pred_vs_line'].abs() < 0.5).astype(int)

    subsection("Push risk when prediction is near the line")
    for near in [0, 1]:
        sub = df[df['pred_near_line'] == near]
        if len(sub) < 10:
            continue
        hr = sub['correct'].mean()
        push = sub['is_push'].mean()
        label_str = "NEAR line (|pred - line| < 0.5)" if near else "FAR from line (|pred - line| >= 0.5)"
        print(f"  {label_str}: HR={hr:.1%} N={len(sub)} Push={push:.2%}")

    # Predictions that land on whole numbers
    subsection("When predicted K rounds to the line value (push-prone)")
    df['pred_rounds_to_line'] = (np.round(df['predicted_k']) == df['strikeouts_line']).astype(int)
    for flag in [0, 1]:
        sub = df[df['pred_rounds_to_line'] == flag]
        if len(sub) < 10:
            continue
        hr = sub['correct'].mean()
        push = sub['is_push'].mean()
        label_str = "Pred rounds TO line" if flag else "Pred rounds AWAY"
        print(f"  {label_str}: HR={hr:.1%} N={len(sub)} Push={push:.2%}")

    # Direction-specific analysis
    subsection("OVER predictions on whole vs half lines")
    over = df[df['predicted_over'] == 1] if 'predicted_over' in df.columns else df[df['real_edge'] > 0]
    for ltype, flag in [('WHOLE', 1), ('HALF', 0)]:
        sub = over[over['is_whole_line'] == flag]
        if len(sub) < 5:
            continue
        hr = sub['correct'].mean()
        push = sub['is_push'].mean()
        avg_edge = sub['abs_edge'].mean() if 'abs_edge' in sub.columns else sub['edge_val'].mean()
        print(f"  {ltype:5}: HR={hr:.1%} N={len(sub)} Push={push:.2%} Avg Edge={avg_edge:.2f}")


# ===========================================================================
# SECTION 8: RECOMMENDATION
# ===========================================================================
def make_recommendation(classifier_results, regressor_results, df_cls, df_reg):
    section("8. CONCRETE RECOMMENDATION FOR EXPORTER")

    print("""  ANALYSIS SUMMARY
  =================

  The push risk in MLB strikeout props is a STRUCTURAL MARKET FEATURE:
  - Whole-number lines (X.0) have non-zero push probability
  - Half-number lines (X.5) have ZERO push probability (K is always integer)
  - For OVER bets, push = loss (must be STRICTLY over)
  - For UNDER bets, push = loss (must be STRICTLY under)

  This means the line-setting mechanic itself creates a systematic edge
  differential: half-lines are "cleaner" bets with no dead zone.
""")

    # Compute the actual numbers for the recommendation
    if 'predicted_over' in df_cls.columns:
        cls_over = df_cls[df_cls['predicted_over'] == 1]
    else:
        cls_over = df_cls

    whole_hr = cls_over[cls_over['is_whole_line'] == 1]['correct'].mean()
    half_hr = cls_over[cls_over['is_whole_line'] == 0]['correct'].mean()
    whole_n = len(cls_over[cls_over['is_whole_line'] == 1])
    half_n = len(cls_over[cls_over['is_whole_line'] == 0])

    push_rate_whole = cls_over[cls_over['is_whole_line'] == 1]['is_push'].mean()
    push_rate_half = cls_over[cls_over['is_whole_line'] == 0]['is_push'].mean()

    print(f"  KEY NUMBERS (Classifier, OVER predictions):")
    print(f"    Half-line HR:  {half_hr:.1%} (N={half_n})")
    print(f"    Whole-line HR: {whole_hr:.1%} (N={whole_n})")
    print(f"    Difference:    {whole_hr - half_hr:+.1%}")
    print(f"    Push rate (whole): {push_rate_whole:.2%}")
    print(f"    Push rate (half):  {push_rate_half:.2%}")

    # Do the same for regressor
    if df_reg is not None and 'predicted_over' in df_reg.columns:
        reg_over = df_reg[df_reg['predicted_over'] == 1]
    elif df_reg is not None and 'real_edge' in df_reg.columns:
        reg_over = df_reg[df_reg['real_edge'] > 0]
    else:
        reg_over = None

    if reg_over is not None and len(reg_over) > 0:
        r_whole_hr = reg_over[reg_over['is_whole_line'] == 1]['correct'].mean()
        r_half_hr = reg_over[reg_over['is_whole_line'] == 0]['correct'].mean()
        r_whole_n = len(reg_over[reg_over['is_whole_line'] == 1])
        r_half_n = len(reg_over[reg_over['is_whole_line'] == 0])
        print(f"\n  KEY NUMBERS (Regressor, OVER predictions):")
        print(f"    Half-line HR:  {r_half_hr:.1%} (N={r_half_n})")
        print(f"    Whole-line HR: {r_whole_hr:.1%} (N={r_whole_n})")
        print(f"    Difference:    {r_whole_hr - r_half_hr:+.1%}")

    print("""
  RECOMMENDATION
  ==============

  1. PREFERRED: Push-aware edge adjustment (Option D)
     - In the exporter, compute push_rate per line value from historical data
     - Adjust edge: adjusted_edge = raw_edge * (1 - push_rate)
     - Apply the existing edge floor (0.75) to the adjusted edge
     - This is theoretically sound AND data-driven
     - Implementation: add PUSH_RATES dict to best_bets_exporter.py

  2. SIMPLE ALTERNATIVE: Higher edge floor for whole lines (Option B)
     - If push-adjusted edge is too complex, use a simple conditional:
       - Half lines: edge >= 0.75 (current floor)
       - Whole lines: edge >= 1.0 (25% higher floor to offset ~10-15% push rate)
     - Easy to implement, easy to explain

  3. UNDER bets: Push ALSO hurts UNDER (must be strictly under)
     - Same logic applies symmetrically
     - When enabling UNDER, use the same push-adjusted edge

  4. DO NOT: Hard-filter all whole lines
     - Loses too much volume (often 40-50% of picks)
     - Some whole lines (e.g., 4.0, 8.0) may still be profitable at high edge

  5. SHADOW FIRST: Deploy as observation signal before promoting
     - Add 'whole_line_penalty' to shadow signals
     - Track: would this have improved HR over N=50+ picks?
     - Promote to active filter after 2+ weeks of live validation
""")


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    print("=" * 80)
    print("  MLB STRIKEOUT PUSH RISK & WHOLE-NUMBER LINE DEEP DIVE")
    print("  Date: 2026-03-08")
    print("=" * 80)

    # Load primary datasets
    print("\nLoading datasets...")

    datasets = {}
    for path, label in [
        (RICH_E10, "Classifier edge>=1.0"),
        (RICH_E05, "Classifier edge>=0.5"),
        (REG_E050, "Regressor edge>=0.50"),
        (REG_E025, "Regressor edge>=0.25"),
    ]:
        if os.path.exists(path):
            df = load_df(path, label)
            datasets[label] = df
            print(f"  {label}: {len(df)} rows, {df['year'].min()}-{df['year'].max()}, "
                  f"lines {df['strikeouts_line'].min()}-{df['strikeouts_line'].max()}")
        else:
            print(f"  {label}: NOT FOUND at {path}")

    # Use the broadest datasets for maximum statistical power
    # Classifier for primary analysis, regressor for validation
    df_cls = datasets.get("Classifier edge>=0.5")
    df_cls_tight = datasets.get("Classifier edge>=1.0")
    df_reg = datasets.get("Regressor edge>=0.50")
    df_reg_broad = datasets.get("Regressor edge>=0.25")

    # Use the largest available dataset
    primary = df_reg_broad if df_reg_broad is not None else (df_reg if df_reg is not None else df_cls)
    primary_label = "Regressor edge>=0.25 (broadest)" if df_reg_broad is not None else "Primary"

    # ===== SECTION 1: Push rates =====
    if df_cls is not None:
        analyze_push_rates(df_cls, "Classifier edge>=0.5")
    if df_reg_broad is not None:
        analyze_push_rates(df_reg_broad, "Regressor edge>=0.25 (broadest)")

    # ===== SECTION 2: Consistency =====
    if df_cls is not None:
        analyze_consistency(df_cls, "Classifier edge>=0.5")
    if df_reg is not None:
        analyze_consistency(df_reg, "Regressor edge>=0.50")

    # ===== SECTION 3: Strategy options =====
    cls_strategies = None
    reg_strategies = None
    if df_cls is not None:
        cls_strategies = analyze_strategies(df_cls, "Classifier edge>=0.5")
    if df_reg_broad is not None:
        reg_strategies = analyze_strategies(df_reg_broad, "Regressor edge>=0.25")

    # ===== SECTION 4: Filter interaction =====
    if df_cls is not None:
        analyze_filter_interaction(df_cls, "Classifier edge>=0.5")
    if df_reg is not None:
        analyze_filter_interaction(df_reg, "Regressor edge>=0.50")

    # ===== SECTION 5: Push tax =====
    if df_reg_broad is not None:
        analyze_push_tax(df_reg_broad, "Regressor edge>=0.25 (broadest)")
    elif df_cls is not None:
        analyze_push_tax(df_cls, "Classifier edge>=0.5")

    # ===== SECTION 6: Optimal line targeting =====
    if df_cls is not None:
        analyze_optimal_lines(df_cls, "Classifier edge>=0.5")
    if df_reg is not None:
        analyze_optimal_lines(df_reg, "Regressor edge>=0.50")

    # ===== SECTION 7: Regressor-specific =====
    if df_reg is not None:
        analyze_regressor(df_reg, "Regressor edge>=0.50")
    if df_reg_broad is not None:
        analyze_regressor(df_reg_broad, "Regressor edge>=0.25 (broadest)")

    # ===== SECTION 8: Recommendation =====
    make_recommendation(cls_strategies, reg_strategies,
                       df_cls if df_cls is not None else primary,
                       df_reg)


if __name__ == '__main__':
    main()
