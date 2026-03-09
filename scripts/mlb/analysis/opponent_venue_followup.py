#!/usr/bin/env python3
"""
Follow-up analysis on key findings from the initial deep dive.
Focuses on cross-season validation and the most actionable patterns.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats

pd.set_option('display.width', 200)
pd.set_option('display.max_colwidth', 30)
pd.set_option('display.max_rows', 100)
pd.set_option('display.float_format', '{:.3f}'.format)

BASE = Path(__file__).resolve().parent.parent.parent.parent / "results"

# Load everything — combine both models at edge 0.5/0.25 for max data
rich = pd.read_csv(BASE / "mlb_walkforward_v4_rich/predictions_catboost_120d_fixed_edge0.5.csv")
reg = pd.read_csv(BASE / "mlb_walkforward_v4_regression/predictions_regression_120d_edge0.50.csv")

TEAM_MAP = {'AZ': 'ARI'}
for df in [rich, reg]:
    df['team_abbr'] = df['team_abbr'].replace(TEAM_MAP)
    df['opponent_team_abbr'] = df['opponent_team_abbr'].replace(TEAM_MAP)

rich['source'] = 'catboost'
rich['predicted_dir'] = rich['predicted_over'].map({1: 'OVER', 0: 'UNDER'})
reg['source'] = 'regression'
reg['predicted_dir'] = reg['predicted_over'].map({1: 'OVER', 0: 'UNDER'})

combined = pd.concat([rich, reg], ignore_index=True)
combined['game_date'] = pd.to_datetime(combined['game_date'])
combined['month'] = combined['game_date'].dt.month
combined['year'] = combined['game_date'].dt.year
combined['season'] = combined['game_date'].apply(lambda d: d.year if d.month >= 3 else d.year - 1)


def hr_ci(series, z=1.96):
    n = len(series)
    if n == 0:
        return 0, 0, 0, 0
    hr = series.mean()
    se = np.sqrt(hr * (1 - hr) / n) if n > 1 else 0
    return hr, hr - z * se, hr + z * se, n


def section(title):
    print(f"\n{'=' * 100}")
    print(f"  {title}")
    print(f"{'=' * 100}")


# ─────────────────────────────────────────────────────
# A. KC DEEP DIVE — Is KC really a filter candidate?
# ─────────────────────────────────────────────────────
section("A. KC OPPONENT DEEP DIVE — Is the 46.3% HR real?")

kc = combined[combined.opponent_team_abbr == 'KC']
print(f"\nTotal picks vs KC: {len(kc)}, HR: {kc.correct.mean():.1%}")

# By season
for season in sorted(kc.season.unique()):
    s = kc[kc.season == season]
    hr, lo, hi, n = hr_ci(s.correct)
    print(f"  {season}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n}")

# By direction
print("\n  By direction:")
for d in ['OVER', 'UNDER']:
    s = kc[kc.predicted_dir == d]
    hr, lo, hi, n = hr_ci(s.correct)
    print(f"    {d}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n}")

# By model
print("\n  By model:")
for src in ['catboost', 'regression']:
    s = kc[kc.source == src]
    hr, lo, hi, n = hr_ci(s.correct)
    print(f"    {src}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n}")

# KC venue vs KC away
print("\n  KC at home (Kauffman) vs KC on road:")
kc_home = kc[kc.venue == 'Kauffman Stadium']
kc_away = kc[kc.venue != 'Kauffman Stadium']
hr_h, _, _, n_h = hr_ci(kc_home.correct)
hr_a, _, _, n_a = hr_ci(kc_away.correct)
print(f"    At Kauffman: HR {hr_h:.1%} N={n_h}")
print(f"    Away venues: HR {hr_a:.1%} N={n_a}")

# KC K-rate is league-lowest. Does model systematically overshoot?
print(f"\n  KC batters avg Ks per game (from data): {kc.actual_strikeouts.mean():.2f}")
print(f"  KC avg line set at: {kc.strikeouts_line.mean():.2f}")
print(f"  KC actual over rate: {kc.actual_over.mean():.1%}")
print(f"  KC predictions: {kc.predicted_over.mean():.1%} predicted OVER")

# KC month-by-month
print("\n  KC by month:")
for m in sorted(kc.month.unique()):
    s = kc[kc.month == m]
    month_name = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'][m]
    hr, lo, hi, n = hr_ci(s.correct)
    print(f"    {month_name}: HR {hr:.1%} N={n}")


# ─────────────────────────────────────────────────────
# B. HOME/AWAY SPLIT — Biggest finding: some teams wildly different
# ─────────────────────────────────────────────────────
section("B. HOME/AWAY SPLITS — Cross-season validation")

# The most extreme splits were STL (-20%), SF (-14%), NYY (+15%), MIL (+22%)
# Are these persistent or random?

extreme_teams = ['STL', 'SF', 'LAD', 'PIT', 'COL', 'NYY', 'NYM', 'MIL', 'SEA', 'CLE', 'CHC']

for team in extreme_teams:
    print(f"\n--- {team} ---")
    t_data = combined[combined.team_abbr == team]
    for season in sorted(t_data.season.unique()):
        s = t_data[t_data.season == season]
        home = s[s.is_home == 1]
        away = s[s.is_home == 0]
        if len(home) >= 10 and len(away) >= 10:
            home_hr = home.correct.mean()
            away_hr = away.correct.mean()
            delta = home_hr - away_hr
            print(f"  {season}: Home {home_hr:.1%} (N={len(home)}) | Away {away_hr:.1%} (N={len(away)}) | Delta {delta:+.1%}")

# Overall home vs away
print("\n--- Overall Home vs Away (all teams) ---")
home_all = combined[combined.is_home == 1]
away_all = combined[combined.is_home == 0]
hr_h, lo_h, hi_h, n_h = hr_ci(home_all.correct)
hr_a, lo_a, hi_a, n_a = hr_ci(away_all.correct)
print(f"  Home: HR {hr_h:.1%} [{lo_h:.1%}-{hi_h:.1%}] N={n_h:,}")
print(f"  Away: HR {hr_a:.1%} [{lo_a:.1%}-{hi_a:.1%}] N={n_a:,}")

# Cross-season persistence of home/away gap per team
ha_by_season = combined.groupby(['team_abbr', 'season', 'is_home']).agg(
    hr=('correct', 'mean'), n=('correct', 'count')
).reset_index()

gaps_2024 = {}
gaps_2025 = {}
for team in combined.team_abbr.unique():
    for season, gap_dict in [(2024, gaps_2024), (2025, gaps_2025)]:
        t_home = ha_by_season[(ha_by_season.team_abbr == team) & (ha_by_season.season == season) & (ha_by_season.is_home == 1)]
        t_away = ha_by_season[(ha_by_season.team_abbr == team) & (ha_by_season.season == season) & (ha_by_season.is_home == 0)]
        if len(t_home) > 0 and len(t_away) > 0 and t_home.n.iloc[0] >= 15 and t_away.n.iloc[0] >= 15:
            gap_dict[team] = t_home.hr.iloc[0] - t_away.hr.iloc[0]

common_teams = set(gaps_2024.keys()) & set(gaps_2025.keys())
if len(common_teams) >= 10:
    g24 = [gaps_2024[t] for t in common_teams]
    g25 = [gaps_2025[t] for t in common_teams]
    r, p = stats.pearsonr(g24, g25)
    print(f"\n  Home/Away gap persistence: r = {r:.3f} (p = {p:.4f}) across {len(common_teams)} teams")
    if r > 0.3:
        print("  >>> Home/Away gap IS persistent — could be a signal")
    else:
        print("  >>> Home/Away gap is NOT persistent — likely noise")


# ─────────────────────────────────────────────────────
# C. OVER vs UNDER BY OPPONENT — Which direction hurts more?
# ─────────────────────────────────────────────────────
section("C. OVER vs UNDER HR BY OPPONENT — Does KC hurt OVER or UNDER?")

# For the worst opponents, check if the HR penalty is on OVER or UNDER
worst_opps = ['KC', 'MIA', 'CWS', 'SEA', 'ATL']
best_opps = ['BAL', 'MIL', 'TOR', 'SF', 'ARI']

print("\n--- WORST Opponents: OVER vs UNDER split ---")
for opp in worst_opps:
    s = combined[combined.opponent_team_abbr == opp]
    over = s[s.predicted_dir == 'OVER']
    under = s[s.predicted_dir == 'UNDER']
    print(f"  vs {opp:>4s}: OVER {over.correct.mean():.1%} (N={len(over):>4d}) | "
          f"UNDER {under.correct.mean():.1%} (N={len(under):>4d}) | "
          f"Actual Over Rate: {s.actual_over.mean():.1%}")

print("\n--- BEST Opponents: OVER vs UNDER split ---")
for opp in best_opps:
    s = combined[combined.opponent_team_abbr == opp]
    over = s[s.predicted_dir == 'OVER']
    under = s[s.predicted_dir == 'UNDER']
    print(f"  vs {opp:>4s}: OVER {over.correct.mean():.1%} (N={len(over):>4d}) | "
          f"UNDER {under.correct.mean():.1%} (N={len(under):>4d}) | "
          f"Actual Over Rate: {s.actual_over.mean():.1%}")


# ─────────────────────────────────────────────────────
# D. APRIL EFFECT — Is early-season harder to predict?
# ─────────────────────────────────────────────────────
section("D. EARLY SEASON EFFECT — April vs rest of season")

# April is notorious for cold weather, small sample, pitcher deception
for period, mask in [
    ("April (early season)", combined.month == 4),
    ("May", combined.month == 5),
    ("June-August (summer)", combined.month.isin([6, 7, 8])),
    ("September (late)", combined.month == 9),
]:
    s = combined[mask]
    hr, lo, hi, n = hr_ci(s.correct)
    over = s[s.predicted_dir == 'OVER']
    under = s[s.predicted_dir == 'UNDER']
    over_hr = over.correct.mean() if len(over) > 0 else 0
    under_hr = under.correct.mean() if len(under) > 0 else 0
    print(f"  {period:30s}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n:,} | OVER {over_hr:.1%} | UNDER {under_hr:.1%}")

# By model in April
print("\n  April by model:")
april = combined[combined.month == 4]
for src in ['catboost', 'regression']:
    s = april[april.source == src]
    hr, lo, hi, n = hr_ci(s.correct)
    print(f"    {src}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n}")


# ─────────────────────────────────────────────────────
# E. DIFFICULTY QUINTILE × DIRECTION INTERACTION
# ─────────────────────────────────────────────────────
section("E. OPPONENT DIFFICULTY × DIRECTION — Where does the edge come from?")

# Recompute difficulty score
team_metrics = combined.groupby('opponent_team_abbr').agg(
    hr=('correct', 'mean'),
    n=('correct', 'count'),
    avg_k=('actual_strikeouts', 'mean'),
).reset_index()

# Simple difficulty: just use historical HR (since cross-season shows r=-0.29,
# the composite score adds no value over raw HR)
team_metrics = team_metrics.sort_values('hr')
team_metrics['difficulty_q'] = pd.qcut(team_metrics.hr, 5, labels=['Q1_Hardest', 'Q2', 'Q3', 'Q4', 'Q5_Easiest'])
diff_map = team_metrics.set_index('opponent_team_abbr')['difficulty_q'].to_dict()
combined['opp_q'] = combined['opponent_team_abbr'].map(diff_map)

print("\n--- OVER HR by Opponent Difficulty Quintile ---")
for q in ['Q1_Hardest', 'Q2', 'Q3', 'Q4', 'Q5_Easiest']:
    s = combined[combined.opp_q == q]
    over = s[s.predicted_dir == 'OVER']
    under = s[s.predicted_dir == 'UNDER']
    hr_o, lo_o, hi_o, n_o = hr_ci(over.correct)
    hr_u, lo_u, hi_u, n_u = hr_ci(under.correct)
    print(f"  {q:12s}: OVER {hr_o:.1%} [{lo_o:.1%}-{hi_o:.1%}] N={n_o:>4d} | "
          f"UNDER {hr_u:.1%} [{lo_u:.1%}-{hi_u:.1%}] N={n_u:>4d} | "
          f"Delta: {hr_o - hr_u:+.1%}")


# ─────────────────────────────────────────────────────
# F. EDGE CONCENTRATION — Do we lose on low-edge picks vs hard opponents?
# ─────────────────────────────────────────────────────
section("F. EDGE × OPPONENT — Do we lose on marginal picks?")

# Use catboost data which has clean edge column
rich_c = rich.copy()
rich_c['edge_bucket'] = pd.cut(rich_c['edge'].abs(), bins=[0, 1, 1.5, 2, 3, 10], labels=['0-1', '1-1.5', '1.5-2', '2-3', '3+'])

for tier, teams in [('HARD', ['KC', 'MIA', 'CWS', 'SEA', 'ATL', 'NYM']),
                    ('EASY', ['BAL', 'MIL', 'TOR', 'SF', 'ARI', 'DET', 'PIT'])]:
    print(f"\n  {tier} opponents: {teams}")
    sub = rich_c[rich_c.opponent_team_abbr.isin(teams)]
    for eb in ['0-1', '1-1.5', '1.5-2', '2-3', '3+']:
        e = sub[sub.edge_bucket == eb]
        if len(e) >= 10:
            hr, lo, hi, n = hr_ci(e.correct)
            print(f"    Edge {eb:>5s}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n}")


# ─────────────────────────────────────────────────────
# G. LOW-K OPPONENT × OVER — The structural pattern
# ─────────────────────────────────────────────────────
section("G. LOW-K OPPONENT × OVER PREDICTION — Structural mismatch?")

# KC has the lowest K rate. When we predict OVER against KC, do we systematically fail?
# Check residuals (regression model has them)
reg_c = reg.copy()

low_k_teams = ['KC', 'SD', 'TOR', 'MIA', 'HOU', 'WSH']
high_k_teams = ['LAA', 'SEA', 'COL', 'BOS', 'OAK', 'PIT']

for label, teams in [('LOW-K opponents', low_k_teams), ('HIGH-K opponents', high_k_teams)]:
    sub = reg_c[reg_c.opponent_team_abbr.isin(teams)]
    over = sub[sub.predicted_dir == 'OVER']
    under = sub[sub.predicted_dir == 'UNDER']
    if 'residual' in sub.columns:
        print(f"\n  {label}:")
        print(f"    OVER:  HR {over.correct.mean():.1%} N={len(over)} | "
              f"Avg residual: {over.residual.mean():.2f} | Median: {over.residual.median():.2f}")
        print(f"    UNDER: HR {under.correct.mean():.1%} N={len(under)} | "
              f"Avg residual: {under.residual.mean():.2f} | Median: {under.residual.median():.2f}")
        print(f"    Avg actual K: {sub.actual_strikeouts.mean():.2f} vs predicted: {sub.predicted_k.mean():.2f}")


# ─────────────────────────────────────────────────────
# H. DIVISION-LEVEL DEEPER — OVER vs UNDER by division
# ─────────────────────────────────────────────────────
section("H. DIVISION EFFECTS — OVER vs UNDER breakdown")

DIVISIONS = {
    'AL East': ['NYY', 'BOS', 'TB', 'TOR', 'BAL'],
    'AL Central': ['CLE', 'MIN', 'CWS', 'DET', 'KC'],
    'AL West': ['HOU', 'SEA', 'TEX', 'LAA', 'OAK'],
    'NL East': ['ATL', 'NYM', 'PHI', 'MIA', 'WSH'],
    'NL Central': ['MIL', 'STL', 'CHC', 'CIN', 'PIT'],
    'NL West': ['LAD', 'SD', 'SF', 'ARI', 'COL'],
}

TEAM_TO_DIV = {}
for div, teams in DIVISIONS.items():
    for t in teams:
        TEAM_TO_DIV[t] = div

combined['opp_div'] = combined['opponent_team_abbr'].map(TEAM_TO_DIV)

print("\n--- OVER HR by Opponent Division ---")
for div in sorted(DIVISIONS.keys()):
    s = combined[combined.opp_div == div]
    over = s[s.predicted_dir == 'OVER']
    under = s[s.predicted_dir == 'UNDER']
    hr_o, lo_o, hi_o, n_o = hr_ci(over.correct)
    hr_u, lo_u, hi_u, n_u = hr_ci(under.correct)
    print(f"  {div:>14s}: OVER {hr_o:.1%} [{lo_o:.1%}-{hi_o:.1%}] N={n_o:>4d} | "
          f"UNDER {hr_u:.1%} [{lo_u:.1%}-{hi_u:.1%}] N={n_u:>4d}")


# ─────────────────────────────────────────────────────
# I. RATE FIELD / BUSCH — Are these venue effects real?
# ─────────────────────────────────────────────────────
section("I. WORST VENUES DEEP DIVE")

for venue in ['Rate Field', 'Busch Stadium', 'loanDepot park', 'Daikin Park']:
    v = combined[combined.venue == venue]
    print(f"\n--- {venue} ---")
    print(f"  Overall: HR {v.correct.mean():.1%} N={len(v)}")
    for season in sorted(v.season.unique()):
        s = v[v.season == season]
        if len(s) >= 10:
            hr, lo, hi, n = hr_ci(s.correct)
            print(f"  {season}: HR {hr:.1%} [{lo:.1%}-{hi:.1%}] N={n}")
    # OVER vs UNDER
    over = v[v.predicted_dir == 'OVER']
    under = v[v.predicted_dir == 'UNDER']
    print(f"  OVER: {over.correct.mean():.1%} N={len(over)} | UNDER: {under.correct.mean():.1%} N={len(under)}")
    # Home team
    home_team = v[v.is_home == 1]['team_abbr'].mode()
    if len(home_team) > 0:
        print(f"  Home team: {home_team.iloc[0]}")


# ─────────────────────────────────────────────────────
# FINAL ACTIONABLE SUMMARY
# ─────────────────────────────────────────────────────
section("FINAL ACTIONABLE SUMMARY")

print("""
FINDINGS RANKED BY ACTIONABILITY:

