# Comprehensive Model System Evaluation Plan

**Date:** 2026-02-25 (Session 343)
**Status:** PLAN — pending execution
**Goal:** Evaluate the entire model system, identify root causes of decline, determine which models still produce value, and decide on retraining/architecture changes.

---

## Executive Summary

Every production model is BLOCKED or DEGRADING. The system-wide crisis stems from three interrelated problems: (1) training staleness (10-48 days), (2) structural UNDER bias from MAE/Huber loss functions, and (3) over-reliance on Vegas features when Vegas is consistently more accurate than our models. This plan lays out a structured evaluation and action sequence.

---

## Part 1: Current State Assessment

### 1.1 Model Health Dashboard (as of Feb 25)

| Family | Best Variant | Edge 5+ HR | Edge 5+ N | State | Days Stale | Best Bets Source? |
|--------|-------------|-----------|----------|-------|------------|-------------------|
| v12_noveg_q45 | train1102_0125 | **71.4% UNDER** | 7 | BLOCKED | 31 | Yes (1 pick, 1 win) |
| v12_noveg_q43 | train0104_0215 | **66.7% UNDER** | 9 | BLOCKED | 10 | Yes (1 pick, 1 win) |
| v9_low_vegas | train0106_0205 | **62.5% UNDER** | 16 | DEGRADING | 20 | Yes (1 pick, 1 win) |
| v9_q45 | train1102_0125 | 55.6% UNDER | 9 | BLOCKED | 31 | No |
| v9_mae | champion | **51.3% OVER** | 39 | BLOCKED | 20 | No |
| v12_mae | champion | 50.0% UNDER | 18 | BLOCKED | 9 | Yes (2 picks, 1 win) |
| v9_q43 | train1102_0125 | 41.7% UNDER | 12 | BLOCKED | 31 | No |
| v9_mae | champion | **34.1% UNDER** | 85 | BLOCKED | 20 | No |
| v12_vegas_q43 | train0104_0215 | **20.0% UNDER** | 10 | BLOCKED | 10 | No |

**Key takeaways:**
1. The 3 families producing profitable edge-5+ picks are: **v12_noveg_q45**, **v12_noveg_q43**, and **v9_low_vegas** — all with reduced/zero Vegas features
2. The v9_mae UNDER direction is catastrophic (34.1%) but OVER is marginally OK (51.3%)
3. v12_vegas_q43 is the worst performer at 20.0% — full-Vegas quantile is a dead end
4. Only 6 graded best bets picks in 30 days — the blocking system is working (preventing losses) but best bets volume is critically low

### 1.2 Direction Bias Analysis

| Family | % UNDER Predictions | Avg Pred vs Vegas | Model MAE | Vegas MAE |
|--------|--------------------|--------------------|-----------|-----------|
| v12_noveg | **89.3%** | -3.14 | 5.38 | 4.99 |
| v12_champion | **79.3%** | -1.30 | 5.10 | 4.88 |
| v9_family | 61.6% | -0.61 | 5.12 | 4.88 |
| v9_low_vegas | 52.3% | -0.56 | 5.12 | 4.74 |

Every model has worse MAE than Vegas. The UNDER bias ranges from 52% (v9_low_vegas) to 89% (v12_noveg). The paradox: v12_noveg has the most extreme UNDER bias AND the best hit rate at edge 5+. This means the bias itself isn't the problem — it's the model's ability to identify *which* UNDERs will hit.

### 1.3 Weekly Trend Analysis

**V12 Champion (edge 3+):**
```
Jan 26: 66.7% (6 picks)  — good but tiny N
Feb 2:  54.5% (33 picks) — stable
Feb 9:  54.5% (11 picks) — stable
Feb 16: 58.3% (48 picks) — peak
Feb 23: 35.0% (20 picks) — COLLAPSE
```

**V9 Champion (edge 3+):**
```
Jan 19: 67.0% (112 picks) — peak
Jan 26: 57.3% (96 picks)  — declining
Feb 2:  36.3% (124 picks) — COLLAPSE
Feb 9:  45.1% (51 picks)  — not recovering
Feb 16: 47.1% (17 picks)  — still underwater
```

**Pattern:** Both models collapse ~3-4 weeks after training cutoff, suggesting a ~21-day effective shelf life for CatBoost models in the current NBA environment.

