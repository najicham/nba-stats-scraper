# Recommendations & Next Steps - Post Grading Restoration

**Date:** 2026-01-25
**Status:** Pipeline Fully Restored - Ready for Next Phase
**Context:** Session 16 completed grading backfill (45.9% → 98.1%)

---

## Executive Summary

The grading backfill was successful - your pipeline is now operating at peak capacity with 98.1% grading coverage. However, during the work, we identified several opportunities for further improvement and some known issues that could be addressed.

**Priority Breakdown:**
- 🔴 **P0 (Critical):** 1 item - Duplicate predictions
- 🟡 **P1 (High):** 2 items - Data completeness, validation alignment
- 🟢 **P2 (Medium):** 3 items - Quality improvements
- ⚪ **P3 (Low):** 4 items - Nice-to-have polish

**Estimated Total Effort:** 4-6 hours for all P0-P1 items

---

## 🔴 Priority 0: Critical Issues

### 1. Duplicate Prediction Records Investigation & Cleanup

**Problem:** 6,473 duplicate prediction records found in recent dates (per handoff docs)

**Evidence:**
```
| Date       | Total Rows | Unique Players | Duplicates |
|------------|------------|----------------|------------|
| 2026-01-22 |        609 |             88 |        521 |
| 2026-01-23 |      5,193 |             85 |      5,108 |
| 2026-01-24 |        486 |             65 |        421 |
```

**Impact:**
- Inflated row counts in analytics
- Potential double-counting in metrics
- Wasted storage
- Grading may process same prediction twice

**Root Cause (Hypothesis):**
Prediction processor ran twice without deduplication:
- First batch: 2026-01-23 22:48:24
- Second batch: 2026-01-24 12:18:57

**Recommended Actions:**

**Step 1: Investigate (15 min)**
```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Check current duplicate count
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as total,
  COUNT(DISTINCT CONCAT(player_lookup, '|', game_id, '|', system_id)) as unique,
  COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup, '|', game_id, '|', system_id)) as duplicates
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date >= '2026-01-20'
GROUP BY game_date
HAVING duplicates > 0
ORDER BY game_date DESC
"
```

**Step 2: Identify Pattern (10 min)**
```sql
-- Find which systems have duplicates
SELECT
  system_id,
  COUNT(*) as total,
  COUNT(DISTINCT CONCAT(player_lookup, '|', game_id, '|', game_date)) as unique
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= '2026-01-20'
GROUP BY system_id
HAVING total != unique
```

**Step 3: Cleanup Options**

**Option A: Mark duplicates as inactive (RECOMMENDED - Safe)**
```sql
-- Mark duplicates as inactive (keeping newest)
UPDATE `nba-props-platform.nba_predictions.player_prop_predictions`
SET is_active = FALSE
WHERE CONCAT(player_lookup, '|', game_id, '|', system_id, '|', game_date) IN (
  SELECT CONCAT(player_lookup, '|', game_id, '|', system_id, '|', game_date)
  FROM (
    SELECT
      player_lookup,
      game_id,
      system_id,
      game_date,
      created_at,
      ROW_NUMBER() OVER (
        PARTITION BY player_lookup, game_id, system_id, game_date
        ORDER BY created_at DESC
      ) as rn
    FROM `nba-props-platform.nba_predictions.player_prop_predictions`
    WHERE game_date >= '2026-01-20'
  )
  WHERE rn > 1
)
```

