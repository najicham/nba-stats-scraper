# V8 Architecture Analysis

**Date:** 2026-01-31
**Session:** 55
**Status:** Complete

---

## Key Finding: Production V8 is NOT a Full Ensemble

### Training vs Production Gap

**Training** (`ml/train_final_ensemble_v8.py`):
- Trains 3 base models: XGBoost, LightGBM, CatBoost
- Creates stacked ensemble with Ridge meta-learner
- Achieves 3.40 MAE (best)

**Production** (`predictions/worker/prediction_systems/catboost_v8.py`):
- Only loads and uses CatBoost model (`catboost_v8_33features_*.cbm`)
- Does NOT load XGBoost or LightGBM
- Does NOT apply Ridge meta-learner
- Achieves 3.43 MAE (single model)

### Why This Matters

The stacked ensemble provides only **0.9% improvement** (3.40 vs 3.43 MAE), which is why deploying just CatBoost was deemed acceptable. However, this gap may be larger on specific player segments (stars, high-variance players).

---

## Ensemble Architecture Details

### Base Models (Training)

| Model | MAE | Notes |
|-------|-----|-------|
| XGBoost | 3.45 | Standard gradient boosting |
| LightGBM | 3.47 | Leaf-wise growth |
| CatBoost | 3.43 | **Best single model** |
| Simple Average | 3.44 | (XGB + LGB + CB) / 3 |
| **Stacked** | **3.40** | **Ridge meta-learner** |

### Ridge Meta-Learner Coefficients

```python
stacked_coefs = [0.38, -0.10, 0.74]
#                XGB   LGB    CB
```

**Interpretation:**
- CatBoost dominates (0.74 weight)
- XGBoost provides meaningful signal (0.38)
- LightGBM is **penalized** (-0.10) - indicates redundancy with other models

### Training Data

- Period: 2021-11-01 to 2024-06-01
- Samples: 76,863
- Features: 33

---

## Production Code Analysis

### catboost_v8.py Model Loading

```python
def _load_local_model(self):
    # Only loads CatBoost - no XGBoost or LightGBM
    model_files = list(models_dir.glob("catboost_v8_33features_*.cbm"))
    self.model = cb.CatBoostRegressor()
    self.model.load_model(str(model_path))
```

### What's Missing for True Ensemble

To deploy the full stacked ensemble, production would need:
1. Load all 3 base models (XGB, LGB, CB)
2. Generate predictions from each
3. Apply Ridge coefficients: `0.38*xgb + (-0.10)*lgb + 0.74*cb`
4. Handle different model formats (.json, .txt, .cbm)

---

## Implications for Research

### Question 1: Does the 0.9% ensemble gap matter?

For overall MAE: probably not (3.43 vs 3.40 = negligible)

For **star players** (high variance): possibly significant
- Single models struggle with 30+ point swings
- Ensemble smoothing could help

### Question 2: Would recency weighting help the ensemble?

Session 52 showed recency weighting helps single CatBoost achieve 65% hit rate on high-confidence picks.

**Untested hypothesis:** Recency weighting on all 3 base models could:
- Capture recent player role changes
- Adapt to mid-season fatigue patterns
- Improve star player predictions (where V8 struggles)

### Question 3: Is deploying full ensemble worth the complexity?

**Costs:**
- 3x model loading time
- 3x inference time
- More complex deployment

**Benefits:**
- Potentially better star player predictions
- More robust to individual model failures
- Could enable tier-based model selection

---

## Experiment Plan

### Experiment 1: Stacked Ensemble with 60-day Recency

Train new ensemble where all 3 base models use 60-day recency weighting:
1. Train XGBoost with sample weights (60-day half-life)
2. Train LightGBM with sample weights
3. Train CatBoost with sample weights
4. Train Ridge meta-learner on validation predictions
5. Evaluate on January 2026

### Experiment 2: Full Ensemble vs Single CatBoost

Compare on January 2026:
- Single CatBoost (current production V8)
- Single CatBoost + 60d recency
- Stacked ensemble (no recency)
- Stacked ensemble + 60d recency

### Experiment 3: Tier-Based Stacking

Different ensemble weights per tier:
- Stars: May need higher LightGBM weight for variance handling
- Rotation: CatBoost-heavy (current coefficients)
- Bench: XGBoost-heavy for low-sample robustness

---

## Files Reference

| File | Purpose |
|------|---------|
| `ml/train_final_ensemble_v8.py` | V8 training script (creates ensemble) |
| `predictions/worker/prediction_systems/catboost_v8.py` | V8 production (CatBoost only) |
| `models/ensemble_v8_20260108_211817_metadata.json` | Training results and coefficients |
| `models/catboost_v8_33features_*.cbm` | Production CatBoost model |
| `models/xgboost_v8_33features_*.json` | XGBoost (trained but not deployed) |
| `models/lightgbm_v8_33features_*.txt` | LightGBM (trained but not deployed) |

---

*Session 55 - V8 Architecture Analysis Complete*
