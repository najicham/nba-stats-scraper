#!/usr/bin/env python3
"""
MLB Pitcher Deep Dive Analysis
===============================
Comprehensive pitcher-level analysis on walk-forward regressor data.
Informs pitcher filter strategy (blacklist, signals, matchup effects).

Uses: results/mlb_walkforward_v4_rich/predictions_catboost_120d_fixed_edge1.0.csv
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# CONFIG
# ============================================================
BASE = Path('/home/naji/code/nba-stats-scraper/results/mlb_walkforward_v4_rich')
PRIMARY_FILE = BASE / 'predictions_catboost_120d_fixed_edge1.0.csv'
WIDE_FILE = BASE / 'predictions_catboost_120d_fixed_edge0.5.csv'

CURRENT_BLACKLIST = frozenset([
    'freddy_peralta', 'tyler_glasnow', 'tanner_bibee', 'mitchell_parker',
    'hunter_greene', 'yusei_kikuchi', 'casey_mize', 'paul_skenes',
    'jose_soriano', 'mitch_keller',
])

MIN_N = 10  # Minimum starts for statistical validity
SEPARATOR = '=' * 80
SUB_SEP = '-' * 70

# ============================================================
# LOAD DATA
# ============================================================
def load_data():
    df = pd.read_csv(PRIMARY_FILE)
    df['game_date'] = pd.to_datetime(df['game_date'])
    df['correct'] = df['correct'].astype(int)
    df['predicted_over'] = df['predicted_over'].astype(int)
    df['actual_over'] = df['actual_over'].astype(int)
    df['is_home'] = df['is_home'].astype(int)
    # Compute prediction error
    # For regressor: predicted K is inferred from proba and line
    # The model predicts whether actual > line. proba is P(over).
    # prediction_value = proba * something? Actually, the edge is |proba - 0.5| * 10
    # For strikeouts: actual_error = actual_strikeouts - strikeouts_line
    df['line_error'] = df['actual_strikeouts'] - df['strikeouts_line']
    df['projection_error'] = df['actual_strikeouts'] - df['projection_value']
    # Direction the model predicted
    df['pred_direction'] = np.where(df['predicted_over'] == 1, 'OVER', 'UNDER')
    return df

def load_wide_data():
    df = pd.read_csv(WIDE_FILE)
    df['game_date'] = pd.to_datetime(df['game_date'])
    df['correct'] = df['correct'].astype(int)
    df['predicted_over'] = df['predicted_over'].astype(int)
    df['actual_over'] = df['actual_over'].astype(int)
    df['is_home'] = df['is_home'].astype(int)
    df['line_error'] = df['actual_strikeouts'] - df['strikeouts_line']
    df['projection_error'] = df['actual_strikeouts'] - df['projection_value']
    df['pred_direction'] = np.where(df['predicted_over'] == 1, 'OVER', 'UNDER')
    return df


def section(title):
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


# ============================================================
# 1. PITCHER CONSISTENCY
# ============================================================
def analyze_pitcher_consistency(df):
    section("1. PITCHER CONSISTENCY — Who is most/least predictable?")

    pitcher_stats = df.groupby(['pitcher_name', 'pitcher_lookup']).agg(
        N=('correct', 'count'),
        HR=('correct', 'mean'),
        wins=('correct', 'sum'),
        avg_edge=('edge', 'mean'),
        avg_line=('strikeouts_line', 'mean'),
        avg_actual=('actual_strikeouts', 'mean'),
        avg_k9=('season_k_per_9', 'mean'),
        over_rate=('actual_over', 'mean'),
        pred_over_rate=('predicted_over', 'mean'),
    ).reset_index()

    # Variance in correctness (higher = more inconsistent)
    correct_var = df.groupby('pitcher_lookup')['correct'].std().reset_index()
    correct_var.columns = ['pitcher_lookup', 'correct_std']
    pitcher_stats = pitcher_stats.merge(correct_var, on='pitcher_lookup')

    # Line error variance per pitcher
    error_var = df.groupby('pitcher_lookup')['line_error'].agg(['mean', 'std']).reset_index()
    error_var.columns = ['pitcher_lookup', 'mean_line_error', 'line_error_std']
    pitcher_stats = pitcher_stats.merge(error_var, on='pitcher_lookup')

    pitcher_stats['HR_pct'] = (pitcher_stats['HR'] * 100).round(1)

    # Filter to meaningful sample sizes
    valid = pitcher_stats[pitcher_stats['N'] >= MIN_N].copy()
    valid = valid.sort_values('HR', ascending=False)

    print(f"\nTotal pitchers: {len(pitcher_stats)}")
    print(f"Pitchers with N >= {MIN_N}: {len(valid)}")
    print(f"Overall HR: {df['correct'].mean()*100:.1f}% (N={len(df)})")

    # TOP 10 most profitable
    print(f"\n{SUB_SEP}")
    print("TOP 10 MOST PROFITABLE PITCHERS (N >= 10)")
    print(f"{SUB_SEP}")
    top10 = valid.head(10)
    for _, row in top10.iterrows():
        on_bl = " [BLACKLISTED]" if row['pitcher_lookup'] in CURRENT_BLACKLIST else ""
        print(f"  {row['pitcher_name']:25s}  HR={row['HR_pct']:5.1f}%  N={int(row['N']):3d}  "
              f"wins={int(row['wins']):3d}  avg_edge={row['avg_edge']:.2f}  "
              f"K/9={row['avg_k9']:.1f}  avg_line={row['avg_line']:.1f}  "
              f"line_err_std={row['line_error_std']:.2f}{on_bl}")

    # WORST 10
    print(f"\n{SUB_SEP}")
    print("WORST 10 PITCHERS (N >= 10)")
    print(f"{SUB_SEP}")
    worst10 = valid.tail(10).sort_values('HR', ascending=True)
    for _, row in worst10.iterrows():
        on_bl = " [BLACKLISTED]" if row['pitcher_lookup'] in CURRENT_BLACKLIST else ""
        print(f"  {row['pitcher_name']:25s}  HR={row['HR_pct']:5.1f}%  N={int(row['N']):3d}  "
              f"wins={int(row['wins']):3d}  avg_edge={row['avg_edge']:.2f}  "
              f"K/9={row['avg_k9']:.1f}  avg_line={row['avg_line']:.1f}  "
              f"line_err_std={row['line_error_std']:.2f}{on_bl}")

    # Highest variance (most unpredictable)
    print(f"\n{SUB_SEP}")
    print("MOST VOLATILE PITCHERS (highest line_error_std, N >= 10)")
    print(f"{SUB_SEP}")
    volatile = valid.nlargest(10, 'line_error_std')
    for _, row in volatile.iterrows():
        print(f"  {row['pitcher_name']:25s}  line_err_std={row['line_error_std']:.2f}  "
              f"HR={row['HR_pct']:5.1f}%  N={int(row['N']):3d}  avg_line={row['avg_line']:.1f}")

    # Distribution of pitcher HRs
    print(f"\n{SUB_SEP}")
    print("PITCHER HR DISTRIBUTION (N >= 10)")
    print(f"{SUB_SEP}")
    bins = [(0, 40), (40, 45), (45, 50), (50, 55), (55, 60), (60, 65), (65, 70), (70, 100)]
    for lo, hi in bins:
        bucket = valid[(valid['HR_pct'] >= lo) & (valid['HR_pct'] < hi)]
        total_picks = int(bucket['N'].sum())
        print(f"  {lo:3d}-{hi:3d}%: {len(bucket):3d} pitchers, {total_picks:5d} picks")

    return pitcher_stats, valid


# ============================================================
# 2. PITCHER TRAITS THAT PREDICT SUCCESS
# ============================================================
def analyze_pitcher_traits(df, pitcher_stats, valid):
    section("2. PITCHER TRAITS — What separates profitable from unprofitable?")

    # Split into profitable (>55%) and unprofitable (<50%)
    profitable = valid[valid['HR'] > 0.55]
    unprofitable = valid[valid['HR'] < 0.50]

    print(f"\nProfitable pitchers (HR > 55%): {len(profitable)}, avg N={profitable['N'].mean():.0f}")
    print(f"Unprofitable pitchers (HR < 50%): {len(unprofitable)}, avg N={unprofitable['N'].mean():.0f}")

    # Compare traits
    traits = ['avg_k9', 'avg_line', 'avg_actual', 'avg_edge', 'over_rate',
              'line_error_std', 'mean_line_error']
    print(f"\n{'Trait':25s}  {'Profitable':>12s}  {'Unprofitable':>12s}  {'Delta':>8s}")
    print(f"  {'-'*60}")
    for t in traits:
        p_val = profitable[t].mean()
        u_val = unprofitable[t].mean()
        delta = p_val - u_val
        print(f"  {t:23s}  {p_val:12.2f}  {u_val:12.2f}  {delta:+8.2f}")

    # K/9 buckets
    print(f"\n{SUB_SEP}")
    print("HR BY PITCHER K/9 BUCKET")
    print(f"{SUB_SEP}")
    df_k9 = df.copy()
    df_k9['k9_bucket'] = pd.cut(df_k9['season_k_per_9'],
                                  bins=[0, 6, 7, 8, 9, 10, 11, 12, 15],
                                  labels=['<6', '6-7', '7-8', '8-9', '9-10', '10-11', '11-12', '12+'])
    k9_hr = df_k9.groupby('k9_bucket', observed=True).agg(
        HR=('correct', 'mean'), N=('correct', 'count'), avg_edge=('edge', 'mean'),
        avg_line=('strikeouts_line', 'mean')
    )
    for bucket, row in k9_hr.iterrows():
        flag = " <-- BEST" if row['HR'] == k9_hr['HR'].max() else ""
        print(f"  K/9 {bucket:>6s}: HR={row['HR']*100:5.1f}%  N={int(row['N']):5d}  "
              f"avg_edge={row['avg_edge']:.2f}  avg_line={row['avg_line']:.1f}{flag}")

    # Line level analysis
    print(f"\n{SUB_SEP}")
    print("HR BY LINE LEVEL (strikeouts_line)")
    print(f"{SUB_SEP}")
    df_line = df.copy()
    df_line['line_bucket'] = pd.cut(df_line['strikeouts_line'],
                                     bins=[0, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 20],
                                     labels=['<=3.5', '3.5-4.5', '4.5-5.5', '5.5-6.5',
                                             '6.5-7.5', '7.5-8.5', '8.5+'])
    line_hr = df_line.groupby('line_bucket', observed=True).agg(
        HR=('correct', 'mean'), N=('correct', 'count'),
        avg_k9=('season_k_per_9', 'mean'),
        over_rate=('actual_over', 'mean'),
    )
    for bucket, row in line_hr.iterrows():
        flag = " <-- BEST" if row['HR'] == line_hr['HR'].max() else ""
        flag2 = " <-- WORST" if row['HR'] == line_hr['HR'].min() and int(row['N']) >= 20 else flag
        print(f"  Line {bucket:>8s}: HR={row['HR']*100:5.1f}%  N={int(row['N']):5d}  "
              f"K/9={row['avg_k9']:.1f}  over_rate={row['over_rate']*100:.1f}%{flag2}")

    # Home/away splits per pitcher profitability tier
    print(f"\n{SUB_SEP}")
    print("HOME vs AWAY SPLITS")
    print(f"{SUB_SEP}")
    for label, mask in [("HOME", df['is_home'] == 1), ("AWAY", df['is_home'] == 0)]:
        sub = df[mask]
        print(f"  {label}: HR={sub['correct'].mean()*100:.1f}%  N={len(sub)}  "
              f"avg_edge={sub['edge'].mean():.2f}  avg_line={sub['strikeouts_line'].mean():.1f}")

    # Day/night splits
    print(f"\n{SUB_SEP}")
    print("DAY vs NIGHT SPLITS")
    print(f"{SUB_SEP}")
    for label, mask in [("DAY", df['is_day_game'] == 1), ("NIGHT", df['is_day_game'] == 0)]:
        sub = df[mask]
        print(f"  {label:5s}: HR={sub['correct'].mean()*100:.1f}%  N={len(sub)}  "
              f"avg_edge={sub['edge'].mean():.2f}")

    # OVER vs UNDER prediction direction
    print(f"\n{SUB_SEP}")
    print("OVER vs UNDER PREDICTION DIRECTION")
    print(f"{SUB_SEP}")
    for direction in ['OVER', 'UNDER']:
        sub = df[df['pred_direction'] == direction]
        print(f"  {direction:5s}: HR={sub['correct'].mean()*100:.1f}%  N={len(sub)}  "
              f"avg_edge={sub['edge'].mean():.2f}  avg_line={sub['strikeouts_line'].mean():.1f}")


# ============================================================
# 3. MATCHUP EFFECTS
# ============================================================
def analyze_matchups(df, df_wide):
    section("3. MATCHUP EFFECTS — Pitcher vs Opponent Combos")

    # Use wide dataset for more coverage
    matchups = df_wide.groupby(['pitcher_lookup', 'pitcher_name', 'opponent_team_abbr']).agg(
        HR=('correct', 'mean'), N=('correct', 'count'),
        avg_actual=('actual_strikeouts', 'mean'), avg_line=('strikeouts_line', 'mean'),
    ).reset_index()

    matchups_valid = matchups[matchups['N'] >= 3].copy()
    matchups_valid['HR_pct'] = (matchups_valid['HR'] * 100).round(1)

    print(f"\nTotal pitcher-opponent combos: {len(matchups)}")
    print(f"Combos with N >= 3: {len(matchups_valid)}")

    # Best money matchups
    print(f"\n{SUB_SEP}")
    print("TOP 15 'MONEY MATCHUPS' (N >= 3, sorted by HR then N)")
    print(f"{SUB_SEP}")
    money = matchups_valid.sort_values(['HR', 'N'], ascending=[False, False]).head(15)
    for _, row in money.iterrows():
        print(f"  {row['pitcher_name']:25s} vs {row['opponent_team_abbr']:3s}  "
              f"HR={row['HR_pct']:5.1f}%  N={int(row['N']):3d}  "
              f"avg_K={row['avg_actual']:.1f}  line={row['avg_line']:.1f}")

    # Worst matchups
    print(f"\n{SUB_SEP}")
    print("WORST 15 MATCHUPS (N >= 3, sorted by HR ascending)")
    print(f"{SUB_SEP}")
    worst = matchups_valid.sort_values(['HR', 'N'], ascending=[True, False]).head(15)
    for _, row in worst.iterrows():
        print(f"  {row['pitcher_name']:25s} vs {row['opponent_team_abbr']:3s}  "
              f"HR={row['HR_pct']:5.1f}%  N={int(row['N']):3d}  "
              f"avg_K={row['avg_actual']:.1f}  line={row['avg_line']:.1f}")

    # Opponent-level aggregate (regardless of pitcher)
    print(f"\n{SUB_SEP}")
    print("OPPONENT AGGREGATE HR (model HR when picking pitcher vs this opponent)")
    print(f"{SUB_SEP}")
    opp_stats = df.groupby('opponent_team_abbr').agg(
        HR=('correct', 'mean'), N=('correct', 'count'),
        avg_actual_k=('actual_strikeouts', 'mean'),
        avg_line=('strikeouts_line', 'mean'),
    ).reset_index()
    opp_stats = opp_stats.sort_values('HR', ascending=False)
    for _, row in opp_stats.iterrows():
        flag = ""
        if row['HR'] >= 0.60 and int(row['N']) >= 20:
            flag = " <-- EXPLOIT"
        elif row['HR'] < 0.48 and int(row['N']) >= 20:
            flag = " <-- AVOID"
        print(f"  vs {row['opponent_team_abbr']:3s}: HR={row['HR']*100:5.1f}%  N={int(row['N']):4d}  "
              f"avg_actual_K={row['avg_actual_k']:.1f}  avg_line={row['avg_line']:.1f}{flag}")

    # Venue analysis
    print(f"\n{SUB_SEP}")
    print("VENUE HR (top and bottom)")
    print(f"{SUB_SEP}")
    venue_stats = df.groupby('venue').agg(
        HR=('correct', 'mean'), N=('correct', 'count'),
        avg_actual=('actual_strikeouts', 'mean'),
    ).reset_index()
    venue_valid = venue_stats[venue_stats['N'] >= 15].sort_values('HR', ascending=False)
    print("  TOP 10:")
    for _, row in venue_valid.head(10).iterrows():
        print(f"    {row['venue']:35s}  HR={row['HR']*100:5.1f}%  N={int(row['N']):4d}  avg_K={row['avg_actual']:.1f}")
    print("  BOTTOM 10:")
    for _, row in venue_valid.tail(10).iterrows():
        print(f"    {row['venue']:35s}  HR={row['HR']*100:5.1f}%  N={int(row['N']):4d}  avg_K={row['avg_actual']:.1f}")


# ============================================================
# 4. LINE ACCURACY / MODEL BIAS
# ============================================================
def analyze_line_accuracy(df):
    section("4. LINE ACCURACY — Model vs Line vs Actual bias analysis")

    # Overall bias
    avg_actual = df['actual_strikeouts'].mean()
    avg_line = df['strikeouts_line'].mean()
    avg_proj = df['projection_value'].mean()
    avg_line_error = df['line_error'].mean()
    avg_proj_error = df['projection_error'].mean()

    print(f"\n  Overall Averages:")
    print(f"    Actual strikeouts:     {avg_actual:.2f}")
    print(f"    Line (market):         {avg_line:.2f}")
    print(f"    Projection:            {avg_proj:.2f}")
    print(f"    Line error (act-line): {avg_line_error:+.2f}  (positive = line too low)")
    print(f"    Proj error (act-proj): {avg_proj_error:+.2f}  (positive = proj too low)")

    # Over rate vs line
    over_rate = df['actual_over'].mean()
    print(f"\n  Actual OVER rate:        {over_rate*100:.1f}%  (50% = perfectly calibrated line)")
    print(f"  Model OVER pred rate:    {df['predicted_over'].mean()*100:.1f}%")

    # By direction
    print(f"\n{SUB_SEP}")
    print("BIAS BY PREDICTED DIRECTION")
    print(f"{SUB_SEP}")
    for direction in ['OVER', 'UNDER']:
        sub = df[df['pred_direction'] == direction]
        actual_over_rate = sub['actual_over'].mean()
        print(f"  When model says {direction:5s}: actual_over_rate={actual_over_rate*100:.1f}%  "
              f"HR={sub['correct'].mean()*100:.1f}%  N={len(sub)}  "
              f"avg_line_error={sub['line_error'].mean():+.2f}")

    # Error by line level
    print(f"\n{SUB_SEP}")
    print("LINE ACCURACY BY LINE LEVEL")
    print(f"{SUB_SEP}")
    df_line = df.copy()
    df_line['line_bucket'] = pd.cut(df_line['strikeouts_line'],
                                     bins=[0, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 20],
                                     labels=['<=3.5', '3.5-4.5', '4.5-5.5', '5.5-6.5',
                                             '6.5-7.5', '7.5-8.5', '8.5+'])
    for bucket, grp in df_line.groupby('line_bucket', observed=True):
        print(f"  Line {bucket:>8s}: line_err={grp['line_error'].mean():+.2f}  "
              f"proj_err={grp['projection_error'].mean():+.2f}  "
              f"line_err_std={grp['line_error'].std():.2f}  "
              f"over_rate={grp['actual_over'].mean()*100:.1f}%  N={len(grp)}")

    # Error by K/9 level
    print(f"\n{SUB_SEP}")
    print("LINE ACCURACY BY PITCHER K/9")
    print(f"{SUB_SEP}")
    df_k9 = df.copy()
    df_k9['k9_bucket'] = pd.cut(df_k9['season_k_per_9'],
                                  bins=[0, 7, 8, 9, 10, 11, 15],
                                  labels=['<7', '7-8', '8-9', '9-10', '10-11', '11+'])
    for bucket, grp in df_k9.groupby('k9_bucket', observed=True):
        print(f"  K/9 {bucket:>6s}: line_err={grp['line_error'].mean():+.2f}  "
              f"line_err_std={grp['line_error'].std():.2f}  "
              f"over_rate={grp['actual_over'].mean()*100:.1f}%  "
              f"model_HR={grp['correct'].mean()*100:.1f}%  N={len(grp)}")

    # Where does model over/under-estimate?
    print(f"\n{SUB_SEP}")
    print("MODEL OVER-ESTIMATION vs UNDER-ESTIMATION")
    print(f"{SUB_SEP}")
    over_pred = df[df['predicted_over'] == 1]
    under_pred = df[df['predicted_over'] == 0]
    # For OVER predictions: actual should be > line. Measure.
    over_actual_above = (over_pred['actual_strikeouts'] > over_pred['strikeouts_line']).mean()
    under_actual_below = (under_pred['actual_strikeouts'] < under_pred['strikeouts_line']).mean()
    over_actual_equal = (over_pred['actual_strikeouts'] == over_pred['strikeouts_line']).mean()
    under_actual_equal = (under_pred['actual_strikeouts'] == under_pred['strikeouts_line']).mean()

    print(f"  OVER predictions:  actual > line = {over_actual_above*100:.1f}%  "
          f"actual = line = {over_actual_equal*100:.1f}%  "
          f"actual < line = {(1-over_actual_above-over_actual_equal)*100:.1f}%  (N={len(over_pred)})")
    print(f"  UNDER predictions: actual < line = {under_actual_below*100:.1f}%  "
          f"actual = line = {under_actual_equal*100:.1f}%  "
          f"actual > line = {(1-under_actual_below-under_actual_equal)*100:.1f}%  (N={len(under_pred)})")

    # Push — how often does actual == line?
    push_rate = (df['actual_strikeouts'] == df['strikeouts_line']).mean()
    print(f"\n  Push rate (actual == line): {push_rate*100:.1f}%")
    # Push by line level
    print("  Push rate by line level:")
    for bucket, grp in df_line.groupby('line_bucket', observed=True):
        push = (grp['actual_strikeouts'] == grp['strikeouts_line']).mean()
        print(f"    Line {bucket:>8s}: push_rate={push*100:.1f}%  N={len(grp)}")


# ============================================================
# 5. BLACKLIST VALIDATION
# ============================================================
def validate_blacklist(df, df_wide):
    section("5. BLACKLIST VALIDATION — Are all 10 pitchers truly bad?")

    print(f"\nCurrent blacklist ({len(CURRENT_BLACKLIST)} pitchers):")
    print(f"  {', '.join(sorted(CURRENT_BLACKLIST))}")
    print(f"\nValidation criteria: N >= {MIN_N}, HR < 45% = CONFIRMED, 45-50% = BORDERLINE, 50%+ = INVALID")

    # Use primary (edge 1.0) and wide (edge 0.5) datasets
    print(f"\n{SUB_SEP}")
    print("BLACKLIST PITCHER DETAIL — Edge >= 1.0 (production threshold)")
    print(f"{SUB_SEP}")

    confirmed = []
    borderline = []
    invalid = []
    insufficient = []

    for pitcher in sorted(CURRENT_BLACKLIST):
        sub = df[df['pitcher_lookup'] == pitcher]
        if len(sub) == 0:
            print(f"  {pitcher:25s}  NO DATA at edge >= 1.0")
            insufficient.append(pitcher)
            continue
        hr = sub['correct'].mean()
        n = len(sub)
        over_n = len(sub[sub['pred_direction'] == 'OVER'])
        under_n = len(sub[sub['pred_direction'] == 'UNDER'])
        over_hr = sub[sub['pred_direction'] == 'OVER']['correct'].mean() if over_n > 0 else float('nan')
        under_hr = sub[sub['pred_direction'] == 'UNDER']['correct'].mean() if under_n > 0 else float('nan')

        if n < MIN_N:
            verdict = "INSUFFICIENT_N"
            insufficient.append(pitcher)
        elif hr < 0.45:
            verdict = "CONFIRMED_BAD"
            confirmed.append(pitcher)
        elif hr < 0.50:
            verdict = "BORDERLINE"
            borderline.append(pitcher)
        else:
            verdict = "INVALID — SHOULD REMOVE"
            invalid.append(pitcher)

        over_hr_str = f"{over_hr*100:.1f}%" if not np.isnan(over_hr) else "N/A"
        under_hr_str = f"{under_hr*100:.1f}%" if not np.isnan(under_hr) else "N/A"

        print(f"  {pitcher:25s}  HR={hr*100:5.1f}%  N={n:3d}  "
              f"OVER_HR={over_hr_str:>6s} (N={over_n:2d})  "
              f"UNDER_HR={under_hr_str:>6s} (N={under_n:2d})  "
              f"K/9={sub['season_k_per_9'].mean():.1f}  "
              f"avg_line={sub['strikeouts_line'].mean():.1f}  "
              f"→ {verdict}")

    # Check wider data for insufficient pitchers
    if insufficient:
        print(f"\n{SUB_SEP}")
        print("CHECKING WIDER DATASET (edge >= 0.5) FOR INSUFFICIENT PITCHERS")
        print(f"{SUB_SEP}")
        for pitcher in insufficient:
            sub = df_wide[df_wide['pitcher_lookup'] == pitcher]
            if len(sub) == 0:
                print(f"  {pitcher:25s}  STILL NO DATA at edge >= 0.5")
                continue
            hr = sub['correct'].mean()
            n = len(sub)
            v = "OK" if n >= MIN_N else f"still low N={n}"
            print(f"  {pitcher:25s}  HR={hr*100:5.1f}%  N={n:3d}  ({v})")

    # Find pitchers NOT on blacklist but should be
    print(f"\n{SUB_SEP}")
    print("PITCHERS NOT ON BLACKLIST BUT POTENTIALLY SHOULD BE (HR < 45%, N >= 10)")
    print(f"{SUB_SEP}")
    pitcher_agg = df.groupby(['pitcher_name', 'pitcher_lookup']).agg(
        HR=('correct', 'mean'), N=('correct', 'count'),
        avg_k9=('season_k_per_9', 'mean'),
        avg_line=('strikeouts_line', 'mean'),
    ).reset_index()
    candidates = pitcher_agg[
        (pitcher_agg['N'] >= MIN_N) &
        (pitcher_agg['HR'] < 0.45) &
        (~pitcher_agg['pitcher_lookup'].isin(CURRENT_BLACKLIST))
    ].sort_values('HR')

    if len(candidates) == 0:
        print("  None found — blacklist catches all sub-45% pitchers with N >= 10")
    else:
        for _, row in candidates.iterrows():
            print(f"  {row['pitcher_name']:25s}  HR={row['HR']*100:5.1f}%  N={int(row['N']):3d}  "
                  f"K/9={row['avg_k9']:.1f}  avg_line={row['avg_line']:.1f}  "
                  f"→ CANDIDATE FOR BLACKLIST")

    # Summary
    print(f"\n{SUB_SEP}")
    print("BLACKLIST SUMMARY")
    print(f"{SUB_SEP}")
    print(f"  CONFIRMED BAD (HR < 45%):     {len(confirmed)} — {confirmed}")
    print(f"  BORDERLINE (45-50%):           {len(borderline)} — {borderline}")
    print(f"  INVALID (HR >= 50%, remove!):  {len(invalid)} — {invalid}")
    print(f"  INSUFFICIENT DATA (N < 10):    {len(insufficient)} — {insufficient}")

    # Impact analysis: How much do blacklisted pitchers drag down overall HR?
    bl_picks = df[df['pitcher_lookup'].isin(CURRENT_BLACKLIST)]
    non_bl_picks = df[~df['pitcher_lookup'].isin(CURRENT_BLACKLIST)]
    print(f"\n  Blacklisted pitcher picks: N={len(bl_picks)}, HR={bl_picks['correct'].mean()*100:.1f}%")
    print(f"  Non-blacklisted picks:     N={len(non_bl_picks)}, HR={non_bl_picks['correct'].mean()*100:.1f}%")
    if len(bl_picks) > 0:
        lift = non_bl_picks['correct'].mean() - df['correct'].mean()
        print(f"  Removing blacklisted pitchers would lift HR by: {lift*100:+.1f}pp")


# ============================================================
# 6. PITCHER STREAKS
# ============================================================
def analyze_streaks(df, df_wide):
    section("6. PITCHER STREAKS — Is recent form predictive?")

    # Use wide data for more coverage of individual pitchers
    data = df_wide.sort_values(['pitcher_lookup', 'game_date']).copy()

    # Compute rolling HR for each pitcher (last 3 and last 5 starts)
    data['rolling_3'] = data.groupby('pitcher_lookup')['correct'].transform(
        lambda x: x.rolling(3, min_periods=3).mean().shift(1)
    )
    data['rolling_5'] = data.groupby('pitcher_lookup')['correct'].transform(
        lambda x: x.rolling(5, min_periods=5).mean().shift(1)
    )

    # Also compute rolling actual_over rate
    data['rolling_over_3'] = data.groupby('pitcher_lookup')['actual_over'].transform(
        lambda x: x.rolling(3, min_periods=3).mean().shift(1)
    )

    valid_3 = data.dropna(subset=['rolling_3'])
    valid_5 = data.dropna(subset=['rolling_5'])

    print(f"\n  Picks with 3-start history: {len(valid_3)}")
    print(f"  Picks with 5-start history: {len(valid_5)}")

    # Is a hot pitcher (high rolling HR) predictive?
    print(f"\n{SUB_SEP}")
    print("ROLLING 3-START HR AS PREDICTOR")
    print(f"{SUB_SEP}")
    bins_3 = [(0, 0.01, 'All 3 wrong (0%)'), (0.01, 0.34, '1 of 3 (33%)'),
              (0.34, 0.67, '2 of 3 (67%)'), (0.67, 1.01, 'All 3 right (100%)')]
    for lo, hi, label in bins_3:
        sub = valid_3[(valid_3['rolling_3'] >= lo) & (valid_3['rolling_3'] < hi)]
        if len(sub) > 0:
            print(f"  Last 3 = {label:20s}: next_HR={sub['correct'].mean()*100:5.1f}%  N={len(sub)}")

    print(f"\n{SUB_SEP}")
    print("ROLLING 5-START HR AS PREDICTOR")
    print(f"{SUB_SEP}")
    bins_5 = [(0, 0.21, '0-1 of 5 (0-20%)'), (0.21, 0.41, '2 of 5 (40%)'),
              (0.41, 0.61, '3 of 5 (60%)'), (0.61, 0.81, '4 of 5 (80%)'),
              (0.81, 1.01, '5 of 5 (100%)')]
    for lo, hi, label in bins_5:
        sub = valid_5[(valid_5['rolling_5'] >= lo) & (valid_5['rolling_5'] < hi)]
        if len(sub) > 0:
            print(f"  Last 5 = {label:20s}: next_HR={sub['correct'].mean()*100:5.1f}%  N={len(sub)}")

    # Autocorrelation: is correct[t] correlated with correct[t+1]?
    print(f"\n{SUB_SEP}")
    print("AUTOCORRELATION — Does last start predict next?")
    print(f"{SUB_SEP}")
    data_lag = data.copy()
    data_lag['prev_correct'] = data_lag.groupby('pitcher_lookup')['correct'].shift(1)
    data_lag = data_lag.dropna(subset=['prev_correct'])
    corr = data_lag['correct'].corr(data_lag['prev_correct'])
    print(f"  Autocorrelation (correct[t-1] vs correct[t]): r = {corr:.4f}")

    # After win vs after loss
    after_win = data_lag[data_lag['prev_correct'] == 1]
    after_loss = data_lag[data_lag['prev_correct'] == 0]
    print(f"  After WIN:  next_HR={after_win['correct'].mean()*100:.1f}%  N={len(after_win)}")
    print(f"  After LOSS: next_HR={after_loss['correct'].mean()*100:.1f}%  N={len(after_loss)}")

    # Over/under streaks
    print(f"\n{SUB_SEP}")
    print("OVER/UNDER STREAKS — Does recent over/under trend predict?")
    print(f"{SUB_SEP}")
    bins_over = [(0, 0.01, '0 of 3 OVER'), (0.01, 0.34, '1 of 3 OVER'),
                 (0.34, 0.67, '2 of 3 OVER'), (0.67, 1.01, '3 of 3 OVER')]
    for lo, hi, label in bins_over:
        sub = valid_3[(valid_3['rolling_over_3'] >= lo) & (valid_3['rolling_over_3'] < hi)]
        if len(sub) > 0:
            # What's the actual over rate in the next start?
            next_over = sub['actual_over'].mean()
            # And model HR?
            next_hr = sub['correct'].mean()
            print(f"  {label:18s}: next_over_rate={next_over*100:5.1f}%  "
                  f"model_HR={next_hr*100:5.1f}%  N={len(sub)}")

    # Hot/cold streak lengths
    print(f"\n{SUB_SEP}")
    print("STREAK LENGTH ANALYSIS")
    print(f"{SUB_SEP}")
    # Compute consecutive correct/incorrect streaks per pitcher
    streaks = []
    for pitcher, grp in data.groupby('pitcher_lookup'):
        grp = grp.sort_values('game_date')
        curr_streak = 0
        for _, row in grp.iterrows():
            if row['correct'] == 1:
                curr_streak = max(curr_streak, 0) + 1
            else:
                curr_streak = min(curr_streak, 0) - 1
            streaks.append({
                'pitcher': pitcher,
                'streak': curr_streak,
                'correct': row['correct'],
                'next_correct': None,
            })

    streak_df = pd.DataFrame(streaks)
    # For each row, the "next" row's correct value
    streak_df['next_correct'] = streak_df.groupby('pitcher')['correct'].shift(-1)
    streak_valid = streak_df.dropna(subset=['next_correct'])

    for streak_val in [-3, -2, -1, 1, 2, 3]:
        if streak_val > 0:
            sub = streak_valid[streak_valid['streak'] >= streak_val]
            label = f"Win streak >= {streak_val}"
        else:
            sub = streak_valid[streak_valid['streak'] <= streak_val]
            label = f"Loss streak <= {streak_val}"
        if len(sub) >= 20:
            next_hr = sub['next_correct'].mean()
            print(f"  {label:22s}: next_HR={next_hr*100:5.1f}%  N={len(sub)}")

    # Days rest impact
    print(f"\n{SUB_SEP}")
    print("DAYS REST IMPACT ON HR")
    print(f"{SUB_SEP}")
    rest_bins = [(0, 4, '<4d (short)'), (4, 5, '4d'), (5, 6, '5d (normal)'),
                 (6, 7, '6d'), (7, 10, '7-9d'), (10, 999, '10d+')]
    for lo, hi, label in rest_bins:
        sub = df[(df['days_rest'] >= lo) & (df['days_rest'] < hi)]
        if len(sub) >= 10:
            print(f"  {label:15s}: HR={sub['correct'].mean()*100:5.1f}%  N={len(sub)}  "
                  f"avg_edge={sub['edge'].mean():.2f}")


# ============================================================
# 7. ACE PARADOX
# ============================================================
def analyze_ace_paradox(df):
    section("7. ACE PARADOX — Are high-K/9 pitchers harder to predict?")

    overall_hr = df['correct'].mean()

    # Define ace tiers
    df_copy = df.copy()
    df_copy['tier'] = pd.cut(df_copy['season_k_per_9'],
                              bins=[0, 7, 8, 9, 10, 11, 12, 15],
                              labels=['<7 (back-end)', '7-8 (mid)', '8-9 (avg)',
                                      '9-10 (good)', '10-11 (ace-)', '11-12 (ace)', '12+ (elite)'])

    print(f"\n{SUB_SEP}")
    print("HR BY K/9 TIER")
    print(f"{SUB_SEP}")
    for tier, grp in df_copy.groupby('tier', observed=True):
        delta = grp['correct'].mean() - overall_hr
        err_std = grp['line_error'].std()
        over_rate = grp['actual_over'].mean()
        print(f"  {tier:20s}: HR={grp['correct'].mean()*100:5.1f}%  delta={delta*100:+5.1f}pp  "
              f"N={len(grp):5d}  line_err_std={err_std:.2f}  "
              f"over_rate={over_rate*100:.1f}%  avg_line={grp['strikeouts_line'].mean():.1f}")

    # Within aces: OVER vs UNDER
    print(f"\n{SUB_SEP}")
    print("ACE (K/9 >= 10) — OVER vs UNDER DIRECTION")
    print(f"{SUB_SEP}")
    aces = df_copy[df_copy['season_k_per_9'] >= 10]
    non_aces = df_copy[df_copy['season_k_per_9'] < 10]

    for label, sub in [("ACES (K/9 >= 10)", aces), ("NON-ACES (K/9 < 10)", non_aces)]:
        print(f"\n  {label}:")
        for direction in ['OVER', 'UNDER']:
            d = sub[sub['pred_direction'] == direction]
            if len(d) > 0:
                print(f"    {direction:5s}: HR={d['correct'].mean()*100:5.1f}%  N={len(d)}  "
                      f"avg_edge={d['edge'].mean():.2f}  "
                      f"avg_line={d['strikeouts_line'].mean():.1f}")

    # Line sharpness for aces vs non-aces
    print(f"\n{SUB_SEP}")
    print("LINE SHARPNESS — Is the market more accurate for aces?")
    print(f"{SUB_SEP}")
    for label, sub in [("ACES (K/9 >= 10)", aces), ("NON-ACES (K/9 < 10)", non_aces)]:
        mae = np.abs(sub['line_error']).mean()
        line_bias = sub['line_error'].mean()
        push_rate = (sub['actual_strikeouts'] == sub['strikeouts_line']).mean()
        print(f"  {label:25s}: MAE={mae:.2f}  bias={line_bias:+.2f}  "
              f"push_rate={push_rate*100:.1f}%  N={len(sub)}")

    # What K/9 range is the sweet spot?
    print(f"\n{SUB_SEP}")
    print("OPTIMAL K/9 RANGE FOR PROFITABILITY")
    print(f"{SUB_SEP}")
    # Finer grain
    fine_bins = [(0, 6), (6, 7), (7, 8), (8, 8.5), (8.5, 9), (9, 9.5), (9.5, 10),
                 (10, 10.5), (10.5, 11), (11, 12), (12, 15)]
    best_hr = 0
    best_range = None
    for lo, hi in fine_bins:
        sub = df_copy[(df_copy['season_k_per_9'] >= lo) & (df_copy['season_k_per_9'] < hi)]
        if len(sub) >= 30:
            hr = sub['correct'].mean()
            if hr > best_hr:
                best_hr = hr
                best_range = f"{lo}-{hi}"
            print(f"  K/9 {lo:4.1f}-{hi:4.1f}: HR={hr*100:5.1f}%  N={len(sub):5d}  "
                  f"avg_edge={sub['edge'].mean():.2f}")

    print(f"\n  >>> OPTIMAL K/9 RANGE: {best_range} at {best_hr*100:.1f}% HR")

    # Ace-specific analysis: variance decomposition
    print(f"\n{SUB_SEP}")
    print("VARIANCE DECOMPOSITION — Why are aces hard?")
    print(f"{SUB_SEP}")
    for label, sub in [("ACES (K/9 >= 10)", aces), ("NON-ACES (K/9 < 10)", non_aces)]:
        actual_std = sub['actual_strikeouts'].std()
        line_std = sub['strikeouts_line'].std()
        error_std = sub['line_error'].std()
        # Coefficient of variation of actual K
        cv = sub['actual_strikeouts'].std() / sub['actual_strikeouts'].mean()
        print(f"  {label:25s}:")
        print(f"    actual_K std:    {actual_std:.2f}  (mean={sub['actual_strikeouts'].mean():.1f})")
        print(f"    line std:        {line_std:.2f}  (mean={sub['strikeouts_line'].mean():.1f})")
        print(f"    error std:       {error_std:.2f}")
        print(f"    K CV (std/mean): {cv:.3f}")

    # Edge threshold for aces
    print(f"\n{SUB_SEP}")
    print("EDGE THRESHOLD FOR ACES — Do aces need higher edge?")
    print(f"{SUB_SEP}")
    for edge_floor in [1.0, 1.5, 2.0, 2.5, 3.0]:
        ace_sub = aces[aces['edge'] >= edge_floor]
        non_ace_sub = non_aces[non_aces['edge'] >= edge_floor]
        if len(ace_sub) >= 20 and len(non_ace_sub) >= 20:
            print(f"  Edge >= {edge_floor:.1f}: "
                  f"ACES={ace_sub['correct'].mean()*100:.1f}% (N={len(ace_sub)})  "
                  f"NON-ACES={non_ace_sub['correct'].mean()*100:.1f}% (N={len(non_ace_sub)})  "
                  f"gap={((ace_sub['correct'].mean()-non_ace_sub['correct'].mean())*100):+.1f}pp")


# ============================================================
# 8. SYNTHESIS & RECOMMENDATIONS
# ============================================================
def synthesis(df, pitcher_stats, valid):
    section("8. SYNTHESIS & ACTIONABLE RECOMMENDATIONS")

    overall_hr = df['correct'].mean()
    bl_picks = df[df['pitcher_lookup'].isin(CURRENT_BLACKLIST)]
    non_bl_picks = df[~df['pitcher_lookup'].isin(CURRENT_BLACKLIST)]

    print(f"""
  DATASET: {len(df)} predictions at edge >= 1.0, {df['pitcher_lookup'].nunique()} unique pitchers
  OVERALL HR: {overall_hr*100:.1f}%
  DATE RANGE: {df['game_date'].min().date()} to {df['game_date'].max().date()}
  """)

    # Blacklist impact
    if len(bl_picks) > 0:
        print(f"  BLACKLIST IMPACT:")
        print(f"    Blacklisted picks:     HR={bl_picks['correct'].mean()*100:.1f}% (N={len(bl_picks)})")
        print(f"    Non-blacklisted picks: HR={non_bl_picks['correct'].mean()*100:.1f}% (N={len(non_bl_picks)})")
        lift = (non_bl_picks['correct'].mean() - overall_hr) * 100
        print(f"    Lift from blacklist:    {lift:+.1f}pp")

    # Find optimal filters
    # K/9 filter
    low_k9 = df[df['season_k_per_9'] < 7]
    high_k9 = df[df['season_k_per_9'] >= 11]
    mid_k9 = df[(df['season_k_per_9'] >= 7) & (df['season_k_per_9'] < 11)]

    print(f"\n  K/9 FILTER IMPACT:")
    print(f"    K/9 < 7:    HR={low_k9['correct'].mean()*100:.1f}% (N={len(low_k9)})")
    print(f"    K/9 7-11:   HR={mid_k9['correct'].mean()*100:.1f}% (N={len(mid_k9)})")
    print(f"    K/9 >= 11:  HR={high_k9['correct'].mean()*100:.1f}% (N={len(high_k9)})")

    # Candidates for new blacklist pitchers
    pitcher_agg = df.groupby(['pitcher_name', 'pitcher_lookup']).agg(
        HR=('correct', 'mean'), N=('correct', 'count'),
    ).reset_index()
    new_candidates = pitcher_agg[
        (pitcher_agg['N'] >= MIN_N) &
        (pitcher_agg['HR'] < 0.45) &
        (~pitcher_agg['pitcher_lookup'].isin(CURRENT_BLACKLIST))
    ]
    print(f"\n  NEW BLACKLIST CANDIDATES: {len(new_candidates)}")
    for _, row in new_candidates.iterrows():
        print(f"    {row['pitcher_name']:25s}  HR={row['HR']*100:.1f}%  N={int(row['N'])}")

    # Pitchers to REMOVE from blacklist
    remove_candidates = []
    for pitcher in sorted(CURRENT_BLACKLIST):
        sub = df[df['pitcher_lookup'] == pitcher]
        if len(sub) >= MIN_N and sub['correct'].mean() >= 0.50:
            remove_candidates.append((pitcher, sub['correct'].mean(), len(sub)))
    print(f"\n  REMOVE FROM BLACKLIST (HR >= 50%, N >= {MIN_N}): {len(remove_candidates)}")
    for p, hr, n in remove_candidates:
        print(f"    {p:25s}  HR={hr*100:.1f}%  N={n}")

    # Overall recommendations
    print(f"""
  {SUB_SEP}
  KEY RECOMMENDATIONS
  {SUB_SEP}
  1. BLACKLIST REFINEMENT:
     - Validate each pitcher quarterly with fresh data
     - Use N >= 10 minimum (current threshold is good)
     - Consider DIRECTION-specific blacklists (some pitchers bad for OVER but fine for UNDER)

  2. LINE-LEVEL FILTERS:
     - Low lines (<=3.5) and high lines (>=8.5) may need separate treatment
     - Push rate varies significantly by line level

  3. K/9 AWARENESS:
     - Track whether "ace paradox" holds in live data
     - Consider K/9-adjusted edge thresholds

  4. STREAK-BASED SIGNALS:
     - Evaluate whether rolling 3-5 start HR is a viable signal
     - Over/under streaks (3 consecutive) may have mean-reversion value

  5. MATCHUP-BASED SIGNALS:
     - Opponent K-rate is a strong modifier
     - Specific pitcher-opponent combos are too sparse for individual rules
  """)


# ============================================================
# MAIN
# ============================================================
def main():
    print(SEPARATOR)
    print("  MLB PITCHER DEEP DIVE ANALYSIS")
    print(f"  Data: {PRIMARY_FILE.name}")
    print(f"  Date: 2026-03-08")
    print(SEPARATOR)

    df = load_data()
    df_wide = load_wide_data()

    print(f"\n  Primary dataset (edge >= 1.0): {len(df)} predictions, "
          f"{df['pitcher_lookup'].nunique()} pitchers")
    print(f"  Wide dataset (edge >= 0.5):    {len(df_wide)} predictions, "
          f"{df_wide['pitcher_lookup'].nunique()} pitchers")
    print(f"  Date range: {df['game_date'].min().date()} to {df['game_date'].max().date()}")

    pitcher_stats, valid = analyze_pitcher_consistency(df)
    analyze_pitcher_traits(df, pitcher_stats, valid)
    analyze_matchups(df, df_wide)
    analyze_line_accuracy(df)
    validate_blacklist(df, df_wide)
    analyze_streaks(df, df_wide)
    analyze_ace_paradox(df)
    synthesis(df, pitcher_stats, valid)


if __name__ == '__main__':
    main()
