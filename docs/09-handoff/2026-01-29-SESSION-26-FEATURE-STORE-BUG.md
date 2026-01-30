# Session 26 Handoff - Feature Store Bug & Data Lineage Validation

**Date:** 2026-01-29
**Priority:** HIGH - Data quality issue affecting historical predictions
**Status:** Investigation complete, fixes needed

---

## TL;DR

During 2024-25 season validation, we discovered that the `ml_feature_store_v2` table has **incorrect L5/L10 rolling average values** for all historical data. The feature store values include the game being predicted (data leakage). This affects catboost_v8 prediction accuracy metrics.

**Key Stats:**
- 25,846 feature store records affected (100% of 2024-25 season)
- 0% used cache (should be ~100%)
- L5/L10 values are wrong by 2-4 points on average
- catboost_v8 74% accuracy may be artificially inflated

---

## What Was Discovered

### 1. Feature Store Bug

**The Problem:**
```
Victor Wembanyama on Jan 15, 2025:
- Actual L5 (games before Jan 15): 22.2 pts ← CORRECT
- Feature Store L5: 17.8 pts ← WRONG (includes Jan 15 game)
- Cache L5: 22.2 pts ← CORRECT
```

**Root Cause:**
- 100% of 2024-25 feature store used "fallback" calculation instead of cache
- Cache existed and had correct data (created 2 days before feature store)
- The fallback calculation has a bug (uses `<=` instead of `<` somewhere)

**Impact:**
- catboost_v8 predictions for 2024-25 used features with data leakage
- The reported 74% accuracy is unreliable
- Only affects historical backfill, not production (2025-26)

### 2. Other `<=` Issues Found

Multiple files use `<=` for date comparisons which could cause similar bugs:

| File | Line(s) | Issue |
|------|---------|-------|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | 142 | `game_date <= '{game_date}'` in player_rest CTE |
| `predictions/shadow_mode_runner.py` | 128 | `game_date <= @game_date` in history CTE |
| `data_processors/ml_feedback/scoring_tier_processor.py` | 168, 189 | `game_date <= '{as_of_date}'` |
| `validation/validators/precompute/player_daily_cache_validator.py` | Multiple | `cache_date <= '{end_date}'` |
| `shared/utils/completeness_checker.py` | 306, 547, 1563+ | `game_date <= DATE(...)` |

### 3. Validation Query Fix

The original validation also had a bug:
- Used `game_date <= cache_date` (wrong)
- Should use `game_date < cache_date` (correct)

This was fixed in documentation:
- `docs/08-projects/current/season-validation-2024-25/DATA-LINEAGE-VALIDATION.md`
- `docs/08-projects/current/season-validation-2024-25/VALIDATION-FRAMEWORK.md`
- `schemas/bigquery/validation/cache_lineage_validation.sql` (NEW)

---

## What Was Validated (2024-25 Season)

| Check | Result | Notes |
|-------|--------|-------|
| Points arithmetic | ✅ 100% correct | All 28,240 records |
| Grading coverage | ✅ 99.7% | Working correctly |
| Source reconciliation | ✅ 100% NBAC | No BDL fallback |
| Predictions ↔ Analytics | ✅ 100% | Zero orphaned predictions |
| Anomalies | ✅ Expected | 13 OT games, 8 garbage time |
| Cache vs Analytics (early season) | ✅ ~100% | Dec/Jan correct |
| Cache vs Analytics (late season) | ⚠️ ~30% | Mar-Jun stale (separate issue) |
| **Feature Store vs Cache** | ❌ 7-11% | **THE BUG** |

---

## Files Created/Modified

### New Files
- `docs/08-projects/current/season-validation-2024-25/FEATURE-STORE-BUG-INVESTIGATION.md` - Full investigation
- `schemas/bigquery/validation/cache_lineage_validation.sql` - Validation queries

### Modified Files
- `docs/08-projects/current/season-validation-2024-25/DATA-LINEAGE-VALIDATION.md`
- `docs/08-projects/current/season-validation-2024-25/DATA-QUALITY-METRICS.md`
- `docs/08-projects/current/season-validation-2024-25/VALIDATION-FRAMEWORK.md`

---

## Action Items for Next Session

### Priority 1: Fix `<=` Issues

Fix all identified date comparison issues:

