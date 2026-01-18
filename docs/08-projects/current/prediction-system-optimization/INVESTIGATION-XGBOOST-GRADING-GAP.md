# Investigation: XGBoost V1 Grading Gap

**Created:** 2026-01-18
**Investigated:** 2026-01-18 (Same day)
**Status:** ✅ RESOLVED
**Priority:** ~~HIGH~~ N/A (No longer an issue)
**Time Spent:** 2 hours (codebase exploration)

---

## ✅ RESOLUTION SUMMARY

**Root Cause Identified:** NOT A BUG - Intentional system architecture changes

**Timeline of Events:**
1. **Jan 8, 2026** - XGBoost V1 replaced with CatBoost V8 (commit 87d2038c)
2. **Jan 11-16** - NO xgboost_v1 predictions generated (system didn't exist)
3. **Jan 17, 2026** - Both XGBoost V1 and CatBoost V8 restored concurrently (commit 289bbb7f)
4. **Jan 18, 2026** - New XGBoost V1 V2 model deployed (3.726 MAE validation)

**Current Status (2026-01-18):**
- ✅ XGBoost V1 V2: 280 predictions generated on Jan 18
- ✅ CatBoost V8: 293 predictions generated on Jan 17-18
- ✅ All 6 systems: Healthy and generating predictions
- ⏳ Grading: Last ran Jan 17 (Jan 18 games not complete yet)

**Verdict:** No grading bug exists. XGBoost V1 predictions will be graded tomorrow (Jan 19) once Jan 18 games complete. The "grading gap" was simply a period when XGBoost V1 didn't exist in the system.

**Evidence:**
```
Predictions (Jan 15-18):
- xgboost_v1: 280 (first: Jan 18, last: Jan 18) ← NEW model!
- catboost_v8: 293 (first: Jan 17, last: Jan 18)
- ensemble_v1: 1,284 predictions
- All 6 systems active

Grading (Jan 10-17):
- catboost_v8: 335 graded (last: Jan 17) ✅
- ensemble_v1: 439 graded (last: Jan 17) ✅
- xgboost_v1: 96 graded (last: Jan 10) ← Normal, system was removed Jan 8-16
```

**No Action Needed:** Grading processor has no system-specific filtering. It will grade xgboost_v1 predictions starting Jan 19 when games complete.

---

## 🎯 Original Problem Statement (Now Resolved)

**XGBoost V1 predictions are not being graded since 2026-01-10** (8 days ago), preventing validation of the newly deployed XGBoost V1 V2 model's production performance.

**UPDATE:** This was due to XGBoost V1 being removed from the system (Jan 8-16), not a grading bug.

---

## 📊 Evidence

### Grading History
- **Last Graded:** 2026-01-10
- **Historical Grading:** 6,219 predictions over 31 dates
- **Historical MAE:** 4.47 points (old XGBoost V1)
- **Date Range:** 2025-11-19 to 2026-01-10

### Recent Grading Status (Other Systems)
| Date | Systems Graded | XGBoost V1 Graded? |
|------|----------------|--------------------|
| 2026-01-17 | 4 systems (17 total) | ❌ NO |
| 2026-01-16 | 0 systems | ❌ NO |
| 2026-01-15 | 4 systems (60 total) | ❌ NO |
| 2026-01-14 | 4 systems (201 total) | ❌ NO |
| 2026-01-13 | 5 systems (252 total) | ❌ NO |
| 2026-01-10 | XGBoost included (95) | ✅ YES (last time) |

### Predictions Still Being Generated
- **2026-01-18:** 280 predictions generated ✅
- **System:** Active and healthy
- **Quality:** Zero placeholders, high confidence (0.77)

**Conclusion:** Prediction generation works, but grading pipeline is not processing XGBoost V1.

---

## 🔍 Investigation Steps

### Step 1: Verify Other Systems Being Graded (5 mins)

**Check if problem is XGBoost-specific or system-wide:**

```sql
-- Check which systems are being graded recently
SELECT
  system_id,
  MIN(game_date) as first_graded,
  MAX(game_date) as last_graded,
  COUNT(DISTINCT game_date) as dates_graded,
  COUNT(*) as total_graded
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2026-01-10'
GROUP BY system_id
ORDER BY last_graded DESC;
```

**Expected:** Other systems should show recent grading (2026-01-17), XGBoost V1 should stop at 2026-01-10.

**If TRUE:** Problem is XGBoost-specific (most likely)
**If FALSE:** System-wide grading issue (different investigation)

---

### Step 2: Check Prediction Volume vs Grading (10 mins)

**Verify predictions exist but aren't graded:**

```sql
-- Compare predictions made vs graded for XGBoost V1
WITH predictions AS (
  SELECT
    game_date,
    COUNT(*) as predicted,
    COUNT(DISTINCT player_lookup) as predicted_players
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE system_id = 'xgboost_v1'
    AND game_date >= '2026-01-10'
  GROUP BY game_date
),
graded AS (
  SELECT
    game_date,
    COUNT(*) as graded,
    COUNT(DISTINCT player_lookup) as graded_players
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE system_id = 'xgboost_v1'
    AND game_date >= '2026-01-10'
  GROUP BY game_date
)
SELECT
  p.game_date,
  p.predicted,
  p.predicted_players,
  COALESCE(g.graded, 0) as graded,
  COALESCE(g.graded_players, 0) as graded_players,
  p.predicted - COALESCE(g.graded, 0) as grading_gap
FROM predictions p
LEFT JOIN graded g ON p.game_date = g.game_date
ORDER BY p.game_date DESC;
```

**Expected:** Large grading_gap for dates after 2026-01-10.

---

### Step 3: Check Grading Processor Code (15 mins)

**Location:** `data_processors/grading/` or similar

**Look for:**
1. System ID filtering logic
2. Hard-coded system lists
3. Recent changes to grading processor
4. Conditional logic that might exclude xgboost_v1

**Search for system_id references:**
```bash
cd /home/naji/code/nba-stats-scraper
grep -r "xgboost_v1" data_processors/grading/ --include="*.py"
grep -r "system_id" data_processors/grading/ --include="*.py" -A 5 -B 5
```

**Check for:**
- `if system_id in ['catboost_v8', 'ensemble_v1', ...]` (missing xgboost_v1)
- `if system_id != 'xgboost_v1'` (explicit exclusion)
- Recent commits that might have changed filtering

---

### Step 4: Check Grading Processor Execution Logs (15 mins)

**Check if grading processor is running:**

```bash
gcloud logging read \
  'resource.labels.service_name:"grading" AND
   timestamp>="2026-01-13T00:00:00Z"' \
  --limit=100 \
  --project nba-props-platform \
  --format=json | jq -r '.[] | "\(.timestamp): \(.textPayload // .jsonPayload.message)"' | grep -i "xgboost"
```

**Look for:**
- Mentions of xgboost_v1
- Error messages about xgboost
- Successful processing of other systems but not xgboost
- Any filtering/skipping messages

**Also check:**
```bash
# Check for general grading execution
gcloud logging read \
  'resource.labels.service_name:"grading" AND
   jsonPayload.message:"Grading complete" AND
   timestamp>="2026-01-13T00:00:00Z"' \
  --limit=20 \
  --project nba-props-platform
```

---

### Step 5: Check System ID Consistency (10 mins)

**Verify system_id is consistent across tables:**

```sql
-- Check if predictions use correct system_id
SELECT DISTINCT system_id
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= '2026-01-10'
ORDER BY system_id;

-- Check if prediction_accuracy uses same system_ids
SELECT DISTINCT system_id
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2026-01-10'
ORDER BY system_id;
```

**Expected:** Both should include 'xgboost_v1'

**If missing from prediction_accuracy:** Strong evidence of filtering issue

---

### Step 6: Check Boxscore Availability (10 mins)

**Verify actual game results exist for grading:**

```sql
-- Check if boxscores exist for recent dates
SELECT
  game_date,
  COUNT(*) as games,
  COUNT(DISTINCT player_id) as players
FROM `nba-props-platform.nba_boxscores.player_boxscores`
WHERE game_date >= '2026-01-10'
GROUP BY game_date
ORDER BY game_date DESC;
```

**Expected:** Boxscores should exist for dates 2026-01-11 through 2026-01-17 (not 01-18 yet)

**If missing:** Grading blocked by missing data (affects all systems)
**If present:** Problem is system-specific filtering

---

### Step 7: Check Prediction Table Schema (5 mins)

**Verify predictions have all required fields for grading:**

```sql
-- Sample recent XGBoost V1 predictions
SELECT *
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = 'xgboost_v1'
  AND game_date = '2026-01-17'
LIMIT 5;
```

**Check for:**
- player_lookup (for joining with boxscores)
- game_id (for joining with games)
- predicted_points (the prediction)
- line_value (prop line)
- All required fields present

---

## 🎯 Likely Root Causes (Prioritized)

### 1. System ID Filtering in Grading Processor (70% probability)
**Hypothesis:** Grading processor has hard-coded system list or conditional that excludes xgboost_v1

**Evidence Supporting:**
- Other systems being graded
- XGBoost V1 predictions generated successfully
- Clean cutoff on 2026-01-10 (suggests code change)

**How to Confirm:**
- Step 3: Check grading processor code
- Step 4: Check logs for filtering messages

**Fix:** Update grading processor to include xgboost_v1

---

### 2. Recent Code Change on 2026-01-10 (20% probability)
**Hypothesis:** Code deployment around Jan 10 introduced filtering bug

**Evidence Supporting:**
- Exact cutoff date (2026-01-10 last graded)
- Suggests intentional or accidental code change

**How to Confirm:**
- Check git history around 2026-01-10
- Review recent deployments to grading processor

```bash
cd /home/naji/code/nba-stats-scraper
git log --since="2026-01-08" --until="2026-01-12" --oneline -- data_processors/grading/
```

**Fix:** Revert breaking change or fix introduced bug

---

### 3. System ID Renamed/Changed (5% probability)
**Hypothesis:** system_id changed from 'xgboost_v1' to something else

**Evidence Against:**
- Predictions still use 'xgboost_v1'
- Would affect all xgboost predictions, not just grading

**How to Confirm:**
- Step 5: Check system_id consistency

**Fix:** Update grading processor to use new system_id

---

### 4. Grading Processor Crashed/Disabled (5% probability)
**Hypothesis:** Grading completely stopped for all systems

**Evidence Against:**
- Other systems still being graded (catboost_v8, ensemble_v1)

**How to Confirm:**
- Step 1: Verify other systems being graded recently

**Fix:** Restart/redeploy grading processor

---

## 🛠️ Recommended Investigation Order

**Total Time: ~1-2 hours**

1. **Quick Checks (20 mins):**
   - Step 1: Verify other systems graded ✅ (confirms XGBoost-specific)
   - Step 2: Check prediction vs grading gap ✅ (quantify problem)
   - Step 5: Check system_id consistency ✅ (rule out rename)

2. **Deep Dive (40 mins):**
   - Step 3: Review grading processor code (most likely culprit)
   - Step 4: Check grading logs (look for filtering/errors)
   - Step 7: Check prediction schema (ensure compatible)

3. **Supporting Evidence (20 mins):**
   - Step 6: Check boxscore availability (rule out data issue)
   - Git history review (find code changes around Jan 10)

---

## ✅ Success Criteria

**Investigation Complete When:**
- ✅ Root cause identified
- ✅ Reproduce the issue (understand why it happens)
- ✅ Fix identified (code change needed)
- ✅ Fix implemented and tested
- ✅ XGBoost V1 predictions start being graded

**Validation:**
```sql
-- After fix, should see recent grading
SELECT
  MAX(game_date) as latest_graded,
  COUNT(*) as recent_graded
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'xgboost_v1'
  AND game_date >= '2026-01-15';
```

**Expected:** latest_graded should be recent (2026-01-17 or later)

---

## 📝 Investigation Notes Template

```markdown
## Investigation Session - [Date]

### Hypothesis
[What you're investigating]

### Steps Executed
- [ ] Step 1: ...
- [ ] Step 2: ...

### Findings
- [Key observations]

### Root Cause
[Once identified]

### Fix Implemented
[Code changes made]

### Validation
[How you confirmed it works]
```

---

## 🚨 If Investigation Takes >2 Hours

**Stop and reassess:**
1. Document progress so far
2. Escalate if critical
3. Consider workarounds:
   - Use CatBoost V8 as proxy for model performance
   - Monitor prediction characteristics (confidence, range)
   - Wait for grading to naturally resume

**Workaround for Monitoring:**
While grading is broken, track these instead:
- Prediction volume (should be consistent)
- Confidence distribution (should match baseline)
- Prediction range (should be 0-60)
- Zero placeholders
- Compare predicted values to CatBoost V8 (should correlate)

---

## 🔗 Related Documentation

- **Baseline:** [day0-baseline-2026-01-18.md](track-e-e2e-testing/results/day0-baseline-2026-01-18.md)
- **Monitoring Queries:** [daily-monitoring-queries.sql](track-a-monitoring/daily-monitoring-queries.sql)
- **Progress Log:** [PROGRESS-LOG.md](PROGRESS-LOG.md)

---

## 📞 Escalation

**Escalate if:**
- Root cause not found in 2 hours
- Fix requires significant refactoring
- Affects multiple systems
- Data loss or corruption suspected

**Escalation Path:**
1. Document investigation progress
2. Summarize findings and blockers
3. Post in #engineering-alerts
4. Tag data engineering team lead

---

**Status:** 🔍 Ready to Investigate
**Priority:** HIGH (blocking Track A validation)
**Owner:** Next available engineer
**Created:** 2026-01-18
