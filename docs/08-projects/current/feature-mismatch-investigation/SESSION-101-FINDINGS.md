# Session 101 Findings - Feature Mismatch Investigation

**Date:** 2026-02-03
**Status:** ROOT CAUSE IDENTIFIED

---

## Executive Summary

The feature mismatch issue was caused by a **race condition between feature store WRITE_TRUNCATE updates and worker cache**. This resulted in predictions using stale/incorrect feature data with quality ~65.5 instead of the correct 87.59.

---

## Root Cause

### Technical Details

1. **Feature Store Uses WRITE_TRUNCATE**
   - Located at: `data_processors/precompute/ml_feature_store/batch_writer.py:319`
   - Each feature store run completely OVERWRITES existing data for that date

2. **Worker Caches Features Per Game Date**
   - Located at: `predictions/worker/data_loaders.py:80-87`
   - 5-minute TTL for same-day/future dates
   - Cache is per-instance (not shared across Cloud Run instances)

3. **Timeline on Feb 2-3:**
   ```
   UNKNOWN     - Feature store first populated for Feb 3 (quality ~65.5)
   ~21:38      - Worker loaded Feb 3 features (cached quality 65.5)
   22:30:07    - Feature store re-populated with WRITE_TRUNCATE (quality 87.59)
   23:12:42    - Predictions made using STALE cached data (quality 65.5)
   ```

### Evidence

1. **Worker logs at 23:12:**
   ```
   Features validated for petenance (quality: 65.5)
   Features validated for royceoneale (quality: 65.5)
   ```

2. **Current feature store (after truncate):**
   - All entries show quality 87.59
   - No entries with quality 65.5 exist

3. **Prediction critical_features JSON:**
   - Shows `feature_quality_score: 65.46`
   - Shows `pts_avg_last_5: 12.8` (should be 24.2 for Markkanen)

---

## Impact Assessment

### Affected Dates

| Date | Total Predictions | Null Quality | Low Quality | % Affected |
|------|------------------|--------------|-------------|------------|
| **Feb 3** | 147 | 102 | 0 | **69.4%** |
| **Feb 2** | 97 | 97 | 0 | **100.0%** |
| Jan 31 | 209 | 0 | 0 | 0.0% |

### Performance Impact

**Feb 2 Results (confirmed):**
- Overall hit rate: **41.9%** (expected ~54%)
- High-edge hit rate: **0.0%** (0/7 correct)
- All 7 high-edge predictions failed

---

## Fix Actions

### Immediate (Session 101)

1. ✅ Identified root cause
2. ⏳ Triggered regeneration for Feb 3 via `/regenerate-with-supersede`
3. ⏳ Need to regenerate Feb 2 predictions (games already played, for historical accuracy)

### Short-term

1. **Increase cache invalidation frequency** for same-day features
2. **Add cache invalidation when feature store is written** (Pub/Sub notification)
3. **Add quality score validation** before making predictions

### Long-term

1. Consider removing WRITE_TRUNCATE in favor of WRITE_APPEND with deduplication
2. Add monitoring for feature store write timestamps vs prediction timestamps
3. Add feature quality score comparison logging

---

## Files Involved

| File | Issue |
|------|-------|
| `data_processors/precompute/ml_feature_store/batch_writer.py:319` | WRITE_TRUNCATE causes data loss |
| `predictions/worker/data_loaders.py:80-87` | Instance-level cache can serve stale data |
| `predictions/worker/data_loaders.py:168-193` | Cache TTL logic (5 min) may not be enough |

---

## Related Sessions

- Session 99: Fixed feature store quality from 65% to 85% (possibly created the initial bad data)
- Session 100: Documented the problem definition
- Session 97: Model revert and quality field additions

---

## Next Steps

1. Monitor Feb 3 regeneration progress
2. Regenerate Feb 2 predictions for historical accuracy
3. Implement cache invalidation mechanism
4. Add pre-prediction feature quality validation
