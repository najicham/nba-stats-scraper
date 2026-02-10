# Hyperparameters, Tuning, and Future Experiments

**Session:** 177
**Last Updated:** 2026-02-09

## What Are Hyperparameters?

Hyperparameters are settings you choose **before** training a model. They control **how** the model learns, not **what** it learns from the data. Think of them as knobs on a machine — the data is the raw material, but the knobs determine how the machine processes it.

CatBoost (our algorithm) has hundreds of hyperparameters, but only 3 matter enough to tune:

### The 3 Tunable Hyperparameters

| Parameter | Default | Range We Search | What It Does |
|-----------|---------|----------------|-------------|
| **depth** | 6 | [5, 6, 7] | How many yes/no questions each decision tree can ask. Deeper trees capture more nuance but risk memorizing noise (overfitting). A depth-6 tree asks up to 6 questions like "is vegas_line > 20.5?" |
| **learning_rate** | 0.05 | [0.03, 0.05] | How much each new tree corrects the previous ones. Lower = more cautious, needs more trees to converge but often generalizes better. Higher = learns faster but can overshoot. |
| **l2_leaf_reg** | 3.0 | [1.5, 3.0, 5.0] | Penalty for complex predictions. Higher values force the model to make simpler, more conservative predictions. Prevents the model from fitting to noise in small subgroups. |

### Fixed Hyperparameters (Not Tuned)

| Parameter | Value | Why It's Fixed |
|-----------|-------|---------------|
| **iterations** | 1000 | Maximum number of trees. Early stopping usually stops at 200-400. |
| **early_stopping_rounds** | 50 | Stop if validation error hasn't improved in 50 rounds. Prevents overfitting. |
| **random_seed** | 42 | Makes results reproducible. Same data + same seed = same model. |

## How Tuning Works

The `--tune` flag runs a **grid search**: it trains 18 separate models (3 depths x 3 l2 values x 2 learning rates) on 85% of the training data, evaluates each on the remaining 15%, and picks the combination with the best edge 3+ hit rate (using MAE as tiebreaker).

```bash
# With tuning
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "MY_EXPERIMENT" \
    --tune \
    --train-start 2025-11-02 --train-end 2026-01-31

# Without tuning (uses defaults)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "MY_EXPERIMENT" \
    --train-start 2025-11-02 --train-end 2026-01-31
```

### What Tuning Found In Our Experiments

| Experiment | depth | l2_leaf_reg | learning_rate | Notes |
|---|---|---|---|---|
| V9_BASELINE_CLEAN | 6 | 3.0 | 0.05 | Defaults (not tuned) |
| V9_FULL_CLEAN | **7** | 3.0 | **0.03** | Clean data, tuning picked deeper + slower |
| V9_FULL_FEB | **7** | **5.0** | 0.05 | Contaminated data, tuning picked deeper + more regularized |
| V9_TUNED_FEB | **7** | **5.0** | **0.03** | Contaminated data, tuning picked deeper + more reg + slower |

**Pattern:** Tuning consistently selects depth=7 (deeper trees). On contaminated data it also increases regularization (l2=5.0), which makes sense — more training data with overlap needs more regularization to avoid memorizing.

### Does Tuning Actually Help?

On clean data (the only valid comparison):

| Model | MAE | HR All | HR 3+ | Directional Balance |
|---|---|---|---|---|
| V9_BASELINE_CLEAN (defaults) | **4.784** | 62.4% | **87.0%** | OVER 89.3%, UNDER 78.6% |
| V9_FULL_CLEAN (tuned + recency) | 4.804 | 62.5% | 82.4% | OVER 89.2%, UNDER **58.6%** |

**Verdict:** On this eval period, default hyperparameters slightly beat tuned ones. The tuned model has worse directional balance (UNDER barely above breakeven). **Tuning is not a guaranteed improvement** — it's worth trying but should not be blindly trusted.

## Other Training Factors

### Recency Weighting (`--recency-weight DAYS`)

Gives recent games higher importance during training using exponential decay.

```bash
--recency-weight 30  # Half-life of 30 days
```

**How it works:** A game from yesterday has weight ~1.0. A game from 30 days ago has weight ~0.5. A game from 60 days ago has weight ~0.25. Weights are normalized so the mean is 1.0 (preserves effective sample size).

**When to use:** When you suspect recent NBA trends (trades, injuries, team dynamics) matter more than early-season patterns. The trade deadline (Feb) and All-Star break are natural inflection points.

**Our results:** Recency weighting made negligible difference on clean data. May matter more with longer training windows (90+ days) where early-season data is stale.

### Training Window Length

| Window | Pros | Cons |
|--------|------|------|
| **Short (30-45 days)** | Captures recent trends, fast training | Small sample, high variance |
| **Medium (60-90 days)** | Good balance, our default | May include stale patterns |
| **Long (90-120 days)** | Large sample, stable metrics | Early data may be irrelevant |