### 1.4 Best Bets Pipeline Analysis

Current best bets algorithm: `edge 5+ → negative filters → rank by edge → top 5`

**Problem:** Only 6 graded best bets picks in 30 days means:
- Model health blocking is correctly preventing bad picks
- But the system is generating almost no actionable output
- The blocking is so aggressive that very few picks survive all filters

**Best bets filter chain:**
1. Edge >= 5.0 (most picks eliminated here due to low model confidence)
2. Player blacklist (< 40% HR on 8+ edge-3+ picks)
3. Avoid familiar (6+ games vs opponent)
4. Feature quality floor (quality < 85)
5. Bench UNDER block (UNDER + line < 12)
6. UNDER + line movement blocks (line jumped/dropped 2+)
7. Model direction affinity blocking (NEW — Session 343)

The fact that only 6 picks survive in 30 days suggests the models aren't generating enough high-edge predictions, not that the filters are too strict.

---

## Part 2: Root Cause Diagnosis

### 2.1 Why Models Decline

| Root Cause | Evidence | Severity |
|-----------|----------|----------|
| **Training staleness** | V9 collapsed 3 weeks post-training (Jan 19→Feb 2). V12 collapsed ~2 weeks post-training (Feb 16→Feb 23). | HIGH |
| **MAE loss UNDER bias** | All MAE models predict 0.5-3.1 pts below Vegas → overwhelming UNDER lean | HIGH |
| **Vegas feature anchoring** | Full-Vegas models (v12_mae, v9_mae) underperform low/no-Vegas variants (v9_low_vegas, v12_noveg) | MEDIUM |
| **Q43 quantile compounding** | Q43 predicts 43rd percentile, already below mean, on top of MAE's mean-regression bias → catastrophic double-UNDER | HIGH |
| **Market regime shifts** | Post All-Star Break: trade deadline changes, scoring pattern shifts, Vegas line recalibration | MEDIUM |

### 2.2 What's Working

Despite the crisis, there IS signal in the system:

1. **v12_noveg variants UNDER at edge 5+** — 66-71% HR. The no-Vegas V12 feature set (50 features) combined with quantile regression finds genuine UNDER opportunities.
2. **v9_low_vegas UNDER at edge 5+** — 62.5% HR. Reducing Vegas weight lets the model form independent opinions that are additive to the market.
3. **v12 champion OVER at edge 3+** — 60.0% (10 picks in 14 days). When the model does predict OVER, it's often right. But OVER picks are extremely rare.
4. **Role player predictions** — 60.9% HR at edge 3+ (vs 48.6% for starters, 50% for stars). The model is best at predicting bench/role players.

### 2.3 What's Definitively Dead

| Approach | Status | Evidence |
|----------|--------|----------|
| Q43 quantile with Vegas | DEAD | 20.0% HR at edge 5+ (10 picks). Catastrophic UNDER compounding. |
| V9 MAE UNDER | DEAD | 34.1% HR at edge 5+ (85 picks). Huge sample, consistent failure. |
| Two-stage pipeline | DEAD | Prior experiments, documented in CLAUDE.md. |
| Edge Classifier (Model 2) | DEAD | AUC < 0.50, no predictive value. |
| Recency weighting | DEAD | 33.3% HR in prior test. |
| Lines-only training | DEAD | 20% HR in prior test. |

---

## Part 3: Evaluation Framework — 7 Investigations

### Investigation 1: Best Bets Source Attribution (2 hours)

**Question:** Which model families are sourcing the most profitable best bets picks, and at what edge thresholds?

**Method:**
```sql
-- Join signal_best_bets_picks with prediction_accuracy to trace
-- which model's prediction was selected for each best bet pick
SELECT sbp.system_id, sbp.recommendation,
       COUNT(*) as picks,
       COUNTIF(sbp.prediction_correct) as wins,
       AVG(sbp.edge) as avg_edge,
       -- Check if the model contributed the winning prediction
       COUNTIF(sbp.prediction_correct AND sbp.edge >= 5) as high_edge_wins
FROM signal_best_bets_picks sbp
WHERE game_date >= '2026-01-01'
GROUP BY 1, 2
ORDER BY wins DESC
```

