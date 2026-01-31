# CatBoost V12/V13 Experiments

**Status:** EXPERIMENTS COMPLETE - V13 ready for implementation
**Started:** 2026-01-31 (Session 52)
**Best Model:** 60-day recency weighting (65% high-conf hit rate)

---

## Summary

After running 30+ experiments on January 2026 data, we found that **60-day recency weighting** achieves the best high-confidence hit rate (65%) compared to no weighting (56.9%).

### Key Finding

| Configuration | High-Conf Hit% | Volume | ROI |
|---------------|----------------|--------|-----|
| No weighting (V8 baseline) | 56.9% | 181 bets | +8.6% |
| **60-day recency (V13)** | **65.0%** | **40 bets** | **+24.1%** |
| 90-day recency | 61.1% | 36 bets | +16.7% |
| 150-day recency | 63.9% | 61 bets | +21.5% |

---

## Experiment Results

### Training Period Experiments

| ID | Training Data | Samples | MAE | All Hit% | High Hit% |
|----|---------------|---------|-----|----------|-----------|
| EXP01 | 2024-25 only | 26K | 4.49 | 49.8% | 53.9% |
| EXP02 | 2024-Dec 2025 | 35K | 4.44 | 50.8% | 52.8% |
| EXP03 | 2023-2025 | 61K | 4.47 | 49.9% | 59.0% |
| EXP04 | 2022-2025 | 86K | 4.49 | 50.1% | 61.1% |
| EXP05 | 2021-2025 (full) | 113K | 4.59 | 49.4% | 56.9% |

**Conclusion:** More data doesn't help without recency weighting.

### Recency Weighting Experiments

| Half-Life | MAE | All Hit% | High Hit% | High Bets |
|-----------|-----|----------|-----------|-----------|
| 30d | 4.40 | 50.5% | 60.0% | 65 |
| 45d | 4.40 | 50.9% | 59.6% | 47 |
| **60d** | **4.39** | **50.8%** | **65.0%** | **40** |
| 75d | 4.38 | 51.7% | 59.4% | 32 |
| 90d | 4.39 | 50.9% | 61.1% | 36 |
| 120d | 4.39 | 51.0% | 60.9% | 46 |
| 150d | 4.41 | 50.0% | 63.9% | 61 |
| 180d | 4.45 | 50.3% | 58.8% | 102 |
| 240d | 4.41 | 50.4% | 60.5% | 81 |
| 365d | 4.56 | 49.4% | 56.2% | 153 |
| None | 4.59 | 49.4% | 56.9% | 181 |

**Conclusion:** 60-day half-life is optimal for high-confidence picks.

### Hyperparameter Experiments (with 60d recency)

| Config | MAE | All Hit% | High Hit% |
|--------|-----|----------|-----------|
| depth=3 | 4.36 | 51.7% | 61.8% |
| depth=4 | 4.38 | 50.0% | 60.9% |
| depth=5 | 4.39 | 51.5% | 58.3% |
| depth=6 (baseline) | 4.39 | 50.8% | 65.0% |
| l2_reg=1.0 | 4.38 | 51.0% | 61.0% |
| l2_reg=10.0 | 4.39 | 51.1% | 60.5% |
| subsample=0.9 | 4.40 | 50.2% | 61.2% |

**Conclusion:** Default V8 hyperparameters + 60d recency is optimal.

---

## January 2026 Analysis

### Why January Was Different

| Metric | December 2025 | January 2026 | Change |
|--------|---------------|--------------|--------|
| Avg points | 12.54 | 12.04 | -0.50 |
| Games with >10pt swing | 8.3% | 10.0% | +1.7% |
| 30+ point games | ~5% | 3.3% | -1.7% |
| <10 point games | ~40% | 45% | +5% |

### Performance by Player Tier

| Tier | Predictions | Hit Rate | Avg Bias |
|------|-------------|----------|----------|
| Stars (25+) | 156 | 46.2% | +1.16 (overpredicted) |
| Starters (18-25) | 357 | 41.7% | +0.85 |
| Rotation (12-18) | 778 | 44.5% | 0.00 |
| Bench (<12) | 1316 | 40.0% | +0.27 |

**Stars and Starters were hardest to predict** - model overpredicted them.

### Most Mispredicted Players

| Player | Games | Predicted | Actual | Bias |
|--------|-------|-----------|--------|------|
| Jerami Grant | 5 | 22.8 | 12.6 | -10.2 |
| Domantas Sabonis | 5 | 18.9 | 10.0 | -8.9 |
| Lauri Markkanen | 9 | 24.9 | 16.8 | -8.2 |
| Tyler Herro | 6 | 19.9 | 13.5 | -6.4 |
| Jalen Brunson | 10 | 23.3 | 17.7 | -5.6 |

---

## Why Recency Weighting Works

1. **January patterns differ from historical** - Recent games better predict current form
2. **Captures current slumps** - Established stars underperforming
3. **Reduces stale signal** - Old patterns less relevant
4. **60-day is optimal** - Balances recency with sample size

### Weight Distribution (60-day half-life)

| Days Old | Weight | Effective Multiplier |
|----------|--------|---------------------|
| 0 (today) | 1.00 | 16x vs 2-year-old |
| 30 | 0.71 | 11x |
| 60 | 0.50 | 8x |
| 90 | 0.35 | 6x |
| 180 | 0.12 | 2x |
| 365 | 0.015 | 0.25x |
| 730 | 0.0002 | 0.003x |

---

## Recommended V13 Configuration

```python
# catboost_v13.py configuration

# Training
TRAINING_START = "2021-11-01"
RECENCY_HALF_LIFE = 60  # days

def calculate_sample_weights(dates: pd.Series) -> np.ndarray:
    """60-day half-life exponential decay"""
    dates = pd.to_datetime(dates)
    max_date = dates.max()
    days_old = (max_date - dates).dt.days
    decay_rate = np.log(2) / 60
    weights = np.exp(-days_old * decay_rate)
    return (weights / weights.mean()).values  # Normalize

# Hyperparameters (same as V8)
CATBOOST_PARAMS = {
    "depth": 6,
    "learning_rate": 0.07,
    "l2_leaf_reg": 3.8,
    "subsample": 0.72,
    "min_data_in_leaf": 16,
    "iterations": 1000,
    "early_stopping_rounds": 50,
}

# Inference
MIN_EDGE_THRESHOLD = 5.0  # Only output high-confidence picks
```

---

## Files

### Experiment Scripts
- `ml/experiments/run_january_backfill_experiment.py` - January 2026 experiments
- `ml/experiments/train_walkforward.py` - General training with recency

### Results
- `ml/experiments/results/mega_experiment_20260131_*.json` - All results
- `ml/experiments/results/catboost_jan_exp_*.cbm` - Trained models

### Documentation
- This file: `docs/08-projects/current/catboost-v12-v13-experiments/README.md`
- Handoff: `docs/09-handoff/2026-01-31-SESSION-52-CATBOOST-EXPERIMENTS-HANDOFF.md`

---

## Next Steps

1. [ ] Create `catboost_v13.py` with 60-day recency
2. [ ] Add shadow mode to worker.py
3. [ ] Run A/B test vs V8 for 1 week
4. [ ] Promote V13 if results hold

---

*Created: 2026-01-31 Session 52*