**Option B: Create deduplicated view (Non-destructive)**
```sql
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.player_prop_predictions_clean` AS
SELECT * FROM (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY player_lookup, game_id, system_id, game_date
      ORDER BY created_at DESC
    ) as rn
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
)
WHERE rn = 1
```

**Step 4: Prevent Future Duplicates**
- Review prediction processor code for deduplication logic
- Add UNIQUE constraint or check before insert
- Location: `services/prediction_worker/` or prediction coordinator

**Estimated Time:** 45 minutes
**Priority:** 🔴 P0 - Should do soon
**Risk:** Low if using Option A (just marks inactive)

---

## 🟡 Priority 1: High Value Improvements

### 2. Complete BDL Boxscore Gaps (14 Dates)

**Current Status:** 96.2% coverage (614/638 games)
**Target:** >98% coverage

**Missing Games by Date:**

| Date | Missing | Priority | Command |
|------|---------|----------|---------|
| 2026-01-15 | 3 | HIGH | `python bin/backfill/bdl_boxscores.py --date 2026-01-15` |
| 2026-01-14 | 2 | HIGH | `python bin/backfill/bdl_boxscores.py --date 2026-01-14` |
| 2026-01-13 | 2 | HIGH | `python bin/backfill/bdl_boxscores.py --date 2026-01-13` |
| 2026-01-12 | 2 | HIGH | `python bin/backfill/bdl_boxscores.py --date 2026-01-12` |
| 2026-01-07 | 2 | MEDIUM | `python bin/backfill/bdl_boxscores.py --date 2026-01-07` |
| 2026-01-05 | 2 | MEDIUM | `python bin/backfill/bdl_boxscores.py --date 2026-01-05` |
| 2026-01-03 | 2 | LOW | `python bin/backfill/bdl_boxscores.py --date 2026-01-03` |
| 2026-01-02 | 2 | LOW | `python bin/backfill/bdl_boxscores.py --date 2026-01-02` |
| 2026-01-01 | 2 | LOW | `python bin/backfill/bdl_boxscores.py --date 2026-01-01` |
| 2026-01-17 | 1 | LOW | `python bin/backfill/bdl_boxscores.py --date 2026-01-17` |
| 2026-01-16 | 1 | LOW | `python bin/backfill/bdl_boxscores.py --date 2026-01-16` |
| 2026-01-08 | 1 | LOW | `python bin/backfill/bdl_boxscores.py --date 2026-01-08` |
| 2026-01-06 | 1 | LOW | `python bin/backfill/bdl_boxscores.py --date 2026-01-06` |
| 2026-01-24 | 1 | SKIP | GSW@MIN postponed (rescheduled to Jan 25) |

**Impact:**
- Analytics Phase 3 is already at 100%, so this is cosmetic
- Would clean up BDL coverage for completeness
- May help with future analytics queries

**Recommended Approach:**

**Quick Win - High Priority Dates Only (15 min):**
```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Process 4 high-priority dates (9 games)
for date in 2026-01-15 2026-01-14 2026-01-13 2026-01-12; do
  echo "Processing $date..."
  python bin/backfill/bdl_boxscores.py --date $date
done

# Verify improvement
python bin/validation/daily_data_completeness.py --days 30
```

**Full Cleanup - All Dates (30 min):**
```bash
# Process all 13 dates (skip Jan 24 - postponed game)
for date in 2026-01-17 2026-01-16 2026-01-15 2026-01-14 2026-01-13 2026-01-12 \
            2026-01-08 2026-01-07 2026-01-06 2026-01-05 2026-01-03 2026-01-02 2026-01-01; do
  echo "Processing $date..."
  python bin/backfill/bdl_boxscores.py --date $date
  sleep 2  # Rate limiting
done
```

**Estimated Time:** 15-30 minutes
**Priority:** 🟡 P1 - High value, low effort
**Risk:** Very low - read-only backfill

---

### 3. Align Validation Script with Processor Logic

**Problem:** `bin/validation/daily_data_completeness.py` shows different coverage numbers than actual grading coverage.

**Evidence:**
- Validation script reports lower grading percentages
- Uses different filters than grading processor
- Confusing for monitoring and reporting

**Root Cause:**
Validation script may not filter predictions the same way as the grading processor:

**Grading Processor Filters:**
```sql
WHERE is_active = TRUE
  AND current_points_line IS NOT NULL
  AND current_points_line != 20.0
  AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
  AND invalidation_reason IS NULL
```

**Recommended Actions:**

**Step 1: Compare Logic (10 min)**
```bash
# Read validation script
cat bin/validation/daily_data_completeness.py | grep -A 20 "def.*gradable"

