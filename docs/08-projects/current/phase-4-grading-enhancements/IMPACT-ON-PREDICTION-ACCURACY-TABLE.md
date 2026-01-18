# Impact Analysis: Session 91 Fixes on prediction_accuracy Table

**Date:** 2026-01-17
**Question:** Will fixing duplicates/data quality affect hit rates in ML model v8 performance analysis?
**Answer:** **YES - prediction_accuracy also has duplicates and needs the same fixes**

---

## Executive Summary

**Good News:** Session 91 fixes were applied to `prediction_grades` table (new grading system)

**Bad News:** The `prediction_accuracy` table (used in ML model v8 analysis) is SEPARATE and has its own data quality issues:
- **214 duplicates** in 2025-26 season data
- Same confidence normalization issues likely exist
- Hit rates in PERFORMANCE-ANALYSIS-GUIDE.md may be inflated

**Impact:** The performance metrics you measured are likely overstated due to duplicates.

---

## Two Separate Grading Tables

We have TWO grading tables in the system:

| Table | Rows | Date Range | Systems | Purpose | Status |
|-------|------|------------|---------|---------|--------|
| **prediction_accuracy** | 497,304 | 2021-11-02 to 2026-01-15 | 7 | Historical grading (ML model v8 analysis) | ⚠️ **Has 214 duplicates** |
| **prediction_grades** | 9,238 | 2026-01-01 to 2026-01-16 | 6 | New grading system (Phase 3) | ✅ **Fixed in Session 91** |

---

## Impact on ML Model v8 Performance Analysis

### What We Found

Checking `prediction_accuracy` for duplicates in 2025-26 season:
```sql
SELECT
  COUNT(*) as total_rows,
  COUNT(DISTINCT CONCAT(game_id, player_lookup, system_id, CAST(COALESCE(line_value, -1) AS STRING))) as unique_predictions,
  COUNT(*) - COUNT(DISTINCT CONCAT(...)) as duplicates
FROM `nba_predictions.prediction_accuracy`
WHERE game_date >= "2025-10-01"

Results:
- Total rows: 57,758
- Unique predictions: 57,544
- Duplicates: 214 (0.37%)
```

### Impact Assessment

