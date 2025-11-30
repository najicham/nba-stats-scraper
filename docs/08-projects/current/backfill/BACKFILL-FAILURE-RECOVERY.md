# Backfill Failure Recovery Playbook

**Created:** 2025-11-29
**Purpose:** Comprehensive recovery procedures for backfill failures
**Related:** BACKFILL-MASTER-EXECUTION-GUIDE.md, BACKFILL-GAP-ANALYSIS.md

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Failure Categories](#failure-categories)
3. [Recovery Procedures](#recovery-procedures)
4. [Common Failure Scenarios](#common-failure-scenarios)
5. [Emergency Procedures](#emergency-procedures)
6. [Prevention](#prevention)

---

## 🎯 Overview {#overview}

### Failure Philosophy

**Key Principles:**
1. **Don't panic** - Backfill is fully resumable
2. **Understand first** - Diagnose before fixing
3. **Document everything** - Log what happened and how you fixed it
4. **Verify fix** - Run quality gates after recovery
5. **Learn and prevent** - Update docs to prevent recurrence

### Resumability

The backfill is designed to be resumable at any point:
- ✅ All completed dates recorded in `processor_run_history`
- ✅ Scripts automatically skip already-processed dates
- ✅ No need to restart from beginning
- ✅ Can pause and resume anytime

---

## 📊 Failure Categories {#failure-categories}

### Category 1: Script/Infrastructure Failures

**Symptoms:**
- Script crashes
- Connection timeouts
- "Command not found" errors
- Permission denied errors

**Impact:** LOW - No data corruption, just interrupted

**Recovery:** Simple - Just re-run the script

---

### Category 2: Data Availability Failures

**Symptoms:**
- "FileNotFoundError" - Source data doesn't exist
- "No data found" - Query returns empty
- "Table not found" - Upstream table missing

**Impact:** MEDIUM - Indicates missing Phase 2 data

**Recovery:** Moderate - Need to backfill upstream data first

---

### Category 3: Processing Errors

**Symptoms:**
- "Division by zero"
- "NULL value" errors
- "Invalid data type" errors
- Logic errors in processors

**Impact:** MEDIUM - Processor logic issue

**Recovery:** Moderate - May need code fix

---

### Category 4: Resource Exhaustion

**Symptoms:**
- "Query timeout"
- "Memory exceeded"
- "Rate limit exceeded"

**Impact:** LOW - Temporary resource issue

**Recovery:** Simple - Retry with delay or reduced batch size

---

### Category 5: Defensive Check Blocks

**Symptoms:**
- "DependencyError: Gap detected"
- "Upstream processor failed"
- "Completeness threshold not met"

**Impact:** MEDIUM - Indicates data quality issue

**Recovery:** Moderate - Fill gaps first, then retry

---

## 🔧 Recovery Procedures {#recovery-procedures}

### Procedure 1: Identify Failure Point

**Step 1: Check where backfill stopped**

```sql
-- Find last successful date processed
SELECT
  MAX(data_date) as last_successful_date,
  MAX(created_at) as last_successful_time
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND processor_name = 'PlayerGameSummaryProcessor'
  AND success = true
  AND data_date BETWEEN "2020-10-01" AND "2024-06-30"
```

**Step 2: Check for recent failures**

```sql
-- Find recent failures
SELECT
  data_date,
  processor_name,
  error_message,
  created_at
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND success = false
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
ORDER BY created_at DESC
LIMIT 20
```

---

### Procedure 2: Categorize the Failure

Use error message to determine category:

```bash
# Script failures
grep -i "command not found\|permission denied\|connection timeout" logfile.log

# Data availability failures
grep -i "FileNotFoundError\|No data found\|Table not found" logfile.log

# Processing errors
grep -i "division by zero\|NULL value\|invalid data" logfile.log

# Resource exhaustion
grep -i "timeout\|memory\|rate limit" logfile.log

# Defensive check blocks
grep -i "DependencyError\|Gap detected\|upstream.*failed" logfile.log
```

---

### Procedure 3: Resume Backfill

**For Script/Infrastructure Failures:**

```bash
# Simply re-run the backfill script
./bin/backfill/backfill_phase3_historical.sh

# Script will:
# 1. Query for missing dates
# 2. Skip already-completed dates
# 3. Resume from where it left off
```

**For Specific Date Failures:**

```bash
# Retry specific date
DATE="2023-11-15"

for processor in player_game_summary team_defense_game_summary team_offense_game_summary upcoming_player_game_context upcoming_team_game_context; do
  ./bin/run_backfill.sh analytics/$processor \
    --start-date=$DATE \
    --end-date=$DATE \
    --skip-downstream-trigger=true
done
```

**For Range of Dates:**

```bash
# Retry date range
START="2023-11-10"
END="2023-11-15"

./bin/backfill/backfill_phase3_historical.sh
# Will automatically process missing dates in range
```

---

### Procedure 4: Verify Recovery

After recovery, verify completion:

```sql
-- Check if date is now complete
SELECT
  processor_name,
  success,
  rows_processed,
  created_at
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND data_date = '2023-11-15'
ORDER BY created_at DESC
```

Expected: All 5 processors show `success = true`

---

## 🔥 Common Failure Scenarios {#common-failure-scenarios}

### Scenario 1: Script Crashes Mid-Backfill

**Symptom:**
```
Processing date 150/327...
Connection lost
Script terminated
```

**Diagnosis:**
- Network interruption
- SSH session timeout
- System shutdown

**Impact:** None - All completed dates saved

**Recovery:**

```bash
# Step 1: Check where it stopped
# (Use Procedure 1 above)

# Step 2: Simply re-run script
./bin/backfill/backfill_phase3_historical.sh

# Step 3: Script will resume from date 151/327
```

**Prevention:**
- Run in `tmux` or `screen` session
- Use `nohup` to survive logouts
- Monitor progress logs

---

### Scenario 2: Phase 2 Data Missing for Date

**Symptom:**
```
ERROR: FileNotFoundError: No raw data found for game_date=2023-11-15
Processing failed for 2023-11-15
```

**Diagnosis:**
```sql
-- Check if Phase 2 data exists
SELECT COUNT(*)
FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
WHERE game_date = '2023-11-15'
```

Result: `COUNT(*) = 0` → Phase 2 data missing

**Impact:** Cannot process this date until Phase 2 exists

**Recovery:**

```bash
# Step 1: Verify the date had games
bq query --use_legacy_sql=false "
SELECT game_id, game_date, home_team, away_team
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_date = '2023-11-15'
  AND game_status = 3
"

# If games exist:
# Step 2: Backfill Phase 2 for that date first
# (This depends on your Phase 2 backfill scripts)

# Step 3: After Phase 2 complete, retry Phase 3
DATE="2023-11-15"
for processor in player_game_summary team_defense_game_summary team_offense_game_summary upcoming_player_game_context upcoming_team_game_context; do
  ./bin/run_backfill.sh analytics/$processor \
    --start-date=$DATE \
    --end-date=$DATE \
    --skip-downstream-trigger=true
done
```

**Prevention:**
- Run Stage 0 quality gate before starting
- Verify Phase 2 100% complete
- Don't skip pre-backfill verification

---

### Scenario 3: Defensive Check Blocks Processing

**Symptom:**
```
⚠️ Analytics BLOCKED: Gap Detected
Missing dates in lookback window: ['2023-11-10', '2023-11-12']
DependencyError: Cannot process 2023-11-15 - upstream gaps detected
```

**Diagnosis:**
```sql
-- Check for gaps in lookback window
SELECT game_date
FROM `nba-props-platform.nba_raw.nbac_schedule`
WHERE game_status = 3
  AND game_date BETWEEN '2023-11-01' AND '2023-11-15'
  AND game_date NOT IN (
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_analytics.player_game_summary`
  )
ORDER BY game_date
```

**Impact:** Processor correctly blocking due to incomplete data

**Recovery:**

```bash
# Step 1: Fill the gaps first
for gap_date in 2023-11-10 2023-11-12; do
  echo "Filling gap: $gap_date"
  for processor in player_game_summary team_defense_game_summary team_offense_game_summary upcoming_player_game_context upcoming_team_game_context; do
    ./bin/run_backfill.sh analytics/$processor \
      --start-date=$gap_date \
      --end-date=$gap_date \
      --skip-downstream-trigger=true
  done
done

# Step 2: Now retry the blocked date
DATE="2023-11-15"
for processor in player_game_summary team_defense_game_summary team_offense_game_summary upcoming_player_game_context upcoming_team_game_context; do
  ./bin/run_backfill.sh analytics/$processor \
    --start-date=$DATE \
    --end-date=$DATE \
    --skip-downstream-trigger=true
done
```

**Prevention:**
- Process dates sequentially (prevents gaps)
- Use Stage 1 script which processes in order
- Don't skip dates manually

---

### Scenario 4: BigQuery Query Timeout

**Symptom:**
```
ERROR: Query timeout: exceeded 180 seconds
Processing failed for 2023-11-15
```

**Diagnosis:**
- Query too complex
- Too much data for date
- BigQuery temporary issue

**Impact:** Temporary - Can retry

**Recovery:**

```bash
# Step 1: Wait 30 seconds
sleep 30

# Step 2: Retry the date
DATE="2023-11-15"
for processor in player_game_summary team_defense_game_summary team_offense_game_summary upcoming_player_game_context upcoming_team_game_context; do
  ./bin/run_backfill.sh analytics/$processor \
    --start-date=$DATE \
    --end-date=$DATE \
    --skip-downstream-trigger=true
done

# If still fails after 2-3 retries:
# Step 3: Check if it's a specific processor
# Try processors individually to isolate issue
```

**Prevention:**
- Add retry logic to processors (may already exist)
- Add delays between dates (sleep 2 in script)
- Monitor BigQuery quotas

---

### Scenario 5: Multiple Processors Fail for Same Date

**Symptom:**
```
[player_game_summary] ✅ Success
[team_defense_game_summary] ❌ Failed
[team_offense_game_summary] ❌ Failed
[upcoming_player_game_context] ✅ Success
[upcoming_team_game_context] ❌ Failed
⚠️ Date 2023-11-15 had failures
```

**Diagnosis:**
```sql
-- Check which processors failed
SELECT
  processor_name,
  error_message,
  processing_decision
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND data_date = '2023-11-15'
  AND success = false
ORDER BY processor_name
```

**Impact:** Date partially complete - some data exists

**Recovery:**

```bash
# Retry ONLY the failed processors
DATE="2023-11-15"

# From diagnosis, if team_defense_game_summary failed:
./bin/run_backfill.sh analytics/team_defense_game_summary \
  --start-date=$DATE \
  --end-date=$DATE \
  --skip-downstream-trigger=true

# Repeat for other failed processors
./bin/run_backfill.sh analytics/team_offense_game_summary \
  --start-date=$DATE \
  --end-date=$DATE \
  --skip-downstream-trigger=true

./bin/run_backfill.sh analytics/upcoming_team_game_context \
  --start-date=$DATE \
  --end-date=$DATE \
  --skip-downstream-trigger=true
```

**Prevention:**
- Processors should be independent
- Investigate why some fail while others succeed
- May indicate processor-specific bug

---

### Scenario 6: Backfill Completes But Quality Gate Fails

**Symptom:**
```
✅ ALL DATES SUCCESSFUL
Backfill script completed

But quality gate shows:
phase3_dates: 635
missing_dates: 3
gate_status: ⚠️ STAGE 1 INCOMPLETE
```

**Diagnosis:**
```sql
-- Find the 3 missing dates
SELECT s.game_date
FROM `nba-props-platform.nba_raw.nbac_schedule` s
WHERE s.game_status = 3
  AND s.game_date BETWEEN "2020-10-01" AND "2024-06-30"
  AND s.game_date NOT IN (
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_analytics.player_game_summary`
  )
ORDER BY s.game_date
```

**Impact:** 3 dates were skipped or failed silently

**Recovery:**

```bash
# Step 1: Get missing dates from query above
MISSING_DATES="2022-03-15 2022-04-20 2023-01-10"

# Step 2: Process each missing date
for date in $MISSING_DATES; do
  echo "Processing missing date: $date"
  for processor in player_game_summary team_defense_game_summary team_offense_game_summary upcoming_player_game_context upcoming_team_game_context; do
    ./bin/run_backfill.sh analytics/$processor \
      --start-date=$date \
      --end-date=$date \
      --skip-downstream-trigger=true
  done
done

# Step 3: Re-run quality gate
# (Use Query #14 from BACKFILL-GAP-ANALYSIS.md)
```

**Prevention:**
- Review backfill script logs carefully
- Don't ignore partial failures
- Run quality gate immediately after backfill

---

### Scenario 7: Alert Spam Despite Backfill Mode

**Symptom:**
```
Inbox flooded with 200+ error emails
Despite skip_downstream_trigger=true
```

**Diagnosis:**
- `backfill_mode` not properly detected
- Alert suppression not working
- Critical errors bypassing suppression

**Impact:** Annoying but doesn't affect data

**Recovery:**

```bash
# Step 1: Verify backfill_mode detection
grep "backfill_mode" shared/utils/notification_system.py

# Step 2: Check if skip_downstream_trigger is being passed
# Look at logs to see if flag is set

# Step 3: If urgent, temporarily disable emails in .env
# (Not recommended - you'll be blind to real issues)
```

**Prevention:**
- Verify alert suppression before starting
- Test with small date range first
- Monitor first hour of backfill

---

## 🚨 Emergency Procedures {#emergency-procedures}

### Emergency 1: Stop Backfill Immediately

**When to use:**
- Discovered critical bug in processor
- Wrong data being written
- Need to fix code before continuing

**How to stop:**

```bash
# If running in terminal:
Ctrl+C

# If running in background:
ps aux | grep backfill_phase3
kill <PID>

# If running in tmux/screen:
tmux attach -t backfill
Ctrl+C

# If triggered via cron/scheduler:
# Disable the cron job first
```

**After stopping:**
1. Document where it stopped
2. Fix the issue (code, config, etc.)
3. Test fix with single date
4. Resume backfill

---

### Emergency 2: Rollback Corrupted Data

**When to use:**
- Realized data written incorrectly
- Need to delete and reprocess

**How to rollback:**

```sql
-- DELETE data for specific date (USE WITH CAUTION!)
DELETE FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2023-11-15';

DELETE FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
WHERE game_date = '2023-11-15';

-- (Repeat for other Phase 3 tables)

-- Also delete processor_run_history entries
DELETE FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_3_analytics'
  AND data_date = '2023-11-15';
```

**After rollback:**
1. Fix the bug that caused corruption
2. Test with single date
3. Re-run that date
4. Verify data correct

---

### Emergency 3: BigQuery Quota Exceeded

**Symptom:**
```
ERROR: Exceeded quota: concurrent queries
ERROR: Exceeded quota: daily query bytes
```

**Immediate action:**

```bash
# Stop backfill
Ctrl+C or kill process

# Wait for quota reset
# Concurrent queries: Wait 1-5 minutes
# Daily bytes: Wait until next day
```

**Recovery:**

```bash
# Add delays to script (reduce load)
# In backfill_phase3_historical.sh, change:
sleep 2  # to
sleep 10  # Longer delay between dates

# Or reduce parallelization
# Process fewer processors at once
```

---

## 🛡️ Prevention {#prevention}

### Prevention 1: Pre-Flight Checks

Always run these before starting backfill:

```bash
# 1. Verify schemas
./bin/verify_schemas.sh

# 2. Verify Phase 2 complete
# (Use Query #13 from BACKFILL-GAP-ANALYSIS.md)

# 3. Test with single date
TEST_DATE="2023-11-01"
./bin/run_backfill.sh analytics/player_game_summary \
  --start-date=$TEST_DATE \
  --end-date=$TEST_DATE \
  --skip-downstream-trigger=true

# 4. Verify test succeeded
# Check processor_run_history for TEST_DATE
```

---

### Prevention 2: Run in Stages

Don't try to backfill everything at once:

```bash
# Week 1: Test 7 days
./bin/run_backfill.sh analytics/player_game_summary \
  --start-date=2023-11-01 \
  --end-date=2023-11-07 \
  --skip-downstream-trigger=true

# Verify success, then:

# Week 2: One month
# (Process Oct 2023)

# Verify success, then:

# Week 3: One season
# (Process all 2023-24)

# And so on...
```

---

### Prevention 3: Monitor Proactively

Set up monitoring during backfill:

```bash
# Terminal 1: Run backfill
./bin/backfill/backfill_phase3_historical.sh

# Terminal 2: Monitor progress
watch -n 300 'bq query --use_legacy_sql=false "Query #5 from GAP-ANALYSIS"'

# Terminal 3: Monitor failures
watch -n 300 'bq query --use_legacy_sql=false "Query #9 from GAP-ANALYSIS"'
```

---

### Prevention 4: Document Everything

Keep a log of what you're doing:

```bash
# Start log
cat > backfill_execution_log.md <<EOF
# Backfill Execution Log
Started: $(date)
By: $(whoami)

## Actions Taken
$(date): Started Stage 1 Phase 3 backfill
$(date): Processed 50/327 dates
$(date): Encountered error on 2023-11-15 - investigating
$(date): Fixed issue, resuming
EOF

# Update log throughout execution
echo "$(date): Completed 100/327 dates" >> backfill_execution_log.md
```

---

## 📞 Escalation

**If you can't resolve within 2 hours:**

1. **Document the issue:**
   - Error messages
   - What you tried
   - Current state

2. **Check documentation:**
   - BACKFILL-MASTER-EXECUTION-GUIDE.md
   - BACKFILL-GAP-ANALYSIS.md
   - This playbook

3. **Search codebase:**
   - Look for similar errors in `docs/`
   - Check processor code
   - Review git history

4. **Safe to pause:**
   - Backfill is resumable
   - No harm in stopping to investigate
   - Better to understand than push forward blindly

---

## 🎯 Quick Reference

### Resume After Any Failure

```bash
# Just re-run the script - it will resume automatically
./bin/backfill/backfill_phase3_historical.sh
```

### Check Current Status

```sql
-- Use Query #5 from BACKFILL-GAP-ANALYSIS.md
-- Shows: total_dates, completed_dates, remaining, pct_complete
```

### Find Failed Dates

```sql
-- Use Query #9 from BACKFILL-GAP-ANALYSIS.md
-- Shows: All failed dates that need retry
```

### Retry Specific Date

```bash
DATE="2023-11-15"
for processor in player_game_summary team_defense_game_summary team_offense_game_summary upcoming_player_game_context upcoming_team_game_context; do
  ./bin/run_backfill.sh analytics/$processor \
    --start-date=$DATE \
    --end-date=$DATE \
    --skip-downstream-trigger=true
done
```

---

**Document Version:** 1.0
**Last Updated:** 2025-11-29
**Related Docs:**
- BACKFILL-MASTER-EXECUTION-GUIDE.md
- BACKFILL-GAP-ANALYSIS.md
- BACKFILL-VALIDATION-CHECKLIST.md
