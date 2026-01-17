# ROOT CAUSE FOUND: Jan 8, 2026 Feature Quality Drop

**Investigation Date:** 2026-01-16
**Status:** ✅ ROOT CAUSE IDENTIFIED

---

## Executive Summary

The complete loss of `phase4_partial` features on January 8, 2026 was caused by **`player_daily_cache` table not being updated on Jan 8 and Jan 12**.

This is a **data availability issue**, not a code or pipeline failure. The upstream precompute tables are being updated inconsistently.

---

## The Smoking Gun

### player_daily_cache Updates (Jan 5-15)

| Date | Players | Status |
|------|---------|--------|
| 2026-01-05 | 114 | ✅ Updated |
| 2026-01-06 | 84 | ✅ Updated |
| 2026-01-07 | 183 | ✅ Updated |
| **2026-01-08** | **0** | **❌ MISSING** |
| 2026-01-09 | 57 | ✅ Updated |
| 2026-01-10 | 103 | ✅ Updated |
| 2026-01-11 | 199 | ✅ Updated |
| **2026-01-12** | **0** | **❌ MISSING** |
| 2026-01-13 | 183 | ✅ Updated |
| 2026-01-14 | 177 | ✅ Updated |
| 2026-01-15 | 191 | ✅ Updated |

**Jan 8 and Jan 12 have ZERO records in player_daily_cache!**

### Other Phase4 Tables (ALL UPDATED)

**player_composite_factors:** ✅ Updated every day including Jan 8 (115 players)

**player_shot_zone_analysis:** ✅ Updated every day including Jan 8 (430 players)

**team_defense_zone_analysis:** ✅ Updated every day including Jan 8 (30 teams)

---

## Why This Breaks Phase4_Partial

The `phase4_partial` data source requires **>50% of features from Phase4 precompute tables**.

`player_daily_cache` provides critical features:
- Features 0-4: Recent performance (points avg last 5/10, season avg, std, games)
- Features 18-20: Shot zones (paint rate, 3pt rate, assisted rate)
- Features 22-23: Team context (pace, offensive rating)

**That's 9 out of 25 features = 36% of all features!**

### What Happens When player_daily_cache is Missing:

```
Features from player_daily_cache: 0/25 (missing on Jan 8)
Features from player_composite_factors: 4/25 (features 5-8)
Features from player_shot_zone_analysis: 3/25 (features 18-20, but overlap with cache)
Features from team_defense_zone_analysis: 2/25 (features 13-14)
Features from fallback/defaults: 16/25

Phase4 percentage = 9/25 = 36% < 50% threshold
→ Labeled as "mixed" instead of "phase4_partial"
→ Quality score drops from 97 → 77-84
```

---

## Impact Analysis

### Jan 8 Impact

**Features generated on Jan 8:**
- 115 records (lowest of the period except Jan 12)
- All labeled "mixed" (0 phase4_partial)
- Quality scores: 77.2-84.4 (no high-quality 90+ features)
- Missing player_daily_cache forced fallback to defaults

**Why Jan 8 had fewer features:**
- Fewer players had composite_factors data (115 vs usual 200-300)
- Without daily_cache, many players couldn't generate features at all
- Some players may have been filtered out due to low quality

### Jan 10 Anomaly Explained

**Jan 10 had catastrophically low quality (58.6-62.8):**
- player_daily_cache WAS updated (103 players)
- But something else went wrong
- Suggests a different data quality issue on that date
- Need separate investigation for Jan 10

### Jan 12 Also Affected

**Jan 12 characteristics:**
- player_daily_cache missing (like Jan 8)
- Only 98 feature records generated (second lowest)
- Quality 67.6-84.4 (no 90+ features)
- All "mixed" data source

**Jan 12 validates the pattern: missing daily_cache → mixed features**

---

## Verification of Root Cause

### Test 1: Check if player_daily_cache absence correlates with mixed data source

✅ **CONFIRMED**

- Jan 8: 0 daily_cache records → 100% mixed features
- Jan 12: 0 daily_cache records → 100% mixed features
- All other dates: daily_cache present → phase4_partial available

### Test 2: Check if other Phase4 tables compensate

❌ **NO**

