# Session 26 Comprehensive Handoff - Feature Store Bug & Validation Gap

**Date:** 2026-01-29
**Priority:** HIGH
**For:** New chat session to investigate and fix

---

## Start Here

Read these documents in order:
1. This handoff (you're reading it)
2. `docs/08-projects/current/season-validation-2024-25/FEATURE-STORE-BUG-INVESTIGATION.md`

---

## Summary of What Happened

During 2024-25 season validation, we discovered:

1. **Feature Store Bug:** `ml_feature_store_v2` has wrong L5/L10 values for all 25,846 historical records
2. **100% used fallback:** Cache existed but wasn't used during backfill
3. **Data leakage:** Feature values include the game being predicted
4. **Validation Gap:** Existing `/validate-lineage` skill doesn't check this

---

## The Bug in Detail

### What's Wrong

```
Victor Wembanyama on Jan 15, 2025:
- Actual L5 before Jan 15: 22.2 pts ← CORRECT (what predictions should use)
- Feature Store L5: 17.8 pts ← WRONG (includes Jan 15 game)
- Cache L5: 22.2 pts ← CORRECT

Match rate for Jan 15, 2025:
- L5: 7.2% (14/194 match)
- L10: 11.3% (22/194 match)
```

### Why It Matters

- catboost_v8 predictions used these wrong features
- The 74% reported accuracy may be inflated
- This is data leakage - model had access to future information

### Root Cause

```sql
-- This query shows 100% used fallback
SELECT
  CASE WHEN source_daily_cache_rows_found IS NOT NULL THEN 'Cache' ELSE 'Fallback' END,
  COUNT(*)
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date BETWEEN '2024-11-01' AND '2025-06-30'
GROUP BY 1

-- Result:
-- Fallback: 25,846 (100%)
-- Cache: 0 (0%)
```

**The mystery:** Cache existed (created Jan 7, 2026) but feature store (created Jan 9, 2026) didn't use it. Something prevented cache lookup.

---

## The Validation Gap

### What We Have

| Skill | What It Checks | Would Catch This Bug? |
|-------|----------------|----------------------|
| `/validate-lineage` | Quality scores, window completeness, processing context | **NO** - doesn't compare actual values |
| `/validate-historical` | Field coverage, record counts | **NO** - doesn't compare cross-table values |
| `/validate-daily` | Pipeline health, today's data | **NO** - doesn't check feature store vs cache |

### What We Need

A check that validates:
```sql
-- Feature store L5 should match cache L5 within tolerance
SELECT
  COUNT(*) as total,
  COUNTIF(ABS(f.features[OFFSET(0)] - c.points_avg_last_5) < 0.1) as matches
FROM `nba_predictions.ml_feature_store_v2` f
JOIN `nba_precompute.player_daily_cache` c
  ON f.player_lookup = c.player_lookup AND f.game_date = c.cache_date
WHERE f.game_date = @date

-- Should be >95% match rate
-- Alert if <95% or if source_daily_cache_rows_found is NULL
```

---

## Your Tasks (Use Agents in Parallel)

### Task 1: Find All `<=` Date Comparisons

Use an Explore agent to search:
```
Search the entire codebase for date comparisons using <= instead of <.
Look for: game_date <=, cache_date <=, analysis_date <=
Return file paths, line numbers, and context.
Flag any that could cause off-by-one errors in rolling averages or lookback windows.
```

Known issues to fix:
- `data_processors/precompute/ml_feature_store/feature_extractor.py:142`
- `predictions/shadow_mode_runner.py:128`
- `data_processors/ml_feedback/scoring_tier_processor.py:168,189`
- `shared/utils/completeness_checker.py` (multiple)

### Task 2: Investigate Why Cache Wasn't Used

The cache existed but feature store didn't use it. Find out why:

```
1. Read the feature store backfill code:
   - backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py
   - data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
   - data_processors/precompute/ml_feature_store/feature_extractor.py

2. Find where batch_extract_daily_cache is called
3. Check if there are any conditions that would skip cache lookup
4. Look for silent error handling that might swallow failures
5. Check if there's a date format mismatch between cache_date and game_date
```

### Task 3: Add Feature Store Validation to `/validate-lineage`

Update the validation skill to catch this:

```
1. Read .claude/skills/validate-lineage.md
2. Add a new check: "Feature Store vs Cache Match Rate"
3. The check should:
   - Sample 50 records per date
   - Compare features[0] (L5) to cache points_avg_last_5
   - Compare features[1] (L10) to cache points_avg_last_10
   - Alert if match rate < 95%
   - Alert if source_daily_cache_rows_found IS NULL for >5% of records

4. Add validation queries to schemas/bigquery/validation/cache_lineage_validation.sql
```

### Task 4: Fix the `<=` Issues

Change `<=` to `<` where appropriate:
- Only for date comparisons in lookback windows
- Don't change range queries like `BETWEEN start AND end`
- Add comment explaining why `<` is correct

### Task 5: Re-evaluate Fallback Architecture

Answer these questions:
1. Should fallback exist at all for historical backfill?
2. Should fallback fail loudly instead of silently?
3. Should we validate feature values before writing to BigQuery?
4. Should there be a pre-commit hook for `<=` date comparisons?

Document recommendations in the investigation doc.

### Task 6: Create Prevention Mechanisms

1. **Pre-commit hook:** Flag `<=` in date comparisons
2. **Post-backfill validation:** Automatically run feature store vs cache check
3. **Alerting:** Alert if fallback usage > 5% for historical data
4. **Schema validation:** Add check that source columns are not NULL

---

## Key Files

### Investigation & Documentation
- `docs/08-projects/current/season-validation-2024-25/FEATURE-STORE-BUG-INVESTIGATION.md`
- `docs/08-projects/current/season-validation-2024-25/DATA-LINEAGE-VALIDATION.md`
- `schemas/bigquery/validation/cache_lineage_validation.sql`

### Feature Store Code
- `data_processors/precompute/ml_feature_store/feature_extractor.py`
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- `backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py`

### Validation Skills
- `.claude/skills/validate-lineage.md`
- `.claude/skills/validate-historical.md`
- `shared/validation/` - Implementation code

---

## Key Queries

### Check Fallback Usage
```sql
SELECT
  CASE WHEN source_daily_cache_rows_found IS NOT NULL THEN 'Cache' ELSE 'Fallback' END as src,
  COUNT(*) as records
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date BETWEEN '2024-11-01' AND '2025-06-30'
GROUP BY 1
```

### Validate L5 Match Rate
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

### Check Wembanyama Specifically
```sql
-- Cache (correct)
SELECT points_avg_last_5 FROM `nba_precompute.player_daily_cache`
WHERE player_lookup='victorwembanyama' AND cache_date='2025-01-15'

-- Feature Store (wrong)
SELECT features[OFFSET(0)] FROM `nba_predictions.ml_feature_store_v2`
WHERE player_lookup='victorwembanyama' AND game_date='2025-01-15'
```

---

## Success Criteria

When you're done, these should all be true:

1. [ ] All `<=` date comparison issues are fixed
2. [ ] We understand why cache wasn't used during backfill
3. [ ] `/validate-lineage` skill updated to check feature store vs cache
4. [ ] Prevention mechanisms documented/implemented
5. [ ] Feature store backfill re-run with correct data (or plan documented)
6. [ ] Predictions re-run (or plan documented)

---

## Context That Might Help

- The cache uses `cache_date`, feature store uses `game_date` - same values
- Cache was created Dec 16, 2025 - Jan 7, 2026
- Feature store was created Jan 9, 2026 (after cache)
- Production (2025-26 season) data appears correct - only historical affected
- The `_batch_extract_daily_cache` function queries `WHERE cache_date = '{game_date}'`
- The `_safe_query` method re-raises errors, doesn't swallow them

---

## Don't Forget

1. **Use agents liberally** - Parallelize investigation tasks
2. **Document everything** - Update the investigation doc with findings
3. **Test fixes** - Verify with queries before deploying
4. **Check related systems** - MLB might have similar issues
