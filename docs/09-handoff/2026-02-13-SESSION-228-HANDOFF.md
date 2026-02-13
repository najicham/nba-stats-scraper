# Session 228 Handoff — V12 Features Validated, Ready for Phase 2

**Date:** 2026-02-13
**Focus:** V12 feature implementation, Phase 0 diagnostics, Phase 1A/1B experiments
**Next Session:** Build Phase 2 Edge Classifier (Model 2)

---

## What Was Done This Session

### 1. Generated 3 Parallel Chat Prompts (from start prompt)

Created self-contained prompts for Chat A (V12 implementation), Chat B (diagnostics), Chat C (Phase 1A experiments). All 3 ran in parallel.

### 2. Chat A: V12 Feature Implementation (Complete)

- Added V12 contract to `shared/ml/feature_contract.py` (54 features, indices 39-53)
- Added `augment_v12_features()` to `ml/experiments/quick_retrain.py` (3 BQ sub-queries)
- Added `--feature-set v12` CLI support
- Smoke test passed end-to-end
- **Committed:** `fb6b50aa`

### 3. Chat B: Phase 0 Diagnostics (Complete)

Ran 6 diagnostic BQ queries. Key findings:
- **Vegas sharpness stable** (MAE 4.91→4.95) — edges still exist
- **Role OVER picks profitable** — 55.8% HR in Feb 2026 even with old model
- **Stars unpredictable** — 36.4% OVER HR, 9.6 MAE
- **UNDER bias systemic** — avg edge -0.80 to -1.03 across all periods
- **Trade deadline NOT the cause** — stable players worse than traded
- **Documented:** `docs/08-projects/current/model-improvement-analysis/20-DIAGNOSTIC-RESULTS.md`

### 4. Chat C: Phase 1A Baseline Experiments (Complete)

Ran 9 experiments (Vegas-free, MAE loss, V9 features). Key findings:
- Feb 2025: **69.35%** edge 3+ HR (architecture validated)
- Jan 2026: **64.13%** (strong)
- Feb 2026: **48.89%** (below breakeven — needs V12 features)
- Training window, loss function, feature pruning — none help Feb 2026
- **Documented:** `docs/08-projects/current/model-improvement-analysis/21-PHASE1A-RESULTS.md`

### 5. Phase 1B: V12 Feature Experiments (Complete)

Ran 4 V12 experiments on all eval windows + 2 ablation experiments. **V12 improves every window:**

| Window | Phase 1A (V9) | Phase 1B (V12) | Delta |
|--------|--------------|----------------|-------|
| Feb 2025 | 69.35% | **72.92%** | +3.6pp |
| Dec 2025 | 50.85% | **56.58%** | +5.7pp |
| Jan 2026 | 64.13% | **78.70%** | +14.6pp |
| Feb 2026 | 48.89% | **60.00%** | +11.1pp |
| **Average** | **58.31%** | **67.05%** | **+8.7pp** |

