# ML Study Guide: Key Concepts Behind Our Model Experiments

**Created:** Session 246 (2026-02-13)
**Purpose:** Reference guide for understanding the techniques used in our NBA prediction models. Covers every concept that came up across Sessions 228-245.

---

## Table of Contents

1. [CatBoost Fundamentals](#1-catboost-fundamentals)
2. [Loss Functions: MAE vs Huber vs Quantile](#2-loss-functions)
3. [RSM (Random Subspace Method)](#3-rsm-random-subspace-method)
4. [Grow Policy: SymmetricTree vs Depthwise](#4-grow-policy)
5. [Feature Importance and Dominance](#5-feature-importance)
6. [Walk-Forward Validation](#6-walk-forward-validation)
7. [Governance Gates](#7-governance-gates)
8. [Edge and Hit Rate Math](#8-edge-and-hit-rate-math)
9. [Vegas Bias and Calibration](#9-vegas-bias-and-calibration)
10. [Overfitting in Betting Models](#10-overfitting-in-betting-models)
11. [Out-of-Sample Validation](#11-out-of-sample-validation)
12. [Shadow/Challenger Deployment](#12-shadow-challenger-deployment)
13. [Post-Prediction Filters vs Model Features](#13-post-prediction-filters)
14. [Multi-Season Backtesting](#14-multi-season-backtesting)
15. [Model Decay](#15-model-decay)

---

## 1. CatBoost Fundamentals

CatBoost is a gradient boosting library (like XGBoost and LightGBM) that builds an ensemble of decision trees sequentially. Each tree corrects the errors of the previous ones.

**Why CatBoost for this project:**
- Handles missing values (NaN) natively — critical since some features are unavailable for all players
- Ordered boosting reduces overfitting vs traditional gradient boosting
- Good out-of-the-box performance without extensive tuning

**How it predicts points:**
1. Start with a base prediction (mean of training targets)
2. Tree 1 learns from the residuals (errors)
3. Tree 2 learns from Tree 1's residuals
4. ... up to N iterations (we use 1000 with early stopping at 50)
5. Final prediction = sum of all tree outputs

**Key parameters we tune:**
- `depth` (default 6): How deep each tree grows. Deeper = more complex interactions but higher overfit risk.
- `iterations` (1000): Maximum trees. Early stopping usually cuts this to 100-300.
- `learning_rate` (auto): How much each tree contributes. Lower = more trees needed, smoother learning.
- `l2_leaf_reg`: L2 regularization on leaf values. Higher = more conservative predictions.
- `rsm`: Random Subspace Method — see section 3.
- `grow_policy`: How trees are built — see section 4.

**Further reading:**
- CatBoost docs: https://catboost.ai/en/docs/
- Original paper: "CatBoost: unbiased boosting with categorical features" (Prokhorenkova et al., 2018)

---

## 2. Loss Functions

The loss function defines what the model optimizes during training. This is the single most impactful choice — it changes what the model learns.

### MAE (Mean Absolute Error)

```
Loss = average(|predicted - actual|)
```

- Optimizes the **median** of the target distribution
- Treats all errors equally (a 2-point error is exactly twice as bad as a 1-point error)
- Produces **tighter predictions** closer to the center
- Fewer extreme predictions → fewer high-edge picks → lower volume but potentially higher accuracy per pick

**In our experiments:** MAE produced 35 edge 3+ picks (V12_RSM50_FIXED) with 71.4% HR. High quality, low volume.

### Huber Loss

```
Loss = { 0.5 * error^2           if |error| <= delta
       { delta * |error| - 0.5 * delta^2   if |error| > delta
```

- **Hybrid of MSE and MAE.** Behaves like MSE (squared error) for small errors and MAE (absolute error) for large errors.
- The `delta` parameter (we use 5) is the crossover point.
- For point prediction errors < 5 points: penalizes quadratically (like MSE). The model tries harder to get close.
- For point prediction errors > 5 points: penalizes linearly (like MAE). Outliers don't dominate the optimization.
- Produces **more spread** in predictions — the model is less afraid of predicting far from the mean because outlier errors aren't punished as harshly.
- More spread → more predictions with edge >= 3 → higher volume.

**In our experiments:** Huber:5 produced 88 edge 3+ picks (RSM50_HUBER_V2) with 62.5% HR. 2.5x the volume of MAE at a lower but still profitable hit rate.

**Why delta=5?** A 5-point miss on an NBA player prop is roughly the boundary between "close" and "badly wrong." Players averaging 20 points with a prediction off by 3 is normal variance. Off by 8 means something structural was missed. Delta=5 tells the model: care a lot about getting within 5, but don't let outliers distort everything.

**The key insight:** Huber fundamentally changes feature importance. Under MAE, `points_avg_season` dominates at 30%. Under Huber, `points_std_last_10` rises to 20.6% importance (from ~0%). The model becomes variance-aware — it learns which players have volatile scoring, which creates more edge opportunities.

### Quantile Loss

```
Loss = { alpha * error          if error > 0 (under-prediction)
       { (1 - alpha) * |error|  if error < 0 (over-prediction)
```

- Predicts a specific quantile of the distribution, not the mean/median.
- alpha=0.43 means: predict the value where the player scores BELOW this 43% of the time.
- Creates systematic bias: alpha < 0.5 → UNDER bias, alpha > 0.5 → OVER bias.
- The Q43 model (Session 186) achieved 65.8% HR on edge 3+ when fresh, but strong UNDER bias (67.6% UNDER HR vs lower OVER HR).

**In our experiments:** Quantile + RSM50 combination was too UNDER-biased (37.5% OVER HR). Quantile is useful standalone but doesn't pair well with other techniques.

**Further reading:**
- Huber loss: https://en.wikipedia.org/wiki/Huber_loss
- Quantile regression: https://en.wikipedia.org/wiki/Quantile_regression
- "Robust Statistics" by Peter Huber (the inventor)

---

## 3. RSM (Random Subspace Method)

RSM controls what fraction of features each tree split can consider. This is CatBoost's parameter `rsm` (also called `colsample_bylevel` in XGBoost).

```python
# In our winning config:
rsm = 0.5  # Each split considers only 50% of features (randomly selected)
```

**How it works:**
- Without RSM (rsm=1.0): Every tree split evaluates ALL 50 features to find the best split point.
- With RSM=0.5: Each split randomly masks out 50% of features and chooses the best split from the remaining 25 features.
- Different splits in the same tree get different random subsets.

**Why it helps us:**

Our model had a **feature dominance problem.** `points_avg_season` was consuming 30%+ of importance — the model over-relied on one feature. RSM forces the model to learn from other features because sometimes `points_avg_season` is masked out.

| Config | points_avg_season | HR 3+ |
|--------|-------------------|-------|
| No RSM (baseline) | 30.0% | 46.4% |
| RSM 0.5 | 27.7% | 57.1% |
| RSM 0.5 + Huber | 8.0% | 62.5% |

The progressive reduction in feature dominance correlates with better performance. The model becomes more robust because it doesn't collapse when one feature is noisy.

**RSM 0.5 vs 0.3 vs 0.7:**

| RSM | HR 3+ | N | Trade-off |
|-----|-------|---|-----------|
| 0.3 | 56.8% | 37 | Too aggressive — model can't find good splits |
| **0.5** | **57.1%** | **35** | **Sweet spot** |
| 0.7 | 55.9% | 34 | Not enough regularization |

**Analogy:** Think of it like a basketball team. If one player (feature) handles the ball 100% of the time, the offense is predictable. RSM forces ball movement — sometimes the star is "sitting out" and the role players have to contribute. The team becomes harder to defend (model becomes more robust).

**Further reading:**
- Random Subspace Method: Ho, T.K. "The random subspace method for constructing decision forests" (1998)
- CatBoost rsm parameter: https://catboost.ai/en/docs/references/training-parameters/common#rsm

---

## 4. Grow Policy

Controls how CatBoost builds each decision tree.

### SymmetricTree (CatBoost default)

- All leaves at the same depth use the **same split feature and threshold**
- Produces balanced, symmetric trees
- Very fast (GPU-optimized)
- Less expressive — can't create asymmetric patterns

### Depthwise (what we use)

- Standard tree building: each node picks its own best split independently
- More expressive — different branches can focus on different features
- Slightly slower but produces better predictions when combined with RSM
- Similar to how XGBoost and LightGBM build trees by default

**Why we use Depthwise with RSM:**

SymmetricTree + RSM is redundant — the symmetric constraint already limits feature usage per level. Depthwise + RSM gives maximum benefit because each node independently finds the best feature from its random subset, creating diverse tree structures.

```python
# Our winning config
grow_policy = "Depthwise"
rsm = 0.5
```

---

## 5. Feature Importance

CatBoost reports how much each feature contributed to reducing the loss function across all trees. Higher % = more influential.

### Reading Feature Importance

```
points_avg_season:     30.00%  ← Worrying: model over-relies on one signal
points_avg_last_10:    24.64%
points_avg_last_5:     12.06%
line_vs_season_avg:     5.04%  ← V12 feature, deviation signal
minutes_avg_last_10:    3.21%
usage_rate_last_5:      1.81%  ← V12 feature, role change signal
...
breakout_flag:          0.00%  ← Dead feature, model ignores it
```

### Feature Dominance Problem

When one feature exceeds ~25% importance, the model becomes fragile:
- If that feature is noisy or stale, the whole prediction degrades
- The model doesn't learn backup signals
- This was the key insight from Session 228: `points_avg_season` at 75% (Huber without RSM) produced the worst results

**The fix:** RSM 0.5 + Depthwise forces feature importance to spread out. Our best models have top feature at 8-27% instead of 30-75%.

### Zero-Importance Features

Features at 0.00% are ignored by the model. CatBoost handles these gracefully — they don't hurt, but they add unnecessary complexity. All FG% features (V13, V14) scored 0% because shooting efficiency doesn't predict point totals (it predicts direction, which is a different problem).

---

## 6. Walk-Forward Validation

Standard train/test split can mislead in time-series data because it doesn't simulate real trading/betting conditions.

### How It Works

Instead of one big eval window, we evaluate week by week:

```
Training:  Nov 2 ─────────────── Jan 31
Eval Week 1:                      Feb 1-7
Eval Week 2:                      Feb 8-14
Eval Week 3:                      Feb 15-21
```

Each week is evaluated independently. This shows if the model degrades over time (staleness) or has volatile performance.

### What to Look For

**Good walk-forward:**
```
Week 1: 66.7%
Week 2: 55.0%
Week 3: 58.3%
```
Consistent, no sharp drops.

**Bad walk-forward (decay signal):**
```
Week 1: 70.0%
Week 2: 55.0%
Week 3: 40.0%
```
Getting worse each week — the model is going stale.

### Why It Matters for Betting

A model that averages 60% but swings between 80% and 40% is dangerous. Walk-forward stability tells you whether to trust the model on any given week, not just on average.

---

## 7. Governance Gates

Our 6 gates that a model MUST pass before promotion. Each prevents a specific failure mode we've encountered.

| Gate | Threshold | Why It Exists |
|------|-----------|---------------|
| **MAE improvement** | Better than baseline | Prevents deploying a less accurate model |
| **HR edge 3+ >= 60%** | 60% | Must be profitable after -110 vig (~52.4% breakeven) with margin of safety |
| **Sample size >= 50** | n >= 50 | Prevents lucky small samples from getting promoted |
| **Vegas bias +/- 1.5** | Within limits | Catches systematic over/under prediction vs market |
| **No critical tier bias** | < +/- 5 pts | Prevents model from being great on stars but terrible on role players |
| **Directional balance** | OVER > 50% AND UNDER > 50% | Prevents one-sided models (e.g., all UNDER) |

### The Breakeven Math

At standard -110 odds:
- Bet $110 to win $100
- Need to win 52.38% of bets to break even: $110 / ($110 + $100) = 52.38%
- At 60% HR: ROI = (0.60 * 100 - 0.40 * 110) / 110 = **+14.5%**
- At 70% HR: ROI = (0.70 * 100 - 0.30 * 110) / 110 = **+33.6%**

The 60% gate gives meaningful margin above breakeven. Below 55%, profit margins are razor-thin and vulnerable to variance.

### Why Sample Size Matters

With n=35, a 71.4% HR has a 95% confidence interval of roughly 55-88%. The true rate could easily be below breakeven. With n=88, a 62.5% HR has a CI of roughly 52-73% — still wide, but the lower bound is near breakeven.

```
95% CI ≈ HR ± 1.96 * sqrt(HR * (1-HR) / n)

n=35, HR=71.4%: CI = 71.4% ± 15.0% → [56.4%, 86.4%]
n=88, HR=62.5%: CI = 62.5% ± 10.1% → [52.4%, 72.6%]
```

---

## 8. Edge and Hit Rate Math

### What Is Edge?

```
edge = predicted_points - betting_line
```

- Edge +5 on OVER: model predicts player will score 5 more than the line suggests → bet OVER
- Edge -5 on UNDER: model predicts player will score 5 less than the line → bet UNDER
- `|edge| >= 3` is our minimum threshold for actionable picks

### Why Filter by Edge?

Most predictions have small edge (0-2 points). These are essentially coin flips — the model isn't confident. Higher edge means more model conviction:

| Edge Bucket | Typical HR | Volume |
|-------------|-----------|--------|
| 0-1 | ~50% | High (majority of predictions) |
| 1-3 | ~52% | Medium |
| **3-5** | **58-65%** | **Low-Medium (our target)** |
| **5+** | **65-80%** | **Very Low (best picks)** |

The trade-off: higher edge threshold = better HR but fewer picks. Our governance uses 3+ as the minimum where signal consistently exceeds noise.

---

## 9. Vegas Bias and Calibration

### What Is Vegas Bias?

```
vegas_bias = average(predicted_points - vegas_line)
```

- Bias of 0: model agrees with Vegas on average (well calibrated)
- Bias of -2: model systematically predicts 2 fewer points than Vegas (UNDER bias)
- Bias of +2: model systematically predicts 2 more points than Vegas (OVER bias)

### Why It Matters

Vegas lines are set by sharp bookmakers using massive data. A systematic disagreement with Vegas usually means the model is miscalibrated, not that it's smarter than Vegas.

**Our failure case:** The Feb 2 retrain had MAE of 4.12 (better!) but vegas_bias of -2.26. It was systematically UNDER-predicting, which crashed HR from 71.2% to 51.2%. Lower MAE ≠ better betting.

### Vegas-Free Models

Our V12 models exclude Vegas features (indices 25-28: vegas_points_line, vegas_opening_line, vegas_line_move, has_vegas_line). The model predicts independently of market lines.

**Why go Vegas-free?**
- When Vegas is included (42% importance), the model just adjusts around the line
- A Vegas-free model provides an independent estimate — the edge calculation (`pred - line`) is more meaningful
- Vegas-free models are more robust to line movement and stale lines

**The catch:** `line_vs_season_avg` (V12 feature) is computed from `vegas_points_line - season_avg`. It partially leaks Vegas info. But removing it crashes HR from 57.1% → 51.9%, so we keep it. The signal it provides (how much the market deviates from the player's norm) is genuinely useful.

---

## 10. Overfitting in Betting Models

Overfitting means the model learns patterns in the training data that don't generalize.

### Common Overfitting Patterns in Sports Betting

**1. Small eval window overfitting:**
Finding a model that works on 12 days of data doesn't mean it works in general. Our Feb 1-12 eval window is small. This is why multi-season backtesting is critical.

**2. Feature snooping:**
Testing dozens of features and keeping the ones that worked on your eval set. The FG% features (V13/V14) correctly showed 0% importance — if they'd shown 2% importance and we'd kept them, we might be overfitting to noise.

**3. Optimization target mismatch:**
We optimize MAE (point prediction) but bet on direction (OVER/UNDER). A model with lower MAE can have worse HR — the Feb 2 retrain (MAE 4.12, HR 51.2%) proved this.

**4. In-sample leakage (Session 230):**
Using a model's own predictions on its training data to train a second model. The first model gets 88% on its training data (memorization), so the second model learns to trust it blindly. Always use out-of-fold (OOF) predictions.

### Defenses Against Overfitting

| Defense | How We Use It |
|---------|---------------|
| Walk-forward validation | Evaluate week by week, not one block |
| Governance gates | 6 independent checks prevent lucky results |
| Multi-season backtest | Test on 2024-25 data (planned) |
| Shadow deployment | Live predictions before promotion |
| Early stopping | Trees stop growing when validation loss plateaus |
| RSM 0.5 | Prevents single-feature dominance |
| Sample size gate | n >= 50 minimum |

---

## 11. Out-of-Sample Validation

Data the model (or analysis) has never seen during development.

### Levels of OOS Rigor

**Level 1: Hold-out split (what we have)**
Train on Nov-Jan, evaluate on Feb 1-12. The model never saw Feb data during training. But WE saw the Feb results while developing the model — we chose RSM, Huber, etc. because they worked on this window.

**Level 2: Split-sample (what we should do next)**
Discover a pattern (3PT cold) on Nov-Jan data only. Then test on Feb 1-12 WITHOUT changing anything. If the pattern holds on data it was never fitted to, it's more likely real.

**Level 3: Forward test (gold standard)**
Deploy the model and wait for new data (Feb 19+). Neither the model nor the developer has seen this data. This is what shadow deployment provides.

**Level 4: Multi-season (strongest)**
Test on a completely different season (2024-25). Different players, different team compositions, different market conditions. If the model works here, it's learning something fundamental.

### Applied to Our 3PT Cold Filter

The 77.5% HR was found by analyzing ALL of `prediction_accuracy`. This is not OOS — we found the pattern and are measuring it on the same data. Steps to validate:

1. **Split-sample:** Re-run the SQL but only on Nov-Jan games. If 3PT cold players still show elevated OVER HR, the signal is consistent.
2. **Forward test:** On Feb 19+ predictions, check if 3PT cold OVER bets outperform. If the signal holds on data from after the All-Star break, it's robust.
3. **Base rate check:** Is 40 picks enough? At 77.5% with n=40, the 95% CI is [62%, 89%]. The lower bound (62%) is still above breakeven, which is encouraging.

---

## 12. Shadow/Challenger Deployment

Running a new model alongside the production champion without affecting users.

### How Our Shadow System Works

```
Prediction Request
├── catboost_v9 (champion) → user-facing picks, alerts, API
├── catboost_v12 (shadow) → BigQuery only, graded independently
├── catboost_v9_q43 (shadow) → BigQuery only
└── catboost_v9_q45 (shadow) → BigQuery only
```

Each model writes predictions with its own `system_id`. The grading system grades all models independently. We can compare performance without risk.

### The Promotion Path

1. **Train** → passes governance gates in backtest
2. **Upload to GCS** → model file in cloud storage
3. **Shadow deploy** → update env var, model runs in parallel
4. **Monitor 2+ days** → check live predictions flow correctly
5. **Accumulate 50+ graded edge 3+ picks** → statistical significance
6. **Pass live governance** → HR >= 60% on live data
7. **Promote** → update champion env var (`CATBOOST_V9_MODEL_PATH`)
8. **Monitor post-promotion** → watch for unexpected behavior

### Why Shadow Testing Matters

Backtest performance ≠ live performance. Reasons it can differ:
- Feature store data may have different quality in real-time vs historical
- Line timing: backtests use final lines, live predictions use early lines
- Player availability: injuries announced after prediction time
- Data freshness: real-time features may be stale

---

## 13. Post-Prediction Filters vs Model Features

### The FG% Lesson

SQL analysis proved cold 3PT shooters go OVER at 55-60% rate. We tried adding this as model features (V13, V14). Every FG% feature got 0% importance. Why?

**CatBoost predicts point totals, not over/under.** A player shooting 35% from 3 doesn't predictably score X points — they might shoot more, get more free throws, etc. The FG% signal is about **probability of direction** (more likely to go OVER), not about **predicted magnitude** (how many points they'll score).

### When to Use Model Features vs Post-Prediction Rules

| Signal Type | Use As | Example |
|-------------|--------|---------|
| Predicts magnitude (how many points) | Model feature | `points_avg_last_5`, `minutes_load` |
| Predicts direction probability | Post-prediction filter | 3PT cold → likely OVER |
| Predicts which edges will hit | Neither (didn't work) | Edge Classifier attempt |

### How Post-Prediction Rules Work

```
1. Model predicts: Player X will score 24.5 points
2. Line is 22.5 → edge = +2.0 → OVER recommendation
3. Post-prediction check: Player's last-5 3PT% is 22% (very cold)
4. Rule: BOOST confidence on this OVER pick
5. Or conversely: Player's 3PT% is 55% (hot) → FLAG/reduce confidence
```

The model handles the magnitude prediction. The filter handles the directional probability adjustment. They're complementary, not redundant.

---

## 14. Multi-Season Backtesting

Testing on data from a completely different season to detect overfitting.

### Why Single-Season Tests Can Mislead

Our model was developed and evaluated entirely on the 2025-26 season:
- Training: Nov 2025 - Jan 2026
- Evaluation: Feb 2026

Every choice we made (V12 features, RSM, Huber) was informed by how it performed in this season. If 2025-26 has unique characteristics (specific team compositions, injury patterns, rule changes), our model might be exploiting these rather than learning general patterns.

### What Multi-Season Testing Reveals

| If multi-season HR is... | It means... |
|--------------------------|-------------|
| Similar to current season (60%+) | Model learns general patterns. Safe to deploy. |
| Slightly worse (52-60%) | Model partially overfit to current season. Usable with caution. |
| At breakeven or worse (<52%) | Model is overfit. Do NOT promote. |
| Better than current season | Current season may be unusually hard. Model is likely robust. |

### Practical Constraints

- V12 features (days_rest, usage_rate, etc.) may not exist in the feature store for older dates
- Prop line data coverage changes over time
- Team compositions are different each season

The test isn't "will the model make money last season?" — it's "does the same recipe (V12 + RSM + Huber) produce edge when applied to different data?"

---

## 15. Model Decay

Models get worse over time as the data they were trained on becomes stale.

### Why Models Decay

- **Player form changes:** A player averaging 25 in November may average 20 in February
- **Team dynamics:** Trades, injuries, lineup changes alter player roles
- **Market adaptation:** Bookmakers adjust lines based on recent performance
- **Seasonal patterns:** Fatigue, motivation, schedule density change through the season

### Our Decay Experience

| Period | Champion HR 3+ | Age (days since training end) |
|--------|---------------|------------------------------|
| Launch (Feb 8) | 71.2% | 31 days |
| Feb 13 | 36.7% | 36 days |

The champion trained on Nov-Jan data has degraded severely by mid-February. It's making predictions based on January patterns that no longer hold.

### Defenses Against Decay

1. **Monthly retraining** — update the model with recent data
2. **Shadow challengers** — always have a newer model ready
3. **Decay monitoring** — `validate-daily` Phase 0.56 tracks weekly HR
4. **Quick promotion** — when shadow outperforms champion, swap fast

### The Retrain Paradox (Session 179)

Retraining doesn't always help. Our Feb 2 retrain had better MAE (4.12 vs 4.82) but worse HR (51.2% vs 71.2%). The model learned the UNDER bias in recent data too aggressively.

**Solution:** RSM + Huber + governance gates. RSM prevents the model from latching onto one pattern, Huber is robust to outliers, and governance gates catch miscalibration before deployment.

---

## Quick Reference: Our Winning Config

```python
# The recipe that passed all 6 governance gates
model = CatBoostRegressor(
    iterations=1000,
    depth=6,
    loss_function="Huber:delta=5",
    rsm=0.5,
    grow_policy="Depthwise",
    early_stopping_rounds=50,
    random_seed=42,
)

# Feature set: V12 (50 features, no vegas)
# Training: walk-forward, include all players (with and without prop lines)
# Eval: edge >= 3 threshold for actionable picks
```

**Why each piece:**
- **Huber:5** — robust to outliers, generates more high-edge picks
- **RSM 0.5** — forces feature diversity, prevents dominance
- **Depthwise** — works synergistically with RSM (each node finds its own best split)
- **V12 features** — adds trend, fatigue, usage signals that reduce season-average dominance
- **No vegas** — independent predictions, meaningful edge calculation
- **Walk-forward** — catches decay early, validates week-by-week stability

---

## Recommended Reading Order

If you're starting from scratch:

1. **CatBoost basics** — understand gradient boosting (Section 1)
2. **Edge and HR math** — understand what we're optimizing for (Section 8)
3. **Loss functions** — understand why Huber works (Section 2)
4. **RSM** — understand the feature dominance fix (Section 3)
5. **Governance gates** — understand the safety checks (Section 7)
6. **Overfitting** — understand the risks (Section 10)
7. **Walk-forward and OOS** — understand validation rigor (Sections 6, 11)
8. **Everything else** — as needed when specific topics come up
