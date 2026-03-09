#!/usr/bin/env python3
"""MLB Signal & Filter Optimization — Part 2: Deeper dives.

Follow-up analysis from Part 1:
1. CWS status (was in bad_opponents, now 50.8% — validate)
2. Away pitcher as a SIGNAL (not filter) — home pitcher boost for ranking
3. Edge floor sweet spot with standard vs aggressive filter
4. Best configuration recommendation (profit-maximizing)
5. Pitcher blacklist validation — are we removing good pitchers' occasional bad runs?
6. UNDER sweet spot drill-down (edge 0.5-0.75 was 59.7%)
7. Top-3 daily selection with signal-based ranking vs pure edge ranking
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

DATA_FILE = Path('/home/naji/code/nba-stats-scraper/results/mlb_walkforward_v4_regression/predictions_regression_120d_edge0.25.csv')
df = pd.read_csv(DATA_FILE)

EXPANDED_BLACKLIST = frozenset([
    'bradley_blalock', 'casey_mize', 'davis_martin', 'george_kirby',
    'jack_kochanowicz', 'jake_irvin', 'jameson_taillon', 'javier_assad',
    'jeffrey_springs', 'josé_berríos', 'logan_allen', 'luis_severino',
    'mackenzie_gore', 'mitch_keller', 'mitchell_parker', 'randy_vásquez',
    'ryan_feltner', 'ryne_nelson', 'tanner_bibee', 'tyler_mahle', 'zach_eflin',
])

CURRENT_BLACKLIST = frozenset([
    'freddy_peralta', 'tyler_glasnow', 'tanner_bibee', 'mitchell_parker',
    'hunter_greene', 'yusei_kikuchi', 'casey_mize', 'paul_skenes',
    'jose_soriano', 'mitch_keller',
])

EXPANDED_BAD_OPPS = frozenset(['AZ', 'KC', 'MIA'])
EXPANDED_BAD_VENUES = frozenset([
    'Guaranteed Rate Field', 'Nationals Park', 'Progressive Field', 'loanDepot park',
])

# =============================================================================
# 1. CWS VALIDATION — should we keep them in bad opponents?
# =============================================================================
print("=" * 90)
print("  1. CWS OPPONENT VALIDATION")
print("=" * 90)

over_base = df[(df['predicted_over'] == 1) & (df['abs_edge'] >= 0.5)]
cws = over_base[over_base['opponent_team_abbr'] == 'CWS']
print(f"\n  vs CWS (OVER, edge >= 0.5): {cws['correct'].mean():.1%} (N={len(cws)})")
print(f"  At 50.8%, CWS is borderline — just above 50%. Not bad enough to filter.")
print(f"  DROP CWS from bad opponents list.")

# AZ validation
az = over_base[over_base['opponent_team_abbr'] == 'AZ']
print(f"\n  vs AZ (OVER, edge >= 0.5): {az['correct'].mean():.1%} (N={len(az)})")
if len(az) < 20:
    print(f"  WARNING: N={len(az)} is small. AZ filter may be noisy.")

# =============================================================================
# 2. AWAY PITCHER AS SIGNAL (ranking boost, not hard filter)
# =============================================================================
print("\n\n" + "=" * 90)
print("  2. HOME/AWAY AS RANKING SIGNAL (not hard filter)")
print("=" * 90)

# At edge >= 0.75, home vs away
over_75 = df[(df['predicted_over'] == 1) & (df['abs_edge'] >= 0.75)]
home = over_75[over_75['is_home'] == 1]
away = over_75[over_75['is_home'] == 0]
print(f"\n  Edge >= 0.75:")
print(f"    HOME: {home['correct'].mean():.1%} (N={len(home)})")
print(f"    AWAY: {away['correct'].mean():.1%} (N={len(away)})")
print(f"    Lift: {(home['correct'].mean() - away['correct'].mean())*100:+.1f}pp")

# By edge bucket, home vs away
print(f"\n  Home vs Away by edge bucket:")
for lo, hi in [(0.5, 0.75), (0.75, 1.0), (1.0, 1.25), (1.25, 1.5), (1.5, 2.0)]:
    h = over_base[(over_base['abs_edge'] >= lo) & (over_base['abs_edge'] < hi) & (over_base['is_home'] == 1)]
    a = over_base[(over_base['abs_edge'] >= lo) & (over_base['abs_edge'] < hi) & (over_base['is_home'] == 0)]
    if len(h) >= 20 and len(a) >= 20:
        print(f"    [{lo:.2f}, {hi:.2f}): HOME {h['correct'].mean():.1%}(N={len(h)}) vs AWAY {a['correct'].mean():.1%}(N={len(a)}) "
              f"= {(h['correct'].mean()-a['correct'].mean())*100:+.1f}pp")

print(f"\n  CONCLUSION: Home pitcher is a RANKING signal, not a filter.")
print(f"  Use it to boost home pitchers in ranking, not block away pitchers.")


# =============================================================================
# 3. BLACKLIST DEEP-DIVE — validate expanded list
# =============================================================================
print("\n\n" + "=" * 90)
print("  3. PITCHER BLACKLIST DEEP-DIVE")
print("=" * 90)

# Check pitchers that were in current list but NOT in expanded
removed = CURRENT_BLACKLIST - EXPANDED_BLACKLIST
kept = CURRENT_BLACKLIST & EXPANDED_BLACKLIST
added = EXPANDED_BLACKLIST - CURRENT_BLACKLIST

print(f"\n  Current blacklist: {len(CURRENT_BLACKLIST)}")
print(f"  Expanded blacklist: {len(EXPANDED_BLACKLIST)}")
print(f"  Kept: {len(kept)}, Removed: {len(removed)}, Added: {len(added)}")

# Check removed pitchers' HR
print(f"\n  REMOVED from blacklist (>= 45% HR at edge >= 0.5):")
for p in sorted(removed):
    subset = over_base[over_base['pitcher_lookup'] == p]
    if len(subset) > 0:
        print(f"    {p:<25} {subset['correct'].mean():.1%} (N={len(subset)})")
    else:
        print(f"    {p:<25} no picks in this dataset")

# Check added pitchers
print(f"\n  ADDED to blacklist (<45% HR, N >= 8):")
for p in sorted(added):
    subset = over_base[over_base['pitcher_lookup'] == p]
    if len(subset) > 0:
        print(f"    {p:<25} {subset['correct'].mean():.1%} (N={len(subset)})")

# Verify: what's the HR of picks from EXPANDED_BLACKLIST pitchers at different edge floors?
print(f"\n  Blacklisted pitcher HR by edge floor:")
for edge_floor in [0.25, 0.5, 0.75, 1.0]:
    over_ef = df[(df['predicted_over'] == 1) & (df['abs_edge'] >= edge_floor)]
    bl_picks = over_ef[over_ef['pitcher_lookup'].isin(EXPANDED_BLACKLIST)]
    non_bl = over_ef[~over_ef['pitcher_lookup'].isin(EXPANDED_BLACKLIST)]
    if len(bl_picks) > 0:
        print(f"    edge >= {edge_floor}: BLACKLIST {bl_picks['correct'].mean():.1%}(N={len(bl_picks)}) "
              f"vs CLEAN {non_bl['correct'].mean():.1%}(N={len(non_bl)}) "
              f"= {(non_bl['correct'].mean()-bl_picks['correct'].mean())*100:+.1f}pp lift")


# =============================================================================
# 4. UNDER SWEET SPOT — edge 0.5-0.75 deep dive
# =============================================================================
print("\n\n" + "=" * 90)
print("  4. UNDER SWEET SPOT — edge [0.50, 0.75)")
print("=" * 90)

under_sweet = df[(df['predicted_over'] == 0) & (df['abs_edge'] >= 0.50) & (df['abs_edge'] < 0.75)].copy()
print(f"\n  UNDER [0.50, 0.75) HR: {under_sweet['correct'].mean():.1%} (N={len(under_sweet)})")

if len(under_sweet) >= 30:
    # Line level
    print(f"\n  By line level:")
    for lo, hi in [(3.5, 5.0), (5.0, 6.0), (6.0, 6.5), (6.5, 7.0), (7.0, 10.0)]:
        s = under_sweet[(under_sweet['strikeouts_line'] >= lo) & (under_sweet['strikeouts_line'] < hi)]
        if len(s) >= 5:
            print(f"    line [{lo}, {hi}): {s['correct'].mean():.1%} (N={len(s)})")

    # K/9
    print(f"\n  By K/9:")
    for lo, hi in [(0, 7), (7, 9), (9, 11), (11, 15)]:
        s = under_sweet[(under_sweet['season_k_per_9'] >= lo) & (under_sweet['season_k_per_9'] < hi)]
        if len(s) >= 5:
            print(f"    K/9 [{lo}, {hi}): {s['correct'].mean():.1%} (N={len(s)})")

    # Home/Away
    home_u = under_sweet[under_sweet['is_home'] == 1]
    away_u = under_sweet[under_sweet['is_home'] == 0]
    print(f"\n  Home: {home_u['correct'].mean():.1%} (N={len(home_u)})")
    print(f"  Away: {away_u['correct'].mean():.1%} (N={len(away_u)})")

    # Day/Night
    day_u = under_sweet[under_sweet['is_day_game'] == 1]
    night_u = under_sweet[under_sweet['is_day_game'] == 0]
    print(f"\n  Day:   {day_u['correct'].mean():.1%} (N={len(day_u)})")
    print(f"  Night: {night_u['correct'].mean():.1%} (N={len(night_u)})")

    # Projection
    u_proj = under_sweet.dropna(subset=['projection_value'])
    u_proj_agrees = u_proj[u_proj['projection_value'] < u_proj['strikeouts_line']]
    u_proj_disagrees = u_proj[u_proj['projection_value'] >= u_proj['strikeouts_line']]
    print(f"\n  Proj agrees (< line): {u_proj_agrees['correct'].mean():.1%} (N={len(u_proj_agrees)})")
    print(f"  Proj disagrees:       {u_proj_disagrees['correct'].mean():.1%} (N={len(u_proj_disagrees)})")

    # avg5 < line
    cold_u = under_sweet[under_sweet['k_avg_last_5'] < under_sweet['strikeouts_line']]
    hot_u = under_sweet[under_sweet['k_avg_last_5'] >= under_sweet['strikeouts_line']]
    print(f"\n  Cold (avg5 < line):   {cold_u['correct'].mean():.1%} (N={len(cold_u)})")
    print(f"  Hot (avg5 >= line):   {hot_u['correct'].mean():.1%} (N={len(hot_u)})")

    # Combo: low line + cold
    lo_cold = under_sweet[(under_sweet['strikeouts_line'] < 6.5) & (under_sweet['k_avg_last_5'] < under_sweet['strikeouts_line'])]
    hi_hot = under_sweet[(under_sweet['strikeouts_line'] >= 6.5) & (under_sweet['k_avg_last_5'] >= under_sweet['strikeouts_line'])]
    print(f"\n  Low line + cold: {lo_cold['correct'].mean():.1%} (N={len(lo_cold)})" if len(lo_cold) >= 5 else "")
    print(f"  High line + hot: {hi_hot['correct'].mean():.1%} (N={len(hi_hot)})" if len(hi_hot) >= 5 else "")


# =============================================================================
# 5. UNDER across ALL edges — volume-profit tradeoff
# =============================================================================
print("\n\n" + "=" * 90)
print("  5. UNDER FULL ANALYSIS — can we make UNDER work?")
print("=" * 90)

under_all = df[df['predicted_over'] == 0].copy()
print(f"\n  ALL UNDER: {under_all['correct'].mean():.1%} (N={len(under_all)})")

# Filter combos for UNDER
under_filt = under_all[under_all['abs_edge'] >= 0.5].copy()
if len(under_filt) >= 30:
    # Signal combination for UNDER
    under_filt['u_low_line'] = under_filt['strikeouts_line'] < 6.5
    under_filt['u_proj_agrees'] = under_filt['projection_value'] < under_filt['strikeouts_line']
    under_filt['u_cold'] = under_filt['k_avg_last_5'] < under_filt['strikeouts_line']
    under_filt['u_home'] = under_filt['is_home'] == 1
    under_filt['u_sc'] = (
        under_filt['u_low_line'].astype(int) +
        under_filt['u_proj_agrees'].astype(int) +
        under_filt['u_cold'].astype(int) +
        under_filt['u_home'].astype(int)
    )

    print(f"\n  UNDER signal combos (edge >= 0.5):")
    print(f"  {'Combo':<50} {'HR':>7} {'N':>5}")
    print(f"  {'-'*65}")

    combos = [
        ("low_line + cold", under_filt['u_low_line'] & under_filt['u_cold']),
        ("low_line + proj_agrees", under_filt['u_low_line'] & under_filt['u_proj_agrees']),
        ("cold + proj_agrees", under_filt['u_cold'] & under_filt['u_proj_agrees']),
        ("low_line + cold + proj", under_filt['u_low_line'] & under_filt['u_cold'] & under_filt['u_proj_agrees']),
        ("SC >= 3", under_filt['u_sc'] >= 3),
        ("SC >= 2", under_filt['u_sc'] >= 2),
        ("low_line only", under_filt['u_low_line'] & ~under_filt['u_cold']),
        ("cold only", under_filt['u_cold'] & ~under_filt['u_low_line']),
    ]

    for name, mask in combos:
        s = under_filt[mask]
        if len(s) >= 5:
            print(f"  {name:<50} {s['correct'].mean():>6.1%} {len(s):>5}")

    # UNDER monthly if we pick top-1 per day with SC >= 2
    under_sc2 = under_filt[under_filt['u_sc'] >= 2]
    if len(under_sc2) >= 20:
        top1_under = under_sc2.sort_values('abs_edge', ascending=False).groupby('game_date').head(1)
        print(f"\n  UNDER top-1/day with SC >= 2: {top1_under['correct'].mean():.1%} (N={len(top1_under)})")
        top1_under = top1_under.copy()
        top1_under['month'] = pd.to_datetime(top1_under['game_date']).dt.to_period('M')
        for month in sorted(top1_under['month'].unique()):
            m = top1_under[top1_under['month'] == month]
            print(f"    {str(month)}: {m['correct'].mean():.1%} (N={len(m)})")


# =============================================================================
# 6. SIGNAL-BASED RANKING vs PURE EDGE RANKING
# =============================================================================
print("\n\n" + "=" * 90)
print("  6. RANKING STRATEGY: Edge vs Signal-Weighted vs Hybrid")
print("=" * 90)

# Apply standard filters
over_clean = df[df['predicted_over'] == 1].copy()
over_clean = over_clean[over_clean['abs_edge'] <= 2.0]
over_clean = over_clean[~over_clean['pitcher_lookup'].isin(EXPANDED_BLACKLIST)]
over_clean = over_clean[~over_clean['opponent_team_abbr'].isin(EXPANDED_BAD_OPPS)]
over_clean = over_clean[~over_clean['venue'].isin(EXPANDED_BAD_VENUES)]
over_clean = over_clean[over_clean['abs_edge'] >= 0.75]

print(f"\n  Clean OVER pool (edge >= 0.75, filters applied): {over_clean['correct'].mean():.1%} (N={len(over_clean)})")

# Add signal scores
over_clean['s_proj'] = (over_clean['projection_value'] > over_clean['strikeouts_line']).astype(float) * 3.0
over_clean['s_home'] = (over_clean['is_home'] == 1).astype(float) * 2.0
over_clean['s_hot'] = (over_clean['k_avg_last_5'] > (over_clean['strikeouts_line'] + 1.0)).astype(float) * 2.0
over_clean['s_avg5'] = (over_clean['k_avg_last_5'] > over_clean['strikeouts_line']).astype(float) * 1.5
over_clean['s_long_rest'] = (over_clean['days_rest'] >= 7).astype(float) * 1.5
over_clean['s_night'] = (over_clean['is_day_game'] == 0).astype(float) * 1.0
over_clean['s_high_k9'] = (over_clean['season_k_per_9'] >= 9.0).astype(float) * 1.0

over_clean['signal_score'] = (
    over_clean['s_proj'] + over_clean['s_home'] + over_clean['s_hot'] +
    over_clean['s_avg5'] + over_clean['s_long_rest'] + over_clean['s_night'] +
    over_clean['s_high_k9']
)

# Hybrid: edge + signal_score * 0.3
over_clean['hybrid_score'] = over_clean['abs_edge'] + over_clean['signal_score'] * 0.3

# Compare ranking strategies
strategies = {
    'Pure Edge': 'abs_edge',
    'Pure Signal': 'signal_score',
    'Hybrid (edge + 0.3*sig)': 'hybrid_score',
}

print(f"\n  {'Strategy':<35} {'Top1 HR':>8} {'Top2 HR':>8} {'Top3 HR':>8} {'Top3 N':>7}")
print(f"  {'-'*70}")

for name, col in strategies.items():
    for top_n in [1, 2, 3]:
        top = over_clean.sort_values(col, ascending=False).groupby('game_date').head(top_n)
        if top_n == 1:
            t1_hr = top['correct'].mean()
            t1_n = len(top)
        elif top_n == 2:
            t2_hr = top['correct'].mean()
        elif top_n == 3:
            t3_hr = top['correct'].mean()
            t3_n = len(top)

    print(f"  {name:<35} {t1_hr:>7.1%} {t2_hr:>7.1%} {t3_hr:>7.1%} {t3_n:>7}")


# Also test hybrid with different signal weights
print(f"\n  Hybrid weight sensitivity (Top-3/day HR):")
print(f"  {'Signal Weight':>14} {'Top3 HR':>9} {'N':>6}")
print(f"  {'-'*32}")
for w in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0]:
    over_clean['_score'] = over_clean['abs_edge'] + over_clean['signal_score'] * w
    top3 = over_clean.sort_values('_score', ascending=False).groupby('game_date').head(3)
    print(f"  {w:>14.2f} {top3['correct'].mean():>8.1%} {len(top3):>6}")


# =============================================================================
# 7. FINAL RECOMMENDED CONFIGURATION — BATTLE TEST
# =============================================================================
print("\n\n" + "=" * 90)
print("  7. FINAL RECOMMENDED CONFIGURATION — BATTLE TESTED")
print("=" * 90)

# Best config from analysis:
# - Filters: overconfidence (>2.0), expanded blacklist, expanded bad_opp, expanded bad_venue
# - Edge floor: 0.75
# - Ranking: hybrid (edge + 0.3 * signal_score)
# - Top-3 per day

# Apply filters
best_pool = df[df['predicted_over'] == 1].copy()
best_pool = best_pool[best_pool['abs_edge'] <= 2.0]
best_pool = best_pool[~best_pool['pitcher_lookup'].isin(EXPANDED_BLACKLIST)]
best_pool = best_pool[~best_pool['opponent_team_abbr'].isin(EXPANDED_BAD_OPPS)]
best_pool = best_pool[~best_pool['venue'].isin(EXPANDED_BAD_VENUES)]
best_pool = best_pool[best_pool['abs_edge'] >= 0.75]

# Signal scores for ranking
best_pool['s_proj'] = (best_pool['projection_value'] > best_pool['strikeouts_line']).astype(float) * 3.0
best_pool['s_home'] = (best_pool['is_home'] == 1).astype(float) * 2.0
best_pool['s_hot'] = (best_pool['k_avg_last_5'] > (best_pool['strikeouts_line'] + 1.0)).astype(float) * 2.0
best_pool['s_avg5'] = (best_pool['k_avg_last_5'] > best_pool['strikeouts_line']).astype(float) * 1.5
best_pool['s_long_rest'] = (best_pool['days_rest'] >= 7).astype(float) * 1.5
best_pool['s_night'] = (best_pool['is_day_game'] == 0).astype(float) * 1.0
best_pool['s_high_k9'] = (best_pool['season_k_per_9'] >= 9.0).astype(float) * 1.0
best_pool['signal_score'] = (
    best_pool['s_proj'] + best_pool['s_home'] + best_pool['s_hot'] +
    best_pool['s_avg5'] + best_pool['s_long_rest'] + best_pool['s_night'] +
    best_pool['s_high_k9']
)
best_pool['hybrid_score'] = best_pool['abs_edge'] + best_pool['signal_score'] * 0.3

# Select top-3 by hybrid
top3_final = best_pool.sort_values('hybrid_score', ascending=False).groupby('game_date').head(3)

print(f"\n  FINAL CONFIG:")
print(f"    Filters: overconfidence (>2.0) + expanded BL + expanded bad_opp + expanded bad_venue")
print(f"    Edge floor: 0.75 K")
print(f"    Ranking: hybrid (edge + 0.3 * signal_quality)")
print(f"    Selection: top-3 per day")
print(f"\n  Pool: {len(best_pool)} predictions, {best_pool['game_date'].nunique()} days")
print(f"  HR (all pool): {best_pool['correct'].mean():.1%} (N={len(best_pool)})")
print(f"  HR (top-3/day): {top3_final['correct'].mean():.1%} (N={len(top3_final)})")

# Monthly
top3_final = top3_final.copy()
top3_final['month'] = pd.to_datetime(top3_final['game_date']).dt.to_period('M')

print(f"\n  Monthly breakdown:")
print(f"  {'Month':<10} {'HR':>7} {'N':>5} {'W':>4} {'L':>4} {'ROI est':>9}")
print(f"  {'-'*42}")

total_profit = 0
for month in sorted(top3_final['month'].unique()):
    m = top3_final[top3_final['month'] == month]
    hr = m['correct'].mean()
    wins = int(m['correct'].sum())
    losses = len(m) - wins
    # Rough ROI: win +0.91, lose -1.0 (standard -110 odds)
    profit = wins * 0.91 - losses * 1.0
    roi = profit / len(m) * 100
    total_profit += profit
    print(f"  {str(month):<10} {hr:>6.1%} {len(m):>5} {wins:>4} {losses:>4} {roi:>+8.1f}%")

total_roi = total_profit / len(top3_final) * 100
print(f"  {'TOTAL':<10} {top3_final['correct'].mean():>6.1%} {len(top3_final):>5} "
      f"{int(top3_final['correct'].sum()):>4} {int(len(top3_final) - top3_final['correct'].sum()):>4} "
      f"{total_roi:>+8.1f}%")

losing_months = sum(1 for month in top3_final['month'].unique()
                    if top3_final[top3_final['month'] == month]['correct'].mean() < 0.5)
print(f"\n  Losing months: {losing_months}")
print(f"  Total estimated profit: {total_profit:+.1f} units on {len(top3_final)} bets")
print(f"  Estimated ROI: {total_roi:+.1f}%")


# =============================================================================
# 8. COMPARISON: Current config vs Recommended
# =============================================================================
print("\n\n" + "=" * 90)
print("  8. CURRENT vs RECOMMENDED CONFIG COMPARISON")
print("=" * 90)

# Current: current blacklist, KC/MIA/CWS, current venues, edge >= 0.75, pure edge ranking
current_pool = df[df['predicted_over'] == 1].copy()
current_pool = current_pool[current_pool['abs_edge'] <= 2.0]
current_pool = current_pool[~current_pool['pitcher_lookup'].isin(CURRENT_BLACKLIST)]
current_pool = current_pool[~current_pool['opponent_team_abbr'].isin(frozenset(['KC', 'MIA', 'CWS']))]
current_pool = current_pool[~current_pool['venue'].isin(frozenset(['loanDepot park', 'Rate Field', 'Sutter Health Park', 'Busch Stadium']))]
current_pool = current_pool[current_pool['abs_edge'] >= 0.75]

current_top3 = current_pool.sort_values('abs_edge', ascending=False).groupby('game_date').head(3)
recommended_top3 = top3_final  # from section 7

print(f"\n  {'Metric':<30} {'Current':>12} {'Recommended':>12}")
print(f"  {'-'*58}")
print(f"  {'Pool size':<30} {len(current_pool):>12} {len(best_pool):>12}")
print(f"  {'Pool HR':<30} {current_pool['correct'].mean():>11.1%} {best_pool['correct'].mean():>11.1%}")
print(f"  {'Top-3/day N':<30} {len(current_top3):>12} {len(recommended_top3):>12}")
print(f"  {'Top-3/day HR':<30} {current_top3['correct'].mean():>11.1%} {recommended_top3['correct'].mean():>11.1%}")

c_wins = int(current_top3['correct'].sum())
c_losses = len(current_top3) - c_wins
c_profit = c_wins * 0.91 - c_losses * 1.0
c_roi = c_profit / len(current_top3) * 100

r_wins = int(recommended_top3['correct'].sum())
r_losses = len(recommended_top3) - r_wins
r_profit = r_wins * 0.91 - r_losses * 1.0
r_roi = r_profit / len(recommended_top3) * 100

print(f"  {'Est. ROI':<30} {c_roi:>+11.1f}% {r_roi:>+11.1f}%")
print(f"  {'Est. Profit (units)':<30} {c_profit:>+11.1f} {r_profit:>+11.1f}")
print(f"  {'Improvement':>30} {'':<12} {(recommended_top3['correct'].mean()-current_top3['correct'].mean())*100:>+11.1f}pp")

# Significance test
from scipy import stats
current_arr = current_top3['correct'].values
rec_arr = recommended_top3['correct'].values
# Z-test for proportions
p1 = current_arr.mean()
p2 = rec_arr.mean()
n1 = len(current_arr)
n2 = len(rec_arr)
p_pool = (p1*n1 + p2*n2) / (n1 + n2)
se = np.sqrt(p_pool * (1-p_pool) * (1/n1 + 1/n2))
z = (p2 - p1) / se if se > 0 else 0
p_val = 1 - stats.norm.cdf(abs(z))
print(f"\n  Z-test: z={z:.2f}, p={p_val:.3f} (one-sided)")
if p_val < 0.05:
    print(f"  STATISTICALLY SIGNIFICANT at 95% confidence")
elif p_val < 0.10:
    print(f"  Suggestive at 90% confidence (not significant at 95%)")
else:
    print(f"  NOT statistically significant — improvement is within noise")
    print(f"  Need more data or bigger HR gap for significance")


# =============================================================================
# 9. SPECIFIC RECOMMENDATIONS SUMMARY
# =============================================================================
print("\n\n" + "=" * 90)
print("  9. SPECIFIC RECOMMENDATIONS")
print("=" * 90)

print("""
FILTER CHANGES (code updates needed):
======================================