# Compare with processor
cat data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py | grep -A 20 "WHERE game_date"
```

**Step 2: Update Validation Script (20 min)**
- Align filters to match grading processor exactly
- Add comments explaining each filter
- Test on recent dates to verify alignment

**Step 3: Add Ungradable Category (10 min)**
- Report "ungradable" predictions separately (no betting lines)
- Makes it clear why some aren't graded
- Reduces confusion

**Example Output (After Fix):**
```
Date         Gradable  Graded  Coverage  Ungradable  Notes
------------------------------------------------------------
2026-01-20        457     407    89.1%          25  25 players no game data
2025-11-05          0       0     N/A          381  No betting lines
```

**Estimated Time:** 40 minutes
**Priority:** 🟡 P1 - High value for ongoing monitoring
**Risk:** Low - script update only

---

## 🟢 Priority 2: Medium Value Improvements

### 4. Fix `prediction_correct` NULL Edge Cases

**Problem:** Some graded predictions have `prediction_correct = NULL` instead of TRUE/FALSE

**Evidence:**
- Random sampling found 3/10 predictions with NULL (30%)
- MAE and bias calculations are unaffected (good)
- Likely occurs in PUSH scenarios or edge cases

**Impact:**
- LOW - Core metrics (MAE, bias) are accurate
- Win rate calculations may be slightly affected
- Analytics queries might need NULL handling

**Recommended Investigation:**

**Step 1: Identify Pattern (15 min)**
```sql
-- Find common characteristics of NULL predictions
SELECT
  recommendation,
  actual_points,
  line_value,
  CASE
    WHEN actual_points = line_value THEN 'PUSH'
    WHEN actual_points > line_value THEN 'OVER'
    WHEN actual_points < line_value THEN 'UNDER'
  END as actual_result,
  COUNT(*) as count
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2025-12-01'
  AND prediction_correct IS NULL
  AND is_voided = FALSE
GROUP BY recommendation, actual_points, line_value
ORDER BY count DESC
LIMIT 20
```

**Step 2: Fix Logic (30 min)**
- Update recommendation logic in processor
- Handle PUSH scenarios explicitly
- Location: `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`

**Step 3: Backfill Fixed Values (15 min)**
```sql
-- Update NULL values with correct calculation
UPDATE `nba-props-platform.nba_predictions.prediction_accuracy`
SET prediction_correct = CASE
  WHEN recommendation = 'OVER' AND actual_points > line_value THEN TRUE
  WHEN recommendation = 'UNDER' AND actual_points < line_value THEN TRUE
  WHEN recommendation = 'PUSH' AND actual_points = line_value THEN TRUE
  ELSE FALSE
END
WHERE prediction_correct IS NULL
  AND is_voided = FALSE
```

**Estimated Time:** 1 hour
**Priority:** 🟢 P2 - Low priority, good for completeness
**Risk:** Low - clear logic fix

---

### 5. Feature Completeness Deep Dive

**Status:** Confirmed that `player_daily_cache` exists with 76 feature columns, but detailed completeness check pending.

**What to Check:**
- Do all predictions have corresponding L0 features?
- What's the quality distribution? (HIGH/MEDIUM/LOW)
- Are there any missing feature windows?

**Recommended Actions:**

**Step 1: Feature Coverage Check (10 min)**
```sql
SELECT
  COUNT(DISTINCT p.player_lookup) as players_with_predictions,
  COUNT(DISTINCT f.player_lookup) as players_with_features,
  COUNT(DISTINCT p.player_lookup) - COUNT(DISTINCT f.player_lookup) as missing
FROM (
  SELECT DISTINCT player_lookup, game_date
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE game_date = '2026-01-20'
    AND is_active = TRUE
) p
LEFT JOIN `nba-props-platform.nba_precompute.player_daily_cache` f
  ON p.player_lookup = f.player_lookup
  AND p.game_date = f.cache_date
