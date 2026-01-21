# Session 95: Data Cleanup and Maintenance Tasks

**Date:** 2026-01-18
**Previous Session:** Session 93 (Validation of Session 92 duplicate-write fix)
**Status:** 🟡 **READY** - Cleanup and maintenance tasks
**Priority:** MEDIUM - Non-blocking cleanup and investigation

---

## Executive Summary

Session 93 successfully validated the Session 92 duplicate-write fix - **zero duplicates** in predictions since deployment. The critical accuracy table issue (190k duplicates) has been handed off to Session 94 for investigation.

This session focuses on **cleanup and maintenance tasks** that don't require immediate attention but will improve data quality and system health:

1. **Orphaned staging tables** - 50 tables from Nov 19, 2025 ready to clean
2. **Historical prediction duplicates** - 117 duplicates from before the fix (5 on Jan 11, 112 on Jan 4)
3. **Ungraded predictions** - 175 predictions from yesterday not yet graded
4. **Optional enhancements** - Phase 4 recalibration work, Slack alerts

---

## Context from Previous Sessions

### Session 92: Duplicate-Write Fix ✅
- Fixed race condition causing duplicate predictions
- Implemented Firestore-based distributed locking
- Deployed prediction-worker-00066-sm8 on Jan 17, 2026

### Session 93: Validation ✅
- **Validated fix working:** 0 duplicates in 1,993 predictions since deployment
- **Discovered new issue:** 190k duplicates in accuracy table (handed off to Session 94)
- **Identified cleanup needs:** Orphaned tables, historical duplicates, ungraded predictions

### Session 94: Accuracy Investigation (In Progress)
- Investigating 190k duplicate rows in `prediction_accuracy` table
- Separate session handling this critical issue
- **Do not work on accuracy table issues in this session**

---

## Task List

### Task 1: Clean Up Orphaned Staging Tables (30 mins)

**Background:**
Staging tables from Nov 19, 2025 were never cleaned up after consolidation completed. These tables are consuming storage and cluttering the dataset.

**What to clean:**
- 50+ staging tables matching pattern: `_staging_batch_2025_11_19_*`
- Tables from prediction-worker-00055-mlj revision
- All confirmed consolidated (predictions exist in main table)

**Commands:**

1. **List orphaned tables (verification):**
```bash
bq ls --project_id=nba-props-platform --max_results=100 nba_predictions | grep "_staging_batch_2025_11_19"
```

2. **Count orphaned tables:**
```bash
bq ls --project_id=nba-props-platform --max_results=100 nba_predictions | grep "_staging_batch_2025_11_19" | wc -l
```

3. **Check if cleanup script exists:**
```bash
ls -la ./bin/cleanup/cleanup_old_staging_tables.sh
```

4. **Dry run (safe):**
```bash
./bin/cleanup/cleanup_old_staging_tables.sh --dry-run --date=2025-11-19
```

5. **Actually delete (after verifying dry run):**
```bash
./bin/cleanup/cleanup_old_staging_tables.sh --date=2025-11-19
```

**Validation:**
```bash
# Should return 0 tables
bq ls --project_id=nba-props-platform --max_results=100 nba_predictions | grep "_staging_batch_2025_11_19" | wc -l

# Verify predictions still exist
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions_from_nov19
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2025-11-19'
"
```

**Success Criteria:**
- ✅ 50+ staging tables deleted
- ✅ No predictions lost (same count before/after)
- ✅ Storage freed up

---

### Task 2: Clean Up Historical Prediction Duplicates (30 mins)

**Background:**
Before the Session 92 fix, duplicate predictions were created on Jan 4 and Jan 11. These need to be removed for data cleanliness.

**Duplicates to clean:**
- **Jan 11, 2026:** 5 duplicate business keys
- **Jan 4, 2026:** 112 duplicate business keys
- **Total:** 117 duplicate business keys

**Investigation Commands:**

1. **Verify duplicate count:**
```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as duplicate_count
FROM (
  SELECT game_id, player_lookup, system_id, current_points_line, game_date, COUNT(*) as cnt
  FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
  WHERE game_date IN ('2026-01-04', '2026-01-11')
  GROUP BY 1,2,3,4,5
  HAVING cnt > 1
)
GROUP BY game_date
ORDER BY game_date
"
```

2. **Sample duplicates to understand pattern:**
```bash
bq query --use_legacy_sql=false "
SELECT
  game_id,
  player_lookup,
  system_id,
  current_points_line,
  COUNT(*) as duplicate_count,
  ARRAY_AGG(prediction_id ORDER BY created_at) as prediction_ids,
  ARRAY_AGG(created_at ORDER BY created_at) as created_timestamps
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2026-01-11'
GROUP BY 1,2,3,4
HAVING COUNT(*) > 1
LIMIT 10
"
```

