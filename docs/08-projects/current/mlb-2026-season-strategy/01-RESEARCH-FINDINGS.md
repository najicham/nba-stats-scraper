# MLB 2026 — Research Findings

Session 443: 11 parallel research agents, 3,869+ walk-forward predictions (Apr 2024 - Sep 2025).

## Agent Results

### 1. Retrain Cadence
- **14d is optimal.** 7d = +0.6pp (noise, 2x compute). 21d = -1.7pp (real cliff).
- No staleness within a 14d window (early vs late HR identical, p=0.99).
- Trigger-based retraining is -0.5pp worse than fixed schedule.
- Season-start is weak — force retrain after 3 weeks with 200+ in-season samples.

### 2. Pitcher Deep Dive (225 pitchers analyzed)
- Expand blacklist 10 → 18 pitchers. Top additions: Logan Webb (37.5%), Jose Berrios (38.1%), Logan Gilbert (38.5%).
- Removed from blacklist (now profitable): Freddy Peralta (54.5%), Tyler Glasnow (66.7%), Paul Skenes (61.9%).
- K/9 sweet spot: 8.0-8.5 (64.3% HR). K/9 9.0-9.5 is the worst zone (45.3%).
- Extended rest 7d+ is a real signal (+4-6pp).
- Pitcher autocorrelation is near-zero (r=0.030). Individual starts are independent.
- Best opponents: BAL (66.2%), ARI (66.2%). Worst: KC (45.6%), ATL (46.8%).

### 3. Seasonal Patterns
- **Unified strategy is best.** No toxic windows survive multiple testing correction.
- OVER dominance is significant: 58.4% vs 52.6% (p=0.0076).
- Seasonal ramp (not window): April 52.7% → May-Aug 56.8% → Sep 61.2%.
- June is consistently weak (52.4% both years) but doesn't reach significance.
- ASB, trade deadline, DOW, day/night, dome/outdoor — all noise.

### 4. Filter Stack Optimization
- Pitcher blacklist: +3.1pp (biggest single filter).
- Whole-number line filter: +1.6pp incremental after other filters.
- Edge floor 0.75K maximizes total profit.
- Tiered ranking (hybrid #1, edge #2-3) = 66.2% HR top-3.
- UNDER at edge 0.5-0.75K = 59.7% (viable with signal gating).

### 5. Ensemble Models
- **CatBoost solo wins.** 64.7% HR at e≥1.0 vs best ensemble 61.8%.
- Model agreement is anti-correlated with winning (-3.1pp).
- Models correlated at r ~0.93. Averaging dilutes CatBoost's unique signal.
- Same pattern as NBA fleet.

### 6. Top-Pick Quality
- Filter stack is the real alpha (+5.5pp over unfiltered).
- Composite ranking: +2.3pp over pure edge (but fails cross-season — see agent 11).
- Ultra staking (2u on high-confidence) boosts profit +33%.
- No unfiltered subset reliably hits 70%.
- 11 of 13 months profitable. Aug-Sep strongest.

### 7. UNDER Deep Dive
- UNDER IS viable with strict filters: 62.6% HR (N=115).
- Edge alone is useless for UNDER — flat at 51-55% regardless of floor.
- Signal stacking works: edge ≥ 1.5 AND projection < line AND (cold_form OR line ≥ 6.0).
- Mixed portfolio (3 OVER + 1 filtered UNDER) improves both HR and ROI.
- Direction-aware pitcher insights: Corbin Burnes OVER 36%/UNDER 67%.

### 8. Hyperparameter Sweep
- **Defaults win.** Every alternative (deeper trees, different LR, alternative loss functions) is worse or noise.
- Deeper trees make more picks but dilute quality. Shallow baseline is more selective.
- RMSE loss > MAE > Quantile > Huber.

### 9. Line/Market Analysis
- **Whole-number lines: 49.0% OVER HR** (p<0.001). Push rate 17.3%.
- Edge ≥ 3.0 hurts (50% HR). Same overconfidence pattern as NBA.
- Proba ≥ 0.80 is overconfident (48.4% HR).
- Low lines (≤ 4.0) are the sweet spot: 60% HR.
- Market systematically underprices K lines (+0.37 K bias).
- Projection agreement: +2.6pp when agreeing, -3.8pp when disagreeing.
- Half-lines structurally favor OVER at 54.5% vs 46.3% for whole lines.

### 10. Opponent/Venue Interactions
- **Cross-season opponent HR is anti-correlated (r=-0.29).** Static lists are useless.
- Venue effects confounded with home team (eta²=0.006, p=0.13).
- No travel, familiarity, division, or timezone effects detected.
- April penalty is real (52.2%, -6pp) — structural, from cold weather + small training windows.
- Rolling 60-day opponent K-rate is the only viable opponent signal (dynamic, not static).

### 11. Composite Scoring
- **Pure edge ranking wins.** No composite survives cross-season validation.
- Logistic regression: zero significant predictors (AUC 0.5385).
- Adding features monotonically hurts top-3 ranking.
- Projection agrees lift flips direction between seasons (+6.4pp 2024, -0.3pp 2025).

### 12. Feature Importance
- Top 3 features: line_level (18.1%), fip (10.9%), bp_projection (5.8%).
- Top 5 features alone = 55.2% HR (+1.5pp over 41-feature baseline).
- 3 dead features (zero importance): month_of_season, days_into_season, is_postseason.
- 2 exact duplicates: season_starts = season_games, recent_workload_ratio = games_last_30d/6.
- All derived features are noise. CatBoost captures interactions internally.
- Feature rankings stable across retrains (Spearman rho = 0.882).

### 13. Bankroll Simulation (10,000 Monte Carlo seasons)
- 100% profitable at observed HR. 98.5% at pessimistic 56%.
- Flat 1u is best risk-adjusted. Kelly criterion has 97% max drawdown.
- Profitable at every juice level including -125.
- 50u bankroll = 0% ruin probability.
- Max consecutive losses: 8. Max drawdown: 13.2%.

### 14. Ultra Tier Discovery
- **edge ≥ 1.0 + home + projection agrees = 72.9% HR** (N=221), 3.1pp cross-season gap.
- edge ≥ 1.25 + home = 72.7% (N=128), 0.7pp gap — tighter but lower volume.
- 88% of ultra picks overlap with BB top-3.
- Ultra has 1 losing month in 13 (Mar 2025, N=1).
- Ultra generates equal profit to BB despite 60% fewer picks (2u staking).

## Cross-Cutting Themes

1. **Filters > model tuning.** Filters add +5-8pp. Hyperparameters add 0pp.
2. **Simplicity wins.** Pure edge ranking > composite. Defaults > tuned. Solo > ensemble.
3. **Static lists fail.** Opponents, venues, pitcher stats — all unstable cross-season.
4. **Structural edges survive.** Push risk, overconfidence cap, pitcher quality — these are real.
5. **Same lessons as NBA.** Adding features hurts. Ensembles dilute. Complexity costs.