Even though composite_factors, shot_zone_analysis, and team_defense were updated:
- Not enough features to reach 50% threshold
- player_daily_cache provides 36% of features by itself
- Losing it drops below phase4_partial threshold

### Test 3: Check quality score math

✅ **CONFIRMED**

Without daily_cache (9 features), using defaults instead:
- Old: (9 × 100 + 6 × 100 + 10 × 100) / 25 = 100 (if all phase4)
- New: (6 × 100 + 9 × 40 + 10 × 100) / 25 = 78.4

**Matches observed quality scores of 77.2-84.4 on Jan 8!**

---

## Root Cause: player_daily_cache Pipeline Failure

### What Failed

The pipeline/job/processor that populates `nba_precompute.player_daily_cache` failed on:
- January 8, 2026
- January 12, 2026

### Where to Investigate

1. **Check for Cloud Scheduler/Airflow job failures:**
   ```bash
   # Look for jobs related to daily_cache or player precompute
   gcloud scheduler jobs list --project=nba-props-platform | grep -i "daily\|cache\|precompute"

   # Check logs for Jan 7-8 and Jan 11-12
   gcloud logging read "
     resource.type=cloud_scheduler_job
     timestamp>='2026-01-07T00:00:00Z'
     timestamp<='2026-01-13T00:00:00Z'
     severity>=ERROR
   " --project=nba-props-platform --limit=100
   ```

2. **Check Cloud Functions logs:**
   ```bash
   # Look for player_daily_cache generation failures
   gcloud logging read "
     timestamp>='2026-01-07T00:00:00Z'
     timestamp<='2026-01-13T00:00:00Z'
     jsonPayload.message=~'daily_cache'
     severity>=WARNING
   " --project=nba-props-platform --limit=100
   ```

3. **Check BigQuery job history:**
   ```sql
   -- Look for failed jobs on Jan 8 and Jan 12
   SELECT
       creation_time,
       user_email,
       job_type,
       statement_type,
       error_result,
       query
   FROM `region-us-west2`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
   WHERE DATE(creation_time) IN ('2026-01-08', '2026-01-12')
     AND error_result IS NOT NULL
     AND query LIKE '%player_daily_cache%'
   ORDER BY creation_time DESC;
   ```

4. **Check the processor code:**
   ```bash
   # Find the processor that generates player_daily_cache
   grep -r "player_daily_cache" /home/naji/code/nba-stats-scraper/data_processors --include="*.py" -l

   # Check if it's registered in processor registry
   grep -i "daily.*cache" /home/naji/code/nba-stats-scraper/docs/processor-registry.yaml
   ```

---

## Why Didn't We Notice?

### Missing Monitoring

No alerts fired for:
- ❌ player_daily_cache record count = 0
- ❌ phase4_partial percentage dropped to 0%
- ❌ max feature_quality_score < 90
- ❌ BigQuery table staleness

### Graceful Degradation (Good and Bad)

The feature generation system gracefully fell back to:
- player_composite_factors (still available)
- player_shot_zone_analysis (still available)
- Phase3 fallback data
- Default values

**Good:** System didn't crash
**Bad:** Silent quality degradation went unnoticed

---

## Resolution Steps

### Immediate (P0):

1. **Investigate player_daily_cache pipeline failures on Jan 8 and Jan 12**
   - Check logs for error messages
   - Identify root cause of pipeline failure
   - Fix the underlying issue

2. **Backfill missing dates**
   - Regenerate player_daily_cache for Jan 8 and Jan 12
   - Regenerate ml_feature_store_v2 for those dates
   - Verify phase4_partial features are restored

3. **Monitor for recurrence**
   - Check if Jan 8/12 pattern repeats (weekly? specific day of week?)
   - Jan 8 = Wednesday, Jan 12 = Sunday
   - May indicate day-of-week dependent failure

### Short-term (P1):

4. **Add monitoring and alerting**
   ```sql
   -- Alert if player_daily_cache not updated in last 24 hours
   SELECT
       MAX(cache_date) as last_cache_date,
       CURRENT_DATE() as today,
       DATE_DIFF(CURRENT_DATE(), MAX(cache_date), DAY) as days_stale
   FROM `nba-props-platform.nba_precompute.player_daily_cache`
   HAVING days_stale > 1;

   -- Alert if player count drops >50% from previous day
   -- Alert if phase4_partial percentage < 30%
   -- Alert if max quality score < 90
   ```