Also run the counterfactual: if we had used ONLY the top 3 families (v12_noveg_q45, v12_noveg_q43, v9_low_vegas), what would best bets performance look like?

**Success criteria:** Identify which 2-3 model families should be prioritized for retraining.

### Investigation 2: Model Decay Timeline (1 hour)

**Question:** Exactly when does each model family cross from profitable to unprofitable? Is there a consistent "shelf life"?

**Method:**
```sql
-- 7-day rolling HR by family, starting from each model's training end date
SELECT family, days_since_training, rolling_7d_hr, rolling_7d_n
-- Calculate days_since_training from training end date in system_id
-- Chart the decay curve per family
```

**Expected finding:** Confirm ~21-day shelf life hypothesis.
**Action if confirmed:** Set retrain cadence to 14 days (with 7-day buffer).

### Investigation 3: Direction Bias Deep Dive (2 hours)

**Question:** Is the UNDER bias getting worse over time? Does it correlate with specific game conditions?

**Method:**
- Track weekly `avg(predicted - line_value)` per family
- Segment by: home/away, back-to-back, player tier, game total
- Identify if UNDER bias is worse for specific game contexts

**Expected finding:** UNDER bias worsens with training staleness as the model's "memory" of player scoring rates becomes outdated.

**Actionable output:** Define which game contexts to avoid (or require higher edge) for UNDER bets.

### Investigation 4: Feature Importance Drift (3 hours)

**Question:** Are the most important features shifting? Is the model's feature reliance changing in ways that explain the decline?

**Method:**
```python
# Compare feature importance of current production model vs freshly retrained
# Load production model, extract feature_importances_
# Load fresh retrain candidate, extract feature_importances_
# Diff the top 10 features by importance
```

Also examine:
- Do winning predictions have systematically different feature values than losing ones?
- Are there features with high importance but degraded quality?

**Expected finding:** Vegas features dominate importance in full-Vegas models, causing them to track Vegas too closely rather than finding independent signal.

### Investigation 5: Architecture Decision — Vegas Feature Role (2 hours)

**Question:** Should we move entirely to no-Vegas or low-Vegas architectures?

**Evidence gathered so far:**

| Architecture | Best Edge 5+ HR | Best Family | Rationale |
|-------------|-----------------|-------------|-----------|
| No Vegas (50f) | 71.4% | v12_noveg_q45 UNDER | Model forms independent opinion |
| Low Vegas (33f, 0.25x) | 62.5% | v9_low_vegas UNDER | Slight Vegas guidance without anchoring |
| Full Vegas (54f) | 50.0% | v12_mae UNDER | Model becomes worse copy of Vegas |
| Full Vegas + Q43 | 20.0% | v12_vegas_q43 UNDER | Catastrophic double-UNDER |

**Experiment design:**
1. Retrain v12_noveg_mae through Feb 24 (MAE loss, 50f) → compare to current v12_mae
2. Retrain v12_noveg with Q55 quantile (50f, predict 55th percentile) → counteract UNDER bias
3. Retrain v9_low_vegas with fresh data → confirm it holds up

### Investigation 6: Quantile Model Strategy (2 hours)

**Question:** Q43 is a disaster, but higher quantiles (Q55, Q57, Q60) could counteract the structural UNDER bias. What quantile targets should we test?

**Rationale:**
- MAE predicts the conditional mean → naturally biased below Vegas for "hot" players
- Q43 predicts the 43rd percentile → even MORE below mean → catastrophic UNDER compounding
- Q55-Q60 would predict ABOVE the mean → generates more OVER predictions with genuine edge

**Experiment design:**
1. Train v12_noveg_q55 (50f, alpha=0.55)
2. Train v12_noveg_q57 (50f, alpha=0.57)
3. Compare OVER/UNDER split, edge distribution, and directional HR

**Success criteria:** Q55+ generates >= 30% OVER predictions (vs current ~10-20%) with OVER HR >= 55%.

### Investigation 7: New Feature Candidates (3 hours)

**Question:** Are there untapped data sources or feature engineering opportunities?

**Candidates to evaluate:**

