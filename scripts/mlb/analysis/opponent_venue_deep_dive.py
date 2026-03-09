#!/usr/bin/env python3
"""
Deep dive into opponent and venue effects on MLB strikeout prediction quality.
Analyzes interaction effects and structural patterns across walk-forward data.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats
from collections import defaultdict

pd.set_option('display.width', 200)
pd.set_option('display.max_colwidth', 30)
pd.set_option('display.max_rows', 100)
pd.set_option('display.float_format', '{:.3f}'.format)

# ─────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────

BASE = Path(__file__).resolve().parent.parent.parent.parent / "results"

# Load both main datasets
rich = pd.read_csv(BASE / "mlb_walkforward_v4_rich/predictions_catboost_120d_fixed_edge0.5.csv")
reg = pd.read_csv(BASE / "mlb_walkforward_v4_regression/predictions_regression_120d_edge0.50.csv")

# Also load the higher-edge files for the primary analysis
rich_e1 = pd.read_csv(BASE / "mlb_walkforward_v4_rich/predictions_catboost_120d_fixed_edge1.0.csv")
reg_e1 = pd.read_csv(BASE / "mlb_walkforward_v4_regression/predictions_regression_120d_edge1.00.csv")

# Standardize columns
rich['source'] = 'catboost'
rich['edge_val'] = rich['edge'].abs() if 'edge' in rich.columns else 0
reg['source'] = 'regression'
reg['edge_val'] = reg['abs_edge'] if 'abs_edge' in reg.columns else 0

# Combine for maximum data — use the lower-edge files for more volume
# Tag predicted direction
rich['predicted_dir'] = rich['predicted_over'].map({1: 'OVER', 0: 'UNDER'})
reg['predicted_dir'] = reg['predicted_over'].map({1: 'OVER', 0: 'UNDER'})

# Normalize team abbreviations (AZ -> ARI)
TEAM_MAP = {'AZ': 'ARI'}
for df in [rich, reg, rich_e1, reg_e1]:
    df['team_abbr'] = df['team_abbr'].replace(TEAM_MAP)
    df['opponent_team_abbr'] = df['opponent_team_abbr'].replace(TEAM_MAP)

# Combine both model datasets for maximum sample size
combined = pd.concat([rich, reg], ignore_index=True)
combined['game_date'] = pd.to_datetime(combined['game_date'])
combined['month'] = combined['game_date'].dt.month
combined['year'] = combined['game_date'].dt.year
combined['season'] = combined['game_date'].apply(lambda d: d.year if d.month >= 3 else d.year - 1)

print("=" * 100)
print("MLB OPPONENT & VENUE EFFECTS DEEP DIVE")
print("=" * 100)
print(f"\nTotal predictions: {len(combined):,}")
print(f"  CatBoost: {len(rich):,} (HR {rich.correct.mean():.1%})")
print(f"  Regression: {len(reg):,} (HR {reg.correct.mean():.1%})")
print(f"Date range: {combined.game_date.min().date()} to {combined.game_date.max().date()}")
print(f"Unique teams: {combined.team_abbr.nunique()}, Venues: {combined.venue.nunique()}, Pitchers: {combined.pitcher_lookup.nunique()}")


def hr_with_ci(series, z=1.96):
    """Hit rate with 95% confidence interval."""
    n = len(series)
    if n == 0:
        return 0, 0, 0, 0
    hr = series.mean()
    se = np.sqrt(hr * (1 - hr) / n) if n > 1 else 0
    return hr, hr - z * se, hr + z * se, n


def print_section(title):
    print(f"\n{'=' * 100}")
    print(f"  {title}")
    print(f"{'=' * 100}")


# ─────────────────────────────────────────────────────
# 1. OPPONENT K-RATE TIERS
# ─────────────────────────────────────────────────────
print_section("1. OPPONENT K-RATE TIERS — Do high-K teams predict better for OVER?")

# Compute each team's actual K rate as opponent (how often their batters strike out)
# actual_strikeouts is the number the PITCHER got, so when team X is the opponent,
# the pitcher struck out X's batters
opp_k_stats = combined.groupby('opponent_team_abbr').agg(
    total_ks_against=('actual_strikeouts', 'sum'),
    n_games_as_opponent=('actual_strikeouts', 'count'),
    avg_ks_against=('actual_strikeouts', 'mean'),
    median_ks_against=('actual_strikeouts', 'median'),
).reset_index()
opp_k_stats = opp_k_stats.sort_values('avg_ks_against', ascending=False)

print("\nTeam K susceptibility (avg Ks allowed per game as opponent):")
print(opp_k_stats.to_string(index=False))

# Tier assignment: top 10 = high-K, bottom 10 = low-K
n_teams = len(opp_k_stats)
tier_size = 10
opp_k_stats_sorted = opp_k_stats.sort_values('avg_ks_against', ascending=False).reset_index(drop=True)
high_k_teams = set(opp_k_stats_sorted.head(tier_size)['opponent_team_abbr'])
low_k_teams = set(opp_k_stats_sorted.tail(tier_size)['opponent_team_abbr'])
mid_k_teams = set(opp_k_stats_sorted['opponent_team_abbr']) - high_k_teams - low_k_teams

combined['opp_k_tier'] = combined['opponent_team_abbr'].apply(
    lambda t: 'HIGH-K (top 10)' if t in high_k_teams
    else ('LOW-K (bot 10)' if t in low_k_teams else 'MID-K')
)

print(f"\nHigh-K teams (strike out a lot): {sorted(high_k_teams)}")
print(f"Low-K teams (make contact):      {sorted(low_k_teams)}")

# HR by tier
print("\n--- HR by Opponent K-Rate Tier ---")
for tier in ['HIGH-K (top 10)', 'MID-K', 'LOW-K (bot 10)']:
    subset = combined[combined.opp_k_tier == tier]
    hr, lo, hi, n = hr_with_ci(subset.correct)
    over_sub = subset[subset.predicted_dir == 'OVER']
    under_sub = subset[subset.predicted_dir == 'UNDER']
    over_hr = over_sub.correct.mean() if len(over_sub) > 0 else 0
    under_hr = under_sub.correct.mean() if len(under_sub) > 0 else 0
    print(f"  {tier:20s}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n:,}  |  OVER HR {over_hr:.1%} (N={len(over_sub):,})  |  UNDER HR {under_hr:.1%} (N={len(under_sub):,})")

# HR by opponent team
print("\n--- HR by Opponent Team (sorted by HR, N >= 30) ---")
opp_hr = combined.groupby('opponent_team_abbr').agg(
    hr=('correct', 'mean'),
    n=('correct', 'count'),
    over_hr=('correct', lambda x: x[combined.loc[x.index, 'predicted_dir'] == 'OVER'].mean() if len(x[combined.loc[x.index, 'predicted_dir'] == 'OVER']) > 0 else np.nan),
    avg_k=('actual_strikeouts', 'mean'),
).reset_index()
opp_hr = opp_hr[opp_hr.n >= 30].sort_values('hr', ascending=True)
print(f"{'Team':>6s} {'HR':>8s} {'N':>6s} {'Avg K':>7s}")
for _, row in opp_hr.iterrows():
    flag = " *** FILTER CANDIDATE" if row.hr < 0.48 else (" +++ STRONG" if row.hr > 0.60 else "")
    print(f"  {row.opponent_team_abbr:>4s}  {row.hr:7.1%}  {int(row.n):5d}  {row.avg_k:6.2f}{flag}")


# ─────────────────────────────────────────────────────
# 2. VENUE + TEAM INTERACTION
# ─────────────────────────────────────────────────────
print_section("2. VENUE + TEAM INTERACTION — Disentangling park from opponent")

# Venue-level HR
venue_hr = combined.groupby('venue').agg(
    hr=('correct', 'mean'),
    n=('correct', 'count'),
    avg_k=('actual_strikeouts', 'mean'),
    n_unique_opponents=('opponent_team_abbr', 'nunique'),
).reset_index()
venue_hr = venue_hr[venue_hr.n >= 30].sort_values('hr')

print("\n--- Venue HR (N >= 30, sorted worst to best) ---")
print(f"{'Venue':>30s} {'HR':>8s} {'N':>6s} {'Avg K':>7s} {'Unique Opps':>12s}")
for _, row in venue_hr.iterrows():
    flag = " *** FILTER" if row.hr < 0.48 else (" +++ STRONG" if row.hr > 0.60 else "")
    print(f"  {row.venue:>28s}  {row.hr:7.1%}  {int(row.n):5d}  {row.avg_k:6.2f}  {int(row.n_unique_opponents):>10d}{flag}")

# For venues with enough data, compare HR when facing different opponents
# This disentangles venue vs opponent
print("\n--- Venue Effect: Same Venue, Different Opponents ---")
# Get venues with games against many different opponents
for venue in venue_hr[venue_hr.n >= 80].sort_values('hr').venue:
    v_data = combined[combined.venue == venue]
    # Home team at this venue
    home_team = v_data[v_data.is_home == 1]['team_abbr'].mode()
    home_team_str = home_team.iloc[0] if len(home_team) > 0 else "?"

    # HR by opponent at this venue
    v_opp = v_data.groupby('opponent_team_abbr').agg(hr=('correct', 'mean'), n=('correct', 'count')).reset_index()
    v_opp = v_opp[v_opp.n >= 5]
    if len(v_opp) >= 3:
        hr_std = v_opp.hr.std()
        hr_range = v_opp.hr.max() - v_opp.hr.min()
        overall_hr = v_data.correct.mean()
        print(f"  {venue:28s} (home={home_team_str}): Overall HR {overall_hr:.1%} N={len(v_data):,} | "
              f"Opp HR range: {v_opp.hr.min():.1%}-{v_opp.hr.max():.1%} (spread={hr_range:.1%}, std={hr_std:.1%})")

# Team effect: same team, home vs away
print("\n--- Team Effect: Same Team, Home vs Away ---")
team_ha = combined.groupby(['team_abbr', 'is_home']).agg(
    hr=('correct', 'mean'),
    n=('correct', 'count'),
).reset_index()
team_ha_pivot = team_ha.pivot(index='team_abbr', columns='is_home', values=['hr', 'n']).reset_index()
team_ha_pivot.columns = ['team', 'away_hr', 'home_hr', 'away_n', 'home_n']
team_ha_pivot['delta'] = team_ha_pivot['home_hr'] - team_ha_pivot['away_hr']
team_ha_pivot = team_ha_pivot[(team_ha_pivot.away_n >= 20) & (team_ha_pivot.home_n >= 20)]
team_ha_pivot = team_ha_pivot.sort_values('delta')

print(f"{'Team':>6s} {'Home HR':>9s} {'Home N':>8s} {'Away HR':>9s} {'Away N':>8s} {'Delta':>8s}")
for _, row in team_ha_pivot.iterrows():
    flag = " ***" if abs(row.delta) > 0.10 else ""
    print(f"  {row.team:>4s}  {row.home_hr:8.1%}  {int(row.home_n):6d}  {row.away_hr:8.1%}  {int(row.away_n):6d}  {row.delta:+7.1%}{flag}")

# Variance decomposition: how much of HR variance is venue vs opponent?
print("\n--- Variance Attribution ---")
# Simple approach: compare R^2 of opponent dummy vs venue dummy
from sklearn.preprocessing import LabelEncoder
le_opp = LabelEncoder()
le_venue = LabelEncoder()
combined['opp_encoded'] = le_opp.fit_transform(combined['opponent_team_abbr'])
combined['venue_encoded'] = le_venue.fit_transform(combined['venue'])

# Point-biserial correlation (proxied by one-way ANOVA eta-squared)
# Opponent effect
opp_groups = [g.correct.values for _, g in combined.groupby('opponent_team_abbr')]
f_opp, p_opp = stats.f_oneway(*[g for g in opp_groups if len(g) >= 5])
ss_between_opp = sum(len(g) * (np.mean(g) - combined.correct.mean())**2 for g in opp_groups if len(g) >= 5)
ss_total = len(combined) * combined.correct.var()
eta2_opp = ss_between_opp / ss_total if ss_total > 0 else 0

# Venue effect
venue_groups = [g.correct.values for _, g in combined.groupby('venue')]
f_venue, p_venue = stats.f_oneway(*[g for g in venue_groups if len(g) >= 5])
ss_between_venue = sum(len(g) * (np.mean(g) - combined.correct.mean())**2 for g in venue_groups if len(g) >= 5)
eta2_venue = ss_between_venue / ss_total if ss_total > 0 else 0

print(f"  Opponent effect: eta^2 = {eta2_opp:.4f} (F={f_opp:.2f}, p={p_opp:.4f})")
print(f"  Venue effect:    eta^2 = {eta2_venue:.4f} (F={f_venue:.2f}, p={p_venue:.4f})")
if eta2_opp > eta2_venue:
    print(f"  >>> OPPONENT explains {eta2_opp/eta2_venue:.1f}x more variance than VENUE")
else:
    print(f"  >>> VENUE explains {eta2_venue/eta2_opp:.1f}x more variance than OPPONENT")


# ─────────────────────────────────────────────────────
# 3. DIVISION EFFECTS
# ─────────────────────────────────────────────────────
print_section("3. DIVISION EFFECTS — NL vs AL, inter-league, division breakdown")

DIVISIONS = {
    'AL East': ['NYY', 'BOS', 'TB', 'TOR', 'BAL'],
    'AL Central': ['CLE', 'MIN', 'CWS', 'DET', 'KC'],
    'AL West': ['HOU', 'SEA', 'TEX', 'LAA', 'OAK'],
    'NL East': ['ATL', 'NYM', 'PHI', 'MIA', 'WSH'],
    'NL Central': ['MIL', 'STL', 'CHC', 'CIN', 'PIT'],
    'NL West': ['LAD', 'SD', 'SF', 'ARI', 'COL'],
}

TEAM_TO_DIV = {}
TEAM_TO_LEAGUE = {}
for div, teams in DIVISIONS.items():
    league = div[:2]
    for t in teams:
        TEAM_TO_DIV[t] = div
        TEAM_TO_LEAGUE[t] = league

combined['pitcher_div'] = combined['team_abbr'].map(TEAM_TO_DIV)
combined['opp_div'] = combined['opponent_team_abbr'].map(TEAM_TO_DIV)
combined['pitcher_league'] = combined['team_abbr'].map(TEAM_TO_LEAGUE)
combined['opp_league'] = combined['opponent_team_abbr'].map(TEAM_TO_LEAGUE)
combined['interleague'] = combined['pitcher_league'] != combined['opp_league']

# NL vs AL
print("\n--- League Matchups ---")
for label, mask in [
    ("AL pitcher vs AL batter", (combined.pitcher_league == 'AL') & (combined.opp_league == 'AL')),
    ("NL pitcher vs NL batter", (combined.pitcher_league == 'NL') & (combined.opp_league == 'NL')),
    ("Interleague (all)", combined.interleague),
    ("AL pitcher vs NL batter", (combined.pitcher_league == 'AL') & (combined.opp_league == 'NL')),
    ("NL pitcher vs AL batter", (combined.pitcher_league == 'NL') & (combined.opp_league == 'AL')),
]:
    sub = combined[mask]
    hr, lo, hi, n = hr_with_ci(sub.correct)
    print(f"  {label:30s}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n:,}")

# Opponent division
print("\n--- HR by Opponent Division ---")
opp_div_hr = combined.groupby('opp_div').agg(
    hr=('correct', 'mean'), n=('correct', 'count'),
    avg_k=('actual_strikeouts', 'mean'),
).reset_index().sort_values('hr')
for _, row in opp_div_hr.iterrows():
    hr, lo, hi, n = hr_with_ci(combined[combined.opp_div == row.opp_div].correct)
    print(f"  {row.opp_div:>14s}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n:,} | Avg K={row.avg_k:.2f}")

# Pitcher division
print("\n--- HR by Pitcher Division ---")
pit_div_hr = combined.groupby('pitcher_div').agg(
    hr=('correct', 'mean'), n=('correct', 'count'),
).reset_index().sort_values('hr')
for _, row in pit_div_hr.iterrows():
    hr, lo, hi, n = hr_with_ci(combined[combined.pitcher_div == row.pitcher_div].correct)
    print(f"  {row.pitcher_div:>14s}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n:,}")


# ─────────────────────────────────────────────────────
# 4. OPPONENT STABILITY ACROSS SEASONS
# ─────────────────────────────────────────────────────
print_section("4. OPPONENT STABILITY — Do bad opponents stay bad?")

# Get per-season opponent HR
season_opp = combined.groupby(['season', 'opponent_team_abbr']).agg(
    hr=('correct', 'mean'),
    n=('correct', 'count'),
    avg_k=('actual_strikeouts', 'mean'),
).reset_index()

seasons = sorted(season_opp.season.unique())
print(f"\nSeasons in data: {seasons}")

if len(seasons) >= 2:
    s1, s2 = seasons[0], seasons[1]
    s1_data = season_opp[season_opp.season == s1][['opponent_team_abbr', 'hr', 'n', 'avg_k']].rename(
        columns={'hr': f'hr_{s1}', 'n': f'n_{s1}', 'avg_k': f'k_{s1}'})
    s2_data = season_opp[season_opp.season == s2][['opponent_team_abbr', 'hr', 'n', 'avg_k']].rename(
        columns={'hr': f'hr_{s2}', 'n': f'n_{s2}', 'avg_k': f'k_{s2}'})

    cross = pd.merge(s1_data, s2_data, on='opponent_team_abbr', how='inner')
    cross = cross[(cross[f'n_{s1}'] >= 20) & (cross[f'n_{s2}'] >= 20)]

    # Correlation of HR across seasons
    r_hr, p_hr = stats.pearsonr(cross[f'hr_{s1}'], cross[f'hr_{s2}'])
    r_k, p_k = stats.pearsonr(cross[f'k_{s1}'], cross[f'k_{s2}'])

    print(f"\n--- Cross-Season Correlation (N={len(cross)} teams) ---")
    print(f"  HR correlation {s1} vs {s2}:   r = {r_hr:.3f} (p = {p_hr:.4f})")
    print(f"  Avg K correlation {s1} vs {s2}: r = {r_k:.3f} (p = {p_k:.4f})")

    if r_hr < 0.3:
        print(f"  >>> HR across seasons is NOT STABLE (r={r_hr:.3f}) — opponent HR is not persistent")
    elif r_hr > 0.5:
        print(f"  >>> HR across seasons IS STABLE (r={r_hr:.3f}) — opponent identity matters")
    else:
        print(f"  >>> MODERATE stability (r={r_hr:.3f}) — some signal but noisy")

    if r_k > 0.5:
        print(f"  >>> K-rate IS STABLE across seasons (r={r_k:.3f}) — teams that K a lot keep K-ing")

    print(f"\n--- Team Comparison {s1} vs {s2} ---")
    cross = cross.sort_values(f'hr_{s1}')
    print(f"{'Team':>6s} {f'HR {s1}':>8s} {f'N {s1}':>6s} {f'HR {s2}':>8s} {f'N {s2}':>6s} {'Delta':>8s} {f'K {s1}':>6s} {f'K {s2}':>6s}")
    for _, row in cross.iterrows():
        delta = row[f'hr_{s2}'] - row[f'hr_{s1}']
        flip = " FLIPPED" if abs(delta) > 0.15 else ""
        print(f"  {row.opponent_team_abbr:>4s}  {row[f'hr_{s1}']:7.1%}  {int(row[f'n_{s1}']):5d}  "
              f"{row[f'hr_{s2}']:7.1%}  {int(row[f'n_{s2}']):5d}  {delta:+7.1%}  "
              f"{row[f'k_{s1}']:5.2f}  {row[f'k_{s2}']:5.2f}{flip}")


# ─────────────────────────────────────────────────────
# 5. PITCHER-OPPONENT SPECIFIC PATTERNS
# ─────────────────────────────────────────────────────
print_section("5. PITCHER-OPPONENT PATTERNS — Does familiarity help pitcher or batter?")

# Find pitcher-opponent pairs with 3+ matchups
pitcher_opp = combined.groupby(['pitcher_lookup', 'opponent_team_abbr']).agg(
    hr=('correct', 'mean'),
    n=('correct', 'count'),
    avg_k=('actual_strikeouts', 'mean'),
    avg_line=('strikeouts_line', 'mean'),
    over_rate=('actual_over', 'mean'),
    pitcher_name=('pitcher_name', 'first'),
).reset_index()

print(f"\nTotal pitcher-opponent pairs: {len(pitcher_opp):,}")
for min_n in [3, 4, 5, 6]:
    subset = pitcher_opp[pitcher_opp.n >= min_n]
    print(f"  Pairs with N >= {min_n}: {len(subset):,}, "
          f"avg HR: {subset.hr.mean():.1%}, "
          f"total picks: {subset.n.sum():,}")

# Focus on pairs with 3+ starts
freq_pairs = pitcher_opp[pitcher_opp.n >= 3].copy()
print(f"\n--- Familiarity Effect (N >= 3 matchups) ---")
print(f"Pairs: {len(freq_pairs):,}")

# For each pair, look at how performance evolves with more matchups
# We need the raw data ordered by date for this
familiar_data = combined.merge(
    freq_pairs[['pitcher_lookup', 'opponent_team_abbr']],
    on=['pitcher_lookup', 'opponent_team_abbr'],
    how='inner'
)
familiar_data = familiar_data.sort_values(['pitcher_lookup', 'opponent_team_abbr', 'game_date'])

# Add matchup number within each pair
familiar_data['matchup_num'] = familiar_data.groupby(['pitcher_lookup', 'opponent_team_abbr']).cumcount() + 1

print("\n--- HR by Matchup Number (Nth time facing same opponent) ---")
for mn in sorted(familiar_data.matchup_num.unique()):
    if mn <= 8:
        sub = familiar_data[familiar_data.matchup_num == mn]
        hr, lo, hi, n = hr_with_ci(sub.correct)
        over_rate = sub.actual_over.mean()
        print(f"  Matchup #{mn}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n:,} | Actual over rate: {over_rate:.1%}")

# Trend: first 2 vs 3+
early = familiar_data[familiar_data.matchup_num <= 2]
late = familiar_data[familiar_data.matchup_num >= 3]
hr_early = early.correct.mean()
hr_late = late.correct.mean()
# Statistical test
stat, p_val = stats.chi2_contingency(pd.crosstab(
    familiar_data.matchup_num <= 2, familiar_data.correct
))[:2]
print(f"\n  First 1-2 matchups: HR {hr_early:.1%} (N={len(early):,})")
print(f"  3rd+ matchups:     HR {hr_late:.1%} (N={len(late):,})")
print(f"  Chi-squared p-value: {p_val:.4f}")
if hr_late > hr_early:
    print("  >>> Familiarity HELPS the pitcher (more K predictability)")
elif hr_late < hr_early:
    print("  >>> Familiarity HELPS the batter (harder to predict Ks)")
else:
    print("  >>> No clear familiarity effect")

# Extreme consistent pairs
print("\n--- Most Consistent Pitcher-Opponent Pairs (N >= 4) ---")
strong_pairs = freq_pairs[freq_pairs.n >= 4].copy()
strong_pairs = strong_pairs.sort_values('hr', ascending=False)

print("\n  TOP 15 (always correct):")
print(f"  {'Pitcher':>25s} {'Opp':>5s} {'HR':>8s} {'N':>4s} {'Avg K':>7s} {'Line':>6s} {'Over%':>7s}")
for _, row in strong_pairs.head(15).iterrows():
    print(f"  {row.pitcher_name:>25s} {row.opponent_team_abbr:>5s} {row.hr:7.1%} {int(row.n):4d} "
          f"{row.avg_k:6.2f} {row.avg_line:5.1f} {row.over_rate:6.1%}")

print("\n  BOTTOM 15 (always wrong):")
for _, row in strong_pairs.tail(15).iterrows():
    print(f"  {row.pitcher_name:>25s} {row.opponent_team_abbr:>5s} {row.hr:7.1%} {int(row.n):4d} "
          f"{row.avg_k:6.2f} {row.avg_line:5.1f} {row.over_rate:6.1%}")


# ─────────────────────────────────────────────────────
# 6. VENUE-MONTH WEATHER PROXY
# ─────────────────────────────────────────────────────
print_section("6. VENUE-MONTH WEATHER PROXY — Open-air vs dome, altitude, seasonality")

# Known dome/retractable venues
DOME_VENUES = {
    'Tropicana Field', 'Globe Life Field', 'loanDepot park',  # Fixed roof
    'Chase Field',  # Retractable
    'Minute Maid Park',  # Retractable
    'Rogers Centre',  # Retractable
    'T-Mobile Park',  # Retractable
    'American Family Field',  # Retractable
    'Daikin Park',  # Retractable (was Minute Maid)
}

# High altitude
HIGH_ALT_VENUES = {'Coors Field'}

combined['venue_type'] = combined['venue'].apply(
    lambda v: 'HIGH_ALT' if v in HIGH_ALT_VENUES
    else ('DOME' if v in DOME_VENUES else 'OPEN_AIR')
)

print("\n--- HR by Venue Type ---")
for vt in ['OPEN_AIR', 'DOME', 'HIGH_ALT']:
    sub = combined[combined.venue_type == vt]
    if len(sub) > 0:
        hr, lo, hi, n = hr_with_ci(sub.correct)
        avg_k = sub.actual_strikeouts.mean()
        print(f"  {vt:12s}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n:,} | Avg K: {avg_k:.2f}")

# Open-air venues by month
print("\n--- Open-Air Venues: HR by Month ---")
open_air = combined[combined.venue_type == 'OPEN_AIR']
for month in sorted(open_air.month.unique()):
    sub = open_air[open_air.month == month]
    hr, lo, hi, n = hr_with_ci(sub.correct)
    avg_k = sub.actual_strikeouts.mean()
    month_name = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'][month]
    print(f"  {month_name:>5s}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n:,} | Avg K: {avg_k:.2f}")

# Dome venues by month (should be consistent)
print("\n--- Dome Venues: HR by Month (should be flat) ---")
dome = combined[combined.venue_type == 'DOME']
for month in sorted(dome.month.unique()):
    sub = dome[dome.month == month]
    hr, lo, hi, n = hr_with_ci(sub.correct)
    avg_k = sub.actual_strikeouts.mean()
    month_name = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'][month]
    print(f"  {month_name:>5s}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n:,} | Avg K: {avg_k:.2f}")

# Dome vs open-air consistency test
dome_month_hrs = []
open_month_hrs = []
for month in sorted(combined.month.unique()):
    d_sub = dome[dome.month == month]
    o_sub = open_air[open_air.month == month]
    if len(d_sub) >= 20:
        dome_month_hrs.append(d_sub.correct.mean())
    if len(o_sub) >= 20:
        open_month_hrs.append(o_sub.correct.mean())
if len(dome_month_hrs) >= 3 and len(open_month_hrs) >= 3:
    print(f"\n  Dome monthly HR std:     {np.std(dome_month_hrs):.3f}")
    print(f"  Open-air monthly HR std: {np.std(open_month_hrs):.3f}")
    if np.std(dome_month_hrs) < np.std(open_month_hrs):
        print("  >>> Dome venues ARE more consistent (as expected)")
    else:
        print("  >>> Surprisingly, dome venues are NOT more consistent")

# Coors Field special analysis
print("\n--- Coors Field (altitude effect) ---")
coors = combined[combined.venue == 'Coors Field']
non_coors = combined[combined.venue != 'Coors Field']
if len(coors) > 0:
    hr_c, lo_c, hi_c, n_c = hr_with_ci(coors.correct)
    hr_nc, lo_nc, hi_nc, n_nc = hr_with_ci(non_coors.correct)
    avg_k_c = coors.actual_strikeouts.mean()
    avg_k_nc = non_coors.actual_strikeouts.mean()
    print(f"  Coors:     HR {hr_c:.1%} [{lo_c:.1%}-{hi_c:.1%}] N={n_c} | Avg K: {avg_k_c:.2f}")
    print(f"  Non-Coors: HR {hr_nc:.1%} [{lo_nc:.1%}-{hi_nc:.1%}] N={n_nc:,} | Avg K: {avg_k_nc:.2f}")
    # Over/under at Coors
    coors_over = coors[coors.predicted_dir == 'OVER']
    coors_under = coors[coors.predicted_dir == 'UNDER']
    if len(coors_over) > 0:
        print(f"  Coors OVER:  HR {coors_over.correct.mean():.1%} (N={len(coors_over)})")
    if len(coors_under) > 0:
        print(f"  Coors UNDER: HR {coors_under.correct.mean():.1%} (N={len(coors_under)})")

# Day vs Night at open-air venues
print("\n--- Day vs Night Game at Open-Air Venues ---")
for label, mask in [("Day game", open_air.is_day_game == 1), ("Night game", open_air.is_day_game == 0)]:
    sub = open_air[mask]
    hr, lo, hi, n = hr_with_ci(sub.correct)
    avg_k = sub.actual_strikeouts.mean()
    print(f"  {label:12s}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n:,} | Avg K: {avg_k:.2f}")


# ─────────────────────────────────────────────────────
# 7. TRAVEL EFFECTS
# ─────────────────────────────────────────────────────
print_section("7. TRAVEL EFFECTS — Cross-timezone, road trips")

# Timezone mapping (approximate)
TEAM_TZ = {
    # Eastern
    'NYY': 'ET', 'NYM': 'ET', 'BOS': 'ET', 'BAL': 'ET', 'PHI': 'ET',
    'WSH': 'ET', 'MIA': 'ET', 'TB': 'ET', 'ATL': 'ET', 'PIT': 'ET',
    'CIN': 'ET', 'CLE': 'ET', 'DET': 'ET', 'TOR': 'ET',
    # Central
    'CHC': 'CT', 'CWS': 'CT', 'MIL': 'CT', 'STL': 'CT', 'MIN': 'CT',
    'KC': 'CT', 'HOU': 'CT', 'TEX': 'CT',
    # Mountain
    'ARI': 'MT', 'COL': 'MT',
    # Pacific
    'LAD': 'PT', 'LAA': 'PT', 'SD': 'PT', 'SF': 'PT', 'SEA': 'PT', 'OAK': 'PT',
}

TZ_ORDER = {'ET': 0, 'CT': 1, 'MT': 2, 'PT': 3}

combined['pitcher_tz'] = combined['team_abbr'].map(TEAM_TZ)
combined['venue_tz'] = None  # Determine from is_home and opponent

# If pitcher is away, the venue timezone is the opponent's timezone
# If pitcher is home, the venue timezone is the pitcher's timezone
combined['venue_tz'] = np.where(
    combined['is_home'] == 1,
    combined['team_abbr'].map(TEAM_TZ),
    combined['opponent_team_abbr'].map(TEAM_TZ)
)

combined['tz_diff'] = combined.apply(
    lambda row: abs(TZ_ORDER.get(row['pitcher_tz'], 0) - TZ_ORDER.get(row['venue_tz'], 0))
    if pd.notna(row['pitcher_tz']) and pd.notna(row['venue_tz']) else 0,
    axis=1
)

# For away pitchers only
away = combined[combined.is_home == 0].copy()

print("\n--- Away Pitcher: HR by Timezone Difference ---")
for tz_d in sorted(away.tz_diff.unique()):
    sub = away[away.tz_diff == tz_d]
    hr, lo, hi, n = hr_with_ci(sub.correct)
    tz_label = {0: 'Same TZ', 1: '1 zone', 2: '2 zones', 3: '3 zones (coast-to-coast)'}.get(tz_d, f'{tz_d} zones')
    print(f"  {tz_label:30s}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n:,}")

# Directional travel (west-to-east vs east-to-west)
combined['travel_dir'] = combined.apply(
    lambda row: 'W→E' if TZ_ORDER.get(row['pitcher_tz'], 0) > TZ_ORDER.get(row['venue_tz'], 0)
    else ('E→W' if TZ_ORDER.get(row['pitcher_tz'], 0) < TZ_ORDER.get(row['venue_tz'], 0)
    else 'SAME')
    if row['is_home'] == 0 else 'HOME',
    axis=1
)

print("\n--- Travel Direction (away pitchers only) ---")
for direction in ['SAME', 'E→W', 'W→E']:
    sub = combined[combined.travel_dir == direction]
    hr, lo, hi, n = hr_with_ci(sub.correct)
    print(f"  {direction:8s}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n:,}")

# Consecutive away games proxy: sort by pitcher and date, count consecutive away
print("\n--- Road Trip Length Effect ---")
# Group consecutive away starts for each pitcher
combined_sorted = combined.sort_values(['pitcher_lookup', 'game_date'])
combined_sorted['prev_home'] = combined_sorted.groupby('pitcher_lookup')['is_home'].shift(1)
combined_sorted['away_streak'] = 0

# Simple approach: count consecutive away games
for pitcher in combined_sorted.pitcher_lookup.unique():
    mask = combined_sorted.pitcher_lookup == pitcher
    pitcher_data = combined_sorted[mask].copy()
    streak = 0
    streaks = []
    for _, row in pitcher_data.iterrows():
        if row.is_home == 0:
            streak += 1
        else:
            streak = 0
        streaks.append(streak)
    combined_sorted.loc[mask, 'away_streak'] = streaks

away_streak_data = combined_sorted[combined_sorted.is_home == 0]
for streak_len in [1, 2, 3]:
    if streak_len < 3:
        sub = away_streak_data[away_streak_data.away_streak == streak_len]
        label = f"Away start #{streak_len}"
    else:
        sub = away_streak_data[away_streak_data.away_streak >= streak_len]
        label = f"Away start #{streak_len}+"
    hr, lo, hi, n = hr_with_ci(sub.correct)
    print(f"  {label:20s}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n:,}")


# ─────────────────────────────────────────────────────
# 8. OPPONENT DIFFICULTY SCORE
# ─────────────────────────────────────────────────────
print_section("8. OPPONENT DIFFICULTY SCORE — Composite signal")

# Build a composite score from:
# 1. Team K rate (normalized) — higher K rate = easier opponent for OVER
# 2. Historical HR when facing this opponent (normalized)
# 3. Venue effect of their home park

# First, compute per-team metrics
team_metrics = combined.groupby('opponent_team_abbr').agg(
    hr=('correct', 'mean'),
    n=('correct', 'count'),
    avg_k=('actual_strikeouts', 'mean'),
    over_hr=('correct', lambda x: x[combined.loc[x.index, 'predicted_dir'] == 'OVER'].mean() if len(x[combined.loc[x.index, 'predicted_dir'] == 'OVER']) > 0 else 0.5),
).reset_index()

# Venue HR for home parks
home_venue_map = combined[combined.is_home == 1].groupby('team_abbr')['venue'].agg(lambda x: x.mode().iloc[0] if len(x) > 0 else None).to_dict()
venue_hr_map = combined.groupby('venue')['correct'].mean().to_dict()

team_metrics['home_venue'] = team_metrics['opponent_team_abbr'].map(home_venue_map)
team_metrics['venue_hr'] = team_metrics['home_venue'].map(venue_hr_map)

# Normalize each component to 0-1 (higher = harder opponent = lower HR)
for col in ['hr', 'avg_k', 'venue_hr']:
    if col in team_metrics.columns:
        vals = team_metrics[col].dropna()
        team_metrics[f'{col}_norm'] = (team_metrics[col] - vals.min()) / (vals.max() - vals.min())

# Difficulty score: LOWER is harder (inverted HR + low K + bad venue)
# Actually, let's make HIGHER = MORE DIFFICULT = WORSE for predictions
team_metrics['difficulty_score'] = (
    (1 - team_metrics['hr_norm']) * 0.50 +  # Low HR = difficult
    (1 - team_metrics['avg_k_norm']) * 0.30 +  # Low K rate = difficult (contact team)
    (1 - team_metrics['venue_hr_norm'].fillna(0.5)) * 0.20  # Bad venue = difficult
)

team_metrics = team_metrics.sort_values('difficulty_score', ascending=False)

print("\n--- Opponent Difficulty Ranking (higher = harder to predict against) ---")
print(f"{'Team':>6s} {'Diff Score':>11s} {'HR':>8s} {'N':>6s} {'Avg K':>7s} {'Venue HR':>9s}")
for _, row in team_metrics.iterrows():
    venue_hr_str = f"{row.venue_hr:.1%}" if pd.notna(row.venue_hr) else "N/A"
    flag = " *** HARD" if row.difficulty_score > 0.65 else (" +++ EASY" if row.difficulty_score < 0.35 else "")
    print(f"  {row.opponent_team_abbr:>4s}  {row.difficulty_score:10.3f}  {row.hr:7.1%}  {int(row.n):5d}  {row.avg_k:6.2f}  {venue_hr_str:>8s}{flag}")

# Test: does difficulty score predict future HR?
# Split data in half by time
print("\n--- Predictive Power Test: First Half → Second Half ---")
mid_date = combined.game_date.median()
first_half = combined[combined.game_date <= mid_date]
second_half = combined[combined.game_date > mid_date]

# Build score on first half
fh_metrics = first_half.groupby('opponent_team_abbr').agg(
    hr_fh=('correct', 'mean'),
    n_fh=('correct', 'count'),
    avg_k_fh=('actual_strikeouts', 'mean'),
).reset_index()

sh_metrics = second_half.groupby('opponent_team_abbr').agg(
    hr_sh=('correct', 'mean'),
    n_sh=('correct', 'count'),
).reset_index()

pred_test = pd.merge(fh_metrics, sh_metrics, on='opponent_team_abbr', how='inner')
pred_test = pred_test[(pred_test.n_fh >= 30) & (pred_test.n_sh >= 30)]

if len(pred_test) >= 10:
    r_pred, p_pred = stats.pearsonr(pred_test.hr_fh, pred_test.hr_sh)
    r_k_pred, p_k_pred = stats.pearsonr(pred_test.avg_k_fh, pred_test.hr_sh)
    print(f"  First-half HR → Second-half HR: r = {r_pred:.3f} (p = {p_pred:.4f}) N={len(pred_test)} teams")
    print(f"  First-half K rate → Second-half HR: r = {r_k_pred:.3f} (p = {p_k_pred:.4f})")

    if r_pred > 0.3 and p_pred < 0.10:
        print("  >>> Difficulty score HAS predictive power — use as ranking signal")
    elif r_pred > 0.2:
        print("  >>> WEAK predictive signal — consider as tiebreaker, not primary")
    else:
        print("  >>> No predictive power — opponent difficulty is NOT stable enough for a signal")
else:
    print(f"  Not enough teams with N >= 30 in both halves (have {len(pred_test)})")

# Quintile test: top difficulty quintile vs bottom
team_metrics['diff_quintile'] = pd.qcut(team_metrics.difficulty_score, 5, labels=['Q1_Easy', 'Q2', 'Q3', 'Q4', 'Q5_Hard'])
diff_map = team_metrics.set_index('opponent_team_abbr')['diff_quintile'].to_dict()
combined['opp_difficulty_q'] = combined['opponent_team_abbr'].map(diff_map)

print("\n--- HR by Opponent Difficulty Quintile ---")
for q in ['Q1_Easy', 'Q2', 'Q3', 'Q4', 'Q5_Hard']:
    sub = combined[combined.opp_difficulty_q == q]
    hr, lo, hi, n = hr_with_ci(sub.correct)
    over_sub = sub[sub.predicted_dir == 'OVER']
    under_sub = sub[sub.predicted_dir == 'UNDER']
    over_hr = over_sub.correct.mean() if len(over_sub) > 0 else 0
    under_hr = under_sub.correct.mean() if len(under_sub) > 0 else 0
    print(f"  {q:10s}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n:,}  |  OVER {over_hr:.1%} (N={len(over_sub):,})  |  UNDER {under_hr:.1%} (N={len(under_sub):,})")


# ─────────────────────────────────────────────────────
# FINAL RECOMMENDATIONS
# ─────────────────────────────────────────────────────
print_section("FINAL RECOMMENDATIONS")

# Collect all findings
print("\n--- Hard Filter Candidates (persistent low HR) ---")
# Teams with HR < 48% and N >= 50
bad_opps = team_metrics[(team_metrics.hr < 0.48) & (team_metrics.n >= 50)]
if len(bad_opps) > 0:
    for _, row in bad_opps.iterrows():
        print(f"  vs {row.opponent_team_abbr}: HR {row.hr:.1%} (N={int(row.n)}) — FILTER CANDIDATE")
else:
    print("  No teams with HR < 48% at N >= 50")

# Venues with HR < 48% and N >= 50
bad_venues_list = venue_hr[(venue_hr.hr < 0.48) & (venue_hr.n >= 50)]
if len(bad_venues_list) > 0:
    for _, row in bad_venues_list.iterrows():
        print(f"  {row.venue}: HR {row.hr:.1%} (N={int(row.n)}) — FILTER CANDIDATE")
else:
    print("  No venues with HR < 48% at N >= 50")

print("\n--- Ranking Signal Candidates (modulate edge, not hard filter) ---")
recommendations = []

# Check if K-rate tiers matter
high_k_hr = combined[combined.opp_k_tier == 'HIGH-K (top 10)'].correct.mean()
low_k_hr = combined[combined.opp_k_tier == 'LOW-K (bot 10)'].correct.mean()
k_gap = high_k_hr - low_k_hr
if abs(k_gap) > 0.03:
    direction = "HIGH-K opponents are easier" if k_gap > 0 else "LOW-K opponents are easier"
    recommendations.append(f"  K-rate tier gap: {k_gap:+.1%} ({direction}) — RANKING SIGNAL")
    print(f"  K-rate tier gap: {k_gap:+.1%} ({direction})")
else:
    print(f"  K-rate tier gap: {k_gap:+.1%} — TOO SMALL for signal")

# Check venue type
dome_hr_val = combined[combined.venue_type == 'DOME'].correct.mean()
open_hr_val = combined[combined.venue_type == 'OPEN_AIR'].correct.mean()
venue_gap = dome_hr_val - open_hr_val
print(f"  Dome vs Open-air gap: {venue_gap:+.1%}", "— RANKING SIGNAL" if abs(venue_gap) > 0.03 else "— TOO SMALL")

# Check interleague
il_hr = combined[combined.interleague].correct.mean()
sl_hr = combined[~combined.interleague].correct.mean()
il_gap = il_hr - sl_hr
print(f"  Interleague vs Same-league gap: {il_gap:+.1%}", "— RANKING SIGNAL" if abs(il_gap) > 0.03 else "— TOO SMALL")

# Travel effect
home_hr_val = combined[combined.is_home == 1].correct.mean()
away_hr_val = combined[combined.is_home == 0].correct.mean()
ha_gap = home_hr_val - away_hr_val
print(f"  Home vs Away pitcher gap: {ha_gap:+.1%}", "— RANKING SIGNAL" if abs(ha_gap) > 0.03 else "— TOO SMALL")

# Seasonality
spring_hr = combined[combined.month.isin([4, 5])].correct.mean()
summer_hr = combined[combined.month.isin([6, 7, 8])].correct.mean()
fall_hr = combined[combined.month.isin([9])].correct.mean()
print(f"\n  Seasonality: Apr-May {spring_hr:.1%} | Jun-Aug {summer_hr:.1%} | Sep {fall_hr:.1%}")

print("\n--- Summary Verdict ---")
print("""
Decision framework:
  HARD FILTER: Use when HR < 48% with N >= 80 and cross-season persistence confirmed
  RANKING SIGNAL: Use when effect size > 3pp and somewhat persistent
  OBSERVATION: Use when signal exists but N is too small or not cross-season validated
  IGNORE: Effect < 2pp or not statistically significant
""")

# Count actionable findings
print("\nDone. Results above should be read carefully — small N and multiple comparisons")
print("mean many of these effects may be noise. Focus on LARGE effects (>5pp) with LARGE N (>200).")