5. **Implement retry logic**
   - Add automatic retry for failed daily_cache jobs
   - Implement exponential backoff
   - Send alerts after 3 failed retries

6. **Document dependencies**
   - Document that ml_feature_store_v2 depends on player_daily_cache
   - Create data lineage diagram
   - Add to runbook

### Long-term (P2):

7. **Reduce dependency on single table**
   - Consider if player_daily_cache features can be computed from other sources
   - Implement better fallback strategies
   - Cache player_daily_cache for 2-3 days as backup

8. **Improve observability**
   - Track phase4 percentage over time
   - Dashboard showing Phase4 table update recency
   - Data quality score trending

---

## Model Performance Recovery Plan

### Option A: Backfill and Regenerate (Recommended)

1. Fix player_daily_cache for Jan 8, 12
2. Regenerate features for Jan 8, 12
3. Regenerate predictions for Jan 8, 12
4. Model performance should naturally recover
5. No model retraining needed

**Timeline:** 1-2 days

**Pros:**
- Fixes root cause
- Restores historical data quality
- No model changes needed

**Cons:**
- Requires backfill work
- Historical predictions already graded

### Option B: Retrain on Current Distribution

1. Accept that daily_cache may be unreliable
2. Retrain models on current "mixed" feature distribution
3. Update quality expectations
4. Models adapt to new normal

**Timeline:** 1-2 weeks

**Pros:**
- Makes system more robust to daily_cache failures
- Future-proofs against similar issues

**Cons:**
- May have lower overall accuracy
- Doesn't fix root cause

---

## Additional Investigation Needed

### Question 1: Why did player_daily_cache fail on Jan 8 and Jan 12?

**Hypotheses:**
- Specific day-of-week issue (Wednesday and Sunday)
- Upstream data source unavailable (NBA API, stats provider)
- Resource contention or quota limits
- Code bug triggered on specific conditions
- Manual intervention or deployment on those dates

### Question 2: What about Jan 10 anomaly?

Jan 10 had player_daily_cache (103 records) but still had terrible quality (58.6-62.8).

**Need to investigate:**
- What was different about the daily_cache data on Jan 10?
- Were the values in daily_cache NULL or zeros?
- Did player_composite_factors have issues on Jan 10?
- Was there upstream data corruption?

### Question 3: Is this a recurring pattern?

**Check historical pattern:**
```sql
-- Check for missing dates in player_daily_cache over last 90 days
WITH all_dates AS (
    SELECT DATE_SUB(CURRENT_DATE(), INTERVAL n DAY) as check_date
    FROM UNNEST(GENERATE_ARRAY(0, 90)) as n
),
cache_dates AS (
    SELECT DISTINCT cache_date
    FROM `nba-props-platform.nba_precompute.player_daily_cache`
    WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
)
SELECT
    all_dates.check_date,
    FORMAT_DATE('%A', all_dates.check_date) as day_of_week,
    CASE WHEN cache_dates.cache_date IS NULL THEN 'MISSING' ELSE 'present' END as status
FROM all_dates
LEFT JOIN cache_dates ON all_dates.check_date = cache_dates.cache_date
WHERE cache_dates.cache_date IS NULL
ORDER BY all_dates.check_date DESC;
```

---

## Summary

**Root Cause:** `nba_precompute.player_daily_cache` table was not updated on Jan 8 and Jan 12, 2026

**Impact:** Features lost 36% of Phase4 data, dropped below 50% threshold, fell back to "mixed" instead of "phase4_partial"

**Evidence:**
- player_daily_cache: 0 records on Jan 8, 0 records on Jan 12
- Other Phase4 tables: Updated normally
- Feature quality: Dropped from 97 → 77-84 on Jan 8
- Data source: 100% "mixed" on Jan 8 and Jan 12

**Next Steps:**
1. Find and fix the player_daily_cache pipeline failure
2. Backfill Jan 8 and Jan 12
3. Add monitoring for Phase4 table updates
4. Investigate Jan 10 anomaly separately

**Confidence Level:** 95% - The correlation is clear and the math checks out
