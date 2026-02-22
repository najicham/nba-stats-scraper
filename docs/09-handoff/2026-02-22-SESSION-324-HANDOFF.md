# Session 324 Handoff: V12+Vegas Infrastructure + Shadow Model Deployment

**Date:** 2026-02-22
**Focus:** Build V12+vegas (54f) production infrastructure, retrain with post-ASB data, deploy shadow models
**Status:** 2 shadow models deployed, infrastructure complete, awaiting more data for full governance

## What Was Done

### 1. Post-ASB Data Assessment

Only 2 post-ASB game days completed (Feb 20-21, 15 games). Current V9 champion produced only 2 edge 3+ graded picks. **Not enough for N>=50 governance gate** on MAE models.

Edge 3+ rate: V12+vegas MAE produces ~1 edge 3+ pick per game day — very conservative. Quantile models (Q43) produce ~3.2/day.

### 2. V12+Vegas Infrastructure (catboost_monthly.py)

**Problem:** Production prediction code hardcoded 50-feature V12_NOVEG feature list. V12+vegas (54 features) would crash on dimension mismatch.

**Fix:** Dynamic feature extraction from `feature_contract.py`:
- `feature_set='v12'` → 54 features (with vegas)
- `feature_set='v12_noveg'` → 50 features (without vegas)
- Feature names loaded from shared contract, no more hardcoded list

**Bug fixed:** Pre-existing bug in MONTHLY_MODELS fallback dict — V12_NOVEG models had `feature_set="v12"` instead of `"v12_noveg"`. Would have crashed with the dynamic code. Fixed to correct values.

### 3. Cross-Model Discovery (cross_model_subsets.py)

Added 2 new family patterns for V12+vegas quantile models:
- `v12_vegas_q43`: matches `catboost_v12_q43_*`
- `v12_vegas_q45`: matches `catboost_v12_q45_*`

Classification now correctly handles:
- `catboost_v12_train*` → `v12_mae` (V12+vegas MAE)
- `catboost_v12_q43_train*` → `v12_vegas_q43` (V12+vegas Q43)
- `catboost_v12_noveg_train*` → `v12_mae` (catch-all, legacy)
- `catboost_v12_noveg_q43_train*` → `v12_q43` (V12 no-vegas Q43)

### 4. Model Experiments (7 total)

| # | Model | MAE | HR 3+ | N 3+ | Vegas Bias | Gates |
|---|-------|-----|-------|------|------------|-------|
| 1 | V12+vegas clean (50f) MAE | 4.750 | **91.7%** | 12 | -0.18 | 5/6 |
| 2 | **V12+vegas (54f) MAE** | **4.747** | **75.0%** | **16** | **-0.22** | **5/6** |
| 3 | **V12+vegas (54f) Q43** | **4.797** | **70.6%** | **51** | **-1.56** | **5/6** |
| 4 | V12+vegas (54f) Q45 | 4.831 | 67.4% | 49 | -1.33 | 4/6 |
| 5 | V12+vegas (54f) MAE long | 4.720 | 68.8% | 16 | +0.25 | 4/6 |
| 6 | V12+vegas (54f) Q43 long | 4.838 | 55.3% | 38 | -1.41 | 2/6 |
| 7 | V9 baseline (33f) MAE | 4.858 | 40.0% | 10 | -0.21 | 2/6 |

**Key findings:**
- V12+vegas dominates V9 in every metric (confirmed Session 323B)
- 42-day rolling window > 96-day (confirmed Session 284)
- MAE models too conservative for N>=50 in current eval window
- Q43 model closest to full governance (1 gate short — vegas bias -1.56 vs 1.5 limit)
- V12+vegas clean (50f) shows incredible 91.7% HR but N=12 (needs new feature contract for production, deferred)

### 5. Shadow Models Deployed

| Model ID | Feature Set | Features | Loss | HR 3+ | N | Status |
|----------|------------|----------|------|-------|---|--------|
| `catboost_v12_train1225_0205` | v12 | 54 | MAE | 75.0% | 16 | SHADOW |
| `catboost_v12_q43_train1225_0205` | v12 | 54 | Q:0.43 | 70.6% | 51 | SHADOW |

Both models:
- Uploaded to GCS (`gs://nba-props-platform-models/catboost/v12/monthly/`)
- Registered in `model_registry` with `enabled=TRUE, is_production=FALSE`
- Added to MONTHLY_MODELS fallback dict
- Auto-discovered by cross-model subsets

## Files Changed

| File | Change |
|------|--------|
| `predictions/worker/prediction_systems/catboost_monthly.py` | Dynamic feature extraction, V12+vegas support, NOVEG bugfix, new model entries |
| `shared/config/cross_model_subsets.py` | V12+vegas Q43/Q45 family patterns |