```

**Step 2: Quality Distribution (5 min)**
```sql
SELECT
  CASE
    WHEN completeness_percentage >= 90 THEN 'HIGH (>=90%)'
    WHEN completeness_percentage >= 70 THEN 'MEDIUM (70-89%)'
    WHEN completeness_percentage >= 50 THEN 'LOW (50-69%)'
    ELSE 'POOR (<50%)'
  END as quality_tier,
  COUNT(*) as count,
  ROUND(AVG(l5_completeness_pct), 1) as avg_l5,
  ROUND(AVG(l10_completeness_pct), 1) as avg_l10
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date BETWEEN '2026-01-15' AND '2026-01-20'
GROUP BY quality_tier
```

**Estimated Time:** 15 minutes
**Priority:** 🟢 P2 - Informational, good to know
**Risk:** None - read-only queries

---

### 6. Add Monitoring for Grading Coverage

**Problem:** No automated alerts if grading coverage drops below threshold

**Recommended Solution:**

**Step 1: Create Daily Grading Alert (30 min)**

Create: `bin/alerts/grading_coverage_check.py`
```python
"""
Daily Grading Coverage Check

Alerts if yesterday's grading coverage is below 90%
"""

from google.cloud import bigquery
from datetime import date, timedelta
import sys

def check_grading_coverage():
    client = bigquery.Client(project='nba-props-platform')
    yesterday = date.today() - timedelta(days=1)

    query = f"""
    WITH gradable AS (
      SELECT COUNT(*) as n
      FROM `nba-props-platform.nba_predictions.player_prop_predictions`
      WHERE game_date = '{yesterday}'
        AND is_active = TRUE
        AND current_points_line IS NOT NULL
        AND current_points_line != 20.0
    ),
    graded AS (
      SELECT COUNT(*) as n
      FROM `nba-props-platform.nba_predictions.prediction_accuracy`
      WHERE game_date = '{yesterday}'
    )
    SELECT
      (SELECT n FROM gradable) as gradable,
      (SELECT n FROM graded) as graded,
      ROUND(100.0 * (SELECT n FROM graded) / NULLIF((SELECT n FROM gradable), 0), 1) as coverage_pct
    """

    result = list(client.query(query).result())[0]

    if result.coverage_pct < 90:
        print(f"⚠️  ALERT: Grading coverage for {yesterday} is {result.coverage_pct}%")
        print(f"   Gradable: {result.gradable}, Graded: {result.graded}")
        sys.exit(1)
    else:
        print(f"✅ Grading coverage for {yesterday}: {result.coverage_pct}%")
        sys.exit(0)

if __name__ == '__main__':
    check_grading_coverage()
```

**Step 2: Add to Daily Health Email (10 min)**
- Update `bin/alerts/daily_summary/main.py`
- Add grading coverage to daily summary
- Alert if below 90%

**Step 3: Cloud Scheduler (10 min)**
```bash
# Run daily at 8 AM ET (after grading completes at 6 AM)
gcloud scheduler jobs create http grading-coverage-check \
  --schedule="0 8 * * *" \
  --time-zone="America/New_York" \
  --uri="https://us-central1-nba-props-platform.cloudfunctions.net/grading-coverage-check" \
  --http-method=GET