**Key V12 features:** `line_vs_season_avg` (#3, ~10%), `deviation_from_avg_last3` (#4, ~7%), `points_avg_last_3` (4-5%), `usage_rate_last_5` (3-5%)

**Dead feature ablation:** Removing 10 zero-importance features hurts Feb 2026 (54.29% vs 60.00%). Keep full V12.

**All Phase 1 execution plan gates PASS.** Model 1 is validated.

- **Documented:** `docs/08-projects/current/model-improvement-analysis/22-PHASE1B-RESULTS.md`

---

## What to Do Next Session

### Phase 2: Edge Classifier (Model 2)

**Model 1 is done.** The V12 Vegas-free points predictor works. Now build Model 2: a binary classifier that answers "given Model 1 disagrees with Vegas by X points, is this a good bet?"

#### Architecture

```
Model 1: V12 Vegas-free CatBoost (MAE loss)
  → Predicts actual points scored
  → edge = model1_prediction - vegas_line

Model 2: Edge Classifier (binary, Logloss)
  → Input: Model 1's edge + market/context features
  → Output: probability that the edge will hit
  → Only trained on rows where |edge| >= 2

Bet Selection:
  → edge >= 3 AND model2_confidence >= threshold
```

#### Model 2 Feature Set (~10 features)

```
raw_edge_size           — |model1_pred - vegas_line|
edge_direction          — OVER (+1) or UNDER (-1)
vegas_line_move         — opening to current line movement (feature 27)
line_vs_season_avg      — vegas_line - player_season_avg (already in V12)
multi_book_line_std     — std dev across sportsbooks (already in V12)
player_volatility       — points_std_last_10 (feature 3)
prop_over_streak        — from V12
prop_under_streak       — from V12
game_total_line         — scoring environment (feature 38)
player_tier             — season_avg bucket (star/mid/role/bench)
```

#### Implementation Options

**Option A: Extend quick_retrain.py** — Add `--classification` mode that:
1. Loads Model 1, generates predictions on training data
2. Computes edges: `model1_pred - vegas_line`
3. Creates binary target: `did_edge_hit` (1/0)
4. Trains CatBoost classifier (Logloss) on edge 2+ rows
5. Evaluates combined pipeline: Model 1 edge → Model 2 filter → bet decision

**Option B: Separate script** — `ml/experiments/edge_classifier.py` that:
1. Takes a saved Model 1 `.cbm` file as input
2. Generates backtested edges on training/eval data
3. Trains Model 2
4. Reports combined performance

**Option B is cleaner** — keeps Model 1 and Model 2 concerns separate.

#### Starting Point

Use the JAN26 V12 model (`a0c76ed0`, 78.70% HR) as the reference Model 1 for initial Model 2 development. It has the best combination of performance and sample size.

#### What the Diagnostics Tell Us About Model 2

The diagnostic findings (doc 20) directly inform Model 2's design:
- **Tier filtering:** Stars at 36.4% OVER HR, role at 55.8%. Model 2 should learn to filter by tier.
- **Directional asymmetry:** OVER picks on role/bench are profitable; UNDER picks lose across all tiers. Model 2 should learn edge_direction matters.
- **Line range matters:** High lines (>20.5) had 75% HR in V12_CLEAN_JAN26. Low lines (<12.5) had 87.2%. Model 2 can learn this.

### Also Consider

1. **Implement real `teammate_usage_available`** — Currently placeholder (0.0 everywhere). Needs dedicated query joining injury report + usage rates. Could add signal, especially for star-teammate-out scenarios.

2. **Multi-book line std coverage** — Currently 0% for training data (odds_api data doesn't go back far enough). Only 17% for eval. May need to backfill or accept this as eval-only signal.

3. **Shadow deployment timing** — The V12 JAN26 model (78% HR) could be shadow-deployed now as a standalone improvement, even before Model 2. But per governance, needs explicit user approval.

---

## Modified Files (This Session)

### Committed (`fb6b50aa`)
```
M  shared/ml/feature_contract.py       — V12 contract, defaults, source maps
M  ml/experiments/quick_retrain.py      — augment_v12_features(), --feature-set v12
+  docs/08-projects/current/model-improvement-analysis/17-FINAL-EXECUTION-PLAN.md
+  docs/08-projects/current/model-improvement-analysis/18-TESTING-PLAN.md
+  docs/08-projects/current/model-improvement-analysis/19-V12-FEATURE-ADDITIONS-IMPLEMENTATION.md
+  docs/08-projects/current/model-improvement-analysis/20-DIAGNOSTIC-RESULTS.md
+  docs/08-projects/current/model-improvement-analysis/21-PHASE1A-RESULTS.md
+  docs/08-projects/current/model-improvement-analysis/21-WEB-CHAT-DIAGNOSTIC-BRIEFING.md
```

### Uncommitted (this session — need to commit)
```
+  docs/08-projects/current/model-improvement-analysis/22-PHASE1B-RESULTS.md
+  docs/09-handoff/2026-02-13-SESSION-228-HANDOFF.md
```

### Uncommitted (from previous sessions — unrelated)
```
M  backfill_jobs/publishing/daily_export.py
M  data_processors/precompute/ml_feature_store/feature_extractor.py
M  data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
M  data_processors/precompute/ml_feature_store/quality_scorer.py
M  data_processors/publishing/tonight_player_exporter.py
+  data_processors/publishing/trends_tonight_exporter.py
+  tests/unit/publishing/test_trends_tonight_exporter.py
+  (various docs from sessions 225-227)
```

---

## Key Documents

| Document | Path |
|----------|------|
| Phase 0 Diagnostics | `docs/08-projects/current/model-improvement-analysis/20-DIAGNOSTIC-RESULTS.md` |
| Phase 1A Results | `docs/08-projects/current/model-improvement-analysis/21-PHASE1A-RESULTS.md` |
| **Phase 1B Results** | `docs/08-projects/current/model-improvement-analysis/22-PHASE1B-RESULTS.md` |
| Execution Plan | `docs/08-projects/current/model-improvement-analysis/17-FINAL-EXECUTION-PLAN.md` |
| Testing Plan | `docs/08-projects/current/model-improvement-analysis/18-TESTING-PLAN.md` |
| V12 Feature Spec | `docs/08-projects/current/model-improvement-analysis/19-V12-FEATURE-ADDITIONS-IMPLEMENTATION.md` |

## Quick Reference

| Item | Value |
|------|-------|
| Best Model 1 | VF_V12_JAN26: 78.70% edge 3+ HR, MAE 4.81 |
| Best Feb 2026 | VF_V12_FEB26: 60.00% edge 3+ HR, MAE 4.96 |
| V12 avg improvement | +8.7pp over Phase 1A baseline |
| Top V12 features | line_vs_season_avg (~10%), deviation_from_avg_last3 (~7%) |
| Dead features | multi_book_line_std, teammate_usage_available (no training data) |
| Feature contract | `shared/ml/feature_contract.py` — V12_CONTRACT, 54 features |
| Training script | `ml/experiments/quick_retrain.py` — supports --feature-set v12 |
| Next step | Phase 2: Edge Classifier (Model 2) |

---

## Dead Ends (Do NOT Revisit)

All previous dead ends still apply, plus:
- **Huber loss** — Catastrophic single-feature dominance (75.2% on points_avg_season)
- **180-day training window** — Identical results to 90-day for Vegas-free model
- **Season-to-date training** — Worse than 90-day (more over-indexing on season avg)
- **Dead feature pruning** — Hurts Feb 2026 from 60% to 54%. Keep full V12.