## Current Shadow Model Ecosystem (9 models)

| Model | Family | Features | Loss | HR 3+ | N |
|-------|--------|----------|------|-------|---|
| catboost_v9_train1102_0205 | v9_mae | 33 | MAE | 76.2% | 21 |
| catboost_v12_noveg_train1102_0205 | v12_mae | 50 | MAE | 69.2% | 13 |
| catboost_v9_q43_train1102_0125 | v9_q43 | 33 | Q:0.43 | 62.6% | 115 |
| catboost_v9_q45_train1102_0125 | v9_q45 | 33 | Q:0.45 | 62.9% | 97 |
| catboost_v12_noveg_q43_train1102_0125 | v12_q43 | 50 | Q:0.43 | 61.6% | 125 |
| catboost_v12_noveg_q45_train1102_0125 | v12_q45 | 50 | Q:0.45 | 61.2% | 98 |
| catboost_v9_low_vegas_train0106_0205 | v9_low_vegas | 33 | MAE | 56.3% | 48 |
| **catboost_v12_train1225_0205** | **v12_mae** | **54** | **MAE** | **75.0%** | **16** |
| **catboost_v12_q43_train1225_0205** | **v12_vegas_q43** | **54** | **Q:0.43** | **70.6%** | **51** |

## What the Clean Model Needs (Deferred)

The V12+vegas clean model (50f, 4 dead features excluded) showed 91.7% HR but can't be deployed because:
- It has a DIFFERENT 50-feature set from V12_NOVEG (removes indices 41,42,47,50 vs 25-28)
- Needs its own `V12_CLEAN_CONTRACT` in `feature_contract.py`
- Needs routing logic in `catboost_monthly.py`
- N=12 is too small to justify the infrastructure work now

If the pattern holds with more data, add a `V12_CLEAN_CONTRACT` with explicit feature list.

## Next Session Actions

### Priority 1: Retrain When More Data Available (~Mar 1-5)

After ~8 more game days (Feb 22-Mar 1), retrain MAE models with wider eval:
```bash
# Train Dec 25 - Feb 12, Eval Feb 13 - Mar 5 (~15 game days)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "MAR_V12_VEGAS" --feature-set v12 \
  --train-start 2025-12-25 --train-end 2026-02-12 \
  --eval-start 2026-02-13 --eval-end 2026-03-05 \
  --walkforward --force
```

### Priority 2: Monitor Shadow Models

```bash
# Check if shadows are generating predictions
PYTHONPATH=. python bin/compare-model-performance.py catboost_v12_train1225_0205 --days 3
PYTHONPATH=. python bin/compare-model-performance.py catboost_v12_q43_train1225_0205 --days 3

# Validate daily
/validate-daily
```

### Priority 3: Season Replay (After Models Graded)

Once shadow models have 7+ days of graded predictions:
```bash
/replay  # Compare V12+vegas vs champion V9
```

### Priority 4: Weekly Retrain with V12+Vegas

If V12+vegas shadows outperform V9 in production:
1. Update `retrain.sh` to default to `--feature-set v12`
2. Consider promoting V12+vegas MAE as champion
3. Update CLAUDE.md with new production model

## Governance Gate Notes

Both deployed models have minor gate failures. As shadow models, risk is zero:

1. **V12+vegas MAE (HR 75%, N=16):** Fails N>=50 — MAE models are conservative, producing few edge 3+ picks. Will naturally accumulate N as more games are played. Expected to pass when retrained with wider eval.

2. **V12+vegas Q43 (HR 70.6%, N=51):** Fails vegas bias (-1.56, limit 1.5) by 0.06 points. This is expected behavior for quantile alpha=0.43 — the model intentionally predicts below median, which manifests as negative vegas bias. The existing V9 Q43 and V12 NOVEG Q43 models had similar characteristics at deployment.

## Model Files

| File | Config | MAE | HR 3+ |
|------|--------|-----|-------|
| `models/catboost_v9_54f_train20251225-20260205_20260221_224505.cbm` | V12+vegas MAE | 4.747 | 75.0% |
| `models/catboost_v9_54f_q0.43_train20251225-20260205_20260221_230420.cbm` | V12+vegas Q43 | 4.797 | 70.6% |
| `models/catboost_v9_50f_train20251225-20260205_20260221_224638.cbm` | V12+vegas clean | 4.750 | 91.7% |
| `models/catboost_v9_54f_q0.45_train20251225-20260205_20260221_230519.cbm` | V12+vegas Q45 | 4.831 | 67.4% |
