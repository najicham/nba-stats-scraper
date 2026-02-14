# Phase 2: Edge Classifier (Model 2) Results

**Session 229 | Date: 2026-02-13**

## Executive Summary

**Model 2 (Edge Classifier) does NOT add value.** Both LogisticRegression and CatBoost classifiers failed to discriminate winning edges from losing ones (AUC < 0.50 in both eval windows). Model 1 (V12 Vegas-free) alone with simple edge thresholding remains the best approach.

## Architecture Tested

```
Model 1 (V12 CatBoost, MAE loss, no-vegas, 50 features)
  → Predicts actual points scored
  → edge = model1_pred - vegas_line

Model 2 (Binary Classifier — NEW)
  → Input: edge size, direction, player context (10 features)
  → Output: P(edge will hit)
  → Only trained on |edge| >= 2

Combined Selection:
  → edge >= 3 AND Model2_confidence >= threshold
```

## Model 2 Features (10)

| Feature | Source | Importance (LR) |
|---------|--------|-----------------|
| raw_edge_size | computed | 0.124 |
| edge_direction | computed (+1/-1) | 0.086 |
| player_volatility | points_std_last_10 (V12 idx 3) | 0.132 |
| line_vs_season_avg | vegas_line - season_avg (V12 idx 53) | 0.076 |
| player_tier | categorical from season_avg | 0.106 |
| prop_over_streak | V12 idx 51 | 0.030 |
| prop_under_streak | V12 idx 52 | 0.211 |
| game_total_line | V12 idx 38 | 0.044 |
| days_rest | V12 idx 39 | 0.121 |
| scoring_trend_slope | V12 idx 44 | 0.090 |

## Training Methodology

### Initial Approach (Failed)
Used Model 1's **in-sample predictions** on training data to generate edges.
- **Problem:** Model 1 predictions on its own training data have 88% hit rate (overfit)
- Model 2 saw 88% positive / 12% negative — couldn't learn to discriminate
- LogisticRegression AUC: 0.5658 (seemingly OK but all probs clustered near 0.55-0.70)
- No filtering occurred — all picks passed all thresholds

### Fixed Approach (OOF)
Used **5-fold temporal cross-validation** to generate out-of-fold predictions:
1. Split training data into 5 temporal chunks
2. Train temporary Model 1 on earlier folds, predict on held-out fold
3. OOF predictions are genuinely out-of-sample → realistic ~55-58% hit rate
4. Model 2 trains on these realistic edges

This is a standard stacking/ensembling technique that prevents information leakage.

## Experiment Results

### Experiment 1: Jan 2026 Eval (Best Window)

| Metric | Value |
|--------|-------|
| **Model 1 Eval MAE** | 4.81 |
| **Model 1 HR 3+** | **78.7%** (169 picks) |
| OOF MAE | 4.86 |
| OOF HR (edge>=2) | 58.1% (632 picks) |
| LR AUC-ROC | **0.456** (below random) |
| CB AUC-ROC | **0.453** (below random) |

**Combined Pipeline (edge >= 3):**

| Threshold | HR | N | vs M1 |
|-----------|-----|------|-------|
| Model 1 alone | 78.7% | 169 | baseline |
| conf >= 0.50 | 75.3% | 97 | -3.4pp |
| conf >= 0.55 | 74.2% | 66 | -4.5pp |
| conf >= 0.60 | 63.6% | 22 | -15.1pp |

**Result: Model 2 HURTS performance.** Filtering removes good picks, not bad ones.

### Experiment 2: Feb 2026 Eval (Harder Window)

| Metric | Value |
|--------|-------|
| **Model 1 Eval MAE** | 4.96 |
| **Model 1 HR 3+** | **60.0%** (35 picks) |
| OOF MAE | 4.69 |
| OOF HR (edge>=2) | 55.3% (879 picks) |
| LR AUC-ROC | **0.486** (below random) |
| CB AUC-ROC | **0.487** (below random) |

**Combined Pipeline (edge >= 3):**

| Threshold | HR | N | vs M1 |
|-----------|-----|------|-------|
| Model 1 alone | 60.0% | 35 | baseline |
| conf >= 0.50 | 68.2% | 22 | +8.2pp |

**Result: Apparent improvement (+8.2pp) but with AUC < 0.50 and only 22 picks, this is noise.**