1. PITCHER BLACKLIST — EXPAND from 10 to 21 pitchers:
   REMOVE (now > 45% HR): freddy_peralta, tyler_glasnow, hunter_greene,
                          yusei_kikuchi, paul_skenes, jose_soriano
   KEEP:                  tanner_bibee, mitchell_parker, casey_mize, mitch_keller
   ADD (11 new):          randy_vásquez, zach_eflin, ryne_nelson, josé_berríos,
                          tyler_mahle, jameson_taillon, jake_irvin, ryan_feltner,
                          logan_allen, bradley_blalock, davis_martin, george_kirby,
                          mackenzie_gore, luis_severino, jeffrey_springs,
                          jack_kochanowicz, javier_assad

2. BAD OPPONENTS — MODIFY:
   REMOVE: CWS (50.8% HR — not bad enough)
   KEEP:   KC (42.9%), MIA (46.6%)
   ADD:    AZ (43.8%, but N=16 — OBSERVATION only, promote at N>=25)

3. BAD VENUES — REPLACE:
   REMOVE: Rate Field, Sutter Health Park, Busch Stadium (not in data/above 48%)
   KEEP:   loanDepot park (46.9%)
   ADD:    Guaranteed Rate Field (44.4%), Progressive Field (46.9%),
           Nationals Park (47.3%)