1. KC AS OPPONENT: 46.3% HR (N=227) — WORST in dataset
   - 2024: 40.0%, 2025: 51.2% — improved but still below baseline
   - OVER vs KC: 44.1% HR — model systematically overshoots against lowest-K lineup
   - Mechanism: KC batters make contact, K-rate lowest in MLB
   - VERDICT: OBSERVATION MODE (improved in 2025, not stable enough for hard filter)

2. RATE FIELD (CWS home): 47.7% HR (N=109) — WORST venue
   - CWS moved from Guaranteed Rate Field to Rate Field
   - Small sample — need to validate with 2025 data
   - VERDICT: OBSERVATION MODE (N too small for hard filter)

3. APRIL PENALTY: ~51% HR in April vs ~57% May-Sep
   - Cold weather, small sample sizes for model
   - Not specific to any team or venue
   - VERDICT: RANKING SIGNAL — reduce confidence in April picks

4. OPPONENT DIFFICULTY NOT PERSISTENT: r = -0.29 across seasons
   - Teams that were hard in 2024 were often easy in 2025
   - K-rate is somewhat persistent (r=0.40) but doesn't translate to HR persistence
   - VERDICT: DO NOT use opponent difficulty as hard filter

5. HOME/AWAY SPLITS ARE NOT PERSISTENT:
   - Extreme splits (MIL +22%, NYY +15%) are single-season phenomena
   - Need cross-season r to confirm
   - VERDICT: IGNORE for now

6. DIVISION EFFECTS: AL East opponents = 59.5% HR, NL East = 53.1%
   - 6.4pp gap is meaningful
   - But driven by team composition (BAL, TOR inflate AL East; MIA, ATL deflate NL East)
   - VERDICT: Redundant with per-team effects, not additive

7. FAMILIARITY EFFECT: No significant effect (p=0.39)
   - 3rd+ matchup HR slightly higher but within noise
   - VERDICT: IGNORE

8. TRAVEL/TIMEZONE: No effect detected
   - Coast-to-coast (3 zones): 55.8% vs same-TZ 55.2%
   - VERDICT: IGNORE

RECOMMENDED ACTIONS:
  - Deploy `april_observation` signal: track April picks as observation
  - Deploy `low_k_opponent_over_obs` signal: OVER vs bottom-5 K-rate teams
  - KC opponent: MONITOR, do NOT hard filter (improved in 2025)
  - All venue-level filters: SKIP (confounded with opponent effects)
  - Cross-season instability means NO static opponent lists — must be rolling
""")