| Feature | Source | Hypothesis |
|---------|--------|------------|
| **Line movement direction** | odds_api | Lines moving UP = market sees OVER value → align/counter |
| **Implied team total** (already in V12) | odds_api | Verify it's being used effectively |
| **Opponent recent form** | game_summary | Is opponent getting better/worse defensively in last 5? |
| **Pace delta vs average** | team_stats | Games that will be faster/slower than expected |
| **Player minutes trend** | player_game_summary | Is coach playing the player more/less recently? |
| **Correlation with team winning** | game_summary | Players on winning teams score differently |

**Method:** Feature importance analysis on fresh retrain, plus correlation analysis of candidate features vs actual scoring outcomes.

**Constraint:** V12 already has 54 features. Feature expansion only justified if it meaningfully improves edge 3+ HR (not just MAE).

### Investigation 8: Model Feature Store Deep Dive (3 hours)

**Question:** What are each model's strengths? How do their feature stores and feature importance profiles differ? What tuning experiments should we try?

**Method:**
1. For each enabled model family, extract CatBoost `feature_importances_` from the .cbm file
2. Compare top 10 features by importance across families:
   - v9_mae (production), v9_low_vegas, v12_noveg_q55, v12_noveg_mae, v12_noveg_q43, v12_vegas_q43
3. Correlate feature importance with edge 3+ hit rate per model
4. Identify features that are high-importance in winning models but low-importance in losing models
5. Examine feature value distributions for winning vs losing predictions (per model)

**Tuning experiments to run:**
- Q57 quantile (even more OVER-leaning than Q55)
- Different `min-data-in-leaf` values (regularization)
- Different training window lengths (30, 40, 50 days)
- Category weight experiments (e.g., reduce `recent_performance` weight to avoid recency bias)

**Expected output:** A matrix of model × feature importance, annotated with each model's direction bias and hit rate. This reveals which features to emphasize/de-emphasize per quantile target.

---

## Part 4: Retrain Strategy

### Session 343 Retrain Results (Feb 25)

All four variants tested, all with eval window Feb 10-24 (15 days):

| Variant | MAE | HR 3+ | N 3+ | Vegas Bias | OVER HR | UNDER HR | Gates |
|---------|-----|-------|------|-----------|---------|----------|-------|
| **v9 low_vegas v2** (47d train, vegas=0.25) | 5.169 | **60.0%** | 45 | -0.53 | 63.6% | 58.8% | MAE, N |
| v9 low_vegas v3 (87d train, vegas=0.25) | 5.107 | 55.9% | 34 | -0.26 | 54.5% | 56.5% | HR, N |
| v9 low_vegas v4 (47d, RSM 0.5) | 5.110 | 55.3% | 47 | -0.65 | 50.0% | 56.4% | HR, N, DIR |
| **v12_noveg Q55** (47d, no vegas) | **5.024** | **60.0%** | 20 | **-0.24** | **80.0%** | 53.3% | N only |

**Key findings:**
1. **v12_noveg Q55 is the standout model** — best MAE, best calibration, generates 25% OVER picks (vs 10-20%), OVER hit rate 80%
2. **v9_low_vegas v2 (47d)** is the best v9 variant — 60.0% HR, excellent directional balance
3. **Sample size gate (N >= 50) blocks ALL models** — structural limitation of 15-day eval window
4. **RSM 0.5 hurts performance** for v9 low_vegas — don't use for this family
5. **Wider training window (87d) reduces HR** — too much old data dilutes recent signal
6. **Q55 successfully counteracts UNDER bias** — vegas bias -0.24 vs -0.53 for standard MAE

**Saved models (not deployed):**
- `models/catboost_v9_33f_wt_train20251225-20260209_20260225_100515.cbm` (v2, best v9)
- `models/catboost_v9_50f_noveg_train20251225-20260209_20260225_100720.cbm` (Q55, best overall)

### Phase A: Immediate Retrains (This Week)

| Priority | Family | Feature Set | Loss | Training Window | Vegas Config | Why |
|----------|--------|------------|------|-----------------|-------------|-----|
| 1 | **v9_low_vegas** | v9 (33f) | MAE | Dec 25 - Feb 9 | category-weight vegas=0.25 | Best v9, 60% HR, needs more eval data |
| 2 | **v12_noveg_q55** | v12_noveg (50f) | Quantile (0.55) | Dec 25 - Feb 9 | No vegas | Best overall, 80% OVER HR, most balanced |
| 3 | **v12_noveg_mae** | v12_noveg (50f) | MAE | Dec 25 - Feb 9 | No vegas | Strong architecture, compare to Q55 |
| 4 | **v12_noveg_q57** | v12_noveg (50f) | Quantile (0.57) | Dec 25 - Feb 9 | No vegas | Stronger OVER lean experiment |

