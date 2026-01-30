# January 2026 Performance Investigation Summary

**Date:** 2026-01-30
**For:** Prediction Team Review
**Status:** Investigation Complete - Action Items Pending

---

## Executive Summary

The January 2026 model performance dip from ~70% to ~45% accuracy was **NOT model drift**. It was caused by a **data pipeline bug** that has been partially fixed. The model itself is valid.

---

## Timeline of Events

| Date | Event | Impact |
|------|-------|--------|
| Nov 2024 - Dec 2025 | Production model (catboost_v8) | 70.7% accuracy |
| Jan 7, 2026 | player_daily_cache populated correctly | Cache has correct L5/L10 |
| **Jan 9, 2026** | **Feature store backfill with `<=` bug** | Features include current game (WRONG) |
| Jan 9-28, 2026 | Predictions made with buggy features | 45% accuracy, +6 pt over-prediction bias |
| Jan 29, 2026 | Feature store patched | 8,456 records fixed |
| Jan 30, 2026 | DNP validator bug fixed | 10 records corrected |

---

## Root Cause: Feature Store Bug

### The Problem
A date comparison bug in the feature store backfill caused L5/L10 averages to include the **current game**:

```sql
-- BUGGY CODE
WHERE game_date <= '2026-01-15'  -- Includes Jan 15 game in L5 average

-- CORRECT CODE
WHERE game_date < '2026-01-15'   -- Only games BEFORE Jan 15
```

### Why This Broke Predictions

1. **Model trained on correct data** (2021-2024 data was clean)
2. **Model fed buggy data** (Jan 2026 features included current game)
3. **Pattern mismatch** → Model expected "L5 = last 5 games before today"
4. **Result**: Systematic over-prediction (+6.25 points average bias)

---

## Current Fix Status

| Component | Status | Details |
|-----------|--------|---------|
| Feature store bug | ✅ FIXED | Patched Jan 29, 8,456 records |
| DNP voiding validator | ✅ FIXED | Fixed Jan 30, 10 records |
| **Jan 9-28 predictions** | ❌ NOT FIXED | Still using buggy features |
| Model itself | ✅ VALID | No retraining needed |

---

## Experiment Results: Training Data Comparison

We ran experiments with different training data configurations to evaluate January 2026 performance:

| Experiment | Training Period | Training Samples | Jan 2026 Hit Rate | ROI |
|------------|----------------|------------------|-------------------|-----|
| ALL_DATA | Nov 2021 - Dec 2025 | 106,332 | 53.51% | +2.16% |
| INSEASON_2025_26 | Oct - Dec 2025 | 12,249 | 52.53% | +0.28% |
| COMBINED_RECENT | Jan 2024 - Dec 2025 | 28,552 | 53.01% | +1.21% |
| **RECENT_2024_25** | **Jan - Jun 2025** | **16,303** | **61.12%** | **+16.69%** |

### Key Observations

1. **Recent data performs better**: The RECENT_2024_25 model (trained on just Jan-Jun 2025) significantly outperformed all others
2. **High-confidence picks work well**: RECENT_2024_25 had 80% hit rate on high-confidence (5+ point edge) picks
3. **Direction doesn't matter much**: OVER (61.37%) vs UNDER (60.81%) were nearly identical

### Confidence Breakdown (RECENT_2024_25 model)

| Confidence Level | Count | Hit Rate |
|-----------------|-------|----------|
| High (5+ points) | 483 | **80.12%** |
| Medium (3-5 points) | 666 | 62.16% |
| Low (1-3 points) | 1,714 | 55.37% |
| Pass (<1 point) | 1,305 | 49.96% |

---

## Recommendations

### Immediate Actions (P0)

1. **Regenerate Jan 9-28 predictions**
   ```bash
   python -m backfill_jobs.predictions.catboost_v8_backfill \
     --start-date 2026-01-09 \
     --end-date 2026-01-28 \
     --verbose
   ```
   This will use the patched features and should restore ~70% accuracy for this period.

### Short-term Actions (P1)

2. **Consider recency-weighted training**
   - The RECENT_2024_25 experiment suggests more recent data is more predictive
   - Options:
     a. Retrain with rolling 6-month window
     b. Add time-decay weighting to training samples
     c. Use ensemble of recent + historical models

3. **Deploy validation integration**
   - New post-grading validation has been added to the pipeline
   - Need to deploy the updated grading cloud function

### Long-term Actions (P2)

4. **Automated data quality gates**
   - Add circuit breaker to pause predictions if feature validation fails
   - Alert on feature drift before it impacts predictions

5. **Rolling model updates**
   - Consider monthly model retraining with recent data
   - Or implement online learning for continuous adaptation

---

## Data Quality Validation Tools

New validation tools were integrated in Sessions 30-31:

```bash
# Check feature store quality
python -m shared.validation.feature_store_validator --days 7

# Check prediction quality
python -m shared.validation.prediction_quality_validator --days 30

# Check cross-phase consistency
python -m shared.validation.cross_phase_validator --days 7

# Check feature drift
python -m shared.validation.feature_drift_detector --days 7
```

---

## Key Files Reference

| Purpose | Location |
|---------|----------|
| Model experiments | `ml/experiments/results/*.json` |
| Feature store validator | `shared/validation/feature_store_validator.py` |
| Prediction validator | `shared/validation/prediction_quality_validator.py` |
| Bug root cause analysis | `docs/08-projects/current/season-validation-2024-25/MODEL-DRIFT-ROOT-CAUSE-CLARIFICATION.md` |
| Session 31 handoff | `docs/09-handoff/2026-01-30-SESSION-31-VALIDATION-FIX-AND-MODEL-ANALYSIS-HANDOFF.md` |

---

## Questions for Prediction Team

1. Should we regenerate Jan 9-28 predictions immediately?
2. Do we want to explore retraining with more recent data?
3. Should we implement a rolling training window?
4. What's the appetite for more aggressive data quality gates?

---

*Investigation Summary - 2026-01-30*
*Prepared for Prediction Team Review*