**Duplicate Rate:** 0.37% (much better than prediction_grades' 20%, but still significant)

**Likely Impact on Hit Rates:**
- If duplicates are from winning predictions: Hit rate inflated by ~0.37%
- If duplicates are random: Minimal impact (~0.2%)
- If duplicates cluster on certain dates: Could skew daily/weekly metrics

**Example:**
- Measured hit rate: 55.0%
- Actual hit rate (after dedup): ~54.8% (if duplicates are random)
- Worst case: ~54.6% (if duplicates are all losses)

### Which Metrics Are Affected?

From PERFORMANCE-ANALYSIS-GUIDE.md, these queries may be affected:

**1. Season Performance Summary**
```sql
SELECT
  COUNT(*) as picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate
FROM `nba_predictions.prediction_accuracy`
WHERE game_date >= '2025-10-01' AND system_id = 'catboost_v8'
```
**Impact:** Win rate may be inflated by ~0.2-0.4%

**2. Tier Performance Analysis**
```sql
SELECT
  confidence_tier,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate
FROM `nba_predictions.prediction_accuracy`
WHERE ...
GROUP BY confidence_tier
```
**Impact:** If duplicates cluster in certain tiers, that tier's metrics are skewed

**3. Player-Specific Analysis**
```sql
SELECT player_lookup, COUNT(*) as picks, win_rate
FROM `nba_predictions.prediction_accuracy`
WHERE ...
GROUP BY player_lookup
```
**Impact:** If duplicates are for specific players, their metrics are inflated

---

## Confidence Normalization Issues

### Likely Present in prediction_accuracy

Based on Session 91 findings, `prediction_accuracy` likely has the same catboost_v8 confidence bug.

**To Check:**
```sql
SELECT
  system_id,
  MIN(confidence_score) as min_conf,
  MAX(confidence_score) as max_conf,
  AVG(confidence_score) as avg_conf,
  COUNT(CASE WHEN confidence_score > 1 THEN 1 END) as bad_confidence
FROM `nba_predictions.prediction_accuracy`
WHERE game_date >= '2025-10-01'
GROUP BY system_id
ORDER BY bad_confidence DESC
```

**If catboost_v8 shows max_conf > 1:** Same bug exists in this table.

**Impact:**
- High-confidence tier filtering may be wrong
- Calibration analysis invalid
- Confidence-based betting strategies may fail

---

## Recommended Actions

### Immediate (This Week)

**1. Check Confidence Normalization**
```sql
-- Run this to see if confidence bug exists
SELECT system_id, MIN(confidence_score), MAX(confidence_score), AVG(confidence_score)
FROM `nba_predictions.prediction_accuracy`
WHERE game_date >= '2025-10-01'
GROUP BY system_id
```

If catboost_v8 max > 1:
```sql
-- Fix it (same as we did for prediction_grades)
UPDATE `nba_predictions.prediction_accuracy`
SET confidence_score = confidence_score / 100.0
WHERE system_id = 'catboost_v8'
  AND confidence_score > 1
  AND game_date >= '2025-10-01'  -- Or whatever range has the issue
```

**2. De-Duplicate prediction_accuracy**
```sql
-- Create clean version
CREATE OR REPLACE TABLE `nba_predictions.prediction_accuracy_clean` AS
SELECT * EXCEPT(row_num)
FROM (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY game_id, player_lookup, system_id, CAST(COALESCE(line_value, -1) AS INT64)
      ORDER BY game_date DESC  -- Keep most recent if duplicates
    ) AS row_num
  FROM `nba_predictions.prediction_accuracy`
)
WHERE row_num = 1;

-- Verify
SELECT COUNT(*) FROM `nba_predictions.prediction_accuracy`;  -- 497,304
SELECT COUNT(*) FROM `nba_predictions.prediction_accuracy_clean`;  -- Should be 497,090 (214 fewer)

-- Backup and swap
-- ... (similar to what we did for prediction_grades)
```

**3. Recalculate Hit Rates**

After deduplication, re-run all queries from PERFORMANCE-ANALYSIS-GUIDE.md to get corrected metrics.

**Expected Changes:**
- Season win rate: May drop 0.2-0.4%
- Tier performance: May shift slightly
- Player metrics: Could change for specific players

### Short-Term (Next 2 Weeks)

**4. Extend Session 91 Validation to prediction_accuracy**

Update `bin/validation/daily_data_quality_check.sh` to also check:
```bash
# Add to daily checks
echo "Check: prediction_accuracy duplicates..."
ACCURACY_DUPES=$(bq query --use_legacy_sql=false --format=csv '
  SELECT COUNT(*) - COUNT(DISTINCT CONCAT(game_id, player_lookup, system_id, CAST(COALESCE(line_value, -1) AS STRING)))
  FROM `nba_predictions.prediction_accuracy`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
' | tail -1)

if [ "$ACCURACY_DUPES" -gt 0 ]; then
  echo "❌ Found $ACCURACY_DUPES duplicates in prediction_accuracy"
fi
```

**5. Understand Table Relationship**

Document which table is used for what:
- `prediction_accuracy` - Historical data, ML model analysis
- `prediction_grades` - New Phase 3 grading system
- Are these converging to one table? Or staying separate?
- Should we migrate to one unified grading table?

---

## Why Two Tables Exist

**Hypothesis (needs confirmation):**

1. **prediction_accuracy** (2021-2026, 497K rows)
   - Original grading system
   - Used for ML model v8 development and analysis
   - Has historical data from multiple seasons
   - 7 systems (includes older/deprecated systems?)

2. **prediction_grades** (Jan 2026, 9K rows)
   - New Phase 3 grading system (deployed Session 82-83)
   - Different schema/approach
   - 6 current active systems
   - Designed for dashboard and alerts

**Questions to Resolve:**
- Should we consolidate these tables?
- Is prediction_accuracy deprecated or still actively used?
- Which table should be the source of truth?
- Do they grade the same predictions or different ones?

---

## Summary: Impact on Your Hit Rates

### Direct Answer

**Will Session 91 fixes affect your hit rates?**
- **No** - Session 91 only fixed `prediction_grades`, not `prediction_accuracy`
- **But** - `prediction_accuracy` has the SAME issues (214 duplicates + likely confidence bug)
- **So** - Your measured hit rates are probably inflated by ~0.2-0.4%

### What You Should Do

**To get accurate hit rates:**
1. De-duplicate `prediction_accuracy` (remove 214 duplicates)
2. Fix confidence normalization if present
3. Re-run performance analysis queries
4. Compare before/after metrics

**Expected Impact:**
- Minimal impact (0.2-0.4% on win rates)
- Much smaller than prediction_grades (which had 20% duplicates)
- Specific tiers or players may show larger changes if duplicates cluster

**Good News:**
- Only 0.37% duplicates (not 20%)
- Fixes are straightforward (same process as Session 91)
- Historical data remains mostly accurate

---

**Next Steps:**
1. Run confidence normalization check (5 minutes)
2. De-duplicate prediction_accuracy if needed (30 minutes)
3. Recalculate hit rates from PERFORMANCE-ANALYSIS-GUIDE.md (15 minutes)
4. Document table relationships and consolidation plan (1 hour)

---

**Document Version:** 1.0
**Created:** 2026-01-17
**Status:** Analysis complete, fixes needed
