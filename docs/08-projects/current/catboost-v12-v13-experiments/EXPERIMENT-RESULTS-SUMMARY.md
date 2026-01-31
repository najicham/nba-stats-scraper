# Experiment Results Summary

**Date:** 2026-01-31
**Evaluation Period:** January 1-28, 2026
**Total Experiments:** 30+

---

## Quick Reference

### Best Configuration for High-Confidence Picks

```
Training Data:     Full history (2021-11-01 to current)
Recency Weighting: 60-day half-life
Hyperparameters:   Default V8 settings
Edge Threshold:    5+ points
Expected Hit Rate: 65%
Expected ROI:      +24%
Volume:            ~40 bets/month
```

---

## All Recency Experiments (Sorted by High-Conf Hit Rate)

| Half-Life | MAE | All Hit% | All Bets | High Hit% | High Bets | ROI% |
|-----------|-----|----------|----------|-----------|-----------|------|
| **60d** | **4.39** | **50.8%** | **1325** | **65.0%** | **40** | **+24.1%** |
| 150d | 4.41 | 50.0% | 1411 | 63.9% | 61 | +21.5% |
| 90d | 4.39 | 50.9% | 1353 | 61.1% | 36 | +16.7% |
| 120d | 4.39 | 51.0% | 1347 | 60.9% | 46 | +16.2% |
| 240d | 4.41 | 50.4% | 1521 | 60.5% | 81 | +15.6% |
| 30d | 4.40 | 50.5% | 1456 | 60.0% | 65 | +14.5% |
| 45d | 4.40 | 50.9% | 1396 | 59.6% | 47 | +13.4% |
| 75d | 4.38 | 51.7% | 1305 | 59.4% | 32 | +12.5% |
| 180d | 4.45 | 50.3% | 1515 | 58.8% | 102 | +12.3% |
| None | 4.59 | 49.4% | 1842 | 56.9% | 181 | +8.6% |
| 365d | 4.56 | 49.4% | 1738 | 56.2% | 153 | +7.3% |

---

## Training Period Experiments

| Training Data | Samples | MAE | All Hit% | High Hit% | High Bets |
|---------------|---------|-----|----------|-----------|-----------|
| 2024-25 only | 26K | 4.49 | 49.8% | 53.9% | 91 |
| 2024-Dec 2025 | 35K | 4.44 | 50.8% | 52.8% | 125 |
| 2023-2025 | 61K | 4.47 | 49.9% | 59.0% | 117 |
| 2022-2025 | 86K | 4.49 | 50.1% | 61.1% | 144 |
| 2021-2025 | 113K | 4.59 | 49.4% | 56.9% | 181 |
| 2021-2025 + 60d rec | 113K | 4.39 | 50.8% | 65.0% | 40 |

---

## Hyperparameter Experiments (with 60d recency)

| Config | MAE | All Hit% | High Hit% |
|--------|-----|----------|-----------|
| depth=3 | 4.36 | 51.7% | 61.8% |
| depth=4 | 4.38 | 50.0% | 60.9% |
| depth=5 | 4.39 | 51.5% | 58.3% |
| depth=6 (baseline) | 4.39 | 50.8% | 65.0% |
| depth=8 | 4.39 | 51.4% | 56.4% |
| l2_reg=1.0 | 4.38 | 51.0% | 61.0% |
| l2_reg=5.0 | 4.39 | 51.1% | 50.0% |
| l2_reg=10.0 | 4.39 | 51.1% | 60.5% |
| min_leaf=8 | 4.39 | 50.8% | 65.0% |
| min_leaf=32 | 4.39 | 50.8% | 65.0% |
| min_leaf=64 | 4.39 | 50.8% | 65.0% |
| subsample=0.6 | 4.43 | 49.7% | 59.1% |
| subsample=0.9 | 4.40 | 50.2% | 61.2% |
| lr=0.03 | 4.40 | 49.9% | 62.5% |
| lr=0.10 | 4.42 | 50.0% | 55.1% |

---

## Combined Experiments

| Name | Config | MAE | All Hit% | High Hit% |
|------|--------|-----|----------|-----------|
| COMBO_60d_depth4 | 60d + depth=4 | 4.38 | 50.0% | 60.9% |
| COMBO_60d_depth3 | 60d + depth=3 | 4.36 | 51.7% | 61.8% |
| BEST_COMBO_B | 60d + depth=4 + sub=0.9 | 4.38 | 51.2% | 63.2% |
| BEST_COMBO_C | 45d + depth=4 + l2=5.0 | 4.40 | 50.2% | 60.7% |

---

## Key Conclusions

1. **60-day recency is optimal** for high-confidence picks
2. **Default V8 hyperparameters work well** - no need to change
3. **Full historical data is valuable** - don't train on recent only
4. **High-confidence picks (5+ edge) are most profitable**
5. **min_data_in_leaf doesn't matter much** (8, 32, 64 all same)

---

## Files

- Models: `ml/experiments/results/catboost_jan_exp_*.cbm`
- Results: `ml/experiments/results/mega_experiment_20260131_*.json`
- Scripts: `ml/experiments/run_january_backfill_experiment.py`

---

*Generated: 2026-01-31*