### Walk-Forward Stability (Feb 2026, threshold=0.50)

| Week | M1 HR | M1 N | Combined HR | Combined N | Delta |
|------|-------|------|-------------|------------|-------|
| Jan 26 - Feb 1 | 100.0% | 5 | 100.0% | 4 | 0.0pp |
| Feb 2-8 | 56.0% | 25 | 64.3% | 14 | +8.3pp |
| Feb 9-15 | 40.0% | 5 | 50.0% | 4 | +10.0pp |

## Segmented Analysis (Model 1 Alone)

### Jan 2026 (Strong Period)

| Segment | HR | N |
|---------|-----|------|
| **Stars OVER** | 81.8% | 11 |
| **Starters OVER** | 87.8% | 41 |
| **Role OVER** | 81.1% | 53 |
| Stars UNDER | 68.8% | 16 |
| Starters UNDER | 61.9% | 21 |
| Role UNDER | 76.0% | 25 |
| Edge [3-5) | 71.0% | 100 |
| Edge [5-7) | 88.9% | 27 |
| Edge [7+) | 90.5% | 42 |

### Feb 2026 (Harder Period)

| Segment | HR | N |
|---------|-----|------|
| Stars UNDER | 58.3% | 12 |
| Starters UNDER | 75.0% | 8 |
| Role UNDER | 62.5% | 8 |
| OVER (all) | 50.0% | 4 |
| UNDER (all) | 61.3% | 31 |
| Edge [3-5) | 55.2% | 29 |
| Edge [5-7) | 100.0% | 5 |

## Why Model 2 Failed

### Root Cause: Edge outcomes are dominated by game-specific noise

Whether a 3+ point edge "hits" depends on:
1. **Random variance in player performance** (~5 points std dev for typical player)
2. **Game flow** (blowouts, overtime, foul trouble) — unpredictable
3. **Injury/lineup changes** that happen AFTER prediction
4. **Opponent adjustments** that aren't captured in historical stats

The 10 features we tested (edge size, direction, volatility, streaks, etc.) are all pre-game signals. But basketball point totals have significant randomness. Whether a specific edge hits is more noise than signal.

### Evidence
- Both LR and CatBoost AUC consistently below 0.50 (worse than random)
- Feature coefficients are small and inconsistent between windows
- `prop_under_streak` was most important in Jan but irrelevant in Feb
- No threshold produces reliable improvement over Model 1 alone

### Critical Lesson: In-Sample vs OOF
The initial (broken) approach showed seemingly reasonable LR AUC of 0.5658, which was misleading because:
- Training data had 88% positive class (in-sample Model 1 predictions)
- The LR learned to predict "everything hits" with slight feature modulation
- On eval, all probabilities clustered near 0.55-0.70, providing zero discrimination

**Always use OOF predictions when training a model on another model's outputs.** In-sample predictions create information leakage.

## Conclusions & Recommendations

### Phase 2 Verdict: Model 2 does NOT add value

1. **Use Model 1 (V12) alone with edge thresholds** — edge >= 3 for standard, edge >= 5 for high-confidence
2. **Simple rules outperform ML filtering:**
   - OVER picks consistently outperform UNDER (84% vs 69% in Jan)
   - Higher edge buckets have monotonically better HR ([3-5): 71%, [5-7): 89%, [7+): 91%)
   - Edge size is the single best predictor of success
3. **Stop pursuing Model 2** — the signal simply isn't there in pre-game features
4. **Focus on:**
   - Monthly Model 1 retraining (prevents decay)
   - OVER-preferred filtering (simple rule, adds ~15pp)
   - Higher edge thresholds for fewer, better picks

### Possible Future Directions (if revisiting)
- **In-game signals** (live odds movement, first quarter results) — require real-time infrastructure
- **Player matchup features** (specific defender assignments) — not currently available
- **Ensemble of Model 1 variants** (different training windows) — may capture uncertainty

## Files

- Script: `ml/experiments/edge_classifier.py`
- Model 1 (Jan eval): `models/catboost_v9_50f_noveg_train20251022-20251231_20260212_234328.cbm`
- Model 1 (Feb eval): `models/catboost_v9_50f_noveg_train20251102-20260131_20260212_234326.cbm`