### Phase B: If Phase A Shows Promise (Next Week)

| Priority | Family | Feature Set | Loss | Why |
|----------|--------|------------|------|-----|
| 5 | v9_mae | v9 (33f) | MAE | Production champion refresh |
| 6 | v12_mae | v12 (54f) | MAE | Full-feature refresh for comparison |
| 7 | v12_noveg_q45 | v12_noveg (50f) | Q45 | Currently best performer but 31 days stale |

### Phase C: Decommission (Immediately)

| Family | Action | Reason |
|--------|--------|--------|
| v12_vegas_q43 | **DECOMMISSION** | 20.0% HR at edge 5+, structural flaw |
| v12_vegas_q45 | **DECOMMISSION** | Insufficient data but same Vegas+quantile problem |
| v9_q43 | **EVALUATE** | 41.7% HR, may not survive fresh retrain either |
| All "other" zombie models | **DONE** (Session 343) | Already decommissioned |

---

## Part 5: Architecture Decisions to Make

### Decision 1: Default Architecture

**Options:**
- A) Keep full-Vegas as default, low-Vegas as supplement
- B) **Move to no-Vegas (v12_noveg) as default, keep v9_low_vegas as diversity** (RECOMMENDED)
- C) Remove Vegas features entirely from all models

**Evidence for B:** The top 3 performing families all have reduced/zero Vegas features. Vegas features make the model a worse copy of the market. Independent signal + Vegas as a post-prediction filter is more valuable.

### Decision 2: Quantile Strategy

**Options:**
- A) Keep Q43/Q45 (predict below mean)
- B) **Shift to Q55/Q57 (predict above mean)** (RECOMMENDED for experimentation)
- C) Drop all quantile models, focus only on MAE

**Evidence for B:** Current quantile targets (Q43, Q45) compound the existing UNDER bias. Higher quantile targets would generate more OVER predictions, which historically win at 60-67% when they exist.

### Decision 3: Retrain Cadence

**Options:**
- A) Keep 7-day cadence (too aggressive, models need more training data)
- B) **Move to 14-day cadence with 42-day rolling window** (RECOMMENDED)
- C) Move to 21-day cadence (risk: models may decay before next retrain)

**Evidence for B:** Models show ~21-day effective shelf life. 14-day retrain gives 7-day buffer before expected decline.

### Decision 4: Best Bets Volume

**Options:**
- A) Keep current thresholds (edge 5+, aggressive blocking) — accept 1-2 picks/day
- B) **Add a second tier at edge 4+ with stricter signal requirements** — target 3-5 picks/day
- C) Lower edge threshold to 4+ across the board (risky)

**Evidence for B:** At edge 4+, v12_noveg and v9_low_vegas families maintain >55% HR. Adding signal requirements (model health = HEALTHY/WATCH, direction affinity = OK) could increase volume safely.

---

## Part 6: Execution Timeline

### Week 1 (Feb 25-28): Stabilize + Quick Wins

- [x] Deploy zombie decommission (Session 343)
- [x] Activate direction affinity blocking (Session 343)
- [x] Retrain v9_low_vegas with correct feature weights (4 variants tested)
- [x] Train v12_noveg_q55 (new quantile experiment — best model trained)
- [x] Register both shadow models in model_registry
- [x] Run Investigation 1 (best bets source attribution) — **Session 345**
- [x] Add export freshness monitor to daily-health-check CF — **Session 345**
- [x] Fresh training window experiment (Q55+trend_wt on Jan 5 - Feb 19) — **Session 345**
- [ ] **Verify Feb 26 predictions show ~9 system_ids** (zombie cleanup + shadows active)

### Week 2 (Mar 2-6): Model Deep Dive + Evaluate

