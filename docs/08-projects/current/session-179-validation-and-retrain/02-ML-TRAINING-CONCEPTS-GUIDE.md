# ML Training Concepts Guide

**Date:** 2026-02-09 (Session 179)
**Audience:** Anyone working on the NBA props prediction system
**Goal:** Understand every lever we can pull when training models

---

## Table of Contents

1. [How CatBoost Works (Quick Mental Model)](#how-catboost-works)
2. [Loss Functions: What the Model Optimizes](#loss-functions)
3. [Regularization: Preventing Overfitting](#regularization)
4. [Feature Importance & Weighting](#feature-importance--weighting)
5. [Tree Structure & Growth Policies](#tree-structure--growth-policies)
6. [Sampling: Bootstrap & Subsampling](#sampling)
7. [The Accuracy vs Profitability Problem](#the-accuracy-vs-profitability-problem)
8. [Concepts to Study Further](#concepts-to-study-further)

---

## How CatBoost Works

CatBoost is a **gradient boosted decision tree** (GBDT) algorithm. Here's the intuition:

### Decision Trees
A single decision tree asks yes/no questions about features to make predictions:
```
Is vegas_points_line > 22.5?
  Yes → Is points_avg_last_5 > 20?
    Yes → Predict 25.3
    No  → Predict 21.1
  No  → Is fatigue_score > 60?
    Yes → Predict 14.2
    No  → Predict 16.8
```

A single tree is weak. It can only ask ~6 questions (depth=6) before making a prediction.

### Boosting
Instead of one tree, we build **1000 trees in sequence**. Each tree learns from the **mistakes** of all previous trees:

1. Tree 1 makes predictions. Some are wrong.
2. Tree 2 focuses on the errors Tree 1 made.
3. Tree 3 focuses on what Trees 1+2 still get wrong.
4. ... repeat 1000 times.

The final prediction is the **sum of all trees' predictions**, each scaled by a learning rate.

### What Makes CatBoost Special
- **Ordered boosting**: Prevents a subtle form of overfitting called "target leakage"
- **Symmetric (oblivious) trees**: All branches at the same depth use the same split condition. This is extremely fast at inference and naturally regularized.
- **Native handling of categorical features**: Not relevant for us (all numeric), but CatBoost's core innovation.

---

## Loss Functions

The loss function tells the model **what to optimize**. This is the most fundamental choice.

### RMSE (Root Mean Squared Error) — Default
```
loss = sqrt(mean((predicted - actual)^2))
```
- Heavily penalizes large errors (quadratic penalty)
- Good for accuracy, bad when you have outlier games (Tatum dropping 51)
- One 20-point miss counts as much as four 10-point misses

### MAE (Mean Absolute Error)
```
loss = mean(|predicted - actual|)
```
- Treats all errors linearly — a 20-point miss is just 2x a 10-point miss
- More robust to outliers
- Predicts the **median** rather than the mean

### Huber Loss
```
loss = {
  0.5 * error^2           if |error| <= delta
  delta * |error| - 0.5 * delta^2  otherwise
}
```
- **Best of both worlds**: squared loss for normal games, linear for outliers
- `delta` parameter controls the threshold (try 5-8 for NBA points)
- Reduces influence of blowout/overtime outlier performances

### LogCosh
```
loss = mean(log(cosh(predicted - actual)))
```
- Smooth approximation of MAE
- Behaves like RMSE for small errors, MAE for large errors
- No parameter to tune — just works

### Quantile Loss
```
loss = {
  alpha * (actual - predicted)     if actual >= predicted
  (1 - alpha) * (predicted - actual)  otherwise
}
```
- `alpha = 0.5` → predict median (same as MAE)
- `alpha = 0.55` → predict 55th percentile (slight upward bias)
- Useful for testing whether a slight OVER bias improves betting

### Why This Matters for Betting
Our model minimizes MAE against **actual points scored**. But we bet against **Vegas lines**. The model is optimized for accuracy, not profitability. These are different objectives.

A model that's less accurate overall but more independent from Vegas might generate more profitable bets because it disagrees with the market more often.

---

## Regularization

Regularization prevents the model from **memorizing** the training data. A model that memorizes will perform perfectly on training data but poorly on new data (overfitting).

### L2 Regularization (l2_leaf_reg)
**Our current knob.** Penalizes leaf values (predictions) that are too large. Higher values → more conservative predictions, less overfitting.

```
Training objective = loss + lambda * sum(leaf_values^2)
```

- Default: 3
- Grid search range: 1.5, 3.0, 5.0
- Higher = more regularization = more conservative

### Depth
Number of questions each tree can ask. More depth = more complex patterns, but more overfitting risk.

- Default: 6
- Grid search: 5, 6, 7
- Deeper trees can model interactions like "star player + back-to-back + tough matchup"

### Learning Rate
How much each tree contributes to the final prediction. Lower = each tree has less influence, but you need more trees.

- Default: 0.05
- Grid search: 0.03, 0.05
- Lower + more iterations = better generalization (but slower training)

### Early Stopping
Stop adding trees when validation error stops improving. Prevents building useless trees that overfit.

- Current: stop after 50 rounds without improvement
- This is why we split training data 85/15 — the 15% is for monitoring when to stop

### Random Strength
Adds noise to the split selection process. Higher values mean the model explores more diverse tree structures instead of always picking the same "best" split.

- Default: 1
- Higher values (2-5) = more exploration, reduces dominance of a single feature
- The noise decreases as training progresses (early trees are diverse, later trees converge)

### Min Data in Leaf
Minimum number of training examples a leaf must contain. Higher = leaves represent broader patterns.

- With min_data_in_leaf=1 (default): a leaf could represent a single game
- With min_data_in_leaf=20: each leaf represents at least 20 games → more reliable predictions
- Requires `grow_policy='Depthwise'` (not available with default symmetric trees)

---

## Feature Importance & Weighting

### How CatBoost Picks Splits
At each tree level, CatBoost evaluates ALL features and ALL possible thresholds to find the split that reduces error the most (highest "information gain"). The feature with the best split wins.

When `vegas_points_line` gives the best split at many levels across many trees, it accumulates high importance. This is natural — it IS the most predictive feature.

### Feature Weights (Our New Lever)
CatBoost's `feature_weights` parameter scales the information gain score for each feature during split selection:

```
adjusted_gain = raw_gain * feature_weight
```

- Weight 1.0 (default): normal behavior
- Weight 0.3: feature needs 3.3x the information gain to be selected for a split
- Weight 2.0: feature's splits are valued 2x higher

This doesn't remove the feature from the model — it just makes it harder to get selected, forcing the model to find value in other features at some splits.

### RSM (Random Subspace Method)
Instead of considering ALL features at each split, randomly select a subset:

```
rsm = 0.6 → only 20 of 33 features available per tree level
```

At each level, there's a (1 - rsm) chance that any given feature is excluded. With rsm=0.5, there's a 50% chance `vegas_points_line` is excluded from any given split decision.

**Key insight**: With default symmetric trees, RSM applies at the **level** — all nodes at that depth see the same feature subset. With Depthwise trees, RSM applies at **each node** — much more diverse.

### Category Weights (Convenience)
Our `--category-weight` flag applies the same weight to all features in a category:

```
--category-weight "vegas=0.3" → all 4 vegas features get weight 0.3
--category-weight "recent_performance=2.0" → all 5 performance features get weight 2.0
```

---

## Tree Structure & Growth Policies

### Symmetric Tree (Default — "Oblivious Decision Tree")
```
                    [vegas > 22.5?]              Level 0 (same split for ALL nodes)
                   /                \
        [fatigue > 60?]        [fatigue > 60?]   Level 1 (same split for ALL nodes)
        /         \            /         \
     [pred]    [pred]      [pred]    [pred]       Leaves
```

Every node at the same depth uses **the exact same feature and threshold**. This means:
- Very fast inference (just follow the split conditions)
- Highly regularized (can't overfit to specific paths)
- BUT: if vegas wins at level 0, it dominates the entire tree

### Depthwise (Like XGBoost)
```
                    [vegas > 22.5?]              Level 0
                   /                \
        [fatigue > 60?]      [pts_avg > 20?]     Level 1 (DIFFERENT splits per branch)
        /         \            /         \
     [pred]    [pred]      [pred]    [pred]       Leaves
```

Each branch can use **different features** at each level. This allows:
- Vegas to dominate the left branch, player stats to dominate the right
- Different features matter for different player profiles
- Unlocks full power of RSM and min_data_in_leaf
- More expressive but needs more regularization to prevent overfitting

### Lossguide (Like LightGBM Leaf-wise)
Instead of growing level by level, grows the leaf with the **highest loss improvement** first. Can create deep but narrow trees focused on the hardest examples.

---

## Sampling

### Bootstrap (Row Sampling Across Trees)
Each tree is trained on a **weighted random sample** of the training data:

- **Bayesian** (default): Each row gets a random weight from an exponential distribution. `bagging_temperature` controls how extreme the weights are.
- **Bernoulli**: Each row is included/excluded with probability = `subsample`. Simple and effective.
- **MVS** (Minimum Variance Sampling): Rows that are hard to predict get sampled more often. Focuses learning on the cases where Vegas is wrong — exactly what we want.
- **No**: Every row has equal weight every iteration.

### Subsample (What Fraction of Data Per Tree)
```
subsample = 0.8 → each tree sees 80% of training data
```
Lower values = more diversity between trees, more regularization.

### Why Sampling Helps
If every tree sees every row, all trees tend to learn the same patterns. By randomizing which rows each tree sees, you get a more diverse ensemble where individual trees' mistakes cancel out.

---

## The Accuracy vs Profitability Problem

This is the central tension in our system.

### The Model's Objective
CatBoost minimizes `|predicted_points - actual_points|`. The optimal strategy is:
1. Notice that `vegas_points_line` is already close to `actual_points`
2. Learn small adjustments: `prediction ≈ vegas + tiny_correction`
3. Result: low MAE (accurate!) but predictions track Vegas closely (no edge)

### What We Need
We need `prediction ≠ vegas` for profitable betting. Specifically:
- `prediction > vegas + 3` → bet OVER (with confidence)
- `prediction < vegas - 3` → bet UNDER (with confidence)
- `|prediction - vegas| < 3` → no bet (no edge)

### The Levers We Have

1. **Feature weighting** (`--category-weight "vegas=0.3"`): Make it harder for the model to rely on vegas. Forces it to develop independent opinions.

2. **Feature dropout** (`--rsm 0.5`): Randomly hide vegas from the model at some splits. Different trees learn to predict without it.

3. **Residual modeling** (`--residual`): Change the target to `actual - vegas` so the model explicitly learns Vegas errors. Any non-zero prediction = edge.

4. **Two-stage** (`--two-stage`): Remove vegas entirely from training. The model predicts points independently. Edge = model opinion - Vegas opinion.

5. **Loss function** (`--loss-function "Huber:delta=5"`): Make the model less sensitive to outlier games that inflate MAE and reward Vegas-tracking.

6. **Quantile regression** (`--quantile-alpha 0.55`): Bias predictions slightly upward to generate more OVER signals.

7. **Tree diversity** (`--grow-policy Depthwise --rsm 0.6 --random-strength 3`): Force the model to build diverse trees that find signal in different features.

### The Trade-off
More independence from Vegas → more edge 3+ picks → potentially more profit
More independence from Vegas → higher MAE → less accurate overall

We're looking for the **sweet spot**: enough independence to generate profitable picks, not so much that predictions are garbage.

---

## Concepts to Study Further

### Core ML Concepts
1. **Bias-Variance Trade-off**: Why complex models overfit and simple models underfit. Our depth/regularization choices are all about this trade-off.
   - *Search:* "bias variance trade-off gradient boosting"

2. **Cross-Validation**: How to reliably estimate model performance. Our walk-forward validation is a time-series version of this.
   - *Search:* "time series cross validation walk forward"

3. **Gradient Boosting**: The mathematical framework behind CatBoost, XGBoost, LightGBM. Understanding gradients helps you understand why loss functions matter.
   - *Search:* "gradient boosting explained simply"

### Betting-Specific ML
4. **Kelly Criterion**: How to size bets based on model confidence. Currently we bet flat, but Kelly-based sizing could improve ROI.
   - *Search:* "Kelly criterion sports betting"

5. **Calibration**: Ensuring that when the model says "70% chance of OVER", it actually hits 70% of the time. Our governance gates are a crude version of this.
   - *Search:* "probability calibration machine learning"

6. **Closing Line Value (CLV)**: The gold standard in sports betting ML. If your model's predictions consistently beat the closing line, you have real edge.
   - *Search:* "closing line value sports betting"

### CatBoost Specific
7. **Ordered Boosting**: CatBoost's key innovation. Understanding this explains why CatBoost handles small datasets well.
   - *Read:* [CatBoost paper (NeurIPS 2018)](https://arxiv.org/abs/1706.09516)

8. **Symmetric vs Asymmetric Trees**: Why CatBoost defaults to oblivious trees and when to switch to Depthwise.
   - *Search:* "catboost oblivious trees vs depthwise"

9. **Feature Interactions**: How trees capture interactions between features (e.g., "star player on back-to-back against good defense"). Depth controls how many features can interact.
   - *Search:* "feature interactions decision trees"

### Advanced Topics
10. **Ensemble Methods**: Combining multiple models (e.g., one with vegas, one without) for better predictions. This is our "parallel models" concept taken further.
    - *Search:* "model ensembling stacking blending"

11. **Bayesian Optimization**: Smarter hyperparameter search than grid search. Instead of trying all combinations, uses past results to pick the next best experiment.
    - *Search:* "bayesian optimization hyperparameter tuning optuna"

12. **Uncertainty Estimation**: CatBoost's `posterior_sampling` mode can estimate how confident the model is. Could be used to filter uncertain predictions.
    - *Read:* CatBoost docs on uncertainty estimation

13. **Transfer Learning / Domain Adaptation**: Training on one domain and applying to another. Relevant if we want to use historical seasons to help predict the current season.
    - *Search:* "domain adaptation time series"

14. **Custom Loss Functions**: Writing a loss function that directly optimizes for betting profitability instead of MAE. The holy grail but technically challenging.
    - *Search:* "custom loss function gradient boosting betting"

### Practical Resources
- **CatBoost docs**: https://catboost.ai/docs/ — comprehensive, well-written
- **Kaggle competitions**: Search for "sports betting" or "NBA" competitions to see what approaches work
- **StatsBomb / Pinnacle**: Sports analytics blogs with articles on betting model evaluation

---

## How Our Experiment Flags Map to Concepts

| Flag | Concept | What It Tests |
|------|---------|--------------|
| `--category-weight` | Feature importance manipulation | How much should we rely on each information source? |
| `--feature-weights` | Feature importance manipulation | Surgical control over individual features |
| `--rsm` | Random subspace method | Does hiding features force better learning? |
| `--grow-policy` | Tree architecture | Do asymmetric trees find better patterns? |
| `--min-data-in-leaf` | Regularization | Do broader patterns generalize better? |
| `--bootstrap` | Ensemble diversity | Does focusing on hard examples help? |
| `--subsample` | Ensemble diversity | Does data diversity improve robustness? |
| `--random-strength` | Exploration vs exploitation | Does more randomness find better solutions? |
| `--loss-function` | Optimization objective | What should the model optimize for? |
| `--quantile-alpha` | Asymmetric loss | Should predictions be biased upward? |
| `--residual` | Target engineering | Should we predict errors instead of values? |
| `--two-stage` | Pipeline architecture | Should prediction and betting be separate? |
| `--no-vegas` | Feature ablation | What happens without the dominant feature? |
| `--recency-weight` | Sample weighting | Should recent games matter more? |
| `--tune` | Hyperparameter optimization | Can we find better default parameters? |
| `--walkforward` | Time series validation | Is the model stable over time? |