**Our findings:** The 99-day models (Nov 2 - Feb 8) have lower MAE than 68-day models (Nov 2 - Jan 8), but the backtest metrics are contaminated so we can't draw conclusions yet. Shadow testing will tell us.

### Walk-Forward Validation (`--walkforward`)

Splits the eval period into weekly chunks to detect if the model degrades over time.

**Key finding:** Our models lose predictive edge ~3 weeks from the training end date. Week 4 HR All drops from 64-66% to 54% (near break-even). This supports monthly retraining.

## Future Experiments to Try

### High Priority

1. **Shorter retraining cadence (2-week)**
   Walk-forward shows decay at week 3-4. A 2-week retrain cadence might maintain edge longer than monthly. Test by training on rolling 60-day windows with 2-week eval slices.

2. **Feature engineering: Remove zero-importance features**
   `injury_risk` and `playoff_game` contribute 0% importance across all experiments. Removing them simplifies the model and might reduce noise. However, `injury_risk` could matter during trade deadline and `playoff_game` post-April — test on those periods specifically.

3. **Feature engineering: Interaction features**
   Vegas lines dominate (45% importance). Test adding:
   - `vegas_line_vs_season_avg`: How much Vegas disagrees with the player's season average
   - `line_move_x_injury`: Line movement when injuries are reported
   - `pace_x_minutes`: Expected possessions for the player

4. **Different eval line sources**
   We evaluate against production lines (multi-source cascade). Try evaluating against closing lines (captured at game time) vs opening lines to understand how much line movement affects results.

### Medium Priority

5. **Larger hyperparameter grid**
   Our current grid is 18 combos (3x3x2). Try expanding:
   - `depth`: [4, 5, 6, 7, 8]
   - `l2_leaf_reg`: [0.5, 1.5, 3.0, 5.0, 10.0]
   - `learning_rate`: [0.01, 0.03, 0.05, 0.1]
   - 100 combos total, ~10 min extra training time

6. **Bayesian hyperparameter optimization**
   Replace grid search with Optuna or similar. More efficient than exhaustive grid — focuses on promising regions of the search space. Could find better params in fewer iterations.

7. **Training data augmentation**
   - Add noise to training targets (jitter actual points by +/- 0.5) to improve generalization
   - Oversample high-edge scenarios to improve edge 3+ performance specifically

8. **Ensemble of monthly models**
   Instead of picking one champion, average predictions across the 3 best models (weighted by recent performance). More stable than any single model.

### Low Priority (Exploratory)

9. **Different algorithms**
   Test LightGBM and XGBoost as alternatives to CatBoost. All are gradient boosted tree methods but have different splitting strategies. CatBoost handles categorical features natively which is why we chose it, but we don't have categorical features in V9.

10. **Player-tier-specific models**
    Train separate models for Stars (25+ ppg), Starters (15-24), Role players (5-14), and Bench (<5). Each tier has different dynamics — stars are more predictable, role players have higher variance.

11. **Opponent-adjusted targets**
    Instead of predicting raw points, predict points relative to opponent defensive rating. May reduce the model's dependence on Vegas lines.

12. **Time-series features**
    Add features capturing trends: is the player's scoring trending up or down over the last 5 games? Current features are averages which mask trends.

## How to Run an Experiment

```bash
# 1. Diagnose if retraining is needed
PYTHONPATH=. python ml/experiments/model_diagnose.py

# 2. Run baseline (default params, no extras)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "BASELINE" \
    --train-start 2025-11-02 --train-end 2026-02-28 \
    --eval-start 2026-03-01 --eval-end 2026-03-14 \
    --walkforward

# 3. Run with tuning
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "TUNED" \
    --train-start 2025-11-02 --train-end 2026-02-28 \
    --eval-start 2026-03-01 --eval-end 2026-03-14 \
    --tune --walkforward

# 4. Compare results — if gates pass, script prints MONTHLY_MODELS config
# 5. Upload model + add config + deploy as shadow challenger
# 6. Monitor: python bin/compare-model-performance.py <system_id>
```

## Glossary

| Term | Definition |
|------|-----------|
| **Hyperparameter** | A setting chosen before training that controls how the model learns |
| **Tuning** | Systematically trying different hyperparameter combinations to find the best one |
| **Grid search** | Trying every combination in a predefined set (our method) |
| **Overfitting** | When a model memorizes training data noise and performs poorly on new data |
| **Regularization** | Techniques that penalize model complexity to prevent overfitting (l2_leaf_reg) |
| **Early stopping** | Halting training when validation performance stops improving |
| **Recency weighting** | Giving more recent training examples higher importance |
| **Walk-forward** | Evaluating model on sequential time slices to detect temporal decay |
| **Shadow mode** | Running a challenger model alongside production without affecting user output |
| **Backtest advantage** | Inflated experiment metrics due to using perfect historical data vs noisy real-time data |
| **Contamination** | When training data overlaps with evaluation data, inflating metrics |
| **Survivorship bias** | When filtering to high-edge predictions inflates hit rate by selecting only extreme cases |