- [x] **Study all models' feature stores**: Session 344 completed. See Investigation 4+8 results below.
- [ ] **Grade 4 shadow models (need 3-5 days from Feb 26)**:
  - `catboost_v12_noveg_q55_train1225_0209` (Q55 baseline)
  - `catboost_v12_noveg_q55_tw_train1225_0209` (Q55+trend_wt — best offline)
  - `catboost_v12_noveg_q57_train1225_0209` (Q57 — UNDER specialist)
  - `catboost_v9_low_vegas_train1225_0209` (v9_low_vegas fresh)
- [ ] Run Investigations 2-3 (decay timeline, direction bias)
- [x] **Experiment with new tuning**: Session 344 — tested Q57, Q60, min-data-in-leaf, category weights. See results below.
- [x] Decommission v12_vegas_q43 family permanently (Session 344)
- [ ] **Evaluate v12_mae UNDER model-direction affinity blocking** (53.3% HR, drags best bets from 71.4% → 68.9%)
- [ ] **Evaluate Stars UNDER negative filter** (0% HR on fresh window experiment, N=5 — need more data)

### Week 3 (Mar 9-13): Decide + Scale

- [ ] Run Investigation 5-6 (architecture decision, quantile strategy)
- [ ] Make Decision 1 (default architecture — noveg vs full-vegas)
- [ ] Make Decision 2 (quantile strategy — Q55/Q57 vs MAE)
- [ ] **Identify new feature candidates** from feature importance analysis
- [ ] Retrain Phase B families if warranted
- [ ] Update retrain cadence to 14 days

### Week 4 (Mar 16-20): Optimize

- [ ] Run Investigation 7 (new feature candidates)
- [ ] Implement any architecture changes
- [ ] Full system performance review
- [ ] Update CLAUDE.md with new model guidelines

---

## Part 7: Success Metrics

| Metric | Current | Target (30 days) | Target (60 days) |
|--------|---------|-------------------|-------------------|
| Edge 3+ HR (best model) | 53.7% | 58%+ | 60%+ |
| Edge 5+ HR (best model) | 62.5% | 65%+ | 70%+ |
| Graded best bets per week | ~2 | 5-7 | 8-12 |
| Best bets HR | 83% (5/6) | 65%+ | 70%+ |
| Models in HEALTHY state | 0 | 2+ | 4+ |
| OVER prediction ratio | 10-20% | 25-35% | 30-40% |
| Model MAE vs Vegas MAE | +0.22 worse | Within +0.10 | Equal or better |

---

## Appendix: Key Files

| File | Purpose |
|------|---------|
| `ml/experiments/quick_retrain.py` | Retraining script with governance gates |
| `shared/config/cross_model_subsets.py` | Model family definitions |
| `ml/signals/cross_model_scorer.py` | Multi-model consensus scoring |
| `ml/signals/model_direction_affinity.py` | Direction-specific blocking |
| `ml/signals/aggregator.py` | Best bets pipeline |
| `predictions/worker/prediction_systems/catboost_monthly.py` | Runtime model loading |
| `shared/ml/feature_contract.py` | Feature definitions (33-56 features) |
| `docs/08-projects/current/model-health-diagnosis-session-342/00-DIAGNOSIS.md` | Session 342 diagnosis |

---

## Session 344 Findings: Feature Analysis + Tuning Experiments (Feb 25)

### Investigation 4+8: Feature Importance Analysis

**Extracted `feature_importances_` from all 8 enabled model .cbm files.**

#### Core Finding: Vegas Features Are the #1 Differentiator

| Feature | Winners Avg | Losers Avg | Diff | Implication |
|---------|------------|------------|------|-------------|
| `vegas_points_line` | 2.7% | **23.9%** | -21.2 | Losers anchor to Vegas |
| `points_avg_season` | **23.1%** | 8.7% | +14.4 | Winners use player stats |
| `vegas_opening_line` | 1.2% | **10.0%** | -8.9 | Double Vegas anchor trap |
| `points_avg_last_10` | **14.0%** | 6.4% | +7.6 | Recent form matters |
| `line_vs_season_avg` | **8.0%** | 2.0% | +6.0 | Indirect Vegas signal |
| `multi_book_line_std` | 2.5% | 1.4% | +1.1 | Market disagreement |

**Winners** (Q55, v9_low_vegas, nv_q43, nv_mae): Form independent opinions from player stats.
**Losers** (v9_mae, v12_mae, v12_vegas_q43): Cheap copies of Vegas.

