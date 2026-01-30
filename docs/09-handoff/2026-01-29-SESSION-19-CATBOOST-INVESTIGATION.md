# Session 19 Handoff - CatBoost V8 Performance Investigation

**Date:** 2026-01-29
**Author:** Claude Opus 4.5
**Status:** CRITICAL ISSUE IDENTIFIED - Investigation Needed

---

## Executive Summary

CatBoost V8, the documented "champion" model, has experienced a **severe performance regression** starting around January 8-9, 2026. The model went from 65-70% win rate to 50-51% win rate, with MAE doubling from ~4.0 to ~9.0.

**Key Finding:** The model is predicting absurdly high point totals (40-60+ points) for star players who are scoring 15-30 points. Predictions are being clamped at 60 points (max), indicating the model output is even higher.

---

## Performance Timeline

### Monthly Overview

| Month | Picks | MAE | Win Rate | Bias | Status |
|-------|-------|-----|----------|------|--------|
| Nov 2025 | 296 | 8.08 | 52.7% | +4.46 | Poor |
| Dec 2025 | 1,701 | 5.86 | **68.3%** | +1.47 | **Good** |
| Jan 2026 | 1,901 | 7.03 | 56.0% | +3.02 | Degraded |

### January Week-by-Week Breakdown

| Week | Picks | MAE | Win Rate | Avg Pred | Bias | Extreme (40+) |
|------|-------|-----|----------|----------|------|---------------|
| Jan 1-7 | 704 | **4.29** | **65.9%** | 13.0 | -0.3 | **0** |
| Jan 8-14 | 241 | 7.01 | 45.6% | 15.9 | +1.6 | 11 |
| Jan 15-21 | 160 | 8.17 | 54.4% | 18.3 | +5.5 | 23 |
| Jan 22-28 | 796 | 9.23 | 50.8% | 19.2 | +5.88 | **88** |

**Critical Transition:** Between Jan 7 and Jan 9, performance collapsed:

| Date | MAE | Win Rate | Avg Pred | Extreme |
|------|-----|----------|----------|---------|
| Jan 7 | 4.01 | 66.0% | 12.9 | 0 |
| Jan 9 | **7.05** | **52.8%** | **16.2** | **8** |

---

## OVER vs UNDER Analysis

The problem is concentrated in **OVER predictions**:

### December 2025 (Good Period)
| Direction | Picks | MAE | Win Rate | Bias |
|-----------|-------|-----|----------|------|
| OVER | 1,032 | 6.85 | **69.6%** | +3.49 |
| UNDER | 669 | 4.32 | 66.4% | -1.64 |

### January 2026 (Bad Period)
| Direction | Picks | MAE | Win Rate | Bias |
|-----------|-------|-----|----------|------|
| OVER | 967 | **9.50** | **52.5%** | **+8.03** |
| UNDER | 934 | 4.48 | 59.6% | -2.17 |

**UNDER predictions are relatively stable** (MAE 4.32 → 4.48), but **OVER predictions collapsed** (MAE 6.85 → 9.50, bias +3.49 → +8.03).

---

## Example Catastrophic Predictions

The model is predicting 60 points (clamped max) for players scoring 20-30:

| Player | Date | Predicted | Line | Actual | Error |
|--------|------|-----------|------|--------|-------|
| Anthony Edwards | Jan 28 | 60.0 | 30.5 | 20 | **+40** |
| SGA | Jan 25 | 60.0 | 34.5 | 24 | **+36** |
| Immanuel Quickley | Jan 28 | 41.6 | 16.5 | 7 | **+35** |
| Julius Randle | Jan 25 | 44.5 | 23.5 | 11 | **+34** |

These are not edge cases - there are 122 predictions ≥40 points in January vs 66 in December.

---

## Current System Rankings

| System | MAE | Win Rate | Status |
|--------|-----|----------|--------|
| **ensemble_v1_1** | **4.39** | **56.0%** | ✅ Best performer |
| xgboost_v1 | 4.92 | 55.2% | ✅ Good |
| ensemble_v1 | 4.93 | 53.1% | ✅ Good |
| moving_average | 5.07 | 51.9% | ✅ Baseline |
| **catboost_v8** | **7.03** | 56.0% | ❌ **BROKEN** |

**Recommendation:** Use `ensemble_v1_1` as primary system until CatBoost is fixed.

---

## The 70%+ Win Rate Mystery (Sportsbook Analysis)

The documentation mentions 71.6% betting accuracy. This came from comparing predictions against **sportsbook lines** rather than raw prediction accuracy:

```
Sportsbook Performance Baseline (Jan 2026):
| Caesars    | 1,528 | 1,098 | 71.9% |
| DraftKings | 1,506 | 1,080 | 71.7% |
```

This is a **different metric** - it measures how often the prediction would beat the sportsbook line, not raw OVER/UNDER accuracy. The 70%+ numbers may have been from December when the model was performing well.

---

## Root Cause Hypotheses

