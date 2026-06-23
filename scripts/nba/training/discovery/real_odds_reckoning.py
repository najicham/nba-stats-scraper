#!/usr/bin/env python3
"""Real-odds reckoning: recompute the edge beliefs on the walk-forward cache using
ACTUAL bettingpros odds (both sides) instead of fictional flat -110.

Question (briefing P0): does flat -110 mislead? NBA points props commonly run
-115..-125 (vig 4-9%) vs the -110 (4.5%) assumed everywhere. Which edge-band /
direction cells that look profitable at -110 flip negative at real prices?

Method: per pick (game_date, player_lookup, direction, line, correct) from the
cache, attach the median real American odds for that SIDE from bettingpros (matched
on player-game; report line-match coverage). units = win?(decimal-1):-1.
Compare ROI flat-110 vs ROI real-odds, by edge band x direction (pooled + season).
"""
from pathlib import Path
import numpy as np
import pandas as pd
from google.cloud import bigquery

PROJECT_ID = "nba-props-platform"
FILES = ['results/nba_walkforward_2021/predictions_w56_r7.csv',
         'results/nba_walkforward_2022/predictions_w56_r7.csv',
         'results/nba_walkforward_clean/predictions_w56_r7.csv',
         'results/bb_simulator/predictions_2025_26_all_models.csv']
RANGES = {'2021-22':('2021-10-01','2022-07-01'),'2022-23':('2022-10-01','2023-07-01'),
          '2023-24':('2023-10-01','2024-07-01'),'2024-25':('2024-10-01','2025-07-01'),
          '2025-26':('2025-10-01','2026-07-01')}
def season_of(d):
    for s,(a,b) in RANGES.items():
        if a<=d<=b: return s
    return '?'

def payout(american):
    """decimal-1 (profit per 1 staked) from American odds."""
    a = np.asarray(american, dtype=float)
    return np.where(a>0, a/100.0, 100.0/np.abs(a))

preds = pd.concat([pd.read_csv(f) for f in FILES if Path(f).exists()], ignore_index=True)
preds = preds.drop_duplicates(['game_date','player_lookup','line'])
preds['game_date'] = preds['game_date'].astype(str)
preds['abs_edge'] = preds['edge'].abs()
preds['season'] = preds['game_date'].map(season_of)
print(f"cache picks: {len(preds):,}")

c = bigquery.Client(project=PROJECT_ID)
# median real odds + median line per (game_date, player_lookup, side)
odds = c.query(f"""
WITH dedup AS (
  SELECT game_date, player_lookup, bet_side, book_id,
         points_line, odds_american,
         ROW_NUMBER() OVER (PARTITION BY game_date,player_lookup,bet_side,book_id
                            ORDER BY bookmaker_last_update DESC) rn
  FROM `{PROJECT_ID}.nba_raw.bettingpros_player_points_props`
  WHERE market_type='points' AND odds_american IS NOT NULL AND points_line IS NOT NULL AND game_date BETWEEN '2021-10-01' AND '2026-07-01'
)
SELECT CAST(game_date AS STRING) game_date, player_lookup,
  APPROX_QUANTILES(IF(bet_side='over', odds_american, NULL),2)[OFFSET(1)] AS over_odds,
  APPROX_QUANTILES(IF(bet_side='under',odds_american, NULL),2)[OFFSET(1)] AS under_odds,
  APPROX_QUANTILES(points_line,2)[OFFSET(1)] AS bp_line
FROM dedup WHERE rn=1
GROUP BY 1,2
""").to_dataframe()
print(f"odds rows: {len(odds):,}")

df = preds.merge(odds, on=['game_date','player_lookup'], how='left')
df['has_odds'] = df['over_odds'].notna() & df['under_odds'].notna()
df['line_match'] = df['has_odds'] & (np.abs(df['line'] - df['bp_line']) <= 0.5)
print(f"odds coverage: {100*df['has_odds'].mean():.1f}% | exact-line(±0.5): {100*df['line_match'].mean():.1f}%")
print(f"median real odds — OVER {df['over_odds'].median():.0f}  UNDER {df['under_odds'].median():.0f}  (flat=-110)")

# real odds for the picked side
df['side_odds'] = np.where(df['direction']=='OVER', df['over_odds'], df['under_odds'])
# units at flat -110 and at real odds (only rows with odds)
def roi_table(sub, label):
    print(f"\n===== {label} (picks w/ real odds = {int(sub['has_odds'].sum())}/{len(sub)}) =====")
    print(f"  {'edge':>6} {'dir':>5} | {'N':>5} {'HR':>6} | {'ROI@-110':>9} | {'ROI@real':>9} | {'Δ pp':>6} | flip?")
    s = sub[sub['has_odds']].copy()
    s['u_flat'] = np.where(s['correct']==1, 0.909, -1.0)
    s['u_real'] = np.where(s['correct']==1, payout(s['side_odds']), -1.0)
    for lo,hi,lab in [(0,3,'0-3'),(3,5,'3-5'),(5,99,'5+'),(3,99,'3+')]:
        for d in ['OVER','UNDER']:
            g = s[(s.abs_edge>=lo)&(s.abs_edge<hi)&(s.direction==d)]
            if len(g)<10: continue
            hr=100*g.correct.mean(); rf=100*g.u_flat.mean(); rr=100*g.u_real.mean()
            flip = '⚠ FLIP' if (rf>0)!=(rr>0) else ''
            print(f"  {lab:>6} {d:>5} | {len(g):>5} {hr:5.1f}% | {rf:+8.1f}% | {rr:+8.1f}% | {rr-rf:+5.1f} | {flip}")

roi_table(df, "POOLED (5 seasons)")
for ssn in sorted(df.season.unique()):
    roi_table(df[df.season==ssn], f"SEASON {ssn}")
