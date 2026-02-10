# The Retrain Paradox: Why Better Models Don't Beat the Spread

**Date:** 2026-02-09 (Session 179)
**Status:** Research & Strategy Document

---

## The Problem

When we retrain CatBoost V9 with more recent data, the model gets **more accurate** (lower MAE, higher overall hit rate) but generates **fewer actionable picks** (almost no edge 3+ predictions). This makes it useless for betting despite being a "better" model.

### Evidence

| Model | Training End | MAE | Overall HR | Edge 3+ Picks | Edge 3+ HR |
|-------|-------------|-----|-----------|---------------|------------|
| Production (champion) | Jan 8 | 5.14 | 54.5% | Hundreds | 63.7% |
| V9_CLEAN_TUNED_FEB | Jan 31 | 4.98 | 53.7% | 4 of 269 | 0.0% |
| V9_CLEAN_DEFAULT_FEB | Jan 31 | 4.95 | **60.0%** | 6 of 269 | 33.3% |

The retrained model (Jan 31) is more accurate overall but generates **4-6 edge 3+ picks** vs the production model's hundreds. The production model's "staleness" creates natural divergence from current Vegas lines, which is where our betting edge comes from.

---

## Why Vegas_Points_Line Is the #1 Feature

### It's By Design, Not a Bug

`vegas_points_line` consistently accounts for **29-36% of feature importance** across all V9 experiments. This was an intentional design choice when V8/V9 was built (Sessions 7-8).

**Feature importance (consistent across all experiments):**
1. `vegas_points_line` — 29-36%
2. `vegas_opening_line` — 14-17%
3. `points_avg_season` — 11-15%
4. `points_avg_last_10` — 8-10%
5. `points_avg_last_5` — 3-6%