#### Feature-Value/Winning Correlation (14 days, edge 3+)

| Signal | Finding | Strength |
|--------|---------|----------|
| `pts_std` (variance) | UNDER winners have HIGHER variance (6.5-7.4 vs 5.6-6.5) | STRONG |
| `recent_trend` (momentum) | UNDER winners have NEGATIVE trend (-0.5 to -0.8 vs +0.4 for losers) | STRONG |
| `multi_book_line_std` | UNDER winners: lower std (1.5-1.9 vs 3.0). OVER winners: higher std (2.1 vs 1.1) | MODERATE |
| `line_vs_season_avg` | Extreme line inflation (>6 above season) → UNDER loses | MODERATE |

### Tuning Experiments (all v12_noveg, trained Dec 25 - Feb 9, eval Feb 10-24)

| Model | MAE | HR 3+ (N) | HR 5+ (N) | OVER HR (N) | UNDER HR (N) | Status |
|-------|-----|-----------|-----------|-------------|--------------|--------|
| **Q55+trend_wt** | 5.118 | **58.6% (29)** | 66.7% (3) | 50.0% (6) | **60.9% (23)** | **SHADOW** |
| **Q57** | 5.089 | 53.9% (26) | **80.0% (5)** | 40.0% (10) | **62.5% (16)** | **SHADOW** |
| Q55 baseline | 5.069 | 47.6% (21) | 50.0% (2) | 44.4% (9) | 50.0% (12) | Weaker than expected |
| Q60 | 5.111 | 51.5% (33) | 80.0% (5) | 50.0% (24) | 55.6% (9) | Too much OVER noise |
| Q55+minleaf25 | 5.000 | 50.0% (4) | N/A | N/A | 50.0% (4) | Kills feature diversity |
| Q55+minleaf50 | 5.058 | 50.0% (6) | 0% (1) | N/A | 50.0% (6) | Kills feature diversity |

**Q55+trend_wt config:** `--category-weight "recent_performance=2.0,derived=1.5,matchup=0.5"` — encodes feature analysis directly.

### Decisions Made (Session 344)

1. **v12_vegas_q43 DECOMMISSIONED** — 20% HR edge 5+, confirmed catastrophic by feature analysis (vegas_points_line at 22.8% importance).
2. **Two new shadow models registered**: Q55+trend_wt and Q57.
3. **Dead ends confirmed**: min-data-in-leaf > default, Q60, Q43 with Vegas.
4. **Optimal quantile range: Q55-Q57** — Q60 adds noise, Q43 is catastrophic.
5. **Category weights validated**: Up-weighting recent_performance (2x) and derived (1.5x) while down-weighting matchup (0.5x) improves HR by +11% at edge 3+.

### Updated Model Registry (9 enabled, Session 344)

| Model ID | Family | Status | Training | Notes |
|----------|--------|--------|----------|-------|
| catboost_v9_33f_train... | v9_mae | PRODUCTION | Jan 6 - Feb 5 | Champion |
| catboost_v9_low_vegas_train0106_0205 | v9_low_vegas | active | Jan 6 - Feb 5 | |
| catboost_v9_low_vegas_train1225_0209 | v9_low_vegas | shadow | Dec 25 - Feb 9 | Session 343 |
| catboost_v12_mae_train0104_0215 | v12_mae | active | Jan 4 - Feb 15 | |
| catboost_v12_noveg_mae_train0104_0215 | v12_noveg_mae | active | Jan 4 - Feb 15 | |
| catboost_v12_noveg_q43_train0104_0215 | v12_noveg_q43 | active | Jan 4 - Feb 15 | |
| catboost_v12_noveg_q55_train1225_0209 | v12_noveg_q55 | shadow | Dec 25 - Feb 9 | Session 343 |
| **catboost_v12_noveg_q55_tw_train1225_0209** | **v12_noveg_q55_tw** | **shadow** | Dec 25 - Feb 9 | **Session 344 — best overall** |
| **catboost_v12_noveg_q57_train1225_0209** | **v12_noveg_q57** | **shadow** | Dec 25 - Feb 9 | **Session 344 — UNDER specialist** |

---