### Hypothesis 1: Feature Drift (Most Likely)
- Features may be calculated differently now than during training
- The Jan 25 update added "has_shot_zone_data" feature - may have disrupted feature alignment
- Feature 33 mismatch could cause model to misinterpret other features

### Hypothesis 2: Model File Corruption
- Check if correct model file is being loaded in production
- Model is clamping at 60 - suggests raw output is >60 (indicates model instability)

### Hypothesis 3: Data Pipeline Change
- Feature store (`ml_feature_store_v2`) may have changed data format
- Vegas line features may be missing or malformed

### Hypothesis 4: Training/Production Feature Mismatch
- Model was trained on 33 features from historical data (2021-2024)
- Production features may have different distributions or scales

---

## Investigation Checklist for Next Session

### 1. Check Feature Values
```sql
-- Compare features for a player on a good day vs bad day
SELECT
  game_date,
  player_lookup,
  features[OFFSET(0)] as points_avg_last_5,
  features[OFFSET(5)] as fatigue_score,
  features[OFFSET(25)] as vegas_points_line
FROM nba_predictions.ml_feature_store_v2
WHERE player_lookup = 'anthonyedwards'
  AND game_date IN ('2026-01-05', '2026-01-25')
```

### 2. Check Model Loading Logs
```bash
gcloud logging read 'resource.labels.service_name="prediction-worker" textPayload:"CatBoost"' \
  --limit=50 --freshness=7d
```

### 3. Compare Feature Preparation
- Review `predictions/worker/prediction_systems/catboost_v8.py:_prepare_feature_vector()`
- Check if all 33 features are being extracted correctly
- Verify feature order matches training

### 4. Check Vegas Line Features
- Are `vegas_points_line`, `vegas_opening_line`, `vegas_line_move` populated correctly?
- These are features 25-28 and could significantly affect predictions

### 5. Test with Historical Data
- Run predictions on Jan 5 features (when model worked)
- Compare output to what was generated then

---

## Files to Review

### Prediction System
- `predictions/worker/prediction_systems/catboost_v8.py` - Main prediction code
- `predictions/worker/data_loaders.py` - Feature loading
- `predictions/worker/worker.py` - Orchestration

### Feature Store
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` - Feature generation
- `schemas/bigquery/nba_predictions/ml_feature_store_v2.sql` - Schema

### Model Files
- `models/catboost_v8_33features_*.cbm` - Model file
- `models/ensemble_v8_20260108_211817_metadata.json` - Metadata

### Documentation
- `docs/08-projects/current/ml-model-v8-deployment/` - Deployment docs
- `docs/08-projects/current/grading-validation/` - This investigation

---

## Project Documentation Location

All investigation documentation is in:
```
docs/08-projects/current/grading-validation/
├── 2026-01-29-grading-deep-dive.md
├── 2026-01-29-catboost-regression-analysis.md
├── validation-queries.md
└── (add new files here)
```

### To Update Documentation
1. Add new markdown files with date prefix: `2026-MM-DD-topic.md`
2. Update the regression analysis file with new findings
3. Create a new handoff doc when concluding investigation

---

## CatBoost V9 Recommendations

Based on this investigation, CatBoost V9 should address:

### 1. Feature Validation
- Add runtime feature validation comparing to training distributions
- Alert if features are outside expected ranges
- Log feature values for debugging

### 2. Prediction Bounds
- Current clamp is 0-60; should be tighter (5-50?)
- Star players rarely score >50 even in their best games
- Add warning logs when predictions hit bounds

### 3. A/B Testing Framework
- Deploy V9 in shadow mode first
- Compare against V8 AND ensemble_v1_1
- Require 2+ weeks of good performance before promotion

### 4. Monitoring
- Daily MAE alerts (threshold: >6.0)
- Weekly win rate checks (threshold: <55%)
- Extreme prediction counts (threshold: >20 per day)

### 5. Training Data
- Consider retraining on 2024-2025 data only (more recent)
- Validate feature distributions match production
- Document exact feature preparation pipeline

---

## Immediate Actions

1. **Switch primary system to `ensemble_v1_1`** (best current performer)
2. **Keep CatBoost V8 running in shadow mode** for comparison
3. **Add monitoring alerts** for MAE and extreme predictions
4. **Investigate Jan 8 changes** to find root cause

---

## Session Summary

### What Was Done
- Fixed NAType bug in grading actuals loader
- Backfilled grading for Jan 23-25
- Created comprehensive validation queries
- Identified critical CatBoost V8 regression
- Documented timeline and severity

### What Remains
- Root cause investigation for CatBoost regression
- Feature comparison (good period vs bad period)
- Model/feature alignment verification
- Decision on CatBoost V9 approach

### Commits Made
- `16cb7cec` - fix: Handle pandas NAType in grading actuals loader
- `d734c37e` - docs: Add comprehensive validation queries for grading analysis
- `b51644f2` - docs: Add CatBoost V8 regression analysis - CRITICAL issue

---

*Created: 2026-01-29 4:30 PM PST*
*Author: Claude Opus 4.5*