4. EDGE FLOOR: Keep at 0.75 K (sweet spot confirmed)

5. OVERCONFIDENCE CAP: Keep at 2.0 (39.1% HR above 2.0)

SIGNAL CHANGES:
===============

6. HOME PITCHER: Keep as RANKING signal (weight 2.0), NOT a hard filter
   Home: +7pp lift at edge >= 0.75

7. RANKING STRATEGY: Consider hybrid (edge + 0.3 * signal_quality)
   Signals with positive lift for OVER ranking:
   - home_pitcher (+7.0pp)
   - long_rest (+4.7pp)
   - elite_k9 (+3.4pp) (>=10.0 threshold)
   - recent_k_above_line (+2.5pp)

8. PROJECTION AGREES: +4.3pp lift when combined with home.
   As FILTER (block disagrees): +0.6pp individual lift, but blocks ~30% of picks.
   RECOMMENDATION: Use as ranking signal, not filter (too aggressive).

9. UNDER: 59.7% HR at edge [0.5, 0.75) — promising but LOW VOLUME.
   Best subset: low line (<6.5) + cold (avg5 < line) = needs more data.
   KEEP UNDER DISABLED until more walk-forward data validates.

10. INTERACTION EFFECTS:
    - "Triple positive" (edge >= 1.0 + home + proj agrees) = 68.0% HR
    - "Away + low K/9" = 49.8% (block candidate — +0.7pp lift)
    - Use interactions for pick angle building, not hard filters.
""")

print("=" * 90)
print("  ANALYSIS COMPLETE")
print("=" * 90)