**Deduplication Approach:**

**Option A: Keep Earliest Created** (Recommended)
```sql
-- Create temp table with IDs to delete (keeps earliest)
CREATE TEMP TABLE duplicates_to_delete AS
SELECT prediction_id
FROM (
  SELECT
    prediction_id,
    ROW_NUMBER() OVER (
      PARTITION BY game_id, player_lookup, system_id, current_points_line
      ORDER BY created_at ASC  -- Keep earliest
    ) as row_num
  FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
  WHERE game_date IN ('2026-01-04', '2026-01-11')
)
WHERE row_num > 1;

-- Delete duplicates
DELETE FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE prediction_id IN (SELECT prediction_id FROM duplicates_to_delete);
```

**Option B: Manual Review First**
If unsure, export duplicates to CSV, review manually, then delete specific prediction_ids.

**Validation:**
```bash
# Should return 0 duplicates
bq query --use_legacy_sql=false "
SELECT COUNT(*) as remaining_duplicates
FROM (
  SELECT game_id, player_lookup, system_id, current_points_line, COUNT(*) as cnt
  FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
  WHERE game_date IN ('2026-01-04', '2026-01-11')
  GROUP BY 1,2,3,4
  HAVING cnt > 1
)
"
```

**Success Criteria:**
- ✅ 0 duplicates remaining on Jan 4 and Jan 11
- ✅ Earliest predictions kept (maintain historical accuracy)
- ✅ No data loss (verify prediction count per date)

---

### Task 3: Investigate Ungraded Predictions (30-45 mins)

**Background:**
Daily validation found 175 predictions from yesterday that haven't been graded yet. This could indicate:
- Grading scheduled query delayed/failed
- Boxscore data not available yet
- Configuration issue

**Investigation Steps:**

1. **Check which date is ungraded:**
```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT system_id) as systems
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date >= CURRENT_DATE() - 2
GROUP BY game_date
ORDER BY game_date DESC
"
```

2. **Check grading table for same date:**
```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as graded_predictions,
  MAX(graded_at) as last_graded_time
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date >= CURRENT_DATE() - 2
GROUP BY game_date
ORDER BY game_date DESC
"
```

3. **Check boxscore availability:**
```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games_with_boxscores,
  COUNT(DISTINCT player_id) as players_with_boxscores
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= CURRENT_DATE() - 2
GROUP BY game_date
ORDER BY game_date DESC
"
```

4. **Check scheduled query status:**
```bash
# List scheduled queries
bq ls --transfer_config --project_id=nba-props-platform

# Check grading scheduled query logs
gcloud logging read "resource.type=bigquery_resource AND
  textPayload=~'grading' AND
  timestamp>='2026-01-16T00:00:00Z'" \
  --project=nba-props-platform \
  --limit=20
```

5. **Check grading Cloud Function (if exists):**
```bash
gcloud functions list --project=nba-props-platform | grep grading

# If function exists, check logs
gcloud functions logs read grading \
  --project=nba-props-platform \
  --limit=50
```

**Possible Causes & Solutions:**

| Cause | Solution |
|-------|----------|
| Boxscores not loaded yet | Wait for Phase 2 ingestion to complete |
| Scheduled query failed | Check logs, re-run manually |
| Grading function crashed | Check function logs, redeploy |
| Time zone mismatch | Verify query runs after games complete |
| Missing data for some games | Verify which games are missing boxscores |

**Manual Grading (if needed):**
```bash
# Check if manual grading script exists
ls -la ./bin/grading/

# Run manual grading for specific date
python orchestration/cloud_functions/grading/main.py --date 2026-01-16
```

**Success Criteria:**
- ✅ Root cause identified
- ✅ Grading backlog cleared (if fixable)
- ✅ Monitoring/alerting added (if systemic issue)

---

## Optional Enhancements (If Time Permits)

### Optional 1: Add Slack Alerts for Data Quality (1-2 hours)

**Alerts to add:**
1. Duplicate detection alert (predictions table)
2. Grading failures alert
3. Validation failures alert
4. Staging table accumulation alert

**Reference:** Session 85-89 Slack alerting implementation

### Optional 2: Phase 4 Recalibration Prep (2-3 hours)

**Background:**
Some prediction systems have poor accuracy (<50%) or are overconfident. Phase 4 would add:
- Automated recalibration pipeline
- Player blacklist (LeBron 5.88%, Donovan Mitchell 10.53% accuracy)
- Variance detection for unreliable predictions