```bash
# Files to fix:
data_processors/precompute/ml_feature_store/feature_extractor.py:142
predictions/shadow_mode_runner.py:128
data_processors/ml_feedback/scoring_tier_processor.py:168,189
# And others listed above
```

Change pattern: `game_date <=` → `game_date <`

### Priority 2: Investigate Why Cache Wasn't Used

Run feature store backfill with verbose logging:
```bash
python -m backfill_jobs.precompute.ml_feature_store.ml_feature_store_precompute_backfill \
  --start-date 2025-01-15 --end-date 2025-01-15 \
  --verbose
```

Check:
1. Does batch_extract_daily_cache return data?
2. Is the cache lookup query correct?
3. Are there any silent failures?

### Priority 3: Re-backfill Feature Store

After fixes, re-run for 2024-25:
```bash
python -m backfill_jobs.precompute.ml_feature_store.ml_feature_store_precompute_backfill \
  --start-date 2024-11-01 --end-date 2025-06-30
```

Verify: `source_daily_cache_rows_found IS NOT NULL` for all records

### Priority 4: Re-run Predictions

After feature store is fixed:
```bash
# Re-run catboost_v8 predictions for 2024-25
python -m backfill_jobs.predictions.prediction_backfill \
  --start-date 2024-11-01 --end-date 2025-06-30 \
  --system catboost_v8
```

### Priority 5: Recalculate Accuracy

Compare before/after accuracy to quantify the bug impact.

---

## Re-evaluate Fallback System

**Questions to answer:**

1. **Why does fallback exist at all?**
   - Is it for early season bootstrap?
   - Is it for cache failures?
   - Should it be removed entirely?

2. **Should fallback fail loudly?**
   - Currently: Falls back silently
   - Proposal: Log warning or fail if cache expected but missing

3. **Should we validate before writing?**
   - Add check: Feature store L5 must match cache L5 within tolerance
   - Reject records that use fallback when cache should exist

4. **Add prevention mechanisms:**
   - Pre-commit hook for `<=` date comparisons
   - Automated feature store vs cache validation
   - Alert if >5% of records use fallback

---

## Key Queries for Investigation

### Check Feature Store Data Source
```sql
SELECT
  CASE WHEN source_daily_cache_rows_found IS NOT NULL THEN 'Cache' ELSE 'Fallback' END,
  COUNT(*)
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date BETWEEN '2024-11-01' AND '2025-06-30'
GROUP BY 1
```

### Validate L5 Values
```sql
WITH comparison AS (
  SELECT
    f.player_lookup,
    f.game_date,
    f.features[OFFSET(0)] as fs_l5,
    c.points_avg_last_5 as cache_l5
  FROM `nba_predictions.ml_feature_store_v2` f
  JOIN `nba_precompute.player_daily_cache` c
    ON f.player_lookup = c.player_lookup AND f.game_date = c.cache_date
  WHERE f.game_date = '2025-01-15'
)
SELECT
  COUNT(*) as total,
  COUNTIF(ABS(fs_l5 - cache_l5) < 0.1) as matches,
  ROUND(100.0 * COUNTIF(ABS(fs_l5 - cache_l5) < 0.1) / COUNT(*), 1) as pct
FROM comparison
```

---

## Reference Documents

| Document | Purpose |
|----------|---------|
| `FEATURE-STORE-BUG-INVESTIGATION.md` | Full technical investigation |
| `DATA-LINEAGE-VALIDATION.md` | Validation findings and corrected queries |
| `VALIDATION-FRAMEWORK.md` | Framework with cache lineage section |
| `cache_lineage_validation.sql` | Reusable validation queries |

---

## Context for Next Session

**What you're fixing:**
- A data leakage bug where historical predictions used features that included the game being predicted
- This affects accuracy metrics but NOT production predictions

**Why it matters:**
- catboost_v8 74% accuracy may be wrong
- Can't trust historical analysis without fix
- Need to prevent similar issues in future

**The mystery to solve:**
- Cache existed with correct data
- Feature store was created after cache
- But feature store shows 0% cache usage
- Something prevented the cache lookup - find out what

**Start here:**
1. Read `FEATURE-STORE-BUG-INVESTIGATION.md`
2. Fix the `<=` issues
3. Run backfill with verbose logging to understand why cache wasn't used
4. Re-backfill and verify
