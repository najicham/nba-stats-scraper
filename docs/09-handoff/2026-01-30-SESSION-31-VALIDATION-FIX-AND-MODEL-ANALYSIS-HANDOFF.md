# Session 31 Handoff - Validation Bug Fix and Model Performance Analysis

**Date:** 2026-01-30
**Focus:** Fix DNP voiding validator bug, integrate validation into pipeline, investigate model performance
**Status:** Complete - all validation integrated, model performance investigated

---

## Session Summary

This session accomplished three main objectives:
1. Fixed a bug in the DNP voiding validator (not the grading processor)
2. Integrated validation into daily grading and backfill pipelines
3. Investigated the January 2026 model performance dip

---

## Key Finding #1: DNP Voiding Bug Was in Validator, Not Processor

### The Bug
The handoff from Session 30 reported "317 DNP predictions incorrectly graded" and pointed to the grading processor. **This was incorrect.**

Investigation revealed:
- **4,972 records** with `actual_points=0` had **positive minutes played** (players who played but didn't score)
- **Only 10 records** were true DNPs (0 points AND 0/NULL minutes)
- The **validator** was using the wrong definition of DNP

### Root Cause

| Component | Definition Used | Correct? |
|-----------|----------------|----------|
| Grading Processor | `actual_points=0 AND (minutes_played=0 OR NULL)` | ✅ Correct |
| Validator | `actual_points=0` | ❌ Wrong |

A player who plays but scores 0 points is **NOT** a DNP - that's a valid game result.

### Fix Applied

1. **Validator fix** in `shared/validation/prediction_quality_validator.py`:
   - Changed DNP check to: `actual_points=0 AND (minutes_played=0 OR minutes_played IS NULL)`
   - Fixed confidence calibration query (wrong column name)

2. **Data backfill** in BigQuery:
   - Updated 10 true DNP records: `prediction_correct=NULL, is_voided=TRUE, void_reason='dnp_backfill_fix'`

### Verification
```
DNP Voiding Check: PASS
  Total DNP: 547
  Properly voided: 547
  Incorrectly graded: 0
```

---

## Key Finding #2: January Model Performance Dip Root Cause

### Summary: It's NOT Model Drift - It Was Feature Store Bug

The January 2026 accuracy drop from ~70% to ~45% was caused by a **feature store data quality bug**, not model drift. The bug was identified and patched in Session 27.

### The Bug (Patched Jan 29)
```sql
-- BUGGY (what the backfill did)
WHERE game_date <= '2026-01-15'  -- Includes Jan 15 game in L5 average

-- CORRECT (what it should be)
WHERE game_date < '2026-01-15'   -- Only games BEFORE Jan 15
```

This caused:
- L5/L10 averages to include the current game
- Systematic over-prediction bias (+6.25 points)
- Model trained on correct data → fed buggy data → predictions wrong

### Experiment Results (Different Training Data)

| Experiment | Training Data | Jan 2026 Hit Rate | ROI |
|------------|---------------|-------------------|-----|
| ALL_DATA | 2021-2025 (106K samples) | 53.51% | +2.16% |
| INSEASON_2025_26 | Oct-Dec 2025 only (12K samples) | 52.53% | +0.28% |
| COMBINED_RECENT | 2024-2025 (28K samples) | 53.01% | +1.21% |
| **RECENT_2024_25** | Jan-Jun 2025 (16K samples) | **61.12%** | **+16.69%** |

**Key Insight:** The RECENT_2024_25 model performs significantly better, suggesting seasonal/recency matters.

### Current Status

| Item | Status | Notes |
|------|--------|-------|
| Feature store bug | ✅ FIXED (Jan 29) | 8,456 records patched |
| DNP voiding validator | ✅ FIXED (today) | 10 records corrected |
| Jan 9-28 predictions | ⚠️ NOT FIXED | Made with buggy features, need regeneration |
| Model itself | ✅ VALID | Model is fine, input data was corrupted |

---

## Validation Integration Added

### 1. Daily Grading Pipeline
**File:** `orchestration/cloud_functions/grading/main.py`

Added `run_post_grading_validation()` that runs after successful grading:
- Checks DNP voiding (no incorrectly graded DNPs)
- Checks placeholder lines (no graded placeholder lines)
- Results included in completion Pub/Sub message

### 2. ML Feature Store Backfill
**File:** `backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py`

Added `_run_post_backfill_validation()` that runs after backfill completes:
- Checks L5/L10 cache consistency
- Checks for duplicates
- Checks array integrity
- Checks feature bounds

### 3. Predictions Backfill
**File:** `backfill_jobs/prediction/player_prop_predictions_backfill.py`

Added `_run_post_backfill_validation()` that runs after backfill completes:
- Checks prediction bounds (0-70 range)
- Reports outliers

---

## Files Modified This Session

| File | Change |
|------|--------|
| `shared/validation/prediction_quality_validator.py` | Fixed DNP definition, fixed confidence query |
| `orchestration/cloud_functions/grading/main.py` | Added post-grading validation |
| `backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py` | Added post-backfill validation |
| `backfill_jobs/prediction/player_prop_predictions_backfill.py` | Added post-backfill validation |

---

## Recommendations for Next Session

### P0 - Critical
1. **Regenerate Jan 9-28 predictions** - These were made with buggy features
   ```bash
   python -m backfill_jobs.predictions.catboost_v8_backfill \
     --start-date 2026-01-09 \
     --end-date 2026-01-28 \
     --verbose
   ```

### P1 - Important
2. **Consider model retraining with recent data** - RECENT_2024_25 experiment showed 61% hit rate
3. **Add validation to daily orchestration Cloud Scheduler** - Currently only runs on grading completion

### P2 - Nice to Have
4. **Deploy grading cloud function** - Contains new validation code
5. **Add alerting on validation failures** - Slack/email when checks fail

---

## Validation Commands Quick Reference

```bash
# Run all validators
python -m shared.validation.feature_store_validator --days 7
python -m shared.validation.prediction_quality_validator --days 30
python -m shared.validation.cross_phase_validator --days 7
python -m shared.validation.feature_drift_detector --days 7

# Check specific date
python -m shared.validation.prediction_quality_validator --start-date 2026-01-15 --end-date 2026-01-15
```

---

## Git Commits This Session

```
1a72657e fix: Correct DNP definition in prediction quality validator
```

---

## CRITICAL: Grading Corruption Found (From Session 28 Review)

After reviewing Session 28's document, we confirmed a **separate critical issue** - grading pipeline corruption affecting multiple dates:

### Corruption Summary

| Date | System | Drift % | Max Drift | Records |
|------|--------|---------|-----------|---------|
| Jan 28 | catboost_v8 | **94.9%** | 26.0 pts | 424 |
| Jan 25 | zone_matchup_v1 | 38.6% | 14.3 pts | 85 |
| Jan 25 | ensemble_v1_1 | 36.8% | 16.7 pts | 81 |
| Jan 21 | ensemble_v1 | 44.8% | 17.3 pts | 39 |
| Jan 21 | zone_matchup_v1 | 42.5% | 6.0 pts | 37 |

**Total: ~900+ corrupted records**

### Example Corruption (Jan 28)
```
Brandon Miller: predicted 16.1 → stored as 42.1 (+26 pts!)
Anthony Edwards: predicted 35.0 → stored as 60.0 (+25 pts!)
Stephen Curry: predicted 20.7 → stored as 45.0 (+24.3 pts!)
```

### This is DIFFERENT from the feature store bug
- Feature store bug: Wrong features → wrong predictions
- Grading corruption: Correct predictions → **stored incorrectly** during grading

### Required Fix
```sql
-- Delete corrupted grading records
DELETE FROM nba_predictions.prediction_accuracy
WHERE game_date IN ('2026-01-20', '2026-01-21', '2026-01-24', '2026-01-25', '2026-01-28')
  AND system_id IN ('catboost_v8', 'zone_matchup_v1', 'similarity_balanced_v1',
                    'ensemble_v1', 'ensemble_v1_1', 'moving_average');

-- Then re-run grading for these dates
```

### Root Cause Investigation Needed
The root cause of the grading corruption is unknown. Investigate:
- `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`
- Check for race conditions, data joins, or caching issues

---

*Session 31 Handoff - 2026-01-30*
*Investigation and validation integration complete*
*Updated with Session 28 findings after review*