**NOTE:** Wait for Session 94 to complete before analyzing accuracy metrics (data is currently corrupted by duplicates)

### Optional 3: Documentation Updates (30 mins)

Update documentation with Session 92-93 learnings:
- Update `PERFORMANCE-ANALYSIS-GUIDE.md` with duplicate detection
- Add cleanup procedures to maintenance guide
- Document grading troubleshooting steps

---

## Validation Commands Summary

### Overall System Health Check
```bash
# Check for any duplicates in predictions (should be 0)
bq query --use_legacy_sql=false "
SELECT COUNT(*) as duplicate_count
FROM (
  SELECT game_id, player_lookup, system_id, current_points_line, COUNT(*) as cnt
  FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY 1,2,3,4
  HAVING cnt > 1
)
"

# Check staging table count
bq ls --project_id=nba-props-platform nba_predictions | grep "_staging_" | wc -l

# Check grading lag
bq query --use_legacy_sql=false "
SELECT
  DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_behind
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
"

# Check prediction volume (last 7 days)
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT system_id) as systems
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY game_date DESC
"
```

---

## Success Criteria

### Task 1: Staging Table Cleanup ✅
- [ ] 50+ orphaned staging tables deleted
- [ ] Storage freed up (~500 MB estimated)
- [ ] No data loss verified

### Task 2: Historical Duplicate Cleanup ✅
- [ ] 0 duplicates on Jan 4, 2026
- [ ] 0 duplicates on Jan 11, 2026
- [ ] Earliest predictions kept (data integrity)

### Task 3: Ungraded Predictions ✅
- [ ] Root cause identified
- [ ] Issue documented
- [ ] Fix applied (if possible) or monitoring added

### Optional Enhancements
- [ ] Slack alerts configured (if pursued)
- [ ] Documentation updated (if pursued)
- [ ] Phase 4 prep complete (wait for Session 94)

---

## Important Notes

### What NOT to Work On (Session 94 Territory)
- ❌ `prediction_accuracy` table duplicates (190k rows)
- ❌ Accuracy metric recalculation
- ❌ Grading pipeline duplicate fix
- ❌ Model performance analysis (metrics are corrupted)

### Session 94 is handling:
- Root cause of accuracy table duplicates
- Grading pipeline fix
- 190k duplicate row cleanup
- True accuracy metric calculation

**Stay in your lane!** This session is cleanup and maintenance only.

---

## Recommended Approach

### Phase 1: Safe Cleanup (1-1.5 hours)
1. Clean up orphaned staging tables (30 min)
2. Clean up historical prediction duplicates (30 min)
3. Validate both cleanups successful (15 min)

### Phase 2: Investigation (30-45 mins)
1. Investigate ungraded predictions issue
2. Document findings
3. Apply fix or add monitoring

### Phase 3: Optional Work (1-2 hours, if time)
1. Add Slack alerts for data quality
2. Update documentation
3. Prepare Phase 4 recalibration (after Session 94)

---

## Key Files

### Cleanup Scripts
- `bin/cleanup/cleanup_old_staging_tables.sh` - Staging table cleanup
- `bin/validation/daily_data_quality_check.sh` - Daily validation

### Grading Pipeline
- `orchestration/cloud_functions/grading/main.py` - Grading function
- `docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md` - Grading guide

### Related Documentation
- `docs/09-handoff/SESSION-92-COMPLETE.md` - Duplicate fix implementation
- `docs/09-handoff/SESSION-93-VALIDATION-COMPLETE.md` - Validation results
- `docs/09-handoff/SESSION-94-START-PROMPT.md` - Accuracy investigation (separate)

---

## Quick Reference

### BigQuery Tables
- `nba_predictions.player_prop_predictions` - Main predictions table
- `nba_predictions.prediction_accuracy` - Graded predictions (Session 94 territory!)
- `nba_analytics.player_game_summary` - Actual game results (boxscores)

### Staging Tables Pattern
- `nba_predictions._staging_batch_YYYY_MM_DD_*` - Temporary consolidation tables

### Business Key (for deduplication)
```
(game_id, player_lookup, system_id, current_points_line)
```

---

## Ready to Start?

1. Start with Task 1 (staging table cleanup) - safest, most straightforward
2. Move to Task 2 (historical duplicates) - well-defined scope
3. Investigate Task 3 (ungraded predictions) - may require deeper analysis
4. Optionally tackle enhancements if time permits

**Estimated Session Time:** 2-3 hours for core tasks, 4-5 hours with optional work

Good luck! 🧹

---

**Document Version:** 1.0
**Created:** 2026-01-18
**Session:** 95
**Priority:** 🟡 MEDIUM (cleanup and maintenance)
