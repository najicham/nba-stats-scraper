# Model Training Dead Ends

**Last Updated:** 2026-03-04 (Session 403)

Do NOT revisit these approaches — all tested and confirmed negative or neutral.

## Training Approaches
- Grow policy, CHAOS+quantile, residual mode, two-stage pipeline
- Edge Classifier (AUC < 0.50 — does not add value)
- Huber loss (47.4% HR)
- Recency weighting (33.3%)
- Lines-only training (20%)
- Min-PPG filter (33.3%)
- 96-day window
- 87-day training window (too much old data dilutes signal)
- Post-ASB-only training (only 637 samples — need 2,000+, Session 376)
- Anchor-line training (predict actual-prop_line: collapses feature importance, only 9 edge 3+ picks, UNDER 33.3%)
- Direction-specific models (OVER-only/UNDER-only regression — binary classifier AUC=0.507, circular dependency)

## Quantile/Loss Function
- Q43+Vegas (20% HR edge 5+, catastrophic UNDER compounding)
- Q60 quantile (generates OVER volume but not profitably — 50% OVER HR)
- V16 Q55 quantile (53.3% HR, confirmed Session 365: 48.9% HR)
- Noveg Q43 on fresh data (14.8% HR live — 0/54 UNDER)
- LightGBM Q55 (non-deterministic — swung 62%→52% between runs)
- V13+Huber5 combo (62.0% — loss function and features interact non-linearly)

## Feature Variants
- TeamRankings pace features (team_pace_tr, opp_pace_tr, pace_ratio_tr) — Session 408: redundant with existing f7/f14/f22, <1% importance in all 5 seeds, -3.4pp HR vs baseline. Model already has 4 pace features.
- Static tracking stats as individual features (usg, ppg, pct_pts, fga) — Session 407: +0.3pp = noise. 9.2% importance but no HR gain.
- V16 deviation features alone (61.5% vs V12's 73.7%)
- V17 opportunity risk features (blowout_minutes_risk, minutes_volatility_last_10, opponent_pace_mismatch — all <1% importance, 56.7% HR)
- V19 scoring_skewness_last_10 as model feature (not in top 10 importance, 63.16% HR — works better as filter)
- XGBoost+V13 features (63.64% HR — vegas leaks through V13 shooting features)
- Derived D11 expected_scoring_possessions (amplifies usage_spike_score drift — 62.8% vs 68.6%)
- Derived D12 rolling_zscore_5v10 (<1% importance, no signal)
- Percentile features for drift-prone features (all 7 <2% importance, -2.76pp HR, 5-seed validated)

## Training Config
- RSM 0.5 with v9_low_vegas (hurts HR)
- Min-data-in-leaf 25/50 (kills feature diversity, top 2 features = 64-68%)
- Vegas weight < 0.25 (0.1x UNDER 54.5% — worse than 0.25x at 60%)
- Category weight dampening (increases variance, NOT significant across 5 seeds, Session 369)
- W6+dampening stacking (dampening hurts tight windows, Session 369)
- Recency on well-calibrated models (V12 vegas=0.25 went 75%→59%)
- V16 wide eval Feb 1-27 (55.9% — Feb degradation dilutes signal)
- V16 Nov 1 training start (92-day window too broad)
- Window-based ensemble 35d/42d/63d (all 64-66% HR, same feature set = no diversity)
- Tier models on 42-day window (insufficient per-tier samples)
- Starter tier model Dec 1 window (1/6 gates, Vegas bias +2.49)
- XGBoost version mismatch (trained v3.1.2, production v2.0.2 — predictions ~8.6pts off)
- XGBoost vegas weight insensitivity (vw015 = vw025 — unlike CatBoost/LightGBM)

## Signal/Filter Dead Ends
- No-vegas binary classifier (AUC 0.507 = random)
- Health gate on raw model HR (blocked profitable multi-model bets, removed Session 347)
- Blowout_recovery signal (50% HR, 25% in Feb — disabled Session 349)
- Edge calibration isotonic regression (flat ~51% everywhere, Session 370)
- CatBoost uncertainty/virtual ensembles (Q1-Q4 gap reversed on 4/5 seeds)
- Usage_spike_score exclusion/downweight (model already handles drift internally)
- Tier weights star=2.0/starter=1.2/role=0.8/bench=0.3 (ZERO effect across 5 seeds)
- Extended rest 4+d OVER block (research used wrong feature column)
- NOP/SAC UNDER block (research data was wrong — BQ showed different HRs)
- b2b_fatigue_under signal (39.5% Feb HR, disabled Session 373)
- Various UNDER blocks: near-zero scoring_trend_slope, IND opponent, 2+ stars_out, low CV — all either wrong at raw level or already handled by filter stack
- Adversarial noise on usage_spike_score (hurts UNDER)
- Stacked residual on catboost_v8 (47.37% HR — learns noise)
- OVER recovery via Q55/exclude-USS/reweight-categories (all worse than baseline)
- Familiar_matchup threshold lower to 4 (filtering PROFITABLE picks)
- Adaptive signal floor by regime (no SC bucket below breakeven in Feb)
- Slate size filter, time slot x direction filter, model agreement signal
- Line-range-specific edge floors (all above breakeven, filter stack handles)
- Dynamic edge threshold by model age (calendar date is confound, not age)
- Large spread starters UNDER (56.2% HR — BELOW baseline)
- Timezone crossing UNDER block (53.2% — too weak)
- Star_under filter, seasonal star_under, DOW-specific star_under (Session 400b)
- Away_noveg filter (Session 401 — root cause was model staleness)
- Reddit/social media sentiment (Session 403 — team-level, already priced in, near-zero for props)