Vegas features (#1 and #2) together account for **43-53% of the model's decision-making.**

### Why This Creates the Paradox

The model is essentially learning: `prediction ≈ vegas_line + small_adjustments`

When the model is "stale" (trained on older data), its small adjustments diverge from current Vegas because the market has shifted. This divergence = edge.

When the model is "current" (retrained on recent data), it learns the current market's patterns perfectly — and its predictions track Vegas so closely that the adjustments are near-zero. No divergence = no edge.

### The Training Objective Mismatch

CatBoost minimizes MAE (mean absolute error) against **actual points scored**. This rewards:
- Predicting close to reality (good for accuracy)
- Learning that Vegas is already close to reality (copies Vegas)
- NOT diverging from Vegas (divergence increases MAE)

**The model is optimized for accuracy, not profitability.** These are fundamentally different objectives.

---

## Current Experiment Infrastructure

### What We Track (Comprehensive)

Every experiment is registered in `nba_predictions.ml_experiments` (47 experiments to date) with:

| Category | Fields Tracked |
|----------|---------------|
| **Identity** | experiment_id, name, hypothesis, type, tags |
| **Config** | train_days, features (count), hyperparameters (depth/l2/lr/iterations), line_source, recency_weight, tuned (bool), tuned_params |
| **Dates** | train_period (start/end/samples), eval_period (start/end/samples) |
| **Results** | MAE, hit_rate_all, hit_rate_edge_3+/5+, bet counts, pred_vs_vegas_bias, tier_bias (per tier), directional_balance (over/under), feature_importance (all 33), walkforward (per-week), all_gates_passed, model_sha256 |
| **Metadata** | model_path, git_commit, parent_experiment_id, status, timestamps |

### What `/model-experiment` Skill Supports Today

| Feature | Supported | CLI Flag |
|---------|-----------|----------|
| Custom date ranges | Yes | `--train-start/end`, `--eval-start/end` |
| Hyperparameter tuning | Yes | `--tune` (18-combo grid search) |
| Recency weighting | Yes | `--recency-weight DAYS` |
| Walk-forward validation | Yes | `--walkforward` |
| Production line evaluation | Yes | `--use-production-lines` |
| Line source selection | Yes | `--line-source draftkings/bettingpros/fanduel` |
| Date overlap guard | Automatic | Blocks contaminated experiments |
| Duplicate detection | Automatic | `--force` to override |
| Feature exclusion | **No** | Not in CLI |
| Residual target (pred - vegas) | **No** | Not in CLI |
| Custom loss functions | **No** | Not in CLI |
| Two-stage pipelines | **No** | Not in CLI |

### What Exists in Archive (Not Integrated)

Code exists in `ml/archive/experiments/bias_fix_experiments.py` for:

1. **Residual modeling** — target = `actual_points - vegas_line`
2. **Quantile regression** — predict 55th percentile (upward bias correction)
3. **Tier-based sample weighting** — weight star performances 3x higher
4. **Post-hoc calibration** — tier-specific correction factors

These were built in Sessions 107-108 but never integrated into `quick_retrain.py`.

---

## Strategic Approaches to Beat the Spread

### Approach 1: Feature Exclusion (Remove Vegas Dependency)

**Concept:** Train without vegas features (25-28) so the model develops its own scoring predictions independent of the market.

**How:** Remove `vegas_points_line`, `vegas_opening_line`, `vegas_line_move`, `has_vegas_line` from training features (indices 25-28). Train on the remaining 29 features.

**Expected result:**
- Higher MAE (model loses its best anchor)
- More divergence from Vegas (model doesn't know what Vegas thinks)
- Potentially more edge 3+ picks
- Risk: predictions may be worse overall

**Implementation effort:** Medium — modify feature list in `quick_retrain.py`

**Experiment name:** `V9_NO_VEGAS`

### Approach 2: Residual Modeling (Predict Where Vegas Is Wrong)

**Concept:** Instead of predicting `actual_points`, predict `actual_points - vegas_line`. The model only needs to learn systematic Vegas errors.

**How:**
```
target = actual_points - vegas_line
prediction = vegas_line + model.predict(features)
edge = |model.predict(features)|  # How wrong the model thinks Vegas is
```

**Expected result:**
- Model focuses on where Vegas is wrong, not on predicting raw scores
- Natural edge generation (any non-zero prediction = divergence from Vegas)
- Should produce more edge 3+ picks by design
- Vegas features may still be useful (line movement signals where market is uncertain)

**Implementation effort:** Medium — code exists in archive, needs integration

**Experiment name:** `V9_RESIDUAL`

### Approach 3: Profit-Optimized Loss Function

**Concept:** Instead of minimizing MAE, use a custom loss that rewards profitable predictions.

**How:** CatBoost supports custom objectives. Define loss that penalizes predictions close to the line (no edge) more than predictions far from the line that are wrong.

**Expected result:**
- Model optimized for edge, not accuracy
- May produce noisier predictions but more profitable ones
- Risk: harder to tune, may not converge well

**Implementation effort:** High — custom CatBoost loss function

**Experiment name:** `V9_PROFIT_LOSS`

### Approach 4: Two-Stage Pipeline

**Concept:**
- Stage 1: Model predicts player points WITHOUT vegas features (independent assessment)
- Stage 2: Compare prediction to Vegas line → the difference is the edge signal

**How:**
```
stage1_prediction = model_no_vegas.predict(non_vegas_features)  # 29 features
edge = stage1_prediction - vegas_line
recommendation = OVER if edge > threshold else UNDER
```

**Expected result:**
- Cleanly separates "how many points will they score?" from "where is Vegas wrong?"
- Edge is naturally generated as a byproduct
- Can tune the threshold for profitability
- Most philosophically sound approach

**Implementation effort:** Medium — train model on 29 features, compare at inference time

**Experiment name:** `V9_TWO_STAGE`

### Approach 5: Controlled Staleness

**Concept:** Accept that staleness creates edge. Design the retraining cadence around this.

**How:**
- Retrain monthly but hold the new model in shadow for 2-3 weeks
- The shadow period isn't just safety — it's when the model becomes profitable
- After 4 weeks, the model decays too much → swap in the next one
- Rotate models on a 4-week cycle: train → shadow (2 wk) → production (2 wk) → retire

**Expected result:**
- Predictable, stable edge generation
- No code changes needed
- Simple to manage
- Doesn't solve the fundamental issue, just manages it

**Implementation effort:** Low — operational process change only

**Experiment name:** N/A (process change)

### Approach 6: Lower Edge Threshold for Current Models

**Concept:** The retrained model has 60% overall HR (vs 54.5% baseline). If this accuracy holds at edge 1.5+ or 2+, there may be enough picks at sufficient accuracy to overcome the vig.

**How:** Analyze the retrained model's accuracy at various edge thresholds (1, 1.5, 2, 2.5, 3).

**Expected result:**
- More picks at lower thresholds
- May be profitable if accuracy at edge 2+ exceeds ~55%
- Quick to validate with existing data

**Implementation effort:** Low — query existing graded data

**Experiment name:** `V9_EDGE_THRESHOLD_ANALYSIS`

### Approach 7: Feature Weighting (Session 179 — Gray Area Exploration)

**Concept:** Instead of all-or-nothing (keep all vegas vs drop all vegas), use CatBoost's `feature_weights` to **dial down** any feature's influence during split selection. Weight 0.3 on vegas means it needs 3x the information gain to get selected, reducing it from ~30% to ~10% importance. This lets us explore the entire spectrum between full dependence and full independence for every feature.

**How:**
```bash
# Per-category weighting (9 categories available)
--category-weight "vegas=0.3,recent_performance=2.0"

# Per-feature surgical targeting
--feature-weights "vegas_points_line=0.1,vegas_opening_line=0.3"

# Combine both (individual overrides category)
--category-weight "vegas=0.3" --feature-weights "vegas_points_line=0.1"
```

**Feature categories:**
| Category | Features | Default Importance |
|----------|----------|-------------------|
| `recent_performance` | pts_avg_last_5/10/season, std, games_7d | ~25-30% |
| `composite` | fatigue, shot_zone, pace, usage | ~5-8% |
| `derived` | rest, injury, trend, min_change | ~3-5% |
| `matchup` | opp_def, opp_pace, home, b2b, playoff | ~5-8% |
| `shot_zone` | pct_paint/mid/three/ft | ~2-4% |
| `team_context` | team_pace/off_rating/win_pct | ~3-5% |
| `vegas` | vegas_line/opening/move/has_line | **~43-53%** |
| `opponent_history` | avg_vs_opp, games_vs_opp | ~2-3% |
| `minutes_efficiency` | min_avg, ppm_avg | ~3-5% |

**Expected result:**
- Smooth trade-off curve between accuracy (MAE) and independence (edge count)
- Sweet spot where model generates enough edge 3+ picks at profitable hit rates
- Data-driven answer to "how much should we rely on Vegas?"

**Implementation effort:** Low — implemented in Session 179, ready to run

**Experiment name:** `V9_WT_*` (see SKILL.md for full experiment plan)

---

## Recommended Experiment Priority

| Priority | Approach | Why |
|----------|----------|-----|
| **1** | Feature Weighting (#7) | Explores the entire spectrum, most informative, zero risk |
| **2** | Residual Modeling (#2) | Directly addresses the problem, code ported from archive |
| **3** | Two-Stage Pipeline (#4) | Cleanest separation of prediction vs edge |
| **4** | Feature Exclusion (#1) | Simplest binary test, baseline for comparison |
| **5** | Edge Threshold Analysis (#6) | Low effort, may find quick win |
| **6** | Controlled Staleness (#5) | Operational fallback if nothing else works |
| **7** | Profit-Optimized Loss (#3) | Highest effort, most uncertain |

---

## Implementation Plan

### Phase 1: Vegas Weight Sweep (Session 179 — READY NOW)

All integrated into `quick_retrain.py` with `--category-weight` and `--feature-weights`:

1. **Vegas dampening sweep** — `vegas=0.1`, `0.3`, `0.5`, `0.7` (find the sweet spot)
2. **Feature exclusion baseline** — `--no-vegas` (binary comparison point)
3. **Residual modeling** — `--residual` (predict where Vegas is wrong)
4. **Two-stage pipeline** — `--two-stage` (independent prediction → edge computation)
5. **Quantile regression** — `--quantile-alpha 0.55` (bias predictions upward)

### Phase 2: Boost + Dampen Combos

6. **Boost player + dampen vegas** — `vegas=0.3,recent_performance=2.0`
7. **Boost matchup + dampen vegas** — `vegas=0.3,matchup=2.0,derived=1.5`
8. **Surgical: dampen only vegas_points_line** — `vegas_points_line=0.1` (keep opening/move)

### Phase 3: Combined Modes

9. **Quantile + dampened vegas** — `--quantile-alpha 0.55 --category-weight "vegas=0.3"`
10. **Residual + boosted player** — `--residual --category-weight "recent_performance=2.0"`

### Phase 4: Advanced (future)

11. **Custom loss function** — CatBoost custom objective optimizing for profitability
12. **Ensemble approaches** — combine residual + weighted + standard models

See `.claude/skills/model-experiment/SKILL.md` for ready-to-paste commands for all experiments.

---

## Key Files

| Purpose | File |
|---------|------|
| Current trainer | `ml/experiments/quick_retrain.py` |
| Archive residual code | `ml/archive/experiments/bias_fix_experiments.py` |
| Feature contract | `shared/ml/feature_contract.py` |
| Experiment tracking | `schemas/bigquery/nba_predictions/ml_experiments.sql` |
| Skill definition | `.claude/skills/model-experiment/SKILL.md` |
| Hyperparameters guide | `docs/08-projects/current/retrain-infrastructure/04-HYPERPARAMETERS-AND-TUNING.md` |