## Session 345 Findings: Best Bets Attribution + Fresh Window Experiment (Feb 25)

### Investigation 1: Best Bets Source Attribution (COMPLETED)

Joined `signal_best_bets_picks` with `prediction_accuracy` for Jan 1 - Feb 25.

**Overall: 68.9% HR on 106 graded picks.**

| Family | Direction | Graded | Wins | HR | Avg Edge |
|--------|-----------|--------|------|----|----------|
| **v12_mae OVER** | OVER | 20 | 18 | **90.0%** | 8.0 |
| **v9_mae UNDER** | UNDER | 22 | 15 | **68.2%** | 5.9 |
| v9_mae OVER | OVER | 43 | 27 | 62.8% | 7.5 |
| v12_mae UNDER | UNDER | 15 | 8 | **53.3%** | 4.5 |
| v12_q45 UNDER | UNDER | 2 | 2 | 100.0% | 0.1 |
| v9_low_vegas | mixed | 2 | 2 | 100.0% | 5.7 |

**Counterfactual scenarios:**

| Scenario | Graded | Wins | HR |
|----------|--------|------|-----|
| ALL families | 106 | 73 | 68.9% |
| **Exclude v12_mae UNDER** | **91** | **65** | **71.4%** |
| v12_mae OVER only | 20 | 18 | 90.0% |

**Key insights:**
1. **v12_mae OVER is the crown jewel** — 90.0% HR on 20 picks
2. **v12_mae UNDER is the only family+direction below breakeven** — 53.3% drags overall best bets
3. **v9_low_vegas and noveg variants barely appear** — recently activated, not enough data yet
4. **Excluding v12_mae UNDER would boost HR from 68.9% → 71.4%**

**Action items:**
- [ ] Evaluate adding v12_mae UNDER to model-direction affinity blocking (wait for shadow models to provide alternative UNDER picks first)
- [ ] Track which families source best bets once shadows are active (expected Mar 1+)

### Fresh Training Window Experiment: Q55+trend_wt on Jan 5 - Feb 19

Tested if Q55+trend_wt recipe holds on a different training window.

| Metric | Original (Dec 25 - Feb 9) | Fresh (Jan 5 - Feb 19) |
|--------|---------------------------|------------------------|
| HR edge 3+ | **58.6%** (N=29) | 48.0% (N=25) |
| HR edge 5+ | 66.7% (N=3) | **66.7%** (N=9) |
| OVER HR | 50.0% (N=6) | **71.4%** (N=7) |
| UNDER HR | **60.9%** (N=23) | 38.9% (N=18) |
| Stars HR | N/A | 0% (N=5) |

**Conclusions:**
1. **Edge 5+ is stable at 66.7% across both windows** — genuine signal
2. **OVER improved** (71.4%) — recipe generates good OVER picks
3. **UNDER collapsed** (38.9%) — Stars UNDER = 0% is the culprit
4. **Recipe is partially window-sensitive** — needs guardrails for Stars UNDER
5. **Role players remain strong** (66.7% HR) — "role player edge" confirmed

**Dead end confirmed:** Q55+trend_wt on Jan 5 - Feb 19 → gates FAILED. Model NOT deployed.

**Action items:**
- [ ] Consider Stars UNDER negative filter (line > 25, edge < 5 → block)
- [ ] Need more data from live shadow model runs to validate findings

### Infrastructure: Export Freshness Monitor

Added CHECK 8 to `daily-health-check` CF — monitors 10 GCS export files for staleness (12-36h thresholds). Deployed and live.

### What's Next (Prioritized Checklist)

1. **Feb 26:** Verify predictions show ~9 system_ids (zombie cleanup + shadows)
2. **Mar 1-3 (3-5 days):** Grade 4 shadow models — this is THE critical decision point
3. **After grading:** If Q55+trend_wt or Q57 outperform, consider promotion path
4. **After grading:** Evaluate v12_mae UNDER blocking (only if shadows provide replacement UNDER picks)
5. **After grading:** Evaluate Stars UNDER filter with live data (need N >= 15)
6. **Week of Mar 2:** Investigations 2-3 (decay timeline, direction bias deep dive)
7. **Week of Mar 9:** Architecture decisions (noveg default, quantile strategy, retrain cadence)