```

**Estimated Time:** 50 minutes
**Priority:** 🟢 P2 - Proactive monitoring
**Risk:** Low - alerting only

---

## ⚪ Priority 3: Nice-to-Have Polish

### 7. Document Ungradable Predictions Policy

**Action:** Update validation docs to explain Nov 4-18 ungradable predictions
- These are "incomplete predictions by design"
- 3,189 predictions with no betting lines
- Properly excluded from all metrics
- No action needed

**Location:** `docs/00-orchestration/troubleshooting.md`

**Estimated Time:** 10 minutes
**Priority:** ⚪ P3 - Documentation

---

### 8. Create Grading Coverage Dashboard

**Idea:** BigQuery view for easy monitoring

```sql
CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.grading_coverage_daily` AS
WITH predictions AS (
  SELECT
    game_date,
    COUNT(*) as total_predictions,
    COUNTIF(current_points_line IS NOT NULL AND current_points_line != 20.0
            AND is_active = TRUE) as gradable_predictions
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
  GROUP BY game_date
),
grading AS (
  SELECT
    game_date,
    COUNT(*) as graded_count
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
  GROUP BY game_date
)
SELECT
  p.game_date,
  p.total_predictions,
  p.gradable_predictions,
  g.graded_count,
  ROUND(100.0 * g.graded_count / NULLIF(p.gradable_predictions, 0), 1) as coverage_pct,
  CASE
    WHEN ROUND(100.0 * g.graded_count / NULLIF(p.gradable_predictions, 0), 1) >= 95 THEN 'EXCELLENT'
    WHEN ROUND(100.0 * g.graded_count / NULLIF(p.gradable_predictions, 0), 1) >= 90 THEN 'GOOD'
    WHEN ROUND(100.0 * g.graded_count / NULLIF(p.gradable_predictions, 0), 1) >= 70 THEN 'ACCEPTABLE'
    ELSE 'POOR'
  END as status
FROM predictions p
LEFT JOIN grading g ON p.game_date = g.game_date
ORDER BY p.game_date DESC
```

**Estimated Time:** 15 minutes
**Priority:** ⚪ P3 - Nice to have

---

### 9. Weekly ML Adjustment Updates

**Current:** ML adjustments computed once (2026-01-24)
**Recommended:** Update weekly to keep current

**Automation:**
```bash
# Add to cron or Cloud Scheduler
# Run every Sunday at 6 AM ET
0 6 * * 0 cd /home/naji/code/nba-stats-scraper && \
  source .venv/bin/activate && \
  python backfill_jobs/ml_feedback/scoring_tier_backfill.py --as-of-date $(date +%Y-%m-%d)
```

**Estimated Time:** 10 minutes setup
**Priority:** ⚪ P3 - Maintenance

---

### 10. Comprehensive Health Check Script

**Create:** `bin/validation/comprehensive_health.py`

Single command to check entire pipeline:
- Grading coverage (last 7 days)
- System performance updates
- GCS export freshness
- ML adjustment recency
- Feature availability
- Duplicate prediction detection

**Estimated Time:** 1 hour
**Priority:** ⚪ P3 - Tooling improvement

---

## 📊 Recommended Execution Plan

### Option A: Quick Wins (1-2 hours)
Focus on highest value, lowest effort:
1. ✅ Investigate duplicate predictions (45 min)
2. ✅ Fill BDL gaps - high priority dates only (15 min)
3. ✅ Feature completeness check (15 min)
4. ✅ Add grading coverage to daily email (10 min)

**Total:** ~1.5 hours
**Impact:** HIGH - Addresses data quality issues

---

### Option B: Complete P0-P1 (4-6 hours)
Address all critical and high priority items:
1. ✅ Duplicate predictions - full cleanup (45 min)
2. ✅ Fill all BDL gaps (30 min)
3. ✅ Align validation script (40 min)
4. ✅ Feature completeness deep dive (15 min)
5. ✅ Add grading monitoring (50 min)
6. ✅ Fix prediction_correct NULLs (1 hour)

**Total:** ~4 hours
**Impact:** VERY HIGH - Pipeline in excellent shape

---

### Option C: Monitoring & Maintenance Focus (2 hours)
Set up ongoing monitoring:
1. ✅ Add grading coverage check (50 min)
2. ✅ Create grading dashboard view (15 min)
3. ✅ Weekly ML adjustment automation (10 min)
4. ✅ Comprehensive health check script (1 hour)

**Total:** ~2 hours
**Impact:** MEDIUM - Better visibility going forward

---

## 🔍 Immediate Health Check (Recommended First Step)

Before diving into improvements, verify current state:

```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# 1. Check grading for last 3 days
python bin/validation/daily_data_completeness.py --days 3

# 2. Check for duplicate predictions
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  COUNT(DISTINCT CONCAT(player_lookup, '|', game_id, '|', system_id)) as unique
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
"

# 3. Verify GCS exports
gsutil ls -l gs://nba-props-platform-api/v1/results/latest.json
gsutil ls -l gs://nba-props-platform-api/v1/systems/performance.json

# 4. Check ML adjustments
bq query --use_legacy_sql=false "
SELECT as_of_date, COUNT(*) as tiers
FROM \`nba-props-platform.nba_predictions.scoring_tier_adjustments\`
GROUP BY as_of_date
ORDER BY as_of_date DESC
LIMIT 5
"
```

**Expected Results:**
- ✅ Grading: >90% for recent days
- ✅ Duplicates: Should be minimal or none
- ✅ Exports: Updated within last 24 hours
- ✅ ML: 2026-01-24 with 4 tiers

---

## 📝 Decision Matrix

| Task | Effort | Impact | Risk | Recommended? |
|------|--------|--------|------|--------------|
| Duplicate Predictions | Medium | High | Low | ✅ **YES** |
| BDL Gaps (High Priority) | Low | Medium | Very Low | ✅ **YES** |
| Validation Alignment | Medium | High | Low | ✅ **YES** |
| Feature Completeness | Low | Low | None | 🟡 Optional |
| Fix NULL Correctness | High | Low | Low | 🟡 Optional |
| Grading Monitoring | Medium | Medium | Low | ✅ **YES** |
| Documentation Updates | Low | Low | None | 🟡 Optional |
| Dashboard View | Low | Low | None | 🟡 Optional |
| Weekly ML Updates | Low | Medium | Low | 🟡 Optional |
| Health Check Script | High | Medium | None | 🟡 Optional |

---

## 🎯 My Top Recommendation

**Start with this sequence (2 hours total):**

1. **Run health check** (5 min) - Verify current state
2. **Investigate duplicates** (30 min) - Understand scope
3. **Clean up duplicates** (15 min) - Mark inactive or create view
4. **Fill BDL gaps** (15 min) - High priority dates
5. **Add grading to daily email** (10 min) - Ongoing monitoring
6. **Feature completeness check** (15 min) - Confirm all good
7. **Document findings** (10 min) - Update notes

This addresses the most important data quality issue (duplicates), fills key gaps, and sets up monitoring for the future.

Then you can decide if you want to continue with validation alignment and other improvements, or call it a win and move on to other priorities.

---

## 📞 Questions to Consider

Before starting next work:

1. **Are duplicate predictions causing any user-facing issues?**
   - If yes → P0, do immediately
   - If no → Can wait for next session

2. **Is the website performing well with current exports?**
   - If yes → Monitoring is most important
   - If issues → Check export freshness

3. **How critical is the BDL gap filling?**
   - Analytics already 100% → Low urgency
   - Want complete data → Do the quick wins

4. **What's your next major project?**
   - If moving to new work → Focus on monitoring/maintenance
   - If continuing improvements → Do full P0-P1 cleanup

---

## 📚 References

**Documentation:**
- Grading Completion Report: `docs/08-projects/current/season-validation-plan/COMPLETION-REPORT.md`
- Validation Results: `docs/08-projects/current/season-validation-plan/VALIDATION-RESULTS.md`
- Session 16 Summary: `docs/09-handoff/2026-01-25-SESSION-16-GRADING-COMPLETE.md`

**Key Scripts:**
- Grading backfill: `backfill_jobs/grading/prediction_accuracy/`
- BDL backfill: `bin/backfill/bdl_boxscores.py`
- Validation: `bin/validation/daily_data_completeness.py`
- ML feedback: `backfill_jobs/ml_feedback/scoring_tier_backfill.py`

**BigQuery Tables:**
- Predictions: `nba_predictions.player_prop_predictions`
- Grading: `nba_predictions.prediction_accuracy`
- System Performance: `nba_predictions.system_daily_performance`
- ML Adjustments: `nba_predictions.scoring_tier_adjustments`

---

**Status:** Ready for next phase
**Recommendation:** Start with health check + duplicate cleanup
**Total Available Work:** 4-6 hours for full P0-P1 completion

**Let me know which approach you'd like to take!**
